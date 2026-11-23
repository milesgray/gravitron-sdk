#!/usr/bin/env python3
"""
Strongly typed Pydantic (v2) data models for the Gravitron SDK Telemetry & Quota Subsystem.
Complies with rules/pydantic-models.md.
"""

from enum import Enum
from typing import List, Optional
import time
import uuid
from pydantic import BaseModel, ConfigDict, Field


class TelemetryEventStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


class TokenUsageEstimate(BaseModel):
    """Estimated token breakdown for an LLM exchange."""
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = Field(default=0, ge=0, description="Estimated prompt/input tokens")
    completion_tokens: int = Field(default=0, ge=0, description="Estimated completion/output tokens")
    total_tokens: int = Field(default=0, ge=0, description="Sum of prompt and completion tokens")
    calculation_method: str = Field(default="char_heuristic", description="Method used to calculate estimate")


class TelemetryEvent(BaseModel):
    """Atomic telemetry event representing one execution turn or API call."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique event UUID")
    timestamp: float = Field(default_factory=time.time, description="Unix timestamp of event completion")
    plugin_slug: str = Field(..., description="Target plugin identifier (e.g. plan-orchestrator, code-architect)")
    agent_id: str = Field(default="default", description="Registered agent identifier or profile")
    conversation_id: str = Field(default="", description="Target Antigravity conversation UUID")
    model_tier: str = Field(default="flash", description="LLM capability tier: flash_lite, flash, pro")
    prompt_tokens_est: int = Field(default=0, ge=0, description="Estimated prompt tokens")
    completion_tokens_est: int = Field(default=0, ge=0, description="Estimated completion tokens")
    total_tokens_est: int = Field(default=0, ge=0, description="Total estimated tokens")
    turn_duration_ms: float = Field(default=0.0, ge=0.0, description="Total turn execution duration in milliseconds")
    tool_calls_count: int = Field(default=0, ge=0, description="Count of tools called during the turn")
    messages_count: int = Field(default=1, ge=1, description="Count of messages processed")
    status: TelemetryEventStatus = Field(default=TelemetryEventStatus.SUCCESS, description="Execution outcome")
    error_message: Optional[str] = Field(default=None, description="Error or stderr text if execution failed")


class GranularMetricRecord(BaseModel):
    """Time-series telemetry bucket for granular graphing and trend analysis."""
    model_config = ConfigDict(extra="ignore")

    timestamp_bucket: str = Field(..., description="ISO 8601 minute bucket timestamp (YYYY-MM-DDTHH:MM:00)")
    tokens_per_minute: float = Field(default=0.0, ge=0.0, description="Rate of token consumption in bucket")
    calls_per_minute: int = Field(default=0, ge=0, description="Number of agentapi calls in bucket")
    avg_latency_ms: float = Field(default=0.0, ge=0.0, description="Average response latency in bucket")
    tool_calls_count: int = Field(default=0, ge=0, description="Total tool invocations in bucket")


class UsageQueryFilter(BaseModel):
    """Query filter parameters for retrieving telemetry records."""
    model_config = ConfigDict(extra="ignore")

    plugin_slug: Optional[str] = Field(default=None, description="Filter by plugin slug")
    agent_id: Optional[str] = Field(default=None, description="Filter by agent id")
    since_timestamp: Optional[float] = Field(default=None, description="Start timestamp filter")
    until_timestamp: Optional[float] = Field(default=None, description="End timestamp filter")
    window_minutes: Optional[int] = Field(default=60, ge=1, description="Sliding aggregation window in minutes")


class AgentTelemetrySummary(BaseModel):
    """Aggregated usage metrics for a specific agent."""
    model_config = ConfigDict(extra="ignore")

    agent_id: str = Field(..., description="Agent identifier")
    plugin_slug: str = Field(..., description="Associated plugin slug")
    total_calls: int = Field(default=0, ge=0, description="Total number of API calls made")
    total_turns: int = Field(default=0, ge=0, description="Total turns processed")
    total_tokens_est: int = Field(default=0, ge=0, description="Cumulative estimated tokens")
    avg_latency_ms: float = Field(default=0.0, ge=0.0, description="Average turn latency in milliseconds")
    tool_calls_count: int = Field(default=0, ge=0, description="Cumulative tool calls made")
    last_active_timestamp: Optional[float] = Field(default=None, description="Timestamp of most recent activity")
    tokens_per_min_recent: float = Field(default=0.0, ge=0.0, description="Token consumption rate over past 5 minutes")


class PluginQuotaSummary(BaseModel):
    """High-fidelity quota and telemetry rollup for a plugin."""
    model_config = ConfigDict(extra="ignore")

    plugin_slug: str = Field(..., description="Plugin slug")
    total_calls: int = Field(default=0, ge=0, description="Lifetime or query-window total agentapi calls")
    total_turns: int = Field(default=0, ge=0, description="Total conversational turns")
    total_tokens_est: int = Field(default=0, ge=0, description="Cumulative token estimate")
    prompt_tokens_est: int = Field(default=0, ge=0, description="Cumulative prompt token estimate")
    completion_tokens_est: int = Field(default=0, ge=0, description="Cumulative completion token estimate")
    tool_calls_count: int = Field(default=0, ge=0, description="Total tool invocations")
    tokens_per_minute: float = Field(default=0.0, ge=0.0, description="Current rate of token consumption (last 5 min)")
    calls_per_minute: float = Field(default=0.0, ge=0.0, description="Current rate of calls per minute (last 5 min)")
    agents: List[AgentTelemetrySummary] = Field(default_factory=list, description="Per-agent breakdown")
    recent_metrics: List[GranularMetricRecord] = Field(default_factory=list, description="Time series data for charts")


class GlobalTelemetrySummary(BaseModel):
    """System-wide quota and telemetry summary across all plugins."""
    model_config = ConfigDict(extra="ignore")

    total_plugins_monitored: int = Field(default=0, ge=0)
    total_calls_all_time: int = Field(default=0, ge=0)
    total_tokens_all_time: int = Field(default=0, ge=0)
    active_tokens_per_minute: float = Field(default=0.0, ge=0.0)
    active_calls_per_minute: float = Field(default=0.0, ge=0.0)
    plugin_summaries: List[PluginQuotaSummary] = Field(default_factory=list)
