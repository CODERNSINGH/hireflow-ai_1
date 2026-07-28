import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from src.agents.application_agent import ApplicationAgent

# Note: These tests require Playwright to be installed.
# We will use the file:// protocol to load our local HTML fixture.

@pytest.fixture
def sample_form_url():
    """Returns the file:// URL to the sample HTML fixture."""
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "sample_form.html")
    return f"file://{os.path.abspath(fixture_path)}"

@pytest.fixture
def captcha_form_url():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "captcha_form.html")
    return f"file://{os.path.abspath(fixture_path)}"

@pytest.fixture
def flaky_form_url():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "flaky_form.html")
    return f"file://{os.path.abspath(fixture_path)}"

@pytest.fixture
def dummy_resume_path():
    """Creates a temporary dummy PDF file."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 dummy content")
        path = f.name
    yield path
    os.remove(path)

@pytest.fixture
def user_profile():
    return {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "555-1234",
        "education": "bachelors",
        "experience": 3,
        "skills": ["Python", "Playwright", "FastAPI"]
    }

@pytest.fixture
def jd_text():
    return "Looking for a Python Developer with Playwright experience."

@patch("src.automation.form_filler.get_llm_client")
def test_form_filler_standard_fields_and_submit(mock_get_llm, sample_form_url, dummy_resume_path, user_profile, jd_text):
    """
    Test Case 1: Standard fields, resume upload, free-text LLM interaction, and submission success.
    """
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "I love Python and Playwright."
    mock_get_llm.return_value = mock_llm

    agent = ApplicationAgent()
    result = agent.apply(
        application_url=sample_form_url,
        resume_path=dummy_resume_path,
        user_profile=user_profile,
        jd_text=jd_text
    )

    assert result["status"] == "applied"
    
    fields = result["fields_filled"]
    assert "name" in fields
    assert "email" in fields
    assert "phone" in fields
    assert "education" in fields
    assert "experience" in fields
    assert "skills" in fields
    assert "resume" in fields
    assert "textarea_0" in fields
    
    mock_llm.chat.assert_called_once()
    prompt = mock_llm.chat.call_args[0][0]
    assert "Why do you want to work here?" in prompt
    assert "Jane Doe" in prompt
    assert "Python Developer" in prompt

@patch("src.automation.form_filler.get_llm_client")
def test_form_filler_missing_fields(mock_get_llm, sample_form_url, dummy_resume_path, jd_text):
    """
    Test Case 2: Missing fields prevent successful submission (handled gracefully).
    """
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "I want to work here."
    mock_get_llm.return_value = mock_llm

    agent = ApplicationAgent()
    
    # Minimal profile missing name and email
    partial_profile = {
        "phone": "555-0000"
    }

    result = agent.apply(
        application_url=sample_form_url,
        resume_path=dummy_resume_path,
        user_profile=partial_profile,
        jd_text=jd_text
    )

    # Because required fields aren't filled, the form doesn't submit successfully.
    # Our fixture JS will show an alert and NOT show the success div.
    assert result["status"] == "failed"

@patch("src.automation.form_filler.get_llm_client")
def test_form_filler_invalid_url(mock_get_llm, dummy_resume_path, user_profile, jd_text):
    """
    Test Case 3: Test graceful failure on bad URL.
    """
    mock_get_llm.return_value = MagicMock()

    agent = ApplicationAgent()
    result = agent.apply(
        application_url="file:///non_existent_file.html",
        resume_path=dummy_resume_path,
        user_profile=user_profile,
        jd_text=jd_text
    )

    assert result["status"] == "failed"
    assert result["error_reason"] is not None
    assert "net::ERR_FILE_NOT_FOUND" in result["error_reason"] or "net::ERR_NAME_NOT_RESOLVED" in result["error_reason"] or "ERR_" in result["error_reason"]

@patch("src.automation.form_filler.get_llm_client")
def test_captcha_detection(mock_get_llm, captcha_form_url, dummy_resume_path, user_profile, jd_text):
    """
    Test Case 4: CAPTCHA detected.
    """
    mock_get_llm.return_value = MagicMock()

    agent = ApplicationAgent()
    result = agent.apply(
        application_url=captcha_form_url,
        resume_path=dummy_resume_path,
        user_profile=user_profile,
        jd_text=jd_text
    )

    assert result["status"] == "needs_action"
    assert "CAPTCHA" in result["error_reason"]

@patch("src.automation.form_filler.get_llm_client")
@patch("src.agents.application_agent.FormFiller.fill_and_submit")
def test_flaky_form_retry_success(mock_fill, mock_get_llm, flaky_form_url, dummy_resume_path, user_profile, jd_text):
    """
    Test Case 5: Flaky form fails on attempt 1, succeeds on attempt 2.
    """
    mock_get_llm.return_value = MagicMock()
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    mock_fill.side_effect = [
        PlaywrightTimeoutError("Network timeout"),
        {"status": "applied", "fields_filled": ["name"]}
    ]

    agent = ApplicationAgent(max_retries=3, retry_delay=1)
    result = agent.apply(
        application_url=flaky_form_url,
        resume_path=dummy_resume_path,
        user_profile=user_profile,
        jd_text=jd_text
    )

    assert result["status"] == "applied"
    assert result["attempts"] == 2

@patch("src.automation.form_filler.get_llm_client")
def test_permanent_failure(mock_get_llm, dummy_resume_path, user_profile, jd_text):
    """
    Test Case 6: Permanent failure (selector not found / submit missing) is not retried.
    We can test this by using a form that doesn't have a submit button.
    The sample form without filling required fields fails to submit, which raises PermanentFailureError.
    Wait, in test_form_filler_missing_fields, we assert status == failed. We just need to check attempts == 1.
    """
    mock_get_llm.return_value = MagicMock()

    agent = ApplicationAgent(max_retries=3, retry_delay=1)
    
    # Minimal profile missing name and email
    partial_profile = {
        "phone": "555-0000"
    }

    result = agent.apply(
        application_url="data:,<html><body><h1>No submit button</h1></body></html>",
        resume_path=dummy_resume_path,
        user_profile=partial_profile,
        jd_text=jd_text
    )

    assert result["status"] == "failed"
    assert result["attempts"] == 1
    assert "submit button missing" in result["error_reason"]
