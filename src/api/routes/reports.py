"""
HireFlow AI — Weekly Report API Routes

GET /report/{user_id}/latest  — Return the most recent weekly report for a user
GET /report/{user_id}/list    — List all reports for a user (metadata only)
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config.database import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report", tags=["reports"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class StudyPlanItem(BaseModel):
    rank: int
    skill: str
    frequency: int
    reason: str


class InsightsResponse(BaseModel):
    top_skills: List[str]
    top_skill_counts: Dict[str, int]
    top_gaps: List[str]
    strongest_category: str
    weakest_category: str
    role_categories: List[str]


class StatsResponse(BaseModel):
    total: int
    applied: int
    failed: int
    needs_action: int
    pending: int
    avg_match_score: float


class ApplicationSummary(BaseModel):
    application_id: int
    company: str
    role: str
    status: str
    match_score: float
    skill_gaps: List[str]
    resume_path: str
    application_url: str


class WeeklyReportResponse(BaseModel):
    user_id: int
    week_start: str
    week_label: str
    generated_at: str
    stats: StatsResponse
    insights: InsightsResponse
    study_plan: List[StudyPlanItem]
    applications: List[ApplicationSummary]
    html_path: Optional[str] = None


class ReportMetaResponse(BaseModel):
    id: int
    week_start: str
    total_applications: int
    successful_applications: int
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/{user_id}/latest", response_model=Dict[str, Any])
def get_latest_report(user_id: int):
    """
    Return the most recent weekly report for the given user.

    Reads from the weekly_reports table (summary JSON) and returns the full
    structured report. If no report exists, returns 404.
    """
    db = SessionLocal()
    try:
        from src.models.report import WeeklyReport

        record = (
            db.query(WeeklyReport)
            .filter(WeeklyReport.user_id == user_id)
            .order_by(WeeklyReport.week_start.desc())
            .first()
        )

        if not record:
            raise HTTPException(
                status_code=404,
                detail=f"No weekly report found for user {user_id}. "
                       "Generate one first using the report generator.",
            )

        # Parse summary JSON stored in the DB
        summary_data: Dict[str, Any] = {}
        if record.summary:
            try:
                summary_data = json.loads(record.summary)
            except (json.JSONDecodeError, TypeError):
                summary_data = {}

        return {
            "user_id": user_id,
            "week_start": record.week_start.isoformat() if record.week_start else None,
            "total_applications": record.total_applications,
            "successful_applications": record.successful_applications,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "insights": summary_data.get("insights", {}),
            "study_plan": summary_data.get("study_plan", []),
            "html_path": summary_data.get("html_path", ""),
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error fetching latest report for user %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}")
    finally:
        db.close()


@router.get("/{user_id}/list", response_model=List[Dict[str, Any]])
def list_reports(user_id: int, limit: int = 10):
    """
    List all weekly reports for a user (metadata only, no full application data).
    """
    db = SessionLocal()
    try:
        from src.models.report import WeeklyReport

        records = (
            db.query(WeeklyReport)
            .filter(WeeklyReport.user_id == user_id)
            .order_by(WeeklyReport.week_start.desc())
            .limit(limit)
            .all()
        )

        return [
            {
                "id": r.id,
                "week_start": r.week_start.isoformat() if r.week_start else None,
                "total_applications": r.total_applications,
                "successful_applications": r.successful_applications,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]

    except Exception as exc:
        logger.error("Error listing reports for user %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}")
    finally:
        db.close()
