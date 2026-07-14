from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from datetime import datetime

from src.models import Base

class Application(Base):
    __tablename__ = "applications"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    match_score = Column(Float, nullable=True)
    skill_gaps = Column(String, nullable=True)
    resume_path = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending, applied, failed, needs_action
    created_at = Column(DateTime, default=datetime.utcnow)