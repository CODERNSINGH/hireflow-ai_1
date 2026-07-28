"""
Tests for ReportGenerator (Issue #20).

Acceptance criteria:
- Report includes all applications from current weekly cycle
- Per-application section: company, role, status, resume, skill gaps
- Cross-application insights: top 5 skills across all JDs
- Strongest / weakest match category
- Weekly study plan: top 3 skills ranked by gap frequency
- Failed / needs_action applications highlighted
- Report saved to weekly_reports table
- GET /report/{user_id}/latest returns most recent report
- At least 3 test cases
"""

import json
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from src.agents.report_generator import ReportGenerator


# ---------------------------------------------------------------------------
# Sample application data (no DB required)
# ---------------------------------------------------------------------------

def _make_app(
    company="TechCorp",
    role="Software Engineer",
    status="applied",
    match_score=75.0,
    skill_gaps=None,
    skill_matches=None,
    jd_skills=None,
    resume_path="",
    failure_reason="",
    application_url="https://example.com/apply",
):
    return {
        "application_id": 1,
        "company": company,
        "role": role,
        "status": status,
        "match_score": match_score,
        "skill_gaps": skill_gaps or [],
        "skill_matches": skill_matches or [],
        "jd_skills": jd_skills or [],
        "resume_path": resume_path,
        "failure_reason": failure_reason,
        "application_url": application_url,
        "prep_guide_link": "",
        "listing_type": "job",
        "applied_at": None,
    }


SAMPLE_APPS = [
    _make_app(
        company="AIBridge", role="AI Engineer",
        status="applied", match_score=85.0,
        skill_gaps=["Docker", "TypeScript"],
        skill_matches=["Python", "LangChain"],
        jd_skills=["Python", "LangChain", "Docker", "TypeScript"],
    ),
    _make_app(
        company="DataCo", role="Data Scientist",
        status="applied", match_score=70.0,
        skill_gaps=["Spark", "Docker"],
        skill_matches=["Python", "SQL"],
        jd_skills=["Python", "SQL", "Spark", "Docker"],
    ),
    _make_app(
        company="FailCo", role="Backend Engineer",
        status="failed", match_score=55.0,
        skill_gaps=["Kubernetes", "Go"],
        skill_matches=["Python"],
        jd_skills=["Python", "Kubernetes", "Go"],
        failure_reason="Form submission error",
        application_url="https://failco.com/apply",
    ),
    _make_app(
        company="ActionCo", role="DevOps Engineer",
        status="needs_action", match_score=60.0,
        skill_gaps=["Docker", "AWS"],
        skill_matches=["Linux"],
        jd_skills=["Linux", "Docker", "AWS"],
        application_url="https://actionco.com/apply",
    ),
    _make_app(
        company="FrontendInc", role="React Developer",
        status="applied", match_score=90.0,
        skill_gaps=["TypeScript"],
        skill_matches=["React", "JavaScript"],
        jd_skills=["React", "JavaScript", "TypeScript"],
    ),
]


@pytest.fixture
def generator(tmp_path):
    """ReportGenerator using a temp directory for file output."""
    return ReportGenerator(reports_dir=str(tmp_path / "reports"))


@pytest.fixture
def week_start():
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


# ===========================================================================
# Case 1: Core report structure and per-application section
# ===========================================================================

