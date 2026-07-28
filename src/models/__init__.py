from sqlalchemy.orm import declarative_base

# Shared declarative base for all models so Alembic autogenerate
# can see a single metadata object containing every table.
Base = declarative_base()

from src.models.user import User
from src.models.job import Job
from src.models.application import Application, ApplicationStatusLog
from src.models.prep_guide import PrepGuide
from src.models.report import WeeklyReport
