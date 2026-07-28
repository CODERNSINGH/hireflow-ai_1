"""
Tests for PrepGuideAgent - round prediction and topic analysis.

At least 4 test cases:
1. JD with explicit process described
2. JD without any process info (graceful fallback)
3. Internship mode defaults (1-2 rounds)
4. Full-time job mode defaults (3 rounds)
Additional tests cover keyword inference, topic categorization, and edge cases.
"""

import pytest
from src.agents.prep_guide_agent import PrepGuideAgent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def agent():
    return PrepGuideAgent()


# ---------------------------------------------------------------------------
# Acceptance-criteria test cases (rounds)
# ---------------------------------------------------------------------------

class TestRoundsPrediction:

    # -----------------------------------------------------------------------
    # Case 1: JD with explicitly described process
    # -----------------------------------------------------------------------
    def test_explicit_process_in_jd(self, agent):
        """JD explicitly lists rounds - should extract them accurately."""
        jd_text = (
            "We are looking for an AI Engineer Intern.\n"
            "Selection process:\n"
            "Round 1: Online assessment - coding test on HackerRank\n"
            "Round 2: Technical interview with the engineering team\n"
            "Round 3: HR round\n"
            "Must know Python, LangChain, RAG."
        )
        result = agent.predict_rounds(
            jd_text=jd_text,
            company_stage="startup",
            listing_type="internship",
        )
        assert result["source"] == "explicit"
        assert result["round_count"] == 3
        assert len(result["rounds"]) == 3

        # Validate round structure
        for r in result["rounds"]:
            assert "number" in r
            assert "type" in r
            assert "label" in r
            assert "focus" in r
            assert "duration_minutes" in r
            assert "tips" in r
            assert isinstance(r["focus"], list)
            assert isinstance(r["tips"], list)
            assert len(r["focus"]) > 0
            assert len(r["tips"]) > 0

    # -----------------------------------------------------------------------
    # Case 2: JD with NO process info (graceful fallback)
    # -----------------------------------------------------------------------
    def test_no_process_info_fallback_job(self, agent):
        """JD mentions nothing about interview process - should return sensible default."""
        result = agent.predict_rounds(
            jd_text="Looking for a Python developer to join our team.",
            company_stage="early_startup",
            listing_type="job",
        )
        assert result is not None, "Should not crash or return None"
        assert result["source"] == "default"
        assert result["round_count"] >= 1
        assert len(result["rounds"]) >= 1
        assert "notes" in result

    def test_empty_jd_fallback(self, agent):
        """Empty JD should return default, never crash."""
        result = agent.predict_rounds(jd_text="", listing_type="job")
        assert result is not None
        assert result["source"] == "default"
        assert result["round_count"] >= 1

    def test_whitespace_only_jd_fallback(self, agent):
        """Whitespace-only JD should behave like empty JD."""
        result = agent.predict_rounds(jd_text="   \n\t  ", listing_type="internship")
        assert result is not None
        assert result["source"] == "default"

    # -----------------------------------------------------------------------
    # Case 3: Internship mode - default 1-2 rounds
    # -----------------------------------------------------------------------
    def test_internship_default_rounds(self, agent):
        """Internship listings without process info should default to 1-2 rounds."""
        result = agent.predict_rounds(
            jd_text="Looking for a Python intern to help build our data pipeline.",
            company_stage="startup",
            listing_type="internship",
        )
        assert result["source"] == "default"
        assert 1 <= result["round_count"] <= 2, (
            f"Internship default should be 1-2 rounds, got {result['round_count']}"
        )

    def test_internship_keyword_inferred_capped_at_two(self, agent):
        """
        When keywords imply >2 round types for internship but no explicit count,
        results should be capped at 2.
        """
        jd_text = (
            "Internship at TechCorp. "
            "We have an online assessment, followed by a technical interview, "
            "then a founder round and an HR interview."
        )
        result = agent.predict_rounds(
            jd_text=jd_text,
            company_stage="startup",
            listing_type="internship",
        )
        assert result["round_count"] <= 2, (
            f"Inferred internship rounds should be capped at 2, got {result['round_count']}"
        )

    # -----------------------------------------------------------------------
    # Case 4: Full-time job mode - default 3 rounds
    # -----------------------------------------------------------------------
    def test_job_default_rounds(self, agent):
        """Full-time job listings without process info should default to 3 rounds."""
        result = agent.predict_rounds(
            jd_text="Looking for a senior software engineer.",
            company_stage="enterprise",
            listing_type="job",
        )
        assert result["source"] == "default"
        assert result["round_count"] == 3, (
            f"Job default should be 3 rounds, got {result['round_count']}"
        )

    # -----------------------------------------------------------------------
    # Keyword inference
    # -----------------------------------------------------------------------
    def test_keyword_inference_online_test(self, agent):
        """JD mentioning 'online test' should infer an online assessment round."""
        jd_text = (
            "We are looking for an AI Engineer Intern. "
            "Selection process: online test, technical interview, HR round. "
            "Must know Python, LangChain, RAG."
        )
        result = agent.predict_rounds(
            jd_text=jd_text,
            company_stage="startup",
            listing_type="internship",
        )
        # Should detect from keywords (inferred or explicit)
        assert result["source"] in ("inferred", "explicit")
        assert result["round_count"] >= 1

        types = [r["type"] for r in result["rounds"]]
        assert "online_assessment" in types or "technical" in types

    def test_keyword_inference_founder_round(self, agent):
        """JD mentioning 'founder round' should include a founder type round."""
        jd_text = (
            "Join our early-stage startup. "
            "Interview process includes a technical screen and a founder round."
        )
        result = agent.predict_rounds(
            jd_text=jd_text,
            company_stage="early_startup",
            listing_type="job",
        )
        types = [r["type"] for r in result["rounds"]]
        assert "founder" in types, f"Expected founder round, got types: {types}"

    def test_keyword_inference_hr_round(self, agent):
        """JD mentioning 'HR round' should include an HR type round."""
        jd_text = "Process: technical interview followed by an HR round."
        result = agent.predict_rounds(
            jd_text=jd_text,
            company_stage="unknown",
            listing_type="job",
        )
        types = [r["type"] for r in result["rounds"]]
        assert "hr" in types, f"Expected HR round, got: {types}"

    # -----------------------------------------------------------------------
    # Round structure validation
    # -----------------------------------------------------------------------
    def test_each_round_has_required_keys(self, agent):
        """Every round dict must contain the 5 required keys."""
        result = agent.predict_rounds(
            jd_text="We are looking for a software engineer.",
            listing_type="job",
        )
        required_keys = {"number", "type", "label", "focus", "duration_minutes", "tips"}
        for r in result["rounds"]:
            missing = required_keys - set(r.keys())
            assert not missing, f"Round missing keys: {missing}"

    def test_round_numbers_are_sequential(self, agent):
        """Rounds should be numbered sequentially starting from 1."""
        result = agent.predict_rounds(
            jd_text="Technical interview and HR round.",
            listing_type="job",
        )
        for idx, r in enumerate(result["rounds"], start=1):
            assert r["number"] == idx, f"Expected round number {idx}, got {r['number']}"

    def test_duration_is_positive_integer(self, agent):
        """Duration in minutes must be a positive integer."""
        result = agent.predict_rounds(jd_text="", listing_type="job")
        for r in result["rounds"]:
            assert isinstance(r["duration_minutes"], int)
            assert r["duration_minutes"] > 0


