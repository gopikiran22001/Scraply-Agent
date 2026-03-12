"""
Redis service for queue operations.
The AI Agent uses this to listen for new requests and process them.
"""

import asyncio
import ssl
from typing import Optional, Callable, Awaitable, Dict, Any
import redis.asyncio as redis
from redis.asyncio import Redis

from config.settings import settings
from config.constants import QueueNames
from utils.logging_utils import logger, log_queue_event


class RedisService:
    """
    Service for Redis queue operations.
    Provides async queue listening and dequeue capabilities.
    """

    def __init__(self):
        self._client: Optional[Redis] = None
        self._running = False

    async def connect(self):
        """Establish connection to Redis."""
        if self._client is not None:
            return

        try:
            connection_kwargs = {
                "host": settings.redis.host,
                "port": settings.redis.port,
                "decode_responses": True,
            }

            # Add password if provided
            if settings.redis.password:
                connection_kwargs["password"] = settings.redis.password

            # Handle SSL configuration
            if settings.redis.ssl:
                # Create SSL context for Redis Cloud / managed Redis
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                connection_kwargs["ssl"] = ssl_context

            self._client = redis.Redis(**connection_kwargs)

            # Test connection
            await self._client.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis connection closed")

    async def _ensure_connected(self):
        """Ensure Redis client is connected."""
        if self._client is None:
            await self.connect()

    # ==================== QUEUE OPERATIONS ====================

    async def dequeue(self, queue_name: str) -> Optional[str]:
        """
        Dequeue an item from the right side of a queue (FIFO).

        Args:
            queue_name: Name of the queue

        Returns:
            The dequeued item ID or None if queue is empty
        """
        await self._ensure_connected()
        try:
            result = await self._client.rpop(queue_name)
            if result:
                log_queue_event(queue_name, "dequeued", result)
            return result
        except Exception as e:
            logger.error(f"Error dequeuing from {queue_name}: {e}")
            return None

    async def blocking_dequeue(
        self,
        queue_name: str,
        timeout: int = 0
    ) -> Optional[str]:
        """
        Blocking dequeue - waits for an item if queue is empty.

        Args:
            queue_name: Name of the queue
            timeout: Timeout in seconds (0 = block forever)

        Returns:
            The dequeued item ID or None on timeout
        """
        await self._ensure_connected()
        try:
            result = await self._client.brpop(queue_name, timeout=timeout)
            if result:
                queue, item = result
                log_queue_event(queue_name, "dequeued (blocking)", item)
                return item
            return None
        except Exception as e:
            logger.error(f"Error in blocking dequeue from {queue_name}: {e}")
            return None

    async def peek(self, queue_name: str) -> Optional[str]:
        """
        Peek at the next item without removing it.

        Args:
            queue_name: Name of the queue

        Returns:
            The next item ID or None if queue is empty
        """
        await self._ensure_connected()
        try:
            return await self._client.lindex(queue_name, -1)
        except Exception as e:
            logger.error(f"Error peeking {queue_name}: {e}")
            return None

    async def get_queue_size(self, queue_name: str) -> int:
        """
        Get the current size of a queue.

        Args:
            queue_name: Name of the queue

        Returns:
            Number of items in the queue
        """
        await self._ensure_connected()
        try:
            size = await self._client.llen(queue_name)
            return size or 0
        except Exception as e:
            logger.error(f"Error getting queue size for {queue_name}: {e}")
            return 0

    async def enqueue(self, queue_name: str, item: str):
        """
        Enqueue an item (push to left side).

        Args:
            queue_name: Name of the queue
            item: Item to enqueue
        """
        await self._ensure_connected()
        try:
            await self._client.lpush(queue_name, item)
            log_queue_event(queue_name, "enqueued", item)
        except Exception as e:
            logger.error(f"Error enqueuing to {queue_name}: {e}")
            raise

    # ==================== QUEUE LISTENERS ====================

    async def listen_to_queue(
        self,
        queue_name: str,
        handler: Callable[[str], Awaitable[None]],
        poll_interval: float = 1.0
    ):
        """
        Listen to a queue and call handler for each item.
        Uses non-blocking polling for graceful shutdown.

        Args:
            queue_name: Name of the queue to listen to
            handler: Async function to handle each dequeued item
            poll_interval: Interval between polls in seconds
        """
        await self._ensure_connected()
        log_queue_event(queue_name, f"Started listening (interval: {poll_interval}s)")
        self._running = True

        while self._running:
            try:
                # Try to dequeue
                item = await self.dequeue(queue_name)

                if item:
                    try:
                        await handler(item)
                    except Exception as e:
                        logger.error(f"Handler error for {queue_name} item {item}: {e}")
                        # Re-queue on handler failure for retry
                        await self.enqueue(queue_name, item)
                else:
                    # No item, wait before polling again
                    await asyncio.sleep(poll_interval)

            except asyncio.CancelledError:
                logger.info(f"Queue listener cancelled for {queue_name}")
                break
            except Exception as e:
                logger.error(f"Error in queue listener for {queue_name}: {e}")
                await asyncio.sleep(poll_interval)

        log_queue_event(queue_name, "Stopped listening")

    def stop_listening(self):
        """Signal the listener to stop."""
        self._running = False

    # ==================== MULTI-QUEUE OPERATIONS ====================

    async def dequeue_from_multiple(
        self,
        queue_names: list[str],
        timeout: int = 5
    ) -> Optional[tuple[str, str]]:
        """
        Blocking dequeue from multiple queues.

        Args:
            queue_names: List of queue names to listen to
            timeout: Timeout in seconds

        Returns:
            Tuple of (queue_name, item) or None on timeout
        """
        await self._ensure_connected()
        try:
            result = await self._client.brpop(queue_names, timeout=timeout)
            if result:
                queue, item = result
                log_queue_event(queue, "dequeued (multi)", item)
                return (queue, item)
            return None
        except Exception as e:
            logger.error(f"Error in multi-queue dequeue: {e}")
            return None

    # ==================== CACHE OPERATIONS ====================

    async def cache_set(
        self,
        key: str,
        value: str,
        expire_seconds: int = 300
    ):
        """
        Set a cache value with expiration.

        Args:
            key: Cache key
            value: Value to cache
            expire_seconds: TTL in seconds
        """
        await self._ensure_connected()
        try:
            await self._client.setex(key, expire_seconds, value)
        except Exception as e:
            logger.error(f"Error setting cache key {key}: {e}")

    async def cache_get(self, key: str) -> Optional[str]:
        """
        Get a cached value.

        Args:
            key: Cache key

        Returns:
            Cached value or None
        """
        await self._ensure_connected()
        try:
            return await self._client.get(key)
        except Exception as e:
            logger.error(f"Error getting cache key {key}: {e}")
            return None

    async def cache_delete(self, key: str):
        """Delete a cache key."""
        await self._ensure_connected()
        try:
            await self._client.delete(key)
        except Exception as e:
            logger.error(f"Error deleting cache key {key}: {e}")

    # ==================== RETRY TRACKING ====================

    async def get_retry_count(self, request_id: str, request_type: str) -> int:
        """
        Get the current retry count for a request.

        Args:
            request_id: The request ID
            request_type: Type of request ('pickup' or 'dump')

        Returns:
            Current retry count (0 if not set)
        """
        await self._ensure_connected()
        key = f"retry:{request_type}:{request_id}"
        try:
            count = await self._client.get(key)
            return int(count) if count else 0
        except Exception as e:
            logger.error(f"Error getting retry count for {key}: {e}")
            return 0

    async def increment_retry_count(self, request_id: str, request_type: str, expire_hours: int = 24) -> int:
        """
        Increment the retry count for a request.

        Args:
            request_id: The request ID
            request_type: Type of request ('pickup' or 'dump')
            expire_hours: TTL for the retry counter in hours

        Returns:
            New retry count after increment
        """
        await self._ensure_connected()
        key = f"retry:{request_type}:{request_id}"
        try:
            count = await self._client.incr(key)
            # Set expiration on first increment
            if count == 1:
                await self._client.expire(key, expire_hours * 3600)
            logger.debug(f"Retry count for {key}: {count}")
            return count
        except Exception as e:
            logger.error(f"Error incrementing retry count for {key}: {e}")
            return 0

    async def clear_retry_count(self, request_id: str, request_type: str):
        """
        Clear the retry count for a request (called after successful assignment).

        Args:
            request_id: The request ID
            request_type: Type of request ('pickup' or 'dump')
        """
        await self._ensure_connected()
        key = f"retry:{request_type}:{request_id}"
        try:
            await self._client.delete(key)
        except Exception as e:
            logger.error(f"Error clearing retry count for {key}: {e}")

    # ==================== HEALTH CHECK ====================

    async def health_check(self) -> bool:
        """Check Redis connectivity."""
        try:
            await self._ensure_connected()
            await self._client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False

    async def get_all_queue_sizes(self) -> Dict[str, int]:
        """Get sizes of all known queues."""
        return {
            QueueNames.PICKUP_QUEUE: await self.get_queue_size(QueueNames.PICKUP_QUEUE),
            QueueNames.DUMP_QUEUE: await self.get_queue_size(QueueNames.DUMP_QUEUE),
            QueueNames.PICKUP_ASSIGN_QUEUE: await self.get_queue_size(QueueNames.PICKUP_ASSIGN_QUEUE),
            QueueNames.DUMP_ASSIGN_QUEUE: await self.get_queue_size(QueueNames.DUMP_ASSIGN_QUEUE),
        }


# Global Redis service instance
redis_service = RedisService()
