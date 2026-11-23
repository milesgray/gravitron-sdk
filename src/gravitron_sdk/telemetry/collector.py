#!/usr/bin/env python3
"""
Telemetry Collector & Token Estimation Subsystem for Gravitron SDK.
Provides turn interception, calibrated token estimation, and asynchronous logging.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Optional, Sequence

from gravitron_sdk.telemetry.models import (
    TelemetryEvent,
    TelemetryEventStatus,
    TokenUsageEstimate,
)
from gravitron_sdk.telemetry.storage import TelemetryStorage

logger = logging.getLogger("Gravitron.Telemetry")

# Heuristic: 1 token ~ 3.85 characters for typical markdown, code, and English prompts.
CHARS_PER_TOKEN = 3.85
BASE_TOOL_CALL_TOKEN_OVERHEAD = 45


def estimate_tokens(
    prompt_text: str = "",
    response_text: str = "",
    tool_calls: Optional[Sequence[Any]] = None,
) -> TokenUsageEstimate:
    """Estimates prompt and completion tokens using a calibrated character heuristic."""
    prompt_chars = len(prompt_text or "")
    resp_chars = len(response_text or "")
    num_tool_calls = len(tool_calls) if tool_calls else 0

    # Calculate prompt tokens
    prompt_tokens = max(1, math.ceil(prompt_chars / CHARS_PER_TOKEN)) if prompt_chars > 0 else 0

    # Calculate completion tokens including tool overhead
    completion_text_tokens = math.ceil(resp_chars / CHARS_PER_TOKEN) if resp_chars > 0 else 0
    tool_tokens = num_tool_calls * BASE_TOOL_CALL_TOKEN_OVERHEAD
    completion_tokens = max(1, completion_text_tokens + tool_tokens) if (resp_chars > 0 or num_tool_calls > 0) else 0

    total_tokens = prompt_tokens + completion_tokens

    return TokenUsageEstimate(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        calculation_method="calibrated_char_and_tool_heuristic",
    )


class TelemetryCollector:
    """Singleton/shared collector for recording agentapi invocation telemetry."""

    _instance: Optional[TelemetryCollector] = None

    def __init__(self, storage: Optional[TelemetryStorage] = None):
        self.storage = storage or TelemetryStorage()

    @classmethod
    def get_instance(cls) -> TelemetryCollector:
        """Retrieves or creates the global collector instance."""
        if cls._instance is None:
            cls._instance = TelemetryCollector()
        return cls._instance

    def record_turn(
        self,
        plugin_slug: str,
        agent_id: str = "default",
        conversation_id: str = "",
        model_tier: str = "flash",
        prompt_text: str = "",
        response_text: str = "",
        turn_duration_ms: float = 0.0,
        tool_calls_count: int = 0,
        messages_count: int = 1,
        status: TelemetryEventStatus = TelemetryEventStatus.SUCCESS,
        error_message: Optional[str] = None,
    ) -> TelemetryEvent:
        """Calculates token estimates and records a completed turn in SQLite."""
        token_est = estimate_tokens(
            prompt_text=prompt_text,
            response_text=response_text,
            tool_calls=[None] * tool_calls_count,
        )

        event = TelemetryEvent(
            timestamp=time.time(),
            plugin_slug=plugin_slug,
            agent_id=agent_id,
            conversation_id=conversation_id,
            model_tier=model_tier,
            prompt_tokens_est=token_est.prompt_tokens,
            completion_tokens_est=token_est.completion_tokens,
            total_tokens_est=token_est.total_tokens,
            turn_duration_ms=round(turn_duration_ms, 2),
            tool_calls_count=tool_calls_count,
            messages_count=messages_count,
            status=status,
            error_message=error_message,
        )

        try:
            self.storage.record_event(event)
            logger.debug(
                "Logged telemetry turn for %s/%s: %s tokens in %sms",
                plugin_slug,
                agent_id,
                event.total_tokens_est,
                event.turn_duration_ms,
            )
        except Exception as e:
            logger.error("Failed to record telemetry event: %s", e)

        return event
