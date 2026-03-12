"""
Tests for duplicate detection utilities.
"""

import pytest
from datetime import datetime, timedelta
from utils.duplicate_utils import (
    DuplicateDetector,
    DuplicateCandidate,
    detect_spam_indicators,
    get_duplicate_check_summary
)


class TestDuplicateDetector:
    """Tests for duplicate detection."""

    @pytest.fixture
    def detector(self):
        return DuplicateDetector(
            distance_threshold_km=0.5,
            time_threshold_hours=24,
            description_similarity_threshold=0.6
        )

    def test_exact_duplicate(self, detector):
        """Test detection of exact duplicate."""
        new_request = {
            "id": "new",
            "latitude": 28.6139,
            "longitude": 77.2090,
            "category": "PLASTIC",
            "description": "Plastic bottles for recycling",
            "requested_at": datetime.now()
        }
        
        existing = [{
            "id": "existing",
            "latitude": 28.6140,  # Very close
            "longitude": 77.2091,
            "category": "PLASTIC",
            "description": "Plastic bottles for recycling",
            "requested_at": datetime.now() - timedelta(hours=1)
        }]
        
        is_dup, candidates = detector.check_for_duplicates(new_request, existing)
        
        assert is_dup
        assert len(candidates) == 1
        assert candidates[0].request_id == "existing"
        assert candidates[0].similarity_score > 0.6

    def test_no_duplicate_different_location(self, detector):
        """Test that distant requests are not duplicates."""
        new_request = {
            "id": "new",
            "latitude": 28.6139,
            "longitude": 77.2090,
            "category": "PLASTIC",
            "description": "Plastic bottles",
            "requested_at": datetime.now()
        }
        
        existing = [{
            "id": "existing",
            "latitude": 19.0760,  # Mumbai - far away
            "longitude": 72.8777,
            "category": "PLASTIC",
            "description": "Plastic bottles",
            "requested_at": datetime.now()
        }]
        
        is_dup, candidates = detector.check_for_duplicates(new_request, existing)
        
        assert not is_dup

    def test_no_duplicate_different_category(self, detector):
        """Test that different categories reduce similarity."""
        new_request = {
            "id": "new",
            "latitude": 28.6139,
            "longitude": 77.2090,
            "category": "PLASTIC",
            "description": "Waste collection",
            "requested_at": datetime.now()
        }
        
        existing = [{
            "id": "existing",
            "latitude": 28.6140,
            "longitude": 77.2091,
            "category": "METAL",  # Different category
            "description": "Waste collection",
            "requested_at": datetime.now()
        }]
        
        is_dup, candidates = detector.check_for_duplicates(new_request, existing)
        
        # Should have lower similarity
        if candidates:
            assert candidates[0].similarity_score < 0.8

    def test_excludes_same_id(self, detector):
        """Test that same ID is excluded from comparison."""
        new_request = {
            "id": "same_id",
            "latitude": 28.6139,
            "longitude": 77.2090,
            "category": "PLASTIC",
            "description": "Test",
            "requested_at": datetime.now()
        }
        
        existing = [{
            "id": "same_id",  # Same ID
            "latitude": 28.6139,
            "longitude": 77.2090,
            "category": "PLASTIC",
            "description": "Test",
            "requested_at": datetime.now()
        }]
        
        is_dup, candidates = detector.check_for_duplicates(new_request, existing)
        
        assert not is_dup
        assert len(candidates) == 0


class TestSpamIndicators:
    """Tests for spam detection."""

    def test_valid_request(self):
        """Test valid request passes spam check."""
        request = {
            "description": "I have plastic bottles and papers to recycle",
            "latitude": 28.6139,
            "longitude": 77.2090,
            "category": "PLASTIC",
            "image_url": "https://example.com/image.jpg"
        }
        
        is_spam, reasons = detect_spam_indicators(request)
        
        assert not is_spam
        assert len(reasons) == 0

    def test_short_description(self):
        """Test short description is flagged."""
        request = {
            "description": "test",  # Too short
            "latitude": 28.6139,
            "longitude": 77.2090,
            "category": "PLASTIC",
            "image_url": "https://example.com/image.jpg"
        }
        
        is_spam, reasons = detect_spam_indicators(request)
        
        assert "Description too short" in reasons

    def test_invalid_coordinates(self):
        """Test invalid coordinates are flagged."""
        request = {
            "description": "Valid description here",
            "latitude": 0,
            "longitude": 0,
            "category": "PLASTIC",
            "image_url": "https://example.com/image.jpg"
        }
        
        is_spam, reasons = detect_spam_indicators(request)
        
        assert "Invalid coordinates (0, 0)" in reasons

    def test_missing_image(self):
        """Test missing image is flagged."""
        request = {
            "description": "Valid description here",
            "latitude": 28.6139,
            "longitude": 77.2090,
            "category": "PLASTIC"
            # No image_url
        }
        
        is_spam, reasons = detect_spam_indicators(request)
        
        assert "Missing image" in reasons

    def test_multiple_indicators_spam(self):
        """Test multiple indicators trigger spam."""
        request = {
            "description": "a",  # Too short
            "latitude": 0,
            "longitude": 0,
            # Missing category and image
        }
        
        is_spam, reasons = detect_spam_indicators(request)
        
        assert is_spam
        assert len(reasons) >= 2


class TestDuplicateCheckSummary:
    """Tests for summary generation."""

    def test_no_duplicates_summary(self):
        """Test summary with no duplicates."""
        summary = get_duplicate_check_summary(False, [])
        
        assert "No potential duplicates" in summary

    def test_duplicate_detected_summary(self):
        """Test summary when duplicate is detected."""
        candidates = [
            DuplicateCandidate(
                request_id="existing123",
                similarity_score=0.85,
                distance_km=0.2,
                time_diff_hours=2,
                category_match=True,
                description_similarity=0.9,
                reasons=["Same category", "Very close"]
            )
        ]
        
        summary = get_duplicate_check_summary(True, candidates)
        
        assert "Potential duplicate detected" in summary
        assert "existing123" in summary
        assert "85%" in summary

    def test_low_risk_summary(self):
        """Test summary with low duplicate risk."""
        candidates = [
            DuplicateCandidate(
                request_id="other456",
                similarity_score=0.3,
                distance_km=2.0,
                time_diff_hours=10,
                category_match=False,
                description_similarity=0.2,
                reasons=["Somewhat nearby"]
            )
        ]
        
        summary = get_duplicate_check_summary(False, candidates)
        
        assert "Low duplicate risk" in summary
