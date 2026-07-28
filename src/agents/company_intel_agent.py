"""
CompanyIntelAgent - Automated Company Research for Interview Prep.

Collects structured intelligence about a company from multiple sources:
  - Web search (Tavily) for recent news, tech stack signals, funding stage
  - Glassdoor / AmbitionBox keyword search for interview experience patterns
  - Website metadata inference (when URL is provided)

Saves results to the `company_intel` field of the `prep_guides` table.

This is Issue #19 and is the final content piece before the prep guide is
assembled into a complete document (Issue 20 / 24).
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stage inference heuristics
# ---------------------------------------------------------------------------

_STAGE_SIGNALS: List[tuple] = [
    # (regex pattern on combined text, stage label)
    (r"\bseries\s*[de]\b|\bgrowth[\s-]stage\b|\bpre[\s-]?ipo\b", "late_stage"),
    (r"\bseries\s*[bc]\b|\bgrowth\b", "growth"),
    (r"\bseries\s*[ab]\b", "early_stage"),
    (r"\bseed\b|\bpre[\s-]?seed\b|\bangel\b", "seed"),
    (r"\bbootstrap", "bootstrapped"),
    (r"\bpublic\b|\bnyse\b|\bnasdaq\b|\blisted\b", "public"),
    (r"\bfortune\s*500\b|\benterprise\b|\bconglomerate\b", "enterprise"),
    (r"\bstartup\b|\bearly[\s-]stage\b", "startup"),
]

# ---------------------------------------------------------------------------
# Tech stack keyword signals (pattern → technology label)
# ---------------------------------------------------------------------------

_TECH_SIGNALS: List[tuple] = [
    (r"\bpython\b", "Python"),
    (r"\brust\b", "Rust"),
    (r"\bgolang\b|\bgo\b(?!\s*to)", "Go"),
    (r"\bjava\b(?!script)", "Java"),
    (r"\btypescript\b", "TypeScript"),
    (r"\bjavascript\b|\bnode\.?js\b", "JavaScript/Node.js"),
    (r"\breact\b", "React"),
    (r"\bvue\b", "Vue.js"),
    (r"\bangular\b", "Angular"),
    (r"\bkubernetes\b|\bk8s\b", "Kubernetes"),
    (r"\bdocker\b", "Docker"),
    (r"\baws\b|amazon\s+web\s+services", "AWS"),
    (r"\bgcp\b|google\s+cloud", "GCP"),
    (r"\bazure\b", "Azure"),
    (r"\bpostgres\b|\bpostgresql\b", "PostgreSQL"),
    (r"\bmysql\b", "MySQL"),
    (r"\bmongodb\b", "MongoDB"),
    (r"\bredis\b", "Redis"),
    (r"\blangchain\b", "LangChain"),
    (r"\blanggraph\b", "LangGraph"),
    (r"\bopenai\b", "OpenAI API"),
    (r"\banthropics?\b", "Anthropic API"),
    (r"\brag\b|retrieval.augmented", "RAG"),
    (r"\bfastapi\b", "FastAPI"),
    (r"\bdjango\b", "Django"),
    (r"\bflask\b", "Flask"),
    (r"\bspark\b", "Apache Spark"),
    (r"\bkafka\b", "Apache Kafka"),
    (r"\belasticsearch\b", "Elasticsearch"),
    (r"\bgraphql\b", "GraphQL"),
]

# ---------------------------------------------------------------------------
# Interview pattern signals (words that indicate a type of interview round)
# ---------------------------------------------------------------------------

_INTERVIEW_PATTERN_SIGNALS: List[tuple] = [
    (r"coding\s+test|online\s+assessment|hackerrank|codility", "Online coding assessment"),
    (r"technical\s+interview|tech\s+round|coding\s+interview", "Technical interview round"),
    (r"system\s+design", "System design round"),
    (r"founder\s+(interview|round)|ceo\s+round", "Founder / CEO round"),
    (r"hr\s+(round|interview)|behavioral\s+interview", "HR / Behavioral round"),
    (r"take.?home|assignment", "Take-home assignment"),
    (r"pair\s+programming|live\s+coding", "Pair programming / live coding"),
    (r"case\s+study|portfolio\s+review", "Case study / portfolio review"),
    (r"(\d+)\s+round", "Multiple rounds ({n} rounds reported)"),
    (r"two\s+round|three\s+round|four\s+round|five\s+round", "Multiple rounds mentioned"),
]

# ---------------------------------------------------------------------------
# Fallback interview patterns by company stage (when no reviews found)
# ---------------------------------------------------------------------------

_STAGE_DEFAULT_PATTERNS: Dict[str, List[str]] = {
    "seed": ["1-2 rounds (typical for early-stage)", "Founder interview likely", "Culture-fit focus"],
    "startup": ["2-3 rounds", "Technical screen + founder/culture round"],
    "early_stage": ["2-3 rounds", "Online assessment + technical interview"],
    "growth": ["3-4 rounds", "Online assessment + technical + managerial + HR"],
    "late_stage": ["4-5 rounds", "Multiple technical rounds + system design + HR"],
    "enterprise": ["4-6 rounds", "Multiple rounds including HR, technical, and panel interview"],
    "public": ["4-5 rounds", "Structured interview process with rubric-based evaluation"],
    "bootstrapped": ["1-2 rounds", "Informal process, founder interview common"],
    "unknown": ["2-3 rounds (estimated)", "Process varies — check company career page"],
}


class CompanyIntelAgent:
    """
    Researches a company and returns structured intelligence for interview prep.

    Usage::

        agent = CompanyIntelAgent()
        intel = agent.research(
            company_name="Anthropic",
            website="https://anthropic.com",
        )
        # Returns dict with: stage, tech_stack, recent_news,
        #                    interview_patterns, key_people, summary

    The result can be saved to the prep_guides.company_intel column::

        guide.company_intel = json.dumps(intel)
        db.commit()
    """

    def __init__(self, tavily_api_key: Optional[str] = None) -> None:
        self._api_key = (
            tavily_api_key
            or os.environ.get("TAVILY_API_KEY")
            or self._load_from_settings()
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def research(
        self,
        company_name: str,
        website: Optional[str] = None,
        db_session=None,
        application_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Research a company and return structured intel.

        Parameters
        ----------
        company_name : str
            The company name to research.
        website : str, optional
            The company's website URL (improves accuracy when provided).
        db_session : SQLAlchemy Session, optional
            If provided (along with application_id), saves result to
            prep_guides.company_intel.
        application_id : int, optional
            Used with db_session to locate the PrepGuide row.

        Returns
        -------
        dict with keys:
            - stage (str)
            - tech_stack (list of str)
            - recent_news (list of dicts: title, url, date)
            - interview_patterns (list of str)
            - interview_patterns_note (str)
            - key_people (list of str)
            - summary (str)
            - sources_checked (list of str)
            - researched_at (ISO timestamp str)
        """
        logger.info("Researching company: %s", company_name)

        raw_texts: List[str] = []
        sources_checked: List[str] = []
        recent_news: List[Dict[str, str]] = []
        key_people: List[str] = []

        # 1. Tavily web search — general company info
        general_results = self._tavily_search(
            f"{company_name} company overview tech stack funding stage",
            max_results=5,
        )
        if general_results:
            sources_checked.append("web_search:general")
            for r in general_results:
                raw_texts.append(r.get("content", "") + " " + r.get("title", ""))

        # 2. Recent news (last ~3 months)
        news_results = self._tavily_search(
            f"{company_name} news 2024 2025",
            max_results=5,
        )
        if news_results:
            sources_checked.append("web_search:news")
            for r in news_results:
                recent_news.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "date": r.get("published_date", ""),
                })
                raw_texts.append(r.get("content", "") + " " + r.get("title", ""))

        # 3. Interview experience search (Glassdoor / AmbitionBox)
        interview_results = self._tavily_search(
            f"{company_name} interview experience glassdoor ambitionbox process rounds",
            max_results=5,
        )
        interview_raw: List[str] = []
        if interview_results:
            sources_checked.append("web_search:interview_reviews")
            for r in interview_results:
                content = r.get("content", "") + " " + r.get("title", "")
                interview_raw.append(content)
                raw_texts.append(content)

        # 4. Key people search
        people_results = self._tavily_search(
            f"{company_name} CEO founder leadership team",
            max_results=3,
        )
        if people_results:
            sources_checked.append("web_search:people")
            for r in people_results:
                raw_texts.append(r.get("content", "") + " " + r.get("title", ""))
                people = self._extract_key_people(r.get("content", "") + " " + r.get("title", ""))
                key_people.extend(people)

        # 5. Website hint text
        if website:
            raw_texts.append(f"website: {website} company {company_name}")
            sources_checked.append(f"website_hint:{website}")

        # 6. Derive structured intel from collected text
        combined = " ".join(raw_texts)
        stage = self._infer_stage(combined, company_name)
        tech_stack = self._extract_tech_stack(combined)
        interview_patterns, patterns_note = self._extract_interview_patterns(
            interview_raw, company_name, stage
        )

        # Deduplicate
        key_people = list(dict.fromkeys(key_people))[:5]
        tech_stack = list(dict.fromkeys(tech_stack))
        recent_news = recent_news[:5]

        result: Dict[str, Any] = {
            "company_name": company_name,
            "website": website or "",
            "stage": stage,
            "tech_stack": tech_stack,
            "recent_news": recent_news,
            "interview_patterns": interview_patterns,
            "interview_patterns_note": patterns_note,
            "key_people": key_people,
            "summary": self._build_summary(company_name, stage, tech_stack, interview_patterns),
            "sources_checked": sources_checked,
            "researched_at": datetime.now(timezone.utc).isoformat(),
        }

        # 7. Persist to DB if session provided
        if db_session and application_id:
            self._save_to_db(db_session, application_id, result)

        return result

    def save_to_prep_guide(
        self,
        db_session,
        application_id: int,
        intel: Dict[str, Any],
    ) -> bool:
        """
        Persist intel dict to prep_guides.company_intel for the given application.

        Returns True on success, False on failure.
        """
        return self._save_to_db(db_session, application_id, intel)

    # ------------------------------------------------------------------
    # Private helpers — search
    # ------------------------------------------------------------------

    def _tavily_search(
        self, query: str, max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """Run a Tavily web search. Returns [] on any failure."""
        if not self._api_key or self._api_key.strip() in ("", "your_tavily_api_key_here"):
            logger.debug("No Tavily API key — skipping live search for: %s", query)
            return []
        try:
            from tavily import TavilyClient  # type: ignore
            client = TavilyClient(api_key=self._api_key)
            response = client.search(
                query=query,
                max_results=max_results,
                search_depth="basic",
            )
            return response.get("results", [])
        except Exception as exc:
            logger.warning("Tavily search failed ('%s'): %s", query, exc)
            return []

    # ------------------------------------------------------------------
    # Private helpers — extraction
    # ------------------------------------------------------------------

    def _infer_stage(self, text: str, company_name: str) -> str:
        """Infer company stage from collected text."""
        text_lower = text.lower()
        for pattern, label in _STAGE_SIGNALS:
            if re.search(pattern, text_lower):
                return label
        return "unknown"

    def _extract_tech_stack(self, text: str) -> List[str]:
        """Extract technology mentions from combined text."""
        text_lower = text.lower()
        found: List[str] = []
        for pattern, label in _TECH_SIGNALS:
            if re.search(pattern, text_lower):
                found.append(label)
        return found

    def _extract_interview_patterns(
        self, review_texts: List[str], company_name: str, stage: str
    ) -> tuple:
        """
        Extract interview round patterns from review text.
        Returns (patterns_list, note_string).
        """
        if not review_texts:
            default = _STAGE_DEFAULT_PATTERNS.get(stage, _STAGE_DEFAULT_PATTERNS["unknown"])
            note = (
                f"No interview reviews found for {company_name}. "
                "Showing typical patterns for this company stage."
            )
            return default, note

        combined = " ".join(review_texts).lower()
        patterns: List[str] = []

        for pattern, label in _INTERVIEW_PATTERN_SIGNALS:
            match = re.search(pattern, combined)
            if match:
                if "{n}" in label:
                    n = match.group(1) if match.lastindex else "multiple"
                    patterns.append(label.format(n=n))
                else:
                    patterns.append(label)

        if not patterns:
            # Text was found but no recognisable patterns → graceful fallback
            default = _STAGE_DEFAULT_PATTERNS.get(stage, _STAGE_DEFAULT_PATTERNS["unknown"])
            note = (
                f"Interview review content found for {company_name} but specific patterns "
                "could not be extracted. Showing stage-based estimates."
            )
            return default, note

        note = (
            f"Interview patterns inferred from Glassdoor/AmbitionBox reviews for {company_name}."
        )
        return patterns, note

    def _extract_key_people(self, text: str) -> List[str]:
        """Extract likely key people (CEO, founders) from text."""
        # Match "Name, CEO" or "CEO Name" style mentions
        patterns = [
            r"([A-Z][a-z]+ [A-Z][a-z]+),?\s*(?:CEO|Co-Founder|Founder|CTO|COO|President)",
            r"(?:CEO|Co-Founder|Founder|CTO|COO|President)[,:\s]+([A-Z][a-z]+ [A-Z][a-z]+)",
        ]
        found: List[str] = []
        for pat in patterns:
            for match in re.finditer(pat, text):
                name = match.group(1).strip()
                if name and len(name.split()) >= 2:
                    found.append(name)
        return found

    def _build_summary(
        self,
        company_name: str,
        stage: str,
        tech_stack: List[str],
        interview_patterns: List[str],
    ) -> str:
        """Build a human-readable one-paragraph summary."""
        stage_label = stage.replace("_", " ").title()
        tech = ", ".join(tech_stack[:5]) if tech_stack else "not detected"
        patterns = "; ".join(interview_patterns[:3]) if interview_patterns else "not detected"
        return (
            f"{company_name} appears to be a {stage_label} company. "
            f"Detected tech stack includes: {tech}. "
            f"Interview process signals: {patterns}."
        )

    def _save_to_db(
        self, db_session, application_id: int, intel: Dict[str, Any]
    ) -> bool:
        """Save intel JSON to prep_guides.company_intel."""
        try:
            from src.models.prep_guide import PrepGuide

            guide = (
                db_session.query(PrepGuide)
                .filter(PrepGuide.application_id == application_id)
                .first()
            )
            if guide:
                guide.company_intel = json.dumps(intel)
            else:
                # Create a minimal guide row if none exists
                guide = PrepGuide(
                    application_id=application_id,
                    company_name=intel.get("company_name", ""),
                    role_title="",
                    company_intel=json.dumps(intel),
                )
                db_session.add(guide)
            db_session.commit()
            logger.info("Saved company intel for application_id=%s", application_id)
            return True
        except Exception as exc:
            db_session.rollback()
            logger.error("Failed to save company intel: %s", exc)
            return False

    @staticmethod
    def _load_from_settings() -> Optional[str]:
        try:
            from src.config.settings import get_settings
            return get_settings().TAVILY_API_KEY
        except Exception:
            return None
