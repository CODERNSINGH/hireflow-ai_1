"""
Tests for the Multi-Factor Match Scorer (Issue 10).

Covers all sub-scores, determinism, error handling, and DB persistence.
Creates SQLite-compatible tables manually to avoid JSONB incompatibility.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Generator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.pipelines.match_scorer import (
    EMBEDDING_BLEND_RATIO,
    MatchScorer,
    _parse_numeric_salary,
    _parse_year_range,
    _significant_words,
)

# ====================================================================== #
# Fixtures
# ====================================================================== #


@pytest.fixture
def test_db_session() -> Generator[Session, None, None]:
    """Create an in-memory SQLite database with manually created tables.

    We avoid Base.metadata.create_all() because the User model uses
    PostgreSQL JSONB, which SQLite cannot render.
    """
    engine = create_engine("sqlite:///:memory:")

    # Create tables with SQLite-compatible types
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
    """Create a User row using raw SQL and return as an ORM object."""
    import json as _json

    profile_json = _json.dumps(master_profile) if master_profile else None
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

    # Return as ORM object
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
    source: str = "test",
    listing_type: str = "job",
    is_spam: bool = False,
    spam_confidence: float | None = None,
) -> Job:
    """Create a Job row using raw SQL and return as an ORM object."""
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
            "pd": datetime.utcnow(),
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


@pytest.fixture
def sample_user(test_db_session: Session) -> User:
    """Create a sample user with internship mode."""
    return _insert_user(
        test_db_session,
        id=1,
        name="Test Student",
        email="test@example.com",
        mode="internship",
        master_profile={
            "skills": ["Python", "FastAPI", "PostgreSQL", "React"],
            "target_roles": ["AI Engineer Intern", "Backend Developer Intern"],
            "preferred_locations": ["Bangalore", "Remote"],
            "min_stipend": 20000,
        },
    )


@pytest.fixture
def sample_jobs(test_db_session: Session) -> list[Job]:
    """Create a variety of sample jobs for scoring tests."""
    jobs_data = [
        dict(
            id=1,
            company_name="TechCorp",
            role_title="Backend Developer Intern",
            jd_text=(
                "We are looking for a backend developer intern with Python, "
                "FastAPI, and PostgreSQL experience. You will build REST APIs "
                "and work on our data pipeline. This is a great opportunity "
                "for students. " * 3
            ),
            skills_required="Python, FastAPI, PostgreSQL",
            experience_required="0-1 years",
            location="Bangalore",
            stipend_salary="25000",
            application_url="https://example.com/apply1",
            source="Lever",
            listing_type="internship",
            is_spam=False,
            spam_confidence=0.05,
        ),
        dict(
            id=2,
            company_name="WebSolutions",
            role_title="Frontend Developer",
            jd_text="Seeking a frontend developer with React and TypeScript skills.",
            skills_required="React, TypeScript, CSS",
            experience_required="1-2 years",
            location="Mumbai",
            stipend_salary="50000",
            application_url="https://example.com/apply2",
            source="Greenhouse",
            listing_type="job",
            is_spam=False,
            spam_confidence=0.05,
        ),
        dict(
            id=3,
            company_name="SpamCorp",
            role_title="Fake Job",
            jd_text="This is spam content.",
            skills_required="None",
            experience_required="None",
            location="Unknown",
            stipend_salary="0",
            application_url="https://spam.com/apply",
            source="Spam",
            listing_type="job",
            is_spam=True,
            spam_confidence=0.95,
        ),
        dict(
            id=4,
            company_name="AIStartup",
            role_title="AI Engineer Intern",
            jd_text=(
                "Looking for an AI intern with experience in Python, LangChain, "
                "and LLMs. You will build RAG pipelines and work on cutting-edge "
                "AI products. We offer a great learning environment and "
                "competitive stipend. " * 3
            ),
            skills_required="Python, LangChain, LLMs",
            experience_required="0-1 years",
            location="Remote",
            stipend_salary="35000",
            application_url="https://example.com/apply4",
            source="Lever",
            listing_type="internship",
            is_spam=False,
            spam_confidence=0.02,
        ),
        dict(
            id=5,
            company_name="OldSchool",
            role_title="Senior Java Developer",
            jd_text="Senior Java developer needed for enterprise applications.",
            skills_required="Java, Spring, SQL",
            experience_required="5+ years",
            location="Delhi",
            stipend_salary="Competitive",
            application_url="https://example.com/apply5",
            source="Naukri",
            listing_type="job",
            is_spam=False,
            spam_confidence=0.1,
        ),
    ]

    jobs = []
    for data in jobs_data:
        jobs.append(_insert_job(test_db_session, **data))
    return jobs


@pytest.fixture
def mock_embedding_pipeline() -> MagicMock:
    """Return a mock EmbeddingPipeline that returns deterministic scores."""

    def search_side_effect(query_text: str, top_k: int = 5) -> list[dict]:
        return [
            {
                "job_id": 1,
                "score": 0.85,
                "role_title": "Backend Developer Intern",
                "company_name": "TechCorp",
            },
            {
                "job_id": 4,
                "score": 0.92,
                "role_title": "AI Engineer Intern",
                "company_name": "AIStartup",
            },
            {
                "job_id": 2,
                "score": 0.45,
                "role_title": "Frontend Developer",
                "company_name": "WebSolutions",
            },
            {
                "job_id": 5,
                "score": 0.30,
                "role_title": "Senior Java Developer",
                "company_name": "OldSchool",
            },
        ][:top_k]

    mock = MagicMock()
    mock.search = search_side_effect
    return mock


@pytest.fixture
def scorer_with_mocks(
    test_db_session: Session,
    mock_embedding_pipeline: MagicMock,
) -> MatchScorer:
    """A MatchScorer with injected mock db and embedding pipeline."""
    return MatchScorer(embedding_pipeline=mock_embedding_pipeline, db=test_db_session)


# ====================================================================== #
# Sub-score: _skill_match_score
# ====================================================================== #


class TestSkillMatchScore:
    def test_full_overlap(self):
        """All user skills appear in the job requirements."""
        score, matches, gaps = MatchScorer._skill_match_score(
            ["Python", "FastAPI", "PostgreSQL"],
            "Python, FastAPI, PostgreSQL",
            embedding_sim=0.0,
        )
        expected = (1.0 - EMBEDDING_BLEND_RATIO) * 1.0 + EMBEDDING_BLEND_RATIO * 0.0
        assert math.isclose(score, expected, rel_tol=1e-4)
        assert len(matches) == 3
        assert len(gaps) == 0

    def test_partial_overlap(self):
        """Some user skills match the job requirements, some don't."""
        score, matches, gaps = MatchScorer._skill_match_score(
            ["Python", "FastAPI", "React"],
            "Python, FastAPI, PostgreSQL, Docker",
            embedding_sim=0.0,
        )
        expected = (1.0 - EMBEDDING_BLEND_RATIO) * 0.5 + EMBEDDING_BLEND_RATIO * 0.0
        assert math.isclose(score, expected, rel_tol=1e-4)
        assert len(matches) == 2
        assert len(gaps) == 2

    def test_zero_overlap(self):
        """No user skills match the job requirements."""
        score, matches, gaps = MatchScorer._skill_match_score(
            ["React", "CSS"],
            "Python, FastAPI, PostgreSQL",
            embedding_sim=0.0,
        )
        expected = (1.0 - EMBEDDING_BLEND_RATIO) * 0.0 + EMBEDDING_BLEND_RATIO * 0.0
        assert math.isclose(score, expected, rel_tol=1e-4)
        assert len(matches) == 0
        assert len(gaps) == 3

    def test_empty_job_skills(self):
        """Job has no skills listed — should return neutral 0.5."""
        score, matches, gaps = MatchScorer._skill_match_score(
            ["Python", "FastAPI"],
            "",
            embedding_sim=0.0,
        )
        assert score == 0.5
        assert len(matches) == 0
        assert len(gaps) == 0

    def test_null_job_skills(self):
        """Job skills is empty string."""
        score, matches, gaps = MatchScorer._skill_match_score(
            ["Python"],
            "",
            embedding_sim=0.5,
        )
        assert score == 0.5
        assert len(matches) == 0

    def test_case_insensitive(self):
        """Skill matching should be case-insensitive."""
        score, matches, gaps = MatchScorer._skill_match_score(
            ["python", "FASTAPI"],
            "Python, fastapi",
            embedding_sim=0.0,
        )
        expected = (1.0 - EMBEDDING_BLEND_RATIO) * 1.0 + EMBEDDING_BLEND_RATIO * 0.0
        assert math.isclose(score, expected, rel_tol=1e-4)
        assert len(matches) == 2

    def test_with_embedding_similarity(self):
        """Embedding similarity blends correctly."""
        score, matches, gaps = MatchScorer._skill_match_score(
            ["Python"],
            "Python, FastAPI",
            embedding_sim=0.8,
        )
        expected = (1.0 - EMBEDDING_BLEND_RATIO) * (
            1.0 / 2.0
        ) + EMBEDDING_BLEND_RATIO * 0.8
        assert math.isclose(score, expected, rel_tol=1e-4)
        assert len(matches) == 1
        assert len(gaps) == 1


