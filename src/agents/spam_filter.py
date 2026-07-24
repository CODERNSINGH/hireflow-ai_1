import re
import argparse
from typing import Dict, Any, List

from src.config.settings import get_settings
from src.config.database import SessionLocal
from src.models.job import Job

class SpamFilter:
    def __init__(self, threshold: float = None):
        if threshold is None:
            settings = get_settings()
            self.threshold = settings.SPAM_FILTER_THRESHOLD
        else:
            self.threshold = threshold

    def score(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scores a job listing for spam/quality.
        Expected keys in job_data: 'jd_text', 'company_name', 'skills_required'
        """
        confidence = 0.0
        reasons = []

        jd_text = job_data.get('jd_text', '')
        company_name = job_data.get('company_name', '')
        skills_required = job_data.get('skills_required', [])

        # 1. Missing company name
        if not company_name or str(company_name).strip() == '':
            confidence += 0.4
            reasons.append("Missing company name")

        # 2. JD under 50 words
        word_count = len(re.findall(r'\b\w+\b', jd_text)) if jd_text else 0
        if word_count < 50:
            confidence += 0.3
            reasons.append(f"JD under 50 words (count: {word_count})")

        # 3. No skills mentioned
        # skills_required could be a list, or comma separated string depending on caller
        # We assume caller parses it to a list or it's empty
        if not skills_required or len(skills_required) == 0:
            confidence += 0.2
            reasons.append("No skills mentioned")

        # 4. Unrealistic salary claims or spammy keywords
        spammy_keywords = [
            'rockstar ninja', 'get rich quick', 'earn millions', 
            'great pay', 'ninja developer', 'rockstar'
        ]
        if jd_text:
            jd_lower = jd_text.lower()
            for kw in spammy_keywords:
                if kw in jd_lower:
                    confidence += 0.3
                    reasons.append(f"Spammy keyword found: '{kw}'")
                    break  # Apply this penalty at most once

        # Check for unrealistic salary (e.g. $1,000,000 or $1M+)
        if jd_text:
            jd_lower = jd_text.lower()
            if re.search(r'\$\s*\d{1,3}(,\d{3}){2,}', jd_lower) or re.search(r'\$\s*\d+\s*(million|m)\b', jd_lower):
                confidence += 0.4
                reasons.append("Unrealistic salary claim found")

        # Cap confidence at 1.0
        confidence = min(confidence, 1.0)

        return {
            'is_spam': confidence >= self.threshold,
            'spam_confidence': round(confidence, 2),
            'reasons': reasons
        }


def run_spam_filter():
    """
    Runs the spam filter against all jobs currently in the database.
    Updates the is_spam and spam_confidence fields.
    """
    db = SessionLocal()
    try:
        jobs = db.query(Job).all()
        sf = SpamFilter()
        updated = 0
        
        for job in jobs:
            # Parse skills_required which is stored as a string in DB
            skills = []
            if job.skills_required:
                skills = [s.strip() for s in str(job.skills_required).split(',')]

            data = {
                'jd_text': job.jd_text or '',
                'company_name': job.company_name or '',
                'skills_required': skills
            }
            
            result = sf.score(data)
            
            job.is_spam = result['is_spam']
            job.spam_confidence = result['spam_confidence']
            updated += 1
            
        db.commit()
        print(f"Successfully scored {updated} jobs for spam.")
    except Exception as e:
        db.rollback()
        print(f"Error running spam filter: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run spam filter against all jobs in DB")
    parser.add_argument("--run", action="store_true", help="Score all jobs in the database")
    args = parser.parse_args()

    if args.run:
        run_spam_filter()
