import logging
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

class CaptchaHandler:
    def __init__(self):
        pass

    def detect(self, application_url: str) -> bool:
        """
        Navigates to the url and attempts to detect common CAPTCHA elements.
        Returns True if a CAPTCHA is detected, False otherwise.
        """
        detected = False
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()

                logger.info(f"Checking for CAPTCHA at {application_url}")
                page.goto(application_url, wait_until="domcontentloaded")

                detected = self.detect_on_page(page)

                browser.close()
        except Exception as e:
            logger.error(f"Error while checking CAPTCHA: {e}")
            
        return detected
        
    def detect_on_page(self, page) -> bool:
        """
        Detect CAPTCHAs on an already open Playwright Page object.
        """
        # Common selectors for reCAPTCHA, hCaptcha, and Cloudflare Turnstile
        captcha_selectors = [
            "iframe[src*='recaptcha']",
            "iframe[src*='hcaptcha']",
            "iframe[src*='cf-turnstile']",
            ".g-recaptcha",
            ".h-captcha",
            ".cf-turnstile",
            "img[alt*='captcha' i]",
            "img[src*='captcha' i]"
        ]
        
        try:
            for selector in captcha_selectors:
                elements = page.locator(selector)
                if elements.count() > 0:
                    logger.warning(f"CAPTCHA detected via selector: {selector}")
                    return True
        except Exception as e:
            logger.debug(f"Error checking CAPTCHA selectors: {e}")
            
        return False
