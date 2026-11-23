"""
Drop-in ``Agent`` for the Google Antigravity SDK backed by local ``agentapi``.
"""

from __future__ import annotations

from typing import Any, Optional

from google.antigravity import Agent as UpstreamAgent
from google.antigravity.connections import connection

from gravitron_sdk.connections.agentapi_config import (
    AgentAPIAgentConfig,
    GravitronAgentConfig,
)


class GravitronAgent(UpstreamAgent):
    """``google.antigravity.Agent`` that always runs on the agentapi transport.

    Accepts a Gravitron config, any upstream ``AgentConfig`` such as
    ``LocalAgentConfig`` (converted automatically), or keyword arguments used
    to build a ``GravitronAgentConfig``.
    """

    def __init__(self, config: Optional[connection.AgentConfig] = None, **kwargs: Any):
        if config is None:
            config = GravitronAgentConfig(**kwargs)
        elif kwargs:
            raise TypeError("Pass either a config object or keyword arguments, not both.")
        elif not isinstance(config, AgentAPIAgentConfig):
            config = GravitronAgentConfig.from_local_config(config)
        super().__init__(config)


Agent = GravitronAgent

__all__ = ["Agent", "GravitronAgent"]