# ====================================================================== #
# Sub-score: _role_fit_score
# ====================================================================== #


class TestRoleFitScore:
    def test_exact_match(self):
        """Target role exactly matches job title."""
        score = MatchScorer._role_fit_score(
            ["Backend Developer Intern"],
            "Backend Developer Intern",
        )
        assert score > 0.5

    def test_partial_overlap(self):
        """Target role has partial word overlap with job title."""
        # "intern" is a stop-word, "ai" and "machine"/"learning" don't overlap
        score = MatchScorer._role_fit_score(
            ["AI Engineer Intern"],
            "Machine Learning Intern",
        )
        assert score == 0.0

        # Shared significant words: backend, developer
        score = MatchScorer._role_fit_score(
            ["Backend Developer"],
            "Senior Backend Developer",
        )
        assert score > 0.5

    def test_no_target_roles(self):
        """User has no target roles set."""
        score = MatchScorer._role_fit_score([], "Software Engineer")
        assert score == 0.5


# ====================================================================== #
# Sub-score: _experience_fit_score
# ====================================================================== #


class TestExperienceFitScore:
    def test_internship_mode_internship_listing(self):
        """Internship mode user applying to internship listing."""
        score = MatchScorer._experience_fit_score(
            "internship", "0-1 years", "internship"
        )
        assert score == 1.0

    def test_internship_unusual_high_experience(self):
        """Internship listing asking for 3+ years experience."""
        score = MatchScorer._experience_fit_score(
            "internship", "3+ years", "internship"
        )
        assert score == 0.5  # Unusual for an internship

    def test_mode_mismatch(self):
        """User is in internship mode but job is full-time."""
        score = MatchScorer._experience_fit_score("internship", "1-3 years", "job")
        assert score == 0.2

    def test_job_mode_entry_level(self):
        """Job mode user applying to job listing with entry-level requirements."""
        score = MatchScorer._experience_fit_score("job", "0-2 years", "job")
        assert score >= 0.9

    def test_job_mode_mid_level(self):
        """Job mode user applying to mid-level listing."""
        score = MatchScorer._experience_fit_score("job", "3-5 years", "job")
        assert score == 0.7

    def test_job_mode_senior_level(self):
        """Job mode user applying to senior listing (5+ years)."""
        score = MatchScorer._experience_fit_score("job", "5+ years", "job")
        assert score == 0.4

    def test_unparseable_experience(self):
        """Job has no parseable experience field."""
        score = MatchScorer._experience_fit_score("job", "Entry level - fresher", "job")
        assert score == 0.7

    def test_empty_experience(self):
        """Job experience field is empty."""
        score = MatchScorer._experience_fit_score("internship", "", "internship")
        assert score == 1.0


