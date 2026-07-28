"""
PrepGuideAgent - Interview Round Predictor and Topic Analyzer.

This module reads a job description and company signals to:
1. Predict the interview structure (number of rounds, type, focus, duration, tips).
2. Categorize the candidate's skills relative to the JD requirements into
   strong, moderate, and gap buckets.

The resource finder (Issue 18) uses the gap list to find learning materials.
The mock question generator (Issue 18) uses the round types to generate questions.
"""

import re
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Round type catalogue – order matters (specific patterns before generic ones)
# ---------------------------------------------------------------------------

_ROUND_TYPE_PATTERNS: List[Dict[str, Any]] = [
    {
        "keywords": [
            "online test", "online assessment", "coding test", "aptitude test",
            "hackerrank", "codility", "mcq", "written test", "assessment",
        ],
        "type": "online_assessment",
        "label": "Online Assessment",
        "focus": ["Problem solving", "Data structures", "Algorithms", "Aptitude"],
        "duration_minutes": 60,
        "tips": [
            "Practice timed coding challenges on platforms like HackerRank or LeetCode.",
            "Brush up on arrays, strings, sorting, and basic graph problems.",
            "Read the problem statement twice before coding.",
        ],
    },
    {
        "keywords": [
            "technical interview", "technical round", "tech round", "coding interview",
            "system design", "technical screen", "technical discussion",
        ],
        "type": "technical",
        "label": "Technical Interview",
        "focus": ["Coding", "System design", "Problem solving", "Technical depth"],
        "duration_minutes": 60,
        "tips": [
            "Explain your thought process out loud before writing code.",
            "Ask clarifying questions about constraints and edge cases.",
            "Practice on a whiteboard or shared editor without IDE hints.",
        ],
    },
    {
        "keywords": [
            "founder round", "founder interview", "ceo round", "co-founder",
            "leadership round", "executive round",
        ],
        "type": "founder",
        "label": "Founder / Leadership Round",
        "focus": ["Culture fit", "Vision alignment", "Problem-solving mindset", "Motivation"],
        "duration_minutes": 45,
        "tips": [
            "Research the company's mission, product, and recent news.",
            "Be ready to discuss why you want to work at this specific company.",
            "Show genuine curiosity; ask about the company's biggest challenges.",
        ],
    },
    {
        "keywords": [
            "hr round", "hr interview", "human resources", "behavioral interview",
            "culture fit", "cultural fit", "culture round",
        ],
        "type": "hr",
        "label": "HR / Behavioral Round",
        "focus": ["Communication", "Behavioral questions", "Career goals", "Culture fit"],
        "duration_minutes": 30,
        "tips": [
            "Use the STAR method (Situation, Task, Action, Result) for behavioral questions.",
            "Prepare 3-4 examples from past projects or academic work.",
            "Have a clear answer for 'Tell me about yourself' and 'Why this company?'.",
        ],
    },
    {
        "keywords": [
            "managerial round", "manager round", "hiring manager",
        ],
        "type": "managerial",
        "label": "Managerial Round",
        "focus": ["Team collaboration", "Past projects", "Ownership mindset", "Problem solving"],
        "duration_minutes": 45,
        "tips": [
            "Discuss specific contributions to team projects.",
            "Highlight situations where you took ownership without being asked.",
            "Ask about team structure and day-to-day responsibilities.",
        ],
    },
    {
        "keywords": [
            "portfolio review", "design round", "case study", "take-home", "assignment",
            "project round", "portfolio",
        ],
        "type": "portfolio_case",
        "label": "Portfolio / Case Study Round",
        "focus": ["Project walkthrough", "Design decisions", "Problem framing", "Communication"],
        "duration_minutes": 60,
        "tips": [
            "Walk through your project end-to-end: problem, approach, outcome.",
            "Anticipate questions about trade-offs and what you would do differently.",
            "Keep explanations concise and avoid jargon.",
        ],
    },
]

# ---------------------------------------------------------------------------
# Default round templates per listing type
# ---------------------------------------------------------------------------

_INTERNSHIP_DEFAULT_ROUNDS = [
    {
        "number": 1,
        "type": "online_assessment",
        "label": "Online Assessment",
        "focus": ["Problem solving", "Data structures", "Basic algorithms"],
        "duration_minutes": 60,
        "tips": [
            "Practice timed challenges on HackerRank or LeetCode.",
            "Focus on arrays, strings, and sorting problems.",
        ],
    },
    {
        "number": 2,
        "type": "hr",
        "label": "HR / Behavioral Round",
        "focus": ["Communication", "Motivation", "Culture fit"],
        "duration_minutes": 30,
        "tips": [
            "Use the STAR method for behavioral questions.",
            "Be clear about why you chose this internship.",
        ],
    },
]

