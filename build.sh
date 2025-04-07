#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install dependencies
pip install -r requirements.txt

# Install Playwright without browser download
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 pip install playwright

# Use specific version of Playwright browsers that's known to work on Render
mkdir -p $HOME/.cache/ms-playwright
PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright

# Use pre-installed browsers through Docker container
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 