# ====================================================================== #
# Sub-score: _location_fit_score
# ====================================================================== #


class TestLocationFitScore:
    def test_remote_job_match(self):
        """Job is remote — should match any preference."""
        score = MatchScorer._location_fit_score(
            ["Bangalore"],
            "Remote",
        )
        assert score == 1.0

    def test_exact_city_match(self):
        """Job location matches one of the user's preferred cities."""
        score = MatchScorer._location_fit_score(
            ["Bangalore", "Mumbai"],
            "Bangalore, Karnataka",
        )
        assert score == 1.0

    def test_no_match(self):
        """Job location does not match any preference."""
        score = MatchScorer._location_fit_score(
            ["Bangalore", "Remote"],
            "Mumbai",
        )
        assert score == 0.3

    def test_no_preference(self):
        """User has no preferred locations set."""
        score = MatchScorer._location_fit_score([], "Bangalore")
        assert score == 0.5


# ====================================================================== #
# Sub-score: _stipend_salary_fit_score
# ====================================================================== #


class TestStipendSalaryFitScore:
    def test_meets_minimum(self):
        """Job stipend meets or exceeds the user's minimum."""
        score = MatchScorer._stipend_salary_fit_score("internship", 20000, "25000")
        assert score == 1.0

    def test_below_minimum(self):
        """Job stipend is below the user's minimum."""
        score = MatchScorer._stipend_salary_fit_score("internship", 50000, "30000")
        assert math.isclose(score, 30000 / 50000, rel_tol=1e-4)

    def test_unparseable_salary(self):
        """Job uses a non-numeric string like 'Competitive'."""
        score = MatchScorer._stipend_salary_fit_score(
            "internship", 20000, "Competitive"
        )
        assert score == 0.5

    def test_no_minimum_set(self):
        """User has no minimum stipend set."""
        score = MatchScorer._stipend_salary_fit_score("internship", None, "30000")
        assert score == 0.5

    def test_currency_symbols(self):
        """Job salary includes currency symbols and commas."""
        score = MatchScorer._stipend_salary_fit_score("internship", 20000, "₹25,000")
        assert score == 1.0

    def test_empty_string(self):
        """Job stipend is empty string."""
        score = MatchScorer._stipend_salary_fit_score("internship", 20000, "")
        assert score == 0.5


