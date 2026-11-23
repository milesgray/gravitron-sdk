"""
Gravitron SDK: run Google Antigravity SDK agents on your personal Antigravity quota.

Swap ``from google.antigravity import ...`` for ``from gravitron_sdk import ...``
and your ``Agent`` runs through the local ``agentapi`` CLI instead of the
Gemini API or Vertex AI.
"""

from importlib.metadata import PackageNotFoundError, version as _version

import google.antigravity as _upstream
from google.antigravity import *  # noqa: F401,F403  (re-export the full upstream API)
from google.antigravity import hooks, tools, triggers, types
from google.antigravity.conversation.conversation import Conversation
from google.antigravity.hooks import policy

from gravitron_sdk.agent import Agent, GravitronAgent
from gravitron_sdk.client import AgentAPIClient
from gravitron_sdk.connections.agentapi_config import (
    AgentAPIAgentConfig,
    GravitronAgentConfig,
    LocalAgentConfig,
)
from gravitron_sdk.connections.agentapi_connection import (
    AgentAPIConnection,
    AgentAPIConnectionStrategy,
)
from gravitron_sdk.connections.transcript_streamer import TranscriptStreamer
from gravitron_sdk.context7 import Context7Client
from gravitron_sdk.models import ModelTier
from gravitron_sdk.triggers import (
    TriggerContext,
    every,
    on_file_change,
    on_ipc_message,
    trigger,
)

try:
    __version__ = _version("gravitron-sdk")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0"

_GRAVITRON_EXPORTS = [
    "Agent",
    "GravitronAgent",
    "LocalAgentConfig",
    "GravitronAgentConfig",
    "AgentAPIAgentConfig",
    "AgentAPIConnectionStrategy",
    "AgentAPIConnection",
    "AgentAPIClient",
    "ModelTier",
    "TranscriptStreamer",
    "Context7Client",
    "Conversation",
    "every",
    "on_file_change",
    "on_ipc_message",
    "trigger",
    "TriggerContext",
    "hooks",
    "policy",
    "tools",
    "triggers",
    "types",
]

__all__ = sorted(set(_upstream.__all__) | set(_GRAVITRON_EXPORTS))
