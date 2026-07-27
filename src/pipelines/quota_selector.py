"""
HireFlow AI — Weekly Quota Selector and Confirmation Flow

Narrows the ranked list of scored jobs (from Issue 10's MatchScorer) down to
the user's weekly quota, applies filters (previous applications, expired
listings, blacklisted companies), and manages the confirmation gate.

Status lifecycle managed by this module:
    pending  →  planned  →  confirmed  →  resume_pending  →  (Issue 12 hooks in)

Safety principle: confirmation is an explicit gate.
- generate_weekly_plan() and swap_job() NEVER call trigger_resume_generation().
- Only confirm_plan() calls the resume stub.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from src.config.database import SessionLocal
from src.models.application import Application
from src.models.job import Job
from src.models.user import User

logger = logging.getLogger(__name__)

# Number of days after which a listing is considered expired.
EXPIRY_DAYS = 30


# ====================================================================== #
# Resume generation stub (placeholder for Issue 12)
# ====================================================================== #


def _current_week_monday() -> date:
    """Return the Monday of the current ISO week as a date."""
    today = datetime.utcnow().date()
    return today - timedelta(days=today.weekday())


def trigger_resume_generation(application_id: int, db: Session) -> None:
    """Stub for Issue 12 — Resume Tailoring Engine.

    Currently just updates the application status to 'resume_pending' and
    logs that this is where Issue 12 will hook in. Does NOT generate or
    return any fake resume data.

    Args:
        application_id: The ID of the confirmed application.
        db: SQLAlchemy session to use for the update.
    """
    app = db.query(Application).filter(Application.id == application_id).first()
    if app is None:
        logger.warning(
            "trigger_resume_generation called for non-existent "
            "application_id=%s. Skipping.",
            application_id,
        )
        return

    app.status = "resume_pending"
    logger.info(
        "trigger_resume_generation stub called for application_id=%s "
        "(job_id=%s, user_id=%s). "
        "Status updated to 'resume_pending'. "
        "Issue 12 (Resume Tailoring Engine) will implement "
        "actual resume generation here.",
        application_id,
        app.job_id,
        app.user_id,
    )
    db.commit()


# ====================================================================== #
# QuotaSelector
# ====================================================================== #


class QuotaSelector:
    """Selects, swaps, and confirms a weekly plan of job applications.

    Args:
        db: Optional SQLAlchemy session for testability.
            Defaults to a fresh SessionLocal().
    """

    def __init__(self, db: Optional[Session] = None) -> None:
        self.db = db or SessionLocal()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def generate_weekly_plan(self, user_id: int) -> list[dict]:
        """Generate a weekly plan for the user.

        Filters the user's already-scored applications, applies exclusion
        rules (previous applications, expired listings, blacklisted companies),
        and selects the top N where N = user.weekly_quota.

        Idempotent: if a plan already exists for the current cycle, returns
        the existing plan without re-filtering. Calling twice does NOT create
        duplicates or double-select jobs.

        Args:
            user_id: Database ID of the user.

        Returns:
            List of dicts, each with: job_id, company_name, role_title,
            match_score, skill_gaps, rank, status.

        Raises:
            ValueError: If no user exists with the given user_id.
        """
        user = self.db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise ValueError(f"User with id {user_id} not found.")

        cycle_monday = _current_week_monday()

        # ── Check for existing plan (idempotency) ────────────────── #
        existing_planned = (
            self.db.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.status == "planned",
                Application.cycle_start_date == cycle_monday,
            )
            .order_by(Application.rank)
            .all()
        )

        if existing_planned:
            logger.info(
                "Existing plan found for user_id=%s, cycle=%s. "
                "Returning %d planned applications.",
                user_id,
                cycle_monday,
                len(existing_planned),
            )
            return self._applications_to_dicts(existing_planned, self.db)

        # ── Guard: don't regenerate if plan was already processed ── #
        # If any applications exist with this cycle_start_date (regardless
        # of status), a plan was already generated for this cycle. Don't
        # regenerate — return the remaining planned ones (which may be
        # empty if all were confirmed/removed).
        existing_cycle_count = (
            self.db.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.cycle_start_date == cycle_monday,
            )
            .count()
        )

        if existing_cycle_count > 0:
            logger.info(
                "Plan for user_id=%s cycle=%s was already processed. "
                "Found %d applications for this cycle, but none in "
                "'planned' status. Returning empty plan.",
                user_id,
                cycle_monday,
                existing_cycle_count,
            )
            return []

        # ── Get scored applications pending planning (from Issue 10) ─ #
        # CRITICAL: ONLY fetch applications that are still in "pending"
        # status. Applications in "resume_pending", "confirmed",
        # "applied", or "planned" must NEVER be touched by this query.
        scored_apps = (
            self.db.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.status == "pending",
            )
            .order_by(Application.rank)
            .all()
        )

        if not scored_apps:
            logger.info(
                "No scored applications in 'pending' status found "
                "for user_id=%s. Cannot generate a plan.",
                user_id,
            )
            return []

        # ── Determine blacklisted companies ──────────────────────── #
        profile: dict = user.master_profile or {}
        blacklisted_companies: list[str] = (
            profile.get("blacklisted_companies", []) or []
        )
        blacklist_lower = {
            c.strip().lower() for c in blacklisted_companies if c.strip()
        }

        # ── Determine companies already applied to (previous cycles) #
        already_applied_companies: set[str] = self._get_already_applied_companies(
            user_id
        )

        # ── Build filter tracking (for debugging) ────────────────── #
        skipped_expired = 0
        skipped_blacklist = 0
        skipped_already_applied = 0

        # Build a lookup of job_id -> Job to avoid N+1 queries
        job_ids = [app.job_id for app in scored_apps]
        jobs_dict: dict[int, Job] = {
            job.id: job for job in self.db.query(Job).filter(Job.id.in_(job_ids)).all()
        }

        selected: list[Application] = []

        for app in scored_apps:
            if len(selected) >= user.weekly_quota:
                break

            job = jobs_dict.get(app.job_id)
            if job is None:
                continue

            # Filter a: already applied to this company
            if job.company_name.strip().lower() in already_applied_companies:
                skipped_already_applied += 1
                continue

            # Filter b: expired listing
            if self._is_expired(job):
                skipped_expired += 1
                continue

            # Filter c: blacklisted company
            if job.company_name.strip().lower() in blacklist_lower:
                skipped_blacklist += 1
                continue

            selected.append(app)

        # ── Mark selected applications as planned ────────────────── #
        for app in selected:
            app.status = "planned"
            app.cycle_start_date = cycle_monday

        self.db.commit()

        logger.info(
            "Generated weekly plan for user_id=%s: %d selected (quota=%d). "
            "Filtered: %d expired, %d blacklisted, %d already applied.",
            user_id,
            len(selected),
            user.weekly_quota,
            skipped_expired,
            skipped_blacklist,
            skipped_already_applied,
        )

        return self._applications_to_dicts(selected, self.db)

    def swap_job(self, user_id: int, remove_job_id: int, add_job_id: int) -> list[dict]:
        """Swap one planned job for another from the scored list.

        Args:
            user_id: Database ID of the user.
            remove_job_id: Job ID to remove from the plan.
            add_job_id: Job ID to add to the plan.

        Returns:
            Updated list of planned application dicts.

        Raises:
            ValueError: If remove_job_id is not in the plan, or add_job_id
                is not a valid available job, or the swap would exceed quota.
        """
        cycle_monday = _current_week_monday()

        # ── Validate remove_job_id is currently planned ──────────── #
        remove_app = (
            self.db.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.job_id == remove_job_id,
                Application.status == "planned",
                Application.cycle_start_date == cycle_monday,
            )
            .first()
        )

        if remove_app is None:
            raise ValueError(
                f"Job {remove_job_id} is not in the current weekly plan "
                f"for user {user_id}."
            )

        # ── Validate add_job_id exists and is scoreable ──────────── #
        add_app = (
            self.db.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.job_id == add_job_id,
            )
            .first()
        )

        if add_app is None:
            raise ValueError(
                f"Job {add_job_id} has not been scored for user {user_id}. "
                "Run the match scorer first."
            )

        add_job = self.db.query(Job).filter(Job.id == add_job_id).first()
        if add_job is None:
            raise ValueError(f"Job {add_job_id} not found.")

        # ── Validate add_job_id is not already planned ───────────── #
        already_planned = (
            self.db.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.job_id == add_job_id,
                Application.status == "planned",
                Application.cycle_start_date == cycle_monday,
            )
            .first()
        )

        if already_planned is not None:
            raise ValueError(
                f"Job {add_job_id} is already in the current weekly plan "
                f"for user {user_id}."
            )

        # ── Perform the swap ─────────────────────────────────────── #
        remove_app.status = "pending"
        remove_app.cycle_start_date = None

        add_app.status = "planned"
        add_app.cycle_start_date = cycle_monday

        # Re-order ranks for planned applications
        planned_apps = (
            self.db.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.status == "planned",
                Application.cycle_start_date == cycle_monday,
            )
            .order_by(Application.rank)
            .all()
        )

        # Re-assign ranks based on original match score order
        for i, app in enumerate(planned_apps):
            app.rank = i + 1

        self.db.commit()

        logger.info(
            "Swapped job %s out, job %s in for user_id=%s.",
            remove_job_id,
            add_job_id,
            user_id,
        )

        return self._applications_to_dicts(planned_apps, self.db)

    def confirm_plan(
        self,
        user_id: int,
        confirmed_job_ids: list[int],
        removed_job_ids: list[int],
    ) -> dict:
        """Confirm the weekly plan.

        This is the gate: ONLY this method calls trigger_resume_generation().
        generate_weekly_plan() and swap_job() never trigger resume generation.

        Args:
            user_id: Database ID of the user.
            confirmed_job_ids: Job IDs to confirm (must be in 'planned' status).
            removed_job_ids: Job IDs to remove from the plan.

        Returns:
            Summary dict with: confirmed_count, removed_count,
            confirmed_applications (list of dicts), note (string).

        Raises:
            ValueError: If confirmed_job_ids is empty.
            ValueError: If any confirmed_job_id is not in 'planned' status.
        """
        if not confirmed_job_ids:
            raise ValueError("confirmed_job_ids must not be empty.")

        cycle_monday = _current_week_monday()

        # ── Validate all confirmed IDs are currently planned ─────── #
        planned_apps = (
            self.db.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.status == "planned",
                Application.cycle_start_date == cycle_monday,
            )
            .all()
        )

        planned_job_ids = {app.job_id for app in planned_apps}
        unknown_ids = set(confirmed_job_ids) - planned_job_ids
        if unknown_ids:
            raise ValueError(
                f"Job IDs {sorted(unknown_ids)} are not in the current "
                f"weekly plan for user {user_id}."
            )

        # ── Find the confirmed and removed applications ──────────── #
        confirmed_apps = [
            app for app in planned_apps if app.job_id in confirmed_job_ids
        ]
        removed_apps = [app for app in planned_apps if app.job_id in removed_job_ids]

        # ── Update statuses ──────────────────────────────────────── #
        for app in confirmed_apps:
            app.status = "confirmed"
            trigger_resume_generation(app.id, self.db)

        for app in removed_apps:
            app.status = "pending"
            app.cycle_start_date = None

        # Re-rank remaining confirmed applications
        for i, app in enumerate(confirmed_apps):
            app.rank = i + 1

        # Build a jobs lookup for response data
        confirmed_job_ids_list = [app.job_id for app in confirmed_apps]
        jobs_dict: dict[int, Job] = {
            job.id: job
            for job in self.db.query(Job)
            .filter(Job.id.in_(confirmed_job_ids_list))
            .all()
        }

        confirmed_dicts = [
            {
                "job_id": app.job_id,
                "company_name": (
                    jobs_dict[app.job_id].company_name
                    if app.job_id in jobs_dict
                    else "Unknown"
                ),
                "role_title": (
                    jobs_dict[app.job_id].role_title
                    if app.job_id in jobs_dict
                    else "Unknown"
                ),
                "match_score": app.match_score,
                "skill_gaps": (json.loads(app.skill_gaps) if app.skill_gaps else []),
                "rank": app.rank,
                "status": app.status,
            }
            for app in confirmed_apps
        ]

        summary = {
            "confirmed_count": len(confirmed_apps),
            "removed_count": len(removed_apps),
            "confirmed_applications": confirmed_dicts,
            "note": (
                "Resume generation is not yet implemented (Issue 12 pending). "
                "Application status has been updated to 'resume_pending' "
                "after confirmation."
            ),
        }

        self.db.commit()

        logger.info(
            "Plan confirmed for user_id=%s: %d confirmed, %d removed.",
            user_id,
            len(confirmed_apps),
            len(removed_apps),
        )

        return summary

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _applications_to_dicts(apps: list[Application], db: Session) -> list[dict]:
        """Convert Application ORM objects to the standard response format.

        Queries jobs in a single batch to avoid N+1.
        """
        if not apps:
            return []

        job_ids = list({app.job_id for app in apps})
        jobs_dict: dict[int, Job] = {
            job.id: job for job in db.query(Job).filter(Job.id.in_(job_ids)).all()
        }

        return [
            {
                "job_id": app.job_id,
                "company_name": (
                    jobs_dict[app.job_id].company_name
                    if app.job_id in jobs_dict
                    else "Unknown"
                ),
                "role_title": (
                    jobs_dict[app.job_id].role_title
                    if app.job_id in jobs_dict
                    else "Unknown"
                ),
                "match_score": app.match_score,
                "skill_gaps": (json.loads(app.skill_gaps) if app.skill_gaps else []),
                "rank": app.rank,
                "status": app.status,
            }
            for app in apps
        ]

    def _get_already_applied_companies(self, user_id: int) -> set[str]:
        """Find company names the user has already applied to.

        Queries applications with status='applied' and returns the
        company names of their associated jobs.
        """
        results = (
            self.db.query(Job.company_name)
            .join(Application, Application.job_id == Job.id)
            .filter(
                Application.user_id == user_id,
                Application.status == "applied",
            )
            .distinct()
            .all()
        )
        return {row[0].strip().lower() for row in results if row[0]}

    @staticmethod
    def _is_expired(job: Job) -> bool:
        """Check if a job listing is expired (> EXPIRY_DAYS old).

        NULL posting_date is treated as NOT expired — we include it.
        Reasoning: excluding listings with unknown posting dates could
        wrongly hide legitimate recent listings whose scraper didn't
        capture a date. It's safer to include them with a log note.
        """
        if job.posting_date is None:
            logger.debug(
                "Job %s (%s) has NULL posting_date — including it.",
                job.id,
                job.company_name,
            )
            return False

        age = datetime.utcnow() - job.posting_date
        return age.days > EXPIRY_DAYS


# ====================================================================== #
# CLI entry point
# ====================================================================== #


def main() -> None:
    """Run the quota selector from the command line.

    Usage:
        python -m src.pipelines.quota_selector --user-id 1
        python -m src.pipelines.quota_selector --user-id 1 --dry-run
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a weekly plan for a user.",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        required=True,
        help="Database ID of the user.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan as JSON without saving to the database.",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    selector = QuotaSelector()
    plan = selector.generate_weekly_plan(args.user_id)

    if args.dry_run:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return

    print(f"Generated plan for user_id={args.user_id}: {len(plan)} jobs selected.")
    for entry in plan[:3]:
        print(
            f"  Rank {entry['rank']}: {entry['role_title']} @ {entry['company_name']} "
            f"(score={entry['match_score']}, status={entry['status']})"
        )


if __name__ == "__main__":
    main()
