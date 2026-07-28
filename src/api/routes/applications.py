from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from src.config.database import get_db
from src.models.application import Application
from src.models.job import Job

router = APIRouter(
    prefix="/applications",
    tags=["applications"],
)


class ApplicationResponse(BaseModel):
    id: int
    user_id: int
    job_id: int
    company_name: str
    role_title: str
    status: str
    resume_path: Optional[str] = None
    failure_reason: Optional[str] = None
    manual_application_url: Optional[str] = None
    applied_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.get("/{user_id}", response_model=List[ApplicationResponse])
def get_user_applications(
    user_id: int,
    status: Optional[str] = Query(None, description="Filter by status (e.g., applied, needs_action, failed)"),
    skip: int = Query(0, ge=0, description="Pagination skip"),
    limit: int = Query(50, ge=1, le=100, description="Pagination limit"),
    db: Session = Depends(get_db),
):
    query = db.query(Application, Job).join(Job, Application.job_id == Job.id).filter(Application.user_id == user_id)

    if status:
        query = query.filter(Application.status == status)

    query = query.order_by(Application.created_at.desc())
    
    # Pagination
    results = query.offset(skip).limit(limit).all()
    
    response = []
    for app, job in results:
        app_dict = {
            "id": app.id,
            "user_id": app.user_id,
            "job_id": app.job_id,
            "company_name": job.company_name,
            "role_title": job.role_title,
            "status": app.status,
            "resume_path": app.resume_path,
            "failure_reason": app.failure_reason,
            "applied_at": app.applied_at,
        }
        
        # Include manual application URL for needs_action
        if app.status == "needs_action":
            app_dict["manual_application_url"] = job.application_url
            
        response.append(ApplicationResponse(**app_dict))
        
    return response
