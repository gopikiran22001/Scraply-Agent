"""
Logging configuration for the Scraply AI Agent.
"""

import logging
import sys
from typing import Optional
from datetime import datetime


def setup_logger(
    name: str = "scraply_agent",
    level: int = logging.INFO,
    log_file: Optional[str] = None
) -> logging.Logger:
    """
    Set up a configured logger instance.

    Args:
        name: Logger name
        level: Logging level
        log_file: Optional file path for logging

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Clear existing handlers
    logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# Global logger instance
logger = setup_logger()


def log_request_processing(
    request_type: str,
    request_id: str,
    action: str,
    details: Optional[str] = None
):
    """Log request processing events."""
    message = f"[{request_type}] {request_id} - {action}"
    if details:
        message += f" | {details}"
    logger.info(message)


def log_agent_decision(
    agent_name: str,
    request_id: str,
    decision: str,
    reasoning: Optional[str] = None
):
    """Log agent decisions."""
    message = f"[{agent_name}] Request {request_id} -> {decision}"
    if reasoning:
        message += f" | Reasoning: {reasoning}"
    logger.info(message)


def log_api_call(
    method: str,
    endpoint: str,
    status_code: Optional[int] = None,
    error: Optional[str] = None
):
    """Log API calls."""
    if error:
        logger.error(f"API {method} {endpoint} - Error: {error}")
    elif status_code:
        logger.debug(f"API {method} {endpoint} - Status: {status_code}")
    else:
        logger.debug(f"API {method} {endpoint}")


def log_queue_event(
    queue_name: str,
    event: str,
    request_id: Optional[str] = None
):
    """Log queue events."""
    message = f"[Queue:{queue_name}] {event}"
    if request_id:
        message += f" - ID: {request_id}"
    logger.debug(message)
