"""
Tests for the LaTeX PDF Generation and Resume Storage (Issue 13).

Tests marked with @pytest.mark.real_xelatex require a working xelatex
binary on PATH and will be skipped on machines without it.

All other tests use mocking and will pass without any LaTeX installation.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.pipelines.pdf_generator import PDFGenerator

# ====================================================================== #
# Helpers
# ====================================================================== #


def _xelatex_available() -> bool:
    """Check if xelatex is available on this system."""
    return shutil.which("xelatex") is not None


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
                resume_version INTEGER DEFAULT 1,
                status VARCHAR NOT NULL DEFAULT 'pending',
                failure_reason VARCHAR,
                applied_at DATETIME,
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
    location: str = "",
    application_url: str = "https://example.com/apply",
    source: str = "test",
    listing_type: str = "internship",
    is_spam: bool = False,
) -> Job:
    db.execute(
        text(
            "INSERT INTO jobs (id, company_name, role_title, jd_text, "
            "skills_required, location, application_url, posting_date, "
            "source, listing_type, is_spam, created_at) "
            "VALUES (:id, :cn, :rt, :jd, :sr, :loc, :au, :pd, "
            ":src, :lt, :spam, :ca)"
        ),
        {
            "id": id,
            "cn": company_name,
            "rt": role_title,
            "jd": jd_text,
            "sr": skills_required,
            "loc": location,
            "au": application_url,
            "pd": datetime.utcnow(),
            "src": source,
            "lt": listing_type,
            "spam": is_spam,
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
    status: str = "pending",
    resume_path: str | None = None,
    resume_version: int | None = None,
) -> Application:
    db.execute(
        text(
            "INSERT INTO applications (id, user_id, job_id, match_score, "
            "resume_path, resume_version, status, created_at) "
            "VALUES (:id, :uid, :jid, :ms, :rp, :rv, :st, :ca)"
        ),
        {
            "id": id,
            "uid": user_id,
            "jid": job_id,
            "ms": match_score,
            "rp": resume_path,
            "rv": resume_version,
            "st": status,
            "ca": datetime.utcnow(),
        },
    )
    db.commit()
    app = db.query(Application).filter(Application.id == id).first()
    assert app is not None, "Failed to create test application"
    return app


@pytest.fixture
def fixture_user(test_db_session: Session) -> User:
    return _insert_user(
        test_db_session,
        id=1,
        name="Alice Johnson",
        email="alice@example.com",
    )


@pytest.fixture
def fixture_job(test_db_session: Session) -> Job:
    return _insert_job(
        test_db_session,
        id=10,
        company_name="AI Startup",
        role_title="AI Engineer Intern",
        jd_text="Looking for Python and LangChain experience.",
        skills_required="Python, LangChain",
    )


@pytest.fixture
def fixture_application(
    test_db_session: Session, fixture_user: User, fixture_job: Job
) -> Application:
    return _insert_application(
        test_db_session,
        id=100,
        user_id=fixture_user.id,
        job_id=fixture_job.id,
        status="resume_pending",
    )


def _sample_resume_content() -> dict:
    """Return a realistic resume_content dict matching Issue 12 output shape."""
    return {
        "summary": "Alice is an experienced candidate skilled in Python and LangChain, "
        "applying for the AI Engineer Intern position at AI Startup.",
        "skills": ["Python", "LangChain", "FastAPI", "PostgreSQL"],
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
        ],
        "experience": [
            {
                "title": "Software Engineer Intern",
                "company": "TechStartup",
                "duration": "6 months",
                "description": "Worked on backend services with Python and FastAPI.",
            },
        ],
        "education": {
            "degree": "B.Tech Computer Science",
            "university": "MIT",
            "year": 2025,
        },
    }


@pytest.fixture
def mock_xelatex_on_path() -> Generator[None, None, None]:
    """Mock shutil.which('xelatex') to return a fake path."""
    with patch(
        "src.pipelines.pdf_generator.shutil.which", return_value="/usr/bin/xelatex"
    ):
        yield


# ====================================================================== #
# Test: _escape_latex
# ====================================================================== #


class TestEscapeLatex:
    def test_escapes_backslash(self):
        """Backslash is escaped first (before other chars)."""
        result = PDFGenerator._escape_latex("hello\\world")
        assert "\\textbackslash{}" in result

    def test_escapes_percent(self):
        """Percent sign is escaped."""
        result = PDFGenerator._escape_latex("50% improvement")
        assert "50\\% improvement" == result

    def test_escapes_ampersand(self):
        """Ampersand is escaped."""
        result = PDFGenerator._escape_latex("R&D")
        assert "R\\&D" == result

    def test_escapes_hash(self):
        """Hash symbol is escaped."""
        result = PDFGenerator._escape_latex("#1 priority")
        assert "\\#1 priority" == result

    def test_escapes_dollar(self):
        """Dollar sign is escaped."""
        result = PDFGenerator._escape_latex("$10K saved")
        assert "\\$10K saved" == result

    def test_escapes_underscore(self):
        """Underscore is escaped."""
        result = PDFGenerator._escape_latex("fast_api")
        assert "fast\\_api" == result

    def test_escapes_braces(self):
        """Curly braces are escaped."""
        result = PDFGenerator._escape_latex("{hello}")
        assert "\\{hello\\}" == result

    def test_escapes_tilde(self):
        """Tilde is escaped."""
        result = PDFGenerator._escape_latex("~tilde")
        assert "\\textasciitilde{}tilde" == result

    def test_escapes_caret(self):
        """Caret is escaped."""
        result = PDFGenerator._escape_latex("^caret")
        assert "\\textasciicircum{}caret" == result

    def test_no_special_chars_returns_unchanged(self):
        """Plain text with no special characters passes through unchanged."""
        result = PDFGenerator._escape_latex("Hello World")
        assert result == "Hello World"

    def test_mixed_special_chars(self):
        """Multiple special characters in one string are all escaped."""
        result = PDFGenerator._escape_latex("50% improvement & $10K saved (project_X)")
        assert "\\%" in result
        assert "\\&" in result
        assert "\\$" in result
        assert "\\_" in result

    def test_none_input_returns_empty_string(self):
        """None input is converted to empty string."""
        assert PDFGenerator._escape_latex(None) == ""

    def test_non_string_input_converted(self):
        """Non-string input (e.g. int) is converted to string."""
        assert PDFGenerator._escape_latex(42) == "42"


# ====================================================================== #
# Test: __init__ — xelatex check
# ====================================================================== #


class TestInit:
    def test_raises_runtime_error_when_xelatex_missing(self):
        """Raises clear RuntimeError when xelatex is not on PATH."""
        with patch("src.pipelines.pdf_generator.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="xelatex not found"):
                PDFGenerator()

    def test_initialises_with_xelatex_on_path(self, mock_xelatex_on_path):
        """Initialises successfully when xelatex is on PATH."""
        gen = PDFGenerator()
        assert gen is not None
        assert gen._xelatex_path == "/usr/bin/xelatex"


# ====================================================================== #
# Test: generate — ValueError for missing user/job
# ====================================================================== #


class TestGenerateValueErrors:
    def test_raises_on_nonexistent_user(
        self, mock_xelatex_on_path, test_db_session: Session
    ):
        """Raises ValueError when user_id doesn't exist."""
        gen = PDFGenerator(db=test_db_session)
        with pytest.raises(ValueError, match="User with id 999 not found"):
            gen.generate(999, 1, _sample_resume_content())

    def test_raises_on_nonexistent_job(
        self, mock_xelatex_on_path, test_db_session: Session, fixture_user: User
    ):
        """Raises ValueError when job_id doesn't exist."""
        gen = PDFGenerator(db=test_db_session)
        with pytest.raises(ValueError, match="Job with id 999 not found"):
            gen.generate(fixture_user.id, 999, _sample_resume_content())