_JOB_DEFAULT_ROUNDS = [
    {
        "number": 1,
        "type": "online_assessment",
        "label": "Online Assessment",
        "focus": ["Problem solving", "Data structures", "Algorithms"],
        "duration_minutes": 60,
        "tips": [
            "Practice on HackerRank or LeetCode.",
            "Focus on arrays, graphs, and dynamic programming.",
        ],
    },
    {
        "number": 2,
        "type": "technical",
        "label": "Technical Interview",
        "focus": ["Coding", "System design", "Technical depth"],
        "duration_minutes": 60,
        "tips": [
            "Think aloud and explain your reasoning.",
            "Ask clarifying questions before coding.",
        ],
    },
    {
        "number": 3,
        "type": "hr",
        "label": "HR / Behavioral Round",
        "focus": ["Communication", "Career goals", "Culture fit"],
        "duration_minutes": 30,
        "tips": [
            "Use the STAR method for behavioral questions.",
            "Research the company's mission and recent news.",
        ],
    },
]


class PrepGuideAgent:
    """
    Predicts interview rounds and categorizes skills relative to a JD.

    Usage::

        agent = PrepGuideAgent()

        # Predict rounds
        result = agent.predict_rounds(
            jd_text="...",
            company_stage="startup",
            listing_type="internship",
        )

        # Categorize skills
        topics = agent.analyze_topics(
            user_skills=["Python", "FastAPI"],
            jd_skills=["Python", "LangChain", "Docker"],
            skill_gaps=["LangChain", "Docker"],
        )
    """

    # Matches explicit round mentions: "3 rounds", "two rounds", "4-stage", etc.
    _ROUND_COUNT_RE = re.compile(
        r"\b(?:(\d+)|one|two|three|four|five|six)\s*(?:round|stage|interview|step|phase)s?\b",
        re.IGNORECASE,
    )

    # Ordered list patterns: "Round 1:", "Step 2 -", "Stage 3 -", etc.
    _ORDERED_PROCESS_RE = re.compile(
        r"(?:round|step|stage|phase)\s*\d+\s*[:\-]?\s*(.+?)(?=\n|$)",
        re.IGNORECASE,
    )

    # Process section header
    _PROCESS_SECTION_RE = re.compile(
        r"(?:interview\s+process|hiring\s+process|selection\s+process|recruitment\s+process)"
        r"[\s\S]{0,600}",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict_rounds(
        self,
        jd_text: str,
        company_stage: str = "unknown",
        listing_type: str = "job",
    ) -> Dict[str, Any]:
        """
        Predict interview rounds from a job description.

        Parameters
        ----------
        jd_text:
            The full text of the job description.
        company_stage:
            One of: ``startup``, ``early_startup``, ``series_a``, ``series_b``,
            ``mid_size``, ``enterprise``, ``unknown``.
        listing_type:
            ``"internship"`` or ``"job"`` (full-time).

        Returns
        -------
        dict with keys:
            - ``round_count`` (int)
            - ``rounds`` (list of round dicts)
            - ``source`` (``"explicit"`` | ``"inferred"`` | ``"default"``)
            - ``notes`` (str)
        """
        if not jd_text or not jd_text.strip():
            return self._default_result(listing_type)

        jd_lower = jd_text.lower()

        # 1. Try to detect explicitly described process
        explicit_rounds = self._extract_explicit_rounds(jd_text)
        if explicit_rounds:
            logger.debug("Using explicit round extraction from JD")
            return {
                "round_count": len(explicit_rounds),
                "rounds": explicit_rounds,
                "source": "explicit",
                "notes": "Interview process extracted directly from the job description.",
            }

        # 2. Keyword-based inference from JD body
        inferred_rounds = self._infer_rounds_from_keywords(jd_lower, listing_type)
        if inferred_rounds:
            logger.debug("Using keyword-inferred rounds")
            return {
                "round_count": len(inferred_rounds),
                "rounds": inferred_rounds,
                "source": "inferred",
                "notes": "Interview process inferred from job description keywords.",
            }

        # 3. Sensible defaults
        logger.debug("Using default rounds (no process info found in JD)")
        return self._default_result(listing_type)

    def analyze_topics(
        self,
        user_skills: List[str],
        jd_skills: List[str],
        skill_gaps: List[str],
    ) -> Dict[str, List[str]]:
        """
        Categorize skills into strong, moderate, and gap buckets.

        Parameters
        ----------
        user_skills:
            Skills the user has listed in their profile.
        jd_skills:
            All skills mentioned in the JD.
        skill_gaps:
            Skills already identified as gaps (from a matcher, for example).

        Returns
        -------
        dict with keys:
            - ``strong``   - user has the skill AND it matches a JD requirement.
            - ``moderate`` - user has the skill but it is not a JD requirement.
            - ``gaps``     - skills the JD requires that the user does not have.
        """
        user_lower = {s.lower().strip() for s in user_skills if s}
        jd_lower_set = {s.lower().strip() for s in jd_skills if s}
        gap_lower = {s.lower().strip() for s in skill_gaps if s}

        strong: List[str] = []
        moderate: List[str] = []

        for skill in user_skills:
            norm = skill.lower().strip()
            if not norm:
                continue
            if norm in jd_lower_set and norm not in gap_lower:
                strong.append(skill)
            elif norm not in jd_lower_set:
                moderate.append(skill)

        # Gaps = JD skills the user does not have
        gaps: List[str] = []
        for skill in jd_skills:
            norm = skill.lower().strip()
            if norm and norm not in user_lower:
                gaps.append(skill)

        return {
            "strong": strong,
            "moderate": moderate,
            "gaps": gaps,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _default_result(self, listing_type: str) -> Dict[str, Any]:
        """Return a sensible default when no process info is found."""
        rounds = (
            _INTERNSHIP_DEFAULT_ROUNDS if listing_type == "internship" else _JOB_DEFAULT_ROUNDS
        )
        return {
            "round_count": len(rounds),
            "rounds": [r.copy() for r in rounds],
            "source": "default",
            "notes": (
                "No interview process details found in the JD. "
                "Using standard defaults for this listing type."
            ),
        }

    def _extract_explicit_rounds(self, jd_text: str) -> List[Dict[str, Any]]:
        """
        Try to find explicitly described rounds in the JD.
        Returns a list of round dicts, or empty list if nothing found.
        """
        rounds: List[Dict[str, Any]] = []

        # Look inside a "process" section if present
        section_match = self._PROCESS_SECTION_RE.search(jd_text)
        search_area = section_match.group(0) if section_match else jd_text

        # Find ordered items like "Round 1: ...", "Step 2 - ..."
        matches = self._ORDERED_PROCESS_RE.findall(search_area)
        if not matches:
            return []

        for idx, description in enumerate(matches, start=1):
            description = description.strip()
            rtype = self._classify_round_text(description.lower())
            rounds.append(self._build_round(idx, rtype, description))

        return rounds

    def _infer_rounds_from_keywords(
        self, jd_lower: str, listing_type: str
    ) -> List[Dict[str, Any]]:
        """
        Keyword-scan the whole JD for round-type signals.
        Returns ordered list of unique round dicts.
        """
        seen_types: List[str] = []
        rounds: List[Dict[str, Any]] = []

        for pattern in _ROUND_TYPE_PATTERNS:
            for kw in pattern["keywords"]:
                if kw in jd_lower:
                    rtype = pattern["type"]
                    if rtype not in seen_types:
                        seen_types.append(rtype)
                        rounds.append(self._build_round_from_pattern(len(rounds) + 1, pattern))
                    break  # Only match each pattern once

        if not rounds:
            return []

        # Internship listings: cap at 2 rounds unless JD explicitly says more
        if listing_type == "internship" and len(rounds) > 2:
            count_match = self._ROUND_COUNT_RE.search(jd_lower)
            if not count_match:
                rounds = rounds[:2]

        return rounds

    def _classify_round_text(self, text: str) -> str:
        """Map a free-text round description to a type key."""
        for pattern in _ROUND_TYPE_PATTERNS:
            for kw in pattern["keywords"]:
                if kw in text:
                    return pattern["type"]
        if re.search(r"\bhr\b", text):
            return "hr"
        return "technical"  # sensible fallback

    def _build_round(self, number: int, rtype: str, label_hint: str = "") -> Dict[str, Any]:
        """Build a round dict from a type key."""
        for pattern in _ROUND_TYPE_PATTERNS:
            if pattern["type"] == rtype:
                return self._build_round_from_pattern(number, pattern, label_hint)
        return {
            "number": number,
            "type": rtype,
            "label": label_hint.title() or rtype.replace("_", " ").title(),
            "focus": ["General assessment"],
            "duration_minutes": 45,
            "tips": ["Review the JD thoroughly and prepare relevant examples."],
        }

    @staticmethod
    def _build_round_from_pattern(
        number: int, pattern: Dict[str, Any], label_hint: str = ""
    ) -> Dict[str, Any]:
        return {
            "number": number,
            "type": pattern["type"],
            "label": pattern["label"],
            "focus": list(pattern["focus"]),
            "duration_minutes": pattern["duration_minutes"],
            "tips": list(pattern["tips"]),
        }
