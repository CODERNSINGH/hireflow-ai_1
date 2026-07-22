"""
Tests for the User Profile Onboarding API.

These tests use an in-memory SQLite database so they require no real
PostgreSQL instance.  The `get_db` FastAPI dependency is overridden
with a SQLite session factory that creates all tables fresh for each
test run.

The PDF extraction test mocks `llm_client.extract` so it does not
require a real API key.

Run:
    pytest tests/test_profile_api.py -v
"""

from __future__ import annotations

import io
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# ---------------------------------------------------------------------------
# SQLite does not understand PostgreSQL's JSONB type.
# Patch SQLiteTypeCompiler BEFORE importing any models so that JSONB columns
# are compiled as regular JSON when creating tables in the in-memory SQLite
# engine used for testing.  This is a test-only shim; production still uses
# the real JSONB column against PostgreSQL.
# ---------------------------------------------------------------------------
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler  # noqa: E402


def _visit_JSONB(self, type_, **kw):  # noqa: N802
    """Teach SQLite's DDL compiler to render JSONB as JSON."""
    return self.visit_JSON(type_, **kw)


SQLiteTypeCompiler.visit_JSONB = _visit_JSONB

# Now it is safe to import models and the app.
# All model modules must be imported here so their table definitions are
# registered on Base.metadata before create_all() is called.
import src.models.user  # noqa: F401, E402
import src.models.job  # noqa: F401, E402
import src.models.application  # noqa: F401, E402
import src.models.prep_guide  # noqa: F401, E402
import src.models.report  # noqa: F401, E402

from src.api.main import app  # noqa: E402
from src.config.database import get_db  # noqa: E402
from src.models import Base  # noqa: E402

# --------------------------------------------------------------------------- #
# In-memory SQLite test database
# --------------------------------------------------------------------------- #
# IMPORTANT: SQLite :memory: databases are per-connection — each new
# connection gets a fresh, empty DB.  Using StaticPool forces SQLAlchemy to
# reuse one shared connection so that create_all() and every test session
# operate on the exact same in-memory database.
# --------------------------------------------------------------------------- #

from sqlalchemy.pool import StaticPool  # noqa: E402

SQLITE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db() -> Generator[Session, None, None]:
    """Replace the real PostgreSQL session with an in-memory SQLite session."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Override the dependency before the TestClient is created
app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_database():
    """Create all tables before each test and drop them afterwards."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# --------------------------------------------------------------------------- #
# Helper: minimal valid JSON payload
# --------------------------------------------------------------------------- #


