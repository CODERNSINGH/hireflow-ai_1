"""
EmailService - Transactional email delivery for HireFlow.

Sends the weekly report HTML to the user with resume PDFs attached.
Supports Resend and SendGrid.
Logs sent status to the database.
"""

import os
import base64
import logging
from typing import List, Optional
from datetime import datetime, timezone

import resend
import sendgrid
from sendgrid.helpers.mail import (
    Mail, Attachment, FileContent, FileName, FileType, Disposition
)

from src.config.settings import get_settings
from src.config.database import SessionLocal
from src.models.report import WeeklyReport

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        settings = get_settings()
        # Default to resend if not explicitly set
        self.provider = os.getenv("EMAIL_PROVIDER", "resend").lower()
        self.resend_api_key = os.getenv("RESEND_API_KEY", "")
        self.sendgrid_api_key = os.getenv("SENDGRID_API_KEY", "")
        self.from_email = os.getenv("FROM_EMAIL", "reports@hireflow.ai")
        
        if self.provider == "resend":
            resend.api_key = self.resend_api_key

    def send_weekly_report(
        self,
        to_email: str,
        subject: str,
        report_html: str,
        resume_paths: List[str],
        user_id: Optional[int] = None
    ) -> bool:
        """
        Send the weekly report email.
        """
        # Truncate attachment list to max 10
        resume_paths = resume_paths[:10]
        
        # Check attachment size
        total_size = 0
        valid_attachments = []
        for path in resume_paths:
            if os.path.exists(path):
                total_size += os.path.getsize(path)
                valid_attachments.append(path)

        if total_size > 10 * 1024 * 1024: # 10MB
            logger.warning(f"Total attachment size {total_size} exceeds 10MB limit. Not attaching files.")
            report_html += "<br><p><b>Note:</b> Attachments exceeded 10MB limit and have been omitted. Please view them in your dashboard.</p>"
            valid_attachments = []

        try:
            if self.provider == "sendgrid":
                self._send_with_sendgrid(to_email, subject, report_html, valid_attachments)
            else:
                self._send_with_resend(to_email, subject, report_html, valid_attachments)
        except Exception as e:
            logger.error(f"Failed to send email via {self.provider}: {e}")
            return False

        # Log to database if user_id is provided
        if user_id is not None:
            self._log_sent_at(user_id)

        return True

    def _send_with_resend(self, to_email: str, subject: str, html: str, attachments: List[str]):
        if not self.resend_api_key:
            logger.error("RESEND_API_KEY not set")
            raise ValueError("RESEND_API_KEY not set")

        params = {
            "from": self.from_email,
            "to": to_email,
            "subject": subject,
            "html": html,
        }

        if attachments:
            att_data = []
            for path in attachments:
                with open(path, "rb") as f:
                    content = f.read()
                att_data.append({
                    "filename": os.path.basename(path),
                    "content": list(content),  # Resend python SDK expects list of ints for binary data
                })
            params["attachments"] = att_data

        try:
            response = resend.Emails.send(params)
            logger.info(f"Resend email sent: {response}")
        except Exception as e:
            logger.error(f"Resend API error: {e}")
            raise

    def _send_with_sendgrid(self, to_email: str, subject: str, html: str, attachments: List[str]):
        if not self.sendgrid_api_key:
            logger.error("SENDGRID_API_KEY not set")
            raise ValueError("SENDGRID_API_KEY not set")

        sg = sendgrid.SendGridAPIClient(api_key=self.sendgrid_api_key)
        message = Mail(
            from_email=self.from_email,
            to_emails=to_email,
            subject=subject,
            html_content=html
        )

        for path in attachments:
            with open(path, "rb") as f:
                content = f.read()
            encoded = base64.b64encode(content).decode()
            
            attachment = Attachment()
            attachment.file_content = FileContent(encoded)
            attachment.file_name = FileName(os.path.basename(path))
            attachment.file_type = FileType('application/pdf')
            attachment.disposition = Disposition('attachment')
            message.attachment = attachment

        try:
            response = sg.send(message)
            logger.info(f"SendGrid email sent: status {response.status_code}")
            if response.status_code >= 400:
                raise ValueError(f"SendGrid returned {response.status_code}")
        except Exception as e:
            logger.error(f"SendGrid API error: {e}")
            raise

    def _log_sent_at(self, user_id: int):
        """Update the sent_at timestamp in the weekly_reports table."""
        db = SessionLocal()
        try:
            # Find the latest report for this user
            report = (
                db.query(WeeklyReport)
                .filter(WeeklyReport.user_id == user_id)
                .order_by(WeeklyReport.week_start.desc())
                .first()
            )
            if report:
                report.sent_at = datetime.now(timezone.utc)
                db.commit()
                logger.info(f"Logged sent_at for user_id={user_id}")
            else:
                logger.warning(f"No weekly report found for user_id={user_id} to log sent_at.")
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to log sent_at for user_id={user_id}: {e}")
        finally:
            db.close()
