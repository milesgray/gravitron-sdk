"""
Declarative agent configuration for AgentAPI connections.

Subclasses the Google Antigravity SDK ``AgentConfig`` so that any ``Agent``
routes execution through the local ``agentapi`` CLI (personal Antigravity
quota) instead of the Gemini API / Vertex AI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Union

import pydantic

from google.antigravity import types
from google.antigravity.connections import connection
from google.antigravity.hooks import hooks as hooks_mod
from google.antigravity.hooks import policy
from google.antigravity.triggers import triggers as triggers_mod

from gravitron_sdk.models import ModelTier

DEFAULT_APP_DATA_DIR = Path.home() / ".gemini" / "antigravity-ide"
APP_DATA_DIR_CANDIDATES = (
    Path.home() / ".gemini" / "antigravity",
    Path.home() / ".gemini" / "antigravity-ide",
)

# Fields shared with google.antigravity.AgentConfig that carry over verbatim
# when converting an upstream LocalAgentConfig.
_PASSTHROUGH_FIELDS = (
    "system_instructions",
    "capabilities",
    "tools",
    "policies",
    "hooks",
    "triggers",
    "mcp_servers",
    "workspaces",
    "conversation_id",
    "session_continuation_mode",
    "save_dir",
    "response_schema",
    "skills_paths",
    "inline_skills",
    "subagents",
    "debug_config",
    "retry_config",
    "budget_config",
    "compaction_config",
)


def resolve_app_data_dir(explicit: Optional[str] = None) -> str:
    """Resolve the Antigravity app data dir that holds ``brain/`` transcripts."""
    import os

    if explicit:
        return str(Path(explicit).expanduser())
    env_dir = os.environ.get("ANTIGRAVITY_APP_DATA_DIR")
    if env_dir:
        return str(Path(env_dir).expanduser())
    for candidate in APP_DATA_DIR_CANDIDATES:
        if (candidate / "brain").is_dir():
            return str(candidate)
    return str(DEFAULT_APP_DATA_DIR)


class AgentAPIAgentConfig(connection.AgentConfig):
    """Configuration for an Agent utilizing local Antigravity AgentAPI transport.

    Accepts the full ``google.antigravity.LocalAgentConfig`` signature; cloud-only
    fields (``api_key``, ``vertex``, ``project``, ``location``, ``env``) are kept
    for compatibility but have no effect on the agentapi transport.
    """

    model: ModelTier = pydantic.Field(default=ModelTier.FLASH)
    models: Optional[List[types.ModelTarget]] = None
    title: Optional[str] = None
    profile: Optional[str] = None
    binary_path: Optional[str] = None
    timeout_seconds: int = pydantic.Field(default=120, ge=5, le=600)
    active_project: Optional[str] = None
    plugin_slug: str = "default"
    agent_id: Optional[str] = None
    enable_telemetry: bool = True
    # Cloud-only LocalAgentConfig fields, accepted and ignored.
    api_key: Optional[str] = None
    vertex: Optional[bool] = None
    project: Optional[str] = None
    location: Optional[str] = None
    env: Optional[dict[str, str]] = None

    def __init__(
        self,
        *,
        model: Union[str, ModelTier, types.ModelTarget, None] = None,
        models: Optional[List[types.ModelTarget]] = None,
        title: Optional[str] = None,
        profile: Optional[str] = None,
        binary_path: Optional[str] = None,
        timeout_seconds: int = 120,
        app_data_dir: Optional[str] = None,
        active_project: Optional[str] = None,
        system_instructions: Optional[Union[str, types.SystemInstructions]] = None,
        capabilities: Optional[types.CapabilitiesConfig] = None,
        tools: Optional[List[Union[Callable[..., Any], str]]] = None,
        policies: Optional[Sequence[Any]] = None,
        hooks: Optional[List[hooks_mod.Hook]] = None,
        triggers: Optional[List[triggers_mod.Trigger]] = None,
        mcp_servers: Optional[List[types.McpServerConfig]] = None,
        workspaces: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        session_continuation_mode: Optional[types.SessionContinuationMode] = None,
        response_schema: Optional[Union[dict, type, str]] = None,
        skills_paths: Optional[List[str]] = None,
        **kwargs: Any,
    ):
        ws_list = list(workspaces or [])
        if not ws_list and active_project:
            ws_list = [active_project]

        init_data: dict[str, Any] = {
            "model": ModelTier.from_any(model, models=models),
            "models": models,
            "title": title,
            "profile": profile,
            "binary_path": binary_path,
            "timeout_seconds": timeout_seconds,
            "app_data_dir": resolve_app_data_dir(app_data_dir),
            "active_project": active_project,
            "system_instructions": system_instructions,
            "capabilities": capabilities
            or types.CapabilitiesConfig(enabled_tools=types.BuiltinTools.read_only()),
            "tools": tools or [],
            "policies": policies or [],
            "hooks": hooks or [],
            "triggers": triggers or [],
            "mcp_servers": mcp_servers or [],
            "workspaces": ws_list,
            "conversation_id": conversation_id,
            "session_continuation_mode": session_continuation_mode,
            "response_schema": response_schema,
            "skills_paths": skills_paths or [],
        }
        init_data.update({k: v for k, v in kwargs.items() if v is not None})
        super().__init__(**init_data)

    def eval(self, thinking_level: Optional[types.ThinkingLevel] = None):  # type: ignore[override]
        """Evaluation presets; thinking level is not configurable over agentapi."""
        return super().eval(thinking_level=None)

    def create_strategy(
        self,
        *,
        tool_runner: Any,
        hook_runner: Any,
    ) -> connection.ConnectionStrategy:
        """Instantiates the AgentAPIConnectionStrategy for this configuration."""
        from gravitron_sdk.connections.agentapi_connection import AgentAPIConnectionStrategy

        return AgentAPIConnectionStrategy(
            config=self,
            tool_runner=tool_runner,
            hook_runner=hook_runner,
        )


class GravitronAgentConfig(AgentAPIAgentConfig):
    """Canonical Gravitron config; drop-in replacement for ``LocalAgentConfig``."""

    @classmethod
    def from_local_config(cls, config: connection.AgentConfig) -> "GravitronAgentConfig":
        """Convert any upstream ``AgentConfig`` (e.g. ``LocalAgentConfig``) to Gravitron.

        Preserves instructions, tools, policies, hooks, triggers, workspaces and
        other shared fields, and maps ``model``/``models`` to a ``ModelTier``.
        """
        if isinstance(config, cls):
            return config
        data: dict[str, Any] = {}
        for field in _PASSTHROUGH_FIELDS:
            if hasattr(config, field):
                value = getattr(config, field)
                if value is not None:
                    data[field] = value
        app_data_dir = getattr(config, "app_data_dir", None)
        models = getattr(config, "models", None)
        return cls(
            model=getattr(config, "model", None),
            # Upstream fills ``models`` with Gemini defaults; only use it when
            # no explicit shorthand model was given.
            models=models,
            app_data_dir=app_data_dir,
            **data,
        )


# Drop-in alias: ``from gravitron_sdk import LocalAgentConfig``.
LocalAgentConfig = GravitronAgentConfig

AgentAPIAgentConfig.model_rebuild()
GravitronAgentConfig.model_rebuild()
