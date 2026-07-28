"""
Tests for the Weekly Quota Selector and Confirmation Flow (Issue 11).

Covers plan generation with filters, swap, confirm, idempotency, and the
critical safety guarantee that trigger_resume_generation() is only called
from confirm_plan(), never from generate_weekly_plan() or swap_job().
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.api.routes import weekly_plan as weekly_plan_module
from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.pipelines.quota_selector import (
    QuotaSelector,
    trigger_resume_generation,
    _current_week_monday,
    EXPIRY_DAYS,
)

# ====================================================================== #
# Test fixtures
# ====================================================================== #


@pytest.fixture
def test_db_session() -> Generator[Session, None, None]:
    """Create an in-memory SQLite database with manually created tables."""
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                name VARCHAR NOT NULL,
                email VARCHAR NOT NULL UNIQUE,
                mode VARCHAR NOT NULL,
                master_profile TEXT,
                weekly_quota INTEGER NOT NULL DEFAULT 5,
                confirmation_mode VARCHAR NOT NULL DEFAULT 'batch',
                created_at DATETIME
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY,
                company_name VARCHAR NOT NULL,
                role_title VARCHAR NOT NULL,
                jd_text VARCHAR NOT NULL,
                skills_required VARCHAR,
                experience_required VARCHAR,
                location VARCHAR,
                stipend_salary VARCHAR,
                application_url VARCHAR NOT NULL,
                posting_date DATETIME,
                selection_process VARCHAR,
                source VARCHAR NOT NULL,
                listing_type VARCHAR NOT NULL,
                is_spam BOOLEAN DEFAULT 0,
                spam_confidence FLOAT,
                created_at DATETIME
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE applications (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                job_id INTEGER NOT NULL REFERENCES jobs(id),
                match_score FLOAT,
                skill_gaps VARCHAR,
                skill_matches VARCHAR,
                rank INTEGER,
                cycle_start_date DATE,
                resume_path VARCHAR,
                resume_version INTEGER,
                status VARCHAR NOT NULL DEFAULT 'pending',
                created_at DATETIME
            )
        """)

    TestSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db = TestSessionLocal()

    yield db

    db.close()


def _insert_user(
    db: Session,
    *,
    id: int = 1,
    name: str = "Test Student",
    email: str = "test@example.com",
    mode: str = "internship",
    master_profile: dict | None = None,
    weekly_quota: int = 5,
    confirmation_mode: str = "batch",
) -> User:
    profile_json = json.dumps(master_profile) if master_profile else None
    db.execute(
        text(
            "INSERT INTO users (id, name, email, mode, master_profile, "
            "weekly_quota, confirmation_mode, created_at) "
            "VALUES (:id, :name, :email, :mode, :profile, :quota, :cm, :ca)"
        ),
        {
            "id": id,
            "name": name,
            "email": email,
            "mode": mode,
            "profile": profile_json,
            "quota": weekly_quota,
            "cm": confirmation_mode,
            "ca": datetime.utcnow(),
        },
    )
    db.commit()
    user = db.query(User).filter(User.id == id).first()
    assert user is not None, "Failed to create test user"
    return user


def _insert_job(
    db: Session,
    *,
    id: int = 1,
    company_name: str = "TestCo",
    role_title: str = "Test Role",
    jd_text: str = "A test job description.",
    skills_required: str = "",
    experience_required: str = "",
    location: str = "",
    stipend_salary: str = "",
    application_url: str = "https://example.com/apply",
    posting_date: datetime | None = None,
    source: str = "test",
    listing_type: str = "internship",
    is_spam: bool = False,
    spam_confidence: float | None = None,
) -> Job:
    db.execute(
        text(
            "INSERT INTO jobs (id, company_name, role_title, jd_text, "
            "skills_required, experience_required, location, stipend_salary, "
            "application_url, posting_date, source, listing_type, is_spam, "
            "spam_confidence, created_at) "
            "VALUES (:id, :cn, :rt, :jd, :sr, :er, :loc, :ss, :au, :pd, "
            ":src, :lt, :spam, :sc, :ca)"
        ),
        {
            "id": id,
            "cn": company_name,
            "rt": role_title,
            "jd": jd_text,
            "sr": skills_required,
            "er": experience_required,
            "loc": location,
            "ss": stipend_salary,
            "au": application_url,
            "pd": posting_date,
            "src": source,
            "lt": listing_type,
            "spam": is_spam,
            "sc": spam_confidence,
            "ca": datetime.utcnow(),
        },
    )
    db.commit()
    job = db.query(Job).filter(Job.id == id).first()
    assert job is not None, "Failed to create test job"
    return job


