"""
Tests for the embedding pipeline.
"""

import json
import os
import tempfile
from datetime import datetime
from typing import Generator

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.models import Base
from src.models.job import Job
from src.pipelines.embedding_pipeline import EmbeddingPipeline


class FakeEmbeddingModel:
    """Small deterministic embedding model for offline unit tests."""

    def get_embedding_dimension(self) -> int:
        return 384

    def encode(self, text: str, convert_to_numpy: bool = True) -> np.ndarray:
        vector = np.zeros(self.get_embedding_dimension(), dtype=np.float32)
        for index, byte in enumerate(text.encode("utf-8")):
            vector[index % len(vector)] += byte / 255.0
        return vector


@pytest.fixture
def fake_model() -> FakeEmbeddingModel:
    """Return a deterministic local embedding model."""
    return FakeEmbeddingModel()


@pytest.fixture
def temp_index_dir() -> Generator[str, None, None]:
    """Create a temporary directory for test indices."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def test_db_session() -> Generator[Session, None, None]:
    """Create an in-memory SQLite database for testing."""
    # Use SQLite in-memory for fast tests
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    TestSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db = TestSessionLocal()

    yield db

    db.close()


@pytest.fixture
def sample_jobs(test_db_session: Session) -> list[Job]:
    """Create sample non-spam jobs for testing."""
    jobs = [
        Job(
            id=1,
            company_name="TechCorp",
            role_title="Software Engineer",
            jd_text="We are looking for a skilled software engineer with Python experience.",
            skills_required="Python, FastAPI",
            experience_required="2-3 years",
            location="Remote",
            stipend_salary="₹60,000",
            application_url="https://example.com/apply",
            posting_date=datetime.now(),
            selection_process="Online Test, Interview",
            source="CareerPage",
            listing_type="job",
            is_spam=False,
            spam_confidence=0.1,
        ),
        Job(
            id=2,
            company_name="WebSolutions",
            role_title="Frontend Developer",
            jd_text="Seeking a frontend developer with React and TypeScript skills.",
            skills_required="React, TypeScript, CSS",
            experience_required="1-2 years",
            location="Bangalore",
            stipend_salary="₹50,000",
            application_url="https://example.com/apply",
            posting_date=datetime.now(),
            selection_process="Take-home Test, Interview",
            source="JobBoard",
            listing_type="internship",
            is_spam=False,
            spam_confidence=0.05,
        ),
        Job(
            id=3,
            company_name="DataSystems",
            role_title="Data Scientist",
            jd_text="Looking for a data scientist to work on machine learning models.",
            skills_required="Python, ML, SQL",
            experience_required="3-4 years",
            location="Mumbai",
            stipend_salary="₹70,000",
            application_url="https://example.com/apply",
            posting_date=datetime.now(),
            selection_process="Coding Challenge, Interview",
            source="LinkedIn",
            listing_type="job",
            is_spam=False,
            spam_confidence=0.0,
        ),
        Job(
            id=4,
            company_name="SpamCorp",
            role_title="Fake Job",
            jd_text="This is spam content.",
            skills_required="None",
            experience_required="None",
            location="Unknown",
            stipend_salary="0",
            application_url="https://spam.com/apply",
            posting_date=datetime.now(),
            selection_process="None",
            source="Spam",
            listing_type="job",
            is_spam=True,
            spam_confidence=0.95,
        ),
    ]

    for job in jobs:
        test_db_session.add(job)
    test_db_session.commit()

    return jobs


def test_embed_text_normal(temp_index_dir: str, fake_model: FakeEmbeddingModel):
    """Test embed_text returns correct dimension for normal text."""
    pipeline = EmbeddingPipeline(index_dir=temp_index_dir, model=fake_model)

    text = "Software engineer with Python and FastAPI"
    embedding = pipeline.embed_text(text)

    assert isinstance(embedding, np.ndarray)
    assert embedding.dtype == np.float32
    assert len(embedding) == 384  # MiniLM-L6-v2 produces 384-dim embeddings
    assert not np.allclose(embedding, 0)  # Should not be zero-vector


def test_embed_text_empty_string(temp_index_dir: str, fake_model: FakeEmbeddingModel):
    """Test embed_text returns zero-vector for empty string."""
    pipeline = EmbeddingPipeline(index_dir=temp_index_dir, model=fake_model)

    embedding = pipeline.embed_text("")

    assert isinstance(embedding, np.ndarray)
    assert embedding.dtype == np.float32
    assert len(embedding) == 384
    assert np.allclose(embedding, 0)


def test_embed_text_none(temp_index_dir: str, fake_model: FakeEmbeddingModel):
    """Test embed_text returns zero-vector for None."""
    pipeline = EmbeddingPipeline(index_dir=temp_index_dir, model=fake_model)

    embedding = pipeline.embed_text(None)

    assert isinstance(embedding, np.ndarray)
    assert embedding.dtype == np.float32
    assert len(embedding) == 384
    assert np.allclose(embedding, 0)


def test_embed_text_very_short(temp_index_dir: str, fake_model: FakeEmbeddingModel):
    """Test embed_text returns zero-vector for very short text."""
    pipeline = EmbeddingPipeline(index_dir=temp_index_dir, model=fake_model)

    embedding = pipeline.embed_text("a")

    assert isinstance(embedding, np.ndarray)
    assert embedding.dtype == np.float32
    assert len(embedding) == 384
    assert np.allclose(embedding, 0)


def test_build_index_creates_files(
    temp_index_dir: str,
    test_db_session: Session,
    sample_jobs: list[Job],
    fake_model: FakeEmbeddingModel,
    monkeypatch,
):
    """Test build_index creates index and metadata files."""
    # Monkeypatch the database session to use our test session
    from src.config import database

    original_session_local = database.SessionLocal

    def mock_session_local():
        return test_db_session

    monkeypatch.setattr(database, "SessionLocal", mock_session_local)

    pipeline = EmbeddingPipeline(index_dir=temp_index_dir, model=fake_model)
    pipeline.build_index()

    # Check files were created
    assert os.path.exists(pipeline.index_path)
    assert os.path.exists(pipeline.metadata_path)

    # Check index is loaded
    assert pipeline.index is not None

    # Check metadata file content
    with open(pipeline.metadata_path, "r") as f:
        metadata = json.load(f)

    assert len(metadata) == 3  # 3 non-spam jobs
    assert metadata[0]["job_id"] == 1
    assert metadata[0]["role_title"] == "Software Engineer"
    assert metadata[0]["company_name"] == "TechCorp"

    # Restore original session
    monkeypatch.setattr(database, "SessionLocal", original_session_local)


def test_search_returns_ranked_results(
    temp_index_dir: str,
    test_db_session: Session,
    sample_jobs: list[Job],
    fake_model: FakeEmbeddingModel,
    monkeypatch,
):
    """Test search returns results ranked by similarity score."""
    from src.config import database

    original_session_local = database.SessionLocal

    def mock_session_local():
        return test_db_session

    monkeypatch.setattr(database, "SessionLocal", mock_session_local)

    pipeline = EmbeddingPipeline(index_dir=temp_index_dir, model=fake_model)
    pipeline.build_index()

    results = pipeline.search("Python developer job", top_k=5)

    assert len(results) > 0
    # Results should be ranked by descending score
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)

    # Results should have required fields
    for result in results:
        assert "job_id" in result
        assert "role_title" in result
        assert "company_name" in result
        assert "score" in result

    # Restore original session
    monkeypatch.setattr(database, "SessionLocal", original_session_local)


def test_search_works_after_reloading_saved_index(
    temp_index_dir: str,
    test_db_session: Session,
    sample_jobs: list[Job],
    fake_model: FakeEmbeddingModel,
    monkeypatch,
):
    """Test search works after loading index and metadata from disk."""
    from src.config import database

    original_session_local = database.SessionLocal

    def mock_session_local():
        return test_db_session

    monkeypatch.setattr(database, "SessionLocal", mock_session_local)

    pipeline = EmbeddingPipeline(index_dir=temp_index_dir, model=fake_model)
    pipeline.build_index()

    reloaded_pipeline = EmbeddingPipeline(index_dir=temp_index_dir, model=fake_model)
    results = reloaded_pipeline.search("Python developer job", top_k=5)

    assert len(results) > 0
    for result in results:
        assert "job_id" in result
        assert "role_title" in result
        assert "company_name" in result
        assert "score" in result

    # Restore original session
    monkeypatch.setattr(database, "SessionLocal", original_session_local)


def test_search_raises_without_index(
    temp_index_dir: str, fake_model: FakeEmbeddingModel
):
    """Test search raises RuntimeError when index not built."""
    pipeline = EmbeddingPipeline(index_dir=temp_index_dir, model=fake_model)

    with pytest.raises(RuntimeError) as exc_info:
        pipeline.search("Some query")

    assert "build_index()" in str(exc_info.value)


def test_search_with_large_top_k(
    temp_index_dir: str,
    test_db_session: Session,
    sample_jobs: list[Job],
    fake_model: FakeEmbeddingModel,
    monkeypatch,
):
    """Test search with top_k larger than number of indexed items."""
    from src.config import database

    original_session_local = database.SessionLocal

    def mock_session_local():
        return test_db_session

    monkeypatch.setattr(database, "SessionLocal", mock_session_local)

    pipeline = EmbeddingPipeline(index_dir=temp_index_dir, model=fake_model)
    pipeline.build_index()

    # Request more results than exist
    results = pipeline.search("Python developer", top_k=100)

    # Should return at most 3 non-spam jobs
    assert len(results) <= 3

    # Restore original session
    monkeypatch.setattr(database, "SessionLocal", original_session_local)


def test_build_index_no_jobs(
    temp_index_dir: str,
    test_db_session: Session,
    fake_model: FakeEmbeddingModel,
    monkeypatch,
):
    """Test build_index with no non-spam jobs in database."""
    from src.config import database

    original_session_local = database.SessionLocal

    def mock_session_local():
        return test_db_session

    monkeypatch.setattr(database, "SessionLocal", mock_session_local)

    pipeline = EmbeddingPipeline(index_dir=temp_index_dir, model=fake_model)
    # Database is empty, should not crash
    pipeline.build_index()

    # Index should remain None
    assert pipeline.index is None

    # Restore original session
    monkeypatch.setattr(database, "SessionLocal", original_session_local)
