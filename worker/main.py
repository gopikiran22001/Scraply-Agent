"""
Worker service that runs the AI agent as a background process.
Handles startup, shutdown, health checks, and signal handling.
"""

import asyncio
import signal
import sys
import os
from typing import Optional
from datetime import datetime

# Add parent directory to path for imports when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings
from services.database_service import db_service
from services.redis_service import redis_service
from services.rest_api_service import api_service
from agents.orchestrator_agent import orchestrator
from utils.logging_utils import logger, setup_logger


class Worker:
    """
    Background worker service for the Scraply AI Agent.
    Manages the lifecycle of the agent processing loop.
    """

    def __init__(self):
        self._started_at: Optional[datetime] = None
        self._shutdown_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def startup(self):
        """Initialize all services and connections."""
        logger.info("=" * 60)
        logger.info("Scraply AI Agent Worker Starting...")
        logger.info("=" * 60)

        # Validate settings
        errors = settings.validate()
        if errors:
            for error in errors:
                logger.error(f"Configuration error: {error}")
            raise RuntimeError("Invalid configuration. Please check environment variables.")

        # Connect to services
        logger.info("Connecting to database...")
        await db_service.connect()

        logger.info("Connecting to Redis...")
        await redis_service.connect()

        # Health checks
        logger.info("Running health checks...")

        db_healthy = await db_service.health_check()
        if not db_healthy:
            raise RuntimeError("Database health check failed")

        redis_healthy = await redis_service.health_check()
        if not redis_healthy:
            raise RuntimeError("Redis health check failed")

        # Check REST API health using the new /health endpoint
        api_health = await api_service.get_health()
        if api_health.get("status") == "UP":
            logger.info(f"REST API healthy: {api_health.get('service', 'Scraply REST API')}")
            
            # Optionally get detailed component health
            details = await api_service.get_health_details()
            if details.get("components"):
                components = details["components"]
                for name, status in components.items():
                    comp_status = status.get("status", "UNKNOWN") if isinstance(status, dict) else status
                    logger.info(f"  - {name}: {comp_status}")
        else:
            logger.warning(f"REST API health check returned: {api_health}")
            logger.warning("Will retry on first request")

        # Log queue status
        queue_sizes = await redis_service.get_all_queue_sizes()
        logger.info(f"Queue Status: {queue_sizes}")

        self._started_at = datetime.now()
        logger.info("Worker startup complete!")
        logger.info("=" * 60)

    async def shutdown(self):
        """Gracefully shutdown all services."""
        logger.info("=" * 60)
        logger.info("Shutting down Scraply AI Agent Worker...")
        logger.info("=" * 60)

        # Stop orchestrator
        orchestrator.stop()

        # Cancel any running tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close connections
        await api_service.close()
        await redis_service.disconnect()
        await db_service.disconnect()

        logger.info("Worker shutdown complete!")

    async def run(self):
        """Run the worker main loop."""
        await self.startup()

        try:
            # Create main processing task
            main_task = asyncio.create_task(
                orchestrator.run_continuous()
            )
            self._tasks.append(main_task)

            # Create health check task
            health_task = asyncio.create_task(
                self._health_check_loop()
            )
            self._tasks.append(health_task)

            # Wait for shutdown signal
            await self._shutdown_event.wait()

        except asyncio.CancelledError:
            logger.info("Worker received cancellation")
        except Exception as e:
            logger.error(f"Worker error: {e}")
            raise
        finally:
            await self.shutdown()

    async def _health_check_loop(self, interval: int = 600):
        """Periodic health check loop (default: 10 minutes)."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(interval)

                # Check services
                db_ok = await db_service.health_check()
                redis_ok = await redis_service.health_check()
                api_ok = await api_service.health_check()

                # Get status
                status = await orchestrator.get_status()

                uptime = datetime.now() - self._started_at if self._started_at else None

                logger.info(
                    f"Health: DB={db_ok}, Redis={redis_ok}, API={api_ok}, "
                    f"Queued={status['total_pending']}, "
                    f"Uptime={uptime}"
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")

    def request_shutdown(self):
        """Request graceful shutdown."""
        logger.info("Shutdown requested...")
        self._shutdown_event.set()


def setup_signal_handlers(worker: Worker):
    """Set up signal handlers for graceful shutdown."""
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        worker.request_shutdown()

    # Register signal handlers
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    else:
        # Windows doesn't support SIGTERM well
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGBREAK, signal_handler)


async def main():
    """Main entry point for the worker."""
    # Set up logging
    import logging
    log_level = logging.DEBUG if settings.llm.api_key else logging.INFO
    setup_logger("scraply_agent", level=log_level)

    # Create worker
    worker = Worker()

    # Set up signal handlers
    setup_signal_handlers(worker)

    # Run worker
    try:
        await worker.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        worker.request_shutdown()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
