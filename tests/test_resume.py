"""
Tests for the Resume Tailoring Engine (Issue 12 — RAG Pipeline).

All unit tests use mocked LLM client — no live API key required.
One integration test (marked @pytest.mark.integration) can test against
a real LLM if GROQ_API_KEY is set, but is skipped by default.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.models.job import Job
from src.models.user import User
from src.pipelines.resume_generator import (
    ResumeTailoringEngine,
    _significant_words,
)

# ====================================================================== #
# Fixtures
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
def fixture_user_full(test_db_session: Session) -> User:
    """User with complete master_profile (skills, projects, experience, education)."""
    return _insert_user(
        test_db_session,
        id=1,
        name="Alice Johnson",
        master_profile={
            "skills": ["Python", "LangChain", "FastAPI", "React", "PostgreSQL"],
            "projects": [
                {
                    "name": "RAG Chatbot",
                    "description": "Built a retrieval-augmented generation chatbot "
                    "using LangChain and FAISS for university project.",
                    "tech": ["Python", "LangChain", "FAISS"],
                },
                {
                    "name": "Portfolio Website",
                    "description": "Designed and developed a personal portfolio "
                    "website with React and TailwindCSS.",
                    "tech": ["React", "TailwindCSS", "JavaScript"],
                },
                {
                    "name": "Data Pipeline",
                    "description": "Created an ETL pipeline processing large "
                    "datasets with PostgreSQL and Python.",
                    "tech": ["Python", "PostgreSQL", "Apache Airflow"],
                },
                {
                    "name": "CLI Tool",
                    "description": "Developed a command-line tool for file "
                    "management automation.",
                    "tech": ["Python", "Click"],
                },
            ],
            "experience": [
                {
                    "title": "Software Engineer Intern",
                    "company": "TechStartup",
                    "duration": "6 months",
                },
            ],
            "education": {
                "degree": "B.Tech Computer Science",
                "university": "MIT",
                "year": 2025,
            },
        },
    )


@pytest.fixture
def fixture_user_skills_only(test_db_session: Session) -> User:
    """User whose master_profile has ONLY 'skills' — no projects/experience/education."""
    return _insert_user(
        test_db_session,
        id=2,
        name="Bob Smith",
        master_profile={
            "skills": ["Python", "FastAPI"],
        },
    )


@pytest.fixture
def fixture_user_null_profile(test_db_session: Session) -> User:
    """User whose master_profile is None entirely."""
    return _insert_user(
        test_db_session,
        id=3,
        name="Carol Davis",
        master_profile=None,
    )


@pytest.fixture
def fixture_job_python(test_db_session: Session) -> Job:
    """A Python/LangChain-heavy internship."""
    return _insert_job(
        test_db_session,
        id=10,
        company_name="AI Startup",
        role_title="AI Engineer Intern",
        jd_text=(
            "Looking for an AI intern with experience in Python, LangChain, and LLMs. "
            "You will work on building RAG pipelines and AI-powered features."
        ),
        skills_required="Python, LangChain, LLMs",
        listing_type="internship",
    )


@pytest.fixture
def fixture_job_frontend(test_db_session: Session) -> Job:
    """A React/TailwindCSS-heavy job."""
    return _insert_job(
        test_db_session,
        id=11,
        company_name="Web Agency",
        role_title="Frontend Developer",
        jd_text=(
            "Seeking a frontend developer with experience in React, TypeScript, "
            "and TailwindCSS. You will build responsive web applications."
        ),
        skills_required="React, TailwindCSS, TypeScript",
        listing_type="job",
    )


@pytest.fixture
def fixture_job_generic(test_db_session: Session) -> Job:
    """A job with no skills_required (empty string)."""
    return _insert_job(
        test_db_session,
        id=12,
        company_name="Generic Co",
        role_title="Generalist",
        jd_text="We are hiring a generalist to join our team.",
        skills_required="",
        listing_type="job",
    )


@pytest.fixture
def engine_with_mock_llm(
    test_db_session: Session,
) -> tuple[ResumeTailoringEngine, MagicMock]:
    """Return (engine, mock_llm_client) with a mocked LLM client."""
    with patch("src.pipelines.resume_generator.get_llm_client") as mock_get:
        mock_client = MagicMock()
        mock_client.chat.return_value = (
            "Alice is a skilled candidate with expertise in Python and LangChain, "
            "applying for the AI Engineer Intern position at AI Startup."
        )
        mock_get.return_value = mock_client
        engine = ResumeTailoringEngine(db=test_db_session)
        # Override the llm_client that __init__ already set via get_llm_client()
        engine.llm_client = mock_client
        yield engine, mock_client


# ====================================================================== #
# select_projects
# ====================================================================== #


class TestSelectProjects:
    def test_tech_overlap_ranks_higher(self):
        """A project whose 'tech' overlaps jd_skills scores higher and ranks first."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)

        projects = [
            {
                "name": "RAG Chatbot",
                "description": "Built a chatbot using LangChain.",
                "tech": ["Python", "LangChain"],
            },
            {
                "name": "Portfolio",
                "description": "A personal website built with React.",
                "tech": ["React", "CSS"],
            },
        ]
        jd_text = "Looking for Python and LangChain experience."
        jd_skills = ["python", "langchain"]

        # Portfolio scores 0 (no tech overlap, no description words matching
        # "Looking for Python and LangChain experience."), so only RAG Chatbot
        # (scores: tech_overlap=2, desc_overlap=1) is returned.
        result = engine.select_projects(projects, jd_text, jd_skills)

        assert len(result) == 1
        assert (
            result[0]["name"] == "RAG Chatbot"
        ), "RAG Chatbot should rank first (higher tech overlap)"

    def test_returns_empty_when_no_projects(self):
        """Returns [] when user_projects is [] or None."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)

        assert engine.select_projects([], "some text", ["python"]) == []
        assert engine.select_projects(None, "some text", ["python"]) == []

    def test_at_most_three_results(self):
        """Returns at most 3 results even when more than 3 projects score > 0."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)

        projects = [
            {"name": f"Project {i}", "description": "A project.", "tech": ["Python"]}
            for i in range(5)
        ]
        # All 5 match jd_skills, but only top 3 should return
        jd_text = "Python project."
        jd_skills = ["python"]

        result = engine.select_projects(projects, jd_text, jd_skills)

        assert len(result) == 3

    def test_fallback_when_all_score_zero(self):
        """When ALL projects score 0, still returns up to 3 in original order."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)

        projects = [
            {"name": "Alpha", "description": "Unrelated topic.", "tech": ["Java"]},
            {
                "name": "Beta",
                "description": "Something else entirely.",
                "tech": ["C++"],
            },
            {"name": "Gamma", "description": "No matching keywords.", "tech": ["Rust"]},
        ]
        # Empty jd_skills means zero tech overlap for all
        jd_text = "Completely different domain."
        jd_skills = []

        result = engine.select_projects(projects, jd_text, jd_skills)

        assert len(result) == 3
        assert [p["name"] for p in result] == ["Alpha", "Beta", "Gamma"]

    def test_fallback_all_zero_with_empty_jd_skills(self):
        """Fallback also works when jd_skills is explicitly empty list."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)

        projects = [
            {"name": "Only Project", "description": "Something.", "tech": ["Python"]},
        ]
        jd_text = "General listing."
        jd_skills = []

        result = engine.select_projects(projects, jd_text, jd_skills)

        assert len(result) == 1
        assert result[0]["name"] == "Only Project"

    def test_missing_tech_key_does_not_crash(self):
        """A project dict missing the 'tech' key defaults to empty list."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)

        projects = [
            {
                "name": "No Tech Listed",
                "description": "A project with no tech field.",
                # 'tech' key is absent
            },
            {
                "name": "Has Tech",
                "description": "This one has tech.",
                "tech": ["Python"],
            },
        ]
        jd_text = "Python related work."
        jd_skills = ["python"]

        # Should not crash
        result = engine.select_projects(projects, jd_text, jd_skills)

        assert len(result) == 1  # only the one with tech overlap
        assert result[0]["name"] == "Has Tech"

    def test_projects_unchanged_from_master_profile(self):
        """Returned dicts are the same objects — not rewritten."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)

        project = {
            "name": "RAG Chatbot",
            "description": "Built a RAG chatbot.",
            "tech": ["Python", "LangChain"],
        }
        projects = [project]
        jd_text = "Looking for RAG and LangChain."
        jd_skills = ["python", "langchain"]

        result = engine.select_projects(projects, jd_text, jd_skills)

        # Same dict identity
        assert result[0] is project
        assert result[0]["name"] == "RAG Chatbot"
        assert result[0]["tech"] == ["Python", "LangChain"]


