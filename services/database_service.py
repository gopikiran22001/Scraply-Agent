"""
Database service for read-only access to PostgreSQL views.
The AI Agent uses this service to fetch request and user data.
"""

import asyncio
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager
import asyncpg
from asyncpg import Pool

from config.settings import settings
from config.constants import ViewNames, Status, Role, AccountStatus
from utils.logging_utils import logger


class DatabaseService:
    """
    Service for read-only database operations on views.
    Uses connection pooling for efficiency.
    """

    def __init__(self):
        self._pool: Optional[Pool] = None

    async def connect(self):
        """Establish connection pool to the database."""
        if self._pool is not None:
            return

        try:
            self._pool = await asyncpg.create_pool(
                host=settings.database.host,
                port=settings.database.port,
                database=settings.database.database,
                user=settings.database.user,
                password=settings.database.password,
                min_size=2,
                max_size=10,
                command_timeout=30
            )
            logger.info("Database connection pool established")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    async def disconnect(self):
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Database connection pool closed")

    @asynccontextmanager
    async def _get_connection(self):
        """Get a connection from the pool."""
        if self._pool is None:
            await self.connect()

        async with self._pool.acquire() as conn:
            yield conn

    # ==================== PICKUP QUERIES ====================

    async def get_pickup_by_id(self, pickup_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a pickup request by ID from the view.

        Args:
            pickup_id: The pickup request ID

        Returns:
            Pickup data as dict or None if not found
        """
        async with self._get_connection() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {ViewNames.PICKUPS} WHERE id = $1",
                pickup_id
            )
            return dict(row) if row else None

    async def get_pickups_by_status(
        self,
        status: Status
    ) -> List[Dict[str, Any]]:
        """
        Fetch all pickups with a specific status.

        Args:
            status: Status to filter by

        Returns:
            List of pickup records
        """
        async with self._get_connection() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM {ViewNames.PICKUPS} WHERE status = $1",
                status.value
            )
            return [dict(row) for row in rows]

    async def get_nearby_pickups(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        exclude_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch pickups within a radius of given coordinates.
        Uses PostgreSQL earth distance calculation.

        Args:
            latitude: Center latitude
            longitude: Center longitude
            radius_km: Search radius in kilometers
            exclude_id: Optional ID to exclude from results

        Returns:
            List of nearby pickup records
        """
        # Convert km to meters for earth_distance
        radius_meters = radius_km * 1000

        query = f"""
            SELECT *,
                   (6371 * acos(cos(radians($1)) * cos(radians(latitude))
                   * cos(radians(longitude) - radians($2))
                   + sin(radians($1)) * sin(radians(latitude)))) AS distance_km
            FROM {ViewNames.PICKUPS}
            WHERE (6371 * acos(cos(radians($1)) * cos(radians(latitude))
                   * cos(radians(longitude) - radians($2))
                   + sin(radians($1)) * sin(radians(latitude)))) <= $3
        """

        params = [latitude, longitude, radius_km]

        if exclude_id:
            query += " AND id != $4"
            params.append(exclude_id)

        query += " ORDER BY distance_km"

        async with self._get_connection() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def get_recent_pickups(
        self,
        hours: int = 24,
        status: Optional[Status] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch pickups created within the last N hours.

        Args:
            hours: Number of hours to look back
            status: Optional status filter

        Returns:
            List of recent pickup records
        """
        query = f"""
            SELECT * FROM {ViewNames.PICKUPS}
            WHERE requested_at >= NOW() - INTERVAL '{hours} hours'
        """

        if status:
            query += f" AND status = '{status.value}'"

        query += " ORDER BY requested_at DESC"

        async with self._get_connection() as conn:
            rows = await conn.fetch(query)
            return [dict(row) for row in rows]

    # ==================== ILLEGAL DUMP QUERIES ====================

    async def get_dump_by_id(self, dump_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch an illegal dump report by ID from the view.

        Args:
            dump_id: The dump report ID

        Returns:
            Dump data as dict or None if not found
        """
        async with self._get_connection() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {ViewNames.ILLEGAL_DUMPS} WHERE id = $1",
                dump_id
            )
            return dict(row) if row else None

    async def get_dumps_by_status(
        self,
        status: Status
    ) -> List[Dict[str, Any]]:
        """
        Fetch all dumps with a specific status.

        Args:
            status: Status to filter by

        Returns:
            List of dump records
        """
        async with self._get_connection() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM {ViewNames.ILLEGAL_DUMPS} WHERE status = $1",
                status.value
            )
            return [dict(row) for row in rows]

    async def get_nearby_dumps(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        exclude_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch dumps within a radius of given coordinates.

        Args:
            latitude: Center latitude
            longitude: Center longitude
            radius_km: Search radius in kilometers
            exclude_id: Optional ID to exclude from results

        Returns:
            List of nearby dump records
        """
        query = f"""
            SELECT *,
                   (6371 * acos(cos(radians($1)) * cos(radians(latitude))
                   * cos(radians(longitude) - radians($2))
                   + sin(radians($1)) * sin(radians(latitude)))) AS distance_km
            FROM {ViewNames.ILLEGAL_DUMPS}
            WHERE (6371 * acos(cos(radians($1)) * cos(radians(latitude))
                   * cos(radians(longitude) - radians($2))
                   + sin(radians($1)) * sin(radians(latitude)))) <= $3
        """

        params = [latitude, longitude, radius_km]

        if exclude_id:
            query += " AND id != $4"
            params.append(exclude_id)

        query += " ORDER BY distance_km"

        async with self._get_connection() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def get_recent_dumps(
        self,
        hours: int = 24,
        status: Optional[Status] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch dumps reported within the last N hours.

        Args:
            hours: Number of hours to look back
            status: Optional status filter

        Returns:
            List of recent dump records
        """
        query = f"""
            SELECT * FROM {ViewNames.ILLEGAL_DUMPS}
            WHERE reported_at >= NOW() - INTERVAL '{hours} hours'
        """

        if status:
            query += f" AND status = '{status.value}'"

        query += " ORDER BY reported_at DESC"

        async with self._get_connection() as conn:
            rows = await conn.fetch(query)
            return [dict(row) for row in rows]

    # ==================== USER/PICKER QUERIES ====================

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a user by ID from the view.

        Args:
            user_id: The user ID

        Returns:
            User data as dict or None if not found
        """
        async with self._get_connection() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {ViewNames.USERS} WHERE id = $1",
                user_id
            )
            return dict(row) if row else None

    async def get_active_pickers(self) -> List[Dict[str, Any]]:
        """
        Fetch all active pickers.

        Returns:
            List of active picker records
        """
        async with self._get_connection() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM {ViewNames.USERS}
                WHERE role = $1 AND status = $2
                """,
                Role.PICKER.value,
                AccountStatus.ACCEPTED.value
            )
            return [dict(row) for row in rows]

    async def get_picker_workload(self, picker_id: str) -> Dict[str, int]:
        """
        Get the current workload for a picker.

        Args:
            picker_id: The picker's user ID

        Returns:
            Dict with workload counts
        """
        async with self._get_connection() as conn:
            # Count assigned pickups
            pickup_count = await conn.fetchval(
                f"""
                SELECT COUNT(*) FROM {ViewNames.PICKUPS}
                WHERE picker_id = $1 AND status IN ($2, $3)
                """,
                picker_id,
                Status.ASSIGNED.value,
                Status.IN_PROGRESS.value
            )

            # Count assigned dumps
            dump_count = await conn.fetchval(
                f"""
                SELECT COUNT(*) FROM {ViewNames.ILLEGAL_DUMPS}
                WHERE assigned_picker_id = $1 AND status IN ($2, $3)
                """,
                picker_id,
                Status.ASSIGNED.value,
                Status.IN_PROGRESS.value
            )

            return {
                "active_pickups": pickup_count or 0,
                "active_dumps": dump_count or 0,
                "total": (pickup_count or 0) + (dump_count or 0)
            }

    async def get_pickers_near_location(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 10.0
    ) -> List[Dict[str, Any]]:
        """
        Get active pickers near a location (if they have route info).
        Falls back to all active pickers if no route-based filtering possible.

        Args:
            latitude: Center latitude
            longitude: Center longitude
            radius_km: Search radius

        Returns:
            List of picker records with distance info
        """
        # Get all active pickers
        pickers = await self.get_active_pickers()
        return pickers  # Route-based filtering would be done in picker assignment

    # ==================== UTILITY QUERIES ====================

    async def health_check(self) -> bool:
        """Check database connectivity."""
        try:
            async with self._get_connection() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False


# Global database service instance
db_service = DatabaseService()
