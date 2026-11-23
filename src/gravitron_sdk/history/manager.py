#!/usr/bin/env python3
"""
Agent History Manager for Gravitron SDK.
Persists and serves turn histories for all registered agents across plugins.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from gravitron_sdk.history.models import (
    AgentHistorySession,
    AgentTurnRecord,
    ToolCallRecord,
)
from gravitron_sdk.telemetry.storage import resolve_gravitron_data_dir

logger = logging.getLogger("Gravitron.History")


class AgentHistoryManager:
    """Manages persistent turn records and chat histories for agents."""

    _instance: Optional[AgentHistoryManager] = None

    def __init__(self, base_dir: Optional[Path | str] = None):
        self.base_dir = Path(base_dir or (resolve_gravitron_data_dir() / "history")).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_instance(cls) -> AgentHistoryManager:
        if cls._instance is None:
            cls._instance = AgentHistoryManager()
        return cls._instance

    def _get_conv_path(self, conversation_id: str) -> Path:
        return self.base_dir / f"{conversation_id}.json"

    def get_history(self, conversation_id: str) -> Optional[AgentHistorySession]:
        """Loads full conversational session history by conversation_id."""
        path = self._get_conv_path(conversation_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return AgentHistorySession.model_validate(data)
        except Exception as e:
            logger.error("Failed to load history for %s: %s", conversation_id, e)
            return None

    def record_turn(
        self,
        conversation_id: str,
        plugin_slug: str,
        agent_id: str = "default",
        source: str = "model",
        content: str = "",
        thought: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tokens_est: int = 0,
        duration_ms: float = 0.0,
        status: str = "done",
    ) -> AgentTurnRecord:
        """Appends a new turn to the conversation history file."""
        if not conversation_id:
            conversation_id = f"anonymous-{plugin_slug}-{agent_id}"

        session = self.get_history(conversation_id)
        now = time.time()
        if session is None:
            session = AgentHistorySession(
                conversation_id=conversation_id,
                agent_id=agent_id,
                plugin_slug=plugin_slug,
                created_at=now,
                updated_at=now,
                turns=[],
            )

        tools: List[ToolCallRecord] = []
        if tool_calls:
            for tc in tool_calls:
                tools.append(
                    ToolCallRecord(
                        name=tc.get("name") or "tool",
                        arguments=tc.get("arguments") or tc.get("args") or {},
                        output=tc.get("output"),
                    )
                )

        turn = AgentTurnRecord(
            timestamp=now,
            conversation_id=conversation_id,
            agent_id=agent_id,
            plugin_slug=plugin_slug,
            source=source,
            content=content,
            thought=thought,
            tool_calls=tools,
            tokens_est=tokens_est,
            duration_ms=round(duration_ms, 2),
            status=status,
        )

        session.turns.append(turn)
        session.updated_at = now

        # Persist atomic write
        path = self._get_conv_path(conversation_id)
        tmp_path = path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(session.model_dump_json(indent=2))
            os.replace(tmp_path, path)
        except Exception as e:
            logger.error("Failed to save history turn: %s", e)
            if tmp_path.exists():
                tmp_path.unlink()

        return turn

    def get_agent_history(self, plugin_slug: str, agent_id: str) -> List[AgentTurnRecord]:
        """Collects turns across all conversations for a specific plugin and agent."""
        turns: List[AgentTurnRecord] = []
        for file in self.base_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                session = AgentHistorySession.model_validate(data)
                if session.plugin_slug == plugin_slug and session.agent_id == agent_id:
                    turns.extend(session.turns)
            except Exception:
                continue
        turns.sort(key=lambda t: t.timestamp)
        return turns
