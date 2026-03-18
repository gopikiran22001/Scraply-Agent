"""
Logging configuration for the Scraply AI Agent.
"""

import logging
import sys
from typing import Optional
import asyncio
import json
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


def _normalize_level(level: str) -> str:
    normalized = (level or "INFO").upper()
    if normalized == "WARN":
        return "WARNING"
    return normalized


def _serialize_details(details: Optional[dict]) -> Optional[str]:
    if not details:
        return None
    try:
        serialized = json.dumps(details, ensure_ascii=True, default=str)
        return serialized[:3900]
    except Exception:
        return None


def _log_dispatch_failed(task: asyncio.Task):
    try:
        task.result()
    except Exception as exc:
        logger.debug(f"Agent log dispatch failed: {exc}")


def emit_agent_log(
    level: str,
    message: str,
    event_type: str = "GENERAL",
    request_type: Optional[str] = None,
    request_id: Optional[str] = None,
    details: Optional[dict] = None
):
    """Send structured logs to backend asynchronously without blocking workflows."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    try:
        from services.rest_api_service import api_service

        task = loop.create_task(
            api_service.create_agent_log(
                level=_normalize_level(level),
                message=message,
                event_type=event_type,
                request_type=request_type,
                request_id=request_id,
                details=_serialize_details(details)
            )
        )
        task.add_done_callback(_log_dispatch_failed)
    except Exception as exc:
        logger.debug(f"Failed to queue agent log dispatch: {exc}")


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
    emit_agent_log(
        level="INFO",
        message=message,
        event_type=action.upper().replace(" ", "_"),
        request_type=request_type,
        request_id=request_id,
        details={"details": details} if details else None
    )


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
    emit_agent_log(
        level="INFO",
        message=message,
        event_type="DECISION",
        request_id=request_id,
        details={"agentName": agent_name, "decision": decision, "reasoning": reasoning}
    )


def log_error_event(
    context: str,
    error: str,
    request_type: Optional[str] = None,
    request_id: Optional[str] = None,
    details: Optional[dict] = None
):
    """Log error locally and dispatch it to backend for reporting."""
    message = f"[{context}] {error}"
    logger.error(message)
    emit_agent_log(
        level="ERROR",
        message=message,
        event_type="ERROR",
        request_type=request_type,
        request_id=request_id,
        details=details
    )


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
