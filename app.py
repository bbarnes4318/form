import os
import time
import logging
from flask import Flask, render_template, request, flash, get_flashed_messages, jsonify, send_from_directory, send_file
from playwright.sync_api import sync_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- Configuration ---

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set Playwright environment variables for cloud deployment
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'  # Use browsers from system path
os.environ['PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD'] = '1'  # Skip browser download
os.environ['PLAYWRIGHT_SKIP_VALIDATION'] = '1'  # Skip browser validation

# Load environment variables
load_dotenv()

# Create Flask app configured to serve React build files
app = Flask(__name__, static_folder='../web/dist', static_url_path='')
# IMPORTANT: Set a strong secret key in your environment variables for production!
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'change-this-in-production-to-a-real-secret')

# Initialize zip code search engine (globally is fine)
search = None
try:
    from uszipcode import SearchEngine
    search = SearchEngine()
    logger.info("uszipcode SearchEngine initialized.")
except Exception as e:
    logger.error(f"Failed to initialize or import uszipcode SearchEngine: {e}. Nearby zip code search will be disabled.")
    search = None # Set search to None if initialization fails

# Proxy configuration from environment variables
PROXY_HOST = os.environ.get('PROXY_HOST')
PROXY_PORT = os.environ.get('PROXY_PORT')
PROXY_BASE_USER = os.environ.get('PROXY_BASE_USER') # e.g., user__cr.us
PROXY_PASS = os.environ.get('PROXY_PASS')

# Check if proxy configuration is complete
PROXY_CONFIGURED = all([PROXY_HOST, PROXY_PORT, PROXY_BASE_USER, PROXY_PASS])

if not PROXY_CONFIGURED:
    logger.warning("--- PROXY WARNING ---")
    logger.warning("Incomplete proxy configuration environment variables.")
    logger.warning("Missing: " + ", ".join([var for var, val in {
        'PROXY_HOST': PROXY_HOST, 'PROXY_PORT': PROXY_PORT,
        'PROXY_BASE_USER': PROXY_BASE_USER, 'PROXY_PASS': PROXY_PASS
         }.items() if not val]))
    logger.warning("Application will attempt to run WITHOUT proxies.")
    logger.warning("--- END PROXY WARNING ---")

# --- Status Code Constants ---
STATUS_SUCCESS = 'SUCCESS'
STATUS_PROXY_CONNECT_FAIL = 'PROXY_CONNECT_FAIL'
STATUS_NAVIGATION_FAIL = 'NAVIGATION_FAIL'
STATUS_AUTOMATION_FAIL = 'AUTOMATION_FAIL'
STATUS_UNKNOWN_FAIL = 'UNKNOWN_FAIL'

# --- Email Functions ---
def send_email_notification(prospect_data, proxy_ip=None):
    """Send email notification for new lead submission"""
    try:
        # Get email credentials
        email_user = os.environ.get('EMAIL_USER')
        email_pass = os.environ.get('EMAIL_PASS')
        
        if not email_user or not email_pass:
            logger.warning("Email credentials not configured, skipping email notification")
            return False
            
        timestamp = datetime.now().isoformat()
        
        # Create message
        msg = MIMEMultipart()
        msg['From'] = email_user
        msg['To'] = 'jimbosky35@gmail.com'
        msg['Subject'] = 'New Fair Wreck Lead'
        
        # HTML body
        html_body = f"""
        <h2>New Lead Submission</h2>
        <ul>
          <li><b>Name:</b> {prospect_data.get('name', '')}</li>
          <li><b>Email:</b> {prospect_data.get('email', '')}</li>
          <li><b>Phone:</b> {prospect_data.get('phone', '')}</li>
          <li><b>Case:</b> {prospect_data.get('case', '')}</li>
          <li><b>TCPA Consent:</b> {'Yes' if prospect_data.get('tcpaconsent') else 'No'}</li>
          <li><b>TrustedForm Certificate URL:</b> <a href="{prospect_data.get('xxTrustedFormCertUrl', '')}">{prospect_data.get('xxTrustedFormCertUrl', '')}</a></li>
          <li><b>Proxy IP:</b> {proxy_ip or 'No proxy available'}</li>
        </ul>
        <p>Timestamp: {timestamp}</p>
        """
        
        msg.attach(MIMEText(html_body, 'html'))
        
        # Send email
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(email_user, email_pass)
        text = msg.as_string()
        server.sendmail(email_user, 'jimbosky35@gmail.com', text)
        server.quit()
        
        logger.info("Email notification sent successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email notification: {e}")
        return False

def get_proxy_for_phone(phone):
    """Get proxy configuration based on phone area code"""
    try:
        # Extract area code from phone number
        area_code = ''.join(filter(str.isdigit, phone))[:3]
        
        if not PROXY_CONFIGURED:
            return None
            
        proxy_user = f"{PROXY_BASE_USER};zip.{area_code}"
        
        return {
            'host': PROXY_HOST,
            'port': PROXY_PORT,
            'user': proxy_user,
            'pass': PROXY_PASS
        }
    except Exception as e:
        logger.error(f"Error getting proxy for phone {phone}: {e}")
        return None

