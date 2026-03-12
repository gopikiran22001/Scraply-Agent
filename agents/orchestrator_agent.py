"""
Orchestrator Agent that coordinates the entire request processing workflow.
Manages the flow from queue to evaluation to assignment.
"""

import asyncio
from typing import Dict, Any, Optional
from enum import Enum

from agents.base_agent import BaseAgent, AgentDecision
from agents.pickup_evaluation_agent import PickupEvaluationAgent
from agents.illegal_dump_evaluation_agent import IllegalDumpEvaluationAgent
from agents.picker_assignment_agent import PickerAssignmentAgent
from config.settings import settings
from config.constants import EvaluationResult, Status, QueueNames
from services.database_service import db_service
from services.redis_service import redis_service
from services.rest_api_service import api_service, APIError
from utils.logging_utils import logger, log_request_processing


class RequestType(str, Enum):
    """Types of requests the orchestrator handles."""
    PICKUP = "pickup"
    DUMP = "dump"
    PICKUP_ASSIGN = "pickup_assign"
    DUMP_ASSIGN = "dump_assign"


# Maximum number of picker assignment retries before cancelling
MAX_ASSIGNMENT_RETRIES = 5

# Delay between retries (seconds) - will be used for scheduling re-queue
RETRY_DELAY_SECONDS = 60