class TestReportStructure:

    def test_generate_from_data_returns_valid_structure(self, generator, week_start):
        """Report must contain all required top-level keys."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        required_keys = {
            "user_id", "week_start", "week_label", "generated_at",
            "stats", "applications", "insights", "study_plan",
        }
        missing = required_keys - set(report.keys())
        assert not missing, f"Missing keys: {missing}"

    def test_applications_list_contains_all_apps(self, generator, week_start):
        """All 5 sample applications should appear in the report."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        assert len(report["applications"]) == 5

    def test_each_application_has_required_fields(self, generator, week_start):
        """Each application entry must have: company, role, status, match_score, skill_gaps."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        required = {"company", "role", "status", "match_score", "skill_gaps"}
        for app in report["applications"]:
            missing = required - set(app.keys())
            assert not missing, f"Application missing fields: {missing} — {app}"

    def test_stats_are_correct(self, generator, week_start):
        """Stats should correctly count applied, failed, and needs_action."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        stats = report["stats"]
        assert stats["total"] == 5
        assert stats["applied"] == 3
        assert stats["failed"] == 1
        assert stats["needs_action"] == 1

    def test_avg_match_score_calculated(self, generator, week_start):
        """Average match score should be calculated correctly."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        expected_avg = (85 + 70 + 55 + 60 + 90) / 5
        assert abs(report["stats"]["avg_match_score"] - expected_avg) < 1.0

    def test_week_label_is_human_readable(self, generator, week_start):
        """week_label should be a human-readable date string."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        assert isinstance(report["week_label"], str)
        assert len(report["week_label"]) > 5

    def test_generated_at_is_iso_timestamp(self, generator, week_start):
        """generated_at should be a valid ISO timestamp."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        ts = report["generated_at"]
        parsed = datetime.fromisoformat(ts)
        assert parsed is not None

    def test_empty_apps_returns_valid_structure(self, generator, week_start):
        """Empty applications list should not crash — returns zeroed stats."""
        report = generator.generate_from_data(
            user_id=1, apps_data=[], week_start=week_start
        )
        assert report["stats"]["total"] == 0
        assert report["applications"] == []
        assert isinstance(report["insights"], dict)
        assert isinstance(report["study_plan"], list)


# ===========================================================================
# Case 2: Cross-application insights
# ===========================================================================

class TestCrossApplicationInsights:

    def test_top_skills_contains_most_frequent_jd_skills(self, generator, week_start):
        """Top skills should include skills that appear in most JDs."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        top_skills = report["insights"]["top_skills"]
        assert isinstance(top_skills, list)
        assert len(top_skills) <= 5
        # Python appears in all 5 JDs — must be top
        assert "python" in [s.lower() for s in top_skills], (
            f"Expected 'python' in top skills, got: {top_skills}"
        )

    def test_top_skills_max_5(self, generator, week_start):
        """Top skills list should never exceed 5 items."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        assert len(report["insights"]["top_skills"]) <= 5

    def test_strongest_weakest_category_present(self, generator, week_start):
        """Insights must include strongest_category and weakest_category."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        assert "strongest_category" in report["insights"]
        assert "weakest_category" in report["insights"]
        assert isinstance(report["insights"]["strongest_category"], str)
        assert isinstance(report["insights"]["weakest_category"], str)

    def test_top_gaps_identified(self, generator, week_start):
        """Top gaps should include skills that appeared as gaps in most JDs."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        top_gaps = report["insights"]["top_gaps"]
        assert isinstance(top_gaps, list)
        # Docker appears as gap in 3 apps
        assert "docker" in [g.lower() for g in top_gaps], (
            f"Expected Docker in top gaps. Got: {top_gaps}"
        )

    def test_insights_has_required_keys(self, generator, week_start):
        """Insights dict must have all required keys."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        required = {"top_skills", "top_gaps", "strongest_category", "weakest_category"}
        for key in required:
            assert key in report["insights"], f"Missing insight key: {key}"

    def test_insights_with_empty_apps(self, generator, week_start):
        """Insights on empty data should return valid (possibly empty) structure."""
        report = generator.generate_from_data(
            user_id=1, apps_data=[], week_start=week_start
        )
        assert "top_skills" in report["insights"]
        assert "strongest_category" in report["insights"]


# ===========================================================================
# Case 3: Weekly study plan
# ===========================================================================

