"""
Scraply AI Agent - Main Entry Point

An intelligent AI agent system that automatically evaluates pickup requests
and illegal dumping reports, detects duplicates, and assigns pickers.

Uses Google ADK with Groq LLM backend for AI reasoning.
"""

import asyncio
from worker.main import main

if __name__ == "__main__":
    asyncio.run(main())
