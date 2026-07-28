import pytest
from datetime import datetime
from sqlalchemy.orm import Session

from src.models.user import User, ApplicationMode
from src.models.job import Job
from src.models.application import Application, ApplicationStatusLog
from src.utils.status_logger import StatusLogger
from src.config.database import SessionLocal, engine
from src.models import Base

@pytest.fixture(scope="module")
def db_session():
    # Setup database for tests
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    # Clean up before tests
    db.query(ApplicationStatusLog).delete()
    db.query(Application).delete()
    db.query(Job).delete()
    db.query(User).delete()
    db.commit()
    
    yield db
    db.close()

@pytest.fixture
def setup_data(db_session: Session):
    import uuid
    uid = str(uuid.uuid4())
    user = User(
        name="Test User",
        email=f"test_{uid}@example.com",
        mode=ApplicationMode.job,
        master_profile={}
    )
    db_session.add(user)
    db_session.commit()

    job = Job(
        company_name="Test Co",
        role_title="Engineer",
        jd_text="Do things",
        application_url="http://test.co/apply",
        source="test",
        listing_type="job"
    )
    db_session.add(job)
    db_session.commit()

    app = Application(
        user_id=user.id,
        job_id=job.id,
        status="pending"
    )
    db_session.add(app)
    db_session.commit()

    return {"user": user, "job": job, "app": app}

def test_status_logger_applied(db_session: Session, setup_data: dict):
    app_id = setup_data["app"].id
    
    StatusLogger.log_status(db_session, app_id, "applied")
    
    # Check application update
    app = db_session.query(Application).filter_by(id=app_id).first()
    assert app.status == "applied"
    assert app.applied_at is not None
    
    # Check audit log
    logs = db_session.query(ApplicationStatusLog).filter_by(application_id=app_id).all()
    assert len(logs) == 1
    assert logs[0].status == "applied"

def test_status_logger_failed(db_session: Session, setup_data: dict):
    app_id = setup_data["app"].id
    
    StatusLogger.log_status(db_session, app_id, "failed", reason="Form error")
    
    # Check application update
    app = db_session.query(Application).filter_by(id=app_id).first()
    assert app.status == "failed"
    assert app.failure_reason == "Form error"
    
    # Check audit log
    logs = db_session.query(ApplicationStatusLog).filter_by(application_id=app_id).order_by(ApplicationStatusLog.id.desc()).all()
    assert logs[0].status == "failed"
    assert logs[0].reason == "Form error"

def test_status_logger_needs_action(db_session: Session, setup_data: dict):
    app_id = setup_data["app"].id
    
    StatusLogger.log_status(db_session, app_id, "needs_action", reason="Captcha required")
    
    # Check application update
    app = db_session.query(Application).filter_by(id=app_id).first()
    assert app.status == "needs_action"
    assert app.failure_reason == "Captcha required"
    
    # Check audit log
    logs = db_session.query(ApplicationStatusLog).filter_by(application_id=app_id).order_by(ApplicationStatusLog.id.desc()).all()
    assert logs[0].status == "needs_action"
    assert logs[0].reason == "Captcha required"
