#!/usr/bin/env python3
"""
AgentAPI Connection Strategy and Connection for Google Antigravity SDK.
Implements the abstract ConnectionStrategy and Connection interfaces,
enabling native Antigravity model quota usage via local agentapi CLI.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Optional, Sequence

from google.antigravity import types
from google.antigravity.connections import connection
from gravitron_sdk.connections.transcript_streamer import TranscriptStreamer
from gravitron_sdk.telemetry import TelemetryCollector, TelemetryEventStatus
from gravitron_sdk.history import AgentHistoryManager

logger = logging.getLogger("Gravitron.AgentAPIConnection")


DEFAULT_IDE_BIN = Path.home() / ".gemini" / "antigravity-ide" / "bin" / "agentapi"
UUID_PATTERN = re.compile(
    r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})", re.I
)


class _TelemetryDisabled(Exception):
    """Internal sentinel used to skip telemetry recording."""


def _extract_text_from_content(prompt: types.Content | None) -> str:
    """Extracts a flat string from a string, list of strings, or Content object."""
    if prompt is None:
        return ""
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, (list, tuple, Sequence)):
        parts = []
        for p in prompt:
            if isinstance(p, str):
                parts.append(p)
            elif hasattr(p, "text") and getattr(p, "text"):
                parts.append(str(p.text))
            elif hasattr(p, "content") and getattr(p, "content"):
                parts.append(str(p.content))
            else:
                parts.append(str(p))
        return " ".join(parts)
    if hasattr(prompt, "text") and getattr(prompt, "text"):
        return str(prompt.text)
    return str(prompt)


class AgentAPIConnection(connection.Connection):
    """Active connection session with the local Antigravity agentapi CLI."""

    def __init__(
        self,
        binary_path: str,
        app_data_dir: Path,
        model_tier: str = "flash",
        title: Optional[str] = None,
        profile: Optional[str] = None,
        timeout_seconds: int = 120,
        conversation_id: Optional[str] = None,
        debug_config: Optional[connection.DebugConfig] = None,
        plugin_slug: str = "default",
        agent_id: str = "default",
        workspace: Optional[str] = None,
        enable_telemetry: bool = True,
    ):
        self._enable_telemetry = enable_telemetry
        self._binary_path = binary_path
        self._app_data_dir = app_data_dir
        self._model_tier = model_tier
        self._title = title
        self._profile = profile
        self._timeout_seconds = timeout_seconds
        self._conversation_id = conversation_id or ""
        self._debug_config = debug_config
        self._plugin_slug = plugin_slug
        self._agent_id = agent_id
        self._workspace = workspace

        self._is_idle = True
        self._active_process: Optional[asyncio.subprocess.Process] = None
        self._turn_stop_event = asyncio.Event()
        self._streamer: Optional[TranscriptStreamer] = None
        self._last_stop_reason = types.StopReason.UNSPECIFIED
        self._step_queue: asyncio.Queue[types.Step | None] = asyncio.Queue()
        self._turn_start_time = 0.0
        self._last_prompt_text = ""

    @property
    def is_idle(self) -> bool:
        return self._is_idle

    @property
    def conversation_id(self) -> str:
        return self._conversation_id

    @property
    def debug_config(self) -> Optional[connection.DebugConfig]:
        return self._debug_config

    @property
    def _last_turn_stop_reason(self) -> types.StopReason:
        return self._last_stop_reason

    def _build_new_conversation_cmd(self, prompt_text: str) -> list[str]:
        cmd = [self._binary_path, "new-conversation", f"--model={self._model_tier}"]
        if self._title:
            cmd.append(f"--title={self._title}")
        if self._profile:
            cmd.append(f"--profile={self._profile}")
        cmd.append(prompt_text)
        return cmd

    def _build_send_message_cmd(self, recipient_id: str, content_text: str) -> list[str]:
        cmd = [self._binary_path, "send-message"]
        if self._title:
            cmd.append(f"--title={self._title}")
        cmd.extend([recipient_id, content_text])
        return cmd

    async def send(self, prompt: types.Content | None, **kwargs: Any) -> None:
        """Sends a prompt or instruction to the agent session."""
        if os.environ.get("DISABLE_AGENTAPI") == "1":
            from unittest.mock import Mock, AsyncMock
            if not isinstance(asyncio.create_subprocess_exec, (Mock, AsyncMock)):
                raise RuntimeError("AgentAPI subprocess execution is blocked via DISABLE_AGENTAPI=1 to prevent credit consumption.")

        prompt_text = _extract_text_from_content(prompt)
        if not prompt_text.strip():
            raise ValueError("Cannot send empty prompt content.")

        self._is_idle = False
        self._turn_stop_event.clear()
        self._turn_start_time = time.time()
        self._last_prompt_text = prompt_text

        is_new = not bool(self._conversation_id)
        if is_new:
            cmd = self._build_new_conversation_cmd(prompt_text)
        else:
            cmd = self._build_send_message_cmd(self._conversation_id, prompt_text)

        logger.debug("Executing AgentAPI command: %s", " ".join(cmd[:3]))

        cwd_dir = None
        if self._workspace:
            ws_path = Path(self._workspace).resolve()
            if ws_path.exists() and ws_path.is_dir():
                cwd_dir = str(ws_path)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._active_process = proc

        # Launch monitor task to capture conversation_id and monitor process exit
        asyncio.create_task(self._monitor_turn(proc, is_new))

    async def _monitor_turn(self, proc: asyncio.subprocess.Process, is_new: bool) -> None:
        """Monitors the active turn process and signals completion."""
        status = TelemetryEventStatus.SUCCESS
        err_msg = None
        raw_out = ""
        duration_ms = 0.0
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout_seconds,
            )
            duration_ms = (time.time() - self._turn_start_time) * 1000
            raw_out = stdout.decode("utf-8", errors="replace").strip()
            raw_err = stderr.decode("utf-8", errors="replace").strip()

            if is_new and raw_out:
                match = UUID_PATTERN.search(raw_out)
                if match:
                    self._conversation_id = match.group(1)
                    logger.info("Captured conversation_id: %s", self._conversation_id)

            if proc.returncode == 0:
                self._last_stop_reason = types.StopReason.UNSPECIFIED
                status = TelemetryEventStatus.SUCCESS
            else:
                logger.error("agentapi exited with code %s: %s", proc.returncode, raw_err or raw_out)
                self._last_stop_reason = types.StopReason.UNSPECIFIED
                status = TelemetryEventStatus.ERROR
                err_msg = raw_err or raw_out
        except asyncio.TimeoutError:
            duration_ms = (time.time() - self._turn_start_time) * 1000
            logger.warning("agentapi turn timed out after %ss", self._timeout_seconds)
            self._last_stop_reason = types.StopReason.MAX_MODEL_CALLS_EXCEEDED
            status = TelemetryEventStatus.TIMEOUT
            err_msg = f"Timed out after {self._timeout_seconds}s"
            if proc.returncode is None:
                proc.kill()
        except Exception as e:
            duration_ms = (time.time() - self._turn_start_time) * 1000
            logger.exception("Error monitoring turn: %s", e)
            self._last_stop_reason = types.StopReason.UNSPECIFIED
            status = TelemetryEventStatus.ERROR
            err_msg = str(e)
        finally:
            self._turn_stop_event.set()
            self._is_idle = True
            self._active_process = None

            # Record telemetry and agent history (never fatal)
            try:
                if not self._enable_telemetry:
                    raise _TelemetryDisabled
                collector = TelemetryCollector.get_instance()
                collector.record_turn(
                    plugin_slug=self._plugin_slug,
                    agent_id=self._agent_id,
                    conversation_id=self._conversation_id,
                    model_tier=self._model_tier,
                    prompt_text=self._last_prompt_text,
                    response_text=raw_out,
                    turn_duration_ms=duration_ms,
                    status=status,
                    error_message=err_msg,
                )

                history = AgentHistoryManager.get_instance()
                history.record_turn(
                    conversation_id=self._conversation_id,
                    plugin_slug=self._plugin_slug,
                    agent_id=self._agent_id,
                    source="model" if status == TelemetryEventStatus.SUCCESS else "system",
                    content=raw_out or (err_msg or ""),
                    duration_ms=duration_ms,
                    status="done" if status == TelemetryEventStatus.SUCCESS else "error",
                )
            except _TelemetryDisabled:
                pass
            except Exception as ex:
                logger.error("Telemetry/History logging hook error: %s", ex)


    async def receive_steps(self) -> AsyncIterator[types.Step]:
        """Receives and yields Step objects in real time."""
        # Wait until conversation_id is resolved (either pre-existing or extracted)
        timeout = 10.0
        elapsed = 0.0
        while not self._conversation_id and elapsed < timeout and not self._turn_stop_event.is_set():
            await asyncio.sleep(0.05)
            elapsed += 0.05

        if not self._conversation_id:
            logger.warning("No conversation_id available for transcript streaming")
            return

        self._streamer = TranscriptStreamer(
            conversation_id=self._conversation_id,
            app_data_dir=self._app_data_dir,
        )

        async for step in self._streamer.stream_steps(self._turn_stop_event):
            yield step

    async def send_trigger_notification(self, content: str) -> None:
        """Sends a reactive trigger message into the running agent session."""
        if os.environ.get("DISABLE_AGENTAPI") == "1":
            from unittest.mock import Mock, AsyncMock
            if not isinstance(asyncio.create_subprocess_exec, (Mock, AsyncMock)):
                raise RuntimeError("AgentAPI subprocess execution is blocked via DISABLE_AGENTAPI=1 to prevent credit consumption.")

        if not self._conversation_id:
            logger.warning("Cannot send trigger notification: no conversation_id active")
            return

        cmd = self._build_send_message_cmd(self._conversation_id, content)
        logger.debug("Dispatching trigger notification to conversation %s", self._conversation_id)

        cwd_dir = None
        if self._workspace:
            ws_path = Path(self._workspace).resolve()
            if ws_path.exists() and ws_path.is_dir():
                cwd_dir = str(ws_path)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=self._timeout_seconds)
        except Exception as e:
            logger.error("Failed to deliver trigger notification: %s", e)

    async def wait_for_idle(self) -> None:
        """Blocks until the connection becomes idle."""
        while not self._is_idle:
            await asyncio.sleep(0.05)

    async def cancel(self) -> None:
        """Cancels the active turn in progress."""
        if self._active_process and self._active_process.returncode is None:
            self._active_process.kill()
        self._turn_stop_event.set()
        self._is_idle = True


class AgentAPIConnectionStrategy(connection.ConnectionStrategy):
    """Strategy for establishing a Connection to the local agentapi CLI."""

    def __init__(
        self,
        config: Any,
        tool_runner: Any,
        hook_runner: Any,
    ):
        self._config = config
        self._tool_runner = tool_runner
        self._hook_runner = hook_runner
        self._binary_path: Optional[str] = None
        self._connection: Optional[AgentAPIConnection] = None

    def _resolve_binary_path(self) -> str:
        """Resolves the executable path to agentapi (skipping stale wrappers)."""
        from gravitron_sdk.client import AgentAPIClient

        explicit = getattr(self._config, "binary_path", None)
        if explicit:
            return str(explicit)
        resolved = AgentAPIClient._resolve_binary_path()
        if resolved:
            return resolved
        raise FileNotFoundError(
            "Could not locate the 'agentapi' binary. Install the Antigravity IDE "
            "or set AGENTAPI_BINARY_PATH."
        )

    def connect(self) -> connection.Connection:
        """Returns the established Connection."""
        if not self._connection:
            raise RuntimeError("AgentAPIConnectionStrategy has not been initialized via __aenter__.")
        return self._connection

    async def __aenter__(self) -> None:
        """Validates the environment and prepares the connection."""
        self._binary_path = self._resolve_binary_path()
        app_data_dir = Path(getattr(self._config, "app_data_dir", None) or Path.home() / ".gemini" / "antigravity-ide")
        model_tier = str(getattr(self._config.model, "value", self._config.model))

        workspace = None
        if getattr(self._config, "workspaces", None) and len(self._config.workspaces) > 0:
            workspace = self._config.workspaces[0]
        elif getattr(self._config, "active_project", None):
            workspace = self._config.active_project
        elif getattr(self._config, "project_path", None):
            workspace = self._config.project_path

        self._connection = AgentAPIConnection(
            binary_path=self._binary_path,
            app_data_dir=app_data_dir,
            model_tier=model_tier,
            title=getattr(self._config, "title", None),
            profile=getattr(self._config, "profile", None),
            timeout_seconds=getattr(self._config, "timeout_seconds", 120),
            conversation_id=getattr(self._config, "conversation_id", None),
            debug_config=getattr(self._config, "debug_config", None),
            plugin_slug=getattr(self._config, "plugin_slug", "default"),
            agent_id=getattr(self._config, "agent_id", None) or getattr(self._config, "profile", None) or "default",
            workspace=workspace,
            enable_telemetry=getattr(self._config, "enable_telemetry", True),
        )

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Tears down the connection and cancels active processes."""
        if self._connection:
            await self._connection.cancel()
            self._connection = None
