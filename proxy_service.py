from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Proxy configuration
PROXY_HOST = os.environ.get('PROXY_HOST', 'gw.dataimpulse.com')
PROXY_PORT = os.environ.get('PROXY_PORT', '823')
PROXY_BASE_USER = os.environ.get('PROXY_BASE_USER', 'b31f50d644ecaffc2993__cr.us')
PROXY_PASS = os.environ.get('PROXY_PASS', '8cd531d71ea28e4f')

@app.route('/get-proxy', methods=['POST'])
def get_proxy():
    try:
        data = request.get_json()
        area_code = data.get('area_code')
        
        if not area_code:
            return jsonify({'error': 'Area code is required'}), 400
        
        # Format: user__cr.us_zipcode
        username = f"{PROXY_BASE_USER};zip.{area_code}"
        
        proxy_details = {
            'host': PROXY_HOST,
            'port': PROXY_PORT,
            'user': username,
            'pass': PROXY_PASS
        }
        
        return jsonify({
            'success': True,
            'proxy': proxy_details
        })
        
    except Exception as e:
        logger.error(f"Error in get-proxy: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(port=5001) 