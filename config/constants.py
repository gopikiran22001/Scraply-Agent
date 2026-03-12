"""
Constants for the Scraply AI Agent system.
Matches the backend enums and configuration.
"""

from enum import Enum


class Status(str, Enum):
    """Request status enum - matches backend Status.java"""
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ScrapCategory(str, Enum):
    """Scrap category enum - matches backend ScrapCategory.java"""
    PLASTIC = "PLASTIC"
    PAPER = "PAPER"
    METAL = "METAL"
    ELECTRONICS = "ELECTRONICS"
    GLASS = "GLASS"
    ORGANIC = "ORGANIC"
    MIXED = "MIXED"


class Role(str, Enum):
    """User role enum - matches backend Role.java"""
    ADMIN = "ADMIN"
    USER = "USER"
    PICKER = "PICKER"
    AGENT = "AGENT"


class AccountStatus(str, Enum):
    """Account status enum - matches backend AccountStatus.java"""
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# Redis queue names - matches backend QueueService.java
class QueueNames:
    PICKUP_QUEUE = "pickup_queue"
    DUMP_QUEUE = "dump_queue"
    PICKUP_ASSIGN_QUEUE = "pickup_assign_queue"
    DUMP_ASSIGN_QUEUE = "dump_assign_queue"


# Database view names
class ViewNames:
    USERS = "view_users"
    PICKUPS = "view_pickups"
    ILLEGAL_DUMPS = "view_illegal_dumps"


# Vehicle types for picker compatibility
class VehicleType(str, Enum):
    BICYCLE = "BICYCLE"
    MOTORCYCLE = "MOTORCYCLE"
    AUTO = "AUTO"
    PICKUP_TRUCK = "PICKUP_TRUCK"
    TRUCK = "TRUCK"


# Category vehicle requirements (estimated capacity needs)
CATEGORY_VEHICLE_REQUIREMENTS = {
    ScrapCategory.PLASTIC: [VehicleType.BICYCLE, VehicleType.MOTORCYCLE, VehicleType.AUTO, VehicleType.PICKUP_TRUCK, VehicleType.TRUCK],
    ScrapCategory.PAPER: [VehicleType.BICYCLE, VehicleType.MOTORCYCLE, VehicleType.AUTO, VehicleType.PICKUP_TRUCK, VehicleType.TRUCK],
    ScrapCategory.METAL: [VehicleType.AUTO, VehicleType.PICKUP_TRUCK, VehicleType.TRUCK],
    ScrapCategory.ELECTRONICS: [VehicleType.MOTORCYCLE, VehicleType.AUTO, VehicleType.PICKUP_TRUCK, VehicleType.TRUCK],
    ScrapCategory.GLASS: [VehicleType.AUTO, VehicleType.PICKUP_TRUCK, VehicleType.TRUCK],
    ScrapCategory.ORGANIC: [VehicleType.AUTO, VehicleType.PICKUP_TRUCK, VehicleType.TRUCK],
    ScrapCategory.MIXED: [VehicleType.AUTO, VehicleType.PICKUP_TRUCK, VehicleType.TRUCK],
}


# Evaluation results
class EvaluationResult(str, Enum):
    VALID = "VALID"
    DUPLICATE = "DUPLICATE"
    INVALID = "INVALID"
    SPAM = "SPAM"