# ====================================================================== #
# Sub-score: _company_signal_score
# ====================================================================== #


class TestCompanySignalScore:
    def test_detailed_jd_low_spam(self):
        """Detailed JD with low spam confidence."""
        job = MagicMock(spec=Job)
        job.jd_text = "A" * 3000
        job.spam_confidence = 0.05
        score = MatchScorer._company_signal_score(job)
        assert score > 0.5

    def test_short_jd_high_spam(self):
        """Short JD with high spam confidence."""
        job = MagicMock(spec=Job)
        job.jd_text = "Short"
        job.spam_confidence = 0.9
        score = MatchScorer._company_signal_score(job)
        assert score < 0.5

    def test_null_spam_confidence(self):
        """Job has no spam_confidence set."""
        job = MagicMock(spec=Job)
        job.jd_text = "Some text here"
        job.spam_confidence = None
        score = MatchScorer._company_signal_score(job)
        assert score >= 0.5

    def test_score_bounds(self):
        """Company signal score should never exceed [0, 1]."""
        job = MagicMock(spec=Job)
        job.jd_text = "A" * 10000
        job.spam_confidence = 0.0
        score = MatchScorer._company_signal_score(job)
        assert 0.0 <= score <= 1.0


# ====================================================================== #
# score_all_jobs
# ====================================================================== #


class TestScoreAllJobs:
    def test_raises_on_nonexistent_user(self, scorer_with_mocks: MatchScorer):
        """score_all_jobs raises ValueError for unknown user_id."""
        with pytest.raises(ValueError, match="not found"):
            scorer_with_mocks.score_all_jobs(999)

    def test_returns_sorted_results(
        self,
        scorer_with_mocks: MatchScorer,
        sample_user: User,
        sample_jobs: list[Job],
    ):
        """Results are sorted by match_score descending with deterministic tiebreaker."""
        results = scorer_with_mocks.score_all_jobs(sample_user.id)

        # Spam job (id=3) should be excluded
        job_ids = {r["job_id"] for r in results}
        assert 3 not in job_ids, "Spam job should be excluded"

        # Should have 4 non-spam jobs
        assert len(results) == 4

        # Check sorting
        for i in range(len(results) - 1):
            if results[i]["match_score"] == results[i + 1]["match_score"]:
                assert results[i]["job_id"] < results[i + 1]["job_id"]
            else:
                assert results[i]["match_score"] >= results[i + 1]["match_score"]

        # Ranks should be 1-indexed
        assert results[0]["rank"] == 1
        assert results[-1]["rank"] == len(results)

        # Each result should have all required fields
        for r in results:
            assert "job_id" in r
            assert "match_score" in r
            assert "skill_matches" in r
            assert "skill_gaps" in r
            assert "rank" in r
            assert isinstance(r["match_score"], float)
            assert 0.0 <= r["match_score"] <= 1.0

    def test_determinism(
        self,
        scorer_with_mocks: MatchScorer,
        sample_user: User,
        sample_jobs: list[Job],
    ):
        """Running score_all_jobs twice produces identical results."""
        results1 = scorer_with_mocks.score_all_jobs(sample_user.id)
        results2 = scorer_with_mocks.score_all_jobs(sample_user.id)

        json1 = json.dumps(results1, indent=2, sort_keys=True)
        json2 = json.dumps(results2, indent=2, sort_keys=True)

        assert json1 == json2, (
            "Determinism test failed: running score_all_jobs twice "
            "produced different output."
        )

    def test_empty_jobs_list(
        self,
        test_db_session: Session,
        mock_embedding_pipeline: MagicMock,
        sample_user: User,
    ):
        """No non-spam jobs in the database returns empty list."""
        scorer = MatchScorer(
            embedding_pipeline=mock_embedding_pipeline, db=test_db_session
        )
        results = scorer.score_all_jobs(sample_user.id)
        assert results == []

    def test_best_match_for_internship_user(
        self,
        scorer_with_mocks: MatchScorer,
        sample_user: User,
        sample_jobs: list[Job],
    ):
        """The best matching job should be Backend Developer Intern (id=1)
        because it has 3/3 skill overlap (Python, FastAPI, PostgreSQL)
        vs 1/3 for the AI Engineer Intern role."""
        results = scorer_with_mocks.score_all_jobs(sample_user.id)
        top = results[0]
        assert (
            top["job_id"] == 1
        ), f"Expected job_id=1 (Backend Developer Intern), got {top}"


