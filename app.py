import os
import time
import logging
from flask import Flask, render_template, request, flash, get_flashed_messages
from playwright.sync_api import sync_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv
from uszipcode import SearchEngine

# --- Configuration ---

# Load environment variables from .env file if it exists
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
# IMPORTANT: Set a strong secret key in your environment variables for production!
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'change-this-in-production-to-a-real-secret')

# Initialize zip code search engine (globally is fine)
try:
    search = SearchEngine()
    logger.info("uszipcode SearchEngine initialized.")
except Exception as e:
    logger.error(f"Failed to initialize uszipcode SearchEngine: {e}. Nearby zip code search will fail.")
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

def submit_to_external_form_pw(prospect_data, dynamic_proxy_details=None):
    """
    Submits prospect data using Playwright to elderlyhealthquotes.com.
    Args:
        prospect_data (dict): Contains 'full_name', 'phone', 'zip'.
        dynamic_proxy_details (dict): Contains 'host', 'port', 'user', 'pass' for proxy, or None.
    Returns:
        tuple: (status_code, message_string, captured_lead_id or None)
    """
    # --- Initialize variables ---
    browser = None
    context = None
    page = None
    lead_id = None # Initialize lead_id here
    target_url = 'https://elderlyhealthquotes.com/medicareplans/'
    success_indicator_selector = 'h4.modal-title:has-text("Thank You")' # Verify this selector

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

            # --- 2. Launch Browser ---
            browser_args = {
                'headless': True,
                'args': ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
                'timeout': 120000 # 2 minutes browser launch timeout
            }
            if proxy_options:
                browser_args['proxy'] = proxy_options

            try:
                browser = p.chromium.launch(**browser_args)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1280, 'height': 720}
                )
                page = context.new_page()
                logger.info("Browser launched successfully.")
            except PlaywrightError as launch_err:
                logger.error(f"Browser launch failed: {launch_err}")
                err_str = str(launch_err).lower()
                if "proxy" in err_str or "tunnel" in err_str or "epipe" in err_str or "timeout" in err_str:
                     return STATUS_PROXY_CONNECT_FAIL, f"Proxy launch failed: {launch_err}", None
                else:
                     return STATUS_UNKNOWN_FAIL, f"Browser launch failed: {launch_err}", None
            # Removed general exception catch here, covered by outer block

            # --- 3. Verify Proxy (Optional but Recommended) ---
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

            # --- 4. Navigate to Target Form ---
            try:
                logger.info(f"Navigating to target page: {target_url}...")
                page.goto(target_url, wait_until='domcontentloaded', timeout=60000)
                logger.info("DOM loaded. Waiting for page load event...")
                page.wait_for_load_state('load', timeout=30000)
                logger.info("Load event fired.")
                try:
                    logger.info("Waiting for network idle (up to 30s)...")
                    page.wait_for_load_state('networkidle', timeout=30000)
                    logger.info("Network is idle.")
                except PlaywrightTimeoutError:
                    logger.warning("Timed out waiting for network idle. Proceeding anyway...")
                logger.info("Navigation and waits complete.")
            except PlaywrightError as nav_err:
                logger.error(f"Navigation to target page failed: {nav_err}")
                err_str = str(nav_err).lower()
                if "proxy" in err_str or "tunnel" in err_str or "epipe" in err_str:
                     return STATUS_PROXY_CONNECT_FAIL, f"Navigation via proxy failed: {nav_err}", None
                elif "timeout" in err_str:
                     return STATUS_NAVIGATION_FAIL, f"Navigation timed out: {nav_err}", None
                else:
                     return STATUS_NAVIGATION_FAIL, f"Navigation failed: {nav_err}", None
            # Removed general exception catch here

            # --- 5. Wait for Essential Form Elements ---
            try:
                logger.info("Waiting for essential form elements to be ready...")
                page.locator('input[name="fname"]').wait_for(state='visible', timeout=30000)
                page.locator('input[name="universal_leadid"]').wait_for(state='attached', timeout=15000)
                page.locator('#leadid_tcpa_disclosure').wait_for(state='attached', timeout=10000)
                page.locator('input[name="finish"]').wait_for(state='attached', timeout=10000)
                logger.info("Form elements seem ready.")
            except PlaywrightError as wait_err:
                 logger.error(f"Timed out waiting for essential form elements: {wait_err}")
                 return STATUS_AUTOMATION_FAIL, f"Page did not load required form elements: {wait_err}", None
            # Removed general exception catch here

            # --- 6. Extract Lead ID (Moved before filling, but read just before submit) ---
            # We wait for existence here, but read value later
            try:
                 logger.info("Confirming lead ID field exists...")
                 page.locator('input[name="universal_leadid"]').wait_for(state='attached', timeout=10000)
                 logger.info("Lead ID input field found.")
            except PlaywrightError as lead_wait_err:
                 logger.error(f"Could not confirm existence of Lead ID field: {lead_wait_err}")
                 return STATUS_AUTOMATION_FAIL, f"Could not find Lead ID field: {lead_wait_err}", None

            # --- 7. Fill Form ---
            try:
                logger.info(f"Filling form with data: {prospect_data['full_name']}, {prospect_data['phone']}, {prospect_data['zip']}")
                page.locator('input[name="fname"]').fill(prospect_data['full_name'])
                page.locator('input[name="phoneno"]').fill(prospect_data['phone'])
                page.locator('input[name="zipcode"]').fill(prospect_data['zip'])
                logger.info("Form fields filled.")
            except PlaywrightError as fill_err:
                logger.error(f"Error filling form fields: {fill_err}")
                return STATUS_AUTOMATION_FAIL, f"Failed to fill form field: {fill_err}", None

            # --- 8. Check Consent Box ---
            try:
                logger.info("Checking consent box...")
                consent_locator = page.locator('#leadid_tcpa_disclosure')
                consent_locator.wait_for(state='visible', timeout=10000)
                consent_locator.check(timeout=5000)
                logger.info("Consent box checked.")
                page.wait_for_timeout(500) # Small delay after check
            except PlaywrightError as consent_err:
                logger.error(f"Could not check consent box: {consent_err}")
                return STATUS_AUTOMATION_FAIL, f"Failed to check consent box: {consent_err}", None

            # --- 9. Extract Lead ID (Immediately Before Submit) ---
            # Now read the value
            lead_id = None # Initialize before try
            try:
                logger.info("Extracting final Lead ID just before submit...")
                lead_id_locator = page.locator('input[name="universal_leadid"]')
                lead_id = lead_id_locator.input_value(timeout=5000)
                if not lead_id:
                    logger.error("Lead ID field value is empty right before submit.")
                    page.screenshot(path='lead_id_empty_before_submit.png')
                    return STATUS_AUTOMATION_FAIL, "Lead ID value was empty before submit.", None
                logger.info(f"Lead ID extracted just before submit: {lead_id}")
            except PlaywrightError as lead_err:
                logger.error(f"Could not get Lead ID value right before submit: {lead_err}")
                return STATUS_AUTOMATION_FAIL, f"Could not extract Lead ID before submit: {lead_err}", None # lead_id is None here

 # --- 10. Click Submit Button ---
            try:
                logger.info("Attempting to click submit button...")
                submit_locator = page.locator('input[name="finish"]')

                # REMOVED the wait_for enabled state check as it was causing errors
                # logger.info("Waiting for submit button to be enabled...")
                # submit_locator.wait_for(state='enabled', timeout=15000)

                # ADDED a slightly longer explicit pause just before clicking, after the consent check's pause.
                logger.info("Waiting for 1 second before clicking submit...")
                page.wait_for_timeout(1000) # Explicit 1-second wait

                # Attempt the click directly, with a longer timeout for the click action itself
                logger.info("Executing click action on submit button...")
                submit_locator.click(timeout=15000) # Increased click timeout to 15s
                logger.info("Submit button clicked successfully.")

            except PlaywrightTimeoutError as submit_timeout:
                 # This timeout means the click itself failed after 15s
                 logger.error(f"Timed out trying to click submit button: {submit_timeout}")
                 try:
                      # Capture state if click times out
                      screenshot_path = 'submit_click_timeout.png'
                      page.screenshot(path=screenshot_path)
                      logger.info(f"Screenshot saved: {screenshot_path}")
                 except Exception as screen_err:
                      logger.error(f"Could not take screenshot on click timeout: {screen_err}")
                 return STATUS_AUTOMATION_FAIL, f"Timeout clicking submit button: {submit_timeout}", lead_id # Return ID captured before click attempt
            except PlaywrightError as submit_err:
                 # Other errors during click (e.g., element detached)
                 logger.error(f"Failed to click submit button: {submit_err}")
                 return STATUS_AUTOMATION_FAIL, f"Failed to click submit: {submit_err}", lead_id # Return ID captured before click
            except Exception as general_submit_err:
                 logger.error(f"Unexpected Submit Click error: {general_submit_err}", exc_info=True)
                 return STATUS_UNKNOWN_FAIL, f"Unexpected Submit Click error: {general_submit_err}", lead_id

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

# --- Flask Routes ---
@app.route('/', methods=['GET', 'POST'])
def index():
    """Handles GET request for form display and POST request for submission."""
    if request.method == 'GET':
        return render_template('form.html')

    # --- POST Request Handling ---
    full_name = request.form.get('full_name', '').strip()
    phone = request.form.get('phone', '').strip()
    zip_code = request.form.get('zip_code', '').strip() # Renamed for clarity

    # Basic validation
    if not all([full_name, phone, zip_code]):
        flash('All fields (Full Name, Phone, Zip Code) are required.', 'error')
        return render_template('form.html')
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
            logger.info(f"Calling submit_to_external_form_pw for zip {current_zip}...") # Log before calling
            status, message, lead_id = submit_to_external_form_pw(prospect_data, dynamic_proxy_details)
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