class OrchestratorAgent:
    """
    Central orchestrator that coordinates the entire request processing workflow.

    Workflow:
    1. Receive request ID from queue
    2. Fetch request details from database
    3. Run appropriate evaluation agent
    4. If valid, run picker assignment agent
    5. Execute action via REST API
    """

    def __init__(self):
        self.name = "OrchestratorAgent"
        self._pickup_evaluator = PickupEvaluationAgent()
        self._dump_evaluator = IllegalDumpEvaluationAgent()
        self._picker_assigner = PickerAssignmentAgent()
        self._running = False

    async def process_pickup_request(self, pickup_id: str) -> bool:
        """
        Process a new pickup request from the queue.

        Args:
            pickup_id: The pickup request ID

        Returns:
            True if processed successfully
        """
        log_request_processing("PICKUP", pickup_id, "Started evaluation")

        try:
            # Fetch request details from database
            pickup_data = await db_service.get_pickup_by_id(pickup_id)

            if not pickup_data:
                logger.error(f"Pickup {pickup_id} not found in database")
                return False

            # Check if already processed
            current_status = pickup_data.get("status")
            if current_status != Status.REQUESTED.value:
                logger.info(f"Pickup {pickup_id} already has status {current_status}, skipping")
                return True

            # Run evaluation
            decision = await self._pickup_evaluator.evaluate(pickup_data)

            if decision.result == EvaluationResult.VALID:
                # Mark as in progress (this adds to assignment queue in backend)
                await api_service.update_pickup_progress(pickup_id)
                log_request_processing("PICKUP", pickup_id, "Marked as IN_PROGRESS", "Valid request")
                return True

            elif decision.result in [EvaluationResult.DUPLICATE, EvaluationResult.INVALID, EvaluationResult.SPAM]:
                # Reject the request
                reason = decision.reasoning[:500]  # Truncate reason
                await api_service.cancel_pickup(pickup_id, reason)
                log_request_processing("PICKUP", pickup_id, "Cancelled", decision.result.value)
                return True

            else:
                logger.warning(f"Unexpected evaluation result for {pickup_id}: {decision.result}")
                return False

        except APIError as e:
            logger.error(f"API error processing pickup {pickup_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error processing pickup {pickup_id}: {e}")
            return False

    async def process_dump_request(self, dump_id: str) -> bool:
        """
        Process a new illegal dump report from the queue.

        Args:
            dump_id: The dump report ID

        Returns:
            True if processed successfully
        """
        log_request_processing("DUMP", dump_id, "Started evaluation")

        try:
            # Fetch report details from database
            dump_data = await db_service.get_dump_by_id(dump_id)

            if not dump_data:
                logger.error(f"Dump report {dump_id} not found in database")
                return False

            # Check if already processed
            current_status = dump_data.get("status")
            if current_status != Status.REQUESTED.value:
                logger.info(f"Dump {dump_id} already has status {current_status}, skipping")
                return True

            # Run evaluation
            decision = await self._dump_evaluator.evaluate(dump_data)

            if decision.result == EvaluationResult.VALID:
                # Mark as in progress
                await api_service.update_dumping_progress(dump_id)
                log_request_processing("DUMP", dump_id, "Marked as IN_PROGRESS", "Valid report")
                return True

            elif decision.result in [EvaluationResult.DUPLICATE, EvaluationResult.INVALID, EvaluationResult.SPAM]:
                # Reject the report
                reason = decision.reasoning[:500]
                await api_service.cancel_dumping(dump_id, reason)
                log_request_processing("DUMP", dump_id, "Cancelled", decision.result.value)
                return True

            else:
                logger.warning(f"Unexpected evaluation result for {dump_id}: {decision.result}")
                return False

        except APIError as e:
            logger.error(f"API error processing dump {dump_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error processing dump {dump_id}: {e}")
            return False

    async def process_pickup_assignment(self, pickup_id: str) -> bool:
        """
        Process a pickup request that needs picker assignment.
        Retries up to MAX_ASSIGNMENT_RETRIES times before cancelling.

        Args:
            pickup_id: The pickup request ID

        Returns:
            True if assigned successfully or cancelled after max retries
        """
        log_request_processing("PICKUP_ASSIGN", pickup_id, "Started assignment")

        try:
            # Fetch request details
            pickup_data = await db_service.get_pickup_by_id(pickup_id)

            if not pickup_data:
                logger.error(f"Pickup {pickup_id} not found for assignment")
                return False

            # Check status
            current_status = pickup_data.get("status")
            if current_status != Status.IN_PROGRESS.value:
                logger.info(f"Pickup {pickup_id} has status {current_status}, skipping assignment")
                # Clear any retry count since request is no longer pending
                await redis_service.clear_retry_count(pickup_id, "pickup")
                return True

            # Run picker assignment
            pickup_data["request_type"] = "pickup"
            decision = await self._picker_assigner.evaluate(pickup_data)

            if decision.result == EvaluationResult.VALID and decision.action == "assign":
                picker_id = decision.details.get("picker_id")
                if picker_id:
                    await api_service.assign_pickup(pickup_id, picker_id)
                    # Clear retry count on success
                    await redis_service.clear_retry_count(pickup_id, "pickup")
                    log_request_processing(
                        "PICKUP_ASSIGN", pickup_id, "Assigned",
                        f"Picker: {decision.details.get('picker_name', picker_id)}"
                    )
                    return True

            # Could not assign - check retry count
            retry_count = await redis_service.increment_retry_count(pickup_id, "pickup")
            logger.warning(
                f"Could not assign picker for {pickup_id}: {decision.reasoning} "
                f"(attempt {retry_count}/{MAX_ASSIGNMENT_RETRIES})"
            )

            if retry_count >= MAX_ASSIGNMENT_RETRIES:
                # Max retries reached - cancel the request
                cancel_reason = (
                    f"Unable to find available picker after {MAX_ASSIGNMENT_RETRIES} attempts. "
                    f"Please try again later or contact support."
                )
                await api_service.cancel_pickup(pickup_id, cancel_reason)
                await redis_service.clear_retry_count(pickup_id, "pickup")
                log_request_processing(
                    "PICKUP_ASSIGN", pickup_id, "Cancelled",
                    f"No picker available after {MAX_ASSIGNMENT_RETRIES} attempts"
                )
                return True  # Processed (cancelled)
            else:
                # Re-queue for later retry
                await redis_service.enqueue(QueueNames.PICKUP_ASSIGN_QUEUE, pickup_id)
                return False

        except APIError as e:
            logger.error(f"API error assigning pickup {pickup_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error assigning pickup {pickup_id}: {e}")
            return False

    async def process_dump_assignment(self, dump_id: str) -> bool:
        """
        Process a dump report that needs picker assignment.
        Retries up to MAX_ASSIGNMENT_RETRIES times before cancelling.

        Args:
            dump_id: The dump report ID

        Returns:
            True if assigned successfully or cancelled after max retries
        """
        log_request_processing("DUMP_ASSIGN", dump_id, "Started assignment")

        try:
            # Fetch report details
            dump_data = await db_service.get_dump_by_id(dump_id)

            if not dump_data:
                logger.error(f"Dump {dump_id} not found for assignment")
                return False

            # Check status
            current_status = dump_data.get("status")
            if current_status != Status.IN_PROGRESS.value:
                logger.info(f"Dump {dump_id} has status {current_status}, skipping assignment")
                # Clear any retry count since request is no longer pending
                await redis_service.clear_retry_count(dump_id, "dump")
                return True

            # Run picker assignment
            dump_data["request_type"] = "dump"
            decision = await self._picker_assigner.evaluate(dump_data)

            if decision.result == EvaluationResult.VALID and decision.action == "assign":
                picker_id = decision.details.get("picker_id")
                if picker_id:
                    await api_service.assign_dumping(dump_id, picker_id)
                    # Clear retry count on success
                    await redis_service.clear_retry_count(dump_id, "dump")
                    log_request_processing(
                        "DUMP_ASSIGN", dump_id, "Assigned",
                        f"Picker: {decision.details.get('picker_name', picker_id)}"
                    )
                    return True

            # Could not assign - check retry count
            retry_count = await redis_service.increment_retry_count(dump_id, "dump")
            logger.warning(
                f"Could not assign picker for {dump_id}: {decision.reasoning} "
                f"(attempt {retry_count}/{MAX_ASSIGNMENT_RETRIES})"
            )

            if retry_count >= MAX_ASSIGNMENT_RETRIES:
                # Max retries reached - cancel the request
                cancel_reason = (
                    f"Unable to find available picker after {MAX_ASSIGNMENT_RETRIES} attempts. "
                    f"Please try again later or contact support."
                )
                await api_service.cancel_dumping(dump_id, cancel_reason)
                await redis_service.clear_retry_count(dump_id, "dump")
                log_request_processing(
                    "DUMP_ASSIGN", dump_id, "Cancelled",
                    f"No picker available after {MAX_ASSIGNMENT_RETRIES} attempts"
                )
                return True  # Processed (cancelled)
            else:
                # Re-queue for later retry
                await redis_service.enqueue(QueueNames.DUMP_ASSIGN_QUEUE, dump_id)
                return False

        except APIError as e:
            logger.error(f"API error assigning dump {dump_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error assigning dump {dump_id}: {e}")
            return False

    async def handle_queue_item(self, queue_name: str, item_id: str) -> bool:
        """
        Handle an item from any queue.

        Args:
            queue_name: Name of the source queue
            item_id: The request/report ID

        Returns:
            True if handled successfully
        """
        if queue_name == QueueNames.PICKUP_QUEUE:
            return await self.process_pickup_request(item_id)
        elif queue_name == QueueNames.DUMP_QUEUE:
            return await self.process_dump_request(item_id)
        elif queue_name == QueueNames.PICKUP_ASSIGN_QUEUE:
            return await self.process_pickup_assignment(item_id)
        elif queue_name == QueueNames.DUMP_ASSIGN_QUEUE:
            return await self.process_dump_assignment(item_id)
        else:
            logger.warning(f"Unknown queue: {queue_name}")
            return False

    async def run_single_pass(self) -> int:
        """
        Run a single pass through all queues.
        Processes one item from each queue if available.

        Returns:
            Number of items processed
        """
        processed = 0

        # Process evaluation queues first (new requests)
        for queue_name in [QueueNames.PICKUP_QUEUE, QueueNames.DUMP_QUEUE]:
            item = await redis_service.dequeue(queue_name)
            if item:
                success = await self.handle_queue_item(queue_name, item)
                if success:
                    processed += 1

        # Then process assignment queues
        for queue_name in [QueueNames.PICKUP_ASSIGN_QUEUE, QueueNames.DUMP_ASSIGN_QUEUE]:
            item = await redis_service.dequeue(queue_name)
            if item:
                success = await self.handle_queue_item(queue_name, item)
                if success:
                    processed += 1

        return processed

    async def run_continuous(self, poll_interval: Optional[float] = None):
        """
        Run continuous queue processing.

        Args:
            poll_interval: Seconds between queue checks (default from settings)
        """
        if poll_interval is None:
            poll_interval = settings.agent.poll_interval

        self._running = True
        logger.info(f"[Orchestrator] Starting continuous processing (interval: {poll_interval}s)")

        while self._running:
            try:
                # Try to get item from any queue
                result = await redis_service.dequeue_from_multiple(
                    queue_names=[
                        QueueNames.PICKUP_QUEUE,
                        QueueNames.DUMP_QUEUE,
                        QueueNames.PICKUP_ASSIGN_QUEUE,
                        QueueNames.DUMP_ASSIGN_QUEUE
                    ],
                    timeout=int(poll_interval)
                )

                if result:
                    queue_name, item_id = result
                    await self.handle_queue_item(queue_name, item_id)

            except asyncio.CancelledError:
                logger.info("[Orchestrator] Received cancellation signal")
                break
            except Exception as e:
                logger.error(f"[Orchestrator] Error in processing loop: {e}")
                await asyncio.sleep(poll_interval)

        logger.info("[Orchestrator] Stopped continuous processing")

    def stop(self):
        """Signal the orchestrator to stop processing."""
        self._running = False
        redis_service.stop_listening()

    async def get_status(self) -> Dict[str, Any]:
        """Get current orchestrator status."""
        queue_sizes = await redis_service.get_all_queue_sizes()
        return {
            "running": self._running,
            "queue_sizes": queue_sizes,
            "total_pending": sum(queue_sizes.values())
        }


# Global orchestrator instance
orchestrator = OrchestratorAgent()