def _insert_application(
    db: Session,
    *,
    id: int = 1,
    user_id: int = 1,
    job_id: int = 1,
    match_score: float = 0.8,
    skill_gaps: str = '["gap1"]',
    skill_matches: str = '["skill1"]',
    rank: int = 1,
    cycle_start_date: date | None = None,
    status: str = "pending",
) -> Application:
    db.execute(
        text(
            "INSERT INTO applications (id, user_id, job_id, match_score, "
            "skill_gaps, skill_matches, rank, cycle_start_date, status, "
            "created_at) "
            "VALUES (:id, :uid, :jid, :ms, :sg, :sm, :rk, :csd, :st, :ca)"
        ),
        {
            "id": id,
            "uid": user_id,
            "jid": job_id,
            "ms": match_score,
            "sg": skill_gaps,
            "sm": skill_matches,
            "rk": rank,
            "csd": cycle_start_date,
            "st": status,
            "ca": datetime.utcnow(),
        },
    )
    db.commit()
    app = db.query(Application).filter(Application.id == id).first()
    assert app is not None, "Failed to create test application"
    return app


# ====================================================================== #
# Test: generate_weekly_plan
# ====================================================================== #


class TestGenerateWeeklyPlan:
    def test_selects_exact_quota_when_enough_jobs(self, test_db_session: Session):
        """Selects exactly weekly_quota jobs when more are available."""
        _insert_user(test_db_session, id=1, weekly_quota=3)
        now = datetime.utcnow()

        # Create 6 jobs + scored applications
        jobs_data = [
            (1, "CompanyA"),
            (2, "CompanyB"),
            (3, "CompanyC"),
            (4, "CompanyD"),
            (5, "CompanyE"),
            (6, "CompanyF"),
        ]
        for jid, company in jobs_data:
            _insert_job(test_db_session, id=jid, company_name=company, posting_date=now)
            _insert_application(
                test_db_session,
                id=jid,
                user_id=1,
                job_id=jid,
                rank=jid,
                status="pending",
            )

        selector = QuotaSelector(db=test_db_session)
        plan = selector.generate_weekly_plan(1)

        assert len(plan) == 3, f"Expected 3 jobs, got {len(plan)}"
        job_ids = [p["job_id"] for p in plan]
        assert job_ids == [1, 2, 3], f"Expected top-3 by rank, got {job_ids}"

    def test_selects_fewer_when_not_enough_jobs(self, test_db_session: Session):
        """Selects fewer than weekly_quota when fewer eligible jobs exist."""
        _insert_user(test_db_session, id=1, weekly_quota=10)
        now = datetime.utcnow()

        # Only 3 jobs available
        for jid in range(1, 4):
            _insert_job(
                test_db_session, id=jid, company_name=f"Company{jid}", posting_date=now
            )
            _insert_application(
                test_db_session,
                id=jid,
                user_id=1,
                job_id=jid,
                rank=jid,
                status="pending",
            )

        selector = QuotaSelector(db=test_db_session)
        plan = selector.generate_weekly_plan(1)

        assert len(plan) == 3, f"Expected 3 (all available), got {len(plan)}"

    def test_raises_on_nonexistent_user(self, test_db_session: Session):
        """generate_weekly_plan raises ValueError for unknown user_id."""
        selector = QuotaSelector(db=test_db_session)
        with pytest.raises(ValueError, match="not found"):
            selector.generate_weekly_plan(999)

    def test_empty_when_no_scored_apps(self, test_db_session: Session):
        """Returns empty list when user has no scored applications."""
        _insert_user(test_db_session, id=1)
        selector = QuotaSelector(db=test_db_session)
        plan = selector.generate_weekly_plan(1)
        assert plan == []

    def test_already_applied_filter(self, test_db_session: Session):
        """Excludes companies the user has already applied to."""
        _insert_user(test_db_session, id=1, weekly_quota=5)
        now = datetime.utcnow()

        # Jobs from CompanyX and CompanyY
        _insert_job(test_db_session, id=1, company_name="CompanyX", posting_date=now)
        _insert_job(test_db_session, id=2, company_name="CompanyY", posting_date=now)
        _insert_job(test_db_session, id=3, company_name="CompanyZ", posting_date=now)

        # Scored applications for all 3
        _insert_application(
            test_db_session, id=1, user_id=1, job_id=1, rank=1, status="pending"
        )
        _insert_application(
            test_db_session, id=2, user_id=1, job_id=2, rank=2, status="pending"
        )
        _insert_application(
            test_db_session, id=3, user_id=1, job_id=3, rank=3, status="pending"
        )

        # User has already applied to CompanyX (via a different job)
        _insert_job(test_db_session, id=99, company_name="CompanyX", posting_date=now)
        _insert_application(
            test_db_session,
            id=99,
            user_id=1,
            job_id=99,
            rank=99,
            status="applied",
        )

        selector = QuotaSelector(db=test_db_session)
        plan = selector.generate_weekly_plan(1)

        job_ids = {p["job_id"] for p in plan}
        assert 1 not in job_ids, "CompanyX should be excluded (already applied)"
        assert 2 in job_ids, "CompanyY should be included"
        assert 3 in job_ids, "CompanyZ should be included"

    def test_expired_listing_filter(self, test_db_session: Session):
        """Excludes jobs with posting_date > 30 days old."""
        _insert_user(test_db_session, id=1, weekly_quota=5)
        now = datetime.utcnow()
        old_date = now - timedelta(days=EXPIRY_DAYS + 1)

        # Job 1: recent (not expired)
        _insert_job(test_db_session, id=1, company_name="CompanyA", posting_date=now)
        _insert_application(
            test_db_session, id=1, user_id=1, job_id=1, rank=1, status="pending"
        )

        # Job 2: expired
        _insert_job(
            test_db_session, id=2, company_name="CompanyB", posting_date=old_date
        )
        _insert_application(
            test_db_session, id=2, user_id=1, job_id=2, rank=2, status="pending"
        )

        selector = QuotaSelector(db=test_db_session)
        plan = selector.generate_weekly_plan(1)

        job_ids = {p["job_id"] for p in plan}
        assert 1 in job_ids, "Recent job should be included"
        assert 2 not in job_ids, "Expired job should be excluded"

    def test_null_posting_date_included(self, test_db_session: Session):
        """Jobs with NULL posting_date are included (not expired)."""
        _insert_user(test_db_session, id=1, weekly_quota=5)

        _insert_job(test_db_session, id=1, company_name="CompanyA", posting_date=None)
        _insert_application(
            test_db_session, id=1, user_id=1, job_id=1, rank=1, status="pending"
        )

        selector = QuotaSelector(db=test_db_session)
        plan = selector.generate_weekly_plan(1)

        job_ids = {p["job_id"] for p in plan}
        assert 1 in job_ids, "NULL posting_date job should be included"

    def test_blacklist_filter(self, test_db_session: Session):
        """Excludes jobs where company is in the user's blacklist."""
        _insert_user(
            test_db_session,
            id=1,
            weekly_quota=5,
            master_profile={"blacklisted_companies": ["CompanyB", "CompanyC"]},
        )
        now = datetime.utcnow()

        _insert_job(test_db_session, id=1, company_name="CompanyA", posting_date=now)
        _insert_job(test_db_session, id=2, company_name="CompanyB", posting_date=now)
        _insert_job(test_db_session, id=3, company_name="CompanyC", posting_date=now)

        for jid in range(1, 4):
            _insert_application(
                test_db_session,
                id=jid,
                user_id=1,
                job_id=jid,
                rank=jid,
                status="pending",
            )

        selector = QuotaSelector(db=test_db_session)
        plan = selector.generate_weekly_plan(1)

        job_ids = {p["job_id"] for p in plan}
        assert 1 in job_ids, "CompanyA should be included"
        assert 2 not in job_ids, "CompanyB should be excluded (blacklisted)"
        assert 3 not in job_ids, "CompanyC should be excluded (blacklisted)"

    def test_idempotent(self, test_db_session: Session):
        """Calling generate_weekly_plan twice produces the same plan."""
        _insert_user(test_db_session, id=1, weekly_quota=3)
        now = datetime.utcnow()

        for jid in range(1, 6):
            _insert_job(
                test_db_session, id=jid, company_name=f"Company{jid}", posting_date=now
            )
            _insert_application(
                test_db_session,
                id=jid,
                user_id=1,
                job_id=jid,
                rank=jid,
                status="pending",
            )

        selector = QuotaSelector(db=test_db_session)
        plan1 = selector.generate_weekly_plan(1)
        plan2 = selector.generate_weekly_plan(1)

        json1 = json.dumps(plan1, indent=2, sort_keys=True)
        json2 = json.dumps(plan2, indent=2, sort_keys=True)

        assert json1 == json2, "Plan should be identical on second call"

        # Verify no duplicate applications were created
        all_apps = (
            test_db_session.query(Application)
            .filter(
                Application.user_id == 1,
                Application.status == "planned",
            )
            .all()
        )
        assert len(all_apps) == 3, "Should have exactly 3 planned applications"

    def test_does_not_regenerate_after_confirm(self, test_db_session: Session):
        """After confirming a subset of the plan, GET returns only
        remaining planned jobs — confirmed/removed jobs do NOT reappear."""
        _insert_user(test_db_session, id=1, weekly_quota=4)
        now = datetime.utcnow()

        for jid in range(1, 6):
            _insert_job(
                test_db_session, id=jid, company_name=f"Company{jid}", posting_date=now
            )
            _insert_application(
                test_db_session,
                id=jid,
                user_id=1,
                job_id=jid,
                rank=jid,
                status="pending",
            )

        selector = QuotaSelector(db=test_db_session)
        selector.generate_weekly_plan(1)  # generates: jobs 1,2,3,4

        # Confirm jobs 1 and 3, remove job 2
        selector.confirm_plan(
            user_id=1,
            confirmed_job_ids=[1, 3],
            removed_job_ids=[2],
        )

        # Verify DB after confirm
        all_statuses = {
            row.job_id: row.status
            for row in test_db_session.query(Application)
            .filter(Application.user_id == 1)
            .all()
        }
        assert all_statuses[1] == "resume_pending"
        assert all_statuses[3] == "resume_pending"
        assert all_statuses[2] == "pending"

        # GET the plan again — should NOT regenerate
        second_plan = selector.generate_weekly_plan(1)

        # Only job 4 should still be planned (the 4th highest-rank job
        # from the original top-4: jobs 1,2,3,4 were selected; 1,3 are
        # confirmed, 2 is removed, so only 4 remains planned)
        remaining_ids = {p["job_id"] for p in second_plan}
        assert 1 not in remaining_ids, "Confirmed job 1 should not reappear"
        assert 3 not in remaining_ids, "Confirmed job 3 should not reappear"
        assert 2 not in remaining_ids, "Removed job 2 should not reappear"
        assert 4 in remaining_ids, "Job 4 should still be in planned status"
        assert 5 not in remaining_ids, "Job 5 was never in the plan"

        for app_entry in second_plan:
            assert app_entry["status"] == "planned", (
                f"Job {app_entry['job_id']} has status "
                f"'{app_entry['status']}', expected 'planned'"
            )

    def test_generate_weekly_plan_does_not_call_resume_generation(
        self, test_db_session: Session
    ):
        """generate_weekly_plan must NEVER call trigger_resume_generation."""
        _insert_user(test_db_session, id=1, weekly_quota=2)
        now = datetime.utcnow()

        for jid in range(1, 4):
            _insert_job(
                test_db_session, id=jid, company_name=f"Company{jid}", posting_date=now
            )
            _insert_application(
                test_db_session,
                id=jid,
                user_id=1,
                job_id=jid,
                rank=jid,
                status="pending",
            )

        selector = QuotaSelector(db=test_db_session)

        with patch(
            "src.pipelines.quota_selector.trigger_resume_generation"
        ) as mock_resume:
            selector.generate_weekly_plan(1)
            mock_resume.assert_not_called()


