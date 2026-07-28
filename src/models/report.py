from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from datetime import datetime

from src.models import Base


class WeeklyReport(Base):
    __tablename__ = "weekly_reports"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    week_start = Column(DateTime, nullable=False)
    total_applications = Column(Integer, default=0)
    successful_applications = Column(Integer, default=0)
    summary = Column(String, nullable=True)
    report_path = Column(String, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
