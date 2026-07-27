"""
HireFlow AI — Multi-Factor Match Scorer and Skill Gap Extractor

Scores every non-spam job in the database against a user's profile using
six weighted sub-scores:
  - Skill Match (40%): set overlap between user skills and job required skills,
    blended with embedding cosine similarity from the FAISS index.
  - Role Fit (20%): word-overlap similarity between user target roles and job title.
  - Experience Fit (15%): compatibility of user mode vs job listing type and
    experience requirements.
  - Location Fit (10%): remote match or city-level match against preferences.
  - Stipend/Salary Fit (10%): parsed numeric comparison.
  - Company Signal (5%): JD detail level and inverse spam confidence.

All scoring is deterministic — no LLM calls anywhere in the core path.
Running the scorer twice on identical data produces byte-identical output.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from src.config.database import SessionLocal
from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.pipelines.embedding_pipeline import EmbeddingPipeline

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Weights (must sum to 1.0)
# --------------------------------------------------------------------------- #
WEIGHT_SKILL = 0.40
WEIGHT_ROLE = 0.20
WEIGHT_EXPERIENCE = 0.15
WEIGHT_LOCATION = 0.10
WEIGHT_STIPEND = 0.10
WEIGHT_COMPANY = 0.05

# --------------------------------------------------------------------------- #
# Embedding blend ratio inside the skill-match sub-score
# --------------------------------------------------------------------------- #
EMBEDDING_BLEND_RATIO = 0.30  # 30% embedding similarity, 70% set overlap
EMBEDDING_DEFAULT_SIMILARITY = 0.1  # default when job not in top-K results

# --------------------------------------------------------------------------- #
# Common stop-words for role title matching
# --------------------------------------------------------------------------- #
_STOP_WORDS = frozenset(
    {
        "and",
        "the",
        "or",
        "of",
        "in",
        "for",
        "to",
        "a",
        "an",
        "is",
        "it",
        "at",
        "on",
        "by",
        "with",
        "as",
        "be",
        "but",
        "not",
        "are",
        "was",
        "were",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "intern",
        "engineer",
        "developer",
        "manager",
        "lead",
        "senior",
        "junior",
        "associate",
        "staff",
        "principal",
        "internship",
    }
)


class MatchScorer:
    """Scores every non-spam job against a user profile.

    Args:
        embedding_pipeline: Optional injected pipeline for testability.
            Defaults to a real EmbeddingPipeline.
        db: Optional SQLAlchemy session for testability.
            Defaults to a fresh SessionLocal().
    """

    def __init__(
        self,
        embedding_pipeline: Optional[EmbeddingPipeline] = None,
        db: Optional[Session] = None,
    ) -> None:
        self.embedding_pipeline = embedding_pipeline or EmbeddingPipeline()
        self.db = db or SessionLocal()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def score_all_jobs(self, user_id: int) -> list[dict]:
        """Score every non-spam job against the given user's profile.

        Returns a list of dicts sorted by match_score descending, with
        job_id ascending as a tiebreaker. Each dict contains:
            job_id, match_score, skill_matches, skill_gaps, rank

        Raises:
            ValueError: If no user exists with the given user_id.
        """
        user = self.db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise ValueError(f"User with id {user_id} not found.")

        # Fetch non-spam jobs (matching embedding pipeline's ~is_spam behaviour)
        jobs = self.db.query(Job).filter(~Job.is_spam).all()

        if not jobs:
            return []

        # Prepare user profile data
        profile: dict = user.master_profile or {}
        user_skills: list[str] = profile.get("skills", []) or []
        target_roles: list[str] = profile.get("target_roles", []) or []
        preferred_locations: list[str] = profile.get("preferred_locations", []) or []
        min_stipend: Optional[int] = profile.get("min_stipend")
        user_mode: str = (
            user.mode.value if hasattr(user.mode, "value") else str(user.mode)
        )

        # Compute embedding similarity for all jobs in one search call
        embedding_results: dict[int, float] = self._get_embedding_scores(
            user_skills, target_roles, jobs
        )

        # Score each job
        scored: list[dict] = []
        for job in jobs:
            emb_sim = embedding_results.get(job.id, EMBEDDING_DEFAULT_SIMILARITY)

            skill_score, skill_matches, skill_gaps = self._skill_match_score(
                user_skills, job.skills_required or "", emb_sim
            )
            role_score = self._role_fit_score(target_roles, job.role_title or "")
            exp_score = self._experience_fit_score(
                user_mode, job.experience_required or "", job.listing_type or ""
            )
            loc_score = self._location_fit_score(
                preferred_locations, job.location or ""
            )
            stipend_score = self._stipend_salary_fit_score(
                user_mode, min_stipend, job.stipend_salary or ""
            )
            company_score = self._company_signal_score(job)

            total = (
                WEIGHT_SKILL * skill_score
                + WEIGHT_ROLE * role_score
                + WEIGHT_EXPERIENCE * exp_score
                + WEIGHT_LOCATION * loc_score
                + WEIGHT_STIPEND * stipend_score
                + WEIGHT_COMPANY * company_score
            )

            scored.append(
                {
                    "job_id": job.id,
                    "match_score": round(total, 4),
                    "skill_matches": skill_matches,
                    "skill_gaps": skill_gaps,
                    "rank": 0,  # placeholder, assigned after sort
                }
            )

        # Sort by match_score descending, then job_id ascending (deterministic)
        scored.sort(key=lambda x: (-x["match_score"], x["job_id"]))

        # Assign rank (1-indexed)
        for i, entry in enumerate(scored):
            entry["rank"] = i + 1

        return scored

    def save_results(self, user_id: int, results: list[dict]) -> None:
        """Persist scoring results to the applications table.

        Creates new Application rows or updates existing ones for the
        same user_id + job_id combination (no duplicates). Commits once
        at the end for performance.
        """
        updated_count = 0
        created_count = 0

        for result in results:
            job_id = result["job_id"]

            existing = (
                self.db.query(Application)
                .filter(
                    Application.user_id == user_id,
                    Application.job_id == job_id,
                )
                .first()
            )

            skill_matches_json = json.dumps(result["skill_matches"], sort_keys=True)
            skill_gaps_json = json.dumps(result["skill_gaps"], sort_keys=True)

            if existing:
                existing.match_score = result["match_score"]
                existing.skill_gaps = skill_gaps_json
                existing.skill_matches = skill_matches_json
                existing.rank = result["rank"]
                updated_count += 1
            else:
                app = Application(
                    user_id=user_id,
                    job_id=job_id,
                    match_score=result["match_score"],
                    skill_gaps=skill_gaps_json,
                    skill_matches=skill_matches_json,
                    rank=result["rank"],
                    status="pending",
                )
                self.db.add(app)
                created_count += 1

        self.db.commit()
        logger.info(
            "Saved match results for user_id=%s: %d created, %d updated.",
            user_id,
            created_count,
            updated_count,
        )

    # ------------------------------------------------------------------ #
    # Embedding similarity
    # ------------------------------------------------------------------ #

    def _get_embedding_scores(
        self,
        user_skills: list[str],
        target_roles: list[str],
        jobs: list[Job],
    ) -> dict[int, float]:
        """Build a query from the user profile and run FAISS search.

        Returns a dict mapping job_id -> cosine similarity score (0–1).
        Jobs not in the top-K results get a low default.
        """
        query_parts = []
        query_parts.extend(user_skills)
        query_parts.extend(target_roles)
        query_text = " ".join(query_parts).strip()

        if not query_text:
            return {}

        try:
            top_k = max(len(jobs), 1)
            results = self.embedding_pipeline.search(query_text, top_k=top_k)
        except RuntimeError:
            logger.warning("FAISS index not built yet. Skipping embedding similarity.")
            return {}

        # Map job_id -> similarity score (cosine, 0–1)
        return {r["job_id"]: max(0.0, min(1.0, r["score"])) for r in results}

    # ------------------------------------------------------------------ #
    # Sub-score: Skill Match (40%)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _skill_match_score(
        user_skills: list[str],
        job_skills_required: str,
        embedding_sim: float = EMBEDDING_DEFAULT_SIMILARITY,
    ) -> tuple[float, list[str], list[str]]:
        """Compute set-based skill overlap blended with embedding similarity.

        Args:
            user_skills: List of skills from the user's master profile.
            job_skills_required: Comma-separated string from the Job model.
            embedding_sim: Cosine similarity from FAISS (0–1).

        Returns:
            Tuple of (score 0–1, sorted match list, sorted gap list).
        """
        # Normalise user skills
        user_set = set()
        for s in user_skills or []:
            normalized = s.strip().lower()
            if normalized:
                user_set.add(normalized)

        # Parse and normalise job skills
        if job_skills_required and job_skills_required.strip():
            job_skills = [
                s.strip().lower() for s in job_skills_required.split(",") if s.strip()
            ]
        else:
            job_skills = []

        job_set = set(job_skills)

        if not job_set:
            # No skills listed in JD — neutral score
            return 0.5, [], []

        matches = user_set & job_set
        gaps = job_set - user_set

        set_score = len(matches) / len(job_set)

        # Blend embedding similarity into the skill match score
        # This keeps the total weight at 40% (WEIGHT_SKILL)
        combined = (
            1.0 - EMBEDDING_BLEND_RATIO
        ) * set_score + EMBEDDING_BLEND_RATIO * embedding_sim
        combined = max(0.0, min(1.0, combined))

        return combined, sorted(matches), sorted(gaps)

    # ------------------------------------------------------------------ #
    # Sub-score: Role Fit (20%)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _role_fit_score(
        target_roles: list[str],
        job_role_title: str,
    ) -> float:
        """Word-overlap similarity between user target roles and job title.

        Returns the best match score across all target_roles (0–1).
        If user has no target_roles, returns neutral 0.5.
        """
        if not target_roles:
            return 0.5

        job_words = _significant_words(job_role_title)
        if not job_words:
            return 0.0

        best_score = 0.0
        for role in target_roles:
            role_words = _significant_words(role)
            if not role_words:
                continue

            intersection = role_words & job_words
            union = role_words | job_words

            score = len(intersection) / len(union) if union else 0.0
            best_score = max(best_score, score)

        return best_score

    # ------------------------------------------------------------------ #
    # Sub-score: Experience Fit (15%)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _experience_fit_score(
        user_mode: str,
        job_experience_required: str,
        job_listing_type: str,
    ) -> float:
        """Evaluate experience compatibility.

        Parsing approach:
        - Check if user mode and job listing type match. A mismatch (e.g.
          user in internship mode applying to a full-time job) scores low (0.2).
        - If both are internship mode, default to 1.0 (internships assume
          freshers) unless the experience field explicitly demands more than
          2 years of experience.
        - For job listings, parse the numeric year range from the string
          (e.g. "1-3 years", "3+ years") and score based on how reasonable
          it is for the user's mode. Unparseable strings return a neutral 0.7
          to avoid penalising listings that omit formal year requirements.
        """
        norm_mode = user_mode.strip().lower()
        norm_listing = job_listing_type.strip().lower()

        # Mode mismatch
        if norm_mode != norm_listing:
            return 0.2

        # Both internship — assume fresher-friendly by default
        if norm_mode == "internship":
            # Parse only to catch cases that explicitly require >2 years
            max_years = _parse_max_years(job_experience_required)
            if max_years is not None and max_years > 2:
                return 0.5  # internship requiring 3+ years is unusual
            return 1.0

        # Both job (full-time) — score based on experience range
        min_years, max_years = _parse_year_range(job_experience_required)

        if min_years is None:
            # Unparseable — neutral score, don't penalise
            return 0.7

        # For job mode: closer to 0-2 years entry level is a good fit
        # Entry level = best fit for most user profiles
        if max_years is not None and max_years <= 2:
            return 1.0
        if min_years <= 2:
            return 0.9
        if max_years is not None and max_years <= 5:
            return 0.7
        return 0.4

    # ------------------------------------------------------------------ #
    # Sub-score: Location Fit (10%)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _location_fit_score(
        preferred_locations: list[str],
        job_location: str,
    ) -> float:
        """Check remote or city-level location match.

        Returns 1.0 for remote match, exact city match, or no preference.
        Returns 0.3 if no match (relocation is sometimes acceptable).
        """
        if not preferred_locations:
            return 0.5

        job_loc_lower = (job_location or "").strip().lower()

        if not job_loc_lower:
            return 0.3

        # Remote match — job is remote, which matches everyone
        if job_loc_lower == "remote":
            return 1.0

        for pref in preferred_locations:
            pref_lower = pref.strip().lower()
            if pref_lower and pref_lower in job_loc_lower:
                return 1.0

        return 0.3

    # ------------------------------------------------------------------ #
    # Sub-score: Stipend/Salary Fit (10%)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _stipend_salary_fit_score(
        user_mode: str,
        min_stipend: Optional[int],
        job_stipend_salary: str,
    ) -> float:
        """Compare parsed job stipend/salary against user's minimum.

        Unparseable strings (e.g. "Competitive") return neutral 0.5.
        If user has no minimum set, returns neutral 0.5.
        """
        if min_stipend is None or min_stipend <= 0:
            return 0.5

        job_value = _parse_numeric_salary(job_stipend_salary)

        if job_value is None:
            return 0.5  # unparseable — neutral

        if job_value >= min_stipend:
            return 1.0

        # Proportionally scale down below minimum
        ratio = job_value / min_stipend
        return max(0.0, ratio)

    # ------------------------------------------------------------------ #
    # Sub-score: Company Signal (5%)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _company_signal_score(job: Job) -> float:
        """Weak deterministic signal using JD detail + spam confidence.

        Reasoning:
        - Longer, more detailed JDs tend to correlate with genuine, well-
          structured opportunities. Short or copy-paste JDs are weaker.
        - Spam confidence from earlier filtering provides a secondary signal.
        - Both are lightweight rule-based checks, not LLM evaluations.
        """
        score = 0.5  # neutral baseline

        # JD length bonus (up to +0.25 for very detailed JDs)
        jd_len = len(job.jd_text or "")
        jd_bonus = min(jd_len / 4000, 0.25)

        # Spam confidence penalty (up to -0.25 for high-spam listings)
        spam_penalty = 0.0
        if job.spam_confidence is not None:
            spam_penalty = job.spam_confidence * 0.25

        score = 0.5 + jd_bonus - spam_penalty
        return max(0.0, min(1.0, score))


# ====================================================================== #
# Helper functions
# ====================================================================== #


def _significant_words(text: str) -> set[str]:
    """Split text into lowercase words, removing stop-words and short tokens."""
    words = re.findall(r"[a-zA-Z0-9+#.]+", text.lower())
    return {w for w in words if len(w) > 1 and w not in _STOP_WORDS}


_YEARS_RE = re.compile(
    r"(?P<min>\d+)\s*(?:to|-|–)\s*(?P<max>\d+)\s*(?:years?|yrs?)",
    re.IGNORECASE,
)
_PLUS_YEARS_RE = re.compile(
    r"(?P<min>\d+)\s*\+\s*(?:years?|yrs?).*",
    re.IGNORECASE,
)
_YEARS_ONLY_RE = re.compile(
    r"(?P<val>\d+)\s*(?:years?|yrs?)",
    re.IGNORECASE,
)


def _parse_year_range(text: str) -> tuple[Optional[int], Optional[int]]:
    """Parse a year-range string like '1-3 years' or '2+ years'.

    Returns (min_years, max_years) or (None, None) if unparseable.
    """
    if not text or not text.strip():
        return None, None

    match = _YEARS_RE.search(text)
    if match:
        return int(match.group("min")), int(match.group("max"))

    # Check for single value like "2 years" before plus-pattern
    # to avoid "2 years" matching "2+ years" pattern when `+` is optional
    match = _YEARS_ONLY_RE.search(text)
    if match:
        val = int(match.group("val"))
        return val, val

    match = _PLUS_YEARS_RE.search(text)
    if match:
        min_val = int(match.group("min"))
        return min_val, min_val + 3  # heuristic cap
    if match:
        val = int(match.group("val"))
        return val, val

    return None, None


def _parse_max_years(text: str) -> Optional[int]:
    """Extract only the maximum year value from an experience string."""
    _, max_years = _parse_year_range(text)
    return max_years


_SALARY_RE = re.compile(r"[0-9]+(?:,[0-9]{3})*")


def _parse_numeric_salary(text: str) -> Optional[float]:
    """Extract a numeric salary/stipend value from a free-form string.

    Strips currency symbols and commas, then parses the first numeric
    group. Returns None if no numeric value can be extracted.
    """
    if not text or not text.strip():
        return None

    # Remove common currency symbols and whitespace
    cleaned = re.sub(r"[₹$€£¥\s]", "", text)

    match = _SALARY_RE.search(cleaned)
    if match:
        raw = match.group(0).replace(",", "")
        try:
            return float(raw)
        except ValueError:
            return None

    return None


# ====================================================================== #
# CLI entry point
# ====================================================================== #


def main() -> None:
    """Run the match scorer from the command line.

    Usage:
        python -m src.pipelines.match_scorer --user-id 1
        python -m src.pipelines.match_scorer --user-id 1 --dry-run
    """
    parser = argparse.ArgumentParser(
        description="Score all non-spam jobs against a user profile.",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        required=True,
        help="Database ID of the user to score jobs for.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results as JSON to stdout without writing to the database.",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    scorer = MatchScorer()
    results = scorer.score_all_jobs(args.user_id)

    if args.dry_run:
        # Sort keys consistently so `diff` works for determinism checks
        print(json.dumps(results, indent=2, sort_keys=True))
        return

    scorer.save_results(args.user_id, results)

    # Print summary
    print(f"Scored {len(results)} jobs for user_id={args.user_id}.")
    if results:
        print("Top 3 results:")
        for entry in results[:3]:
            print(
                f"  Rank {entry['rank']}: job_id={entry['job_id']}, "
                f"score={entry['match_score']}, "
                f"gaps={entry['skill_gaps']}"
            )


if __name__ == "__main__":
    main()
