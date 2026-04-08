"""Anthropic-powered job evaluation utilities."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

MODEL_NAME = "claude-sonnet-4-20250514"
SYSTEM_PROMPT = (
    "You are a strict and realistic job evaluator. "
    "Do not be optimistic. Reject jobs that are not a strong match."
)
FALLBACK_COVER_LETTER = (
    "Hello,\n\n"
    "Thank you for considering my application. I am interested in this role, "
    "but I need to review the job manually before sending a tailored cover letter.\n\n"
    "Best regards,\n"
    "Umer"
)


def _extract_text_content(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []):
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _extract_json_payload(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or start >= end:
        raise ValueError("No JSON object found in Anthropic response")

    return json.loads(candidate[start : end + 1])


def _detect_disqualifier(job: dict[str, Any], profile: dict[str, Any]) -> str | None:
    description = " ".join(
        str(job.get(field, "") or "")
        for field in ("title", "location", "description")
    ).lower()

    for phrase in profile.get("disqualify_if", []):
        if str(phrase).lower() in description:
            return str(phrase)

    region_checks = {
        "us work authorization required": [
            "work authorization in the united states",
            "must be authorized to work in the us",
            "us work authorization",
            "u.s. work authorization",
            "eligible to work in the united states",
        ],
        "eu residency required": [
            "must be based in the eu",
            "eu residents only",
            "must reside in europe",
            "only accepting applications from europe",
        ],
    }
    for reason, patterns in region_checks.items():
        if any(pattern in description for pattern in patterns):
            return reason

    return None


def _fallback_resume(profile: dict[str, Any], job: dict[str, Any]) -> str:
    resumes = profile.get("resumes", {})
    if not isinstance(resumes, dict) or not resumes:
        return ""

    description = " ".join(
        str(job.get(field, "") or "")
        for field in ("title", "description")
    ).lower()

    if any(token in description for token in ("tutor", "teaching", "gcse", "teacher")):
        return str(resumes.get("teaching", next(iter(resumes.values()))))
    if any(token in description for token in ("ai", "llm", "machine learning", "ml engineer")):
        return str(resumes.get("ai_engineer", next(iter(resumes.values()))))
    return str(resumes.get("data_science", next(iter(resumes.values()))))


def _fallback_result(
    profile: dict[str, Any],
    job: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    detected_disqualifier = _detect_disqualifier(job, profile)
    return {
        "fit_score": 1,
        "should_apply": False,
        "disqualify_reason": detected_disqualifier or reason,
        "selected_resume": _fallback_resume(profile, job),
        "resume_suggestions": [
            "Add job-specific keywords from the posting to the relevant experience section.",
            "Highlight measurable outcomes that match the role's stated requirements.",
        ],
        "cover_letter": FALLBACK_COVER_LETTER,
    }


def _normalize_result(
    result: dict[str, Any],
    profile: dict[str, Any],
    job: dict[str, Any],
) -> dict[str, Any]:
    resumes = profile.get("resumes", {})
    valid_resume_values = {
        str(value) for value in resumes.values()
    } if isinstance(resumes, dict) else set()
    selected_resume = str(result.get("selected_resume", "") or "").strip()
    if selected_resume not in valid_resume_values:
        selected_resume = _fallback_resume(profile, job)

    suggestions = result.get("resume_suggestions")
    if not isinstance(suggestions, list):
        suggestions = []
    suggestions = [str(item).strip() for item in suggestions if str(item).strip()][:3]
    if len(suggestions) < 2:
        suggestions = [
            "Add job-specific keywords from the posting to the skills summary.",
            "Quantify relevant tutoring, project, or technical outcomes more clearly.",
        ][: max(2, len(suggestions))]

    fit_score_raw = result.get("fit_score", 1)
    try:
        fit_score = max(1, min(10, int(fit_score_raw)))
    except (TypeError, ValueError):
        fit_score = 1

    disqualify_reason = result.get("disqualify_reason")
    if disqualify_reason is not None:
        disqualify_reason = str(disqualify_reason).strip() or None

    detected_disqualifier = _detect_disqualifier(job, profile)
    if detected_disqualifier:
        disqualify_reason = detected_disqualifier

    should_apply = bool(result.get("should_apply", False))
    should_apply = should_apply and fit_score >= 6 and disqualify_reason is None

    cover_letter = str(result.get("cover_letter", "") or "").strip()
    if not cover_letter:
        cover_letter = FALLBACK_COVER_LETTER

    return {
        "fit_score": fit_score,
        "should_apply": should_apply,
        "disqualify_reason": disqualify_reason,
        "selected_resume": selected_resume,
        "resume_suggestions": suggestions,
        "cover_letter": cover_letter,
    }


def analyze_job(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Analyze a job against the candidate profile and return a strict assessment."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _fallback_result(profile, job, "Missing ANTHROPIC_API_KEY in .env")

    resumes = profile.get("resumes", {})
    if not isinstance(resumes, dict) or not resumes:
        return _fallback_result(profile, job, "No resumes configured in profile")

    client = Anthropic(api_key=api_key)
    user_message = (
        "Evaluate this candidate for the job below.\n\n"
        "Candidate profile:\n"
        f"{json.dumps(profile, indent=2)}\n\n"
        "Job details:\n"
        f"Title: {job.get('title', '')}\n"
        f"Company: {job.get('company', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Source: {job.get('source', '')}\n"
        f"URL: {job.get('url', '')}\n"
        "Full description:\n"
        f"{job.get('description', '')}\n\n"
        "Rules:\n"
        "- Score fit from 1 to 10.\n"
        "- should_apply must be true only if score >= 6.\n"
        "- Reject jobs with region restrictions such as US-only or EU-only.\n"
        "- Lower the score if required experience exceeds the candidate profile.\n"
        "- Lower the score if skills do not match the role.\n"
        "- selected_resume must be exactly one of these values:\n"
        f"{json.dumps(list(resumes.values()), indent=2)}\n"
        "- resume_suggestions must contain 2 to 3 concise strings.\n"
        "- cover_letter must be tailored to the role.\n"
        "- Return only valid JSON using exactly these keys:\n"
        '{'
        '"fit_score": int, '
        '"should_apply": bool, '
        '"disqualify_reason": str or null, '
        '"selected_resume": str, '
        '"resume_suggestions": list[str], '
        '"cover_letter": str'
        '}'
    )

    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=1800,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        parsed = _extract_json_payload(_extract_text_content(response))
        return _normalize_result(parsed, profile, job)
    except Exception as exc:
        return _fallback_result(profile, job, f"Anthropic API error: {exc}")
