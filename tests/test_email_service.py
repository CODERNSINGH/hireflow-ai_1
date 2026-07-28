"""
Tests for EmailService (Issue #21).

Acceptance criteria:
- Sends weekly report HTML as email body
- Attaches resume PDFs (up to 10 attachments)
- Works with Resend and SendGrid
- If total attachment size exceeds 10MB: links to resumes instead of attaching
- Email sending logged with timestamp in weekly_reports table
- Failed email send: logs error, does not crash the weekly cycle
- Tests use mocked email provider so no real emails are sent in CI
- At least 3 test cases: normal send, empty attachments, provider failure handling
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
import base64

from src.utils.email_service import EmailService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db_session():
    mock = MagicMock()
    # Ensure it returns a mock report when queried
    mock_report = MagicMock()
    mock_report.sent_at = None
    mock.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_report
    return mock, mock_report

@pytest.fixture
def temp_resumes(tmp_path):
    """Create some dummy 'PDF' files."""
    paths = []
    for i in range(3):
        path = tmp_path / f"resume_{i}.pdf"
        path.write_text(f"Dummy PDF content {i}")
        paths.append(str(path))
    return paths

@pytest.fixture
def large_resume(tmp_path):
    """Create a dummy large file > 10MB."""
    path = tmp_path / "large_resume.pdf"
    # Create 11MB file
    with open(path, "wb") as f:
        f.seek(11 * 1024 * 1024 - 1)
        f.write(b"0")
    return [str(path)]

# ===========================================================================
# Test Cases
# ===========================================================================

class TestEmailService:

    @patch("src.utils.email_service.resend.Emails.send")
    @patch("src.utils.email_service.SessionLocal")
    def test_normal_send_resend(self, mock_session, mock_send, mock_db_session, temp_resumes):
        """Test sending email normally via Resend with attachments."""
        mock_db, mock_report = mock_db_session
        mock_session.return_value = mock_db
        mock_send.return_value = {"id": "12345"}
        
        with patch.dict(os.environ, {"RESEND_API_KEY": "fake_key", "EMAIL_PROVIDER": "resend"}):
            service = EmailService()
            result = service.send_weekly_report(
                to_email="test@example.com",
                subject="Weekly Report",
                report_html="<h1>Hello</h1>",
                resume_paths=temp_resumes,
                user_id=1
            )
            
            assert result is True
            mock_send.assert_called_once()
            
            # Check attachments in params
            call_args = mock_send.call_args[0][0]
            assert "attachments" in call_args
            assert len(call_args["attachments"]) == 3
            
            # Check database log
            mock_db.commit.assert_called_once()
            assert mock_report.sent_at is not None

    @patch("src.utils.email_service.sendgrid.SendGridAPIClient")
    @patch("src.utils.email_service.SessionLocal")
    def test_normal_send_sendgrid(self, mock_session, mock_sg_client, mock_db_session, temp_resumes):
        """Test sending email normally via SendGrid with attachments."""
        mock_db, mock_report = mock_db_session
        mock_session.return_value = mock_db
        
        mock_sg_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_sg_instance.send.return_value = mock_response
        mock_sg_client.return_value = mock_sg_instance
        
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "fake_key", "EMAIL_PROVIDER": "sendgrid"}):
            service = EmailService()
            result = service.send_weekly_report(
                to_email="test@example.com",
                subject="Weekly Report",
                report_html="<h1>Hello</h1>",
                resume_paths=temp_resumes,
                user_id=1
            )
            
            assert result is True
            mock_sg_instance.send.assert_called_once()
            
            # Database log
            mock_db.commit.assert_called_once()

    @patch("src.utils.email_service.resend.Emails.send")
    def test_empty_attachments(self, mock_send):
        """Test sending email with no attachments."""
        mock_send.return_value = {"id": "12345"}
        
        with patch.dict(os.environ, {"RESEND_API_KEY": "fake_key", "EMAIL_PROVIDER": "resend"}):
            service = EmailService()
            result = service.send_weekly_report(
                to_email="test@example.com",
                subject="Weekly Report",
                report_html="<h1>Hello</h1>",
                resume_paths=[],
                user_id=None # no db logging
            )
            
            assert result is True
            mock_send.assert_called_once()
            call_args = mock_send.call_args[0][0]
            assert "attachments" not in call_args

    @patch("src.utils.email_service.resend.Emails.send")
    def test_attachment_size_exceeds_limit(self, mock_send, large_resume):
        """Test that large attachments are dropped and a note is added."""
        mock_send.return_value = {"id": "12345"}
        
        with patch.dict(os.environ, {"RESEND_API_KEY": "fake_key", "EMAIL_PROVIDER": "resend"}):
            service = EmailService()
            html = "<h1>Hello</h1>"
            result = service.send_weekly_report(
                to_email="test@example.com",
                subject="Weekly Report",
                report_html=html,
                resume_paths=large_resume,
                user_id=None
            )
            
            assert result is True
            mock_send.assert_called_once()
            call_args = mock_send.call_args[0][0]
            
            # Should have no attachments because size exceeded 10MB
            assert "attachments" not in call_args
            
            # Note should be appended to HTML
            assert "exceeded 10MB limit" in call_args["html"]

    @patch("src.utils.email_service.resend.Emails.send")
    @patch("src.utils.email_service.SessionLocal")
    def test_provider_failure_handling(self, mock_session, mock_send, mock_db_session, temp_resumes):
        """Test that provider failure does not crash the app and returns False."""
        mock_db, mock_report = mock_db_session
        mock_session.return_value = mock_db
        
        mock_send.side_effect = Exception("API Down")
        
        with patch.dict(os.environ, {"RESEND_API_KEY": "fake_key", "EMAIL_PROVIDER": "resend"}):
            service = EmailService()
            result = service.send_weekly_report(
                to_email="test@example.com",
                subject="Weekly Report",
                report_html="<h1>Hello</h1>",
                resume_paths=temp_resumes,
                user_id=1
            )
            
            assert result is False
            # Should not commit to DB since sending failed
            mock_db.commit.assert_not_called()

    @patch("src.utils.email_service.resend.Emails.send")
    def test_missing_api_key_handling(self, mock_send):
        """Test missing API key fails gracefully."""
        # Intentionally missing API key
        with patch.dict(os.environ, {"EMAIL_PROVIDER": "resend", "RESEND_API_KEY": ""}):
            service = EmailService()
            result = service.send_weekly_report(
                to_email="test@example.com",
                subject="Weekly Report",
                report_html="<h1>Hello</h1>",
                resume_paths=[]
            )
            assert result is False
            mock_send.assert_not_called()
