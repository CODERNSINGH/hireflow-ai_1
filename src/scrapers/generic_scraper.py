import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

from src.scrapers.static_scraper import scrape_static


def is_page_dynamic(url: str) -> bool:
    """
    Detects if a page is likely JS-rendered (dynamic) vs static HTML.
    Returns True if dynamic, False if static.
    """
    try:
        # Use a user-agent to avoid being blocked by simple checks
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        # If we get a 403 or other error, it might be blocking basic requests; try dynamic scraper
        if response.status_code != 200:
            return True
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Check for common SPA mount points that might be mostly empty
        root_divs = soup.find_all('div', id=['root', 'app', '__next', 'application'])
        for div in root_divs:
            if len(div.get_text(strip=True)) < 50:
                return True
                
        # If the page has very few links, it might be dynamically rendering them
        links = soup.find_all('a')
        if len(links) < 3:
            return True
            
        # If there's very little text content overall, it's likely a JS shell
        text_content = soup.get_text(strip=True)
        if len(text_content) < 500:
            return True
            
        return False
    except Exception:
        # If request fails entirely (e.g. timeout, connection error), try dynamic as a fallback
        return True


def scrape_dynamic(url: str, mode: str = "job"):
    """
    Scrapes a dynamically rendered career page using Playwright.
    """
    jobs_data = []
    job_keywords = ["engineer", "developer", "manager", "designer", "analyst", 
                   "intern", "associate", "director", "lead", "specialist", "scientist"]
                   
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=15000)
            
            # Wait a little extra time for React/Vue to populate DOM
            page.wait_for_timeout(2000)
            
            links = page.locator("a").all()
            for a in links:
                try:
                    title = a.inner_text().strip()
                    href = a.get_attribute("href")
                except Exception:
                    continue
                    
                if not title or not href:
                    continue
                    
                title_lower = title.lower()
                is_job = any(keyword in title_lower for keyword in job_keywords)
                
                if is_job:
                    listing_type = "internship" if "intern" in title_lower else "job"
                    if mode == "internship" and listing_type != "internship":
                        continue
                    if mode == "job" and listing_type != "job":
                        continue
                        
                    full_url = urljoin(url, href)
                    
                    if not any(j['application_url'] == full_url for j in jobs_data):
                        jobs_data.append({
                            "role_title": title,
                            "application_url": full_url,
                            "location": "Unknown",
                            "listing_type": listing_type,
                        })
            browser.close()
    except Exception as e:
        print(f"Error scraping dynamic page {url}: {e}")
        
    return jobs_data


def scrape_generic(url: str, mode: str = "job"):
    """
    Auto-detects whether a page is static or JS-rendered and uses the appropriate parser.
    Returns a list of job listings.
    """
    if is_page_dynamic(url):
        return scrape_dynamic(url, mode)
    else:
        return scrape_static(url, mode)