# ====================================================================== #
# Test: _resolve_version
# ====================================================================== #


class TestResolveVersion:
    def test_no_existing_files_returns_1(
        self, mock_xelatex_on_path, test_db_session: Session
    ):
        """When no files exist and no DB record, version = 1."""
        gen = PDFGenerator(db=test_db_session)
        ver = gen._resolve_version(1, 10, 1, 10)
        # With no existing files and no DB records, both return 0, so result is 1.
        assert ver == 1

    def test_version_increments_on_disk(
        self, mock_xelatex_on_path, test_db_session: Session, tmp_path: Path
    ):
        """Mock filesystem vs DB resolution."""
        # _resolve_version is now an instance method that calls
        # _db_max_version_with_session (not a static _db_max_version).
        gen = PDFGenerator(db=test_db_session)
        with patch.object(PDFGenerator, "_filesystem_max_version", return_value=3):
            with patch.object(
                PDFGenerator, "_db_max_version_with_session", return_value=1
            ):
                ver = gen._resolve_version(1, 10, 1, 10)
                assert ver == 4  # filesystem wins (3 > 1), so 4

    def test_version_db_takes_highest(
        self, mock_xelatex_on_path, test_db_session: Session, tmp_path: Path
    ):
        """When DB version is higher than filesystem, DB wins."""
        gen = PDFGenerator(db=test_db_session)
        with patch.object(PDFGenerator, "_filesystem_max_version", return_value=2):
            with patch.object(
                PDFGenerator, "_db_max_version_with_session", return_value=5
            ):
                ver = gen._resolve_version(1, 10, 1, 10)
                assert ver == 6  # DB wins (5 > 2), so 6