# ---------------------------------------------------------------------------
# Acceptance-criteria test cases (topic analysis)
# ---------------------------------------------------------------------------

class TestTopicAnalysis:

    def test_strong_moderate_gap_classification(self, agent):
        """Core classification: strong = user has + JD needs, moderate = user has + JD doesn't, gap = JD needs + user lacks."""
        topics = agent.analyze_topics(
            user_skills=["Python", "FastAPI", "LangChain"],
            jd_skills=["Python", "LangChain", "TypeScript", "Docker", "RAG"],
            skill_gaps=["TypeScript", "Docker"],
        )
        assert "Python" in topics["strong"]
        assert "LangChain" in topics["strong"]
        assert "FastAPI" in topics["moderate"]
        # Gaps: TypeScript, Docker, RAG (user doesn't have any of these)
        assert "TypeScript" in topics["gaps"]
        assert "Docker" in topics["gaps"]
        assert "RAG" in topics["gaps"]

    def test_all_skills_match_jd(self, agent):
        """When user has all JD skills and no gaps, strong list = user_skills, gaps = []."""
        topics = agent.analyze_topics(
            user_skills=["Python", "Django"],
            jd_skills=["Python", "Django"],
            skill_gaps=[],
        )
        assert set(topics["strong"]) == {"Python", "Django"}
        assert topics["gaps"] == []
        assert topics["moderate"] == []

    def test_no_matching_skills(self, agent):
        """When user has no JD skills, everything is a gap."""
        topics = agent.analyze_topics(
            user_skills=["Excel", "PowerPoint"],
            jd_skills=["Python", "Docker"],
            skill_gaps=["Python", "Docker"],
        )
        assert topics["strong"] == []
        assert set(topics["gaps"]) == {"Python", "Docker"}

    def test_empty_user_skills(self, agent):
        """Empty user skills should not crash; all JD skills become gaps."""
        topics = agent.analyze_topics(
            user_skills=[],
            jd_skills=["Python", "LangChain"],
            skill_gaps=["Python", "LangChain"],
        )
        assert topics["strong"] == []
        assert topics["moderate"] == []
        assert set(topics["gaps"]) == {"Python", "LangChain"}

    def test_empty_jd_skills(self, agent):
        """Empty JD skills - all user skills go to moderate, no strong or gaps."""
        topics = agent.analyze_topics(
            user_skills=["Python", "FastAPI"],
            jd_skills=[],
            skill_gaps=[],
        )
        assert topics["strong"] == []
        assert set(topics["moderate"]) == {"Python", "FastAPI"}
        assert topics["gaps"] == []

    def test_case_insensitive_matching(self, agent):
        """Skill matching should be case-insensitive."""
        topics = agent.analyze_topics(
            user_skills=["python", "FASTAPI"],
            jd_skills=["Python", "FastAPI"],
            skill_gaps=[],
        )
        assert len(topics["strong"]) == 2
        assert topics["gaps"] == []

    def test_result_has_required_keys(self, agent):
        """analyze_topics must always return the three required keys."""
        topics = agent.analyze_topics(
            user_skills=["Python"],
            jd_skills=["Python", "Docker"],
            skill_gaps=["Docker"],
        )
        assert "strong" in topics
        assert "moderate" in topics
        assert "gaps" in topics
        assert isinstance(topics["strong"], list)
        assert isinstance(topics["moderate"], list)
        assert isinstance(topics["gaps"], list)

    def test_skill_not_double_counted(self, agent):
        """A skill should appear in exactly one bucket, not multiple."""
        topics = agent.analyze_topics(
            user_skills=["Python", "FastAPI", "Docker"],
            jd_skills=["Python", "Docker", "Kubernetes"],
            skill_gaps=["Kubernetes"],
        )
        all_skills = topics["strong"] + topics["moderate"] + topics["gaps"]
        # No duplicates within the output
        assert len(all_skills) == len(set(s.lower() for s in all_skills)), (
            "Skills should not appear in multiple buckets"
        )
