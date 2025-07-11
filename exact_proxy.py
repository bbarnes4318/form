from playwright.sync_api import sync_playwright

# Use the exact same proxy setup that works in your app
zip_code = "30303"
proxy_base_user = "b31f50d644ecaffc2993__cr.us"
proxy_user = f"{proxy_base_user};zip.{zip_code}"
proxy_password = "8cd531d71ea28e4f"
proxy_host = "gw.dataimpulse.com"
proxy_port = "823"

# Format proxy exactly as in your working app.py
proxy_url = f"http://{proxy_user}:{proxy_password}@{proxy_host}:{proxy_port}"

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        proxy={"server": proxy_url}
    )
    
    context = browser.new_context(viewport={"width": 1280, "height": 720})
    page = context.new_page()
    
    # Try a simple IP checking service
    page.goto("https://api.ipify.org")
    
    # Keep browser open until you press Enter
    input("Press Enter to close browser...")