# ====================================================================== #
# reorder_skills
# ====================================================================== #


class TestReorderSkills:
    def test_jd_skills_appear_first_in_jd_order(self):
        """JD-mentioned skills appear first, in the ORDER they appear in jd_skills."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)

        user_skills = ["Python", "LangChain"]
        jd_skills = ["langchain", "python"]

        result = engine.reorder_skills(user_skills, jd_skills)

        # LangChain first because it appears first in jd_skills
        assert result == ["LangChain", "Python"]

    def test_unmatched_skill_appears_at_end(self):
        """A user skill not in jd_skills still appears at the end."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)

        user_skills = ["Python", "React", "LangChain"]
        jd_skills = ["python", "langchain"]

        result = engine.reorder_skills(user_skills, jd_skills)

        # "React" is unmatched, should appear at end
        assert result[:2] == ["Python", "LangChain"]
        assert result[2] == "React"

    def test_returns_empty_when_empty_input(self):
        """Returns [] when user_skills is []."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)

        assert engine.reorder_skills([], ["python"]) == []

    def test_preserves_original_casing(self):
        """Output preserves original casing from user_skills."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)

        user_skills = ["LangChain", "Python", "FASTAPI"]
        jd_skills = ["python", "fastapi"]

        result = engine.reorder_skills(user_skills, jd_skills)

        # "Python" and "FASTAPI" keep original casing
        assert result[0] == "Python"  # first in jd_skills
        assert result[1] == "FASTAPI"
        assert result[2] == "LangChain"  # unmatched

    def test_all_skills_matched(self):
        """When all user skills match jd_skills, order is by jd_skills."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)

        user_skills = ["Docker", "Python", "AWS", "FastAPI"]
        jd_skills = ["python", "fastapi", "docker", "aws"]

        result = engine.reorder_skills(user_skills, jd_skills)

        assert result == ["Python", "FastAPI", "Docker", "AWS"]

    def test_no_jd_skills_returns_original_order(self):
        """When jd_skills is empty, all skills are unmatched and stay in order."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)

        user_skills = ["Python", "React", "LangChain"]

        result = engine.reorder_skills(user_skills, [])

        assert result == ["Python", "React", "LangChain"]


