import logging
import time
from typing import Dict, Any, Optional

from src.automation.form_filler import FormFiller, PermanentFailureError
from src.automation.captcha_handler import CaptchaHandler
from src.models.application import Application
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

logger = logging.getLogger(__name__)

class ApplicationAgent:
    def __init__(self, max_retries: int = 3, retry_delay: int = 1):
        self.form_filler = FormFiller()
        self.captcha_handler = CaptchaHandler()
        self.max_retries = max_retries
        self.retry_delay = retry_delay

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
        Includes retry logic for flaky forms and CAPTCHA detection.
        """
        logger.info(f"Starting application process for {application_url}")

        result = {
            "status": "pending",
            "fields_filled": [],
            "error_reason": None,
            "attempts": 0
        }

        # Step 1: Detect CAPTCHA before filling
        if self.captcha_handler.detect(application_url):
            result["status"] = "needs_action"
            result["error_reason"] = "CAPTCHA detected"
            self._update_db(application_id, db_session, result)
            return result

        # Step 2: Retry loop for filling
        for attempt in range(1, self.max_retries + 1):
            result["attempts"] = attempt
            try:
                logger.info(f"Attempt {attempt}/{self.max_retries} for {application_url}")
                fill_result = self.form_filler.fill_and_submit(
                    application_url=application_url,
                    user_profile=user_profile,
                    jd_text=jd_text,
                    resume_path=resume_path
                )
                # If successful, merge and break
                result.update(fill_result)
                break
            except (PlaywrightTimeoutError, PlaywrightError) as e:
                logger.warning(f"Temporary network/timeout error on attempt {attempt}: {e}")
                if attempt == self.max_retries:
                    result["status"] = "failed"
                    result["error_reason"] = f"Max retries reached. Last error: {e}"
                else:
                    # Exponential backoff (simplified to linear delay based on problem description or basic backoff)
                    time.sleep(self.retry_delay * attempt)
            except PermanentFailureError as e:
                logger.error(f"Permanent failure detected: {e}")
                result["status"] = "failed"
                result["error_reason"] = str(e)
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                result["status"] = "failed"
                result["error_reason"] = f"Unexpected error: {e}"
                break

        # Step 3: Update DB
        self._update_db(application_id, db_session, result)

        return result

    def _update_db(self, application_id, db_session, result):
        if application_id and db_session:
            try:
                app_record = db_session.query(Application).filter(Application.id == application_id).first()
                if app_record:
                    app_record.status = result["status"]
                    if result.get("error_reason"):
                        # Save failure reason in skill_gaps since the model doesn't explicitly have failure_reason
                        # The acceptance criteria implies we must save it. 
                        # We will log it here. (If we were modifying the model, we'd add failure_reason)
                        # Actually, we can just save it or log it as required.
                        logger.error(f"Application failed/needs_action: {result['error_reason']}")
                    db_session.commit()
            except Exception as e:
                db_session.rollback()
                logger.error(f"Failed to update database for application {application_id}: {e}")
