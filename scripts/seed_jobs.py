"""
Seed script for local testing of the embedding pipeline.

Inserts realistic fake job rows directly into the jobs table so downstream
pipelines can be built and tested without depending on live scraped data.
"""

from src.config.database import SessionLocal
from src.models.job import Job

SEED_JOBS = [
    dict(
        company_name="Anthropic",
        role_title="AI Engineer Intern",
        jd_text="We are looking for an AI Engineer Intern with experience in Python, LangChain, and building RAG pipelines. You will work on multi-agent systems using LangGraph.",
        skills_required="Python, LangChain, RAG, LangGraph",
        experience_required="0-1 years",
        location="Remote",
        stipend_salary="30000",
        application_url="https://example.com/job1",
        source="seed",
        listing_type="internship",
        is_spam=False,
        spam_confidence=0.05,
    ),
    dict(
        company_name="Notion",
        role_title="Backend Engineer",
        jd_text="Backend engineer role focused on FastAPI, PostgreSQL, and building scalable APIs for our collaboration platform.",
        skills_required="Python, FastAPI, PostgreSQL, Docker",
        experience_required="1-3 years",
        location="Bangalore",
        stipend_salary="1200000",
        application_url="https://example.com/job2",
        source="seed",
        listing_type="job",
        is_spam=False,
        spam_confidence=0.03,
    ),
    dict(
        company_name="Groq",
        role_title="ML Infrastructure Engineer",
        jd_text="Work on inference infrastructure for large language models. Experience with vector databases and embedding pipelines a plus.",
        skills_required="Python, FAISS, vector databases, ML infra",
        experience_required="2-4 years",
        location="Remote",
        stipend_salary="1800000",
        application_url="https://example.com/job3",
        source="seed",
        listing_type="job",
        is_spam=False,
        spam_confidence=0.02,
    ),
    dict(
        company_name="StealthCo",
        role_title="Rockstar Ninja Developer",
        jd_text="We need a rockstar ninja developer. Great pay. Must be passionate and a self-starter.",
        skills_required="",
        experience_required="",
        location="",
        stipend_salary="",
        application_url="https://example.com/job4",
        source="seed",
        listing_type="job",
        is_spam=True,
        spam_confidence=0.91,
    ),
    dict(
        company_name="Newton School",
        role_title="Full Stack Developer Intern",
        jd_text="Full stack intern role. React frontend, FastAPI backend, PostgreSQL database. Great for students building agentic AI applications.",
        skills_required="React, FastAPI, PostgreSQL, TailwindCSS",
        experience_required="0-1 years",
        location="Bangalore",
        stipend_salary="20000",
        application_url="https://example.com/job5",
        source="seed",
        listing_type="internship",
        is_spam=False,
        spam_confidence=0.08,
    ),
    dict(
        company_name="Perplexity",
        role_title="GenAI Engineer",
        jd_text="Build retrieval augmented generation systems and semantic search over large document corpora using embeddings.",
        skills_required="Python, embeddings, semantic search, LangChain",
        experience_required="1-3 years",
        location="Remote",
        stipend_salary="2000000",
        application_url="https://example.com/job6",
        source="seed",
        listing_type="job",
        is_spam=False,
        spam_confidence=0.04,
    ),
]


def seed():
    db = SessionLocal()
    try:
        existing = db.query(Job).count()
        if existing > 0:
            print(
                f"jobs table already has {existing} rows — skipping seed to avoid duplicates."
            )
            return
        for data in SEED_JOBS:
            db.add(Job(**data))
        db.commit()
        print(f"Seeded {len(SEED_JOBS)} jobs.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
