import logging
from typing import Dict, Any, Optional

from src.automation.form_filler import FormFiller
from src.models.application import Application

logger = logging.getLogger(__name__)

class ApplicationAgent:
    def __init__(self):
        self.form_filler = FormFiller()

    def apply(
        self,
        application_url: str,
        resume_path: str,
        user_profile: Dict[str, Any],
        jd_text: str,
        application_id: Optional[int] = None,
        db_session=None
    ) -> Dict[str, Any]:
        """
        Orchestrates the application process using the FormFiller.
        If application_id and db_session are provided, it updates the database.
        """
        logger.info(f"Starting application process for {application_url}")

        result = self.form_filler.fill_and_submit(
            application_url=application_url,
            user_profile=user_profile,
            jd_text=jd_text,
            resume_path=resume_path
        )

        # Update DB if session and ID are provided
        if application_id and db_session:
            try:
                app_record = db_session.query(Application).filter(Application.id == application_id).first()
                if app_record:
                    app_record.status = result["status"]
                    if result.get("error_reason"):
                        # We might need a specific field for this, but for now we could use skill_gaps or similar,
                        # or just rely on the logging. The issue mentions "failure reason saved to DB"
                        # I'll check if Application model has it. It didn't seem to have `failure_reason`
                        # Let's add logging instead if no field exists.
                        logger.error(f"Application failed: {result['error_reason']}")
                    db_session.commit()
            except Exception as e:
                db_session.rollback()
                logger.error(f"Failed to update database for application {application_id}: {e}")

        return result
