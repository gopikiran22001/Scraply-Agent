"""
Image utilities for downloading and analyzing images using vision AI.
Uses Google Gemini for image analysis capabilities.
"""

import base64
import hashlib
import httpx
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from config.settings import settings
from utils.logging_utils import logger


class ImageAnalysisResult(str, Enum):
    """Result of image content analysis."""
    VALID_WASTE = "valid_waste"
    VALID_DUMPING = "valid_dumping"
    IRRELEVANT = "irrelevant"
    FAKE_OR_STOCK = "fake_or_stock"
    INAPPROPRIATE = "inappropriate"
    UNREADABLE = "unreadable"
    ERROR = "error"


@dataclass
class ImageAnalysis:
    """Result of image analysis."""
    result: ImageAnalysisResult
    confidence: float
    description: str
    detected_category: Optional[str]
    is_valid: bool
    details: Dict[str, Any]
    image_hash: Optional[str]


async def download_image(url: str, max_size_mb: float = 4.0) -> Optional[bytes]:
    """
    Download an image from URL.

    Args:
        url: Image URL (e.g., Cloudinary URL)
        max_size_mb: Maximum allowed file size in MB

    Returns:
        Image bytes or None if download fails
    """
    if not url:
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()

            # Check content length
            content_length = response.headers.get("content-length")
            if content_length:
                size_mb = int(content_length) / (1024 * 1024)
                if size_mb > max_size_mb:
                    logger.warning(f"Image too large: {size_mb:.2f}MB > {max_size_mb}MB")
                    return None

            # Check actual size
            image_data = response.content
            actual_size_mb = len(image_data) / (1024 * 1024)
            if actual_size_mb > max_size_mb:
                logger.warning(f"Image too large: {actual_size_mb:.2f}MB > {max_size_mb}MB")
                return None

            return image_data

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error downloading image from {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error downloading image from {url}: {e}")
        return None


def get_image_hash(image_data: bytes) -> str:
    """
    Generate a hash of image data for duplicate detection.

    Args:
        image_data: Raw image bytes

    Returns:
        SHA256 hash of the image
    """
    return hashlib.sha256(image_data).hexdigest()


def encode_image_base64(image_data: bytes) -> str:
    """
    Encode image bytes to base64 string.

    Args:
        image_data: Raw image bytes

    Returns:
        Base64 encoded string
    """
    return base64.b64encode(image_data).decode("utf-8")


def get_image_mime_type(image_data: bytes) -> str:
    """
    Detect image MIME type from bytes.

    Args:
        image_data: Raw image bytes

    Returns:
        MIME type string
    """
    # Check magic bytes
    if image_data[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    elif image_data[:2] == b'\xff\xd8':
        return "image/jpeg"
    elif image_data[:6] in (b'GIF87a', b'GIF89a'):
        return "image/gif"
    elif image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
        return "image/webp"
    else:
        return "image/jpeg"  # Default assumption


class VisionService:
    """
    Service for analyzing images using Google Gemini vision model.
    """

    def __init__(self):
        self._client = None
        self._model = None

    def _get_client(self):
        """Get or create the Gemini client."""
        if self._client is None:
            try:
                import google.generativeai as genai
                genai.configure(api_key=settings.vision.api_key)
                self._client = genai
                self._model = genai.GenerativeModel(settings.vision.model)
            except ImportError:
                logger.error("google-generativeai package not installed")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")
                raise
        return self._client, self._model

    async def analyze_waste_image(
        self,
        image_data: bytes,
        context: str = "",
        request_type: str = "pickup"
    ) -> ImageAnalysis:
        """
        Analyze an image to determine if it shows valid waste/dumping.

        Args:
            image_data: Raw image bytes
            context: Additional context (e.g., user description)
            request_type: "pickup" or "dump"

        Returns:
            ImageAnalysis with results
        """
        if not settings.vision.enabled:
            return ImageAnalysis(
                result=ImageAnalysisResult.ERROR,
                confidence=0.0,
                description="Vision analysis disabled",
                detected_category=None,
                is_valid=True,  # Default to valid when vision disabled
                details={"reason": "vision_disabled"},
                image_hash=None
            )

        if not settings.vision.api_key:
            logger.warning("Vision API key not configured")
            return ImageAnalysis(
                result=ImageAnalysisResult.ERROR,
                confidence=0.0,
                description="Vision API key not configured",
                detected_category=None,
                is_valid=True,
                details={"reason": "no_api_key"},
                image_hash=None
            )

        try:
            _, model = self._get_client()

            # Get image hash for duplicate detection
            image_hash = get_image_hash(image_data)

            # Build the prompt based on request type
            if request_type == "pickup":
                prompt = self._build_pickup_vision_prompt(context)
            else:
                prompt = self._build_dump_vision_prompt(context)

            # Create image part for Gemini
            import PIL.Image
            import io
            image = PIL.Image.open(io.BytesIO(image_data))

            # Generate response
            response = model.generate_content([prompt, image])

            # Parse the response
            return self._parse_vision_response(response.text, image_hash)

        except Exception as e:
            logger.error(f"Vision analysis error: {e}")
            return ImageAnalysis(
                result=ImageAnalysisResult.ERROR,
                confidence=0.0,
                description=f"Analysis failed: {str(e)}",
                detected_category=None,
                is_valid=True,  # Default to valid on error (conservative)
                details={"error": str(e)},
                image_hash=get_image_hash(image_data) if image_data else None
            )

    def _build_pickup_vision_prompt(self, context: str) -> str:
        """Build vision prompt for pickup request validation."""
        return f"""Analyze this image for a waste pickup request.

User's description: {context if context else "Not provided"}

Determine:
1. Does the image show actual waste/recyclable materials that need to be picked up?
2. What category of waste is shown? (PLASTIC, PAPER, METAL, ELECTRONICS, GLASS, ORGANIC, MIXED)
3. Is this a real photo or a stock/fake image?
4. Is the image appropriate (not inappropriate content)?

Respond in JSON format:
{{
    "shows_waste": true/false,
    "waste_category": "CATEGORY or null",
    "is_real_photo": true/false,
    "is_appropriate": true/false,
    "confidence": 0.0-1.0,
    "description": "Brief description of what the image shows",
    "concerns": ["list of any concerns"]
}}"""

    def _build_dump_vision_prompt(self, context: str) -> str:
        """Build vision prompt for illegal dumping report validation."""
        return f"""Analyze this image for an illegal dumping report.

User's description: {context if context else "Not provided"}

Determine:
1. Does the image show illegal dumping/littering in a public or unauthorized area?
2. What category of waste is shown? (PLASTIC, PAPER, METAL, ELECTRONICS, GLASS, ORGANIC, MIXED)
3. Is this a real photo or a stock/fake image?
4. Is the image appropriate (not inappropriate content)?
5. How severe does the dumping appear? (low, medium, high)

Respond in JSON format:
{{
    "shows_dumping": true/false,
    "waste_category": "CATEGORY or null",
    "is_real_photo": true/false,
    "is_appropriate": true/false,
    "severity": "low/medium/high",
    "confidence": 0.0-1.0,
    "description": "Brief description of what the image shows",
    "concerns": ["list of any concerns"]
}}"""

    def _parse_vision_response(self, response_text: str, image_hash: str) -> ImageAnalysis:
        """Parse the vision model response."""
        import json
        import re

        try:
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                data = json.loads(json_match.group())
            else:
                raise ValueError("No JSON found in response")

            # Determine result
            shows_waste = data.get("shows_waste", data.get("shows_dumping", False))
            is_real = data.get("is_real_photo", True)
            is_appropriate = data.get("is_appropriate", True)

            if not is_appropriate:
                result = ImageAnalysisResult.INAPPROPRIATE
                is_valid = False
            elif not is_real:
                result = ImageAnalysisResult.FAKE_OR_STOCK
                is_valid = False
            elif not shows_waste:
                result = ImageAnalysisResult.IRRELEVANT
                is_valid = False
            else:
                result = ImageAnalysisResult.VALID_WASTE if "shows_waste" in data else ImageAnalysisResult.VALID_DUMPING
                is_valid = True

            return ImageAnalysis(
                result=result,
                confidence=float(data.get("confidence", 0.8)),
                description=data.get("description", "Image analyzed"),
                detected_category=data.get("waste_category"),
                is_valid=is_valid,
                details={
                    "severity": data.get("severity"),
                    "concerns": data.get("concerns", []),
                    "raw_response": data
                },
                image_hash=image_hash
            )

        except Exception as e:
            logger.error(f"Error parsing vision response: {e}")
            return ImageAnalysis(
                result=ImageAnalysisResult.ERROR,
                confidence=0.5,
                description=f"Could not parse response: {response_text[:200]}",
                detected_category=None,
                is_valid=True,  # Default to valid on parse error
                details={"parse_error": str(e), "raw_response": response_text},
                image_hash=image_hash
            )


async def analyze_image_for_request(
    image_url: Optional[str],
    description: str = "",
    request_type: str = "pickup"
) -> Tuple[Optional[ImageAnalysis], Optional[str]]:
    """
    Download and analyze an image for a pickup/dump request.

    Args:
        image_url: URL of the image (e.g., Cloudinary)
        description: User's description of the waste
        request_type: "pickup" or "dump"

    Returns:
        Tuple of (ImageAnalysis or None, error message or None)
    """
    if not image_url:
        return None, None

    if not settings.vision.enabled:
        logger.debug("Vision analysis disabled, skipping image analysis")
        return None, None

    # Download the image
    image_data = await download_image(
        image_url,
        max_size_mb=settings.vision.max_image_size_mb
    )

    if not image_data:
        return None, "Failed to download image"

    # Analyze the image
    service = VisionService()
    analysis = await service.analyze_waste_image(
        image_data=image_data,
        context=description,
        request_type=request_type
    )

    return analysis, None


# Global vision service instance
vision_service = VisionService()