# ====================================================================== #
# save_results
# ====================================================================== #


class TestSaveResults:
    def test_creates_new_applications(
        self,
        scorer_with_mocks: MatchScorer,
        test_db_session: Session,
        sample_user: User,
        sample_jobs: list[Job],
    ):
        """save_results creates Application rows for new user+job combinations."""
        results = scorer_with_mocks.score_all_jobs(sample_user.id)
        scorer_with_mocks.save_results(sample_user.id, results)

        apps = test_db_session.query(Application).all()
        assert len(apps) == len(results)

        for app in apps:
            assert app.match_score is not None
            assert app.skill_gaps is not None
            assert app.skill_matches is not None
            assert app.rank is not None
            assert app.status == "pending"

    def test_updates_existing_application(
        self,
        scorer_with_mocks: MatchScorer,
        test_db_session: Session,
        sample_user: User,
        sample_jobs: list[Job],
    ):
        """Running save_results twice should update, not create duplicates."""
        results = scorer_with_mocks.score_all_jobs(sample_user.id)

        scorer_with_mocks.save_results(sample_user.id, results)
        count_first = test_db_session.query(Application).count()

        scorer_with_mocks.save_results(sample_user.id, results)
        count_second = test_db_session.query(Application).count()

        assert count_first == count_second, (
            f"Expected same count after second save, "
            f"got {count_first} vs {count_second}"
        )

    def test_stores_json_gaps_and_matches(
        self,
        scorer_with_mocks: MatchScorer,
        test_db_session: Session,
        sample_user: User,
        sample_jobs: list[Job],
    ):
        """skill_gaps and skill_matches are stored as valid JSON strings."""
        results = scorer_with_mocks.score_all_jobs(sample_user.id)
        scorer_with_mocks.save_results(sample_user.id, results)

        apps = test_db_session.query(Application).all()
        for app in apps:
            gaps = json.loads(app.skill_gaps)
            matches = json.loads(app.skill_matches)
            assert isinstance(gaps, list)
            assert isinstance(matches, list)


# ====================================================================== #
# Helper functions
# ====================================================================== #


class TestParseYearRange:
    def test_range_format(self):
        assert _parse_year_range("0-1 years") == (0, 1)

    def test_plus_format(self):
        min_y, max_y = _parse_year_range("5+ years")
        assert min_y == 5
        assert max_y is not None and max_y > 5

    def test_single_value(self):
        assert _parse_year_range("2 years") == (2, 2)

    def test_empty_string(self):
        assert _parse_year_range("") == (None, None)

    def test_non_numeric(self):
        assert _parse_year_range("Entry level") == (None, None)


class TestParseNumericSalary:
    def test_simple_number(self):
        assert _parse_numeric_salary("30000") == 30000.0

    def test_with_currency(self):
        assert _parse_numeric_salary("₹25,000") == 25000.0

    def test_dollar_sign(self):
        assert _parse_numeric_salary("$50,000") == 50000.0

    def test_non_numeric(self):
        assert _parse_numeric_salary("Competitive") is None

    def test_empty_string(self):
        assert _parse_numeric_salary("") is None


class TestSignificantWords:
    def test_removes_stop_words(self):
        words = _significant_words("Senior Software Engineer Intern")
        assert "senior" not in words  # stop word
        assert "software" in words
        assert "intern" not in words  # stop word

    def test_empty_string(self):
        assert _significant_words("") == set()