class TestStudyPlan:

    def test_study_plan_max_3_items(self, generator, week_start):
        """Study plan should have at most 3 items."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        assert len(report["study_plan"]) <= 3

    def test_study_plan_ranked_by_frequency(self, generator, week_start):
        """First item in study plan should be the most frequent gap skill."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        plan = report["study_plan"]
        if len(plan) >= 2:
            assert plan[0]["frequency"] >= plan[1]["frequency"], (
                "Study plan should be sorted by frequency descending"
            )

    def test_study_plan_item_structure(self, generator, week_start):
        """Each study plan item must have rank, skill, frequency, reason."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        for item in report["study_plan"]:
            assert "rank" in item
            assert "skill" in item
            assert "frequency" in item
            assert "reason" in item

    def test_study_plan_top_skill_is_docker(self, generator, week_start):
        """Docker appears as gap in 3 of 5 apps — should be #1 to study."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        if report["study_plan"]:
            top_skill = report["study_plan"][0]["skill"].lower()
            assert top_skill == "docker", (
                f"Expected Docker as top study skill, got: {top_skill}"
            )

    def test_study_plan_empty_when_no_gaps(self, generator, week_start):
        """If all apps have no gaps, study plan should be empty (not crash)."""
        apps = [_make_app(skill_gaps=[], jd_skills=["Python"]) for _ in range(3)]
        report = generator.generate_from_data(
            user_id=1, apps_data=apps, week_start=week_start
        )
        assert isinstance(report["study_plan"], list)


# ===========================================================================
# Case 4: Failed and needs_action highlighting
# ===========================================================================

class TestFailedAndNeedsAction:

    def test_failed_apps_identified(self, generator, week_start):
        """Failed applications should be identifiable from the applications list."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        failed = [a for a in report["applications"] if a["status"] == "failed"]
        assert len(failed) == 1
        assert failed[0]["company"] == "FailCo"

    def test_needs_action_apps_identified(self, generator, week_start):
        """needs_action applications must appear in the report."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        action = [a for a in report["applications"] if a["status"] == "needs_action"]
        assert len(action) == 1
        assert action[0]["company"] == "ActionCo"

    def test_failed_app_has_application_url(self, generator, week_start):
        """Failed/needs_action apps must include application_url for manual apply."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        for app in report["applications"]:
            if app["status"] in ("failed", "needs_action"):
                assert "application_url" in app, (
                    f"Missing application_url for {app['status']} app: {app['company']}"
                )
                assert app["application_url"].startswith("http")


# ===========================================================================
# Case 5: HTML report generation
# ===========================================================================

class TestHTMLGeneration:

    def test_html_file_created(self, generator, week_start):
        """HTML report file should be created at the expected path."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        # Manually trigger HTML save
        html_path = generator._save_html(1, week_start, report)
        assert os.path.exists(html_path), f"HTML file not found at: {html_path}"

    def test_html_contains_company_names(self, generator, week_start):
        """HTML content should mention each company from the applications."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        html_path = generator._save_html(1, week_start, report)
        with open(html_path, encoding="utf-8") as f:
            content = f.read()
        assert "AIBridge" in content
        assert "FailCo" in content

    def test_html_contains_study_plan(self, generator, week_start):
        """HTML should include the study plan section."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        html_path = generator._save_html(1, week_start, report)
        with open(html_path, encoding="utf-8") as f:
            content = f.read()
        assert "Weekly Study Plan" in content or "Study Plan" in content

    def test_html_highlights_action_required(self, generator, week_start):
        """HTML should have an 'Action Required' section for failed/needs_action."""
        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        html_path = generator._save_html(1, week_start, report)
        with open(html_path, encoding="utf-8") as f:
            content = f.read()
        assert "Action Required" in content or "needs_action" in content.lower()


# ===========================================================================
# Case 6: DB persistence
# ===========================================================================

