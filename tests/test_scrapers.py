import os
from unittest.mock import patch, MagicMock
from src.scrapers.lever_scraper import scrape_lever
from src.scrapers.greenhouse_scraper import scrape_greenhouse

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
LEVER_FIXTURE_URL = (
    f"file://{os.path.abspath(os.path.join(FIXTURES_DIR, 'lever.html'))}"
)
GREENHOUSE_FIXTURE_URL = (
    f"file://{os.path.abspath(os.path.join(FIXTURES_DIR, 'greenhouse.html'))}"
)
EMPTY_FIXTURE_URL = (
    f"file://{os.path.abspath(os.path.join(FIXTURES_DIR, 'empty.html'))}"
)
MOCK_JD_PATH = f"file://{os.path.abspath(os.path.join(FIXTURES_DIR, 'mock_jd.html'))}"

os.makedirs(FIXTURES_DIR, exist_ok=True)

# Create mock JD
with open(os.path.join(FIXTURES_DIR, "mock_jd.html"), "w") as f:
    f.write(
        '<!DOCTYPE html><html><body><div class="content">This is the job description.</div></body></html>'
    )

# Create empty fixture file
with open(os.path.join(FIXTURES_DIR, "empty.html"), "w") as f:
    f.write("<html><body></body></html>")

# Create lever fixture with absolute paths
lever_html = f"""<!DOCTYPE html>
<html>
<body>
    <div class="posting">
        <div class="posting-title">
            <h5 data-qa="posting-name">Software Engineer Intern</h5>
            <a class="posting-title" href="{MOCK_JD_PATH}">Apply</a>
        </div>
        <span class="sort-by-location">San Francisco, CA</span>
    </div>
    <div class="posting">
        <div class="posting-title">
            <h5 data-qa="posting-name">Senior Software Engineer</h5>
            <a class="posting-title" href="{MOCK_JD_PATH}">Apply</a>
        </div>
        <span class="sort-by-location">New York, NY</span>
    </div>
</body>
</html>"""
with open(os.path.join(FIXTURES_DIR, "lever.html"), "w") as f:
    f.write(lever_html)

# Create greenhouse fixture with absolute paths
greenhouse_html = f"""<!DOCTYPE html>
<html>
<body>
    <div class="opening">
        <a href="{MOCK_JD_PATH}">Software Engineer Intern</a>
        <span class="location">San Francisco, CA</span>
    </div>
    <div class="opening">
        <a href="{MOCK_JD_PATH}">Senior Software Engineer</a>
        <span class="location">New York, NY</span>
    </div>
    <div class="opening">
        <a href="{MOCK_JD_PATH}">Product Manager Intern</a>
        <span class="location">Remote</span>
    </div>
</body>
</html>"""
with open(os.path.join(FIXTURES_DIR, "greenhouse.html"), "w") as f:
    f.write(greenhouse_html)


@patch("src.scrapers.lever_scraper.time.sleep")
@patch("src.scrapers.lever_scraper.SessionLocal")
def test_lever_scraper_extracts_all_fields(mock_session_local, mock_sleep):
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    scrape_lever(LEVER_FIXTURE_URL, "job")

    assert mock_db.add.call_count == 2

    # Check first job
    first_job = mock_db.add.call_args_list[0][0][0]
    expected_company = [p for p in os.path.abspath(FIXTURES_DIR).split('/') if p][0]
    assert first_job.company_name == expected_company
    assert first_job.role_title == "Software Engineer Intern"
    assert first_job.location == "San Francisco, CA"
    assert "mock_jd.html" in first_job.application_url
    assert "This is the job description." in first_job.jd_text
    assert first_job.source == "lever"


@patch("src.scrapers.lever_scraper.time.sleep")
@patch("src.scrapers.lever_scraper.SessionLocal")
def test_lever_scraper_listing_type(mock_session_local, mock_sleep):
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    scrape_lever(LEVER_FIXTURE_URL, "job")

    jobs = [call_args[0][0] for call_args in mock_db.add.call_args_list]

    assert jobs[0].listing_type == "internship"
    assert jobs[1].listing_type == "job"


@patch("src.scrapers.lever_scraper.time.sleep")
@patch("src.scrapers.lever_scraper.SessionLocal")
def test_lever_scraper_empty_page(mock_session_local, mock_sleep):
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    scrape_lever(EMPTY_FIXTURE_URL, "job")

    assert mock_db.add.call_count == 0


@patch("src.scrapers.greenhouse_scraper.time.sleep")
@patch("src.scrapers.greenhouse_scraper.SessionLocal")
def test_greenhouse_scraper_extracts_all_fields(mock_session_local, mock_sleep):
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    scrape_greenhouse(GREENHOUSE_FIXTURE_URL, "job")

    assert mock_db.add.call_count == 3

    # Check first job
    first_job = mock_db.add.call_args_list[0][0][0]
    expected_company = [p for p in os.path.abspath(FIXTURES_DIR).split('/') if p][0]
    assert first_job.company_name == expected_company
    assert first_job.role_title == "Software Engineer Intern"
    assert first_job.location == "San Francisco, CA"
    assert "mock_jd.html" in first_job.application_url
    assert "This is the job description." in first_job.jd_text
    assert first_job.source == "greenhouse"


@patch("src.scrapers.greenhouse_scraper.time.sleep")
@patch("src.scrapers.greenhouse_scraper.SessionLocal")
def test_greenhouse_scraper_listing_type(mock_session_local, mock_sleep):
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    scrape_greenhouse(GREENHOUSE_FIXTURE_URL, "job")

    jobs = [call_args[0][0] for call_args in mock_db.add.call_args_list]

    assert jobs[0].listing_type == "internship"
    assert jobs[1].listing_type == "job"
    assert jobs[2].listing_type == "internship"


@patch("src.scrapers.greenhouse_scraper.time.sleep")
@patch("src.scrapers.greenhouse_scraper.SessionLocal")
def test_greenhouse_scraper_empty_page(mock_session_local, mock_sleep):
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    scrape_greenhouse(EMPTY_FIXTURE_URL, "job")

    assert mock_db.add.call_count == 0


@patch("src.scrapers.generic_scraper.scrape_dynamic")
@patch("src.scrapers.generic_scraper.scrape_static")
@patch("src.scrapers.generic_scraper.is_page_dynamic")
def test_generic_scraper_routing(mock_is_dynamic, mock_scrape_static, mock_scrape_dynamic):
    from src.scrapers.generic_scraper import scrape_generic

    # Test static routing
    mock_is_dynamic.return_value = False
    scrape_generic("http://example.com", "job")
    mock_scrape_static.assert_called_once_with("http://example.com", "job")
    mock_scrape_dynamic.assert_not_called()

    mock_scrape_static.reset_mock()
    mock_scrape_dynamic.reset_mock()

    # Test dynamic routing
    mock_is_dynamic.return_value = True
    scrape_generic("http://example.com", "job")
    mock_scrape_dynamic.assert_called_once_with("http://example.com", "job")
    mock_scrape_static.assert_not_called()
