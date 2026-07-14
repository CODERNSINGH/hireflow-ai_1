from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from datetime import datetime

from src.models import Base

class PrepGuide(Base):
    __tablename__ = "prep_guides"
    
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    company_name = Column(String, nullable=False)
    role_title = Column(String, nullable=False)
    interview_rounds = Column(String, nullable=True)
    topics_to_prepare = Column(String, nullable=True)
    resources = Column(String, nullable=True)
    mock_questions = Column(String, nullable=True)
    company_intel = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)