# ====================================================================== #
# Test: swap_job
# ====================================================================== #


class TestSwapJob:
    def test_swap_job_success(self, test_db_session: Session):
        """Swapping a planned job for an available one works."""
        _insert_user(test_db_session, id=1, weekly_quota=2)
        now = datetime.utcnow()
        cycle_monday = _current_week_monday()

        for jid in range(1, 5):
            _insert_job(
                test_db_session, id=jid, company_name=f"Company{jid}", posting_date=now
            )
            _insert_application(
                test_db_session,
                id=jid,
                user_id=1,
                job_id=jid,
                rank=jid,
                status="pending",
            )

        # Generate initial plan (selects jobs 1, 2)
        selector = QuotaSelector(db=test_db_session)
        plan = selector.generate_weekly_plan(1)
        assert [p["job_id"] for p in plan] == [1, 2]

        # Swap out job 1, add job 3
        updated_plan = selector.swap_job(user_id=1, remove_job_id=1, add_job_id=3)

        updated_ids = [p["job_id"] for p in updated_plan]
        assert 1 not in updated_ids, "Job 1 should be removed"
        assert 3 in updated_ids, "Job 3 should be added"

        # Verify DB state
        removed_app = (
            test_db_session.query(Application)
            .filter(Application.user_id == 1, Application.job_id == 1)
            .first()
        )
        assert removed_app is not None
        assert removed_app.status == "pending"
        assert removed_app.cycle_start_date is None

        added_app = (
            test_db_session.query(Application)
            .filter(Application.user_id == 1, Application.job_id == 3)
            .first()
        )
        assert added_app is not None
        assert added_app.status == "planned"
        assert added_app.cycle_start_date == cycle_monday

    def test_swap_nonexistent_remove_job(self, test_db_session: Session):
        """Removing a job that isn't in the plan raises an error."""
        _insert_user(test_db_session, id=1, weekly_quota=2)
        now = datetime.utcnow()

        _insert_job(test_db_session, id=1, company_name="CompanyA", posting_date=now)
        _insert_application(
            test_db_session, id=1, user_id=1, job_id=1, rank=1, status="pending"
        )

        selector = QuotaSelector(db=test_db_session)
        selector.generate_weekly_plan(1)

        # Job 2 is not in the plan
        _insert_job(test_db_session, id=2, company_name="CompanyB")
        _insert_application(
            test_db_session, id=2, user_id=1, job_id=2, rank=2, status="pending"
        )

        with pytest.raises(ValueError, match="not in the current weekly plan"):
            selector.swap_job(user_id=1, remove_job_id=999, add_job_id=2)

    def test_swap_does_not_call_resume_generation(self, test_db_session: Session):
        """swap_job must NEVER call trigger_resume_generation."""
        _insert_user(test_db_session, id=1, weekly_quota=2)
        now = datetime.utcnow()

        for jid in range(1, 4):
            _insert_job(
                test_db_session, id=jid, company_name=f"Company{jid}", posting_date=now
            )
            _insert_application(
                test_db_session,
                id=jid,
                user_id=1,
                job_id=jid,
                rank=jid,
                status="pending",
            )

        selector = QuotaSelector(db=test_db_session)
        selector.generate_weekly_plan(1)

        with patch(
            "src.pipelines.quota_selector.trigger_resume_generation"
        ) as mock_resume:
            selector.swap_job(user_id=1, remove_job_id=2, add_job_id=3)
            mock_resume.assert_not_called()


