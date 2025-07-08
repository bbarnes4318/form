from playwright.sync_api import sync_playwright
from uszipcode import SearchEngine
import sys

# Initialize zip code search engine
search = SearchEngine()

# Michigan and nearby major cities for fallback
MICHIGAN_ZIPS = [
    "49503",  # Grand Rapids, MI
    "49201",  # Jackson, MI
    "48933",  # Lansing, MI
    "48226",  # Detroit, MI
    "48864",  # Okemos, MI
    "49684",  # Traverse City, MI
    "48858",  # Mount Pleasant, MI
    "48912",  # East Lansing, MI
    "49855",  # Marquette, MI
    "60601",  # Chicago, IL
    "44101",  # Cleveland, OH
    "43215",  # Columbus, OH
    "46204"   # Indianapolis, IN
]

def get_nearby_zip_codes(target_zip, radius_miles, max_results=15):
    """Find nearby zip codes within radius"""
    try:
        result = search.by_zipcode(target_zip)
        if not result:
            print(f"Invalid zip code: {target_zip}")
            return []
            
        nearby = search.by_coordinates(
            result.lat, 
            result.lng, 
            radius=radius_miles, 
            returns=max_results+1
        )
        
        # Return list of zip codes excluding the target
        return [z.zipcode for z in nearby if z.zipcode != target_zip]
    except Exception as e:
        print(f"Error finding nearby zips: {e}")
        return []

def try_with_proxy(zip_code):
    """Try to launch browser with specific zip"""
    print(f"\nTrying zip code: {zip_code}")
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=False,
                proxy={
                    "server": "http://gw.dataimpulse.com:823",
                    "username": f"b31f50d644ecaffc2993__cr.us;zip.{zip_code}",
                    "password": "8cd531d71ea28e4f"
                }
            )
            
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://whatismyipaddress.com")
            
            print(f"SUCCESS with zip {zip_code} - BROWSER IS OPEN")
            print(f"You requested {target_zip} but are using {zip_code} ({get_distance(target_zip, zip_code)} miles away)")
            input("Press Enter to close browser...")
            
            browser.close()
            return True
            
        except Exception as e:
            print(f"Failed with zip {zip_code}")
            return False

def get_distance(zip1, zip2):
    """Get distance between two zip codes"""
    try:
        loc1 = search.by_zipcode(zip1)
        loc2 = search.by_zipcode(zip2)
        if loc1 and loc2 and loc1.lat and loc1.lng and loc2.lat and loc2.lng:
            from math import sin, cos, sqrt, atan2, radians
            
            # Approximate radius of earth in miles
            R = 3958.8
            
            lat1 = radians(loc1.lat)
            lon1 = radians(loc1.lng)
            lat2 = radians(loc2.lat)
            lon2 = radians(loc2.lng)
            
            dlon = lon2 - lon1
            dlat = lat2 - lat1
            
            a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
            c = 2 * atan2(sqrt(a), sqrt(1 - a))
            
            distance = R * c
            return round(distance)
        return "unknown"
    except:
        return "unknown"

# Get zip code from command line or prompt
if len(sys.argv) > 1:
    target_zip = sys.argv[1]
else:
    target_zip = input("Enter zip code: ")

# Try requested zip first
print("Starting search for working proxy...")
if try_with_proxy(target_zip):
    sys.exit(0)

# Search with increasing radius up to 1000 miles
print(f"\nOriginal zip {target_zip} failed. Searching outward...")

# Try increasing radiuses - extreme distances
tried_zips = {target_zip}
for radius in [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]:
    print(f"\nSearching within {radius} miles...")
    nearby_zips = get_nearby_zip_codes(target_zip, radius_miles=radius, max_results=15)
    
    # Filter out already tried zip codes
    new_zips = [z for z in nearby_zips if z not in tried_zips]
    
    if not new_zips:
        print(f"No new zip codes found within {radius} miles")
        continue
        
    print(f"Found {len(new_zips)} new zip codes to try within {radius} miles")
    
    # Try each nearby zip
    for zip_code in new_zips:
        tried_zips.add(zip_code)
        if try_with_proxy(zip_code):
            sys.exit(0)

# If all radius searches fail, try Michigan cities as fallback
print("\nRadius search failed. Trying Michigan and nearby major cities as fallback...")
for zip_code in MICHIGAN_ZIPS:
    if zip_code not in tried_zips:
        if try_with_proxy(zip_code):
            sys.exit(0)
        tried_zips.add(zip_code)

print("\nAll attempts failed.")