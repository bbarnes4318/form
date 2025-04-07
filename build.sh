#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install dependencies
pip install -r requirements.txt

# Install Playwright
pip install playwright

# Install Playwright browsers (with explicit path)
python -m playwright install chromium
python -m playwright install-deps

# Use specific version of Playwright browsers that's known to work on Render
mkdir -p $HOME/.cache/ms-playwright
PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright

# Use pre-installed browsers through Docker container
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 