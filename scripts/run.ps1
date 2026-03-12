# ===================================================
# Scraply AI Agent - Windows Run Script
# ===================================================
# This script starts the AI Agent worker service.
# Usage: .\run.ps1 [options]
# Options:
#   -Dev     Run in development mode with debug logging
#   -Test    Run tests instead of the worker
# ===================================================

param(
    [switch]$Dev,
    [switch]$Test
)

$ErrorActionPreference = "Stop"

# Navigate to script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $ScriptDir "..")

# Check for virtual environment
if (-not (Test-Path ".venv")) {
    Write-Host "Virtual environment not found. Creating..."
    python -m venv .venv
}

# Activate virtual environment
& .\.venv\Scripts\Activate.ps1

# Check if dependencies are installed
$installed = python -c "import google.adk" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing dependencies..."
    pip install -r requirements.txt
}

# Check for .env file
if (-not (Test-Path ".env")) {
    Write-Host "Warning: .env file not found. Copy .env.example to .env and configure it."
    exit 1
}

# Run based on arguments
if ($Dev) {
    Write-Host "Starting in development mode..."
    $env:LOG_LEVEL = "DEBUG"
    python main.py
}
elseif ($Test) {
    Write-Host "Running tests..."
    pytest tests/ -v
}
else {
    Write-Host "Starting Scraply AI Agent Worker..."
    python main.py
}