class TestDatabasePersistence:

    def test_save_to_db_success(self, generator, week_start):
        """_save_to_db() should call db.commit() and return True."""
        from src.models.report import WeeklyReport

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.filter.return_value.first.return_value = None

        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        result = generator._save_to_db(mock_db, user_id=1, week_start=week_start, report=report)

        assert result is True
        mock_db.commit.assert_called_once()

    def test_save_to_db_failure_returns_false(self, generator, week_start):
        """If DB commit raises, _save_to_db() returns False without crashing."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.filter.return_value.first.return_value = None
        mock_db.commit.side_effect = Exception("DB connection lost")

        report = generator.generate_from_data(
            user_id=1, apps_data=SAMPLE_APPS, week_start=week_start
        )
        result = generator._save_to_db(mock_db, user_id=1, week_start=week_start, report=report)

        assert result is False
        mock_db.rollback.assert_called()

    def test_generate_with_db_calls_save(self, generator, week_start):
        """generate() with a real-like db_session should attempt to save to DB."""
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.filter.return_value.filter.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.filter.return_value.first.return_value = None

        with patch.object(generator, "_save_to_db", return_value=True) as mock_save:
            report = generator.generate(
                user_id=1,
                db_session=mock_db,
                week_start=week_start,
            )
            mock_save.assert_called_once()

        assert report["saved_to_db"] is True


# ===========================================================================
# Case 7: API route (GET /report/{user_id}/latest)
# ===========================================================================

class TestReportAPIRoute:

    def test_get_latest_report_returns_404_when_no_report(self):
        """GET /report/{user_id}/latest should return 404 when no report exists."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        with patch("src.api.routes.reports.SessionLocal", return_value=mock_db):
            from fastapi.testclient import TestClient
            # Import app after patching to avoid email-validator issue
            try:
                from src.api.routes.reports import router
                from fastapi import FastAPI
                test_app = FastAPI()
                test_app.include_router(router)
                client = TestClient(test_app)
                response = client.get("/report/999/latest")
                assert response.status_code == 404
            except ImportError:
                pytest.skip("FastAPI test client dependencies not available")

    def test_get_latest_report_returns_data_when_exists(self):
        """GET /report/{user_id}/latest returns structured data when report exists."""
        from src.models.report import WeeklyReport
        from datetime import datetime

        mock_record = WeeklyReport(
            id=1,
            user_id=1,
            week_start=datetime(2024, 7, 22),
            total_applications=5,
            successful_applications=3,
            summary=json.dumps({
                "insights": {"top_skills": ["Python", "Docker"], "top_gaps": ["Docker"]},
                "study_plan": [{"rank": 1, "skill": "Docker", "frequency": 3, "reason": "test"}],
                "html_path": "/data/reports/1/week_2024_30.html",
            }),
            created_at=datetime(2024, 7, 28),
        )

        mock_db = MagicMock()
        mock_db.__enter__ = lambda s: s
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_record

        with patch("src.api.routes.reports.SessionLocal", return_value=mock_db):
            from fastapi import FastAPI
            from src.api.routes.reports import router
            test_app = FastAPI()
            test_app.include_router(router)
            try:
                from fastapi.testclient import TestClient
                client = TestClient(test_app)
                response = client.get("/report/1/latest")
                assert response.status_code == 200
                data = response.json()
                assert data["user_id"] == 1
                assert "insights" in data
                assert "study_plan" in data
            except ImportError:
                pytest.skip("FastAPI test client dependencies not available")


# ===========================================================================
# Case 8: Helper utility tests
# ===========================================================================

class TestHelperUtilities:

    def test_parse_csv_field_basic(self):
        gen = ReportGenerator()
        result = gen._parse_csv_field("Python, Docker, AWS")
        assert result == ["Python", "Docker", "AWS"]

    def test_parse_csv_field_empty(self):
        gen = ReportGenerator()
        assert gen._parse_csv_field("") == []
        assert gen._parse_csv_field(None) == []

    def test_infer_role_category_ai(self):
        gen = ReportGenerator()
        assert gen._infer_role_category("AI Engineer Intern") == "AI/ML"

    def test_infer_role_category_backend(self):
        gen = ReportGenerator()
        assert gen._infer_role_category("Senior Backend Developer") == "Backend"

    def test_infer_role_category_data(self):
        gen = ReportGenerator()
        assert gen._infer_role_category("Data Analyst") == "Data"

    def test_infer_role_category_other(self):
        gen = ReportGenerator()
        assert gen._infer_role_category("Marketing Manager") == "Other"

    def test_current_week_monday_is_monday(self):
        monday = ReportGenerator._current_week_monday()
        assert monday.weekday() == 0, "Should be Monday (weekday=0)"
