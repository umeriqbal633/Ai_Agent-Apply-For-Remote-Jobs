"""SQLite helpers for storing scraped jobs."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "jobs.db"
VALID_STATUSES = {
    "pending",
    "approved",
    "skipped",
    "applied",
    "manual_required",
}


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _get_connection() -> sqlite3.Connection:
    _ensure_data_dir()
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def initialize_db() -> None:
    """Create the jobs database and table if they do not exist."""
    with _get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                company TEXT,
                location TEXT,
                url TEXT UNIQUE,
                description TEXT,
                source TEXT,
                cover_letter TEXT,
                resume_used TEXT,
                status TEXT DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'skipped', 'applied', 'manual_required')),
                skip_reason TEXT,
                disqualify_reason TEXT,
                job_id TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def job_exists(url: str) -> bool:
    """Return True when a job URL is already stored."""
    initialize_db()
    with _get_connection() as connection:
        row = connection.execute(
            "SELECT 1 FROM jobs WHERE url = ? LIMIT 1",
            (url,),
        ).fetchone()
    return row is not None


def insert_job(job_dict: dict[str, Any]) -> str | None:
    """Insert a job if its URL is not already present and return its generated job_id."""
    initialize_db()
    url = job_dict.get("url")
    if not url or job_exists(url):
        return None

    with _get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO jobs (
                title,
                company,
                location,
                url,
                description,
                source,
                cover_letter,
                resume_used,
                status,
                skip_reason,
                disqualify_reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_dict.get("title"),
                job_dict.get("company"),
                job_dict.get("location"),
                url,
                job_dict.get("description"),
                job_dict.get("source"),
                job_dict.get("cover_letter"),
                job_dict.get("resume_used"),
                job_dict.get("status", "pending"),
                job_dict.get("skip_reason"),
                job_dict.get("disqualify_reason"),
            ),
        )
        row_id = cursor.lastrowid
        generated_job_id = f"job_{row_id:04d}"
        connection.execute(
            "UPDATE jobs SET job_id = ? WHERE id = ?",
            (generated_job_id, row_id),
        )
    return generated_job_id


def get_jobs_by_status(status: str) -> list[dict[str, Any]]:
    """Return all jobs with the requested status."""
    initialize_db()
    with _get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM jobs
            WHERE status = ?
            ORDER BY created_at DESC, id DESC
            """,
            (status,),
        ).fetchall()
    return [dict(row) for row in rows]


def update_job_status(
    job_id: str,
    status: str,
    skip_reason: str | None = None,
) -> None:
    """Update a job's status and optional reason fields."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    disqualify_reason = skip_reason if status in {"skipped", "manual_required"} else None

    initialize_db()
    with _get_connection() as connection:
        connection.execute(
            """
            UPDATE jobs
            SET status = ?, skip_reason = ?, disqualify_reason = ?
            WHERE job_id = ?
            """,
            (status, skip_reason, disqualify_reason, job_id),
        )


def update_cover_letter(job_id: str, cover_letter: str) -> None:
    """Store the generated cover letter for a job."""
    initialize_db()
    with _get_connection() as connection:
        connection.execute(
            "UPDATE jobs SET cover_letter = ? WHERE job_id = ?",
            (cover_letter, job_id),
        )


def update_resume_used(job_id: str, resume_filename: str) -> None:
    """Store the resume filename selected for a job."""
    initialize_db()
    with _get_connection() as connection:
        connection.execute(
            "UPDATE jobs SET resume_used = ? WHERE job_id = ?",
            (resume_filename, job_id),
        )


def get_all_jobs() -> list[dict[str, Any]]:
    """Return all jobs ordered from newest to oldest."""
    initialize_db()
    with _get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM jobs
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_job_by_id(job_id: str) -> dict[str, Any] | None:
    """Return a single job as a plain dict."""
    initialize_db()
    with _get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM jobs WHERE job_id = ? LIMIT 1",
            (job_id,),
        ).fetchone()
    return _row_to_dict(row)


if __name__ == "__main__":
    initialize_db()
    print("DB initialized successfully")
