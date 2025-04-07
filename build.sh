#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install dependencies
pip install -r requirements.txt

# Set environment variables to skip browser installation
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# Install Playwright without browser download
pip install playwright

# Create the playwright browsers directory
mkdir -p $HOME/.cache/ms-playwright

# Tell the application where to find browsers
echo "export PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright" >> $HOME/.bashrc 