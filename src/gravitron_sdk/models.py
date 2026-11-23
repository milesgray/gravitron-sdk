#!/usr/bin/env python3
"""
Strongly typed Pydantic (v2) data models for the Antigravity AgentAPI CLI interface.
Provides request and response models for conversations, messages, and workspace metadata.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field

_PRO_HINTS = ("pro", "argon", "opus", "sonnet", "ultra")


class ModelTier(str, Enum):
    """Model tier supported by agentapi new-conversation."""
    FLASH_LITE = "flash_lite"
    FLASH = "flash"
    PRO = "pro"

    @classmethod
    def from_any(cls, value: Any = None, models: Any = None) -> "ModelTier":
        """Normalize a tier string, full model name, or ModelTarget into a ModelTier.

        Falls back to the first TEXT target in ``models`` when ``value`` is None,
        and to ``FLASH`` when nothing can be resolved.
        """
        if isinstance(value, cls):
            return value
        if value is None and models:
            for target in models:
                target_types = getattr(target, "types", None) or []
                if not target_types or any(getattr(t, "value", t) == "text" or str(t).endswith("TEXT") for t in target_types):
                    return cls.from_any(getattr(target, "name", None))
            return cls.from_any(getattr(models[0], "name", None))
        name = getattr(value, "name", value)
        if not isinstance(name, str) or not name.strip():
            return cls.FLASH
        text = name.strip().lower().replace("-", "_")
        if text in (cls.FLASH_LITE.value, "lite"):
            return cls.FLASH_LITE
        if text == cls.PRO.value:
            return cls.PRO
        if "lite" in text:
            return cls.FLASH_LITE
        tokens = set(text.replace(".", "_").split("_"))
        if any(hint in tokens for hint in _PRO_HINTS):
            return cls.PRO
        return cls.FLASH


class NewConversationRequest(BaseModel):
    """Payload specification for creating a new agent conversation via agentapi."""
    model_config = ConfigDict(extra="ignore")

    prompt: str = Field(..., description="Prompt or instruction to initiate the agent conversation")
    model: ModelTier = Field(default=ModelTier.FLASH, description="LLM capability tier (flash_lite, flash, pro)")
    title: Optional[str] = Field(default=None, description="Optional title label for the conversation session")
    profile: Optional[str] = Field(default=None, description="Optional agent profile configuration name")
    timeout_seconds: int = Field(default=120, description="Maximum execution timeout before cancelling subprocess")


class ConversationResponse(BaseModel):
    """Standardized response schema when creating or invoking a conversation."""
    model_config = ConfigDict(extra="ignore")

    success: bool = Field(..., description="True if agent execution completed successfully with exit code 0")
    conversation_id: Optional[str] = Field(default=None, description="Parsed UUID of the conversation session if found")
    output: str = Field(default="", description="Cleaned stdout text returned by the agent")
    error: Optional[str] = Field(default=None, description="Error message or stderr text if execution failed")
    raw_output: str = Field(default="", description="Unmodified stdout from the agentapi process")


class SendMessageRequest(BaseModel):
    """Payload specification for sending a message to an active conversation."""
    model_config = ConfigDict(extra="ignore")

    recipient_id: str = Field(..., description="Unique conversation UUID or agent recipient identifier")
    content: str = Field(..., description="Message text or instructions sent to the agent")
    title: Optional[str] = Field(default=None, description="Optional display title for the message")
    timeout_seconds: int = Field(default=120, description="Maximum execution timeout before cancelling subprocess")


class SendMessageResponse(BaseModel):
    """Standardized response schema after sending a message."""
    model_config = ConfigDict(extra="ignore")

    success: bool = Field(..., description="True if message delivery and agent response succeeded")
    recipient_id: str = Field(..., description="Target conversation identifier")
    output: str = Field(default="", description="Agent reply text")
    error: Optional[str] = Field(default=None, description="Error message if delivery failed")


class WorkspaceMetadata(BaseModel):
    """Metadata representing an Antigravity workspace attached to a conversation."""
    model_config = ConfigDict(extra="ignore")

    workspaceFolderAbsoluteUri: Optional[str] = Field(default=None, description="Absolute filesystem URI to workspace root")
    gitRootAbsoluteUri: Optional[str] = Field(default=None, description="Absolute filesystem URI to git root repository")
    branchName: Optional[str] = Field(default=None, description="Active git branch name in the workspace")


class ConversationMetadata(BaseModel):
    """Parsed metadata schema returned by agentapi get-conversation-metadata."""
    model_config = ConfigDict(extra="ignore")

    conversation_id: str = Field(..., description="Conversation UUID")
    root_conversation_id: Optional[str] = Field(default=None, description="Root parent conversation UUID in agent tree")
    parent_conversation_id: Optional[str] = Field(default=None, description="Immediate parent conversation UUID")
    created_at: Optional[str] = Field(default=None, description="Session creation timestamp string")
    workspaces: List[WorkspaceMetadata] = Field(default_factory=list, description="Workspaces associated with the conversation")
    raw_json: Dict[str, Any] = Field(default_factory=dict, description="Raw metadata payload returned by the CLI")


class AgentAPISessionMode(str, Enum):
    """Session continuation mode for AgentAPI connections."""
    CREATE_ONLY = "create_only"
    RESUME = "resume"
    CREATE_OR_RESUME = "create_or_resume"


class AgentAPIProcessConfig(BaseModel):
    """Execution options for local agentapi process invocations."""
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="ignore")

    binary_path: Optional[str] = Field(default=None, description="Explicit path to agentapi binary")
    model: ModelTier = Field(default=ModelTier.FLASH, description="Antigravity model tier")
    title: Optional[str] = Field(default=None, description="Human-readable conversation title")
    profile: Optional[str] = Field(default=None, description="Agent execution profile")
    timeout_seconds: int = Field(default=120, ge=5, le=600, description="Command execution timeout")
    app_data_dir: Optional[str] = Field(
        default=None,
        description="Root application data directory housing brain transcripts"
    )


class TranscriptStepRecord(BaseModel):
    """Schema for individual line records parsed from transcript_full.jsonl."""
    model_config = ConfigDict(extra="ignore")

    step_index: int = Field(default=0, description="Index of the step in trajectory")
    source: str = Field(default="SYSTEM", description="Source: MODEL, USER_EXPLICIT, SYSTEM")
    type: str = Field(default="UNKNOWN", description="Step type: USER_INPUT, PLANNER_RESPONSE, etc.")
    status: str = Field(default="DONE", description="Status: DONE, ERROR, RUNNING")
    content: Optional[str] = Field(default=None, description="Textual payload or response content")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(default=None, description="Tool execution requests")
    is_truncated: Optional[bool] = Field(default=False, description="Flag indicating step content truncation")

