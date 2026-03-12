"""
Geographic distance utilities for the Scraply AI Agent.
Uses Haversine formula for accurate distance calculation.
"""

import math
from typing import Tuple, List, Optional
from dataclasses import dataclass


# Earth's radius in kilometers
EARTH_RADIUS_KM = 6371.0


@dataclass
class Location:
    """Represents a geographic location."""
    latitude: float
    longitude: float

    def as_tuple(self) -> Tuple[float, float]:
        return (self.latitude, self.longitude)


def haversine_distance(loc1: Location, loc2: Location) -> float:
    """
    Calculate the great-circle distance between two points on Earth
    using the Haversine formula.

    Args:
        loc1: First location (latitude, longitude)
        loc2: Second location (latitude, longitude)

    Returns:
        Distance in kilometers
    """
    lat1, lon1 = math.radians(loc1.latitude), math.radians(loc1.longitude)
    lat2, lon2 = math.radians(loc2.latitude), math.radians(loc2.longitude)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))

    return EARTH_RADIUS_KM * c


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Convenience function to calculate distance between two coordinate pairs.

    Args:
        lat1, lon1: First location coordinates
        lat2, lon2: Second location coordinates

    Returns:
        Distance in kilometers
    """
    return haversine_distance(
        Location(lat1, lon1),
        Location(lat2, lon2)
    )


def find_nearby_locations(
    center: Location,
    locations: List[Tuple[str, Location]],
    radius_km: float
) -> List[Tuple[str, Location, float]]:
    """
    Find all locations within a given radius of a center point.

    Args:
        center: The center location to search from
        locations: List of (id, location) tuples to search
        radius_km: Search radius in kilometers

    Returns:
        List of (id, location, distance) tuples for locations within radius,
        sorted by distance ascending
    """
    nearby = []

    for loc_id, location in locations:
        distance = haversine_distance(center, location)
        if distance <= radius_km:
            nearby.append((loc_id, location, distance))

    # Sort by distance
    nearby.sort(key=lambda x: x[2])
    return nearby


def find_nearest(
    center: Location,
    locations: List[Tuple[str, Location]]
) -> Optional[Tuple[str, Location, float]]:
    """
    Find the nearest location to a center point.

    Args:
        center: The center location to search from
        locations: List of (id, location) tuples to search

    Returns:
        Tuple of (id, location, distance) for the nearest location, or None if empty
    """
    if not locations:
        return None

    nearest = None
    min_distance = float('inf')

    for loc_id, location in locations:
        distance = haversine_distance(center, location)
        if distance < min_distance:
            min_distance = distance
            nearest = (loc_id, location, distance)

    return nearest


def is_within_route(
    location: Location,
    route_points: List[Location],
    max_deviation_km: float = 2.0
) -> bool:
    """
    Check if a location is within a reasonable deviation from a route.

    Args:
        location: The location to check
        route_points: List of locations defining the route
        max_deviation_km: Maximum allowed deviation from route in km

    Returns:
        True if location is near the route
    """
    if not route_points:
        return True  # No route defined, accept all

    for route_point in route_points:
        if haversine_distance(location, route_point) <= max_deviation_km:
            return True

    return False


def parse_route_string(route_string: Optional[str]) -> List[Location]:
    """
    Parse a route string in format "lat1,lon1;lat2,lon2;..." into locations.

    Args:
        route_string: Route string to parse

    Returns:
        List of Location objects
    """
    if not route_string:
        return []

    locations = []
    try:
        points = route_string.split(";")
        for point in points:
            coords = point.strip().split(",")
            if len(coords) == 2:
                lat = float(coords[0].strip())
                lon = float(coords[1].strip())
                locations.append(Location(lat, lon))
    except (ValueError, IndexError):
        pass  # Invalid format, return empty list

    return locations


def calculate_centroid(locations: List[Location]) -> Optional[Location]:
    """
    Calculate the centroid (geographic center) of a list of locations.

    Args:
        locations: List of locations

    Returns:
        Centroid location or None if empty list
    """
    if not locations:
        return None

    avg_lat = sum(loc.latitude for loc in locations) / len(locations)
    avg_lon = sum(loc.longitude for loc in locations) / len(locations)

    return Location(avg_lat, avg_lon)
