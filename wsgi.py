import os
import subprocess
import logging
from app import app

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Check if Playwright browser is installed
try:
    import playwright
    from playwright.sync_api import sync_playwright
    
    # Try to get browser installation status
    installed = False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            browser.close()
            installed = True
    except Exception as e:
        logger.error(f"Browser not installed: {str(e)}")
        installed = False
    
    # Install if not installed
    if not installed:
        logger.info("Installing Playwright browser...")
        subprocess.run(["playwright", "install", "chromium", "--with-deps"], check=True)
        logger.info("Playwright browser installed successfully.")
except Exception as e:
    logger.error(f"Error setting up Playwright: {str(e)}")

# This is the WSGI entry point
if __name__ == "__main__":
    app.run() 