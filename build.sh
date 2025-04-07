#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
python -m playwright install chromium
python -m playwright install-deps 