# --- Helper Functions ---

def get_nearby_zip_codes(target_zip, radius_miles=10, max_results=5):
    """
    Get nearby zip codes within a specified radius using uszipcode.
    Args:
        target_zip (str): The target zip code.
        radius_miles (int): Radius in miles to search.
        max_results (int): Maximum number of nearby zips to return.
    Returns:
        list: List of nearby zip code strings, excluding the target zip, sorted by distance.
    """
    if not search:
        logger.error("uszipcode search engine not available.")
        return []
    try:
        # 1. Find the coordinates of the target zip code first
        target_zip_obj = search.by_zipcode(target_zip)
        if not target_zip_obj:
            logger.warning(f"Could not find coordinates for target zip code {target_zip}.")
            return [] # Cannot search by coordinates if target isn't found

        target_lat = target_zip_obj.lat
        target_lng = target_zip_obj.lng

        # Check if coordinates were actually found
        if target_lat is None or target_lng is None:
             logger.warning(f"Coordinates are missing for target zip code {target_zip} in the database.")
             return []

        # 2. Search by coordinates using the found lat/lon and the desired radius
        #    Request more than max_results initially because the list includes the target zip itself.
        #    The results from by_coordinates are sorted by distance.
        nearby_results = search.by_coordinates(
            target_lat,
            target_lng,
            radius=radius_miles,
            returns=max_results + 10 # Get extra to allow filtering target zip
        )

        if not nearby_results:
            logger.info(f"No zip codes found within {radius_miles} miles of {target_zip} coordinates.")
            return []

        # 3. Process results: Extract zip codes, filter out the original target, limit count
        zip_codes = []
        count = 0
        for z in nearby_results:
            # Ensure the result object has a valid zipcode attribute and it's not None
            if hasattr(z, 'zipcode') and z.zipcode is not None:
                 zip_str = str(z.zipcode)
                 # Exclude the original target zip code
                 if zip_str != str(target_zip):
                     zip_codes.append(zip_str)
                     count += 1
                     if count >= max_results:
                         break # Stop once we have enough neighbors
            else:
                 # Log if a result object is missing the zipcode attribute
                 logger.warning(f"Found nearby result object without a valid zipcode attribute: {z}")


        logger.info(f"Found {len(zip_codes)} nearby zip codes for {target_zip} within {radius_miles} miles: {zip_codes}")
        return zip_codes

    except Exception as e:
        # Catch other potential errors during lookup
        logger.error(f"Error finding nearby zip codes for {target_zip} (radius {radius_miles}): {str(e)}", exc_info=True)
        return []

# (Place near top of file, after imports/config)
SITE_CONFIG = {
    'elderlyhealth': {
        'url': 'https://elderlyhealthquotes.com/medicareplans/',
        'selectors': {
            'lead_id_field': 'input[name="universal_leadid"]',
            'full_name': 'input[name="fname"]',
            'phone': 'input[name="phoneno"]',
            'zip': 'input[name="zipcode"]',
            'consent': '#leadid_tcpa_disclosure',
            'submit_button': 'input[name="finish"]'
        }
    },
    'seniorsinsurance': {
        'url': 'https://seniorsinsurancequotes.com/',
        'selectors': {
            'lead_id_field': 'input[name="universal_leadid"]',
            'full_name': 'input[name="fname"]',
            'phone': 'input[name="phoneno"]',
            'zip': 'input[name="zipcode"]',
            'consent': '#leadid_tcpa_disclosure',
            'submit_button': 'button[type="submit"][name="finish"]'
        }
    }
}

