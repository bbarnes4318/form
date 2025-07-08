from playwright.sync_api import sync_playwright

# Change this zip code to target different locations
zip_code = "30303"

with sync_playwright() as p:
    # Launch with additional parameters to help with stability
    browser = p.chromium.launch(
        headless=False,
        proxy={
            "server": "http://gw.dataimpulse.com:823",
            "username": f"b31f50d644ecaffc2993__cr.us;zip.30307",
            "password": "8cd531d71ea28e4f"
        },
        args=[
            '--disable-extensions',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--disable-gpu'
        ]
    )
    
    # Increase timeouts for slower residential connections
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
    )
    
    page = context.new_page()
    
    # Increase navigation timeout for slow proxy
    page.set_default_navigation_timeout(60000)  # 60 seconds
    
    # Start with a simple page to verify connection
    page.goto("https://api.ipify.org")
    
    print("IP verified. Now try browsing to other sites.")
    input("Press Enter to close browser...")