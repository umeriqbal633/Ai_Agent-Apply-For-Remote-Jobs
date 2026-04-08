"""Entry point for the job_agent project."""

import argparse

from config_loader import load_profile
from db import (
    initialize_db,
    insert_job,
    job_exists,
    update_cover_letter,
    update_job_status,
    update_resume_used,
)
from job_analyzer import analyze_job
from scraper.linkedin_scraper import scrape_linkedin


def run_pipeline() -> None:
    profile = load_profile()
    initialize_db()

    scrape_warning: str | None = None
    try:
        jobs = scrape_linkedin()
    except Exception as exc:
        jobs = []
        scrape_warning = f"LinkedIn scraping failed: {exc}"

    total_scraped = len(jobs)
    inserted_count = 0
    skipped_count = 0
    ready_for_review_count = 0

    for job in jobs:
        url = str(job.get("url", "") or "").strip()
        if not url or job_exists(url):
            continue

        job_id = insert_job(job)
        if not job_id:
            continue

        inserted_count += 1
        analysis = analyze_job(job, profile)

        if not analysis.get("should_apply", False):
            update_job_status(
                job_id,
                "skipped",
                analysis.get("disqualify_reason") or "Rejected by analyzer",
            )
            skipped_count += 1
            continue

        update_cover_letter(job_id, str(analysis.get("cover_letter", "") or ""))
        update_resume_used(job_id, str(analysis.get("selected_resume", "") or ""))
        update_job_status(job_id, "pending")
        ready_for_review_count += 1

    print(f"total scraped: {total_scraped}")
    print(f"inserted: {inserted_count}")
    print(f"skipped: {skipped_count}")
    print(f"ready for review: {ready_for_review_count}")
    if scrape_warning:
        print(f"warning: {scrape_warning}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the job_agent pipeline.")
    parser.add_argument(
        "--now",
        action="store_true",
        help="Run the scrape and analysis pipeline immediately.",
    )
    args = parser.parse_args(argv)

    if not args.now:
        parser.print_help()
        return

    run_pipeline()


if __name__ == "__main__":
    main()
