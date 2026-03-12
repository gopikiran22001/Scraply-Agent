#!/bin/bash
# ===================================================
# Scraply AI Agent - Run Script
# ===================================================
# This script starts the AI Agent worker service.
# Usage: ./run.sh [options]
# Options:
#   --dev     Run in development mode with debug logging
#   --test    Run tests instead of the worker
# ===================================================

set -e

# Navigate to script directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

# Check for virtual environment
if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Creating..."
    python -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Check if dependencies are installed
if ! python -c "import google.adk" 2>/dev/null; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

# Check for .env file
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found. Copy .env.example to .env and configure it."
    exit 1
fi

# Parse arguments
case "$1" in
    --dev)
        echo "Starting in development mode..."
        export LOG_LEVEL=DEBUG
        python main.py
        ;;
    --test)
        echo "Running tests..."
        pytest tests/ -v
        ;;
    *)
        echo "Starting Scraply AI Agent Worker..."
        python main.py
        ;;
esac
