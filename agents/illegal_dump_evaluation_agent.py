"""
Illegal Dump Evaluation Agent for assessing dump report validity.
Uses AI to analyze reports and detect duplicates or false reports.
"""

from typing import Dict, Any, List, Optional, Any as AnyType
from datetime import datetime, timedelta

from google.adk.agents import Agent
from google.adk.runners import Runner

from agents.base_agent import BaseAgent, AgentDecision
from config.settings import settings
from config.constants import EvaluationResult, Status
from services.database_service import db_service
from utils.duplicate_utils import DuplicateDetector, detect_spam_indicators
from utils.logging_utils import logger
from utils.image_utils import analyze_image_for_request, ImageAnalysisResult


DUMP_EVALUATION_INSTRUCTION = """
You are an illegal dumping report evaluation agent for Scraply, an environmental protection platform.
Your task is to analyze illegal dumping reports and determine if they are valid and genuine.

For each report, you will receive:
- Report details (description, category, location, landmark, timestamp)
- Nearby existing reports
- Any spam indicators detected

You must evaluate:
1. Is the report description meaningful and indicates actual illegal dumping?
2. Is the category appropriate for the described waste?
3. Does the location information make sense?
4. Are there any nearby similar reports that suggest this is a duplicate?
5. Does this appear to be a false or spam report?

Based on your analysis, you must respond with a JSON object containing:
{
    "result": "VALID" | "DUPLICATE" | "INVALID" | "SPAM",
    "confidence": <float between 0 and 1>,
    "reasoning": "<detailed explanation of your decision>",
    "action": "approve" | "reject",
    "priority": "high" | "medium" | "low",
    "suggested_action": "<what should be done next>"
}

Illegal dumping is a serious environmental concern. Be thorough but fair in your evaluation.
High priority should be given to reports near water bodies, schools, or residential areas.
"""


