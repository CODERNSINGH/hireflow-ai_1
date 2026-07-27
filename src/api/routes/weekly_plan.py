"""
HireFlow AI — Weekly Plan API Routes

Endpoints for managing the weekly application plan:
- GET    /weekly-plan/{user_id}   — Fetch or generate the current plan
- POST   /weekly-plan/{user_id}/confirm — Confirm the plan (the safety gate)
- POST   /weekly-plan/{user_id}/swap    — Swap a job in the plan
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.config.database import SessionLocal
from src.models.application import Application
from src.models.user import User
from src.pipelines.quota_selector import QuotaSelector, _current_week_monday

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/weekly-plan", tags=["weekly-plan"])


# ------------------------------------------------------------------ #
# GET /weekly-plan/{user_id}  —  READ-ONLY
# ------------------------------------------------------------------ #
# The GET endpoint MUST NEVER mutate the database. It follows this
# read-first strategy:
#
#   1. Query existing "planned" applications for the current cycle.
#      If found → return them directly (no side effects).
#
#   2. If no "planned" apps exist, check whether any applications at
#      all exist with this cycle's cycle_start_date. If yes → the
#      plan was already generated and processed (all confirmed or
#      removed). Return empty (no regeneration).
#
#   3. Only if NO applications exist for this cycle at all
#      (meaning a plan has never been generated this week) →
#      invoke generate_weekly_plan() once to create it.
#
# This guarantees that a read-only GET never overwrites a later-stage
# status like "resume_pending" or "confirmed" back to "planned".
# ------------------------------------------------------------------ #


@router.get("/{user_id}")
def get_weekly_plan(
    user_id: int,
    page: Optional[int] = Query(
        None, ge=1, description="Page number for individual mode"
    ),
):
    """Fetch or generate the current weekly plan.

    READ-ONLY: never mutates the database. Returns existing "planned"
    applications for the current cycle, or an empty plan if all jobs
    have been confirmed/removed, or generates a fresh plan if none
    exists yet for this cycle.

    Respects user.confirmation_mode:
    - "batch": returns the full list at once
    - "individual": returns one job at a time, paginated via ?page=N
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found.")

        cycle_monday = _current_week_monday()

        # ── Step 1: Read-only — query existing planned apps directly ── #
        planned_apps = (
            db.query(Application)
            .filter(
                Application.user_id == user_id,
                Application.status == "planned",
                Application.cycle_start_date == cycle_monday,
            )
            .order_by(Application.rank)
            .all()
        )

        if planned_apps:
            plan = QuotaSelector._applications_to_dicts(planned_apps, db)
        else:
            # ── Step 2: Check if plan was already processed this cycle ── #
            any_cycle_app = (
                db.query(Application)
                .filter(
                    Application.user_id == user_id,
                    Application.cycle_start_date == cycle_monday,
                )
                .first()
            )

            if any_cycle_app is not None:
                # Plan was generated and fully processed (all confirmed/removed)
                logger.info(
                    "Plan for user_id=%s cycle=%s was already fully "
                    "processed. Returning empty plan (read-only).",
                    user_id,
                    cycle_monday,
                )
                plan = []
            else:
                # ── Step 3: No plan exists yet — generate one ── #
                logger.info(
                    "No plan found for user_id=%s cycle=%s. " "Generating new plan.",
                    user_id,
                    cycle_monday,
                )
                selector = QuotaSelector(db=db)
                plan = selector.generate_weekly_plan(user_id)

        if not plan:
            return {
                "user_id": user_id,
                "cycle_start": str(cycle_monday),
                "confirmation_mode": user.confirmation_mode,
                "applications": [],
                "total_count": 0,
            }

        if user.confirmation_mode == "individual":
            page = page or 1
            page_size = 1
            total = len(plan)
            total_pages = max(1, (total + page_size - 1) // page_size)

            if page > total_pages:
                raise HTTPException(
                    status_code=404,
                    detail=f"Page {page} exceeds total pages ({total_pages}).",
                )

            start = (page - 1) * page_size
            end = start + page_size
            page_items = plan[start:end]

            return {
                "user_id": user_id,
                "cycle_start": str(cycle_monday),
                "confirmation_mode": "individual",
                "applications": page_items,
                "total_count": total,
                "page": page,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_previous": page > 1,
            }

        return {
            "user_id": user_id,
            "cycle_start": str(cycle_monday),
            "confirmation_mode": "batch",
            "applications": plan,
            "total_count": len(plan),
        }

    finally:
        db.close()


# ------------------------------------------------------------------ #
# POST /weekly-plan/{user_id}/confirm
# ------------------------------------------------------------------ #


class ConfirmRequestModel(BaseModel):
    confirmed_job_ids: list[int]
    removed_job_ids: list[int] = []


@router.post("/{user_id}/confirm")
def confirm_weekly_plan(user_id: int, body: ConfirmRequestModel):
    """Confirm the weekly plan.

    This is the safety gate: only confirmed jobs trigger resume generation.
    Accepts a list of job IDs to confirm and a list to remove.
    """
    if not body.confirmed_job_ids:
        raise HTTPException(
            status_code=400,
            detail="confirmed_job_ids must not be empty. "
            "At least one job must be confirmed.",
        )

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found.")

        # Validate all confirmed_job_ids belong to the current plan
        cycle_monday = _current_week_monday()

        planned_job_ids = {
            row[0]
            for row in db.query(Application.job_id)
            .filter(
                Application.user_id == user_id,
                Application.status == "planned",
                Application.cycle_start_date == cycle_monday,
            )
            .all()
        }

        unknown_ids = set(body.confirmed_job_ids) - planned_job_ids
        if unknown_ids:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Job IDs {sorted(unknown_ids)} are not in the current "
                    f"weekly plan for user {user_id}."
                ),
            )

        selector = QuotaSelector(db=db)
        result = selector.confirm_plan(
            user_id=user_id,
            confirmed_job_ids=body.confirmed_job_ids,
            removed_job_ids=body.removed_job_ids,
        )

        return result

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


# ------------------------------------------------------------------ #
# POST /weekly-plan/{user_id}/swap
# ------------------------------------------------------------------ #


class SwapRequestModel(BaseModel):
    remove_job_id: int
    add_job_id: int


@router.post("/{user_id}/swap")
def swap_plan_job(user_id: int, body: SwapRequestModel):
    """Swap one planned job for another from the scored list."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found.")

        selector = QuotaSelector(db=db)
        updated_plan = selector.swap_job(
            user_id=user_id,
            remove_job_id=body.remove_job_id,
            add_job_id=body.add_job_id,
        )

        return {
            "user_id": user_id,
            "cycle_start": str(_current_week_monday()),
            "applications": updated_plan,
            "total_count": len(updated_plan),
            "message": (
                f"Swapped out job {body.remove_job_id} for job {body.add_job_id}."
            ),
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()
