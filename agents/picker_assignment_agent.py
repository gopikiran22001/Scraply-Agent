"""
Picker Assignment Agent for selecting the optimal picker for a request.
Uses AI to analyze picker availability, location, and workload.
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from google.adk.agents import Agent

from agents.base_agent import BaseAgent, AgentDecision
from config.settings import settings
from config.constants import (
    EvaluationResult, Role, AccountStatus, ScrapCategory,
    VehicleType, CATEGORY_VEHICLE_REQUIREMENTS
)
from services.database_service import db_service
from utils.geo_utils import (
    Location, calculate_distance, parse_route_string,
    is_within_route
)
from utils.logging_utils import logger


@dataclass
class PickerScore:
    """Represents a picker's suitability score."""
    picker_id: str
    picker_name: str
    total_score: float
    distance_score: float
    workload_score: float
    vehicle_score: float
    route_score: float
    distance_km: Optional[float]
    current_workload: int
    reasoning: str


PICKER_ASSIGNMENT_INSTRUCTION = """
You are a picker assignment agent for Scraply, a waste collection platform.
Your task is to select the best available picker for a request based on multiple factors.

For each request, you will receive:
- Request details (location, category, description)
- Available pickers with their details (location, vehicle type, current workload, route)

Selection criteria (in order of importance):
1. Vehicle compatibility - picker must have appropriate vehicle for the waste category
2. Geographic proximity - closer pickers are preferred
3. Route compatibility - picker's route should pass near the request location
4. Workload balance - prefer pickers with fewer active assignments

You must respond with a JSON object containing:
{
    "selected_picker_id": "<picker ID or null if no suitable picker>",
    "confidence": <float between 0 and 1>,
    "reasoning": "<detailed explanation of your selection>",
    "alternative_pickers": [<list of alternative picker IDs if available>]
}

If no picker is suitable, set selected_picker_id to null and explain why.
"""


