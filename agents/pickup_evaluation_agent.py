"""
Pickup Evaluation Agent for assessing pickup request validity.
Uses AI to analyze requests and detect duplicates or spam.
"""

from typing import Dict, Any, List, Optional, Any as AnyType
from datetime import datetime, timedelta

from google.adk.agents import Agent
from google.adk.runners import Runner

from agents.base_agent import BaseAgent, AgentDecision
from config.settings import settings
from config.constants import EvaluationResult, Status, ScrapCategory
from services.database_service import db_service
from utils.duplicate_utils import DuplicateDetector, detect_spam_indicators
from utils.logging_utils import logger
from utils.image_utils import analyze_image_for_request, ImageAnalysisResult


PICKUP_EVALUATION_INSTRUCTION = """
You are a pickup request evaluation agent for Scraply, a waste collection platform.
Your task is to analyze pickup requests and determine if they are valid.

For each request, you will receive:
- Request details (description, category, location, timestamp)
- Nearby existing requests
- Any spam indicators detected

You must evaluate:
1. Is the request description meaningful and related to waste collection?
2. Is the category appropriate for the described waste?
3. Are there any nearby similar requests that suggest this is a duplicate?
4. Are there any spam indicators?

Based on your analysis, you must respond with a JSON object containing:
{
    "result": "VALID" | "DUPLICATE" | "INVALID" | "SPAM",
    "confidence": <float between 0 and 1>,
    "reasoning": "<detailed explanation of your decision>",
    "action": "approve" | "reject",
    "suggested_action": "<what should be done next>"
}

Be strict about spam detection but fair about legitimate requests.
Consider that users may describe waste in various ways.
"""


