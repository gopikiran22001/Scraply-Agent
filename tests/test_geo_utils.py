"""
Tests for geographic utility functions.
"""

import pytest
from utils.geo_utils import (
    Location,
    haversine_distance,
    calculate_distance,
    find_nearby_locations,
    find_nearest,
    parse_route_string,
    is_within_route
)


class TestHaversineDistance:
    """Tests for haversine distance calculation."""

    def test_same_point(self):
        """Distance between same point should be 0."""
        loc = Location(28.6139, 77.2090)
        distance = haversine_distance(loc, loc)
        assert distance == 0.0

    def test_known_distance(self):
        """Test with known distance between Delhi and Mumbai."""
        delhi = Location(28.6139, 77.2090)
        mumbai = Location(19.0760, 72.8777)
        
        distance = haversine_distance(delhi, mumbai)
        
        # Known distance is approximately 1150-1160 km
        assert 1100 < distance < 1200

    def test_short_distance(self):
        """Test short distance calculation."""
        loc1 = Location(28.6139, 77.2090)
        loc2 = Location(28.6149, 77.2100)  # Very close point
        
        distance = haversine_distance(loc1, loc2)
        
        # Should be less than 1 km
        assert distance < 1.0
        assert distance > 0


class TestCalculateDistance:
    """Tests for the convenience distance function."""

    def test_calculate_distance(self):
        """Test coordinate-based distance calculation."""
        distance = calculate_distance(28.6139, 77.2090, 28.7041, 77.1025)
        
        # Distance should be approximately 13-15 km
        assert 10 < distance < 20


class TestFindNearbyLocations:
    """Tests for finding nearby locations."""

    def test_find_nearby(self):
        """Test finding locations within radius."""
        center = Location(28.6139, 77.2090)
        locations = [
            ("1", Location(28.6140, 77.2091)),  # Very close
            ("2", Location(28.6200, 77.2150)),  # About 1 km
            ("3", Location(28.7041, 77.1025)),  # About 13 km
        ]
        
        nearby = find_nearby_locations(center, locations, radius_km=5.0)
        
        # Only first two should be within 5 km
        assert len(nearby) == 2
        assert nearby[0][0] == "1"  # Closest first

    def test_no_nearby(self):
        """Test when no locations are within radius."""
        center = Location(0, 0)
        locations = [
            ("1", Location(28.6139, 77.2090)),
        ]
        
        nearby = find_nearby_locations(center, locations, radius_km=1.0)
        
        assert len(nearby) == 0


class TestFindNearest:
    """Tests for finding nearest location."""

    def test_find_nearest(self):
        """Test finding nearest location."""
        center = Location(28.6139, 77.2090)
        locations = [
            ("far", Location(28.7041, 77.1025)),
            ("near", Location(28.6140, 77.2091)),
            ("medium", Location(28.6200, 77.2150)),
        ]
        
        nearest = find_nearest(center, locations)
        
        assert nearest is not None
        assert nearest[0] == "near"

    def test_empty_locations(self):
        """Test with empty location list."""
        center = Location(28.6139, 77.2090)
        
        nearest = find_nearest(center, [])
        
        assert nearest is None


class TestParseRouteString:
    """Tests for route string parsing."""

    def test_valid_route(self):
        """Test parsing valid route string."""
        route_str = "28.6139,77.2090;28.7041,77.1025;19.0760,72.8777"
        
        locations = parse_route_string(route_str)
        
        assert len(locations) == 3
        assert locations[0].latitude == 28.6139
        assert locations[0].longitude == 77.2090

    def test_empty_route(self):
        """Test parsing empty route."""
        locations = parse_route_string(None)
        assert len(locations) == 0
        
        locations = parse_route_string("")
        assert len(locations) == 0

    def test_invalid_route(self):
        """Test parsing invalid route string."""
        locations = parse_route_string("invalid,route,string")
        assert len(locations) == 0


class TestIsWithinRoute:
    """Tests for route proximity check."""

    def test_within_route(self):
        """Test location on route."""
        location = Location(28.6139, 77.2090)
        route = [
            Location(28.6139, 77.2090),  # Same point
            Location(28.7041, 77.1025),
        ]
        
        assert is_within_route(location, route, max_deviation_km=1.0)

    def test_outside_route(self):
        """Test location far from route."""
        location = Location(19.0760, 72.8777)  # Mumbai
        route = [
            Location(28.6139, 77.2090),  # Delhi
            Location(28.7041, 77.1025),
        ]
        
        assert not is_within_route(location, route, max_deviation_km=5.0)

    def test_empty_route(self):
        """Test with empty route (should accept all)."""
        location = Location(28.6139, 77.2090)
        
        assert is_within_route(location, [], max_deviation_km=1.0)
