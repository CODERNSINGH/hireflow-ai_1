import pytest
from src.agents.spam_filter import SpamFilter

@pytest.fixture
def spam_filter():
    return SpamFilter(threshold=0.7)

def test_legitimate_sparse_jd_passes(spam_filter):
    """Test with a legitimate sparse listing (e.g. 3-person startup posting their first internship)."""
    job_data = {
        'jd_text': 'Looking for a Python intern to help build our data pipeline.',
        'company_name': 'DataFlow Labs',
        'skills_required': ['Python']
    }
    result = spam_filter.score(job_data)
    
    # Missing company = 0, < 50 words = 0.3, skills missing = 0, spammy = 0. Total = 0.3
    assert result['is_spam'] is False
    assert result['spam_confidence'] == 0.3

def test_legitimate_standard_jd_passes(spam_filter):
    """Test with a standard, well-written job description."""
    jd_text = "We are looking for a talented software engineer to join our growing team. " * 10
    job_data = {
        'jd_text': jd_text,
        'company_name': 'Tech Growth Corp',
        'skills_required': ['Python', 'Django', 'AWS']
    }
    result = spam_filter.score(job_data)
    
    # Missing company = 0, < 50 words = 0 (100 words), skills missing = 0, spammy = 0. Total = 0.0
    assert result['is_spam'] is False
    assert result['spam_confidence'] == 0.0

def test_spam_missing_company_and_short_jd(spam_filter):
    """Test spam listing with no company name, short JD, and no skills."""
    job_data = {
        'jd_text': 'Looking for someone to help with a project. DM me.',
        'company_name': '',
        'skills_required': []
    }
    result = spam_filter.score(job_data)
    
    # Missing company = 0.4, < 50 words = 0.3, skills missing = 0.2. Total = 0.9
    assert result['is_spam'] is True
    assert result['spam_confidence'] == 0.9

def test_spam_with_spammy_keywords(spam_filter):
    """Test spam listing with spammy keywords."""
    job_data = {
        'jd_text': 'We need a rockstar ninja developer. Great pay. Must be passionate.',
        'company_name': '',
        'skills_required': []
    }
    result = spam_filter.score(job_data)
    
    # Missing company = 0.4, < 50 words = 0.3, skills missing = 0.2, spammy kw = 0.3. Total = 1.2 -> capped at 1.0
    assert result['is_spam'] is True
    assert result['spam_confidence'] == 1.0

def test_spam_unrealistic_salary(spam_filter):
    """Test spam listing with unrealistic salary claims."""
    job_data = {
        'jd_text': 'Join our team and make $1,000,000 in your first month! This is a great opportunity.',
        'company_name': 'GetRichQuick LLC',
        'skills_required': ['Sales']
    }
    result = spam_filter.score(job_data)
    
    # Missing company = 0, < 50 words = 0.3, skills missing = 0, realistic salary/spam kw = 0.4. Total = 0.7
    assert result['is_spam'] is True
    assert result['spam_confidence'] >= 0.7