class IllegalDumpEvaluationAgent(BaseAgent):
    """
    Agent specialized in evaluating illegal dumping reports.
    Checks for validity, duplicates, and false reports.
    """

    def __init__(self):
        super().__init__(
            name="IllegalDumpEvaluationAgent",
            description="Evaluates illegal dumping reports for validity"
        )
        self._duplicate_detector = DuplicateDetector(
            distance_threshold_km=settings.agent.duplicate_distance_km,
            time_threshold_hours=settings.agent.duplicate_time_hours,
            description_similarity_threshold=0.5  # Lower threshold for dumps
        )

    async def evaluate(self, data: Dict[str, Any]) -> AgentDecision:
        """
        Evaluate an illegal dumping report.

        Args:
            data: Dump report data from database

        Returns:
            AgentDecision with evaluation result
        """
        dump_id = data.get("id", "unknown")
        logger.info(f"[IllegalDumpEvaluationAgent] Evaluating dump report {dump_id}")

        # Step 1: Analyze image if present
        image_url = data.get("image_url") or data.get("imageUrl")
        image_analysis = None
        if image_url:
            logger.info(f"[IllegalDumpEvaluationAgent] Analyzing image for {dump_id}")
            image_analysis, image_error = await analyze_image_for_request(
                image_url=image_url,
                description=data.get("description", ""),
                request_type="dump"
            )
            
            if image_analysis:
                logger.info(f"[IllegalDumpEvaluationAgent] Image analysis result: {image_analysis.result.value}")
                
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
                        reasoning=f"Image does not show illegal dumping: {image_analysis.description}",
                        action="reject",
                        details={"image_analysis": image_analysis.details}
                    )

        # Step 2: Check for spam indicators
        is_spam, spam_reasons = detect_spam_indicators(data)
        if is_spam:
            logger.info(f"[IllegalDumpEvaluationAgent] Spam detected for {dump_id}: {spam_reasons}")
            return AgentDecision(
                result=EvaluationResult.SPAM,
                confidence=0.9,
                reasoning=f"Spam indicators detected: {', '.join(spam_reasons)}",
                action="reject",
                details={"spam_reasons": spam_reasons}
            )

        # Step 3: Fetch nearby dump reports for duplicate detection
        nearby_dumps = await self._get_nearby_dumps(
            latitude=data.get("latitude", 0),
            longitude=data.get("longitude", 0),
            exclude_id=dump_id
        )

        # Step 3: Check for duplicates
        is_duplicate, duplicate_candidates = self._duplicate_detector.check_for_duplicates(
            new_request=data,
            existing_requests=nearby_dumps
        )

        # Step 4: Check for duplicates - also compare image hashes if available
        if is_duplicate and duplicate_candidates:
            top_match = duplicate_candidates[0]
            logger.info(f"[IllegalDumpEvaluationAgent] Duplicate detected for {dump_id}: matches {top_match.request_id}")
            return AgentDecision(
                result=EvaluationResult.DUPLICATE,
                confidence=top_match.similarity_score,
                reasoning=f"Duplicate of report {top_match.request_id}: {', '.join(top_match.reasons)}",
                action="reject",
                details={
                    "duplicate_of": top_match.request_id,
                    "similarity_score": top_match.similarity_score,
                    "distance_km": top_match.distance_km
                }
            )

        # Step 5: Use AI for deeper analysis (include image analysis results)
        ai_decision = await self._ai_evaluate(data, nearby_dumps, spam_reasons, image_analysis)

        self.log_decision(dump_id, ai_decision)
        return ai_decision

    async def _get_nearby_dumps(
        self,
        latitude: float,
        longitude: float,
        exclude_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch nearby dump reports for duplicate detection."""
        try:
            nearby = await db_service.get_nearby_dumps(
                latitude=latitude,
                longitude=longitude,
                radius_km=settings.agent.duplicate_distance_km * 2,
                exclude_id=exclude_id
            )

            # Filter to recent ones
            recent_nearby = []
            cutoff_time = datetime.now() - timedelta(hours=settings.agent.duplicate_time_hours)

            for dump in nearby:
                reported_at = dump.get("reported_at")
                if reported_at:
                    if isinstance(reported_at, datetime):
                        if reported_at >= cutoff_time:
                            recent_nearby.append(dump)
                    else:
                        recent_nearby.append(dump)
                else:
                    recent_nearby.append(dump)

            return recent_nearby
        except Exception as e:
            logger.error(f"Error fetching nearby dumps: {e}")
            return []

    async def _ai_evaluate(
        self,
        data: Dict[str, Any],
        nearby_dumps: List[Dict[str, Any]],
        spam_indicators: List[str],
        image_analysis: Optional[AnyType] = None
    ) -> AgentDecision:
        """
        Use AI to evaluate the illegal dump report.

        Args:
            data: Dump report data
            nearby_dumps: Nearby dump reports
            spam_indicators: Any spam indicators found
            image_analysis: Optional image analysis results

        Returns:
            AgentDecision from AI analysis
        """
        prompt = self._build_evaluation_prompt(data, nearby_dumps, spam_indicators, image_analysis)

        try:
            agent = self._create_agent(
                instruction=DUMP_EVALUATION_INSTRUCTION
            )

            runner = Runner(
                agent=agent,
                app_name="scraply_dump_evaluation"
            )

            response_content = ""
            async for event in runner.run_async(user_id="system", user_message=prompt):
                if event.is_final_response():
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            if hasattr(part, 'text'):
                                response_content += part.text

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
                details={
                    "ai_response": parsed,
                    "priority": parsed.get("priority", "medium")
                }
            )

        except Exception as e:
            logger.error(f"AI evaluation error: {e}")
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
        nearby_dumps: List[Dict[str, Any]],
        spam_indicators: List[str],
        image_analysis: Optional[AnyType] = None
    ) -> str:
        """Build the evaluation prompt for the AI."""
        prompt_parts = [
            "Please evaluate this illegal dumping report:\n",
            f"ID: {data.get('id', 'N/A')}",
            f"Description: {data.get('description', 'N/A')}",
            f"Category: {data.get('category', 'N/A')}",
            f"Address: {data.get('address', 'N/A')}",
            f"Landmark: {data.get('landmark', 'N/A')}",
            f"Coordinates: ({data.get('latitude', 0)}, {data.get('longitude', 0)})",
            f"Reported At: {data.get('reported_at', 'N/A')}",
        ]

        # Add image analysis results if available
        if image_analysis:
            prompt_parts.append(f"\nImage Analysis:")
            prompt_parts.append(f"  - Result: {image_analysis.result.value}")
            prompt_parts.append(f"  - Description: {image_analysis.description}")
            prompt_parts.append(f"  - Detected Category: {image_analysis.detected_category or 'Unknown'}")
            prompt_parts.append(f"  - Confidence: {image_analysis.confidence:.2f}")
            if image_analysis.details.get('severity'):
                prompt_parts.append(f"  - Severity: {image_analysis.details['severity']}")
            if image_analysis.details.get('concerns'):
                prompt_parts.append(f"  - Concerns: {', '.join(image_analysis.details['concerns'])}")
        else:
            has_image = 'Yes' if data.get('image_url') or data.get('imageUrl') else 'No'
            prompt_parts.append(f"Has Image: {has_image} (not analyzed)")

        if spam_indicators:
            prompt_parts.append(f"\nSpam Indicators Found: {', '.join(spam_indicators)}")
        else:
            prompt_parts.append("\nNo spam indicators detected.")

        if nearby_dumps:
            prompt_parts.append(f"\nNearby Recent Reports ({len(nearby_dumps)}):")
            for i, nearby in enumerate(nearby_dumps[:5]):
                prompt_parts.append(
                    f"  {i+1}. ID: {nearby.get('id')}, Category: {nearby.get('category')}, "
                    f"Status: {nearby.get('status')}, "
                    f"Distance: {nearby.get('distance_km', 'N/A'):.2f}km"
                )
        else:
            prompt_parts.append("\nNo nearby recent reports found.")

        prompt_parts.append("\nProvide your evaluation as a JSON object.")

        return "\n".join(prompt_parts)
