from datetime import datetime
from sqlalchemy.orm import Session
from src.models.application import Application, ApplicationStatusLog


class StatusLogger:
    @staticmethod
    def log_status(
        db: Session, application_id: int, status: str, reason: str = None
    ) -> None:
        """
        Log a status change for an application and update the application record.
        """
        # Create an audit log entry
        log_entry = ApplicationStatusLog(
            application_id=application_id, status=status, reason=reason
        )
        db.add(log_entry)

        # Update the application's current status
        app = db.query(Application).filter(Application.id == application_id).first()
        if app:
            app.status = status
            if status == "failed":
                app.failure_reason = reason
            elif status == "needs_action":
                app.failure_reason = reason  # Store reason in failure_reason as well
            elif status == "applied":
                app.applied_at = datetime.utcnow()
                
        db.commit()
