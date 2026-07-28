"""
HireFlow AI — LaTeX PDF Generation and Resume Storage (Issue 13).

Takes a resume content dict from ResumeTailoringEngine.tailor(), renders it
into a LaTeX document via Jinja2, compiles it to PDF via xelatex, and saves
it with version-incrementing filenames. Updates the Application DB row with
the resulting path and version.

No LLM calls anywhere in this module — this is pure templating and PDF
compilation, deterministic and offline.

Usage:
    python -m src.pipelines.pdf_generator --user-id 1 --job-id 5
"""

from __future__ import annotations

import argparse
import glob
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from src.config.database import SessionLocal
from src.models.application import Application
from src.models.job import Job
from src.models.user import User
from src.pipelines.resume_generator import ResumeTailoringEngine

logger = logging.getLogger(__name__)

# Base directory for generated resumes
_RESUMES_DIR = Path("data") / "resumes"

# Sentinel used to protect backslashes during LaTeX escaping.
# The null character will never appear in normal UTF-8 text content.
_LATEX_BS_SENTINEL = "\x00"


# ====================================================================== #
# PDFGenerator
# ====================================================================== #


class PDFGenerator:
    """Generate tailored PDF resumes from user profile + job data.

    Uses Jinja2 to render a LaTeX template and xelatex to compile to PDF.
    """

    def __init__(self, db: Optional[Session] = None) -> None:
        """Initialise the PDF generator.

        Checks that xelatex is available on PATH at construction time.

        Raises:
            RuntimeError: If xelatex is not found on PATH.
        """
        self._xelatex_path = shutil.which("xelatex")
        if self._xelatex_path is None:
            raise RuntimeError(
                "xelatex not found. Install MacTeX (brew install --cask "
                "mactex-no-gui) or BasicTeX and ensure it's on your PATH. "
                "On macOS the installer adds /Library/TeX/texbin/ to PATH "
                "via /etc/paths.d/TeX."
            )

        # Set up Jinja2 environment with LaTeX-safe delimiters.
        template_dir = (
            Path(__file__).resolve().parent.parent / "templates" / "resume_latex"
        )
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            block_start_string="\\BLOCK{",
            block_end_string="}",
            variable_start_string="\\VAR{",
            variable_end_string="}",
            comment_start_string="\\#{",
            comment_end_string="}",
            autoescape=False,  # We handle escaping manually via the latex_escape filter
        )

        # Register the LaTeX-escape filter so it can be used in templates.
        self._env.filters["latex_escape"] = self._escape_latex

        self.db = db or SessionLocal()

    # ------------------------------------------------------------------ #
    # LaTeX escaping
    # ------------------------------------------------------------------ #

    @staticmethod
    def _escape_latex(text: str) -> str:
        """Escape LaTeX special characters in user-provided text.

        Covers: \\ & % $ # _ { } ~ ^
        Missing characters pass through unchanged.

        Uses a sentinel approach: backslashes are protected first, then
        all other special characters are escaped, then backslashes are
        restored as \textbackslash{} (the braces are LaTeX syntax, not
        content that would be re-escaped).

        Args:
            text: Raw user-provided text (may contain LaTeX special chars).

        Returns:
            LaTeX-safe string with all special characters escaped.
        """
        if not isinstance(text, str):
            return str(text) if text is not None else ""

        # 1. Protect existing backslashes with a sentinel.
        text = text.replace("\\", _LATEX_BS_SENTINEL)

        # 2. Escape all other LaTeX special characters.
        text = text.replace("&", "\\&")
        text = text.replace("%", "\\%")
        text = text.replace("$", "\\$")
        text = text.replace("#", "\\#")
        text = text.replace("_", "\\_")
        text = text.replace("{", "\\{")
        text = text.replace("}", "\\}")
        text = text.replace("~", "\\textasciitilde{}")
        text = text.replace("^", "\\textasciicircum{}")

        # 3. Restore backslashes as LaTeX-safe commands.
        # The {} in \textbackslash{} are LaTeX syntax (empty group), not
        # content — so they won't be re-escaped by step 2 (they're
        # introduced after step 2 completes).
        text = text.replace(_LATEX_BS_SENTINEL, "\\textbackslash{}")

        return text

    # ------------------------------------------------------------------ #
    # Main generation entry point
    # ------------------------------------------------------------------ #

    def generate(
        self,
        user_id: int | str,
        job_id: int | str,
        resume_content: dict[str, Any],
    ) -> str:
        """Generate a PDF resume from tailored content.

        Args:
            user_id: User ID (int or str — used in directory/filename).
            job_id: Job ID (int or str — used in directory/filename).
            resume_content: Dict matching the output shape of
                ResumeTailoringEngine.tailor(), i.e. keys:
                summary, skills, projects, experience, education.

        Returns:
            Absolute path to the generated PDF file.

        Raises:
            ValueError: If user or job is not found in the database.
            RuntimeError: If xelatex compilation fails.
        """
        # Resolve IDs to integers for DB queries, but keep original for paths.
        try:
            user_id_int = int(user_id)
            job_id_int = int(job_id)
        except (ValueError, TypeError):
            user_id_int = None
            job_id_int = None

        # Fetch User and Job (for name/email/company/role_title).
        user = None
        job = None
        if user_id_int is not None:
            user = self.db.query(User).filter(User.id == user_id_int).first()
        if job_id_int is not None:
            job = self.db.query(Job).filter(Job.id == job_id_int).first()

        if user is None:
            raise ValueError(f"User with id {user_id} not found.")
        if job is None:
            raise ValueError(f"Job with id {job_id} not found.")

        # Determine version number (filesystem vs DB, take the higher).
        version = self._resolve_version(user_id, job_id, user_id_int, job_id_int)

        # Ensure output directory exists.
        user_dir = _RESUMES_DIR / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)

        # Build template context with safe defaults for missing keys.
        safe_content = self._safe_resume_content(resume_content)

        context = {
            "user_name": safe_content.get("user_name") or user.name,
            "user_email": user.email,
            "summary": safe_content.get("summary") or "",
            "skills": safe_content.get("skills") or [],
            "projects": safe_content.get("projects") or [],
            "experience": safe_content.get("experience") or [],
            "education": safe_content.get("education"),
            "job_company": job.company_name,
            "job_role": job.role_title,
        }

        # Render the template.
        template = self._env.get_template("base_template.tex")
        rendered_tex = template.render(context)

        # Compile to PDF via xelatex.
        pdf_path = self._compile_pdf(
            rendered_tex,
            user_dir,
            job_id,
            version,
        )

        # Update Application DB row.
        self._update_application(
            user_id_int=user_id_int,
            job_id_int=job_id_int,
            pdf_path=str(pdf_path),
            version=version,
        )

        return str(pdf_path)

    # ------------------------------------------------------------------ #
    # Version resolution: filesystem vs DB
    # ------------------------------------------------------------------ #

    def _resolve_version(
        self,
        user_id: int | str,
        job_id: int | str,
        user_id_int: int | None,
        job_id_int: int | None,
    ) -> int:
        """Determine the next version number.

        Checks both:
        1. The filesystem for existing files matching
           data/resumes/{user_id}/{job_id}_resume_v*.pdf
        2. The DB's resume_version column for this user_id+job_id combo

        Takes whichever is higher and returns version = max + 1.
        If neither exists, returns 1.

        Args:
            user_id: User ID (used in filesystem path).
            job_id: Job ID (used in filesystem path).
            user_id_int: User ID as int (for DB query), may be None.
            job_id_int: Job ID as int (for DB query), may be None.

        Returns:
            The next version number (int >= 1).
        """
        fs_max = PDFGenerator._filesystem_max_version(user_id, job_id)
        db_max = (
            self._db_max_version_with_session(user_id_int, job_id_int)
            if user_id_int is not None and job_id_int is not None
            else 0
        )
        highest = max(fs_max, db_max)
        return highest + 1

    @staticmethod
    def _filesystem_max_version(user_id: int | str, job_id: int | str) -> int:
        """Find highest existing version number from filesystem glob."""
        pattern = str(_RESUMES_DIR / str(user_id) / f"{job_id}_resume_v*.pdf")
        existing = glob.glob(pattern)

        max_ver = 0
        for path in existing:
            match = re.search(r"_v(\d+)\.pdf$", path)
            if match:
                ver = int(match.group(1))
                if ver > max_ver:
                    max_ver = ver
        return max_ver

    def _db_max_version_with_session(
        self, user_id_int: int | None, job_id_int: int | None
    ) -> int:
        """Query the DB for the highest resume_version for this user+job."""
        app_row = (
            self.db.query(Application.resume_version)
            .filter(
                Application.user_id == user_id_int,
                Application.job_id == job_id_int,
            )
            .order_by(Application.resume_version.desc())
            .first()
        )
        if app_row and app_row[0] is not None:
            return int(app_row[0])
        return 0

    # ------------------------------------------------------------------ #
    # LaTeX compilation
    # ------------------------------------------------------------------ #

    def _compile_pdf(
        self,
        rendered_tex: str,
        output_dir: Path,
        job_id: int | str,
        version: int,
    ) -> Path:
        """Write the .tex file, compile to PDF, clean up aux files.

        Runs xelatex TWICE (standard LaTeX practice — first pass generates
        aux files, second pass resolves cross-references).

        Args:
            rendered_tex: The fully rendered LaTeX source string.
            output_dir: Directory to place the final PDF.
            job_id: Job ID for the filename.
            version: Version number for the filename.

        Returns:
            Path to the final PDF file.

        Raises:
            RuntimeError: If compilation fails (nonzero exit code).
        """
        # Write .tex to a temporary directory so aux files don't pollute.
        with tempfile.TemporaryDirectory(prefix="hireflow_resume_") as tmpdir:
            tex_path = Path(tmpdir) / "resume.tex"
            tex_path.write_text(rendered_tex, encoding="utf-8")

            for pass_num in (1, 2):
                try:
                    result = subprocess.run(
                        [
                            self._xelatex_path,
                            "-interaction=nonstopmode",
                            "-output-directory",
                            tmpdir,
                            str(tex_path),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                except subprocess.TimeoutExpired:
                    raise RuntimeError(
                        "xelatex compilation timed out after 30 seconds. "
                        "This may indicate an infinite loop in the LaTeX "
                        "template or a corrupted installation."
                    )

                if result.returncode != 0:
                    # Save the .log file for debugging (includes LaTeX's
                    # own .log from the temp directory if available).
                    log_path = self._save_failure_log(
                        output_dir=output_dir,
                        job_id=job_id,
                        version=version,
                        pass_num=pass_num,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        tmpdir=tmpdir,
                    )
                    raise RuntimeError(
                        f"xelatex compilation failed on pass {pass_num} "
                        f"(exit code {result.returncode}). "
                        f"See {log_path} for details."
                    )

            # Move/copy the compiled PDF to the output directory.
            pdf_source = Path(tmpdir) / "resume.pdf"
            pdf_dest = output_dir / f"{job_id}_resume_v{version}.pdf"

            if not pdf_source.exists():
                raise RuntimeError(
                    "xelatex completed successfully but no PDF was produced. "
                    "Check the LaTeX template for errors."
                )

            shutil.copy2(str(pdf_source), str(pdf_dest))

        return pdf_dest

    def _save_failure_log(
        self,
        output_dir: Path,
        job_id: int | str,
        version: int,
        pass_num: int,
        stdout: str,
        stderr: str,
        tmpdir: str,
    ) -> Path:
        """Save both stdout/stderr and the LaTeX .log file on failure.

        Args:
            output_dir: Directory to save the log to.
            job_id: Job ID for filename.
            version: Version number for filename.
            pass_num: Which xelatex pass failed.
            stdout: xelatex stdout output.
            stderr: xelatex stderr output.
            tmpdir: Temporary directory path (may contain resume.log from LaTeX).

        Returns:
            Path to the saved log file.
        """
        log_path = output_dir / f"{job_id}_resume_v{version}.log"
        log_content = (
            f"--- xelatex stdout (pass {pass_num}) ---\n"
            f"{stdout}\n\n"
            f"--- xelatex stderr (pass {pass_num}) ---\n"
            f"{stderr}\n"
        )

        # Also try to include the LaTeX .log file if it exists.
        latex_log = Path(tmpdir) / "resume.log"
        if latex_log.exists():
            log_content += (
                f"\n\n--- LaTeX .log file ---\n"
                f"{latex_log.read_text(encoding='utf-8', errors='replace')}"
            )

        log_path.write_text(log_content)
        return log_path

    # ------------------------------------------------------------------ #
    # DB update
    # ------------------------------------------------------------------ #

    def _update_application(
        self,
        user_id_int: int | None,
        job_id_int: int | None,
        pdf_path: str,
        version: int,
    ) -> None:
        """Update the Application row with the generated PDF path and version.

        If no Application row exists for this user+job combination, logs a
        warning but does NOT crash — the PDF was still generated successfully.
        """
        if user_id_int is None or job_id_int is None:
            logger.warning(
                "Cannot update Application: user_id (%s) or job_id (%s) "
                "could not be resolved to ints.",
                user_id_int,
                job_id_int,
            )
            return

        app_row = (
            self.db.query(Application)
            .filter(
                Application.user_id == user_id_int,
                Application.job_id == job_id_int,
            )
            .first()
        )

        if app_row is None:
            logger.warning(
                "No Application row found for user_id=%s, job_id=%s. "
                "PDF was saved to %s but DB was not updated.",
                user_id_int,
                job_id_int,
                pdf_path,
            )
            return

        app_row.resume_path = pdf_path
        app_row.resume_version = version
        self.db.commit()
        logger.info(
            "Updated Application %s: resume_path=%s, resume_version=%s",
            app_row.id,
            pdf_path,
            version,
        )

    # ------------------------------------------------------------------ #
    # Safe resume content helper
    # ------------------------------------------------------------------ #

    @staticmethod
    def _safe_resume_content(
        resume_content: dict[str, Any],
    ) -> dict[str, Any]:
        """Fill in safe defaults for any missing keys in resume_content.

        Accepts a dict that may not perfectly match the expected shape
        (e.g. if called from somewhere other than Issue 12's tailor()).
        """
        return {
            "summary": resume_content.get("summary", ""),
            "skills": resume_content.get("skills", []) or [],
            "projects": resume_content.get("projects", []) or [],
            "experience": resume_content.get("experience", []) or [],
            "education": resume_content.get("education", None),
        }


# ====================================================================== #
# CLI entry point (full Issue 12 → Issue 13 pipeline)
# ====================================================================== #


def main() -> None:
    """Run the full Issue 12 → Issue 13 pipeline from the command line.

    1. Calls ResumeTailoringEngine.tailor() to get tailored content.
    2. Calls PDFGenerator.generate() to compile and save the PDF.
    3. Prints the resulting PDF path.

    Usage:
        python -m src.pipelines.pdf_generator --user-id 1 --job-id 5
    """
    parser = argparse.ArgumentParser(
        description="Generate a tailored PDF resume for a user and job.",
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
        required=True,
        help="Database ID of the job.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Step 1: Get tailored resume content from Issue 12.
    logger.info(
        "Generating tailored resume content for user %s, job %s...",
        args.user_id,
        args.job_id,
    )
    tailor_engine = ResumeTailoringEngine()
    resume_content = tailor_engine.tailor(args.user_id, args.job_id)

    # Step 2: Generate PDF.
    logger.info("Compiling PDF...")
    generator = PDFGenerator()
    pdf_path = generator.generate(args.user_id, args.job_id, resume_content)

    print("\n=== PDF generated successfully ===")
    print(f"Path: {pdf_path}")
    print(f"User: {args.user_id}, Job: {args.job_id}")


if __name__ == "__main__":
    main()
