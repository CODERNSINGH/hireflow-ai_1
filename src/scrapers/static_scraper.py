import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

def scrape_static(url: str, mode: str = "job"):
    """
    Scrapes a static HTML career page for job listings.
    """
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return []

    soup = BeautifulSoup(response.content, 'html.parser')
    
    jobs_data = []
    # Heuristic: Find all anchor tags that might be job postings
    job_keywords = ["engineer", "developer", "manager", "designer", "analyst", 
                   "intern", "associate", "director", "lead", "specialist", "scientist"]
    
    for a in soup.find_all('a', href=True):
        title = a.get_text(strip=True)
        href = a['href']
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
            
            # Simple deduplication based on URL
            if not any(j['application_url'] == full_url for j in jobs_data):
                jobs_data.append({
                    "role_title": title,
                    "application_url": full_url,
                    "location": "Unknown",
                    "listing_type": listing_type,
                })
            
    return jobs_data