# ====================================================================== #
# Test: confirm_plan
# ====================================================================== #


class TestConfirmPlan:
    def test_confirm_plan_updates_status(self, test_db_session: Session):
        """Confirming a plan sets status to 'confirmed'."""
        _insert_user(test_db_session, id=1, weekly_quota=2)
        now = datetime.utcnow()

        for jid in range(1, 4):
            _insert_job(
                test_db_session, id=jid, company_name=f"Company{jid}", posting_date=now
            )
            _insert_application(
                test_db_session,
                id=jid,
                user_id=1,
                job_id=jid,
                rank=jid,
                status="pending",
            )

        selector = QuotaSelector(db=test_db_session)
        plan = selector.generate_weekly_plan(1)

        confirmed = [p["job_id"] for p in plan]
        result = selector.confirm_plan(
            user_id=1,
            confirmed_job_ids=confirmed,
            removed_job_ids=[],
        )

        assert result["confirmed_count"] == 2
        assert result["removed_count"] == 0
        assert "note" in result
        assert "Issue 12" in result["note"]

        # Verify DB state — after the stub runs, status is "resume_pending"
        confirmed_apps = (
            test_db_session.query(Application)
            .filter(
                Application.user_id == 1,
                Application.status == "resume_pending",
            )
            .all()
        )
        assert len(confirmed_apps) == 2, "Both should be resume_pending after stub"
        for confirmed_app in confirmed_apps:
            assert confirmed_app.cycle_start_date == _current_week_monday()

        # Verify the non-confirmed job is still "pending"
        unplanned_app = (
            test_db_session.query(Application)
            .filter(Application.user_id == 1, Application.job_id == 3)
            .first()
        )
        assert unplanned_app is not None
        assert unplanned_app.status == "pending"

    def test_confirm_empty_list_raises_error(self, test_db_session: Session):
        """Confirming with an empty job list is an error."""
        _insert_user(test_db_session, id=1)
        selector = QuotaSelector(db=test_db_session)

        with pytest.raises(ValueError, match="confirmed_job_ids must not be empty"):
            selector.confirm_plan(user_id=1, confirmed_job_ids=[], removed_job_ids=[])

    def test_confirm_job_not_in_plan(self, test_db_session: Session):
        """Confirming a job that isn't in the plan raises an error."""
        _insert_user(test_db_session, id=1, weekly_quota=2)
        now = datetime.utcnow()

        _insert_job(test_db_session, id=1, company_name="CompanyA", posting_date=now)
        _insert_application(
            test_db_session, id=1, user_id=1, job_id=1, rank=1, status="pending"
        )

        selector = QuotaSelector(db=test_db_session)
        selector.generate_weekly_plan(1)

        with pytest.raises(ValueError, match="not in the current weekly plan"):
            selector.confirm_plan(
                user_id=1, confirmed_job_ids=[999], removed_job_ids=[]
            )

    def test_confirm_calls_resume_generation(self, test_db_session: Session):
        """confirm_plan MUST call trigger_resume_generation."""
        _insert_user(test_db_session, id=1, weekly_quota=2)
        now = datetime.utcnow()

        for jid in range(1, 4):
            _insert_job(
                test_db_session, id=jid, company_name=f"Company{jid}", posting_date=now
            )
            _insert_application(
                test_db_session,
                id=jid,
                user_id=1,
                job_id=jid,
                rank=jid,
                status="pending",
            )

        selector = QuotaSelector(db=test_db_session)
        plan = selector.generate_weekly_plan(1)
        confirmed = [p["job_id"] for p in plan]

        with patch(
            "src.pipelines.quota_selector.trigger_resume_generation"
        ) as mock_resume:
            selector.confirm_plan(
                user_id=1,
                confirmed_job_ids=confirmed,
                removed_job_ids=[],
            )
            # Should be called once per confirmed job
            assert mock_resume.call_count == 2

    def test_confirm_removes_jobs(self, test_db_session: Session):
        """Jobs in removed_job_ids are set back to pending."""
        _insert_user(test_db_session, id=1, weekly_quota=3)
        now = datetime.utcnow()

        for jid in range(1, 5):
            _insert_job(
                test_db_session, id=jid, company_name=f"Company{jid}", posting_date=now
            )
            _insert_application(
                test_db_session,
                id=jid,
                user_id=1,
                job_id=jid,
                rank=jid,
                status="pending",
            )

        selector = QuotaSelector(db=test_db_session)
        selector.generate_weekly_plan(1)

        # Confirm job 1, remove jobs 2 and 3
        result = selector.confirm_plan(
            user_id=1,
            confirmed_job_ids=[1],
            removed_job_ids=[2, 3],
        )

        assert result["confirmed_count"] == 1
        assert result["removed_count"] == 2

        # Verify DB
        confirmed_app = (
            test_db_session.query(Application)
            .filter(Application.user_id == 1, Application.job_id == 1)
            .first()
        )
        assert confirmed_app is not None
        assert (
            confirmed_app.status == "resume_pending"
        ), "Status should be resume_pending after stub runs"

        removed_app = (
            test_db_session.query(Application)
            .filter(Application.user_id == 1, Application.job_id == 2)
            .first()
        )
        assert removed_app is not None
        assert removed_app.status == "pending"
        assert removed_app.cycle_start_date is None


