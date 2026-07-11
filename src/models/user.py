from sqlalchemy import Column, Integer, String, DateTime, Enum
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
import enum

from src.models import Base

class ApplicationMode(str, enum.Enum):
    internship = "internship"
    job = "job"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    mode = Column(Enum(ApplicationMode), nullable=False)
    master_profile = Column(JSONB, nullable=True)
    weekly_quota = Column(Integer, nullable=False, default=5)
    confirmation_mode = Column(String, nullable=False, default="batch")
    created_at = Column(DateTime, default=datetime.utcnow)