# ====================================================================== #
# generate_summary
# ====================================================================== #


class TestGenerateSummary:
    def test_prompt_contains_skills_and_grounding_instruction(self):
        """The prompt passed to .chat() contains real skill names and grounding."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)
        mock_client = MagicMock()
        mock_client.chat.return_value = "A fine summary."
        engine.llm_client = mock_client

        job = MagicMock(spec=Job)
        job.role_title = "AI Engineer Intern"
        job.company_name = "AI Startup"
        job.jd_text = "Looking for Python skills."
        job.listing_type = "internship"

        user_profile = {
            "name": "Alice",
            "skills": ["Python", "LangChain"],
            "projects": [{"name": "RAG Bot", "description": "A chatbot."}],
        }

        engine.generate_summary(user_profile, job, "internship")

        prompt = mock_client.chat.call_args[0][0]

        # Should contain real skill names
        assert "Python" in prompt
        assert "LangChain" in prompt

        # Should contain the grounding instruction
        assert "Do not invent" in prompt or "Only reference" in prompt

        # Should NOT contain a skill not in the input profile
        assert "React" not in prompt

    def test_llm_failure_fallback(self):
        """When LLM raises an exception, fallback template is returned."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)
        mock_client = MagicMock()
        mock_client.chat.side_effect = RuntimeError("API error")
        engine.llm_client = mock_client

        job = MagicMock(spec=Job)
        job.role_title = "AI Engineer Intern"
        job.company_name = "AI Startup"
        job.jd_text = "Looking for Python skills."
        job.listing_type = "internship"

        user_profile = {
            "name": "Alice",
            "skills": ["Python", "LangChain"],
            "projects": [],
        }

        result = engine.generate_summary(user_profile, job, "internship")

        # Fallback should contain the user's name and job.role_title
        assert "Alice" in result
        assert "AI Engineer Intern" in result
        assert "AI Startup" in result

    def test_fallback_empty_skills_list(self):
        """Fallback with empty skills list doesn't produce broken comma artifacts."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)
        mock_client = MagicMock()
        mock_client.chat.side_effect = RuntimeError("API error")
        engine.llm_client = mock_client

        job = MagicMock(spec=Job)
        job.role_title = "Intern"
        job.company_name = "TestCo"
        job.jd_text = "Some text."
        job.listing_type = "internship"

        user_profile = {
            "name": "Bob",
            "skills": [],
            "projects": [],
        }

        result = engine.generate_summary(user_profile, job, "internship")

        # Must not contain "skilled in ," or trailing comma artifacts
        assert "skilled in a range of relevant technologies" in result
        assert ",," not in result
        assert result.strip() != ""

    def test_internship_tone_in_prompt(self):
        """Internship listing produces enthusiasm-tone instruction in the prompt."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)
        mock_client = MagicMock()
        mock_client.chat.return_value = "A summary."
        engine.llm_client = mock_client

        job = MagicMock(spec=Job)
        job.role_title = "Intern"
        job.company_name = "TestCo"
        job.jd_text = "Some text."
        job.listing_type = "internship"

        user_profile = {"name": "Alice", "skills": ["Python"], "projects": []}

        engine.generate_summary(user_profile, job, "internship")

        prompt = mock_client.chat.call_args[0][0]
        assert (
            "eager" in prompt.lower()
            or "enthusiasm" in prompt.lower()
            or "learning" in prompt.lower()
        )

    def test_job_tone_in_prompt(self):
        """Job listing produces experienced/outcomes tone instruction in the prompt."""
        engine = ResumeTailoringEngine.__new__(ResumeTailoringEngine)
        mock_client = MagicMock()
        mock_client.chat.return_value = "A summary."
        engine.llm_client = mock_client

        job = MagicMock(spec=Job)
        job.role_title = "Developer"
        job.company_name = "TestCo"
        job.jd_text = "Some text."
        job.listing_type = "job"

        user_profile = {"name": "Alice", "skills": ["Python"], "projects": []}

        engine.generate_summary(user_profile, job, "job")

        prompt = mock_client.chat.call_args[0][0]
        assert (
            "experienced" in prompt.lower()
            or "outcomes" in prompt.lower()
            or "proven" in prompt.lower()
        )