def submit_to_external_form_pw(prospect_data, target_site_key, dynamic_proxy_details=None):
    """
    Submits prospect data using Playwright to the specified target site.
    Args:
        prospect_data (dict): Contains 'full_name', 'phone', 'zip'.
        target_site_key (str): The key identifying the target site (e.g., 'elderlyhealth').
        dynamic_proxy_details (dict): Proxy config or None.
    Returns:
        tuple: (status_code, message_string, captured_lead_id or None)
    """
    # --- Get site config based on key ---
    if target_site_key not in SITE_CONFIG:
        logger.error(f"Invalid target_site_key passed: {target_site_key}")
        return STATUS_UNKNOWN_FAIL, f"Invalid target site key: {target_site_key}", None

    site_info = SITE_CONFIG[target_site_key]
    target_url = site_info['url']
    selectors = site_info['selectors'] # Get the correct selectors dict
    logger.info(f"Targeting site '{target_site_key}' at URL: {target_url}")

    # --- Initialize variables ---
    browser = None
    context = None
    page = None
    lead_id = None # Initialize lead_id here

    # --- Main Try Block ---
    try: # <-- Start of main try block (Level 1 Indent)
        with sync_playwright() as p:
            # --- 1. Configure Proxy ---
            proxy_options = None
            if dynamic_proxy_details:
                proxy_options = {
                    'server': f"http://{dynamic_proxy_details['host']}:{dynamic_proxy_details['port']}",
                    'username': dynamic_proxy_details['user'],
                    'password': dynamic_proxy_details['pass']
                }
                logger.info(f"Attempting connection via proxy: {proxy_options['server']} User: {proxy_options['username']}")
            else:
                logger.info("Attempting connection without proxy.")

            # Launch browser with retry logic
            max_retries = 3
            retry_count = 0
            last_error = None
            
            while retry_count < max_retries:
                try:
                    # Try launching with default args first
                    browser_launch_args = {
                        'headless': False,
                        'args': [
                            '--no-sandbox',
                            '--disable-setuid-sandbox',
                            '--disable-dev-shm-usage',
                            '--disable-gpu'
                        ]
                    }
                    
                    if dynamic_proxy_details:
                        # Format proxy URL with http:// prefix for Playwright
                        proxy_url = f"http://{dynamic_proxy_details['user']}:{dynamic_proxy_details['pass']}@{dynamic_proxy_details['host']}:{dynamic_proxy_details['port']}"
                        browser_launch_args['proxy'] = {
                            'server': proxy_url
                        }
                        
                    browser = p.chromium.launch(**browser_launch_args)
                    break
                except Exception as e:
                    retry_count += 1
                    last_error = str(e)
                    logger.error(f"Browser launch attempt {retry_count} failed: {last_error}")
                    
                    if "executable doesn't exist" in last_error.lower():
                        logger.info("Browser executable not found. Attempting to install...")
                        try:
                            import subprocess
                            subprocess.run(["playwright", "install", "chromium", "--with-deps"], check=True)
                            logger.info("Browser installed. Retrying...")
                            continue
                        except Exception as install_error:
                            logger.error(f"Failed to install browser: {str(install_error)}")
                    
                    if retry_count == max_retries:
                        if "EPIPE" in last_error:
                            return STATUS_PROXY_CONNECT_FAIL, "Proxy connection failed - broken pipe", None
                        elif "ERR_PROXY_CONNECTION_FAILED" in last_error:
                            return STATUS_PROXY_CONNECT_FAIL, "Proxy connection failed", None
                        elif "timeout" in last_error.lower():
                            return STATUS_PROXY_CONNECT_FAIL, "Proxy connection timeout", None
                        elif "executable doesn't exist" in last_error.lower():
                            return STATUS_UNKNOWN_FAIL, "Browser executable not found", None
                        else:
                            return STATUS_UNKNOWN_FAIL, f"Browser launch failed: {last_error}", None
                    
                    time.sleep(2)  # Wait before retrying

            # --- 2. Launch Browser ---
            try: # Level 3 Indent
                # Try launching with default args first
                browser_launch_args = {
                    'headless': False,
                    'args': [
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu'
                    ]
                }

                if proxy_options:
                    browser_launch_args['proxy'] = proxy_options

                browser = p.chromium.launch(**browser_launch_args)
                logger.info("Browser launched successfully (non-headless).")

            except PlaywrightError as launch_err:
                logger.error(f"Browser launch failed: {launch_err}")
                err_str = str(launch_err).lower()
                if "protocol error" in err_str or "browser has disconnected" in err_str or "cannot connect" in err_str:
                     return STATUS_AUTOMATION_FAIL, f"Non-headless launch failed (check environment/Xvfb): {launch_err}", None
                elif "proxy" in err_str or "tunnel" in err_str or "epipe" in err_str or "timeout" in err_str:
                     return STATUS_PROXY_CONNECT_FAIL, f"Proxy launch failed: {launch_err}", None
                else:
                     return STATUS_UNKNOWN_FAIL, f"Browser launch failed: {launch_err}", None

            # --- 3. Create Context and Page ---
            try: # Level 3 Indent
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1280, 'height': 720}
                )
                page = context.new_page()
                logger.info("Browser context and page created.")
            except PlaywrightError as context_err:
                 logger.error(f"Failed to create browser context/page: {context_err}")
                 if browser:
                     try: browser.close()
                     except: pass
                 return STATUS_AUTOMATION_FAIL, f"Context creation failed: {context_err}", None

            # --- 4. Verify Proxy (Optional but Recommended) ---
            if proxy_options:
                try:
                    logger.info("Verifying proxy connection via ipify.org...")
                    page.goto('https://api.ipify.org/', timeout=30000)
                    ip_address = page.locator('pre').text_content(timeout=5000)
                    logger.info(f"Proxy verification successful. IP: {ip_address}")
                except PlaywrightError as verify_err:
                    logger.error(f"Proxy verification failed: {verify_err}")
                    err_str = str(verify_err).lower()
                    if "proxy" in err_str or "tunnel" in err_str or "epipe" in err_str or "timeout" in err_str:
                        return STATUS_PROXY_CONNECT_FAIL, f"Proxy verification failed: {verify_err}", None
                    else:
                        return STATUS_NAVIGATION_FAIL, f"Proxy verification navigation failed: {verify_err}", None
                # Removed general exception catch here

            # --- 5. Navigate to Target Form ---
            try:
                logger.info(f"Navigating to target page: {target_url}...")
                page.goto(target_url, wait_until='domcontentloaded', timeout=60000)
                logger.info("DOM loaded. Waiting for page load event...")
                page.wait_for_load_state('load', timeout=30000)
                logger.info("Load event fired.")
                try:
                    # Increase network idle timeout, but don't fail immediately if it times out
                    page.wait_for_load_state('networkidle', timeout=45000)
                    logger.info("Network is idle.")
                except PlaywrightTimeoutError:
                    logger.warning("Timed out waiting for network idle. Proceeding anyway...")
                logger.info("Navigation and waits complete.")
            except (PlaywrightError, Exception) as nav_err:
                logger.error(f"Navigation to {target_url} failed: {nav_err}")
                # Determine if it's proxy or navigation fail based on context if possible
                return STATUS_NAVIGATION_FAIL, f"Navigation failed: {nav_err}", None

            # --- 6. Wait for Essential Form Elements --- (USING DYNAMIC SELECTORS)
            try:
                logger.info("Waiting for essential form elements to be ready...")
                # Wait for a key element like the submit button using the site-specific selector
                page.locator(selectors['submit_button']).wait_for(state='visible', timeout=20000) # Increased timeout
                logger.info("Form elements seem ready.")
            except PlaywrightTimeoutError as wait_err:
                 logger.error(f"Timed out waiting for essential form elements: {wait_err}")
                 try: page.screenshot(path='form_elements_timeout.png') # Screenshot on failure
                 except: pass
                 return STATUS_AUTOMATION_FAIL, f"Page did not load required form elements: {wait_err}", None

            # --- 7. Extract Lead ID (USING DYNAMIC SELECTOR) ---
            try:
                logger.info("Confirming lead ID field exists...")
                page.locator(selectors['lead_id_field']).wait_for(state='attached', timeout=5000) # Just check existence
                logger.info("Lead ID input field found.")
            except PlaywrightTimeoutError as lead_wait_err:
                 logger.warning(f"Could not find Lead ID field ({selectors['lead_id_field']}) within timeout: {lead_wait_err}")
                 # Don't fail here, maybe it appears later or isn't needed
                 pass # Continue without failing

            # --- 8. Fill Form --- (USING DYNAMIC SELECTORS)
            try:
                logger.info(f"Filling form with data: {prospect_data['full_name']}, {prospect_data['phone']}, {prospect_data['zip']}")
                page.locator(selectors['full_name']).fill(prospect_data['full_name'])
                page.locator(selectors['phone']).fill(prospect_data['phone'])
                page.locator(selectors['zip']).fill(prospect_data['zip'])
                logger.info("Form fields filled.")
            except PlaywrightError as fill_err:
                 logger.error(f"Failed to fill form field: {fill_err}")
                 return STATUS_AUTOMATION_FAIL, f"Failed to fill form field: {fill_err}", None

            # --- 9. Check Consent Box --- (USING DYNAMIC SELECTOR)
            try:
                logger.info("Checking consent box...")
                consent_locator = page.locator(selectors['consent'])
                consent_locator.wait_for(state='visible', timeout=5000)
                consent_locator.check()
                logger.info("Consent box checked.")
            except PlaywrightTimeoutError:
                 logger.warning(f"Consent box ({selectors['consent']}) not found or visible within timeout.")
                 # Decide if this is critical. For now, we warn and continue.
                 pass
            except PlaywrightError as consent_err:
                 logger.error(f"Failed to check consent box: {consent_err}")
                 return STATUS_AUTOMATION_FAIL, f"Failed to check consent box: {consent_err}", None

            # --- 10. Extract Lead ID (Immediately Before Submit) --- (USING DYNAMIC SELECTOR)
            lead_id = None # Initialize before try
            try:
                logger.info("Extracting final Lead ID just before submit...")
                lead_id_locator = page.locator(selectors['lead_id_field'])
                if lead_id_locator.count() > 0:
                     lead_id = lead_id_locator.input_value(timeout=5000)
                     if lead_id:
                         logger.info(f"Lead ID extracted just before submit: {lead_id}")
                     else:
                         logger.warning("Lead ID field found but value is empty.")
                else:
                    logger.warning("Lead ID field not present when trying to read value.")
            except PlaywrightError as lead_err:
                 logger.error(f"Could not extract Lead ID before submit: {lead_err}")
                 # Don't fail here, just log it. lead_id remains None.

            # --- 11. Click Submit Button --- (USING DYNAMIC SELECTOR)
            try:
                logger.info("Attempting to click submit button...")
                submit_button = page.locator(selectors['submit_button'])
                if not submit_button.is_visible():
                    logger.warning("Submit button not immediately visible, waiting...")
                    submit_button.wait_for(state='visible', timeout=10000)

                if not submit_button.is_enabled():
                    logger.warning("Submit button not enabled, waiting...")
                    # Wait for button to potentially become enabled (adjust timeout as needed)
                    # This is tricky, maybe a specific condition is better if known
                    try:
                        page.wait_for_function("() => document.querySelector('{}').disabled === false".format(selectors['submit_button']), timeout=5000)
                    except PlaywrightTimeoutError:
                        logger.error("Submit button did not become enabled.")
                        raise Exception("Submit button did not become enabled.")

                logger.info("Waiting for 1 second before clicking submit...") # Small delay
                time.sleep(1)

                logger.info("Executing click action on submit button...")
                submit_button.click()
                logger.info("Submit button clicked successfully.")

                # --- SUCCESS Condition --- 
                # If click succeeded AND we have a lead_id, consider it successful immediately.
                if lead_id:
                    logger.info(f"Form submission considered successful with Lead ID: {lead_id}")
                    return STATUS_SUCCESS, f"Form submitted successfully with Lead ID: {lead_id}", lead_id
                else:
                    # This case shouldn't happen if lead ID extraction is mandatory, but as a fallback:
                    logger.warning("Submit clicked, but no Lead ID was captured earlier.")
                    return STATUS_SUCCESS, "Form submitted, but Lead ID was not captured.", None

            except PlaywrightTimeoutError as submit_timeout_err:
                logger.error(f"Timeout interacting with submit button: {submit_timeout_err}")
                return STATUS_AUTOMATION_FAIL, f"Timeout clicking submit: {submit_timeout_err}", lead_id # Return ID if captured
            except Exception as general_submit_err:
                 # Catch any other errors during submit interaction
                 logger.error(f"An unexpected error occurred clicking submit: {general_submit_err}")
                 return STATUS_UNKNOWN_FAIL, f"Unexpected Submit Click error: {general_submit_err}", lead_id # Return ID if captured

            # Wait for submission to complete
            try:
                page.wait_for_load_state('networkidle', timeout=30000)
                logger.info("Page loaded after submission")
            except PlaywrightError as e:
                error_msg = str(e)
                logger.error(f"Failed to wait for submission completion: {error_msg}")
                return STATUS_AUTOMATION_FAIL, f"Submission completion wait failed: {error_msg}", None
            
            # Check for success - we consider it successful if we:
            # 1. Successfully submitted the form
            # 2. Have a valid lead ID
            # 3. The page loaded after submission
            if lead_id:
                logger.info(f"Form submission considered successful with Lead ID: {lead_id}")
                return STATUS_SUCCESS, f"Form submitted successfully with Lead ID: {lead_id}", lead_id
            
            # If no lead ID but we got this far, still consider it potentially successful
            logger.info("Form submission likely successful but no lead ID found")
            return STATUS_SUCCESS, "Form likely submitted successfully but no lead ID found", None

        # --- End of 'with sync_playwright()' block ---

    except Exception as e: # <-- Start of main outer EXCEPT block (Level 1 Indent)
        # Catch any unexpected errors not caught by specific PlaywrightError handlers above
        logger.error(f"An unexpected error occurred in Playwright function: {e}", exc_info=True)
        # Ensure lead_id is returned if it was captured before the error
        return STATUS_UNKNOWN_FAIL, f"Unexpected error: {e}", lead_id

    finally: # <-- FINALLY block associated with main outer TRY (Level 1 Indent)
        # Ensure browser resources are closed even if errors occurred (outside the 'with' block, unlikely needed)
        if context:
            try:
                context.close()
                logger.info("Playwright context closed in finally.")
            except Exception as e:
                logger.error(f"Error closing context in finally: {e}")
        if browser:
            try:
                browser.close()
                logger.info("Playwright browser closed in finally.")
            except Exception as e:
                logger.error(f"Error closing browser in finally: {e}")
        logger.info("Playwright browser resources cleanup attempted in finally.")
    # --- End of function ---

