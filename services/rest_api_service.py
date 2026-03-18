"""
REST API service for communicating with the Scraply backend.
The AI Agent uses this to perform actions like assigning pickers and rejecting requests.
"""

import asyncio
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

from config.settings import settings
from config.constants import Status
from utils.logging_utils import logger, log_api_call


class APIError(Exception):
    """Custom exception for API errors."""
    def __init__(self, status_code: int, message: str, endpoint: str):
        self.status_code = status_code
        self.message = message
        self.endpoint = endpoint
        super().__init__(f"API Error {status_code} at {endpoint}: {message}")


@dataclass
class AgentPickupUpdate:
    """
    Request body for updating pickup status.
    Matches backend AgentPickupUpdate.java
    """
    agent_id: str
    pickup_id: str
    status: Status
    reason: Optional[str] = None
    picker_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "agentId": self.agent_id,
            "pickupId": self.pickup_id,
            "status": self.status.value
        }
        if self.reason:
            data["reason"] = self.reason
        if self.picker_id:
            data["pickerId"] = self.picker_id
        return data


@dataclass
class AgentDumpingUpdate:
    """
    Request body for updating illegal dumping status.
    Matches backend AgentDumpingUpdate.java
    """
    agent_id: str
    dumping_id: str
    status: Status
    reason: Optional[str] = None
    picker_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "agentId": self.agent_id,
            "dumpingId": self.dumping_id,
            "status": self.status.value
        }
        if self.reason:
            data["reason"] = self.reason
        if self.picker_id:
            data["pickerId"] = self.picker_id
        return data


@dataclass
class AgentLogEntry:
    """Payload for persisting agent logs in backend."""
    agent_id: str
    level: str
    message: str
    event_type: str = "GENERAL"
    request_type: Optional[str] = None
    request_id: Optional[str] = None
    details: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "agentId": self.agent_id,
            "level": self.level,
            "message": self.message,
            "eventType": self.event_type
        }
        if self.request_type:
            data["requestType"] = self.request_type
        if self.request_id:
            data["requestId"] = self.request_id
        if self.details:
            data["details"] = self.details
        return data


