# HireFlow AI - Issues Tracker

All 26 issues from setup to deployment.
Copy each issue into GitHub Issues. Assign labels, milestone, and "Depends on" as noted.
All feature branches go into dev, not main.

---

## Issue 1 - Dev Environment Setup

Labels: infra, good first issue
Milestone: M1
Branch: feature/issue-1-dev-environment
Depends on: nothing - this is the starting point

### Why

Before you write a single line of code for HireFlow, your machine needs to speak the same language as everyone else on the pod. Mismatched Python versions, missing system packages, and wrong database configs are the most common reason a fresh clone fails to run. This issue exists so every pod member starts from exactly the same foundation.

This is not just setup. It is your first lesson in reproducible environments - one of the most important skills separating a student project from a production-ready one.

### What needs to be done

Set up your local development environment completely. By the end of this issue, you should be able to clone the repo, install all dependencies, and start the API server without any errors.

### Steps (do these in order)

1. Install Python 3.11 (`brew install python@3.11` on Mac)
2. Install Node.js 18 or higher (https://nodejs.org)
3. Install PostgreSQL 16 (`brew install postgresql@16`)
4. Install Docker Desktop (https://docker.com/desktop)
5. Clone the repo: `git clone git@github.com:newton-school-ai/hireflow-ai.git`
6. Switch to dev: `git checkout dev`
7. Create venv: `python3.11 -m venv venv && source venv/bin/activate`
8. Install dependencies: `pip install -r requirements.txt`
9. Install Playwright: `playwright install chromium`
10. Copy env file: `cp .env.example .env` and fill in Groq API key (free at console.groq.com)
11. Create database: `createdb hireflow`
    # Start PostgreSQL
    brew services start postgresql@16

    # Check if it's running
    brew services list

    # Stop PostgreSQL
    brew services stop postgresql@16

    # Restart PostgreSQL
    brew services restart postgresql@16

### How it affects overall development

Every subsequent issue depends on this. If your venv is not active, imports will fail. If PostgreSQL is not running, the API will crash on startup. If Playwright is not installed, scrapers cannot run. Getting this right once means you never debug environment issues again.

### How to test locally

```bash
# Verify Python version
python --version   # should be 3.11.x

# Verify venv is active
which python       # should show .../venv/bin/python

# Verify packages installed
pip list | grep langgraph

# Verify PostgreSQL is running
psql hireflow -c "SELECT 1;"

# Verify Playwright
python -c "from playwright.sync_api import sync_playwright; print('Playwright OK')"

# Start the API (will error on missing DB tables - that is expected until Issue 3)
uvicorn src.api.main:app --reload
```

### Acceptance Criteria

- [ ] Python 3.11 installed and active in venv
- [ ] All packages from requirements.txt installed without errors
- [ ] PostgreSQL running and hireflow database created
- [ ] Playwright chromium installed
- [ ] .env file created with at least LLM_PROVIDER and one API key filled in
- [ ] `uvicorn src.api.main:app --reload` starts without import errors

---

## Issue 2 - Repository Setup and CI/CD Workflow

Labels: infra, m1
Milestone: M1
Branch: feature/issue-2-ci-setup
Depends on: Issue 1

### Why

Right now if someone pushes broken code, no one finds out until another contributor pulls and their setup breaks. Automated CI (Continuous Integration) fixes this - every PR automatically runs the tests. If tests fail, the PR cannot merge.

This is also where you learn the branch strategy. Understanding why dev exists and why we never push directly to main is a mindset shift that changes how you think about collaborative coding.

### What needs to be built

Create GitHub Actions workflow files that run tests automatically on every PR. Also set up the dev branch as the default working branch.

### Files to create

- `.github/workflows/backend-ci.yml` - runs pytest on every PR to dev
- `.github/workflows/frontend-ci.yml` - runs Vitest and build check for frontend PRs

### How it affects overall development

Once this is merged, every PR you open will show a green checkmark or a red cross. Green means your code did not break existing tests. This is the safety net that lets 5 people work on the same codebase without constantly breaking each other's work.

### How to test locally

```bash
# Verify workflow files are valid YAML
python -c "import yaml; yaml.safe_load(open('.github/workflows/backend-ci.yml'))"

# Run the same test command that CI will run
pytest tests/ -v

# Push to a test branch and open a PR to dev - check that Actions tab shows the workflow running
```

### Acceptance Criteria

- [ ] `.github/workflows/backend-ci.yml` runs pytest on every PR targeting dev
- [ ] `.github/workflows/frontend-ci.yml` runs on frontend changes
- [ ] CI passes on a clean branch (no test failures)
- [ ] dev branch exists and is set as the default branch for new PRs
- [ ] main branch protection rule: require PR and passing CI before merge

---

## Issue 3 - Database Schema and Migrations

Labels: infra, m1
Milestone: M1
Branch: feature/issue-3-db-schema
Depends on: Issue 1

### Why

Think of the database as the memory of HireFlow. Every user profile, every scraped job, every application sent, every prep guide generated - all of it lives in the database. If the schema is wrong or incomplete, modules that come later will have nowhere to store their data.

We are using Alembic for migrations instead of running raw SQL directly. The reason: when 5 contributors each make schema changes, Alembic tracks every change in version files. Anyone can apply all changes in order with one command: `alembic upgrade head`. Without this, "works on my machine" becomes the team motto.

### What needs to be built

Define all database tables using SQLAlchemy models and create the first Alembic migration.

### Files to create

- `src/models/user.py` - User model with mode, profile, quota, confirmation_mode
- `src/models/job.py` - Job model with all scraped fields
- `src/models/application.py` - Application model linking user to job
- `src/models/prep_guide.py` - PrepGuide model
- `src/models/report.py` - WeeklyReport model
- `src/config/database.py` - SQLAlchemy engine and session setup
- `migrations/versions/001_initial_schema.py` - first Alembic migration

### How it affects overall development

Every other module reads from and writes to these tables. The scraper saves to jobs. The match scorer updates applications. The prep guide agent writes to prep_guides. If a column is missing or named wrong, the module that depends on it breaks. Getting the schema right now saves every contributor from debugging database errors later.

### How to test locally

```bash
# Apply the migration
alembic upgrade head

# Verify all tables were created
psql hireflow -c "\dt"
# Should show: users, jobs, applications, prep_guides, weekly_reports

# Verify columns in the users table
psql hireflow -c "\d users"

# Downgrade and upgrade to test the migration is reversible
alembic downgrade -1
alembic upgrade head

# Run model tests
pytest tests/test_models.py -v
```

### Acceptance Criteria

- [ ] All 5 tables created: users, jobs, applications, prep_guides, weekly_reports
- [ ] users table includes: id, name, email, mode (internship or job), master_profile (JSONB), weekly_quota, confirmation_mode, created_at
- [ ] jobs table includes: all scraped fields plus listing_type, is_spam, spam_confidence
- [ ] applications table links user_id and job_id with match_score, skill_gaps, resume_path, status
- [ ] `alembic upgrade head` runs without errors on a fresh database
- [ ] `alembic downgrade -1` then `alembic upgrade head` works without errors

---

## Issue 4 - User Profile Model and Onboarding API

Labels: m1, agent
Milestone: M1
Branch: feature/issue-4-profile-api
Depends on: Issue 3

### Why

HireFlow needs to know who it is working for before it can do anything. The profile is not just storage - it is the input to almost every module. The match scorer uses it to rank jobs. The resume engine uses it to pick relevant projects. The prep guide uses it to identify skill gaps.

The onboarding API is the entry point to the entire system. A student uploads their resume, the LLM extracts structured data from it, and that data drives everything downstream. This is your first hands-on experience with LLM-based extraction - not just calling an API, but designing a prompt that reliably pulls structured fields from unstructured text.

### What needs to be built

A FastAPI endpoint that accepts a PDF resume or JSON profile, extracts structured data using an LLM, and stores it in the users table.

### Files to create

- `src/api/routes/profile.py` - POST /profile, GET /profile/{user_id}
- `src/api/main.py` - FastAPI app with router registration
- `src/config/settings.py` - Pydantic settings loading from .env
- `src/utils/llm_client.py` - unified LLM client supporting Groq, Gemini, OpenAI, Ollama

### How it affects overall development

Every other module downstream (scraper, scorer, resume engine) reads from the user profile. If this API stores incomplete or incorrectly structured data, contributors working on M2 and M3 will get None values and KeyErrors. Good data in means good data out.

### How to test locally

```bash
# Start the server
uvicorn src.api.main:app --reload

# Test profile creation with JSON
curl -X POST http://localhost:8000/profile \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Student",
    "email": "test@example.com",
    "skills": ["Python", "LangChain", "FastAPI"],
    "mode": "internship",
    "weekly_quota": 5,
    "target_roles": ["AI Engineer Intern"],
    "preferred_locations": ["Bangalore", "Remote"],
    "min_stipend": 15000
  }'
# Should return the created user with an id

# Test retrieval
curl http://localhost:8000/profile/{user_id}

# Verify in database
psql hireflow -c "SELECT id, name, mode, weekly_quota FROM users;"

# Run tests
pytest tests/test_profile_api.py -v
```

### Acceptance Criteria

- [ ] POST /profile accepts JSON profile and returns created user with id
- [ ] POST /profile accepts PDF resume upload, extracts skills and experience via LLM, stores result
- [ ] GET /profile/{user_id} returns full profile
- [ ] mode field validated: only "internship" or "job" accepted
- [ ] confirmation_mode field defaults to "batch"
- [ ] LLM client works with at least one free provider (Groq or Gemini)
- [ ] API docs available at /docs

---

## Issue 5 - LLM Provider Configuration and Testing

Labels: m1, infra
Milestone: M1
Branch: feature/issue-5-llm-config
Depends on: Issue 4

### Why

HireFlow uses an LLM in at least 6 places: profile extraction, JD parsing, spam classification, resume generation, prep guide generation, and mock question generation. If the LLM client is inconsistent - different calling conventions, different error handling per provider - every module that uses it will have its own workaround. That is technical debt from day one.

This issue builds a single, clean LLM abstraction that every module uses. Swap Groq for OpenAI by changing one line in .env. This is also a practical lesson in how real products handle multi-provider AI infrastructure.

### What needs to be built

A unified LLM client that wraps Groq, Gemini, OpenAI, and Ollama behind a consistent interface. Tested against a real prompt.

### Files to create

- `src/utils/llm_client.py` - unified client, reads LLM_PROVIDER from settings
- `tests/test_llm_client.py` - tests with a simple extraction prompt

### How to test locally

```bash
# With Groq (free)
LLM_PROVIDER=groq pytest tests/test_llm_client.py -v

# With Ollama (local, fully offline)
# First: ollama pull llama3
LLM_PROVIDER=ollama pytest tests/test_llm_client.py -v

# Test the extraction directly
python -c "
from src.utils.llm_client import get_llm_client
client = get_llm_client()
result = client.extract('Extract skills as a list from: Python developer with FastAPI and Docker experience')
print(result)
"
```

### Acceptance Criteria

- [ ] `get_llm_client()` returns correct client based on LLM_PROVIDER env var
- [ ] Supports: groq, gemini, openai, anthropic, ollama
- [ ] Consistent interface: all clients have `.chat()` and `.extract()` methods
- [ ] Graceful error if API key is missing: clear error message, not a stack trace
- [ ] Tests pass with at least one provider

---

## Issue 6 - Lever and Greenhouse Scrapers

Labels: m2, scraper
Milestone: M2
Branch: feature/issue-6-lever-greenhouse-scrapers
Depends on: Issue 3

### Why

Lever and Greenhouse are the two most common ATS platforms used by startups and mid-size companies. A huge percentage of engineering internships and jobs are posted on one of these two. If you can scrape them reliably, you already have access to hundreds of listings.

These scrapers are a hands-on introduction to Playwright - the browser automation tool that will also drive the application agent in M5. Learn it well here because you will use it again.

### What needs to be built

Two scrapers: one for Lever career pages (jobs.lever.co/company) and one for Greenhouse (boards.greenhouse.io/company). Both should extract all required fields and save to the jobs table.

### Files to create

- `src/scrapers/lever_scraper.py`
- `src/scrapers/greenhouse_scraper.py`
- `tests/test_scrapers.py` (Lever and Greenhouse cases)

### How it affects overall development

The match scorer (Issue 9) needs jobs in the database to score. Without scrapers running, there is nothing to match against. The quality of what you scrape directly determines the quality of the matches the system produces.

### How to test locally

```bash
# Run the Lever scraper against a real company (read-only, no form submission)
python -m src.scrapers.lever_scraper --url "https://jobs.lever.co/anthropic" --mode job

# Check what was saved
psql hireflow -c "SELECT company_name, role_title, location FROM jobs LIMIT 10;"

# Run the Greenhouse scraper
python -m src.scrapers.greenhouse_scraper --url "https://boards.greenhouse.io/notion" --mode job

# Run tests (uses mock HTML, no network required)
pytest tests/test_scrapers.py -v -k "lever or greenhouse"
```

### Acceptance Criteria

- [ ] Lever scraper extracts: company_name, role_title, jd_text, location, application_url, posting_date, listing_type
- [ ] Greenhouse scraper extracts the same fields
- [ ] Both scrapers handle pagination (multiple pages of listings)
- [ ] listing_type correctly identified as "internship" or "job" based on title keywords
- [ ] All extracted jobs saved to jobs table
- [ ] Rate limiting: at least 1 second delay between requests
- [ ] At least 3 test cases each using mock HTML fixtures

---

## Issue 7 - Generic Playwright Scraper for Custom Career Pages

Labels: m2, scraper
Milestone: M2
Branch: feature/issue-7-generic-scraper
Depends on: Issue 6

### Why

Not every company uses Lever or Greenhouse. Many have custom-built career pages - some are static HTML, some are JavaScript-rendered SPAs. Without a generic scraper, HireFlow can only reach companies that use the two big ATS platforms. That cuts out a large portion of the most interesting startups.

This issue teaches you the difference between static and dynamic web pages, and why `requests + BeautifulSoup` works for one but silently fails for the other.

### What needs to be built

A generic scraper that can handle both static pages (using BeautifulSoup) and JavaScript-rendered pages (using Playwright). Accepts a URL and returns a list of job listings.

### Files to create

- `src/scrapers/generic_scraper.py` - auto-detects static vs dynamic and uses appropriate parser
- `src/scrapers/static_scraper.py` - BeautifulSoup-based for static pages
- `tests/test_scrapers.py` (add generic scraper cases)

### How to test locally

```bash
# Test against a static career page
python -m src.scrapers.generic_scraper --url "https://example-static-careers.com/jobs"

# Test against a JS-rendered career page
python -m src.scrapers.generic_scraper --url "https://example-spa-careers.com/careers"

# Verify both routes were taken (check logs for "static" vs "playwright" mode)

# Run tests
pytest tests/test_scrapers.py -v -k "generic"
```

### Acceptance Criteria

- [ ] Correctly handles static HTML pages using BeautifulSoup
- [ ] Correctly handles JS-rendered pages using Playwright (waits for content to load)
- [ ] Returns consistent job data structure regardless of which parser was used
- [ ] Handles pages that return no jobs gracefully (empty list, no crash)
- [ ] Logs which scraping method was used for each URL

---

## Issue 8 - Spam Filter and Job Data Quality

Labels: m2, agent
Milestone: M2
Branch: feature/issue-8-spam-filter
Depends on: Issue 6

### Why

Not every listing scraped is a real opportunity. Some are vague ("we are looking for a motivated self-starter"), some are from fake companies, some have unrealistic offers. If these get through to the match scorer, they pollute the rankings and waste the user's weekly quota on garbage listings.

This is your first NLP classification task - building a system that makes a judgment call about text quality. It is also a lesson in precision vs recall trade-offs: you want to catch spam without accidentally filtering out real but sparse listings from legitimate startups.

### What needs to be built

A spam and quality filter that scores each scraped listing and marks it as spam or clean. Saves is_spam and spam_confidence to the jobs table.

### Files to create

- `src/agents/spam_filter.py`
- `tests/test_spam_filter.py`

### How to test locally

```bash
# Run against all jobs currently in the database
python -m src.agents.spam_filter --run

# Check results
psql hireflow -c "SELECT company_name, role_title, is_spam, spam_confidence FROM jobs ORDER BY spam_confidence DESC LIMIT 20;"

# Test with a known spam listing
python -c "
from src.agents.spam_filter import SpamFilter
sf = SpamFilter()
result = sf.score({'jd_text': 'We need a rockstar ninja developer. Great pay. Must be passionate.', 'company_name': '', 'skills_required': []})
print(result)  # should be high spam confidence
"

# Run tests
pytest tests/test_spam_filter.py -v
```

### Acceptance Criteria

- [ ] Filter scores every job in the database and updates is_spam and spam_confidence
- [ ] Flags listings with: missing company name, JD under 50 words, no skills mentioned, unrealistic salary claims
- [ ] Confidence score between 0 and 1
- [ ] Threshold configurable via settings (default 0.7 - above this is spam)
- [ ] At least 5 test cases: 3 spam, 2 legitimate sparse JDs that should pass

---

## Issue 9 - Embedding Pipeline and FAISS Index

Labels: m3, agent
Milestone: M3
Branch: feature/issue-9-embedding-pipeline
Depends on: Issue 8

### Why

How do you measure whether a Python developer is a good fit for a "GenAI Engineer" role? You cannot just count matching keywords - the JD might say "experience with language models" and the profile might say "built RAG pipelines with LangChain." These mean the same thing but share zero words.

Embeddings solve this. They convert text into vectors - lists of numbers where similar meaning produces similar vectors. FAISS is a library by Meta that lets you search through millions of these vectors in milliseconds. This issue is where the intelligence of HireFlow's matching comes from.

### What needs to be built

A pipeline that embeds user profiles and job descriptions into vectors and stores them in a FAISS index for fast similarity search.

### Files to create

- `src/pipelines/embedding_pipeline.py`
- `tests/test_embedding.py`

### How to test locally

```bash
# Embed all jobs currently in the database
python -m src.pipelines.embedding_pipeline --embed-jobs

# Embed a test profile
python -c "
from src.pipelines.embedding_pipeline import EmbeddingPipeline
ep = EmbeddingPipeline()
profile_vec = ep.embed_text('Python developer with LangChain RAG and FastAPI experience')
print('Vector shape:', profile_vec.shape)
print('First 5 values:', profile_vec[:5])
"

# Search for similar jobs
python -c "
from src.pipelines.embedding_pipeline import EmbeddingPipeline
ep = EmbeddingPipeline()
results = ep.search('AI engineer with LangGraph and multi-agent systems', top_k=5)
for r in results:
    print(r['role_title'], '-', r['company_name'], '- similarity:', round(r['score'], 3))
"

# Run tests
pytest tests/test_embedding.py -v
```

### Acceptance Criteria

- [ ] Embedding pipeline generates vectors for all non-spam jobs in the database
- [ ] FAISS index built and saved to disk (data/faiss_index/)
- [ ] Search function returns top-K most similar jobs to a given profile text
- [ ] Handles empty or very short text gracefully
- [ ] Embedding model configurable via settings (default: sentence-transformers/all-MiniLM-L6-v2, free, local)

---

## Issue 10 - Multi-Factor Match Scorer and Skill Gap Extractor

Labels: m3, agent
Milestone: M3
Branch: feature/issue-10-match-scorer
Depends on: Issue 9

### Why

Semantic similarity alone is not enough to rank jobs. A job might be semantically close to your profile but require 5 years of experience when you are a fresher, or be in a city you will not relocate to. The multi-factor scorer combines semantic match with practical filters to produce a ranking that is actually useful.

The skill gap output is equally important - it flows directly into the prep guide (M6) and the resume tailoring engine (M4). What you identify as missing here determines what prep resources are recommended and which projects get highlighted in the resume.

### What needs to be built

A scorer that combines embedding similarity with skill match, role fit, experience fit, location match, and stipend/salary fit into a single ranked score per job.

### Files to create

- `src/pipelines/match_scorer.py`
- `tests/test_matcher.py`

### How to test locally

```bash
# Score all jobs against a test user
python -m src.pipelines.match_scorer --user-id {your_user_id}

# Check ranked results
psql hireflow -c "SELECT j.role_title, j.company_name, a.match_score, a.skill_gaps FROM applications a JOIN jobs j ON a.job_id = j.id WHERE a.user_id = '{your_user_id}' ORDER BY a.match_score DESC LIMIT 10;"

# Run tests
pytest tests/test_matcher.py -v

# Verify scoring is deterministic (run twice, compare output)
python -m src.pipelines.match_scorer --user-id {id} --dry-run > run1.json
python -m src.pipelines.match_scorer --user-id {id} --dry-run > run2.json
diff run1.json run2.json   # should be empty
```

### Acceptance Criteria

- [ ] Scores all non-spam jobs against the user profile
- [ ] Multi-factor scoring: skill match 40%, role fit 20%, experience fit 15%, location 10%, stipend/salary 10%, company signal 5%
- [ ] skill_gaps field populated: list of skills in JD missing from user profile
- [ ] Handles internship mode (compares stipend) and job mode (compares salary) correctly
- [ ] Results saved to applications table with match_score, skill_matches, skill_gaps, rank
- [ ] Scoring is deterministic

---

## Issue 11 - Weekly Quota Selector and Confirmation Flow

Labels: m4, agent
Milestone: M4
Branch: feature/issue-11-quota-selector
Depends on: Issue 10

### Why

The match scorer produces a ranked list of 100+ jobs. The user only wants 10 applications per week. Picking the top 10 sounds simple but there are real constraints: skip companies already applied to, skip expired listings, respect the user's blacklist.

More importantly: nothing gets submitted without the user's explicit approval. This is not a feature - it is a design principle. Automated job applications sent without the user reviewing them can damage professional relationships, send the wrong resume to the wrong company, or apply to roles the user would never want. The confirmation flow is mandatory.

### What needs to be built

A quota selector that picks the top N jobs from the ranked list, generates a weekly plan, and waits for user confirmation before proceeding.

### Files to create

- `src/pipelines/quota_selector.py`
- `src/api/routes/weekly_plan.py` - GET /weekly-plan/{user_id}, POST /weekly-plan/{user_id}/confirm
- `tests/test_quota_selector.py`

### How to test locally

```bash
# Generate a weekly plan for a user
curl http://localhost:8000/weekly-plan/{user_id}
# Should return top N jobs with match scores, skill gaps, planned resume

# Confirm the plan (triggers resume generation and application)
curl -X POST http://localhost:8000/weekly-plan/{user_id}/confirm \
  -H "Content-Type: application/json" \
  -d '{"confirmed_job_ids": ["job_1", "job_2"], "removed_job_ids": ["job_3"]}'

# Swap a listing before confirming
curl -X POST http://localhost:8000/weekly-plan/{user_id}/swap \
  -H "Content-Type: application/json" \
  -d '{"remove_job_id": "job_4", "add_job_id": "job_11"}'

# Run tests
pytest tests/test_quota_selector.py -v
```

### Acceptance Criteria

- [ ] Selects top N jobs (N = user weekly_quota) from ranked list
- [ ] Filters out: already-applied companies, expired listings (posting_date > 30 days), user blacklist
- [ ] GET /weekly-plan returns plan with job details, match score, skill gaps, planned resume summary
- [ ] POST /weekly-plan/confirm accepts confirmed list, triggers next step (resume generation)
- [ ] POST /weekly-plan/swap allows replacing a listing before confirming
- [ ] Nothing proceeds to resume generation until confirmation endpoint is called
- [ ] confirmation_mode respected: "batch" shows all at once, "individual" paginates one by one

---

## Issue 12 - Resume Tailoring Engine (RAG Pipeline)

Labels: m4, agent
Milestone: M4
Branch: feature/issue-12-resume-tailoring
Depends on: Issue 11

### Why

Sending the same resume to every company is one of the most common mistakes in job applications. ATS systems score resumes against job descriptions - a resume that does not mirror the JD's language and skill priorities gets filtered out before a human ever sees it.

HireFlow generates a unique resume for each application. This is a RAG (Retrieval Augmented Generation) pipeline - the LLM generates resume content, but it is grounded in the user's actual profile data rather than hallucinating experience the user does not have.

### What needs to be built

A pipeline that takes a user profile and a job description, selects the most relevant skills and projects, and generates tailored resume content for each section.

### Files to create

- `src/pipelines/resume_generator.py`
- `tests/test_resume.py`

### How to test locally

```bash
# Generate a tailored resume for one application
python -c "
from src.pipelines.resume_generator import ResumeTailoringEngine
engine = ResumeTailoringEngine()
result = engine.tailor(user_id='{id}', job_id='{job_id}')
print('Summary:', result['summary'])
print('Top skills:', result['skills'][:5])
print('Selected projects:', [p['name'] for p in result['projects']])
"

# Run tests
pytest tests/test_resume.py -v

# Verify resume content is different for two different jobs
python -m src.pipelines.resume_generator --user-id {id} --compare-jobs {job_id_1} {job_id_2}
```

### Acceptance Criteria

- [ ] Selects top 2 to 3 most relevant projects from user profile for each JD
- [ ] Reorders skills by JD priority (skills mentioned first in JD appear first in resume)
- [ ] Generates role-specific summary (different tone for internship vs job mode)
- [ ] Resume content references only real skills and projects from the user profile (no hallucination)
- [ ] Output is a structured dict with sections: summary, skills, projects, experience, education
- [ ] Two different JDs produce meaningfully different resumes for the same user

---

## Issue 13 - LaTeX PDF Generation and Resume Storage

Labels: m4, infra
Milestone: M4
Branch: feature/issue-13-pdf-generation
Depends on: Issue 12

### Why

A resume as a Python dict is not something you can email. This issue converts the tailored resume content into a PDF using LaTeX - the same typesetting system used by academic papers and professional documents. LaTeX produces cleaner, more ATS-parseable output than HTML-to-PDF conversion and gives precise control over formatting.

You will also build the resume versioning system here - each resume is saved with a unique path so the user can always see exactly which resume was sent to which company.

### What needs to be built

A LaTeX-based PDF generator that takes tailored resume content and produces a clean, ATS-optimized PDF. Saves each PDF with a versioned path.

### Files to create

- `src/templates/resume_latex/base_template.tex`
- `src/pipelines/pdf_generator.py`
- `tests/test_pdf_generator.py`

### How to test locally

```bash
# Check LaTeX is installed
xelatex --version

# Generate a test PDF
python -c "
from src.pipelines.pdf_generator import PDFGenerator
gen = PDFGenerator()
path = gen.generate(user_id='test_user', job_id='test_job', resume_content={
    'summary': 'AI engineer intern with Python and LangChain experience',
    'skills': ['Python', 'LangChain', 'FastAPI', 'FAISS'],
    'projects': [{'name': 'HireFlow', 'description': 'Agentic job application system'}],
    'education': {'degree': 'B.Tech CS', 'college': 'NST', 'year': 2026}
})
print('PDF saved to:', path)
"

# Open and verify the PDF looks correct
open data/resumes/test_user/test_job_resume.pdf

# Verify versioning: run twice, confirm v1 and v2 are created
pytest tests/test_pdf_generator.py -v
```

### Acceptance Criteria

- [ ] Generates valid PDF from resume content dict
- [ ] PDF saved to data/resumes/{user_id}/{job_id}_resume_v{N}.pdf
- [ ] Version increments if a resume already exists for that job
- [ ] PDF is ATS-parseable (text-selectable, no images for text content)
- [ ] LaTeX template handles long project descriptions without overflow
- [ ] Application record updated in DB with resume_path and resume_version

---

## Issue 14 - Form Filler Agent (Playwright)

Labels: m5, agent
Milestone: M5
Branch: feature/issue-14-form-filler
Depends on: Issue 13

### Why

Filling out job application forms manually is the most time-consuming part of job hunting. Most forms ask the same questions: name, email, education, skills, resume upload. The form filler agent automates this using Playwright - the same browser automation tool used in the scrapers, but now it is filling forms instead of reading them.

This is where the project earns its name. HireFlow actually applies. Understanding how Playwright controls a browser, handles DOM interactions, and manages timing is a skill that transfers directly to test automation, RPA, and any web automation work.

### What needs to be built

A Playwright-based agent that navigates to an application URL, fills in standard form fields, uploads the tailored resume, and submits the form.

### Files to create

- `src/agents/application_agent.py`
- `src/automation/form_filler.py`
- `tests/test_automation.py`

### How to test locally

```bash
# Test against a dummy form (create a test HTML form locally)
# A sample test form is provided in tests/fixtures/sample_form.html

python -c "
from src.agents.application_agent import ApplicationAgent
agent = ApplicationAgent()
result = agent.apply(
    application_url='file://tests/fixtures/sample_form.html',
    resume_path='data/resumes/test/test_resume.pdf',
    user_profile={'name': 'Test User', 'email': 'test@example.com', 'phone': '9999999999'}
)
print('Status:', result['status'])
print('Fields filled:', result['fields_filled'])
"

# Run automation tests (uses mock forms, no real submission)
pytest tests/test_automation.py -v
```

### Acceptance Criteria

- [ ] Fills standard fields: name, email, phone, education, experience years, skills
- [ ] Uploads resume PDF to file upload fields
- [ ] Handles free-text fields like "Why do you want to work here?" using LLM with JD context
- [ ] Submits the form and waits for confirmation page
- [ ] Returns status: applied, failed, or needs_action
- [ ] Application status and any failure reason saved to DB
- [ ] At least 3 test cases using local HTML fixture forms

---

## Issue 15 - CAPTCHA Detection and Error Recovery

Labels: m5, agent
Milestone: M5
Branch: feature/issue-15-captcha-error-recovery
Depends on: Issue 14

### Why

The real world is messier than a test fixture. Career pages change structure, go down temporarily, throw CAPTCHAs, or time out mid-submission. An agent that crashes on the first unexpected thing is not production-ready.

This issue adds resilience to the application agent. CAPTCHA detection is intentionally non-solving - solving CAPTCHAs programmatically is legally and ethically problematic. Instead, the agent flags these for manual action and moves on to the next listing. This is also where you learn retry logic and graceful degradation.

### What needs to be built

CAPTCHA detection, retry logic, and error recovery so the application agent handles failures gracefully instead of crashing.

### Files to create

- `src/automation/captcha_handler.py`
- Update `src/agents/application_agent.py` with retry and recovery logic

### How to test locally

```bash
# Test CAPTCHA detection
python -c "
from src.automation.captcha_handler import CaptchaHandler
handler = CaptchaHandler()
# Test with a page that has a CAPTCHA (use a fixture)
result = handler.detect('file://tests/fixtures/captcha_form.html')
print('CAPTCHA detected:', result)
"

# Test retry logic
python -c "
from src.agents.application_agent import ApplicationAgent
agent = ApplicationAgent(max_retries=3, retry_delay=1)
# Test against a form that fails on first attempt
result = agent.apply(application_url='file://tests/fixtures/flaky_form.html', ...)
print('Final status:', result['status'])
print('Attempts made:', result['attempts'])
"

# Run tests
pytest tests/test_automation.py -v -k "captcha or retry or recovery"
```

### Acceptance Criteria

- [ ] CAPTCHA detection identifies common CAPTCHA types (reCAPTCHA, hCaptcha, image challenges)
- [ ] On CAPTCHA detection: status set to needs_action, failure_reason = "CAPTCHA detected", agent moves to next listing
- [ ] Retry logic: configurable max_retries (default 3) with exponential backoff
- [ ] Network timeout handled: treated as temporary failure, retried
- [ ] Form structure change (selector not found): treated as permanent failure after 1 attempt
- [ ] All failure modes produce a clean status and reason in the DB - no unhandled exceptions

---

## Issue 16 - Application Status Logger and Tracker

Labels: m5, infra
Milestone: M5
Branch: feature/issue-16-status-logger
Depends on: Issue 15

### Why

Applying to a job is not a one-time event. The application exists in the system across time - first planned, then confirmed, then applied (or failed). The user needs to be able to look back at any application and see exactly what happened: which resume was sent, when it was submitted, and what the current status is.

This issue builds the logging layer that makes HireFlow trustworthy - the user should never wonder "did it actually apply?"

### What needs to be built

A status logging system that records every state change for every application with a timestamp and reason.

### Files to create

- `src/utils/status_logger.py`
- `src/api/routes/applications.py` - GET /applications/{user_id}

### How to test locally

```bash
# View all applications for a user
curl http://localhost:8000/applications/{user_id}

# Filter by status
curl "http://localhost:8000/applications/{user_id}?status=needs_action"

# Verify status trail in database
psql hireflow -c "SELECT j.company_name, j.role_title, a.status, a.failure_reason, a.applied_at FROM applications a JOIN jobs j ON a.job_id = j.id WHERE a.user_id = '{id}';"

# Run tests
pytest tests/test_status_logger.py -v
```

### Acceptance Criteria

- [ ] Every status change logged with timestamp: planned, confirmed, applying, applied, failed, needs_action
- [ ] GET /applications/{user_id} returns all applications with current status and resume link
- [ ] Failed applications include failure_reason
- [ ] needs_action applications include specific reason and manual action URL
- [ ] API response includes pagination (can be many applications over time)

---

## Issue 17 - Interview Round Predictor and Topic Analyzer

Labels: m6, agent
Milestone: M6
Branch: feature/issue-17-round-predictor
Depends on: Issue 10

### Why

Getting a callback is only half the battle. Most students who apply to 10 jobs and get 3 callbacks are underprepared for 2 of them because they did not know what to expect. HireFlow's prep guide changes this.

The interview round predictor reads the JD, the company's career page, and the company's scale to predict what the interview process looks like. The topic analyzer uses the match scorer's skill gap output to tell the user exactly what to study - not generically, but specifically for this JD.

### What needs to be built

An agent that analyzes a JD and predicts interview rounds with focus areas, and categorizes the user's skills into strong, moderate, and gap relative to the JD.

### Files to create

- `src/agents/prep_guide_agent.py` (rounds prediction and topic analysis sections)
- `tests/test_prep_guide.py`

### How to test locally

```bash
python -c "
from src.agents.prep_guide_agent import PrepGuideAgent
agent = PrepGuideAgent()

# Test with a sample JD
result = agent.predict_rounds(
    jd_text='We are looking for an AI Engineer Intern. 2 rounds: technical and HR. Must know Python, LangChain, RAG.',
    company_stage='startup',
    listing_type='internship'
)
print('Predicted rounds:', result['round_count'])
for r in result['rounds']:
    print(f'  Round {r[\"number\"]}: {r[\"type\"]} - {r[\"focus\"]}')

# Test topic analysis
topics = agent.analyze_topics(
    user_skills=['Python', 'FastAPI', 'LangChain'],
    jd_skills=['Python', 'LangChain', 'TypeScript', 'Docker', 'RAG'],
    skill_gaps=['TypeScript', 'Docker']
)
print('Strong:', topics['strong'])
print('Moderate:', topics['moderate'])
print('Gaps:', topics['gaps'])
"

pytest tests/test_prep_guide.py -v -k "rounds or topics"
```

### Acceptance Criteria

- [ ] Predicts number of rounds and type (HR, technical, founder, etc.) for each
- [ ] Prediction uses JD text, company stage, and listing_type (internship = lighter)
- [ ] Gracefully handles JDs that do not mention interview process
- [ ] Topic categorization: strong (user has this), moderate (partial match), gap (missing from profile)
- [ ] Internship predictions default to 1 to 2 rounds unless JD says otherwise

---

## Issue 18 - Resource Finder and Mock Question Generator

Labels: m6, agent
Milestone: M6
Branch: feature/issue-18-resources-mock-questions
Depends on: Issue 17

### Why

Knowing what to study is not enough - you need to know where to study it. The resource finder uses web search to find real documentation, tutorials, and videos for each topic. Mock questions go one step further: instead of generic "Python interview questions", they are generated from the actual JD and company context.

This is the prep guide becoming genuinely useful, not just informative.

### What needs to be built

A resource finder that searches for learning materials per topic, and a mock question generator that produces JD-specific questions.

### Files to create

- Update `src/agents/prep_guide_agent.py` (resource and question sections)
- `tests/test_prep_guide.py` (resource and question test cases)

### How to test locally

```bash
python -c "
from src.agents.prep_guide_agent import PrepGuideAgent
agent = PrepGuideAgent()

# Test resource finder
resources = agent.find_resources(['TypeScript', 'Docker'])
for topic, links in resources.items():
    print(f'{topic}:')
    for link in links:
        print(f'  - {link[\"title\"]}: {link[\"url\"]}')

# Test mock question generator
questions = agent.generate_questions(
    jd_text='Agentic AI Intern - must know LangChain, Python, multi-agent systems',
    company_name='AIBridge',
    listing_type='internship'
)
for q in questions:
    print(f'[{q[\"category\"]}] {q[\"question\"]}')
"

pytest tests/test_prep_guide.py -v -k "resources or questions"
```

### Acceptance Criteria

- [ ] Resource finder returns 2 to 3 links per topic using Tavily or SerpAPI
- [ ] Handles broken or inaccessible links: skips and finds alternatives
- [ ] Mock questions are specific to the JD content, not generic
- [ ] Questions split by category: technical, behavioral, design
- [ ] Internship questions are lighter than full-time questions for the same tech stack

---

## Issue 19 - Company Intel Scraper

Labels: m6, scraper
Milestone: M6
Branch: feature/issue-19-company-intel
Depends on: Issue 17

### Why

Walking into an interview without knowing what the company does is one of the most common and avoidable mistakes. HireFlow automates the research so the user shows up knowing the company's product, stage, tech stack, and - where available - what past candidates experienced in their interviews.

### What needs to be built

An agent that collects company information: stage, team size, tech stack, recent news, and Glassdoor/AmbitionBox interview patterns.

### Files to create

- `src/agents/company_intel_agent.py`
- `tests/test_company_intel.py`

### How to test locally

```bash
python -c "
from src.agents.company_intel_agent import CompanyIntelAgent
agent = CompanyIntelAgent()
intel = agent.research('Anthropic', 'https://anthropic.com')
print('Stage:', intel['stage'])
print('Tech stack:', intel['tech_stack'])
print('Recent news:', intel['recent_news'][:1])
print('Interview patterns found:', len(intel['interview_patterns']))
"

pytest tests/test_company_intel.py -v
```

### Acceptance Criteria

- [ ] Collects: company stage, estimated team size, tech stack, recent news (last 3 months)
- [ ] Searches Glassdoor and AmbitionBox for interview patterns if available
- [ ] Graceful fallback when company has no reviews: returns "No interview reviews found" with fallback guidance
- [ ] Results saved to company_intel field in prep_guides table

---

## Issue 20 - Weekly Report Generator

Labels: m7, agent
Milestone: M7
Branch: feature/issue-20-weekly-report
Depends on: Issue 16 and Issue 19

### Why

By the end of each weekly cycle, the user has applied to 10 jobs with 10 unique resumes and 10 prep guides. Without a report, they have to hunt through the database to find any of this. The weekly report collects everything into one place and adds a layer of insight: what skills appeared most across all 10 JDs? What should the user focus on learning this week?

### What needs to be built

A report generator that compiles all applications, resumes, and prep guides from the current week into a structured report.

### Files to create

- `src/agents/report_generator.py`
- `src/api/routes/reports.py` - GET /report/{user_id}/latest
- `tests/test_report.py`

### How to test locally

```bash
# Generate a report for the current week
python -m src.agents.report_generator --user-id {id}

# View the report via API
curl http://localhost:8000/report/{user_id}/latest

# Check report was saved
psql hireflow -c "SELECT week_start, applied_count, avg_match_score FROM weekly_reports WHERE user_id = '{id}';"

# Open the HTML report
open data/reports/{user_id}/week_2026_23.html

pytest tests/test_report.py -v
```

### Acceptance Criteria

- [ ] Report includes all applications from the current weekly cycle
- [ ] Per-application section: company, role, status, match score, resume link, prep guide link
- [ ] Cross-application insights: top 5 skills across all JDs, user strongest match type, weakest match type
- [ ] Weekly study plan: top 3 skills to learn ranked by frequency across JDs
- [ ] Failed and needs_action applications clearly called out with instructions
- [ ] Report saved to weekly_reports table and as HTML file

---

## Issue 21 - Email Delivery Integration

Labels: m7, infra
Milestone: M7
Branch: feature/issue-21-email-delivery
Depends on: Issue 20

### Why

A report that lives only in a database is not useful to a user checking their phone. Email delivery sends the weekly report, with resume PDFs attached, directly to the user's inbox. This is also the first time HireFlow communicates outward to the real world - not just storing data, but pushing it to a user.

### What needs to be built

An email service that sends the weekly report with attachments using SendGrid or Resend.

### Files to create

- `src/utils/email_service.py`
- `tests/test_email_service.py`

### How to test locally

```bash
# Send a test email (use your own email address)
python -c "
from src.utils.email_service import EmailService
service = EmailService()
service.send_weekly_report(
    to_email='your-email@example.com',
    report_html=open('data/reports/test/sample_report.html').read(),
    resume_paths=['data/resumes/test/job1_resume.pdf']
)
print('Email sent - check your inbox')
"

# For CI testing (no real email sent): mock the SendGrid client
pytest tests/test_email_service.py -v
```

### Acceptance Criteria

- [ ] Sends weekly report HTML as email body
- [ ] Attaches resume PDFs (up to 10)
- [ ] Works with SendGrid and Resend (configurable via EMAIL_PROVIDER env var)
- [ ] Handles attachment size limits gracefully (links instead of attachments if too large)
- [ ] Email sending logged with timestamp in weekly_reports table

---

## Issue 22 - Hiring Side - Shortlist Agent (Optional Module)

Labels: m7, agent
Milestone: M7
Branch: feature/issue-22-hiring-shortlist
Depends on: Issue 10

### Why

HireFlow works for candidates. But the same matching engine that finds the best jobs for a student can be flipped to find the best candidates for a company. A hiring team gets 127 applications - they cannot read them all. HireFlow scores each one against the JD and returns the top 20.

This is the optional module that completes the platform. It also makes for a much stronger project story - you built both sides of the hiring process.

### What needs to be built

An agent that accepts a JD and a pool of applicants, scores each one, and produces a shortlist with a summary report.

### Files to create

- `src/agents/hiring_shortlist_agent.py`
- `src/api/routes/hiring.py` - POST /hiring/shortlist
- `tests/test_hiring_shortlist.py`

### How to test locally

```bash
# Run the shortlisting agent with sample data
curl -X POST http://localhost:8000/hiring/shortlist \
  -H "Content-Type: application/json" \
  -d '{
    "jd_text": "AI Engineer Intern - LangChain, Python, RAG required",
    "applicants": [
      {"name": "Student A", "skills": ["Python", "LangChain", "FastAPI"]},
      {"name": "Student B", "skills": ["Java", "Spring", "SQL"]},
      {"name": "Student C", "skills": ["Python", "LangChain", "Docker", "RAG"]}
    ],
    "shortlist_size": 2
  }'
# Should return Student C and Student A as top 2

pytest tests/test_hiring_shortlist.py -v
```

### Acceptance Criteria

- [ ] Accepts JD text and list of applicants (JSON or CSV)
- [ ] Scores each applicant using the same scoring engine as Issue 10
- [ ] Returns shortlist of top N candidates with score and skill summary
- [ ] Shortlist saved to shortlists table
- [ ] At least 5 test cases including edge cases (no matching candidates, ties)

---

## Issue 23 - React Dashboard Setup and Profile Page

Labels: m8, frontend
Milestone: M8
Branch: feature/issue-23-react-setup
Depends on: Issue 4

### Why

The backend pipeline is powerful but invisible. Users cannot interact with it through a terminal. The React dashboard is the face of HireFlow - the place where the user sets up their profile, reviews the weekly plan, tracks applications, and reads prep guides.

This issue sets up the frontend foundation: project structure, routing, API client, and the profile page.

### What needs to be built

A React application with routing, an API client connected to the FastAPI backend, and the profile setup page.

### Files to create

- `frontend/src/App.jsx`
- `frontend/src/api/client.js` - axios client pointing to FastAPI
- `frontend/src/pages/ProfilePage.jsx`
- `frontend/src/components/ModeSelector.jsx` - internship vs job toggle
- `frontend/package.json`

### How to test locally

```bash
cd frontend
npm install
npm run dev
# Open http://localhost:3000

# Verify profile page loads and mode selector works
# Fill in profile form and submit - check that API call reaches FastAPI
# Check browser console for errors (should be none)

# Run frontend tests
npm run test
```

### Acceptance Criteria

- [ ] React app starts on port 3000 without errors
- [ ] Profile page allows: name, email, skills input, resume upload, mode selection, quota setting
- [ ] Mode selector toggles between Internship and Job mode, sends correct value to API
- [ ] Form submits to POST /profile and shows success or error message
- [ ] API client handles 400 and 500 errors without crashing the UI
- [ ] Mobile-responsive layout

---

## Issue 24 - Weekly Plan View and Application Tracker

Labels: m8, frontend
Milestone: M8
Branch: feature/issue-24-plan-tracker-ui
Depends on: Issue 23 and Issue 11

### Why

This is the most important screen in HireFlow. The user sees their top 10 ranked opportunities, reviews each tailored resume, makes changes, and clicks confirm. The application tracker then shows the live status of every submission. This is where the value of the whole system becomes visible.

### What needs to be built

The weekly plan confirmation UI and the application status tracker table.

### Files to create

- `frontend/src/pages/WeeklyPlanPage.jsx`
- `frontend/src/components/JobCard.jsx`
- `frontend/src/components/ResumePreview.jsx`
- `frontend/src/pages/ApplicationTrackerPage.jsx`

### How to test locally

```bash
cd frontend && npm run dev

# Navigate to /weekly-plan
# Verify job cards show: company, role, match score, skill gaps, planned resume
# Test swap: remove one listing and add another from the ranked list
# Test resume preview: click "preview resume" - PDF should open
# Click "Confirm and Apply" - verify POST /weekly-plan/confirm is called
# Navigate to /applications - verify table shows all applications with status
```

### Acceptance Criteria

- [ ] Weekly plan shows top N jobs with match score, key skill gaps, resume that will be used
- [ ] User can remove a listing and swap with next ranked alternative
- [ ] Resume preview shows the tailored PDF before user confirms
- [ ] "Confirm and Apply" button calls confirmation endpoint, triggers application pipeline
- [ ] Application tracker table: company, role, status badge (applied/failed/needs action), date, resume link
- [ ] Needs action items highlighted with link to manual apply URL

---

## Issue 25 - Prep Guide Viewer and Resume Library

Labels: m8, frontend
Milestone: M8
Branch: feature/issue-25-prep-guide-viewer
Depends on: Issue 23 and Issue 17

### Why

The prep guide is only useful if it is easy to read. This page needs to present interview rounds, topics, resources, and mock questions in a way that a student can sit with for 30 minutes and come out feeling prepared - not overwhelmed.

### What needs to be built

A prep guide detail page and a resume library showing all generated resumes.

### Files to create

- `frontend/src/pages/PrepGuidePage.jsx`
- `frontend/src/components/TopicBadge.jsx` - strong, moderate, gap visual indicators
- `frontend/src/pages/ResumeLibraryPage.jsx`

### How to test locally

```bash
cd frontend && npm run dev

# Navigate to /applications/{id}/prep-guide
# Verify all sections load: rounds, topics (with color-coded badges), resources (clickable links), mock questions, company intel
# Test that topic badges correctly show green (strong), yellow (moderate), red (gap)
# Navigate to /resumes - verify all generated PDFs are listed with company and version
# Download a resume and verify it opens correctly
```

### Acceptance Criteria

- [ ] Prep guide page shows all sections from the backend
- [ ] Topic badges are color-coded: green for strong, yellow for moderate, red for gap
- [ ] Resources are clickable external links, open in new tab
- [ ] Mock questions expandable (click to reveal) to avoid cognitive overload
- [ ] Resume library lists all resumes with company, role, version, date generated, and download link

---

## Issue 26 - Docker Deployment and Railway or Render Setup

Labels: m8, infra
Milestone: M8
Branch: feature/issue-26-deployment
Depends on: Issue 2 and all previous issues

### Why

A project that only runs on your laptop is not a project - it is a demo. Deployment means the system runs on a server, accessible via a real URL, ready to be shown to anyone without setup. This is also where you learn containerization: Docker ensures that "works on my machine" becomes "works everywhere."

This is the final issue. By the time this is merged to main, HireFlow is live.

### What needs to be built

Verify Docker setup works end-to-end, deploy to Railway or Render, and confirm the live URL works.

### Files to create or update

- `Dockerfile` - verify and update if needed
- `docker-compose.yml` - verify and update if needed
- `docs/deployment.md` - deployment steps and live URL

### How to test locally

```bash
# Build and run with Docker
docker-compose up --build

# Verify all services start
curl http://localhost:8000/docs   # API docs
open http://localhost:3000        # Frontend

# Test the full pipeline via Docker (end-to-end test)
pytest tests/test_e2e.py -v

# Deploy to Railway
railway login
railway up

# Verify live URL
curl https://hireflow-ai.up.railway.app/docs
```

### Acceptance Criteria

- [ ] `docker-compose up --build` starts API, frontend, and database without errors
- [ ] All environment variables documented in .env.example are correctly passed to containers
- [ ] Application deployed to Railway or Render with a live URL
- [ ] Live URL accessible without VPN or local setup
- [ ] End-to-end test passes: profile creation, weekly plan generation, confirmation flow
- [ ] docs/deployment.md documents the live URL and how to redeploy

---

NST Engineering - HireFlow
