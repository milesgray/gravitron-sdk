#!/usr/bin/env python3
"""
Strongly typed Pydantic (v2) data models for the Gravitron SDK Agent History Subsystem.
Complies with rules/pydantic-models.md.
"""

from typing import List, Optional, Dict, Any
import time
import uuid
from pydantic import BaseModel, ConfigDict, Field


class ToolCallRecord(BaseModel):
    """Execution record for an individual tool invocation."""
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Tool name invoked")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Arguments supplied to tool")
    output: Optional[str] = Field(default=None, description="Result text or error string returned")


class AgentTurnRecord(BaseModel):
    """Complete conversational turn captured from agentapi execution."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Turn UUID")
    timestamp: float = Field(default_factory=time.time, description="Unix timestamp of turn")
    conversation_id: str = Field(default="", description="Antigravity conversation UUID")
    agent_id: str = Field(default="default", description="Registered agent identifier")
    plugin_slug: str = Field(default="", description="Plugin slug owning this agent")
    source: str = Field(default="model", description="Turn origin: user, model, system")
    content: str = Field(default="", description="Cleaned response or prompt text")
    thought: Optional[str] = Field(default=None, description="Extracted model reasoning/thinking trace")
    tool_calls: List[ToolCallRecord] = Field(default_factory=list, description="Tools invoked during turn")
    tokens_est: int = Field(default=0, ge=0, description="Estimated total tokens for turn")
    duration_ms: float = Field(default=0.0, ge=0.0, description="Turn execution latency in milliseconds")
    status: str = Field(default="done", description="Outcome status: done, error, timeout")


class AgentHistorySession(BaseModel):
    """Full session history containing sequential turns for an agent."""
    model_config = ConfigDict(extra="ignore")

    conversation_id: str = Field(..., description="Conversation UUID")
    agent_id: str = Field(default="default", description="Agent identifier")
    plugin_slug: str = Field(default="", description="Parent plugin slug")
    created_at: float = Field(default_factory=time.time, description="Session inception timestamp")
    updated_at: float = Field(default_factory=time.time, description="Last turn timestamp")
    turns: List[AgentTurnRecord] = Field(default_factory=list, description="Ordered turns in session")
