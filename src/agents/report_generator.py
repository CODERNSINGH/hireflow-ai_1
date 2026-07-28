"""
ReportGenerator - Weekly Cycle Report Compiler for HireFlow.

Collects all applications, resumes, prep guides, and skill data from the
current weekly cycle and compiles them into:
  1. A structured JSON report (saved to weekly_reports table)
  2. An HTML report file (saved to data/reports/{user_id}/)

Cross-application insights produced:
  - Top 5 skills appearing across all JDs this week
  - Strongest and weakest match categories for the user
  - Weekly study plan: top 3 skills to learn, ranked by JD frequency
  - Failed / needs_action applications with manual apply instructions

This is Issue #20 — the final aggregation layer before email delivery (Issue 21)
and dashboard display (Issue 24).
"""

import argparse
import json
import logging
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DEFAULT_REPORTS_DIR = os.path.join("data", "reports")

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>HireFlow Weekly Report — {week_label}</title>
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f4f6fb; color: #222; margin: 0; padding: 0; }}
    .header {{ background: linear-gradient(135deg,#1e3a5f,#2980b9); color:#fff; padding: 32px 40px; }}
    .header h1 {{ margin:0; font-size:1.8rem; }}
    .header p {{ margin:4px 0 0; opacity:.85; }}
    .container {{ max-width: 900px; margin: 32px auto; padding: 0 20px; }}
    .card {{ background:#fff; border-radius:8px; box-shadow:0 1px 4px rgba(0,0,0,.12); margin-bottom:24px; padding:24px; }}
    h2 {{ margin-top:0; font-size:1.15rem; color:#1e3a5f; border-bottom:2px solid #e8edf5; padding-bottom:8px; }}
    .stat-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:16px; }}
    .stat {{ text-align:center; padding:16px; background:#f0f4fa; border-radius:6px; }}
    .stat .num {{ font-size:2rem; font-weight:700; color:#2980b9; }}
    .stat .label {{ font-size:.8rem; color:#666; margin-top:4px; }}
    table {{ width:100%; border-collapse:collapse; font-size:.9rem; }}
    th {{ text-align:left; padding:8px 10px; background:#f0f4fa; color:#444; }}
    td {{ padding:8px 10px; border-bottom:1px solid #f0f4fa; vertical-align:top; }}
    .badge {{ display:inline-block; padding:2px 8px; border-radius:12px; font-size:.75rem; font-weight:600; }}
    .badge-applied {{ background:#d4edda; color:#155724; }}
    .badge-failed {{ background:#f8d7da; color:#721c24; }}
    .badge-needs-action {{ background:#fff3cd; color:#856404; }}
    .badge-pending {{ background:#e2e3e5; color:#383d41; }}
    .skill-chip {{ display:inline-block; background:#e8f0fe; color:#1a73e8; border-radius:12px; padding:2px 10px; margin:2px; font-size:.8rem; }}
    .action-box {{ background:#fff3cd; border-left:4px solid #ffc107; padding:12px 16px; border-radius:0 6px 6px 0; margin:8px 0; }}
    .study-item {{ display:flex; align-items:center; gap:12px; margin:8px 0; }}
    .rank {{ font-size:1.4rem; font-weight:700; color:#2980b9; width:30px; }}
    ul {{ margin:6px 0; padding-left:20px; }}
    footer {{ text-align:center; color:#999; font-size:.8rem; padding:24px 0; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>&#128202; HireFlow Weekly Report</h1>
    <p>Week of {week_label} &nbsp;|&nbsp; Generated {generated_at}</p>
  </div>
  <div class="container">

    <!-- Summary stats -->
    <div class="card">
      <h2>&#128200; Week at a Glance</h2>
      <div class="stat-grid">
        <div class="stat"><div class="num">{total}</div><div class="label">Applications</div></div>
        <div class="stat"><div class="num">{applied}</div><div class="label">Applied</div></div>
        <div class="stat"><div class="num">{failed}</div><div class="label">Failed</div></div>
        <div class="stat"><div class="num">{needs_action}</div><div class="label">Needs Action</div></div>
        <div class="stat"><div class="num">{avg_score}%</div><div class="label">Avg Match</div></div>
      </div>
    </div>

    <!-- Cross-app insights -->
    <div class="card">
      <h2>&#128161; Cross-Application Insights</h2>
      <p><strong>Top skills this week (appeared across most JDs):</strong></p>
      <div>{top_skills_html}</div>
      <p style="margin-top:16px"><strong>Strongest match category:</strong> {strongest_category}</p>
      <p><strong>Weakest match category:</strong> {weakest_category}</p>
    </div>

    <!-- Weekly study plan -->
    <div class="card">
      <h2>&#128218; Weekly Study Plan — Top 3 to Learn</h2>
      {study_plan_html}
    </div>

    <!-- Applications table -->
    <div class="card">
      <h2>&#128196; All Applications This Week</h2>
      <table>
        <thead>
          <tr>
            <th>#</th><th>Company</th><th>Role</th><th>Status</th>
            <th>Match Score</th><th>Key Gaps</th><th>Resume</th>
          </tr>
        </thead>
        <tbody>
          {applications_rows}
        </tbody>
      </table>
    </div>

    <!-- Needs action -->
    {needs_action_section}

    <footer>Generated by HireFlow AI &mdash; {generated_at}</footer>
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class ReportGenerator:
    """
    Compiles the weekly cycle report for a given user.

    Usage (programmatic)::

        gen = ReportGenerator()
        report = gen.generate(user_id=1, db_session=db)
        # report contains: applications, insights, study_plan, html_path, ...

    Usage (CLI)::

        python -m src.agents.report_generator --user-id 1
    """

    def __init__(self, reports_dir: str = _DEFAULT_REPORTS_DIR) -> None:
        self.reports_dir = reports_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        user_id: int,
        db_session,
        week_start: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Generate the full weekly report for the given user.

        Parameters
        ----------
        user_id : int
        db_session : SQLAlchemy Session
        week_start : datetime, optional
            Monday of the target week (UTC). Defaults to the current week's Monday.

        Returns
        -------
        dict with keys: user_id, week_start, applications, insights,
                        study_plan, stats, html_path, saved_to_db
        """
        if week_start is None:
            week_start = self._current_week_monday()

        week_end = week_start + timedelta(days=7)

        # 1. Fetch applications for this week
        apps_data = self._fetch_applications(db_session, user_id, week_start, week_end)

        # 2. Compute stats
        stats = self._compute_stats(apps_data)

        # 3. Cross-application insights
        insights = self._compute_insights(apps_data)

        # 4. Weekly study plan
        study_plan = self._build_study_plan(apps_data)

        report: Dict[str, Any] = {
            "user_id": user_id,
            "week_start": week_start.isoformat(),
            "week_label": week_start.strftime("%B %d, %Y"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stats": stats,
            "applications": apps_data,
            "insights": insights,
            "study_plan": study_plan,
        }

        # 5. Save HTML file
        html_path = self._save_html(user_id, week_start, report)
        report["html_path"] = html_path

        # 6. Save JSON sidecar
        json_path = self._save_json(user_id, report)
        report["json_path"] = json_path

        # 7. Save to DB
        saved = self._save_to_db(db_session, user_id, week_start, report)
        report["saved_to_db"] = saved

        return report

    def generate_from_data(
        self,
        user_id: int,
        apps_data: List[Dict[str, Any]],
        week_start: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Generate report from pre-fetched application data (no DB required).
        Useful for testing and offline generation.
        """
        if week_start is None:
            week_start = self._current_week_monday()

        stats = self._compute_stats(apps_data)
        insights = self._compute_insights(apps_data)
        study_plan = self._build_study_plan(apps_data)

        return {
            "user_id": user_id,
            "week_start": week_start.isoformat(),
            "week_label": week_start.strftime("%B %d, %Y"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stats": stats,
            "applications": apps_data,
            "insights": insights,
            "study_plan": study_plan,
            "html_path": None,
            "json_path": None,
            "saved_to_db": False,
        }

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_applications(
        self,
        db_session,
        user_id: int,
        week_start: datetime,
        week_end: datetime,
    ) -> List[Dict[str, Any]]:
        """Fetch and enrich applications for the given user and week."""
        from src.models.application import Application
        from src.models.job import Job
        from src.models.prep_guide import PrepGuide

        try:
            rows = (
                db_session.query(Application, Job)
                .join(Job, Application.job_id == Job.id)
                .filter(Application.user_id == user_id)
                .filter(Application.cycle_start_date >= week_start.date())
                .filter(Application.cycle_start_date < week_end.date())
                .all()
            )
        except Exception as exc:
            logger.warning("DB query failed, returning empty: %s", exc)
            return []

        apps: List[Dict[str, Any]] = []
        for app, job in rows:
            # Parse skill gaps
            gaps = self._parse_csv_field(getattr(app, "skill_gaps", "") or "")
            matches = self._parse_csv_field(getattr(app, "skill_matches", "") or "")
            jd_skills = self._parse_csv_field(getattr(job, "skills_required", "") or "")

            # Fetch prep guide (optional)
            guide_link = ""
            try:
                guide = (
                    db_session.query(PrepGuide)
                    .filter(PrepGuide.application_id == app.id)
                    .first()
                )
                if guide:
                    guide_link = f"data/reports/{user_id}/prep_{app.id}.html"
            except Exception:
                pass

            apps.append({
                "application_id": app.id,
                "company": job.company_name,
                "role": job.role_title,
                "status": app.status,
                "match_score": round((app.match_score or 0) * 100, 1) if app.match_score else 0,
                "skill_gaps": gaps,
                "skill_matches": matches,
                "jd_skills": jd_skills,
                "resume_path": app.resume_path or "",
                "failure_reason": app.failure_reason or "",
                "application_url": job.application_url,
                "prep_guide_link": guide_link,
                "listing_type": job.listing_type,
                "applied_at": app.applied_at.isoformat() if app.applied_at else None,
            })

        return apps

    # ------------------------------------------------------------------
    # Stat computation
    # ------------------------------------------------------------------

    def _compute_stats(self, apps: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = len(apps)
        applied = sum(1 for a in apps if a["status"] == "applied")
        failed = sum(1 for a in apps if a["status"] == "failed")
        needs_action = sum(1 for a in apps if a["status"] == "needs_action")
        pending = sum(1 for a in apps if a["status"] in ("pending", "planned", "applying"))

        scores = [a["match_score"] for a in apps if a["match_score"]]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0

        return {
            "total": total,
            "applied": applied,
            "failed": failed,
            "needs_action": needs_action,
            "pending": pending,
            "avg_match_score": avg_score,
        }

    # ------------------------------------------------------------------
    # Cross-application insights
    # ------------------------------------------------------------------

    def _compute_insights(self, apps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Derive cross-application signals from all applications this week."""
        # Skill frequency across all JDs
        all_jd_skills: List[str] = []
        for app in apps:
            all_jd_skills.extend(app.get("jd_skills", []))

        skill_counter = Counter(s.strip().lower() for s in all_jd_skills if s.strip())
        top_5_skills = [skill for skill, _ in skill_counter.most_common(5)]

        # Role category analysis — infer from role titles
        role_titles = [a["role"].lower() for a in apps]
        category_scores: Dict[str, List[float]] = {}
        for app in apps:
            cat = self._infer_role_category(app["role"])
            if cat not in category_scores:
                category_scores[cat] = []
            category_scores[cat].append(app["match_score"])

        strongest_category = "N/A"
        weakest_category = "N/A"
        if category_scores:
            avg_by_cat = {
                cat: sum(scores) / len(scores)
                for cat, scores in category_scores.items()
            }
            strongest_category = max(avg_by_cat, key=avg_by_cat.get)
            weakest_category = min(avg_by_cat, key=avg_by_cat.get)

        # Gap frequency
        all_gaps: List[str] = []
        for app in apps:
            all_gaps.extend(app.get("skill_gaps", []))
        gap_counter = Counter(g.strip().lower() for g in all_gaps if g.strip())
        top_gaps = [skill for skill, _ in gap_counter.most_common(5)]

        return {
            "top_skills": top_5_skills,
            "top_skill_counts": dict(skill_counter.most_common(5)),
            "top_gaps": top_gaps,
            "strongest_category": strongest_category,
            "weakest_category": weakest_category,
            "role_categories": list(category_scores.keys()),
        }

    def _build_study_plan(self, apps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Build weekly study plan: top 3 gap skills ranked by frequency across JDs.
        """
        all_gaps: List[str] = []
        for app in apps:
            all_gaps.extend(app.get("skill_gaps", []))

        gap_counter = Counter(g.strip() for g in all_gaps if g.strip())
        plan: List[Dict[str, Any]] = []

        for rank, (skill, count) in enumerate(gap_counter.most_common(3), start=1):
            plan.append({
                "rank": rank,
                "skill": skill,
                "frequency": count,
                "reason": f"Appeared as a gap in {count} out of {len(apps)} JD(s) this week.",
            })

        return plan

    # ------------------------------------------------------------------
    # HTML generation
    # ------------------------------------------------------------------

    def _render_html(self, report: Dict[str, Any]) -> str:
        stats = report["stats"]
        insights = report["insights"]
        study_plan = report["study_plan"]
        apps = report["applications"]

        # Top skills chips
        top_skills_html = " ".join(
            f'<span class="skill-chip">{s}</span>'
            for s in insights.get("top_skills", [])
        ) or "<em>Not enough data</em>"

        # Study plan
        study_items = []
        for item in study_plan:
            study_items.append(
                f'<div class="study-item">'
                f'<span class="rank">#{item["rank"]}</span>'
                f'<div><strong>{item["skill"]}</strong>'
                f'<br><small style="color:#666">{item["reason"]}</small></div>'
                f'</div>'
            )
        study_plan_html = "\n".join(study_items) or "<p>No skill gaps identified — great job!</p>"

        # Application rows
        rows = []
        for i, app in enumerate(apps, start=1):
            status = app["status"]
            badge_class = {
                "applied": "badge-applied",
                "failed": "badge-failed",
                "needs_action": "badge-needs-action",
            }.get(status, "badge-pending")

            gaps_html = ", ".join(app.get("skill_gaps", [])[:3]) or "—"
            resume = (
                f'<a href="{app["resume_path"]}" target="_blank">Resume</a>'
                if app.get("resume_path") else "—"
            )
            rows.append(
                f'<tr>'
                f'<td>{i}</td>'
                f'<td><strong>{app["company"]}</strong></td>'
                f'<td>{app["role"]}</td>'
                f'<td><span class="badge {badge_class}">{status.replace("_", " ").title()}</span></td>'
                f'<td>{app["match_score"]}%</td>'
                f'<td style="font-size:.8rem;color:#c0392b">{gaps_html}</td>'
                f'<td>{resume}</td>'
                f'</tr>'
            )
        applications_rows = "\n".join(rows) or '<tr><td colspan="7" style="text-align:center;color:#999">No applications this week</td></tr>'

        # Needs action section
        action_apps = [a for a in apps if a["status"] in ("needs_action", "failed")]
        needs_action_section = ""
        if action_apps:
            action_html = '<div class="card"><h2>&#9888;&#65039; Action Required</h2>'
            for app in action_apps:
                url = app.get("application_url", "#")
                reason = app.get("failure_reason") or "Manual review required"
                action_html += (
                    f'<div class="action-box">'
                    f'<strong>{app["company"]} — {app["role"]}</strong><br>'
                    f'<small>{reason}</small><br>'
                    f'<a href="{url}" target="_blank">Apply manually &rarr;</a>'
                    f'</div>'
                )
            action_html += "</div>"
            needs_action_section = action_html

        return _HTML_TEMPLATE.format(
            week_label=report["week_label"],
            generated_at=report["generated_at"][:19].replace("T", " "),
            total=stats["total"],
            applied=stats["applied"],
            failed=stats["failed"],
            needs_action=stats["needs_action"],
            avg_score=stats["avg_match_score"],
            top_skills_html=top_skills_html,
            strongest_category=insights.get("strongest_category", "N/A"),
            weakest_category=insights.get("weakest_category", "N/A"),
            study_plan_html=study_plan_html,
            applications_rows=applications_rows,
            needs_action_section=needs_action_section,
        )

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _save_html(self, user_id: int, week_start: datetime, report: Dict[str, Any]) -> str:
        """Render and save HTML report. Returns the file path."""
        user_dir = os.path.join(self.reports_dir, str(user_id))
        os.makedirs(user_dir, exist_ok=True)

        week_str = week_start.strftime("%Y_%V")
        html_path = os.path.join(user_dir, f"week_{week_str}.html")

        try:
            html_content = self._render_html(report)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info("HTML report saved: %s", html_path)
        except Exception as exc:
            logger.error("Failed to save HTML report: %s", exc)

        return html_path

    def _save_json(self, user_id: int, report: Dict[str, Any]) -> str:
        """Save JSON sidecar (latest.json) for dashboard consumption."""
        user_dir = os.path.join(self.reports_dir, str(user_id))
        os.makedirs(user_dir, exist_ok=True)
        json_path = os.path.join(user_dir, "latest.json")

        try:
            # Make a serialisable copy (exclude html/json paths to avoid circular)
            serialisable = {k: v for k, v in report.items() if k not in ("html_path", "json_path")}
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(serialisable, f, indent=2, default=str)
            logger.info("JSON report saved: %s", json_path)
        except Exception as exc:
            logger.error("Failed to save JSON report: %s", exc)

        return json_path

    def _save_to_db(
        self,
        db_session,
        user_id: int,
        week_start: datetime,
        report: Dict[str, Any],
    ) -> bool:
        """Persist report to weekly_reports table."""
        try:
            from src.models.report import WeeklyReport

            existing = (
                db_session.query(WeeklyReport)
                .filter(WeeklyReport.user_id == user_id)
                .filter(WeeklyReport.week_start == week_start)
                .first()
            )

            stats = report["stats"]
            summary_json = json.dumps({
                "insights": report.get("insights", {}),
                "study_plan": report.get("study_plan", []),
                "html_path": report.get("html_path", ""),
            })

            if existing:
                existing.total_applications = stats["total"]
                existing.successful_applications = stats["applied"]
                existing.summary = summary_json
            else:
                record = WeeklyReport(
                    user_id=user_id,
                    week_start=week_start,
                    total_applications=stats["total"],
                    successful_applications=stats["applied"],
                    summary=summary_json,
                )
                db_session.add(record)

            db_session.commit()
            logger.info("Report saved to DB for user_id=%s", user_id)
            return True
        except Exception as exc:
            try:
                db_session.rollback()
            except Exception:
                pass
            logger.error("Failed to save report to DB: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _current_week_monday() -> datetime:
        """Return the most recent Monday at midnight UTC."""
        today = datetime.now(timezone.utc).date()
        monday = today - timedelta(days=today.weekday())
        return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)

    @staticmethod
    def _parse_csv_field(value: str) -> List[str]:
        """Parse a comma-separated skills string into a list."""
        if not value:
            return []
        return [s.strip() for s in str(value).split(",") if s.strip()]

    @staticmethod
    def _infer_role_category(role_title: str) -> str:
        """Roughly categorise a role title for insight analysis."""
        t = role_title.lower()
        if any(x in t for x in ("ai", "ml", "machine learning", "data scientist", "nlp", "llm")):
            return "AI/ML"
        if any(x in t for x in ("backend", "api", "server", "platform")):
            return "Backend"
        if any(x in t for x in ("frontend", "react", "ui", "web")):
            return "Frontend"
        if any(x in t for x in ("data", "analyst", "analytics", "bi")):
            return "Data"
        if any(x in t for x in ("devops", "infra", "cloud", "sre", "platform")):
            return "DevOps"
        if any(x in t for x in ("full stack", "fullstack", "software engineer", "developer")):
            return "Full Stack"
        return "Other"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _run_cli() -> None:
    parser = argparse.ArgumentParser(description="Generate HireFlow weekly report")
    parser.add_argument("--user-id", type=int, required=True, help="User ID to generate report for")
    parser.add_argument(
        "--week-start",
        type=str,
        default=None,
        help="ISO date of week Monday (e.g. 2024-07-22). Defaults to current week.",
    )
    args = parser.parse_args()

    week_start: Optional[datetime] = None
    if args.week_start:
        from datetime import date
        d = date.fromisoformat(args.week_start)
        week_start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

    from src.config.database import SessionLocal
    db = SessionLocal()
    try:
        gen = ReportGenerator()
        report = gen.generate(user_id=args.user_id, db_session=db, week_start=week_start)
        print(f"Report generated!")
        print(f"  HTML: {report.get('html_path')}")
        print(f"  JSON: {report.get('json_path')}")
        print(f"  Applications: {report['stats']['total']}")
        print(f"  Applied: {report['stats']['applied']}")
        print(f"  Top skills: {report['insights'].get('top_skills', [])}")
        print(f"  Study plan: {[s['skill'] for s in report['study_plan']]}")
    finally:
        db.close()


if __name__ == "__main__":
    _run_cli()
