"""
Base agent class providing common functionality for all agents.
Uses Google ADK with Groq LLM backend.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
import json

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from config.settings import settings
from config.constants import EvaluationResult
from utils.logging_utils import logger, log_agent_decision


@dataclass
class AgentDecision:
    """Represents an agent's decision on a request."""
    result: EvaluationResult
    confidence: float  # 0-1
    reasoning: str
    action: str  # e.g., "approve", "reject", "assign"
    details: Dict[str, Any]


class BaseAgent(ABC):
    """
    Abstract base class for all AI agents.
    Provides common LLM integration and decision-making framework.
    """

    def __init__(self, name: str, description: str):
        """
        Initialize the base agent.

        Args:
            name: Agent name for identification
            description: Agent description for logging
        """
        self.name = name
        self.description = description
        self._llm = None
        self._agent = None

    def _get_llm(self) -> LiteLlm:
        """Get or create the LLM model instance."""
        if self._llm is None:
            self._llm = LiteLlm(
                model=f"groq/{settings.llm.model}",
                api_key=settings.llm.api_key
            )
        return self._llm

    def _create_agent(
        self,
        instruction: str,
        tools: Optional[List] = None
    ) -> Agent:
        """
        Create a Google ADK Agent instance.

        Args:
            instruction: System instruction for the agent
            tools: Optional list of tools the agent can use

        Returns:
            Configured Agent instance
        """
        return Agent(
            name=self.name,
            model=self._get_llm(),
            instruction=instruction,
            tools=tools or []
        )

    @abstractmethod
    async def evaluate(self, data: Dict[str, Any]) -> AgentDecision:
        """
        Evaluate input data and make a decision.

        Args:
            data: Input data for evaluation

        Returns:
            AgentDecision with the result
        """
        pass

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """
        Parse LLM response into structured data.

        Args:
            response: Raw LLM response text

        Returns:
            Parsed response as dict
        """
        # Try to extract JSON from response
        try:
            # Look for JSON block
            if "```json" in response:
                json_start = response.find("```json") + 7
                json_end = response.find("```", json_start)
                json_str = response[json_start:json_end].strip()
                return json.loads(json_str)
            elif "{" in response and "}" in response:
                # Try to find JSON object
                json_start = response.find("{")
                json_end = response.rfind("}") + 1
                json_str = response[json_start:json_end]
                return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # Fallback: return as text
        return {"text": response}

    def _build_context_prompt(self, data: Dict[str, Any]) -> str:
        """
        Build a context string from input data.

        Args:
            data: Input data dict

        Returns:
            Formatted context string
        """
        lines = ["Request Data:"]
        for key, value in data.items():
            if value is not None:
                lines.append(f"  - {key}: {value}")
        return "\n".join(lines)

    def log_decision(
        self,
        request_id: str,
        decision: AgentDecision
    ):
        """Log an agent decision."""
        log_agent_decision(
            agent_name=self.name,
            request_id=request_id,
            decision=decision.result.value,
            reasoning=decision.reasoning[:200]  # Truncate for logging
        )
