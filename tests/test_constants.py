"""
Tests for configuration and constants.
"""

import pytest
import os
from config.constants import (
    Status,
    ScrapCategory,
    Role,
    AccountStatus,
    QueueNames,
    ViewNames,
    VehicleType,
    EvaluationResult,
    CATEGORY_VEHICLE_REQUIREMENTS
)


class TestStatusEnum:
    """Tests for Status enum."""

    def test_all_statuses(self):
        """Test all status values exist."""
        assert Status.REQUESTED.value == "REQUESTED"
        assert Status.ASSIGNED.value == "ASSIGNED"
        assert Status.IN_PROGRESS.value == "IN_PROGRESS"
        assert Status.COMPLETED.value == "COMPLETED"
        assert Status.CANCELLED.value == "CANCELLED"

    def test_status_count(self):
        """Test expected number of statuses."""
        assert len(Status) == 5


class TestScrapCategory:
    """Tests for ScrapCategory enum."""

    def test_all_categories(self):
        """Test all category values exist."""
        categories = [
            "PLASTIC", "PAPER", "METAL", 
            "ELECTRONICS", "GLASS", "ORGANIC", "MIXED"
        ]
        for cat in categories:
            assert ScrapCategory(cat) is not None

    def test_category_count(self):
        """Test expected number of categories."""
        assert len(ScrapCategory) == 7


class TestRole:
    """Tests for Role enum."""

    def test_all_roles(self):
        """Test all role values exist."""
        assert Role.ADMIN.value == "ADMIN"
        assert Role.USER.value == "USER"
        assert Role.PICKER.value == "PICKER"
        assert Role.AGENT.value == "AGENT"


class TestQueueNames:
    """Tests for queue name constants."""

    def test_queue_names(self):
        """Test queue name values."""
        assert QueueNames.PICKUP_QUEUE == "pickup_queue"
        assert QueueNames.DUMP_QUEUE == "dump_queue"
        assert QueueNames.PICKUP_ASSIGN_QUEUE == "pickup_assign_queue"
        assert QueueNames.DUMP_ASSIGN_QUEUE == "dump_assign_queue"


class TestViewNames:
    """Tests for database view names."""

    def test_view_names(self):
        """Test view name values."""
        assert ViewNames.USERS == "view_users"
        assert ViewNames.PICKUPS == "view_pickups"
        assert ViewNames.ILLEGAL_DUMPS == "view_illegal_dumps"


class TestVehicleRequirements:
    """Tests for vehicle requirements mapping."""

    def test_plastic_vehicles(self):
        """Test vehicles for plastic category."""
        vehicles = CATEGORY_VEHICLE_REQUIREMENTS[ScrapCategory.PLASTIC]
        assert VehicleType.BICYCLE in vehicles
        assert VehicleType.TRUCK in vehicles

    def test_metal_requires_larger_vehicle(self):
        """Test metal requires larger vehicles."""
        vehicles = CATEGORY_VEHICLE_REQUIREMENTS[ScrapCategory.METAL]
        assert VehicleType.BICYCLE not in vehicles
        assert VehicleType.TRUCK in vehicles

    def test_all_categories_have_requirements(self):
        """Test all categories have vehicle requirements."""
        for category in ScrapCategory:
            assert category in CATEGORY_VEHICLE_REQUIREMENTS
            assert len(CATEGORY_VEHICLE_REQUIREMENTS[category]) > 0


class TestEvaluationResult:
    """Tests for evaluation result enum."""

    def test_all_results(self):
        """Test all result values exist."""
        assert EvaluationResult.VALID.value == "VALID"
        assert EvaluationResult.DUPLICATE.value == "DUPLICATE"
        assert EvaluationResult.INVALID.value == "INVALID"
        assert EvaluationResult.SPAM.value == "SPAM"