# ====================================================================== #
# Test: trigger_resume_generation stub
# ====================================================================== #


class TestTriggerResumeGeneration:
    def test_updates_status_to_resume_pending(self, test_db_session: Session):
        """trigger_resume_generation sets status to 'resume_pending'."""
        _insert_user(test_db_session, id=1)
        _insert_job(test_db_session, id=1)
        _insert_application(
            test_db_session,
            id=1,
            user_id=1,
            job_id=1,
            status="confirmed",
        )

        app = test_db_session.query(Application).filter(Application.id == 1).first()
        assert app is not None
        assert app.status == "confirmed"

        trigger_resume_generation(application_id=1, db=test_db_session)

        test_db_session.refresh(app)
        assert app.status == "resume_pending"

    def test_handles_nonexistent_application(self, test_db_session: Session):
        """trigger_resume_generation gracefully handles missing app."""
        # Should not crash
        trigger_resume_generation(application_id=999, db=test_db_session)

    def test_only_confirm_calls_resume_generation(self, test_db_session: Session):
        """Comprehensive safety test: only confirm_plan calls the stub."""
        _insert_user(test_db_session, id=1, weekly_quota=2)
        now = datetime.utcnow()

        for jid in range(1, 4):
            _insert_job(
                test_db_session, id=jid, company_name=f"Company{jid}", posting_date=now
            )
            _insert_application(
                test_db_session,
                id=jid,
                user_id=1,
                job_id=jid,
                rank=jid,
                status="pending",
            )

        selector = QuotaSelector(db=test_db_session)

        with patch(
            "src.pipelines.quota_selector.trigger_resume_generation"
        ) as mock_resume:
            # generate_weekly_plan should NOT call it
            selector.generate_weekly_plan(1)
            assert (
                mock_resume.call_count == 0
            ), "generate_weekly_plan called trigger_resume_generation!"

            # swap_job should NOT call it
            with pytest.raises(ValueError):
                selector.swap_job(user_id=1, remove_job_id=999, add_job_id=3)
            assert (
                mock_resume.call_count == 0
            ), "swap_job called trigger_resume_generation!"

            # confirm_plan SHOULD call it
            selector.confirm_plan(
                user_id=1,
                confirmed_job_ids=[1, 2],
                removed_job_ids=[],
            )
            assert (
                mock_resume.call_count == 2
            ), f"confirm_plan should call it 2 times, got {mock_resume.call_count}"


