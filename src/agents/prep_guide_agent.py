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


# ===========================================================================
# Issue 18 additions — Resource Finder & Mock Question Generator
# ===========================================================================

import os
from typing import Optional

# ---------------------------------------------------------------------------
# Static curated resource catalogue
# Keyed by normalised skill name (lowercase).  Each entry contains 2-3 links
# with title, url, and type (docs | video | article | course).
# Used as primary source when Tavily key is absent and as fallback otherwise.
# ---------------------------------------------------------------------------

_STATIC_RESOURCES: Dict[str, List[Dict[str, str]]] = {
    "python": [
        {"title": "Official Python Docs", "url": "https://docs.python.org/3/", "type": "docs"},
        {"title": "Python Tutorial – freeCodeCamp", "url": "https://www.freecodecamp.org/news/the-python-handbook/", "type": "article"},
        {"title": "Python Full Course – Programming with Mosh", "url": "https://www.youtube.com/watch?v=_uQrJ0TkZlc", "type": "video"},
    ],
    "langchain": [
        {"title": "LangChain Official Docs", "url": "https://python.langchain.com/docs/get_started/introduction", "type": "docs"},
        {"title": "LangChain Crash Course – freeCodeCamp", "url": "https://www.youtube.com/watch?v=lG7Uxts9SXs", "type": "video"},
        {"title": "LangChain Conceptual Guide", "url": "https://python.langchain.com/docs/concepts/", "type": "docs"},
    ],
    "langgraph": [
        {"title": "LangGraph Official Docs", "url": "https://langchain-ai.github.io/langgraph/", "type": "docs"},
        {"title": "LangGraph Tutorial", "url": "https://langchain-ai.github.io/langgraph/tutorials/", "type": "docs"},
        {"title": "Build Agentic Apps with LangGraph", "url": "https://www.youtube.com/watch?v=R8KB-Zcynxc", "type": "video"},
    ],
    "typescript": [
        {"title": "TypeScript Official Docs", "url": "https://www.typescriptlang.org/docs/", "type": "docs"},
        {"title": "TypeScript Handbook", "url": "https://www.typescriptlang.org/docs/handbook/intro.html", "type": "docs"},
        {"title": "TypeScript Course – freeCodeCamp", "url": "https://www.youtube.com/watch?v=30LWjhZzg50", "type": "video"},
    ],
    "docker": [
        {"title": "Docker Official Docs", "url": "https://docs.docker.com/get-started/", "type": "docs"},
        {"title": "Docker Tutorial for Beginners", "url": "https://www.youtube.com/watch?v=3c-iBn73dDE", "type": "video"},
        {"title": "Docker Curriculum", "url": "https://docker-curriculum.com/", "type": "article"},
    ],
    "rag": [
        {"title": "RAG Explained – LangChain Blog", "url": "https://blog.langchain.dev/retrieval-augmented-generation-rag/", "type": "article"},
        {"title": "RAG from Scratch – freeCodeCamp", "url": "https://www.youtube.com/watch?v=sVcwVQRHIc8", "type": "video"},
        {"title": "LangChain RAG Tutorial", "url": "https://python.langchain.com/docs/tutorials/rag/", "type": "docs"},
    ],
    "fastapi": [
        {"title": "FastAPI Official Docs", "url": "https://fastapi.tiangolo.com/", "type": "docs"},
        {"title": "FastAPI Full Course", "url": "https://www.youtube.com/watch?v=7t2alSnE2-I", "type": "video"},
        {"title": "FastAPI Tutorial – Real Python", "url": "https://realpython.com/fastapi-python-web-apis/", "type": "article"},
    ],
    "react": [
        {"title": "React Official Docs", "url": "https://react.dev/learn", "type": "docs"},
        {"title": "React Full Course – freeCodeCamp", "url": "https://www.youtube.com/watch?v=4UZrsTqkcW4", "type": "video"},
        {"title": "React Tutorial – W3Schools", "url": "https://www.w3schools.com/react/", "type": "article"},
    ],
    "javascript": [
        {"title": "MDN JavaScript Guide", "url": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide", "type": "docs"},
        {"title": "JavaScript.info", "url": "https://javascript.info/", "type": "article"},
        {"title": "JavaScript Full Course – freeCodeCamp", "url": "https://www.youtube.com/watch?v=jS4aFq5-91M", "type": "video"},
    ],
    "sql": [
        {"title": "SQL Tutorial – W3Schools", "url": "https://www.w3schools.com/sql/", "type": "article"},
        {"title": "PostgreSQL Official Docs", "url": "https://www.postgresql.org/docs/", "type": "docs"},
        {"title": "SQL Full Course – freeCodeCamp", "url": "https://www.youtube.com/watch?v=HXV3zeQKqGY", "type": "video"},
    ],
    "machine learning": [
        {"title": "ML Course – fast.ai", "url": "https://course.fast.ai/", "type": "course"},
        {"title": "Scikit-learn Docs", "url": "https://scikit-learn.org/stable/user_guide.html", "type": "docs"},
        {"title": "ML Crash Course – Google", "url": "https://developers.google.com/machine-learning/crash-course", "type": "course"},
    ],
    "deep learning": [
        {"title": "Deep Learning Specialization – Coursera", "url": "https://www.coursera.org/specializations/deep-learning", "type": "course"},
        {"title": "fast.ai Deep Learning Course", "url": "https://course.fast.ai/", "type": "course"},
        {"title": "PyTorch Official Tutorials", "url": "https://pytorch.org/tutorials/", "type": "docs"},
    ],
    "kubernetes": [
        {"title": "Kubernetes Official Docs", "url": "https://kubernetes.io/docs/home/", "type": "docs"},
        {"title": "Kubernetes Tutorial – freeCodeCamp", "url": "https://www.youtube.com/watch?v=X48VuDVv0do", "type": "video"},
        {"title": "Kubernetes Crash Course", "url": "https://www.youtube.com/watch?v=s_o8dwzRlu4", "type": "video"},
    ],
    "aws": [
        {"title": "AWS Getting Started", "url": "https://aws.amazon.com/getting-started/", "type": "docs"},
        {"title": "AWS Free Training", "url": "https://explore.skillbuilder.aws/learn", "type": "course"},
        {"title": "AWS Tutorial – freeCodeCamp", "url": "https://www.youtube.com/watch?v=SOTamWNgDKc", "type": "video"},
    ],
    "git": [
        {"title": "Git Official Docs", "url": "https://git-scm.com/doc", "type": "docs"},
        {"title": "Pro Git Book (free)", "url": "https://git-scm.com/book/en/v2", "type": "article"},
        {"title": "Git & GitHub Crash Course – Traversy Media", "url": "https://www.youtube.com/watch?v=SWYqp7iY_Tc", "type": "video"},
    ],
    "system design": [
        {"title": "System Design Primer – GitHub", "url": "https://github.com/donnemartin/system-design-primer", "type": "article"},
        {"title": "System Design Interview – Alex Xu (free summary)", "url": "https://bytebytego.com/courses/system-design-interview", "type": "course"},
        {"title": "System Design Concepts – freeCodeCamp", "url": "https://www.youtube.com/watch?v=FSR1s2b-l_I", "type": "video"},
    ],
    "multi-agent": [
        {"title": "LangGraph Multi-Agent Tutorial", "url": "https://langchain-ai.github.io/langgraph/tutorials/multi_agent/multi-agent-collaboration/", "type": "docs"},
        {"title": "Agentic AI Overview – LangChain Blog", "url": "https://blog.langchain.dev/what-is-an-agent/", "type": "article"},
        {"title": "Building Multi-Agent Systems", "url": "https://www.youtube.com/watch?v=hvAPnpSfSGo", "type": "video"},
    ],
}

# Generic fallback when a skill isn't in the catalogue
_GENERIC_RESOURCE_TEMPLATE = [
    {
        "title": "Search on freeCodeCamp",
        "url": "https://www.freecodecamp.org/news/search/?query={topic}",
        "type": "article",
    },
    {
        "title": "Official Documentation Search",
        "url": "https://devdocs.io/#q={topic}",
        "type": "docs",
    },
]

# ---------------------------------------------------------------------------
# Question templates per category and listing_type
# ---------------------------------------------------------------------------

_TECHNICAL_QUESTIONS = [
    "Can you walk me through how {skill} works under the hood?",
    "How would you use {skill} to solve a real-world problem at {company}?",
    "What are the main trade-offs when choosing {skill} over alternatives?",
    "Describe a bug or unexpected behaviour you encountered while using {skill} and how you resolved it.",
    "How do you test code that relies heavily on {skill}?",
]

_TECHNICAL_QUESTIONS_DEEP = [
    "Design a production-grade system at {company} that uses {skill}. Walk me through the architecture.",
    "How does {skill} handle scale? What breaks first under load, and how would you fix it?",
    "Explain the internal data structures or algorithms that make {skill} efficient.",
    "Compare {skill} to two alternatives and explain when you'd choose each.",
    "How would you migrate a legacy codebase to use {skill} with minimal risk?",
]

_BEHAVIORAL_QUESTIONS = [
    "Tell me about a project where you used {skill}. What was your specific contribution?",
    "Describe a time you had to learn {skill} quickly. How did you approach it?",
    "Have you ever disagreed with a technical decision about {skill}? How did you handle it?",
    "Tell me about a time a project involving {skill} didn't go as planned. What did you learn?",
]

_DESIGN_QUESTIONS = [
    "How would you design a {skill}-based pipeline for {company}'s core product?",
    "If you had to add {skill} to an existing system with no downtime, what would your rollout plan look like?",
    "What would your ideal architecture look like for a system that needs to scale {skill} to 10x current load?",
]

_FOUNDER_BEHAVIORAL = [
    "Why do you want to work at {company} specifically, rather than a larger company?",
    "What does building something from zero to one mean to you?",
    "Where do you see AI heading in the next 3 years, and how does that align with what {company} is doing?",
    "What's a problem you've noticed in the industry that {company} could solve?",
]

_HR_BEHAVIORAL = [
    "Tell me about yourself and why you applied to {company}.",
    "Where do you see yourself in 2 years from now?",
    "What's your biggest strength, and how has it helped you in a technical project?",
    "Describe a time you had to manage competing priorities. How did you decide what to do first?",
    "How do you handle feedback that you disagree with?",
]


class ResourceFinder:
    """
    Finds learning resources per skill topic.

    Strategy:
    1. If TAVILY_API_KEY is set, query Tavily for live web results.
    2. Fall back to (or supplement with) the curated static catalogue.
    3. If a topic has no static entry and Tavily is unavailable, return
       generic search links so the caller always gets something useful.
    """

    def __init__(self, tavily_api_key: Optional[str] = None) -> None:
        self._api_key = tavily_api_key or os.environ.get("TAVILY_API_KEY") or self._load_from_settings()

    @staticmethod
    def _load_from_settings() -> Optional[str]:
        try:
            from src.config.settings import get_settings
            return get_settings().TAVILY_API_KEY
        except Exception:
            return None

    def get_resources(
        self,
        topic: str,
        max_results: int = 3,
    ) -> List[Dict[str, str]]:
        """
        Return 2-3 learning resources for the given topic.

        Parameters
        ----------
        topic : str
            The skill/topic to find resources for.
        max_results : int
            Maximum number of links to return (default 3).

        Returns
        -------
        list of dicts, each with keys: title, url, type
        """
        norm = topic.lower().strip()

        # 1. Try Tavily live search
        if self._api_key and self._api_key.strip() not in ("", "your_tavily_api_key_here"):
            live = self._tavily_search(topic, max_results)
            if live:
                return live[:max_results]

        # 2. Static catalogue lookup (exact or partial match)
        static = self._static_lookup(norm, max_results)
        if static:
            return static

        # 3. Generic fallback — always returns something
        return self._generic_fallback(topic, max_results)

    def _tavily_search(self, topic: str, max_results: int) -> List[Dict[str, str]]:
        """Call Tavily search API and map results to our schema."""
        try:
            from tavily import TavilyClient  # type: ignore
            client = TavilyClient(api_key=self._api_key)
            query = f"learn {topic} tutorial documentation beginner guide"
            response = client.search(query=query, max_results=max_results + 2, search_depth="basic")
            results = []
            for r in response.get("results", []):
                url = r.get("url", "")
                title = r.get("title", url)
                rtype = self._classify_url_type(url)
                if url and title:
                    results.append({"title": title, "url": url, "type": rtype})
            return results[:max_results]
        except Exception as exc:
            logger.warning("Tavily search failed for '%s': %s — falling back to static", topic, exc)
            return []

    def _static_lookup(self, norm: str, max_results: int) -> List[Dict[str, str]]:
        """Exact-then-partial match against the static catalogue."""
        if norm in _STATIC_RESOURCES:
            return list(_STATIC_RESOURCES[norm][:max_results])
        # Partial match
        for key, resources in _STATIC_RESOURCES.items():
            if norm in key or key in norm:
                return list(resources[:max_results])
        return []

    def _generic_fallback(self, topic: str, max_results: int) -> List[Dict[str, str]]:
        """Return generic search links when nothing else matches."""
        encoded = topic.replace(" ", "+")
        return [
            {
                "title": f"freeCodeCamp — {topic} articles",
                "url": f"https://www.freecodecamp.org/news/search/?query={encoded}",
                "type": "article",
            },
            {
                "title": f"DevDocs — {topic} reference",
                "url": f"https://devdocs.io/#q={encoded}",
                "type": "docs",
            },
        ][:max_results]

    @staticmethod
    def _classify_url_type(url: str) -> str:
        url_lower = url.lower()
        if any(x in url_lower for x in ["youtube.com", "youtu.be", "vimeo.com"]):
            return "video"
        if any(x in url_lower for x in ["coursera", "udemy", "pluralsight", "edx", "skillbuilder", "fast.ai"]):
            return "course"
        if any(x in url_lower for x in ["/docs/", "documentation", "reference", "api-reference", "devdocs"]):
            return "docs"
        return "article"


class MockQuestionGenerator:
    """
    Generates JD-specific mock interview questions.

    Questions are derived from the actual skills and context in the JD,
    not from generic question banks.
    """

    # JD keyword → technology / concept
    _SKILL_SIGNALS: List[tuple] = [
        (r"langchain", "LangChain"),
        (r"langgraph", "LangGraph"),
        (r"rag|retrieval.augmented", "RAG (Retrieval-Augmented Generation)"),
        (r"multi.?agent", "multi-agent systems"),
        (r"vector\s*(store|database|db|search)", "vector databases"),
        (r"fastapi", "FastAPI"),
        (r"typescript", "TypeScript"),
        (r"react\.?js|reactjs", "React"),
        (r"docker", "Docker"),
        (r"kubernetes|k8s", "Kubernetes"),
        (r"aws|gcp|azure|cloud", "cloud infrastructure"),
        (r"system design", "system design"),
        (r"machine\s*learning|ml\b", "machine learning"),
        (r"deep\s*learning|neural\s*network", "deep learning"),
        (r"sql|postgres|mysql", "SQL"),
        (r"python", "Python"),
        (r"javascript|js\b", "JavaScript"),
        (r"git\b", "Git"),
    ]

    def generate(
        self,
        jd_text: str,
        company_name: str = "the company",
        listing_type: str = "job",
        round_types: Optional[List[str]] = None,
        max_per_category: int = 3,
    ) -> List[Dict[str, str]]:
        """
        Generate mock interview questions tailored to the JD.

        Parameters
        ----------
        jd_text : str
            Full job description text.
        company_name : str
            Company name for personalised questions.
        listing_type : str
            "internship" or "job" — controls depth.
        round_types : list of str, optional
            Round types from predict_rounds (e.g. ["technical", "hr", "founder"]).
            If None, all categories are generated.
        max_per_category : int
            Maximum questions per category (default 3; reduced for internship).

        Returns
        -------
        list of dicts with keys: question, category, skill (optional)
        """
        if listing_type == "internship":
            max_per_category = min(max_per_category, 2)

        detected_skills = self._extract_skills(jd_text)
        round_types = round_types or ["technical", "hr"]
        questions: List[Dict[str, str]] = []

        # Technical questions — from JD skills
        if "technical" in round_types or "online_assessment" in round_types:
            templates = _TECHNICAL_QUESTIONS_DEEP if listing_type == "job" else _TECHNICAL_QUESTIONS
            tech_qs = self._build_tech_questions(
                detected_skills, company_name, templates, max_per_category
            )
            questions.extend(tech_qs)

        # Behavioral questions — from JD skills
        if any(rt in round_types for rt in ("hr", "behavioral", "technical", "managerial")):
            beh_qs = self._build_behavioral_questions(
                detected_skills, company_name, max_per_category
            )
            questions.extend(beh_qs)

        # Design questions — for job listings or when design/portfolio round present
        if listing_type == "job" or "portfolio_case" in (round_types or []):
            design_qs = self._build_design_questions(
                detected_skills, company_name, max_per_category
            )
            questions.extend(design_qs)

        # Founder / culture questions
        if "founder" in round_types:
            for q_tmpl in _FOUNDER_BEHAVIORAL[:max_per_category]:
                questions.append({
                    "question": q_tmpl.format(company=company_name),
                    "category": "behavioral",
                })

        # HR questions
        if "hr" in round_types:
            for q_tmpl in _HR_BEHAVIORAL[:max_per_category]:
                questions.append({
                    "question": q_tmpl.format(company=company_name),
                    "category": "behavioral",
                })

        # Deduplicate
        seen: set = set()
        unique: List[Dict[str, str]] = []
        for q in questions:
            key = q["question"].lower()
            if key not in seen:
                seen.add(key)
                unique.append(q)

        return unique

    def _extract_skills(self, jd_text: str) -> List[str]:
        """Extract skill/technology signals from JD text."""
        found: List[str] = []
        jd_lower = jd_text.lower()
        for pattern, label in self._SKILL_SIGNALS:
            if re.search(pattern, jd_lower):
                found.append(label)
        return found or ["software engineering"]  # always have at least one skill

    def _build_tech_questions(
        self,
        skills: List[str],
        company: str,
        templates: List[str],
        limit: int,
    ) -> List[Dict[str, str]]:
        questions = []
        for skill in skills[:limit]:
            tmpl = templates[len(questions) % len(templates)]
            questions.append({
                "question": tmpl.format(skill=skill, company=company),
                "category": "technical",
                "skill": skill,
            })
            if len(questions) >= limit:
                break
        return questions

    def _build_behavioral_questions(
        self,
        skills: List[str],
        company: str,
        limit: int,
    ) -> List[Dict[str, str]]:
        questions = []
        for i, skill in enumerate(skills[:limit]):
            tmpl = _BEHAVIORAL_QUESTIONS[i % len(_BEHAVIORAL_QUESTIONS)]
            questions.append({
                "question": tmpl.format(skill=skill, company=company),
                "category": "behavioral",
                "skill": skill,
            })
        return questions

    def _build_design_questions(
        self,
        skills: List[str],
        company: str,
        limit: int,
    ) -> List[Dict[str, str]]:
        questions = []
        for i, skill in enumerate(skills[:limit]):
            tmpl = _DESIGN_QUESTIONS[i % len(_DESIGN_QUESTIONS)]
            questions.append({
                "question": tmpl.format(skill=skill, company=company),
                "category": "design",
                "skill": skill,
            })
        return questions


# ---------------------------------------------------------------------------
# Attach new methods to PrepGuideAgent
# ---------------------------------------------------------------------------

def _prep_guide_find_resources(
    self,
    topics: List[str],
    max_per_topic: int = 3,
) -> Dict[str, List[Dict[str, str]]]:
    """
    Find 2-3 learning resources for each topic.

    Parameters
    ----------
    topics : list of str
        Skill names (typically from analyze_topics gaps or strong list).
    max_per_topic : int
        Maximum resources per topic (default 3).

    Returns
    -------
    dict mapping topic -> list of resource dicts (title, url, type)
    """
    finder = ResourceFinder()
    result: Dict[str, List[Dict[str, str]]] = {}
    for topic in topics:
        if topic:
            result[topic] = finder.get_resources(topic, max_results=max_per_topic)
    return result


def _prep_guide_generate_questions(
    self,
    jd_text: str,
    company_name: str = "the company",
    listing_type: str = "job",
    round_types: Optional[List[str]] = None,
    max_per_category: int = 3,
) -> List[Dict[str, str]]:
    """
    Generate JD-specific mock interview questions.

    Parameters
    ----------
    jd_text : str
        Full job description text.
    company_name : str
        Company name used to personalise questions.
    listing_type : str
        "internship" or "job".
    round_types : list of str, optional
        Round type keys from predict_rounds output.
    max_per_category : int
        Max questions per category.

    Returns
    -------
    list of dicts with keys: question, category, (skill)
    """
    generator = MockQuestionGenerator()
    return generator.generate(
        jd_text=jd_text,
        company_name=company_name,
        listing_type=listing_type,
        round_types=round_types,
        max_per_category=max_per_category,
    )


# Monkey-patch the methods onto PrepGuideAgent so the class interface
# stays in one logical unit while the issue-18 code is additive.
PrepGuideAgent.find_resources = _prep_guide_find_resources
PrepGuideAgent.generate_questions = _prep_guide_generate_questions
