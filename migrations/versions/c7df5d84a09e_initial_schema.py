"""Initial schema

Revision ID: c7df5d84a09e
Revises: 
Create Date: 2026-07-11 12:17:54.054238

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c7df5d84a09e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create applicationmode enum type (if it doesn't exist)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE applicationmode AS ENUM ('internship', 'job');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create users table
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('mode', postgresql.ENUM('internship', 'job', name='applicationmode', create_type=False), nullable=False),
        sa.Column('master_profile', postgresql.JSONB(), nullable=True),
        sa.Column('weekly_quota', sa.Integer(), nullable=False),
        sa.Column('confirmation_mode', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    
    # Create jobs table
    op.create_table('jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_name', sa.String(), nullable=False),
        sa.Column('role_title', sa.String(), nullable=False),
        sa.Column('jd_text', sa.String(), nullable=False),
        sa.Column('skills_required', sa.String(), nullable=True),
        sa.Column('experience_required', sa.String(), nullable=True),
        sa.Column('location', sa.String(), nullable=True),
        sa.Column('stipend_salary', sa.String(), nullable=True),
        sa.Column('application_url', sa.String(), nullable=False),
        sa.Column('posting_date', sa.DateTime(), nullable=True),
        sa.Column('selection_process', sa.String(), nullable=True),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('listing_type', sa.String(), nullable=False),
        sa.Column('is_spam', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('spam_confidence', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create applications table
    op.create_table('applications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('match_score', sa.Float(), nullable=True),
        sa.Column('skill_gaps', sa.String(), nullable=True),
        sa.Column('resume_path', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create prep_guides table
    op.create_table('prep_guides',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=False),
        sa.Column('company_name', sa.String(), nullable=False),
        sa.Column('role_title', sa.String(), nullable=False),
        sa.Column('interview_rounds', sa.String(), nullable=True),
        sa.Column('topics_to_prepare', sa.String(), nullable=True),
        sa.Column('resources', sa.String(), nullable=True),
        sa.Column('mock_questions', sa.String(), nullable=True),
        sa.Column('company_intel', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create weekly_reports table
    op.create_table('weekly_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('week_start', sa.DateTime(), nullable=False),
        sa.Column('total_applications', sa.Integer(), nullable=False),
        sa.Column('successful_applications', sa.Integer(), nullable=False),
        sa.Column('summary', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('weekly_reports')
    op.drop_table('prep_guides')
    op.drop_table('applications')
    op.drop_table('jobs')
    op.drop_table('users')
    
    # Drop enum type (if it exists)
    op.execute("""
        DO $$ BEGIN
            DROP TYPE IF EXISTS applicationmode;
        EXCEPTION WHEN undefined_object THEN null;
        END $$;
    """)

