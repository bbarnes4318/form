# Flask Form Submission Application

A Flask web application that handles form submissions using Playwright with zip-code-targeted residential proxy support.

## Features

- Internal form for data collection
- Automatic proxy selection based on zip code
- Automatic retry with nearby zip codes if initial proxy fails
- JavaScript execution support (including Jornaya)
- Detailed logging and error handling

## Requirements

- Python 3.8+
- Flask
- Playwright
- Gunicorn
- uszipcode
- python-dotenv

## Installation

1. Clone the repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Install Playwright browsers and dependencies:
```bash
playwright install --with-deps
```

4. Create a `.env` file with the following variables:
```
PROXY_USER=your_proxy_username
PROXY_PASS=your_proxy_password
PROXY_HOST=your_proxy_host
PROXY_PORT=your_proxy_port
FLASK_SECRET_KEY=your_secret_key
```

## Running the Application

### Development
```bash
python app.py
```

### Production
```bash
gunicorn app:app
```

## API Endpoints

### GET /
Serves the main form page

### POST /submit
Accepts JSON data with the following structure:
```json
{
    "first_name": "John",
    "last_name": "Doe",
    "email": "john@example.com",
    "phone": "1234567890",
    "zip": "12345"
}
```

Returns JSON response:
```json
{
    "success": true,
    "message": "Form submitted successfully",
    "ip_address": "123.45.67.89",
    "zip_used": "12345"
}
```

## Proxy Configuration

The application uses zip-code-targeted residential proxies. The proxy URL is constructed as:
```
http://{username};zip.{zipcode}:{password}@{host}:{port}
```

If the initial proxy connection fails, the application will automatically try nearby zip codes within a 10-mile radius.

## Logging

The application logs detailed information about:
- Proxy configuration and connection attempts
- Form submission status
- IP address verification
- Any errors or issues encountered

## Error Handling

The application includes comprehensive error handling for:
- Proxy connection failures
- Form submission issues
- JavaScript execution problems
- Network timeouts

## Deployment

The application is configured for GCP deployment with:
- `requirements.txt` for dependencies
- `Procfile` for process management
- `runtime.txt` for Python version specification #   f o r m  
 