class PickupEvaluationAgent(BaseAgent):
    """
    Agent specialized in evaluating pickup requests.
    Checks for validity, duplicates, and spam.
    """

    def __init__(self):
        super().__init__(
            name="PickupEvaluationAgent",
            description="Evaluates pickup requests for validity and duplicates"
        )
        self._duplicate_detector = DuplicateDetector(
            distance_threshold_km=settings.agent.duplicate_distance_km,
            time_threshold_hours=settings.agent.duplicate_time_hours
        )

    async def evaluate(self, data: Dict[str, Any]) -> AgentDecision:
        """
        Evaluate a pickup request.

        Args:
            data: Pickup request data from database

        Returns:
            AgentDecision with evaluation result
        """
        pickup_id = data.get("id", "unknown")
        logger.info(f"[PickupEvaluationAgent] Evaluating pickup {pickup_id}")

        # Step 1: Analyze image if present
        image_url = data.get("image_url") or data.get("imageUrl")
        image_analysis = None
        if image_url:
            logger.info(f"[PickupEvaluationAgent] Analyzing image for {pickup_id}")
            image_analysis, image_error = await analyze_image_for_request(
                image_url=image_url,
                description=data.get("description", ""),
                request_type="pickup"
            )
            
            if image_analysis:
                logger.info(f"[PickupEvaluationAgent] Image analysis result: {image_analysis.result.value}")
                
                # Reject if image is inappropriate or fake
                if image_analysis.result == ImageAnalysisResult.INAPPROPRIATE:
                    return AgentDecision(
                        result=EvaluationResult.INVALID,
                        confidence=image_analysis.confidence,
                        reasoning=f"Image contains inappropriate content: {image_analysis.description}",
                        action="reject",
                        details={"image_analysis": image_analysis.details}
                    )
                
                if image_analysis.result == ImageAnalysisResult.FAKE_OR_STOCK:
                    return AgentDecision(
                        result=EvaluationResult.SPAM,
                        confidence=image_analysis.confidence,
                        reasoning=f"Image appears to be fake or stock photo: {image_analysis.description}",
                        action="reject",
                        details={"image_analysis": image_analysis.details}
                    )
                
                if image_analysis.result == ImageAnalysisResult.IRRELEVANT:
                    return AgentDecision(
                        result=EvaluationResult.INVALID,
                        confidence=image_analysis.confidence,
                        reasoning=f"Image does not show waste/recyclables: {image_analysis.description}",
                        action="reject",
                        details={"image_analysis": image_analysis.details}
                    )

        # Step 2: Check for spam indicators
        is_spam, spam_reasons = detect_spam_indicators(data)
        if is_spam:
            logger.info(f"[PickupEvaluationAgent] Spam detected for {pickup_id}: {spam_reasons}")
            return AgentDecision(
                result=EvaluationResult.SPAM,
                confidence=0.9,
                reasoning=f"Spam indicators detected: {', '.join(spam_reasons)}",
                action="reject",
                details={"spam_reasons": spam_reasons}
            )

        # Step 3: Fetch nearby pickups for duplicate detection
        nearby_pickups = await self._get_nearby_pickups(
            latitude=data.get("latitude", 0),
            longitude=data.get("longitude", 0),
            exclude_id=pickup_id
        )

        # Step 4: Check for duplicates
        is_duplicate, duplicate_candidates = self._duplicate_detector.check_for_duplicates(
            new_request=data,
            existing_requests=nearby_pickups
        )

        if is_duplicate and duplicate_candidates:
            top_match = duplicate_candidates[0]
            logger.info(f"[PickupEvaluationAgent] Duplicate detected for {pickup_id}: matches {top_match.request_id}")
            return AgentDecision(
                result=EvaluationResult.DUPLICATE,
                confidence=top_match.similarity_score,
                reasoning=f"Duplicate of request {top_match.request_id}: {', '.join(top_match.reasons)}",
                action="reject",
                details={
                    "duplicate_of": top_match.request_id,
                    "similarity_score": top_match.similarity_score,
                    "distance_km": top_match.distance_km
                }
            )

        # Step 5: Use AI for deeper analysis (include image analysis results)
        ai_decision = await self._ai_evaluate(data, nearby_pickups, spam_reasons, image_analysis)

        self.log_decision(pickup_id, ai_decision)
        return ai_decision

    async def _get_nearby_pickups(
        self,
        latitude: float,
        longitude: float,
        exclude_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch nearby pickup requests for duplicate detection."""
        try:
            # Get pickups within the configured radius and time window
            nearby = await db_service.get_nearby_pickups(
                latitude=latitude,
                longitude=longitude,
                radius_km=settings.agent.duplicate_distance_km * 2,  # Wider search
                exclude_id=exclude_id
            )

            # Filter to recent ones (within time threshold)
            recent_nearby = []
            cutoff_time = datetime.now() - timedelta(hours=settings.agent.duplicate_time_hours)

            for pickup in nearby:
                requested_at = pickup.get("requested_at")
                if requested_at:
                    if isinstance(requested_at, datetime):
                        if requested_at >= cutoff_time:
                            recent_nearby.append(pickup)
                    else:
                        # Include if we can't parse the date
                        recent_nearby.append(pickup)
                else:
                    recent_nearby.append(pickup)

            return recent_nearby
        except Exception as e:
            logger.error(f"Error fetching nearby pickups: {e}")
            return []

    async def _ai_evaluate(
        self,
        data: Dict[str, Any],
        nearby_pickups: List[Dict[str, Any]],
        spam_indicators: List[str],
        image_analysis: Optional[Any] = None
    ) -> AgentDecision:
        """
        Use AI to evaluate the pickup request.

        Args:
            data: Pickup request data
            nearby_pickups: Nearby pickup requests
            spam_indicators: Any spam indicators found
            image_analysis: Optional image analysis results

        Returns:
            AgentDecision from AI analysis
        """
        # Build prompt with context
        prompt = self._build_evaluation_prompt(data, nearby_pickups, spam_indicators, image_analysis)

        try:
            # Create and run agent
            agent = self._create_agent(
                instruction=PICKUP_EVALUATION_INSTRUCTION
            )

            runner = Runner(
                agent=agent,
                app_name="scraply_pickup_evaluation"
            )

            # Run the agent
            response_content = ""
            async for event in runner.run_async(user_id="system", user_message=prompt):
                if event.is_final_response():
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            if hasattr(part, 'text'):
                                response_content += part.text

            # Parse response
            parsed = self._parse_llm_response(response_content)

            result_str = parsed.get("result", "VALID").upper()
            try:
                result = EvaluationResult(result_str)
            except ValueError:
                result = EvaluationResult.VALID

            return AgentDecision(
                result=result,
                confidence=float(parsed.get("confidence", 0.8)),
                reasoning=parsed.get("reasoning", "AI evaluation completed"),
                action=parsed.get("action", "approve" if result == EvaluationResult.VALID else "reject"),
                details={"ai_response": parsed}
            )

        except Exception as e:
            logger.error(f"AI evaluation error: {e}")
            # Default to valid if AI fails (conservative approach)
            return AgentDecision(
                result=EvaluationResult.VALID,
                confidence=0.6,
                reasoning=f"AI evaluation failed ({str(e)}), defaulting to valid",
                action="approve",
                details={"error": str(e)}
            )

    def _build_evaluation_prompt(
        self,
        data: Dict[str, Any],
        nearby_pickups: List[Dict[str, Any]],
        spam_indicators: List[str],
        image_analysis: Optional[Any] = None
    ) -> str:
        """Build the evaluation prompt for the AI."""
        prompt_parts = [
            "Please evaluate this pickup request:\n",
            f"ID: {data.get('id', 'N/A')}",
            f"Description: {data.get('description', 'N/A')}",
            f"Category: {data.get('category', 'N/A')}",
            f"Address: {data.get('address', 'N/A')}",
            f"Coordinates: ({data.get('latitude', 0)}, {data.get('longitude', 0)})",
            f"Requested At: {data.get('requested_at', 'N/A')}",
        ]

        # Add image analysis results if available
        if image_analysis:
            prompt_parts.append(f"\nImage Analysis:")
            prompt_parts.append(f"  - Result: {image_analysis.result.value}")
            prompt_parts.append(f"  - Description: {image_analysis.description}")
            prompt_parts.append(f"  - Detected Category: {image_analysis.detected_category or 'Unknown'}")
            prompt_parts.append(f"  - Confidence: {image_analysis.confidence:.2f}")
            if image_analysis.details.get('concerns'):
                prompt_parts.append(f"  - Concerns: {', '.join(image_analysis.details['concerns'])}")
        else:
            has_image = 'Yes' if data.get('image_url') or data.get('imageUrl') else 'No'
            prompt_parts.append(f"Has Image: {has_image} (not analyzed)")

        if spam_indicators:
            prompt_parts.append(f"\nSpam Indicators Found: {', '.join(spam_indicators)}")
        else:
            prompt_parts.append("\nNo spam indicators detected.")

        if nearby_pickups:
            prompt_parts.append(f"\nNearby Recent Requests ({len(nearby_pickups)}):")
            for i, nearby in enumerate(nearby_pickups[:5]):  # Limit to 5
                prompt_parts.append(
                    f"  {i+1}. ID: {nearby.get('id')}, Category: {nearby.get('category')}, "
                    f"Distance: {nearby.get('distance_km', 'N/A'):.2f}km, "
                    f"Description: {nearby.get('description', 'N/A')[:50]}..."
                )
        else:
            prompt_parts.append("\nNo nearby recent requests found.")

        prompt_parts.append("\nProvide your evaluation as a JSON object.")

        return "\n".join(prompt_parts)