# ====================================================================== #
# Test: Expiry helper
# ====================================================================== #


# ====================================================================== #
# Test: GET /weekly-plan/{user_id} is READ-ONLY (via TestClient)
# ====================================================================== #
# These tests verify that the GET route never mutates the database.
# After confirming a subset of jobs, calling GET multiple times must
# not change any application status, and confirmed jobs must never
# reappear as "planned" in the response.
#
# Each test creates its own in-memory engine + tables + seed data,
# then patches SessionLocal in the route and pipeline modules so that
# the TestClient uses the same isolated database.
# ====================================================================== #


def _create_test_tables(engine):
    """Create all tables needed for the TestClient integration tests."""
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                name VARCHAR NOT NULL,
                email VARCHAR NOT NULL UNIQUE,
                mode VARCHAR NOT NULL,
                master_profile TEXT,
                weekly_quota INTEGER NOT NULL DEFAULT 5,
                confirmation_mode VARCHAR NOT NULL DEFAULT 'batch',
                created_at DATETIME
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY,
                company_name VARCHAR NOT NULL,
                role_title VARCHAR NOT NULL,
                jd_text VARCHAR NOT NULL,
                skills_required VARCHAR,
                experience_required VARCHAR,
                location VARCHAR,
                stipend_salary VARCHAR,
                application_url VARCHAR NOT NULL,
                posting_date DATETIME,
                selection_process VARCHAR,
                source VARCHAR NOT NULL,
                listing_type VARCHAR NOT NULL,
                is_spam BOOLEAN DEFAULT 0,
                spam_confidence FLOAT,
                created_at DATETIME
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE applications (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                job_id INTEGER NOT NULL REFERENCES jobs(id),
                match_score FLOAT,
                skill_gaps VARCHAR,
                skill_matches VARCHAR,
                rank INTEGER,
                cycle_start_date DATE,
                resume_path VARCHAR,
                resume_version INTEGER,
                status VARCHAR NOT NULL DEFAULT 'pending',
                created_at DATETIME
            )
        """)


class TestGETWeeklyPlanReadOnly:
    def test_get_does_not_mutate_after_confirm(self):
        """Calling GET twice after confirming a subset must NOT mutate
        the DB: confirmed jobs stay 'resume_pending', removed jobs stay
        'pending', and the response never includes confirmed jobs."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        _create_test_tables(engine)
        TestSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

        # ── Seed data ─────────────────────────────────────────── #
        db = TestSessionLocal()
        _insert_user(db, id=1, weekly_quota=4)
        now = datetime.utcnow()
        for jid in range(1, 6):
            _insert_job(
                db,
                id=jid,
                company_name=f"Company{chr(64 + jid)}",
                posting_date=now,
            )
            _insert_application(
                db,
                id=jid,
                user_id=1,
                job_id=jid,
                rank=jid,
                status="pending",
            )
        db.close()

        # ── Generate plan + confirm a subset ──────────────────── #
        db2 = TestSessionLocal()
        selector = QuotaSelector(db=db2)
        selector.generate_weekly_plan(1)  # plans jobs 1,2,3,4
        selector.confirm_plan(
            user_id=1,
            confirmed_job_ids=[1, 3],
            removed_job_ids=[2],
        )
        db2.close()

        # ── Patch SessionLocal for API calls ──────────────────── #
        original_wp = weekly_plan_module.SessionLocal
        weekly_plan_module.SessionLocal = TestSessionLocal

        try:
            with TestClient(app) as client:
                # Snapshot DB before GET
                check_db = TestSessionLocal()
                statuses_before = {
                    row.job_id: row.status
                    for row in check_db.query(Application)
                    .filter(Application.user_id == 1)
                    .all()
                }
                check_db.close()

                # ── First GET ────────────────────────────────── #
                resp1 = client.get("/weekly-plan/1")
                assert (
                    resp1.status_code == 200
                ), f"First GET returned {resp1.status_code}: {resp1.text}"
                data1 = resp1.json()
                resp_ids1 = {a["job_id"] for a in data1["applications"]}

                assert 1 not in resp_ids1, "Confirmed job 1 appeared in GET response"
                assert 3 not in resp_ids1, "Confirmed job 3 appeared in GET response"
                assert 2 not in resp_ids1, "Removed job 2 appeared in GET response"
                assert 4 in resp_ids1, "Planned job 4 should appear in GET response"

                # ── Second GET ───────────────────────────────── #
                resp2 = client.get("/weekly-plan/1")
                assert resp2.status_code == 200

                # ── Snapshot DB after both GETs ──────────────── #
                check_db2 = TestSessionLocal()
                statuses_after = {
                    row.job_id: row.status
                    for row in check_db2.query(Application)
                    .filter(Application.user_id == 1)
                    .all()
                }
                check_db2.close()

                # Critical: DB was NOT mutated
                assert statuses_before == statuses_after, (
                    f"GET calls mutated the DB! "
                    f"Before: {statuses_before}, After: {statuses_after}"
                )
                assert statuses_after[1] == "resume_pending"
                assert statuses_after[3] == "resume_pending"
                assert statuses_after[2] == "pending"
                assert statuses_after[4] == "planned"

        finally:
            weekly_plan_module.SessionLocal = original_wp

    def test_multiple_gets_return_same_plan(self):
        """Calling GET multiple times before confirming returns
        identical results and does not mutate the DB."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        _create_test_tables(engine)
        TestSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

        # Seed data
        db = TestSessionLocal()
        _insert_user(db, id=2, weekly_quota=3)
        now = datetime.utcnow()
        for jid in range(1, 5):
            _insert_job(
                db,
                id=jid,
                company_name=f"Company{chr(64 + jid)}",
                posting_date=now,
            )
            _insert_application(
                db,
                id=jid,
                user_id=2,
                job_id=jid,
                rank=jid,
                status="pending",
            )
        db.close()

        # Generate plan
        db2 = TestSessionLocal()
        selector = QuotaSelector(db=db2)
        selector.generate_weekly_plan(2)
        db2.close()

        # Patch
        original_wp = weekly_plan_module.SessionLocal
        weekly_plan_module.SessionLocal = TestSessionLocal

        try:
            with TestClient(app) as client:
                check_db = TestSessionLocal()
                statuses_before = {
                    row.job_id: row.status
                    for row in check_db.query(Application)
                    .filter(Application.user_id == 2)
                    .all()
                }
                check_db.close()

                r1 = client.get("/weekly-plan/2")
                r2 = client.get("/weekly-plan/2")
                r3 = client.get("/weekly-plan/2")

                assert r1.status_code == 200
                assert r2.status_code == 200
                assert r3.status_code == 200

                assert r1.json() == r2.json(), "First and second GET differ"
                assert r2.json() == r3.json(), "Second and third GET differ"

                check_db2 = TestSessionLocal()
                statuses_after = {
                    row.job_id: row.status
                    for row in check_db2.query(Application)
                    .filter(Application.user_id == 2)
                    .all()
                }
                check_db2.close()
                assert statuses_before == statuses_after, "GETs mutated the DB!"

                for entry in r1.json()["applications"]:
                    assert entry["status"] == "planned"

        finally:
            weekly_plan_module.SessionLocal = original_wp

    def test_get_after_all_confirmed_returns_empty(self):
        """After confirming ALL jobs, GET returns empty plan and does
        not regenerate or mutate the DB."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        _create_test_tables(engine)
        TestSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

        # Seed
        db = TestSessionLocal()
        _insert_user(db, id=3, weekly_quota=2)
        now = datetime.utcnow()
        for jid in range(1, 4):
            _insert_job(
                db,
                id=jid,
                company_name=f"Company{chr(64 + jid)}",
                posting_date=now,
            )
            _insert_application(
                db,
                id=jid,
                user_id=3,
                job_id=jid,
                rank=jid,
                status="pending",
            )
        db.close()

        # Generate + confirm all
        db2 = TestSessionLocal()
        selector = QuotaSelector(db=db2)
        selector.generate_weekly_plan(3)
        selector.confirm_plan(user_id=3, confirmed_job_ids=[1, 2], removed_job_ids=[])
        db2.close()

        original_wp = weekly_plan_module.SessionLocal
        weekly_plan_module.SessionLocal = TestSessionLocal

        try:
            with TestClient(app) as client:
                check_db = TestSessionLocal()
                statuses_before = {
                    row.job_id: row.status
                    for row in check_db.query(Application)
                    .filter(Application.user_id == 3)
                    .all()
                }
                check_db.close()

                resp = client.get("/weekly-plan/3")
                assert resp.status_code == 200
                data = resp.json()

                assert (
                    data["applications"] == []
                ), f"Expected empty, got {len(data['applications'])} jobs"
                assert data["total_count"] == 0

                check_db2 = TestSessionLocal()
                statuses_after = {
                    row.job_id: row.status
                    for row in check_db2.query(Application)
                    .filter(Application.user_id == 3)
                    .all()
                }
                check_db2.close()

                assert statuses_before == statuses_after, "GET mutated the DB!"
                assert statuses_after[1] == "resume_pending"
                assert statuses_after[2] == "resume_pending"

        finally:
            weekly_plan_module.SessionLocal = original_wp


# ====================================================================== #
# Test: Expiry helper
# ====================================================================== #


class TestIsExpired:
    def test_recent_job_not_expired(self):
        """A job posted today is not expired."""
        job = MagicMock(spec=Job)
        job.id = 1
        job.company_name = "TestCo"
        job.posting_date = datetime.utcnow()
        assert QuotaSelector._is_expired(job) is False

    def test_old_job_is_expired(self):
        """A job posted 31+ days ago is expired."""
        job = MagicMock(spec=Job)
        job.id = 1
        job.company_name = "TestCo"
        job.posting_date = datetime.utcnow() - timedelta(days=EXPIRY_DAYS + 1)
        assert QuotaSelector._is_expired(job) is True

    def test_null_posting_date_not_expired(self):
        """A job with NULL posting_date is NOT expired."""
        job = MagicMock(spec=Job)
        job.id = 1
        job.company_name = "TestCo"
        job.posting_date = None
        assert QuotaSelector._is_expired(job) is False