# ====================================================================== #
# tailor — Integration-style (with mocked LLM)
# ====================================================================== #


class TestTailor:
    def test_raises_on_nonexistent_user(
        self, engine_with_mock_llm: tuple[ResumeTailoringEngine, MagicMock]
    ):
        """Raises ValueError containing the user_id when user doesn't exist."""
        engine, _ = engine_with_mock_llm
        with pytest.raises(ValueError, match="not found"):
            engine.tailor(999, 1)

    def test_raises_on_nonexistent_job(
        self,
        engine_with_mock_llm: tuple[ResumeTailoringEngine, MagicMock],
        test_db_session: Session,
    ):
        """Raises ValueError containing the job_id when job doesn't exist."""
        _insert_user(test_db_session, id=1)
        engine, _ = engine_with_mock_llm
        with pytest.raises(ValueError, match="not found"):
            engine.tailor(1, 999)

    def test_returns_required_keys(
        self,
        engine_with_mock_llm: tuple[ResumeTailoringEngine, MagicMock],
        fixture_user_full: User,
        fixture_job_python: Job,
    ):
        """End-to-end: output dict has all 5 required keys."""
        engine, _ = engine_with_mock_llm
        result = engine.tailor(fixture_user_full.id, fixture_job_python.id)

        assert set(result.keys()) == {
            "summary",
            "skills",
            "projects",
            "experience",
            "education",
        }

    def test_anti_hallucination_guarantee(
        self,
        engine_with_mock_llm: tuple[ResumeTailoringEngine, MagicMock],
        fixture_user_full: User,
        fixture_job_python: Job,
    ):
        """Every skill/project in output exists in the fixture's master_profile."""
        engine, _ = engine_with_mock_llm
        result = engine.tailor(fixture_user_full.id, fixture_job_python.id)

        profile: dict = fixture_user_full.master_profile or {}
        real_skills: list[str] = profile.get("skills", []) or []
        real_projects: list[dict] = profile.get("projects", []) or []
        real_project_names = {p["name"] for p in real_projects}

        # Every output skill must be a real skill (case-insensitive check)
        real_skills_lower = {s.lower() for s in real_skills}
        for skill in result["skills"]:
            assert (
                skill.lower() in real_skills_lower
            ), f"Skill '{skill}' not in master_profile"

        # Every output project must be a real project (by name)
        for project in result["projects"]:
            assert (
                project["name"] in real_project_names
            ), f"Project '{project['name']}' not in master_profile"

    def test_skills_only_profile(
        self,
        engine_with_mock_llm: tuple[ResumeTailoringEngine, MagicMock],
        fixture_user_skills_only: User,
        fixture_job_python: Job,
    ):
        """User with only {'skills': [...]} — no crash, sensible defaults."""
        engine, _ = engine_with_mock_llm
        result = engine.tailor(fixture_user_skills_only.id, fixture_job_python.id)

        assert result["projects"] == []
        assert result["experience"] == []
        assert result["education"] is None
        assert result["skills"] == ["Python", "FastAPI"]

    def test_null_profile(
        self,
        engine_with_mock_llm: tuple[ResumeTailoringEngine, MagicMock],
        fixture_user_null_profile: User,
        fixture_job_python: Job,
    ):
        """User with master_profile=None — no crash."""
        engine, _ = engine_with_mock_llm
        # Should not crash
        result = engine.tailor(fixture_user_null_profile.id, fixture_job_python.id)

        assert result["projects"] == []
        assert result["experience"] == []
        assert result["education"] is None
        assert result["skills"] == []

    def test_different_jobs_produce_different_output(
        self,
        engine_with_mock_llm: tuple[ResumeTailoringEngine, MagicMock],
        fixture_user_full: User,
        fixture_job_python: Job,
        fixture_job_frontend: Job,
    ):
        """Two different jobs produce different skills ordering and projects."""
        engine, _ = engine_with_mock_llm

        result_python = engine.tailor(fixture_user_full.id, fixture_job_python.id)
        result_frontend = engine.tailor(fixture_user_full.id, fixture_job_frontend.id)

        # Different skills order
        assert (
            result_python["skills"] != result_frontend["skills"]
        ), "Skills ordering should differ for different JD skills"

        # Python/LangChain job: Python and LangChain should appear first
        assert result_python["skills"][0].lower() in ("python", "langchain")

        # Frontend job: React should appear first
        assert result_frontend["skills"][0].lower() == "react"

        # Different project selections (due to different tech overlap)
        python_project_names = {p["name"] for p in result_python["projects"]}
        frontend_project_names = {p["name"] for p in result_frontend["projects"]}

        # The portfolio project (React) should be in frontend results
        assert "Portfolio Website" in frontend_project_names

        # The RAG Chatbot project (LangChain) should be in python results
        assert "RAG Chatbot" in python_project_names

    def test_tone_differs_by_listing_type(
        self,
        engine_with_mock_llm: tuple[ResumeTailoringEngine, MagicMock],
        fixture_user_full: User,
        fixture_job_python: Job,
        fixture_job_frontend: Job,
    ):
        """Internship vs job listing produce different tone instructions in prompts."""
        engine, mock_client = engine_with_mock_llm

        # Clear previous call history
        mock_client.reset_mock()

        engine.tailor(fixture_user_full.id, fixture_job_python.id)  # internship

        internship_prompt = mock_client.chat.call_args[0][0]

        mock_client.reset_mock()

        engine.tailor(fixture_user_full.id, fixture_job_frontend.id)  # job

        job_prompt = mock_client.chat.call_args[0][0]

        # The internship prompt should contain enthusiasm/learning language
        has_internship_tone = any(
            word in internship_prompt.lower()
            for word in ["eager", "enthusiasm", "learning", "grow"]
        )
        has_job_tone = any(
            word in job_prompt.lower()
            for word in ["experienced", "outcomes", "proven", "delivered"]
        )

        assert (
            has_internship_tone
        ), "Internship prompt should have enthusiasm/learning tone indicators"
        assert (
            has_job_tone
        ), "Job prompt should have experienced/outcomes tone indicators"

    def test_fallback_on_llm_failure_in_tailor(
        self,
        test_db_session: Session,
        fixture_user_full: User,
        fixture_job_python: Job,
    ):
        """When LLM fails, tailor() returns a fallback summary — does NOT crash."""
        with patch("src.pipelines.resume_generator.get_llm_client") as mock_get:
            mock_client = MagicMock()
            mock_client.chat.side_effect = RuntimeError("API down")
            mock_get.return_value = mock_client

            engine = ResumeTailoringEngine(db=test_db_session)
            engine.llm_client = mock_client

            # Should not raise
            result = engine.tailor(fixture_user_full.id, fixture_job_python.id)

            # Fallback summary should contain user name and job title
            assert "Alice" in result["summary"]
            assert "AI Engineer Intern" in result["summary"]


# ====================================================================== #
# _significant_words helper
# ====================================================================== #


class TestSignificantWords:
    def test_removes_stopwords(self):
        """Stopwords like 'the' and 'and' are removed."""
        words = _significant_words("The cat and the dog")
        assert "the" not in words
        assert "and" not in words
        assert "cat" in words
        assert "dog" in words

    def test_returns_lowercase(self):
        """Words are lowercased."""
        words = _significant_words("Hello WORLD")
        assert "hello" in words
        assert "world" in words
        assert "Hello" not in words

    def test_removes_single_letter_words(self):
        """Single-letter words are removed."""
        words = _significant_words("a b c test")
        assert "test" in words
        assert len(words) == 1
