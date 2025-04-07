import requests

proxy = 'http://b31f50d644ecaffc2993__cr.us;zip.01002:8cd531d71ea28e4f@gw.dataimpulse.com:823'
proxies = {
    'http': proxy,
    'https': proxy
}

try:
    response = requests.get('https://api.ipify.org/', proxies=proxies)
    print(f"Status Code: {response.status_code}")
    print(f"IP Address: {response.text}")
except Exception as e:
    print(f"Error: {str(e)}") 