# ====================================================================== #
# Test: _safe_resume_content
# ====================================================================== #


class TestSafeResumeContent:
    def test_all_keys_present_passes_through(self):
        """Full dict with all keys passes through unchanged."""
        content = {
            "summary": "test",
            "skills": ["Python"],
            "projects": [{"name": "P1"}],
            "experience": [{"title": "E1"}],
            "education": {"degree": "B.Tech"},
        }
        safe = PDFGenerator._safe_resume_content(content)
        assert safe["summary"] == "test"
        assert safe["skills"] == ["Python"]
        assert safe["projects"] == [{"name": "P1"}]
        assert safe["experience"] == [{"title": "E1"}]
        assert safe["education"] == {"degree": "B.Tech"}

    def test_missing_keys_use_defaults(self):
        """Missing keys get safe defaults."""
        safe = PDFGenerator._safe_resume_content({})
        assert safe["summary"] == ""
        assert safe["skills"] == []
        assert safe["projects"] == []
        assert safe["experience"] == []
        assert safe["education"] is None

    def test_none_skills_converted_to_empty_list(self):
        """None skills become empty list (not None)."""
        safe = PDFGenerator._safe_resume_content({"skills": None, "projects": None})
        assert safe["skills"] == []
        assert safe["projects"] == []


# ====================================================================== #
# Test: generate — compilation failure
# ====================================================================== #


class TestGenerateCompilationFailure:
    def test_xelatex_failure_raises_runtime_error(
        self,
        mock_xelatex_on_path,
        test_db_session: Session,
        fixture_user: User,
        fixture_job: Job,
    ):
        """When xelatex returns nonzero exit code, raises RuntimeError."""
        gen = PDFGenerator(db=test_db_session)

        with patch.object(
            gen, "_compile_pdf", side_effect=RuntimeError("xelatex failed")
        ):
            with pytest.raises(RuntimeError, match="xelatex failed"):
                gen.generate(
                    fixture_user.id,
                    fixture_job.id,
                    _sample_resume_content(),
                )


# ====================================================================== #
# Test: generate — LaTeX special characters in content
# ====================================================================== #


class TestGenerateWithSpecialChars:
    def test_special_chars_in_content_do_not_crash(
        self,
        mock_xelatex_on_path,
        test_db_session: Session,
        fixture_user: User,
        fixture_job: Job,
    ):
        """Resume content with LaTeX special characters compiles successfully."""
        content = _sample_resume_content()
        content["summary"] = "50% improvement & $10K saved (project_X): done!"
        content["projects"] = [
            {
                "name": "C++ Project",
                "description": "Improved efficiency by 50% & saved $10K with #1 team.",
                "tech": ["C++", "Python"],
            },
        ]

        gen = PDFGenerator(db=test_db_session)

        with patch.object(gen, "_compile_pdf") as mock_compile:
            mock_compile.return_value = "/fake/path.pdf"
            # Should not crash
            result = gen.generate(
                fixture_user.id,
                fixture_job.id,
                content,
            )
            assert result == "/fake/path.pdf"

            # Verify that the template was rendered (didn't crash on escaping)
            mock_compile.assert_called_once()


# ====================================================================== #
# Test: generate — updates Application DB row
# ====================================================================== #


class TestGenerateDBUpdate:
    def test_updates_application_row(
        self,
        mock_xelatex_on_path,
        test_db_session: Session,
        fixture_user: User,
        fixture_job: Job,
        fixture_application: Application,
    ):
        """After successful generation, Application row has resume_path and version."""
        gen = PDFGenerator(db=test_db_session)

        with patch.object(gen, "_compile_pdf", return_value="/fake/path/v1.pdf"):
            with patch.object(PDFGenerator, "_resolve_version", return_value=1):
                gen.generate(
                    fixture_user.id,
                    fixture_job.id,
                    _sample_resume_content(),
                )

        # Refresh and check
        test_db_session.refresh(fixture_application)
        assert fixture_application.resume_path == "/fake/path/v1.pdf"
        assert fixture_application.resume_version == 1

    def test_no_application_row_logs_warning(
        self,
        mock_xelatex_on_path,
        test_db_session: Session,
        fixture_user: User,
        fixture_job: Job,
        caplog,
    ):
        """When no Application row exists, logs warning but doesn't crash."""
        gen = PDFGenerator(db=test_db_session)

        with patch.object(gen, "_compile_pdf", return_value="/fake/path/v1.pdf"):
            with patch.object(PDFGenerator, "_resolve_version", return_value=1):
                # Should not crash even though no Application row exists
                result = gen.generate(
                    fixture_user.id,
                    fixture_job.id,
                    _sample_resume_content(),
                )
                assert result == "/fake/path/v1.pdf"

        # Check that a warning was logged
        warning_messages = [
            record.message for record in caplog.records if record.levelname == "WARNING"
        ]
        assert any("No Application row found" in msg for msg in warning_messages)


