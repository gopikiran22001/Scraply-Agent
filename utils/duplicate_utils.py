"""
Duplicate detection utilities for the Scraply AI Agent.
Identifies potential duplicate requests based on multiple factors.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import re

from utils.geo_utils import Location, calculate_distance
from config.constants import ScrapCategory, EvaluationResult


@dataclass
class DuplicateCandidate:
    """Represents a potential duplicate match."""
    request_id: str
    similarity_score: float
    distance_km: float
    time_diff_hours: float
    category_match: bool
    description_similarity: float
    reasons: List[str]


class DuplicateDetector:
    """
    Detects duplicate pickup requests and illegal dumping reports
    based on geographic proximity, time window, and content similarity.
    """

    def __init__(
        self,
        distance_threshold_km: float = 0.5,
        time_threshold_hours: int = 24,
        description_similarity_threshold: float = 0.6
    ):
        """
        Initialize duplicate detector.

        Args:
            distance_threshold_km: Maximum distance in km to consider as nearby
            time_threshold_hours: Time window in hours for duplicate detection
            description_similarity_threshold: Minimum similarity score (0-1)
        """
        self.distance_threshold_km = distance_threshold_km
        self.time_threshold_hours = time_threshold_hours
        self.description_similarity_threshold = description_similarity_threshold

    def check_for_duplicates(
        self,
        new_request: Dict[str, Any],
        existing_requests: List[Dict[str, Any]]
    ) -> Tuple[bool, List[DuplicateCandidate]]:
        """
        Check if a new request is a potential duplicate of existing requests.

        Args:
            new_request: The new request to check
            existing_requests: List of existing requests to compare against

        Returns:
            Tuple of (is_duplicate, list of duplicate candidates)
        """
        candidates = []
        new_location = Location(
            new_request.get("latitude", 0),
            new_request.get("longitude", 0)
        )
        new_time = self._parse_datetime(new_request.get("created_at") or new_request.get("requested_at") or new_request.get("reported_at"))
        new_category = new_request.get("category", "")
        new_description = new_request.get("description", "")

        for existing in existing_requests:
            # Skip same request
            if existing.get("id") == new_request.get("id"):
                continue

            existing_location = Location(
                existing.get("latitude", 0),
                existing.get("longitude", 0)
            )
            existing_time = self._parse_datetime(existing.get("created_at") or existing.get("requested_at") or existing.get("reported_at"))
            existing_category = existing.get("category", "")
            existing_description = existing.get("description", "")

            # Calculate metrics
            distance = calculate_distance(
                new_location.latitude, new_location.longitude,
                existing_location.latitude, existing_location.longitude
            )

            time_diff = self._calculate_time_diff_hours(new_time, existing_time)
            category_match = new_category == existing_category
            desc_similarity = self._calculate_description_similarity(
                new_description, existing_description
            )

            # Check if this could be a duplicate
            reasons = []
            score = 0.0

            # Geographic proximity (highest weight)
            if distance <= self.distance_threshold_km:
                reasons.append(f"Within {distance:.2f}km distance threshold")
                score += 0.4 * (1 - distance / self.distance_threshold_km)

            # Time proximity
            if time_diff is not None and time_diff <= self.time_threshold_hours:
                reasons.append(f"Within {time_diff:.1f}h time window")
                score += 0.2 * (1 - time_diff / self.time_threshold_hours)

            # Category match
            if category_match:
                reasons.append(f"Same category: {existing_category}")
                score += 0.2

            # Description similarity
            if desc_similarity >= self.description_similarity_threshold:
                reasons.append(f"Description similarity: {desc_similarity:.0%}")
                score += 0.2 * desc_similarity

            # Only include as candidate if there are matches
            if reasons and score > 0.3:
                candidates.append(DuplicateCandidate(
                    request_id=existing.get("id", ""),
                    similarity_score=score,
                    distance_km=distance,
                    time_diff_hours=time_diff if time_diff else float('inf'),
                    category_match=category_match,
                    description_similarity=desc_similarity,
                    reasons=reasons
                ))

        # Sort by similarity score
        candidates.sort(key=lambda x: x.similarity_score, reverse=True)

        # Consider it a duplicate if top candidate has high score
        is_duplicate = bool(candidates and candidates[0].similarity_score >= 0.6)

        return is_duplicate, candidates

    def _calculate_description_similarity(
        self,
        desc1: str,
        desc2: str
    ) -> float:
        """
        Calculate similarity between two descriptions using word overlap.

        Args:
            desc1: First description
            desc2: Second description

        Returns:
            Similarity score between 0 and 1
        """
        if not desc1 or not desc2:
            return 0.0

        # Normalize and tokenize
        words1 = set(self._tokenize(desc1))
        words2 = set(self._tokenize(desc2))

        if not words1 or not words2:
            return 0.0

        # Jaccard similarity
        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into lowercase words."""
        # Remove special chars and split
        text = re.sub(r'[^\w\s]', ' ', text.lower())
        words = text.split()
        # Filter short words
        return [w for w in words if len(w) > 2]

    def _parse_datetime(self, dt_value: Any) -> Optional[datetime]:
        """Parse datetime from various formats."""
        if dt_value is None:
            return None

        if isinstance(dt_value, datetime):
            return dt_value

        if isinstance(dt_value, str):
            try:
                # ISO format
                return datetime.fromisoformat(dt_value.replace('Z', '+00:00'))
            except ValueError:
                pass

            try:
                # Common format
                return datetime.strptime(dt_value, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass

        return None

    def _calculate_time_diff_hours(
        self,
        time1: Optional[datetime],
        time2: Optional[datetime]
    ) -> Optional[float]:
        """Calculate time difference in hours."""
        if time1 is None or time2 is None:
            return None

        diff = abs((time1 - time2).total_seconds())
        return diff / 3600


def detect_spam_indicators(request: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Check for spam indicators in a request.

    Args:
        request: Request data to check

    Returns:
        Tuple of (is_spam, list of reasons)
    """
    reasons = []
    spam_score = 0

    description = request.get("description", "")

    # Check for very short description
    if len(description) < 10:
        reasons.append("Description too short")
        spam_score += 1

    # Check for excessive repetition
    words = description.lower().split()
    if words and len(set(words)) / len(words) < 0.3:
        reasons.append("Excessive word repetition")
        spam_score += 1

    # Check for invalid coordinates
    lat = request.get("latitude", 0)
    lon = request.get("longitude", 0)
    if lat == 0 and lon == 0:
        reasons.append("Invalid coordinates (0, 0)")
        spam_score += 1

    # Check for unrealistic coordinates
    if abs(lat) > 90 or abs(lon) > 180:
        reasons.append("Coordinates out of valid range")
        spam_score += 1

    # Check for missing required fields
    if not request.get("category"):
        reasons.append("Missing category")
        spam_score += 1

    if not request.get("image_url") and not request.get("imageUrl"):
        reasons.append("Missing image")
        spam_score += 1

    is_spam = spam_score >= 2
    return is_spam, reasons


def get_duplicate_check_summary(
    is_duplicate: bool,
    candidates: List[DuplicateCandidate]
) -> str:
    """
    Generate a human-readable summary of duplicate check results.

    Args:
        is_duplicate: Whether a duplicate was detected
        candidates: List of duplicate candidates

    Returns:
        Summary string
    """
    if not candidates:
        return "No potential duplicates found."

    top = candidates[0]
    if is_duplicate:
        return (
            f"Potential duplicate detected (similarity: {top.similarity_score:.0%}). "
            f"Similar to request {top.request_id}: {', '.join(top.reasons)}"
        )
    else:
        return (
            f"Low duplicate risk (top match similarity: {top.similarity_score:.0%}). "
            f"Closest match: {top.request_id} at {top.distance_km:.2f}km"
        )