class PickerAssignmentAgent(BaseAgent):
    """
    Agent specialized in selecting the optimal picker for requests.
    Considers multiple factors including distance, vehicle, and workload.
    """

    def __init__(self):
        super().__init__(
            name="PickerAssignmentAgent",
            description="Assigns optimal picker for pickup requests and dump reports"
        )

    async def evaluate(self, data: Dict[str, Any]) -> AgentDecision:
        """
        Evaluate and select the best picker for a request.

        Args:
            data: Request data including location and category

        Returns:
            AgentDecision with selected picker
        """
        request_id = data.get("id", "unknown")
        request_type = data.get("request_type", "pickup")
        logger.info(f"[PickerAssignmentAgent] Selecting picker for {request_type} {request_id}")

        # Get request location
        request_location = Location(
            latitude=data.get("latitude", 0),
            longitude=data.get("longitude", 0)
        )
        category = data.get("category")
        pin_code = data.get("pin_code")

        # Fetch available pickers
        pickers = await db_service.get_active_pickers()

        if not pickers:
            logger.warning(f"[PickerAssignmentAgent] No active pickers available")
            return AgentDecision(
                result=EvaluationResult.INVALID,
                confidence=1.0,
                reasoning="No active pickers available in the system",
                action="defer",
                details={"error": "no_pickers_available"}
            )

        # Score each picker
        scored_pickers = await self._score_pickers(
            pickers=pickers,
            request_location=request_location,
            category=category,
            request_pin_code=pin_code
        )

        # Filter out unsuitable pickers
        suitable_pickers = [p for p in scored_pickers if p.total_score > 0.2]

        if not suitable_pickers:
            logger.warning(f"[PickerAssignmentAgent] No suitable pickers for {request_id}")
            return AgentDecision(
                result=EvaluationResult.INVALID,
                confidence=0.9,
                reasoning="No pickers meet the requirements for this request",
                action="defer",
                details={
                    "total_pickers": len(pickers),
                    "reason": "no_suitable_pickers"
                }
            )

        # Sort by score descending
        suitable_pickers.sort(key=lambda x: x.total_score, reverse=True)

        # Get AI recommendation for final selection
        ai_decision = await self._ai_select_picker(
            data=data,
            scored_pickers=suitable_pickers[:5]  # Top 5 candidates
        )

        self.log_decision(request_id, ai_decision)
        return ai_decision

    async def _score_pickers(
        self,
        pickers: List[Dict[str, Any]],
        request_location: Location,
        category: Optional[str],
        request_pin_code: Optional[int] = None
    ) -> List[PickerScore]:
        """
        Score each picker based on multiple criteria.

        Args:
            pickers: List of picker records
            request_location: Location of the request
            category: Waste category
            request_pin_code: PIN code of the request location

        Returns:
            List of PickerScore objects
        """
        scored = []

        # Get vehicle requirements for category
        required_vehicles = []
        if category:
            try:
                cat_enum = ScrapCategory(category)
                required_vehicles = CATEGORY_VEHICLE_REQUIREMENTS.get(cat_enum, [])
            except ValueError:
                pass

        for picker in pickers:
            picker_id = picker.get("id", "")
            picker_name = picker.get("name", "Unknown")

            # Get workload
            workload = await db_service.get_picker_workload(picker_id)
            current_workload = workload.get("total", 0)

            # Calculate distance (if picker has location in route)
            route_string = picker.get("pick_up_route") or picker.get("pickUpRoute")
            route_points = parse_route_string(route_string)

            distance_km = None
            distance_score = 0.5  # Default if no route

            if route_points:
                # Use first route point as picker's base location
                picker_location = route_points[0]
                distance_km = calculate_distance(
                    request_location.latitude, request_location.longitude,
                    picker_location.latitude, picker_location.longitude
                )
                # Score: closer is better (max 1.0 at 0km, min 0 at 50km)
                distance_score = max(0, 1 - (distance_km / 50))

            # Vehicle compatibility score
            vehicle_type = picker.get("vehicle_type") or picker.get("vehicleType")
            vehicle_score = 0.5  # Default
            if vehicle_type and required_vehicles:
                try:
                    picker_vehicle = VehicleType(vehicle_type)
                    vehicle_score = 1.0 if picker_vehicle in required_vehicles else 0.1
                except ValueError:
                    vehicle_score = 0.3  # Unknown vehicle type

            # Route compatibility score
            route_score = 0.5  # Default
            if route_points:
                if is_within_route(request_location, route_points, max_deviation_km=5.0):
                    route_score = 1.0
                else:
                    route_score = 0.3

            # Workload score (fewer assignments = higher score)
            workload_score = max(0, 1 - (current_workload / 10))

            # PIN code area match score
            area_score = 0.5  # Default
            picker_pin_code = picker.get("pin_code")
            if request_pin_code and picker_pin_code:
                if picker_pin_code == request_pin_code:
                    area_score = 1.0  # Same PIN code = same area
                elif str(picker_pin_code)[:3] == str(request_pin_code)[:3]:
                    area_score = 0.7  # Same district (first 3 digits match)

            # Calculate total score (weighted)
            total_score = (
                vehicle_score * 0.25 +   # Vehicle compatibility
                distance_score * 0.25 +  # Geographic proximity
                route_score * 0.15 +     # Route compatibility
                workload_score * 0.20 +  # Workload balance
                area_score * 0.15        # PIN code area match
            )

            # Build reasoning
            reasoning_parts = []
            if vehicle_score >= 0.8:
                reasoning_parts.append("suitable vehicle")
            if distance_km and distance_km < 10:
                reasoning_parts.append(f"close ({distance_km:.1f}km)")
            if route_score >= 0.8:
                reasoning_parts.append("on route")
            if workload_score >= 0.7:
                reasoning_parts.append(f"low workload ({current_workload} tasks)")
            if area_score >= 0.8:
                reasoning_parts.append("same area")

            scored.append(PickerScore(
                picker_id=picker_id,
                picker_name=picker_name,
                total_score=total_score,
                distance_score=distance_score,
                workload_score=workload_score,
                vehicle_score=vehicle_score,
                route_score=route_score,
                distance_km=distance_km,
                current_workload=current_workload,
                reasoning=", ".join(reasoning_parts) if reasoning_parts else "average match"
            ))

        return scored

    async def _ai_select_picker(
        self,
        data: Dict[str, Any],
        scored_pickers: List[PickerScore]
    ) -> AgentDecision:
        """
        Use AI to make final picker selection from top candidates.

        Args:
            data: Request data
            scored_pickers: Pre-scored picker candidates

        Returns:
            AgentDecision with selected picker
        """
        prompt = self._build_selection_prompt(data, scored_pickers)

        try:
            response_content = await self._run_prompt(
                instruction=PICKER_ASSIGNMENT_INSTRUCTION,
                prompt=prompt,
                app_name="scraply_picker_assignment",
            )

            parsed = self._parse_llm_response(response_content)

            selected_id = parsed.get("selected_picker_id")

            if selected_id:
                # Find the selected picker's info
                selected = next(
                    (p for p in scored_pickers if p.picker_id == selected_id),
                    scored_pickers[0] if scored_pickers else None
                )

                if selected:
                    return AgentDecision(
                        result=EvaluationResult.VALID,
                        confidence=float(parsed.get("confidence", 0.8)),
                        reasoning=parsed.get("reasoning", f"Selected picker {selected.picker_name}"),
                        action="assign",
                        details={
                            "picker_id": selected.picker_id,
                            "picker_name": selected.picker_name,
                            "score": selected.total_score,
                            "distance_km": selected.distance_km,
                            "alternatives": parsed.get("alternative_pickers", [])
                        }
                    )

            # No picker selected by AI, use highest scored
            if scored_pickers:
                best = scored_pickers[0]
                return AgentDecision(
                    result=EvaluationResult.VALID,
                    confidence=best.total_score,
                    reasoning=f"Selected {best.picker_name} based on score ({best.reasoning})",
                    action="assign",
                    details={
                        "picker_id": best.picker_id,
                        "picker_name": best.picker_name,
                        "score": best.total_score,
                        "distance_km": best.distance_km
                    }
                )

            return AgentDecision(
                result=EvaluationResult.INVALID,
                confidence=0.9,
                reasoning="AI could not select a suitable picker",
                action="defer",
                details={"error": "no_selection"}
            )

        except Exception as e:
            logger.error(f"AI picker selection error: {e}")
            # Fallback to highest scored picker
            if scored_pickers:
                best = scored_pickers[0]
                return AgentDecision(
                    result=EvaluationResult.VALID,
                    confidence=best.total_score * 0.8,
                    reasoning=f"Fallback selection: {best.picker_name} (AI error: {str(e)})",
                    action="assign",
                    details={
                        "picker_id": best.picker_id,
                        "picker_name": best.picker_name,
                        "score": best.total_score
                    }
                )

            return AgentDecision(
                result=EvaluationResult.INVALID,
                confidence=0.5,
                reasoning=f"AI selection failed and no fallback available: {str(e)}",
                action="defer",
                details={"error": str(e)}
            )

    def _build_selection_prompt(
        self,
        data: Dict[str, Any],
        scored_pickers: List[PickerScore]
    ) -> str:
        """Build the selection prompt for the AI."""
        prompt_parts = [
            "Please select the best picker for this request:\n",
            f"Request ID: {data.get('id', 'N/A')}",
            f"Type: {data.get('request_type', 'pickup')}",
            f"Description: {data.get('description', 'N/A')}",
            f"Category: {data.get('category', 'N/A')}",
            f"Location: ({data.get('latitude', 0)}, {data.get('longitude', 0)})",
            f"Address: {data.get('address', 'N/A')}",
            "\nAvailable Pickers (ranked by initial score):"
        ]

        for i, picker in enumerate(scored_pickers):
            distance_str = f"{picker.distance_km:.1f}km" if picker.distance_km else "unknown"
            prompt_parts.append(
                f"\n{i+1}. {picker.picker_name} (ID: {picker.picker_id})"
                f"\n   Score: {picker.total_score:.2f}"
                f"\n   Distance: {distance_str}"
                f"\n   Current Workload: {picker.current_workload} tasks"
                f"\n   Factors: {picker.reasoning}"
            )

        prompt_parts.append("\nProvide your selection as a JSON object.")

        return "\n".join(prompt_parts)

    async def select_picker(
        self,
        request_data: Dict[str, Any],
        request_type: str = "pickup"
    ) -> Optional[str]:
        """
        Convenience method to directly get the selected picker ID.

        Args:
            request_data: Request data
            request_type: Type of request ("pickup" or "dump")

        Returns:
            Selected picker ID or None
        """
        request_data["request_type"] = request_type
        decision = await self.evaluate(request_data)

        if decision.result == EvaluationResult.VALID and decision.action == "assign":
            return decision.details.get("picker_id")

        return None