def _valid_json_payload(**overrides) -> dict:
    base = {
        "name": "Arjun Sharma",
        "email": "arjun@example.com",
        "mode": "internship",
        "skills": ["Python", "FastAPI"],
        "target_roles": ["Backend Engineer"],
        "weekly_quota": 10,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Test 1: JSON profile creation — happy path
# --------------------------------------------------------------------------- #


def test_create_profile_json(client: TestClient):
    """POST /profile with a valid JSON body should return 201 with an id."""
    payload = _valid_json_payload()
    response = client.post("/profile", json=payload)

    assert response.status_code == 201, response.text
    data = response.json()

    assert "id" in data
    assert isinstance(data["id"], int)
    assert data["name"] == "Arjun Sharma"
    assert data["email"] == "arjun@example.com"
    assert data["mode"] == "internship"
    assert data["weekly_quota"] == 10


# --------------------------------------------------------------------------- #
# Test 2: Mode validation — bad value should return 422
# --------------------------------------------------------------------------- #


def test_mode_validation_rejects_bad_value(client: TestClient):
    """POST /profile with an invalid mode should return 422."""
    payload = _valid_json_payload(mode="freelance")
    response = client.post("/profile", json=payload)

    assert response.status_code == 422, response.text
    # FastAPI's validation error body contains a 'detail' list
    detail = response.json().get("detail", [])
    assert any(
        "mode" in str(err).lower() for err in detail
    ), f"Expected a mode-related error in detail, got: {detail}"


# --------------------------------------------------------------------------- #
# Test 3: confirmation_mode defaults to "batch"
# --------------------------------------------------------------------------- #


def test_confirmation_mode_defaults_to_batch(client: TestClient):
    """POST /profile without confirmation_mode should default to 'batch'."""
    payload = _valid_json_payload()
    # Explicitly exclude confirmation_mode — it must default to "batch"
    payload.pop("confirmation_mode", None)

    response = client.post("/profile", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["confirmation_mode"] == "batch"


# --------------------------------------------------------------------------- #
# Test 4: GET /profile/{user_id} — retrieve created user
# --------------------------------------------------------------------------- #


def test_get_profile_returns_user(client: TestClient):
    """Create a profile via POST then retrieve it via GET."""
    create_resp = client.post("/profile", json=_valid_json_payload())
    assert create_resp.status_code == 201
    user_id = create_resp.json()["id"]

    get_resp = client.get(f"/profile/{user_id}")
    assert get_resp.status_code == 200, get_resp.text

    data = get_resp.json()
    assert data["id"] == user_id
    assert data["email"] == "arjun@example.com"
    assert data["mode"] == "internship"


# --------------------------------------------------------------------------- #
# Test 5: GET /profile/{user_id} — 404 for unknown id
# --------------------------------------------------------------------------- #


def test_get_profile_not_found(client: TestClient):
    """GET /profile/99999 should return 404 when the user does not exist."""
    response = client.get("/profile/99999")
    assert response.status_code == 404, response.text
    assert "not found" in response.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# Test 6: PDF upload — LLM extraction mocked
# --------------------------------------------------------------------------- #


def test_create_profile_pdf_with_mocked_llm(client: TestClient):
    """POST /profile/upload with a PDF should create a user.

    The LLM extract() call is mocked so this test works without any real
    API key.  We also patch _extract_pdf_text so we don't need a valid PDF.
    """
    mocked_llm_data = {
        "name": "Priya Mehta",
        "email": "priya@example.com",
        "skills": ["Machine Learning", "PyTorch"],
        "target_roles": ["ML Engineer", "Data Scientist"],
        "education": [
            {"institution": "IIT Delhi", "degree": "B.Tech CS", "year": "2024"}
        ],
        "experience": [],
        "summary": "Aspiring ML engineer with strong fundamentals.",
    }

    # Create a minimal fake PDF bytes (TestClient doesn't care about content
    # because we mock both PDF parsing and LLM extraction)
    fake_pdf = io.BytesIO(b"%PDF-1.4 fake content")

    mock_llm_instance = MagicMock()
    mock_llm_instance.extract.return_value = mocked_llm_data

    with (
        patch("src.api.routes.profile.get_llm_client", return_value=mock_llm_instance),
        patch(
            "src.api.routes.profile._extract_pdf_text",
            return_value="Fake resume text extracted from PDF",
        ),
    ):
        response = client.post(
            "/profile/upload",
            data={
                "mode": "job",
                "weekly_quota": "5",
            },
            files={"file": ("resume.pdf", fake_pdf, "application/pdf")},
        )

    assert response.status_code == 201, response.text
    data = response.json()

    assert data["name"] == "Priya Mehta"
    assert data["email"] == "priya@example.com"
    assert data["mode"] == "job"

    # master_profile should contain LLM-extracted data
    master = data.get("master_profile", {})
    assert "ML Engineer" in master.get("target_roles", [])
    assert "raw_resume_text" in master  # audit trail is stored


# --------------------------------------------------------------------------- #
# Test 7: Duplicate email check
# --------------------------------------------------------------------------- #


def test_create_profile_duplicate_email(client: TestClient):
    """POST /profile with an already registered email should return 400."""
    payload = _valid_json_payload(email="duplicate@example.com")

    # Create the first one
    resp1 = client.post("/profile", json=payload)
    assert resp1.status_code == 201

    # Try creating the second one with the same email
    resp2 = client.post("/profile", json=payload)
    assert resp2.status_code == 400, resp2.text
    assert "already registered" in resp2.json()["detail"].lower()
