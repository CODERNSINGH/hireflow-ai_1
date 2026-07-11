"""Tests for database models and migrations."""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from src.config.database import engine, SessionLocal
from src.models.user import User, ApplicationMode
from src.models.job import Job
from src.models.application import Application
from src.models.prep_guide import PrepGuide
from src.models.report import WeeklyReport


def get_db_session():
    """Get a database session for testing."""
    return SessionLocal()


class TestDatabaseSchema:
    """Test that all required tables exist with correct columns."""

    def test_users_table_exists(self):
        """Verify users table exists and has required columns."""
        inspector = inspect(engine)
        assert 'users' in inspector.get_table_names(), "users table does not exist"
        
        columns = {col['name']: col for col in inspector.get_columns('users')}
        required_columns = {
            'id', 'name', 'email', 'mode', 'master_profile',
            'weekly_quota', 'confirmation_mode', 'created_at'
        }
        assert required_columns.issubset(set(columns.keys())), \
            f"Missing columns in users: {required_columns - set(columns.keys())}"
        
        # Check master_profile is JSONB type
        master_profile_col = columns['master_profile']
        assert 'json' in str(master_profile_col['type']).lower(), \
            f"master_profile should be JSON/JSONB, got {master_profile_col['type']}"

    def test_jobs_table_exists(self):
        """Verify jobs table exists and has required columns."""
        inspector = inspect(engine)
        assert 'jobs' in inspector.get_table_names(), "jobs table does not exist"
        
        columns = {col['name']: col for col in inspector.get_columns('jobs')}
        required_columns = {
            'id', 'company_name', 'role_title', 'jd_text', 'skills_required',
            'experience_required', 'location', 'stipend_salary', 'application_url',
            'posting_date', 'selection_process', 'source', 'listing_type',
            'is_spam', 'spam_confidence', 'created_at'
        }
        assert required_columns.issubset(set(columns.keys())), \
            f"Missing columns in jobs: {required_columns - set(columns.keys())}"

    def test_applications_table_exists(self):
        """Verify applications table exists with foreign keys to users and jobs."""
        inspector = inspect(engine)
        assert 'applications' in inspector.get_table_names(), "applications table does not exist"
        
        columns = {col['name']: col for col in inspector.get_columns('applications')}
        required_columns = {'id', 'user_id', 'job_id', 'match_score', 'skill_gaps', 'resume_path', 'status', 'created_at'}
        assert required_columns.issubset(set(columns.keys())), \
            f"Missing columns in applications: {required_columns - set(columns.keys())}"
        
        # Check foreign keys
        fks = inspector.get_foreign_keys('applications')
        fk_tables = {fk['referred_table'] for fk in fks}
        assert 'users' in fk_tables and 'jobs' in fk_tables, \
            f"applications must have FKs to users and jobs, got FKs to {fk_tables}"

    def test_prep_guides_table_exists(self):
        """Verify prep_guides table exists with foreign key to applications."""
        inspector = inspect(engine)
        assert 'prep_guides' in inspector.get_table_names(), "prep_guides table does not exist"
        
        columns = {col['name']: col for col in inspector.get_columns('prep_guides')}
        required_columns = {
            'id', 'application_id', 'company_name', 'role_title', 'interview_rounds',
            'topics_to_prepare', 'resources', 'mock_questions', 'company_intel', 'created_at'
        }
        assert required_columns.issubset(set(columns.keys())), \
            f"Missing columns in prep_guides: {required_columns - set(columns.keys())}"
        
        # Check foreign key to applications
        fks = inspector.get_foreign_keys('prep_guides')
        fk_tables = {fk['referred_table'] for fk in fks}
        assert 'applications' in fk_tables, \
            f"prep_guides must have FK to applications, got FKs to {fk_tables}"

    def test_weekly_reports_table_exists(self):
        """Verify weekly_reports table exists with foreign key to users."""
        inspector = inspect(engine)
        assert 'weekly_reports' in inspector.get_table_names(), "weekly_reports table does not exist"
        
        columns = {col['name']: col for col in inspector.get_columns('weekly_reports')}
        required_columns = {
            'id', 'user_id', 'week_start', 'total_applications',
            'successful_applications', 'summary', 'created_at'
        }
        assert required_columns.issubset(set(columns.keys())), \
            f"Missing columns in weekly_reports: {required_columns - set(columns.keys())}"
        
        # Check foreign key to users
        fks = inspector.get_foreign_keys('weekly_reports')
        fk_tables = {fk['referred_table'] for fk in fks}
        assert 'users' in fk_tables, \
            f"weekly_reports must have FK to users, got FKs to {fk_tables}"

    def test_all_five_tables_exist(self):
        """Verify all 5 required tables exist."""
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        required_tables = {'users', 'jobs', 'applications', 'prep_guides', 'weekly_reports'}
        missing_tables = required_tables - table_names
        assert not missing_tables, f"Missing tables: {missing_tables}"


class TestModelImports:
    """Test that all models can be imported without errors."""

    def test_import_all_models(self):
        """Verify all models are importable."""
        assert User is not None
        assert Job is not None
        assert Application is not None
        assert PrepGuide is not None
        assert WeeklyReport is not None

    def test_application_mode_enum(self):
        """Verify ApplicationMode enum has correct values."""
        assert hasattr(ApplicationMode, 'internship')
        assert hasattr(ApplicationMode, 'job')
        assert ApplicationMode.internship.value == 'internship'
        assert ApplicationMode.job.value == 'job'