# ====================================================================== #
# Test: real xelatex compilation (requires xelatex on PATH)
# ====================================================================== #


@pytest.mark.skipif(
    not _xelatex_available(), reason="xelatex not available on this system"
)
class TestRealCompilation:
    def test_generates_valid_pdf(
        self,
        test_db_session: Session,
        fixture_user: User,
        fixture_job: Job,
        tmp_path: Path,
    ):
        """Full resume content produces a non-empty PDF file."""
        gen = PDFGenerator(db=test_db_session)

        # Redirect data/resumes to tmp_path
        with patch("src.pipelines.pdf_generator._RESUMES_DIR", tmp_path):
            result = gen.generate(
                fixture_user.id,
                fixture_job.id,
                _sample_resume_content(),
            )

        assert os.path.exists(result)
        assert os.path.getsize(result) > 0, "PDF file is empty"

    def test_generates_valid_pdf_without_experience_and_education(
        self,
        test_db_session: Session,
        fixture_user: User,
        fixture_job: Job,
        tmp_path: Path,
    ):
        """Missing experience/education still produces a valid PDF (sections omitted)."""
        content = _sample_resume_content()
        content["experience"] = []
        content["education"] = None

        gen = PDFGenerator(db=test_db_session)

        with patch("src.pipelines.pdf_generator._RESUMES_DIR", tmp_path):
            result = gen.generate(
                fixture_user.id,
                fixture_job.id,
                content,
            )

        assert os.path.exists(result)
        assert os.path.getsize(result) > 0, "PDF file is empty"

    def test_handles_long_description(
        self,
        test_db_session: Session,
        fixture_user: User,
        fixture_job: Job,
        tmp_path: Path,
    ):
        """A very long project description does not break compilation."""
        content = _sample_resume_content()
        content["projects"] = [
            {
                "name": "Very Long Description Project",
                "description": "A" * 500,  # 500-character description
                "tech": ["Python"],
            },
        ]

        gen = PDFGenerator(db=test_db_session)

        with patch("src.pipelines.pdf_generator._RESUMES_DIR", tmp_path):
            result = gen.generate(
                fixture_user.id,
                fixture_job.id,
                content,
            )

        assert os.path.exists(result)
        assert os.path.getsize(result) > 0, "PDF file is empty"

    def test_version_increments(
        self,
        test_db_session: Session,
        fixture_user: User,
        fixture_job: Job,
        tmp_path: Path,
    ):
        """Calling generate twice produces v1 then v2, both exist."""
        gen = PDFGenerator(db=test_db_session)

        with patch("src.pipelines.pdf_generator._RESUMES_DIR", tmp_path):
            # First call → version 1
            path1 = gen.generate(
                fixture_user.id,
                fixture_job.id,
                _sample_resume_content(),
            )
            assert "_v1.pdf" in path1

            # Create a corresponding Application row for second call
            _insert_application(
                test_db_session,
                id=101,
                user_id=fixture_user.id,
                job_id=fixture_job.id,
                status="resume_pending",
            )

            # Second call → version 2
            path2 = gen.generate(
                fixture_user.id,
                fixture_job.id,
                _sample_resume_content(),
            )
            assert "_v2.pdf" in path2

        assert os.path.exists(path1), f"v1 PDF missing: {path1}"
        assert os.path.exists(path2), f"v2 PDF missing: {path2}"
        assert os.path.getsize(path1) > 0
        assert os.path.getsize(path2) > 0

    def test_special_chars_compile_successfully(
        self,
        test_db_session: Session,
        fixture_user: User,
        fixture_job: Job,
        tmp_path: Path,
    ):
        """Resume content with special LaTeX chars still compiles."""
        content = _sample_resume_content()
        content["summary"] = (
            "Alice contributed to a 50% improvement in R&D efficiency "
            "& saved $10K (project_X) for the #1 client."
        )
        content["projects"] = [
            {
                "name": "C++ & Python",
                "description": "Led a {team} of 3: 50% improvement in build_time.",
                "tech": ["C++", "Python"],
            },
        ]

        gen = PDFGenerator(db=test_db_session)

        with patch("src.pipelines.pdf_generator._RESUMES_DIR", tmp_path):
            result = gen.generate(
                fixture_user.id,
                fixture_job.id,
                content,
            )

        assert os.path.exists(result)
        assert os.path.getsize(result) > 0, "PDF should compile successfully"


# ====================================================================== #
# Test: CLI entry point
# ====================================================================== #


class TestCLI:
    def test_cli_entry_point_exists(self):
        """The module can be imported and has a main() function."""
        from src.pipelines.pdf_generator import main

        assert callable(main)