class RestApiService:
    """
    Service for making authenticated API calls to the Scraply backend.
    """

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._base_url = settings.api.base_url
        self._headers = {
            "X-ACCESS-KEY": settings.api.access_key,
            "X-SECRET-KEY": settings.api.secret_key,
            "Content-Type": "application/json"
        }

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers,
                timeout=settings.api.timeout
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("REST API client closed")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException))
    )
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Make an HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            endpoint: API endpoint
            json_data: Optional JSON body

        Returns:
            Response data as dict

        Raises:
            APIError: If the request fails
        """
        client = await self._get_client()

        try:
            response = await client.request(
                method=method,
                url=endpoint,
                json=json_data
            )

            log_api_call(method, endpoint, response.status_code)

            if response.status_code >= 400:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_detail = error_json.get("message", error_detail)
                except:
                    pass

                raise APIError(
                    status_code=response.status_code,
                    message=error_detail,
                    endpoint=endpoint
                )

            # Return response JSON or empty dict
            if response.text:
                try:
                    return response.json() if isinstance(response.json(), dict) else {"result": response.json()}
                except:
                    return {"result": response.text}
            return {}

        except httpx.ConnectError as e:
            log_api_call(method, endpoint, error=str(e))
            raise
        except httpx.TimeoutException as e:
            log_api_call(method, endpoint, error=f"Timeout: {e}")
            raise
        except APIError:
            raise
        except Exception as e:
            log_api_call(method, endpoint, error=str(e))
            raise

    # ==================== PICKUP OPERATIONS ====================

    async def update_pickup_progress(
        self,
        pickup_id: str
    ) -> Dict[str, Any]:
        """
        Mark a pickup request as IN_PROGRESS for evaluation.
        This triggers the backend to add it to the assignment queue.

        Args:
            pickup_id: The pickup request ID

        Returns:
            API response
        """
        update = AgentPickupUpdate(
            agent_id=settings.agent.agent_id,
            pickup_id=pickup_id,
            status=Status.IN_PROGRESS
        )

        logger.info(f"Marking pickup {pickup_id} as IN_PROGRESS")
        return await self._make_request(
            method="PUT",
            endpoint="/agent/pickup",
            json_data=update.to_dict()
        )

    async def assign_pickup(
        self,
        pickup_id: str,
        picker_id: str
    ) -> Dict[str, Any]:
        """
        Assign a picker to a pickup request.

        Args:
            pickup_id: The pickup request ID
            picker_id: The picker's user ID

        Returns:
            API response
        """
        update = AgentPickupUpdate(
            agent_id=settings.agent.agent_id,
            pickup_id=pickup_id,
            status=Status.ASSIGNED,
            picker_id=picker_id
        )

        logger.info(f"Assigning picker {picker_id} to pickup {pickup_id}")
        return await self._make_request(
            method="PUT",
            endpoint="/agent/pickup",
            json_data=update.to_dict()
        )

    async def cancel_pickup(
        self,
        pickup_id: str,
        reason: str
    ) -> Dict[str, Any]:
        """
        Cancel/reject a pickup request.

        Args:
            pickup_id: The pickup request ID
            reason: Reason for cancellation

        Returns:
            API response
        """
        update = AgentPickupUpdate(
            agent_id=settings.agent.agent_id,
            pickup_id=pickup_id,
            status=Status.CANCELLED,
            reason=reason
        )

        logger.info(f"Cancelling pickup {pickup_id}: {reason}")
        return await self._make_request(
            method="PUT",
            endpoint="/agent/pickup",
            json_data=update.to_dict()
        )

    # ==================== ILLEGAL DUMP OPERATIONS ====================

    async def update_dumping_progress(
        self,
        dumping_id: str
    ) -> Dict[str, Any]:
        """
        Mark an illegal dump report as IN_PROGRESS for evaluation.

        Args:
            dumping_id: The dump report ID

        Returns:
            API response
        """
        update = AgentDumpingUpdate(
            agent_id=settings.agent.agent_id,
            dumping_id=dumping_id,
            status=Status.IN_PROGRESS
        )

        logger.info(f"Marking dump {dumping_id} as IN_PROGRESS")
        return await self._make_request(
            method="PUT",
            endpoint="/agent/dumping",
            json_data=update.to_dict()
        )

    async def assign_dumping(
        self,
        dumping_id: str,
        picker_id: str
    ) -> Dict[str, Any]:
        """
        Assign a picker to an illegal dump report.

        Args:
            dumping_id: The dump report ID
            picker_id: The picker's user ID

        Returns:
            API response
        """
        update = AgentDumpingUpdate(
            agent_id=settings.agent.agent_id,
            dumping_id=dumping_id,
            status=Status.ASSIGNED,
            picker_id=picker_id
        )

        logger.info(f"Assigning picker {picker_id} to dump {dumping_id}")
        return await self._make_request(
            method="PUT",
            endpoint="/agent/dumping",
            json_data=update.to_dict()
        )

    async def cancel_dumping(
        self,
        dumping_id: str,
        reason: str
    ) -> Dict[str, Any]:
        """
        Cancel/reject an illegal dump report.

        Args:
            dumping_id: The dump report ID
            reason: Reason for cancellation

        Returns:
            API response
        """
        update = AgentDumpingUpdate(
            agent_id=settings.agent.agent_id,
            dumping_id=dumping_id,
            status=Status.CANCELLED,
            reason=reason
        )

        logger.info(f"Cancelling dump {dumping_id}: {reason}")
        return await self._make_request(
            method="PUT",
            endpoint="/agent/dumping",
            json_data=update.to_dict()
        )

    async def create_agent_log(
        self,
        level: str,
        message: str,
        event_type: str = "GENERAL",
        request_type: Optional[str] = None,
        request_id: Optional[str] = None,
        details: Optional[str] = None
    ) -> Dict[str, Any]:
        """Persist a structured agent log via backend endpoint."""
        entry = AgentLogEntry(
            agent_id=settings.agent.agent_id,
            level=level,
            message=message,
            event_type=event_type,
            request_type=request_type,
            request_id=request_id,
            details=details
        )

        return await self._make_request(
            method="POST",
            endpoint="/agent/logs",
            json_data=entry.to_dict()
        )

    # ==================== READ OPERATIONS (via existing endpoints) ====================

    async def get_pickup(self, pickup_id: str) -> Dict[str, Any]:
        """
        Get pickup request details.

        Args:
            pickup_id: The pickup request ID

        Returns:
            Pickup data
        """
        return await self._make_request(
            method="GET",
            endpoint=f"/pickups/{pickup_id}"
        )

    async def get_dumping(self, dumping_id: str) -> Dict[str, Any]:
        """
        Get illegal dump report details.

        Args:
            dumping_id: The dump report ID

        Returns:
            Dump data
        """
        return await self._make_request(
            method="GET",
            endpoint=f"/illegals/{dumping_id}"
        )

    # ==================== HEALTH CHECK ====================

    async def health_check(self) -> bool:
        """
        Check basic API connectivity.
        
        Returns:
            True if API is reachable and healthy
        """
        try:
            client = await self._get_client()
            response = await client.get("/health")
            if response.status_code == 200:
                data = response.json()
                return data.get("status") == "UP"
            return False
        except Exception as e:
            logger.error(f"API health check failed: {e}")
            return False

    async def get_health(self) -> Dict[str, Any]:
        """
        Get basic health status from REST API.
        
        Returns:
            Health status dict with status, timestamp, service
        """
        try:
            client = await self._get_client()
            response = await client.get("/health")
            if response.status_code == 200:
                return response.json()
            return {"status": "DOWN", "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"status": "DOWN", "error": str(e)}

    async def get_health_details(self) -> Dict[str, Any]:
        """
        Get detailed health status including all components (database, redis).
        
        Returns:
            Health details dict with status, timestamp, service, components
        """
        try:
            client = await self._get_client()
            response = await client.get("/health/details")
            if response.status_code == 200:
                return response.json()
            return {"status": "DOWN", "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"status": "DOWN", "error": str(e)}

    async def get_database_health(self) -> Dict[str, Any]:
        """
        Get database health status from REST API.
        
        Returns:
            Database health dict with status and details
        """
        try:
            client = await self._get_client()
            response = await client.get("/health/db")
            if response.status_code == 200:
                return response.json()
            return {"status": "DOWN", "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"status": "DOWN", "error": str(e)}

    async def get_redis_health(self) -> Dict[str, Any]:
        """
        Get Redis health status from REST API.
        
        Returns:
            Redis health dict with status and details
        """
        try:
            client = await self._get_client()
            response = await client.get("/health/redis")
            if response.status_code == 200:
                return response.json()
            return {"status": "DOWN", "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"status": "DOWN", "error": str(e)}

    async def wait_for_api(self, max_attempts: int = 10, delay: float = 2.0) -> bool:
        """
        Wait for the REST API to become available.
        
        Args:
            max_attempts: Maximum number of connection attempts
            delay: Delay between attempts in seconds
            
        Returns:
            True if API is available, False if timed out
        """
        import asyncio
        
        for attempt in range(1, max_attempts + 1):
            logger.info(f"Checking REST API health (attempt {attempt}/{max_attempts})...")
            
            if await self.health_check():
                logger.info("REST API is healthy and ready")
                return True
            
            if attempt < max_attempts:
                logger.warning(f"REST API not ready, retrying in {delay}s...")
                await asyncio.sleep(delay)
        
        logger.error("REST API health check failed after all attempts")
        return False


# Global REST API service instance
api_service = RestApiService()