def submit_fallback_test_mode(prospect_data, dynamic_proxy_details=None):
    """
    Fallback function for testing when Playwright browser isn't available.
    This simulates a successful form submission for testing purposes.
    
    Args:
        Same as submit_to_external_form_pw
    Returns:
        Same tuple format as submit_to_external_form_pw
    """
    logger.warning("USING TEST MODE SUBMISSION - NO ACTUAL FORM SUBMISSION IS HAPPENING")
    # Log the data and proxy details
    logger.info(f"Test submission with data: {prospect_data}")
    if dynamic_proxy_details:
        # Log censored proxy details
        censored_proxy = {
            'host': dynamic_proxy_details['host'],
            'port': dynamic_proxy_details['port'],
            'user': dynamic_proxy_details['user'],
            'pass': '********'
        }
        logger.info(f"Test proxy details: {censored_proxy}")
    
    # Generate a fake lead ID
    import uuid
    import time
    lead_id = str(uuid.uuid4())
    
    # Simulate some processing time
    time.sleep(1)
    
    # Return success with the generated lead ID
    return STATUS_SUCCESS, f"TEST MODE: Form submission simulated successfully with Lead ID: {lead_id}", lead_id

def submit_to_ringba(prospect_data):
    """
    Submits prospect data to multiple Ringba enrichment endpoints.
    
    Args:
        prospect_data (dict): Dictionary containing form data with keys:
            - first_name
            - last_name
            - phone
            - state
            - zip
            - age
    
    Returns:
        tuple: (status_code, message)
    """
    try:
        # Format phone number to E.164 format
        phone = prospect_data['phone']
        if not phone.startswith('+1'):
            # Remove any non-digit characters and add +1 prefix
            phone = '+1' + ''.join(filter(str.isdigit, phone))
        
        # List of all Ringba URLs
        ringba_urls = [
            "https://display.ringba.com/enrich/2678526310963217804",  # Original URL
            "https://display.ringba.com/enrich/2665437287541638739",  # New URL 1
            "https://display.ringba.com/enrich/2447044488598652647",  # New URL 2
            "https://display.ringba.com/enrich/2679325464287250184"   # New URL 3
        ]
        
        # Common parameters for all requests
        params = {
            'callerid': phone,
            'first_name': prospect_data['first_name'],
            'last_name': prospect_data['last_name'],
            'age': prospect_data['age'],
            'state': prospect_data['state'],
            'zip': prospect_data['zip'],
            'webhook_url': 'YOUR_GOOGLE_APPS_SCRIPT_URL'  # Add your Google Apps Script web app URL here
        }
        
        # Make requests to all Ringba URLs
        import requests
        success_count = 0
        failed_urls = []
        
        for url in ringba_urls:
            try:
                response = requests.get(url, params=params)
                if response.status_code == 200:
                    success_count += 1
                    logger.info(f"Successfully submitted to Ringba URL: {url}")
                else:
                    failed_urls.append(url)
                    logger.error(f"Failed to submit to Ringba URL {url}. Status code: {response.status_code}")
            except Exception as e:
                failed_urls.append(url)
                logger.error(f"Error submitting to Ringba URL {url}: {str(e)}")
        
        # Return status based on overall results
        if success_count == len(ringba_urls):
            return STATUS_SUCCESS, "Data successfully submitted to all Ringba endpoints"
        elif success_count > 0:
            return STATUS_SUCCESS, f"Data submitted to {success_count}/{len(ringba_urls)} Ringba endpoints"
        else:
            return STATUS_UNKNOWN_FAIL, f"Failed to submit to any Ringba endpoints"
            
    except Exception as e:
        logger.error(f"Error in submit_to_ringba: {e}")
        return STATUS_UNKNOWN_FAIL, f"Error submitting to Ringba: {str(e)}"

