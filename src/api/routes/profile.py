"""
HireFlow AI — Profile API Router

Endpoints:
  POST /profile   — Create a user profile from JSON body or PDF upload
  GET  /profile/{user_id} — Retrieve a user profile by ID

The POST endpoint supports two intake modes:
  1. JSON body  — client sends a ProfileCreateRequest JSON object.
  2. PDF upload — client sends multipart/form-data with a PDF file plus
                  optional override fields. Text is extracted from the PDF
                  with pypdf, then passed to the LLM client for structured
                  extraction. Explicit form fields always win over LLM output.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.config.settings import get_settings
from src.models.user import ApplicationMode, User
from src.utils.llm_client import get_llm_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])


# --------------------------------------------------------------------------- #
# Pydantic schemas
# --------------------------------------------------------------------------- #


class ProfileCreateRequest(BaseModel):
    """Request body for JSON-based profile creation."""

    name: str
    email: EmailStr
    mode: ApplicationMode
    skills: Optional[List[str]] = None
    target_roles: Optional[List[str]] = None
    preferred_locations: Optional[List[str]] = None
    min_stipend: Optional[int] = None
    weekly_quota: int = 5
    confirmation_mode: str = "batch"

    @field_validator("confirmation_mode")
    @classmethod
    def validate_confirmation_mode(cls, v: str) -> str:
        allowed = {"batch", "per_application"}
        if v not in allowed:
            raise ValueError(f"confirmation_mode must be one of {allowed}, got '{v}'")
        return v


class UserResponse(BaseModel):
    """Response schema returned after creating or fetching a profile."""

    id: int
    name: str
    email: str
    mode: str
    master_profile: Optional[Any] = None
    weekly_quota: int
    confirmation_mode: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --------------------------------------------------------------------------- #
# Schema used to guide the LLM extraction from PDF text
# --------------------------------------------------------------------------- #

PROFILE_EXTRACT_SCHEMA = {
    "name": "string — full name of the candidate",
    "email": "string — email address",
    "phone": "string — phone number (optional)",
    "skills": "array of strings — technical and soft skills",
    "education": "array of objects — [{institution, degree, year}]",
    "experience": "array of objects — [{company, role, duration, description}]",
    "target_roles": "array of strings — job titles the candidate is targeting",
    "preferred_locations": "array of strings — preferred work locations",
    "summary": "string — brief professional summary",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _extract_pdf_text(file_bytes: bytes) -> str:
    """Extract raw text from a PDF using pypdf."""
    try:
        from pypdf import PdfReader  # type: ignore[import]
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "PDF processing library is not installed. " "Run: pip install pypdf"
            ),
        ) from exc

    reader = PdfReader(io.BytesIO(file_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages).strip()


def _build_master_profile(
    llm_data: dict,
    *,
    skills: Optional[List[str]],
    target_roles: Optional[List[str]],
    preferred_locations: Optional[List[str]],
    min_stipend: Optional[int],
    raw_resume_text: Optional[str] = None,
) -> dict:
    """Merge LLM-extracted data with explicit overrides.

    Explicit fields always win. LLM data fills in gaps.
    """
    profile: dict = dict(llm_data)

    # Explicit overrides always take precedence
    if skills is not None:
        profile["skills"] = skills
    if target_roles is not None:
        profile["target_roles"] = target_roles
    if preferred_locations is not None:
        profile["preferred_locations"] = preferred_locations
    if min_stipend is not None:
        profile["min_stipend"] = min_stipend

    # Store raw resume text as a fallback / audit trail
    if raw_resume_text:
        profile["raw_resume_text"] = raw_resume_text

    return profile


# --------------------------------------------------------------------------- #
# POST /profile — JSON intake
# --------------------------------------------------------------------------- #


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_profile_json(
    body: ProfileCreateRequest,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Create a user profile from a JSON body.

    Returns the created user with its generated database id.
    Raises 422 automatically if `mode` is not 'internship' or 'job'.
    """
    master_profile = _build_master_profile(
        {},
        skills=body.skills,
        target_roles=body.target_roles,
        preferred_locations=body.preferred_locations,
        min_stipend=body.min_stipend,
    )

    user = User(
        name=body.name,
        email=body.email,
        mode=body.mode,
        master_profile=master_profile if master_profile else None,
        weekly_quota=body.weekly_quota,
        confirmation_mode=body.confirmation_mode,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning("Failed to create profile: email already exists. Error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address is already registered.",
        )
    db.refresh(user)
    logger.info("Created profile for user_id=%s email=%s", user.id, user.email)
    return UserResponse.model_validate(user)


# --------------------------------------------------------------------------- #
# POST /profile/upload — PDF multipart intake
# --------------------------------------------------------------------------- #


@router.post(
    "/upload",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_profile_pdf(
    file: UploadFile = File(..., description="PDF resume file"),
    name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    mode: Optional[str] = Form(None),
    skills: Optional[str] = Form(None, description="Comma-separated skills override"),
    target_roles: Optional[str] = Form(
        None, description="Comma-separated target roles override"
    ),
    preferred_locations: Optional[str] = Form(
        None, description="Comma-separated preferred locations override"
    ),
    min_stipend: Optional[int] = Form(None),
    weekly_quota: int = Form(5),
    confirmation_mode: str = Form("batch"),
    db: Session = Depends(get_db),
) -> UserResponse:
    """Create a user profile from a PDF resume upload.

    The PDF text is extracted and passed to the configured LLM for structured
    extraction. Any explicitly provided form fields override the LLM output.
    At minimum, `name`, `email`, and `mode` are required (either from the form
    or extracted by the LLM).
    """
    # Validate content type
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Expected a PDF file, got '{file.content_type}'.",
        )

    # Validate mode enum if provided explicitly
    resolved_mode: Optional[ApplicationMode] = None
    if mode is not None:
        try:
            resolved_mode = ApplicationMode(mode)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"mode must be 'internship' or 'job', got '{mode}'.",
            )

    # Extract text from PDF
    file_bytes = await file.read()
    resume_text = _extract_pdf_text(file_bytes)
    logger.info(
        "Extracted %d characters from uploaded PDF '%s'",
        len(resume_text),
        file.filename,
    )

    # Call the LLM to extract structured fields
    settings = get_settings()
    try:
        llm = get_llm_client(settings)
        llm_data = llm.extract(resume_text, PROFILE_EXTRACT_SCHEMA)
    except ValueError as exc:
        # Missing API key — return a clear error to the developer
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    # Resolve name, email, mode — explicit form fields win over LLM
    resolved_name: Optional[str] = name or llm_data.get("name")
    resolved_email: Optional[str] = email or llm_data.get("email")
    if resolved_mode is None and llm_data.get("target_roles"):
        # mode cannot be reliably inferred from the resume; require it explicitly
        pass

    if not resolved_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not determine 'name' from the PDF or form fields. "
            "Pass name= as a form field.",
        )
    if not resolved_email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not determine 'email' from the PDF or form fields. "
            "Pass email= as a form field.",
        )
    if resolved_mode is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'mode' is required and could not be inferred. "
            "Pass mode='internship' or mode='job' as a form field.",
        )

    # Parse comma-separated override lists
    skills_list = [s.strip() for s in skills.split(",")] if skills else None
    roles_list = [r.strip() for r in target_roles.split(",")] if target_roles else None
    locations_list = (
        [loc.strip() for loc in preferred_locations.split(",")]
        if preferred_locations
        else None
    )

    master_profile = _build_master_profile(
        llm_data,
        skills=skills_list,
        target_roles=roles_list,
        preferred_locations=locations_list,
        min_stipend=min_stipend,
        raw_resume_text=resume_text,
    )

    user = User(
        name=resolved_name,
        email=resolved_email,
        mode=resolved_mode,
        master_profile=master_profile,
        weekly_quota=weekly_quota,
        confirmation_mode=confirmation_mode,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning(
            "Failed to create profile from PDF: email already exists. Error: %s", exc
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address is already registered.",
        )
    db.refresh(user)
    logger.info("Created profile from PDF for user_id=%s email=%s", user.id, user.email)
    return UserResponse.model_validate(user)


# --------------------------------------------------------------------------- #
# GET /profile/{user_id}
# --------------------------------------------------------------------------- #


@router.get("/{user_id}", response_model=UserResponse)
def get_profile(user_id: int, db: Session = Depends(get_db)) -> UserResponse:
    """Fetch a user profile by its database id.

    Returns 404 if the user does not exist.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id={user_id} not found.",
        )
    return UserResponse.model_validate(user)
