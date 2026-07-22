from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from datetime import datetime

from src.models import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    company_name = Column(String, nullable=False)
    role_title = Column(String, nullable=False)
    jd_text = Column(String, nullable=False)
    skills_required = Column(String, nullable=True)
    experience_required = Column(String, nullable=True)
    location = Column(String, nullable=True)
    stipend_salary = Column(String, nullable=True)
    application_url = Column(String, nullable=False)
    posting_date = Column(DateTime, nullable=True)
    selection_process = Column(String, nullable=True)
    source = Column(String, nullable=False)
    listing_type = Column(String, nullable=False)  # "internship" or "job"
    is_spam = Column(Boolean, default=False)
    spam_confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
