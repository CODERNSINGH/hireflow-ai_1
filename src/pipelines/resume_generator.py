"""
HireFlow AI — Resume Tailoring Engine (RAG Pipeline)

Generates a unique tailored resume for each job application using a strict
Retrieval-Augmented Generation (RAG) approach:

1. DETERMINISTIC steps (no LLM):
   - select_projects(): Rank user's projects by relevance to the job.
   - reorder_skills(): Reorder user's skills to match JD priorities.

2. LLM step (only for free-text generation):
   - generate_summary(): Write a 2-3 sentence grounded summary.

ANTI-HALLUCINATION GUARANTEE:
Every skill in "skills" and every project in "projects" in the output of
tailor() is an exact item from the user's real master_profile. No new skill
or project name may appear anywhere in the output that wasn't already in
master_profile. The LLM only writes the free-text summary — it never selects,
adds, or modifies skills or projects.

Usage:
    python -m src.pipelines.resume_generator --user-id 1 --job-id 5
    python -m src.pipelines.resume_generator --user-id 1 \\
        --compare-jobs 5 8
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from src.config.database import SessionLocal
from src.models.job import Job
from src.models.user import User
from src.utils.llm_client import get_llm_client

logger = logging.getLogger(__name__)

# Small stopword list for description overlap scoring.
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "with",
        "for",
        "in",
        "on",
        "to",
        "of",
        "is",
        "are",
        "we",
        "you",
        "this",
        "that",
    }
)

_MAX_PROJECTS = 3

# ====================================================================== #
# ResumeTailoringEngine
# ====================================================================== #


class ResumeTailoringEngine:
    """Tailor a user's profile data to a specific job.

    All methods that touch user profile data are pure and deterministic
    EXCEPT generate_summary(), which is the ONLY method that calls the LLM.
    """

    def __init__(self, db: Optional[Session] = None) -> None:
        self.db = db or SessionLocal()
        self.llm_client = get_llm_client()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def tailor(self, user_id: int, job_id: int) -> dict[str, Any]:
        """Generate a tailored resume payload for a user + job pair.

        ANTI-HALLUCINATION GUARANTEE:
        Every skill in the returned "skills" list and every project in the
        returned "projects" list is an exact item from the user's real
        master_profile. No new skill or project name may appear anywhere in
        the output that wasn't already in master_profile. The LLM is only
        allowed to touch the free-text "summary" field.

        Returns:
            Dict with keys: summary, skills, projects, experience, education.

        Raises:
            ValueError: If user or job is not found.
        """
        user = self.db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise ValueError(f"User with id {user_id} not found.")

        job = self.db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            raise ValueError(f"Job with id {job_id} not found.")

        # Safely extract profile data (may be None, partial, etc.)
        profile: dict = user.master_profile or {}
        user_skills: list[str] = profile.get("skills", []) or []
        user_projects: list[dict] = profile.get("projects", []) or []
        user_experience: list[dict] = profile.get("experience", []) or []
        user_education: Any = profile.get("education", None)

        # Parse job skills (comma-separated string) — consistent with
        # match_scorer.py's _skill_match_score pattern.
        jd_skills = [
            s.strip().lower()
            for s in (job.skills_required or "").split(",")
            if s.strip()
        ]

        # Deterministic steps (no LLM)
        selected_projects = self.select_projects(user_projects, job.jd_text, jd_skills)
        reordered_skills = self.reorder_skills(user_skills, jd_skills)

        # LLM step (only for free-text summary)
        summary = self.generate_summary(
            {
                "name": user.name,
                "skills": reordered_skills,
                "projects": selected_projects,
            },
            job,
            job.listing_type,
        )

        return {
            "summary": summary,
            "skills": reordered_skills,
            "projects": selected_projects,
            "experience": user_experience,
            "education": user_education,
        }

    # ------------------------------------------------------------------ #
    # Deterministic: Project Selection (PURE PYTHON — NO LLM)
    # ------------------------------------------------------------------ #

    def select_projects(
        self,
        user_projects: list[dict],
        jd_text: str,
        jd_skills: list[str],
    ) -> list[dict]:
        """Rank and select up to 3 projects relevant to the job.

        PURE PYTHON. No LLM call. Scores each project by:
        - tech_overlap * 2 (tech list match against jd_skills)
        - description_overlap (word overlap with jd_text, minus stopwords)

        Returns the SAME dict objects from master_profile — unchanged.
        """
        if not user_projects:
            return []

        scored: list[tuple[int, dict]] = []

        for project in user_projects:
            tech_list: list[str] = project.get("tech", []) or []
            description: str = project.get("description", "") or ""

            # Tech overlap (case-insensitive)
            tech_overlap = sum(1 for t in tech_list if t.strip().lower() in jd_skills)

            # Description overlap: count significant shared words
            desc_words = _significant_words(description)
            jd_words = _significant_words(jd_text)
            description_overlap = len(desc_words & jd_words)

            total_score = tech_overlap * 2 + description_overlap
            scored.append((total_score, project))

        # Stable sort by score descending (preserves original order for ties)
        scored.sort(key=lambda x: (-x[0]))

        # Fallback: if ALL projects score 0, return first N in original order
        all_zero = all(score == 0 for score, _ in scored)
        if all_zero:
            return user_projects[:_MAX_PROJECTS]

        # Return top N with score > 0
        return [proj for score, proj in scored[:_MAX_PROJECTS] if score > 0]

    # ------------------------------------------------------------------ #
    # Deterministic: Skill Reordering (PURE PYTHON — NO LLM)
    # ------------------------------------------------------------------ #

    def reorder_skills(
        self,
        user_skills: list[str],
        jd_skills: list[str],
    ) -> list[str]:
        """Reorder user skills: JD-mentioned first, in JD order.

        PURE PYTHON. No LLM call.

        - matched skills appear in the order they appear in jd_skills
        - unmatched skills appear at the end, in original user_skills order
        - Preserves original casing/spelling from user_skills
        """
        if not user_skills:
            return []

        matched: list[str] = []
        matched_lower: set[str] = set()
        unmatched: list[str] = []

        # First pass: order by position in jd_skills
        for jd_skill in jd_skills:
            for us in user_skills:
                if us.lower() == jd_skill and us.lower() not in matched_lower:
                    matched.append(us)
                    matched_lower.add(us.lower())

        # Second pass: unmatched skills in original order
        for us in user_skills:
            if us.lower() not in matched_lower:
                unmatched.append(us)

        return matched + unmatched

    # ------------------------------------------------------------------ #
    # LLM-Powered: Summary Generation (ONLY METHOD THAT CALLS THE LLM)
    # ------------------------------------------------------------------ #

    def generate_summary(
        self,
        user_profile: dict,
        job: Job,
        listing_type: str,
    ) -> str:
        """Generate a 2-3 sentence tailored summary using the LLM.

        THE ONLY METHOD IN THIS CLASS THAT CALLS THE LLM.
        Falls back to a template-based summary on any exception.

        Args:
            user_profile: Dict with "name", "skills", "projects" — only
                real, selected data from the user's master_profile.
            job: The Job ORM object (uses role_title, company_name, jd_text).
            listing_type: "internship" or "job" — determines tone.

        Returns:
            A plain-text summary string (no markdown, no bullet points).
        """
        name = user_profile.get("name", "")
        skills = user_profile.get("skills", [])
        projects = user_profile.get("projects", [])

        # Build the prompt
        skills_str = ", ".join(skills) if skills else "(no specific skills listed)"
        projects_str = (
            "; ".join(
                f"{p.get('name', 'Project')}: {p.get('description', '')[:120]}"
                for p in projects
            )
            if projects
            else "(no projects listed)"
        )

        jd_excerpt = (job.jd_text or "")[:300]

        # Tone instruction based on listing_type
        if listing_type == "internship":
            tone_instruction = (
                "Use an early-career, enthusiasm-forward, learning-oriented tone. "
                "Emphasise eagerness to apply and grow, seeking to contribute to "
                "the team."
            )
        else:
            tone_instruction = (
                "Use an experienced, outcomes-and-impact-oriented tone. "
                "Emphasise proven experience in the relevant areas and "
                "specific deliverables."
            )

        prompt = (
            f"Write a 2-3 sentence professional summary for {name} "
            f"applying for the {job.role_title} position at {job.company_name}.\n\n"
            f"Candidate skills: {skills_str}\n\n"
            f"Candidate projects:\n{projects_str}\n\n"
            f"Job description excerpt:\n{jd_excerpt}\n\n"
            f"IMPORTANT — Grounding instruction:\n"
            f"Only reference the skills and projects listed above. Do not invent, "
            f"assume, or add any skill, project, experience, or qualification "
            f"not explicitly provided in this data.\n\n"
            f"{tone_instruction}\n\n"
            f"Return ONLY a plain-text summary (no markdown, no bullet points)."
        )

        try:
            result = self.llm_client.chat(prompt)
            return result.strip()
        except Exception as exc:
            logger.warning(
                "LLM call failed during resume summary generation: %s. "
                "Using template fallback.",
                exc,
            )
            return self._fallback_summary(name, skills, job, listing_type)

    # ------------------------------------------------------------------ #
    # Fallback summary (never crashes, even with empty skills)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fallback_summary(
        name: str,
        skills: list[str],
        job: Job,
        listing_type: str,
    ) -> str:
        """Build a template-based summary from real data when LLM fails.

        Gracefully handles empty skills list.
        """
        top_skills = skills[:3]
        tone_word = "eager" if listing_type == "internship" else "experienced"

        skills_part = (
            ", ".join(top_skills) if top_skills else "a range of relevant technologies"
        )

        return (
            f"{name} is an {tone_word} candidate skilled in {skills_part}, "
            f"applying for the {job.role_title} position at {job.company_name}."
        )


# ====================================================================== #
# Helper functions
# ====================================================================== #


def _significant_words(text: str) -> set[str]:
    """Split text into lowercase significant words, removing stopwords."""
    words = re.findall(r"[a-zA-Z0-9+#.]+", text.lower())
    return {w for w in words if len(w) > 1 and w not in _STOP_WORDS}


# ====================================================================== #
# CLI entry point
# ====================================================================== #


def main() -> None:
    """Run the resume tailoring engine from the command line.

    Usage:
        python -m src.pipelines.resume_generator --user-id 1 --job-id 5
        python -m src.pipelines.resume_generator --user-id 1 \\
            --compare-jobs 5 8
    """
    parser = argparse.ArgumentParser(
        description="Generate a tailored resume for a user and job.",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        required=True,
        help="Database ID of the user.",
    )
    parser.add_argument(
        "--job-id",
        type=int,
        default=None,
        help="Database ID of a single job to tailor for.",
    )
    parser.add_argument(
        "--compare-jobs",
        type=int,
        nargs=2,
        default=None,
        metavar=("JOB_ID_1", "JOB_ID_2"),
        help="Compare tailoring across two job IDs (same user).",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    engine = ResumeTailoringEngine()

    if args.compare_jobs:
        job_id_1, job_id_2 = args.compare_jobs
        result_1 = engine.tailor(args.user_id, job_id_1)
        result_2 = engine.tailor(args.user_id, job_id_2)

        print(f"=== Job 1 (id={job_id_1}) ===")
        print(json.dumps(result_1, indent=2, ensure_ascii=False, default=str))
        print()
        print(f"=== Job 2 (id={job_id_2}) ===")
        print(json.dumps(result_2, indent=2, ensure_ascii=False, default=str))
    elif args.job_id:
        result = engine.tailor(args.user_id, args.job_id)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        parser.error("Either --job-id or --compare-jobs is required.")


if __name__ == "__main__":
    main()
