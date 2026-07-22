import argparse
import time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

from src.config.database import SessionLocal
from src.models.job import Job


def get_company_name(url):
    # e.g., https://boards.greenhouse.io/notion -> notion
    path = urlparse(url).path
    parts = [p for p in path.split("/") if p]
    if parts:
        return parts[0]
    return "Unknown"


def scrape_greenhouse(url: str, mode: str):
    company_name = get_company_name(url)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url)

        jobs_data = []

        while True:
            # Wait for openings to load, or proceed if empty
            try:
                page.wait_for_selector(".opening", timeout=10000)
            except Exception:
                pass

            openings = page.locator(".opening").all()

            for opening in openings:
                link_loc = opening.locator("a")
                if link_loc.count() == 0:
                    continue

                role_title = link_loc.first.inner_text().strip()
                application_url = link_loc.first.get_attribute("href")

                # Make application_url absolute if it's relative
                if application_url and application_url.startswith("/"):
                    parsed_url = urlparse(url)
                    application_url = (
                        f"{parsed_url.scheme}://{parsed_url.netloc}{application_url}"
                    )

                location_loc = opening.locator(".location")
                location = (
                    location_loc.first.inner_text().strip()
                    if location_loc.count() > 0
                    else None
                )

                listing_type = "internship" if "intern" in role_title.lower() else "job"

                jobs_data.append(
                    {
                        "role_title": role_title,
                        "application_url": application_url,
                        "location": location,
                        "listing_type": listing_type,
                    }
                )

            # Check for pagination (Next button)
            next_button = page.locator(
                "a:has-text('Next'), .next, .pagination-next"
            ).first
            if next_button.count() > 0 and next_button.is_visible():
                next_button.click()
                time.sleep(1)
            else:
                break

        db = SessionLocal()

        for job_data in jobs_data:
            if not job_data["application_url"]:
                continue

            # Rate limiting
            time.sleep(1)

            # Navigate to JD to get jd_text
            jd_text = ""
            try:
                page.goto(job_data["application_url"])
                try:
                    page.wait_for_selector("#content, body", timeout=5000)
                except Exception:
                    pass
                jd_text = page.locator("body").inner_text().strip()
            except Exception as e:
                print(f"Error extracting JD for {job_data['application_url']}: {e}")

            # Save to db
            job = Job(
                company_name=company_name,
                role_title=job_data["role_title"],
                jd_text=jd_text,
                location=job_data["location"],
                application_url=job_data["application_url"],
                source="greenhouse",
                listing_type=job_data["listing_type"],
            )
            db.add(job)

        db.commit()
        db.close()

        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Greenhouse careers page")
    parser.add_argument(
        "--url", required=True, help="URL of the Greenhouse company page"
    )
    parser.add_argument("--mode", default="job", help="Mode: job or internship")

    args = parser.parse_args()
    scrape_greenhouse(args.url, args.mode)
