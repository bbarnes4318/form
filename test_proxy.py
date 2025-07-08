import requests
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_proxy():
    # Proxy configuration
    proxy_host = "gw.dataimpulse.com"
    proxy_port = "823"
    proxy_user = "b31f50d644ecaffc2993__cr.us"
    proxy_pass = "8cd531d71ea28e4f"
    zip_code = "01002"  # Example zip code

    # Construct proxy URL
    proxy = f'http://{proxy_user};zip.{zip_code}:{proxy_pass}@{proxy_host}:{proxy_port}'
    proxies = {
        'http': proxy,
        'https': proxy
    }

    print(f"Testing proxy with configuration:")
    print(f"Host: {proxy_host}")
    print(f"Port: {proxy_port}")
    print(f"User: {proxy_user}")
    print(f"Zip: {zip_code}")

    try:
        # Test with ipify.org
        response = requests.get('https://api.ipify.org/', proxies=proxies, timeout=10)
        print(f"\nStatus Code: {response.status_code}")
        print(f"IP Address: {response.text}")
        
        # Test with ipinfo.io to get location
        response = requests.get('https://ipinfo.io/json', proxies=proxies, timeout=10)
        print(f"\nLocation Info:")
        print(response.json())
        
        return True
    except Exception as e:
        print(f"\nError: {str(e)}")
        return False

if __name__ == "__main__":
    test_proxy() 