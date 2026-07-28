from sqlalchemy import Column, Date, Integer, String, Float, DateTime, ForeignKey
from datetime import datetime

from src.models import Base


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    match_score = Column(Float, nullable=True)
    skill_gaps = Column(String, nullable=True)
    skill_matches = Column(String, nullable=True)  # JSON-encoded list of matched skills
    rank = Column(Integer, nullable=True)  # Ranking position (1 = best)
    cycle_start_date = Column(
        Date, nullable=True
    )  # Monday of the ISO week this plan entry belongs to
    resume_path = Column(String, nullable=True)
    resume_version = Column(Integer, nullable=True, default=1)
    status = Column(
        String, nullable=False, default="pending"
    )  # pending, planned, confirmed, resume_pending, applying, applied, failed, needs_action
    failure_reason = Column(String, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApplicationStatusLog(Base):
    __tablename__ = "application_status_logs"

    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    status = Column(String, nullable=False)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