# --- API Routes ---
@app.route('/api/submit', methods=['POST', 'OPTIONS'])
def api_submit():
    """API endpoint for React frontend form submissions"""
    # Handle CORS preflight requests
    if request.method == 'OPTIONS':
        response = jsonify({})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization, Accept, X-Requested-With')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS, GET')
        return response
    
    try:
        # Get JSON data from request
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
            
        # Extract form data
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        case_desc = data.get('case', '').strip()
        trusted_form_cert_url = data.get('xxTrustedFormCertUrl', '')
        tcpa_consent = data.get('tcpaconsent', False)
        
        # Basic validation
        if not all([name, email, phone, case_desc]):
            return jsonify({'success': False, 'error': 'All fields are required'}), 400
        
        timestamp = datetime.now().isoformat()
        logger.info(f"{timestamp} - API POST /api/submit from React frontend")
        logger.info(f"Form submission: {name}, {email}, {phone}")
        
        # Get proxy details for area code
        proxy_details = get_proxy_for_phone(phone)
        proxy_ip = f"{proxy_details['host']}:{proxy_details['port']}" if proxy_details else 'No proxy available'
        
        # Prepare prospect data for email
        prospect_data = {
            'name': name,
            'email': email,
            'phone': phone,
            'case': case_desc,
            'xxTrustedFormCertUrl': trusted_form_cert_url,
            'tcpaconsent': tcpa_consent
        }
        
        # Send email notification
        email_sent = send_email_notification(prospect_data, proxy_ip)
        
        if email_sent:
            logger.info("Lead submission processed successfully")
            response = jsonify({'success': True, 'proxyIP': proxy_ip})
        else:
            logger.warning("Email sending failed, but submission received")
            response = jsonify({'success': True, 'proxyIP': proxy_ip, 'warning': 'Email notification failed'})
        
        # Add CORS headers
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        
        return response
        
    except Exception as e:
        logger.error(f"Error processing API submission: {e}")
        response = jsonify({'success': False, 'error': 'Internal server error'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500

# --- Static File Routes for React App ---
@app.route('/')
@app.route('/privacy')
@app.route('/terms')
def serve_react_app():
    """Serve the React application for frontend routes"""
    try:
        return send_file('../web/dist/index.html')
    except FileNotFoundError:
        # Fallback to old form if React build doesn't exist yet
        return render_template('form.html')

@app.route('/assets/<path:filename>')
def serve_react_assets(filename):
    """Serve React build assets (CSS, JS, etc.)"""
    return send_from_directory('../web/dist/assets', filename)

# --- Legacy Form Routes (keeping for backward compatibility) ---
@app.route('/form')
def legacy_form():
    """Legacy form route"""
    return render_template('form.html')

@app.route('/final-expense', methods=['GET', 'POST'])
def final_expense():
    # Force template reload by adding a timestamp parameter
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    
    if request.method == 'POST':
        # Get form data
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        phone = request.form.get('phone')
        state = request.form.get('state')
        zip_code = request.form.get('zip')
        age = request.form.get('age')
        
        # Basic validation
        if not all([first_name, last_name, phone, state, zip_code, age]):
            flash('Please fill in all required fields', 'error')
            return render_template('final_expense_landing.html', timestamp=timestamp)
        
        # Validate zip code format
        if not zip_code.isdigit() or len(zip_code) != 5:
            flash('Please enter a valid 5-digit zip code', 'error')
            return render_template('final_expense_landing.html', timestamp=timestamp)
        
        # Validate phone number format
        phone_digits = ''.join(filter(str.isdigit, phone))
        if len(phone_digits) != 10:
            flash('Please enter a valid 10-digit phone number', 'error')
            return render_template('final_expense_landing.html', timestamp=timestamp)
        
        # Prepare prospect data
        prospect_data = {
            'first_name': first_name,
            'last_name': last_name,
            'phone': phone,
            'state': state,
            'zip': zip_code,
            'age': age
        }
        
        # Submit to Ringba
        ringba_status, ringba_message = submit_to_ringba(prospect_data)
        
        if ringba_status == STATUS_SUCCESS:
            flash('Thank you for your submission! We will contact you shortly.', 'success')
        else:
            flash(f'Error submitting your information: {ringba_message}', 'error')
        
        return render_template('final_expense_landing.html', timestamp=timestamp)
    
    # GET request - show the form
    return render_template('final_expense_landing.html', timestamp=timestamp)

@app.route('/legacy', methods=['GET', 'POST'])
def legacy_index():
    """Handles GET request for form display and POST request for submission."""
    if request.method == 'GET':
        return render_template('form.html')

    # --- POST Request Handling ---
    full_name = request.form.get('full_name', '').strip()
    phone = request.form.get('phone', '').strip()
    zip_code = request.form.get('zip_code', '').strip() # Renamed for clarity
    target_site = request.form.get('target_site', '').strip() # Get the selected site URL

    # --- Site URL Mapping --- (Add more as needed)
    valid_sites = {
        'elderlyhealth': 'https://elderlyhealthquotes.com/medicareplans/',
        'seniorsinsurance': 'https://seniorsinsurancequotes.com/'
    }

    # Basic validation
    if not all([full_name, phone, zip_code, target_site]):
        flash('All fields (Full Name, Phone, Zip Code, Target Site) are required.', 'error')
        return render_template('form.html')

    # Validate target_site selection
    if target_site not in valid_sites:
        flash('Invalid target site selected.', 'error')
        return render_template('form.html')

    target_url = valid_sites[target_site] # Get the actual URL from the selected key

    # Basic check for space, assuming First Last format
    if ' ' not in full_name:
        flash('Please enter both first and last name in Full Name.', 'error')
        return render_template('form.html')
    # Could add more specific validation for phone/zip patterns if desired

    # CORRECTED: Prepare prospect data for the function
    prospect_data = {
        'full_name': full_name,
        'phone': phone,
        'zip': zip_code
        # No first/last split, no dummy email
    }

    logger.info(f"Starting form submission process for: {full_name} with Zip: {zip_code}")

    # Check if we're in test mode (environment variable or Render.com detection)
    TEST_MODE = os.environ.get('TEST_MODE', '0') == '1' or os.environ.get('RENDER', '0') == '1'
    
    # If test mode is enabled, use the fallback test function
    submission_function = submit_fallback_test_mode if TEST_MODE else submit_to_external_form_pw
    if TEST_MODE:
        logger.warning("TEST MODE ENABLED - Using simulated form submission")
        flash("TEST MODE ACTIVE: This is a simulated submission for testing", 'warning')

# --- Initialize retry logic variables ---
    max_retries = 5
    zip_codes_to_try = [zip_code] # Start with the original zip
    tried_zip_codes = set()
    radius = 5 # Initial search radius in miles
    final_status = None
    # Default failure message if loop finishes without success or specific error
    final_message = f"Failed after {max_retries} attempts. Could not complete submission."
    final_lead_id = None

    # --- Retry Loop ---
    for attempt in range(max_retries): # Level 1 Indent (Inside function)

        # --- Get next zip code from the list --- Level 2 Indent
        if not zip_codes_to_try:
            # If the list is empty, stop retrying
            if attempt > 0: # Only log if it's not the very first check
                 logger.warning("No more zip codes left in the queue to try.")
                 # Keep the last failure message if available, otherwise set a generic one
                 final_message = final_message or f"Failed after {attempt} attempts. No suitable proxy found for previously searched nearby zip codes."
            else: # Failed first attempt and found no neighbors immediately
                 # Keep the specific failure message from the first attempt if available
                 final_message = final_message or f"Initial proxy attempt failed for zip {zip_code} and no nearby zips found in radius {radius}."
            break # Exit loop if no zips left in queue

        current_zip = zip_codes_to_try.pop(0) # Get the next zip to try
        if current_zip in tried_zip_codes:
            logger.info(f"Skipping already tried zip code: {current_zip}")
            continue # Go to next attempt iteration

        tried_zip_codes.add(current_zip)
        logger.info(f"--- Attempt {attempt + 1}/{max_retries} --- Trying Zip Code: {current_zip} ---") # Log current attempt

        # --- Prepare proxy details for this specific attempt --- Level 2 Indent
        dynamic_proxy_details = None
        if PROXY_CONFIGURED:
            # Construct the dynamic username string for DataImpulse
            # Ensure PROXY_BASE_USER includes static parts like country code if needed
            dynamic_proxy_user = f"{PROXY_BASE_USER};zip.{current_zip}"
            dynamic_proxy_details = {
                'host': PROXY_HOST,
                'port': PROXY_PORT,
                'user': dynamic_proxy_user,
                'pass': PROXY_PASS
            }
            # Log censored details for security
            logger.info(f"Using proxy configuration: {dynamic_proxy_user}:********@{PROXY_HOST}:{PROXY_PORT}")
        else:
            logger.warning(f"Attempting without proxy for zip {current_zip} as proxy is not configured.") # Log if running without proxy

        # --- Call the Playwright submission function --- Level 2 Indent
        try: # Level 2 Indent
            logger.info(f"Calling {submission_function.__name__} for zip {current_zip} to URL {target_url}...") # Log URL
            # Pass the target_site KEY to the submission function
            status, message, lead_id = submission_function(prospect_data, target_site, dynamic_proxy_details)
            logger.info(f"Call finished for zip {current_zip}. Status: {status}, Message: {message}, LeadID: {lead_id}") # Log after calling

            # Store results of this latest attempt
            final_status, final_message, final_lead_id = status, message, lead_id

            # --- Check status --- Level 3 Indent
            if status == STATUS_SUCCESS:
                logger.info(f"Submission SUCCEEDED on attempt {attempt + 1} with zip {current_zip}.")
                # Use the success message from the function
                flash(f"{final_message} (Used Zip: {current_zip}). Lead ID: {final_lead_id}", 'success')
                break # Exit loop successfully

            elif status == STATUS_PROXY_CONNECT_FAIL:
                logger.warning(f"Attempt {attempt + 1} FAILED with zip {current_zip} due to PROXY_CONNECT_FAIL: {message}")
                if attempt < max_retries - 1: # Check if more retries are allowed
                    # Flash intermediate warning to user
                    flash(f'Proxy connection failed for zip {current_zip}. Finding nearby zip codes (radius {radius} miles)...', 'warning')
                    # Find nearby zip codes only if proxy failed and more retries left
                    if search: # Check if search engine initialized successfully
                        logger.info(f"Finding nearby zip codes for original zip {zip_code} (radius: {radius} miles)")
                        nearby_zips = get_nearby_zip_codes(zip_code, radius_miles=radius, max_results=3) # Use corrected function call
                        if nearby_zips:
                            added_count = 0
                            for z in nearby_zips:
                                if z not in tried_zip_codes and z not in zip_codes_to_try:
                                    zip_codes_to_try.append(z)
                                    added_count += 1
                            if added_count > 0:
                                logger.info(f"Added {added_count} new nearby zip codes to try: {zip_codes_to_try}")
                            else:
                                logger.info("No *new* nearby zip codes found to add in this radius.")
                        else:
                           logger.info(f"No nearby zip codes found within {radius} miles.")
                        # Increase radius for the *next* search attempt
                        radius += 5
                    else:
                        logger.error("Cannot search for nearby zips, uszipcode search engine failed to initialize.")
                        # Update final message and stop retrying if search fails
                        final_message = "Proxy failed, cannot search for nearby zips (SearchEngine init failed)."
                        break # Exit loop

                else: # This was the Last attempt and it failed with proxy error
                    final_message = f"Failed after {max_retries} attempts. Could not connect via proxy near zip {zip_code}. Last error for zip {current_zip}: {message}"
                    logger.error(final_message)
                    # Let loop end naturally, message flashed after loop
                    break # Exit loop

            else: # Handle Other Failures (NAVIGATION_FAIL, AUTOMATION_FAIL, UNKNOWN_FAIL)
                logger.error(f"Attempt {attempt + 1} FAILED with zip {current_zip} due to {status}: {message}")
                # Use the specific failure message from the function
                final_message = f"Submission failed: {message} (Attempted zip: {current_zip})"
                # Stop retrying, no point using different proxy if automation/navigation fails
                break # Exit loop

        except Exception as e: # Catch unexpected errors during the route's handling of the call or loop logic
             logger.error(f"Critical error in submission loop (Attempt {attempt + 1}, Zip {current_zip}): {e}", exc_info=True)
             final_status = STATUS_UNKNOWN_FAIL
             final_message = f"An unexpected server error occurred during attempt {attempt + 1}."
             # Ensure lead_id captured before error (if any) is kept
             final_lead_id = lead_id if 'lead_id' in locals() else None
             break # Exit loop

    # --- After Loop --- (Level 1 Indent - Aligned with 'for')
    # Flash the final outcome message IF it wasn't success
    if final_status != STATUS_SUCCESS:
         # Use the specific final_message determined within the loop
         flash(final_message, 'error')

# ... (logging the final outcome) ...
    logger.info(f"Final submission outcome for {full_name}: Status={final_status}, Message='{final_message}', LeadID='{final_lead_id}'")
    return render_template('form.html') # <-- ENSURE THIS LINE IS PRESENT AND CORRECTLY INDENTED
# --- End of index() function ---

# --- Run Flask App ---
if __name__ == '__main__':
    # Get port from environment variable or use default
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)