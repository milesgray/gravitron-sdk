#!/usr/bin/env python3
"""
Canonical Python client for the Antigravity AgentAPI CLI.
Provides strongly typed sync and async abstractions, automatic binary location discovery,
and structured JSON response parsing.
"""

import os
import re
import sys
import json
import shutil
import asyncio
import logging
import subprocess
from pathlib import Path
import time
from typing import Optional, Type, TypeVar, Any, List

from pydantic import BaseModel
from gravitron_sdk.models import (
    ModelTier,
    ConversationResponse,
    SendMessageResponse,
    ConversationMetadata,
    WorkspaceMetadata,
)
from gravitron_sdk.telemetry import TelemetryCollector, TelemetryEventStatus
from gravitron_sdk.history import AgentHistoryManager

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("Antigravity.AgentAPI")

DEFAULT_IDE_BIN = Path.home() / ".gemini" / "antigravity-ide" / "bin" / "agentapi"


UUID_PATTERN = re.compile(r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})", re.I)
MARKDOWN_JSON_PATTERN = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)


class AgentAPIClient:
    """Strongly typed client for interacting with the Antigravity agentapi binary."""

    def __init__(self, binary_path: Optional[str] = None):
        self._binary_path: Optional[str] = binary_path or self._resolve_binary_path()

    def _record_telemetry(
        self,
        prompt: str,
        output: str,
        duration_ms: float,
        model: Any = ModelTier.FLASH,
        conversation_id: Optional[str] = None,
        profile: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """Internal hook to log telemetry events and agent history if subsystem is present."""
        if TelemetryCollector is None:
            return
        try:
            agent_id = profile or "default"
            status = TelemetryEventStatus.SUCCESS if success else TelemetryEventStatus.ERROR
            model_tier = str(getattr(model, "value", model))
            TelemetryCollector.get_instance().record_turn(
                plugin_slug="agentapi",
                agent_id=agent_id,
                conversation_id=conversation_id or "",
                model_tier=model_tier,
                prompt_text=prompt,
                response_text=output,
                turn_duration_ms=duration_ms,
                status=status,
                error_message=error,
            )
            if AgentHistoryManager is not None and conversation_id:
                AgentHistoryManager.get_instance().record_turn(
                    conversation_id=conversation_id,
                    plugin_slug="agentapi",
                    agent_id=agent_id,
                    source="model" if success else "system",
                    content=output or (error or ""),
                    duration_ms=duration_ms,
                    status="done" if success else "error",
                )
        except Exception as e:
            logger.debug("Telemetry logging skipped: %s", e)


    @property
    def binary_path(self) -> str:
        if not self._binary_path:
            resolved = self._resolve_binary_path()
            if not resolved:
                raise FileNotFoundError(
                    "Could not locate the 'agentapi' binary. Ensure Antigravity IDE is installed."
                )
            self._binary_path = resolved
        return self._binary_path

    @staticmethod
    def _is_runnable_binary(path: Path) -> bool:
        if not path.is_file() or not os.access(path, os.X_OK):
            return False
        try:
            head = path.read_bytes()[:512]
            if head.startswith(b"#!"):
                text = head.decode("utf-8", errors="replace")
                m = re.search(r'^\s*exec\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))', text, re.MULTILINE)
                if m:
                    target = m.group(1) or m.group(2) or m.group(3)
                    if target and target.startswith("/"):
                        tpath = Path(target)
                        return tpath.is_file() and os.access(tpath, os.X_OK)
        except OSError:
            return False
        return True

    @staticmethod
    def _resolve_binary_path() -> Optional[str]:
        """Resolves a runnable executable path to agentapi, skipping stale wrappers."""
        candidates: List[Path] = []
        env_path = os.environ.get("AGENTAPI_BINARY_PATH")
        if env_path:
            candidates.append(Path(env_path).expanduser())
        which_path = shutil.which("agentapi")
        if which_path:
            candidates.append(Path(which_path))

        home = Path.home()
        candidates.extend(
            [
                home / ".gemini" / "antigravity" / "bin" / "agentapi",
                DEFAULT_IDE_BIN,
            ]
        )
        gemini_dir = home / ".gemini"
        if gemini_dir.is_dir():
            candidates.extend(
                sorted(
                    gemini_dir.glob("**/bin/agentapi"),
                    key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
                    reverse=True,
                )
            )

        seen: set[Path] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            if AgentAPIClient._is_runnable_binary(candidate):
                return str(candidate)

        return None

    def _build_new_conversation_cmd(
        self,
        prompt: str,
        model: ModelTier,
        title: Optional[str] = None,
        profile: Optional[str] = None
    ) -> List[str]:
        cmd = [self.binary_path, "new-conversation", f"--model={model.value}"]
        if title:
            cmd.append(f"--title={title}")
        if profile:
            cmd.append(f"--profile={profile}")
        cmd.append(prompt)
        return cmd

    def new_conversation(
        self,
        prompt: str,
        model: ModelTier = ModelTier.FLASH,
        title: Optional[str] = None,
        profile: Optional[str] = None,
        timeout_seconds: int = 120
    ) -> ConversationResponse:
        """Starts a new agent conversation synchronously."""
        if os.environ.get("DISABLE_AGENTAPI") == "1" or "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
            from unittest.mock import Mock
            if not isinstance(subprocess.run, Mock):
                return ConversationResponse(success=False, error="AgentAPI execution disabled to prevent credit consumption")

        cmd = self._build_new_conversation_cmd(prompt, model, title, profile)
        t0 = time.time()

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds
            )
            dur_ms = (time.time() - t0) * 1000
            raw = (res.stdout or "").strip()
            err = (res.stderr or "").strip()

            if res.returncode == 0:
                cid = self._extract_conversation_id(raw)
                self._record_telemetry(
                    prompt=prompt,
                    output=raw,
                    duration_ms=dur_ms,
                    model=model,
                    conversation_id=cid,
                    profile=profile,
                    success=True,
                )
                return ConversationResponse(
                    success=True,
                    conversation_id=cid,
                    output=raw,
                    raw_output=raw
                )
            self._record_telemetry(
                prompt=prompt,
                output=raw,
                duration_ms=dur_ms,
                model=model,
                profile=profile,
                success=False,
                error=err or raw,
            )
            return ConversationResponse(
                success=False,
                error=err or raw or f"Process exited with code {res.returncode}",
                raw_output=raw
            )
        except subprocess.TimeoutExpired:
            dur_ms = (time.time() - t0) * 1000
            self._record_telemetry(
                prompt=prompt,
                output="",
                duration_ms=dur_ms,
                model=model,
                profile=profile,
                success=False,
                error=f"agentapi new-conversation timed out after {timeout_seconds}s",
            )
            return ConversationResponse(
                success=False,
                error=f"agentapi new-conversation timed out after {timeout_seconds}s"
            )
        except Exception as e:
            dur_ms = (time.time() - t0) * 1000
            self._record_telemetry(
                prompt=prompt,
                output="",
                duration_ms=dur_ms,
                model=model,
                profile=profile,
                success=False,
                error=str(e),
            )
            return ConversationResponse(
                success=False,
                error=str(e)
            )

    async def new_conversation_async(
        self,
        prompt: str,
        model: ModelTier = ModelTier.FLASH,
        title: Optional[str] = None,
        profile: Optional[str] = None,
        timeout_seconds: int = 120
    ) -> ConversationResponse:
        """Starts a new agent conversation asynchronously."""
        if os.environ.get("DISABLE_AGENTAPI") == "1" or "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
            from unittest.mock import Mock, AsyncMock
            if not isinstance(asyncio.create_subprocess_exec, (Mock, AsyncMock)):
                return ConversationResponse(success=False, error="AgentAPI execution disabled to prevent credit consumption")

        cmd = self._build_new_conversation_cmd(prompt, model, title, profile)
        t0 = time.time()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds
            )
            dur_ms = (time.time() - t0) * 1000
            raw = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode == 0:
                cid = self._extract_conversation_id(raw)
                self._record_telemetry(
                    prompt=prompt,
                    output=raw,
                    duration_ms=dur_ms,
                    model=model,
                    conversation_id=cid,
                    profile=profile,
                    success=True,
                )
                return ConversationResponse(
                    success=True,
                    conversation_id=cid,
                    output=raw,
                    raw_output=raw
                )
            self._record_telemetry(
                prompt=prompt,
                output=raw,
                duration_ms=dur_ms,
                model=model,
                profile=profile,
                success=False,
                error=err or raw,
            )
            return ConversationResponse(
                success=False,
                error=err or raw or f"Process exited with code {proc.returncode}",
                raw_output=raw
            )
        except asyncio.TimeoutError:
            dur_ms = (time.time() - t0) * 1000
            self._record_telemetry(
                prompt=prompt,
                output="",
                duration_ms=dur_ms,
                model=model,
                profile=profile,
                success=False,
                error=f"agentapi new-conversation timed out after {timeout_seconds}s",
            )
            return ConversationResponse(
                success=False,
                error=f"agentapi new-conversation timed out after {timeout_seconds}s"
            )
        except Exception as e:
            dur_ms = (time.time() - t0) * 1000
            self._record_telemetry(
                prompt=prompt,
                output="",
                duration_ms=dur_ms,
                model=model,
                profile=profile,
                success=False,
                error=str(e),
            )
            return ConversationResponse(
                success=False,
                error=str(e)
            )

    def send_message(
        self,
        recipient_id: str,
        content: str,
        title: Optional[str] = None,
        timeout_seconds: int = 120
    ) -> SendMessageResponse:
        """Sends a message to an ongoing conversation synchronously."""
        if os.environ.get("DISABLE_AGENTAPI") == "1" or "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
            from unittest.mock import Mock
            if not isinstance(subprocess.run, Mock):
                return SendMessageResponse(success=False, error="AgentAPI execution disabled to prevent credit consumption")

        cmd = [self.binary_path, "send-message"]
        if title:
            cmd.append(f"--title={title}")
        cmd.extend([recipient_id, content])
        t0 = time.time()

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds
            )
            dur_ms = (time.time() - t0) * 1000
            raw = (res.stdout or "").strip()
            err = (res.stderr or "").strip()

            if res.returncode == 0:
                self._record_telemetry(
                    prompt=content,
                    output=raw,
                    duration_ms=dur_ms,
                    conversation_id=recipient_id,
                    success=True,
                )
                return SendMessageResponse(
                    success=True,
                    recipient_id=recipient_id,
                    output=raw
                )
            self._record_telemetry(
                prompt=content,
                output=raw,
                duration_ms=dur_ms,
                conversation_id=recipient_id,
                success=False,
                error=err or raw,
            )
            return SendMessageResponse(
                success=False,
                recipient_id=recipient_id,
                error=err or raw or f"Process exited with code {res.returncode}"
            )
        except subprocess.TimeoutExpired:
            dur_ms = (time.time() - t0) * 1000
            self._record_telemetry(
                prompt=content,
                output="",
                duration_ms=dur_ms,
                conversation_id=recipient_id,
                success=False,
                error=f"agentapi send-message timed out after {timeout_seconds}s",
            )
            return SendMessageResponse(
                success=False,
                recipient_id=recipient_id,
                error=f"agentapi send-message timed out after {timeout_seconds}s"
            )
        except Exception as e:
            dur_ms = (time.time() - t0) * 1000
            self._record_telemetry(
                prompt=content,
                output="",
                duration_ms=dur_ms,
                conversation_id=recipient_id,
                success=False,
                error=str(e),
            )
            return SendMessageResponse(
                success=False,
                recipient_id=recipient_id,
                error=str(e)
            )

    def get_metadata(
        self,
        conversation_id: str,
        timeout_seconds: int = 30
    ) -> Optional[ConversationMetadata]:
        """Fetches and parses metadata for a conversation synchronously."""
        cmd = [self.binary_path, "get-conversation-metadata", conversation_id]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds
            )
            if res.returncode != 0 or not res.stdout.strip():
                return None

            data = json.loads(res.stdout.strip())
            conv_meta = data.get("response", {}).get("conversationMetadata", {}).get("metadata", {})
            workspaces_raw = conv_meta.get("workspaces", [])
            workspaces = [
                WorkspaceMetadata(
                    workspaceFolderAbsoluteUri=w.get("workspaceFolderAbsoluteUri"),
                    gitRootAbsoluteUri=w.get("gitRootAbsoluteUri"),
                    branchName=w.get("branchName")
                )
                for w in workspaces_raw
            ]

            return ConversationMetadata(
                conversation_id=conversation_id,
                root_conversation_id=conv_meta.get("rootConversationId"),
                parent_conversation_id=conv_meta.get("parentConversationId"),
                created_at=conv_meta.get("createdAt"),
                workspaces=workspaces,
                raw_json=data
            )
        except Exception as e:
            logger.error(f"Error getting conversation metadata for {conversation_id}: {e}")
            return None

    @staticmethod
    def _extract_conversation_id(text: str) -> Optional[str]:
        """Heuristic to extract UUID / conversation ID from agentapi output if present."""
        uuid_match = UUID_PATTERN.search(text)
        return uuid_match.group(1) if uuid_match else None

    @staticmethod
    def parse_structured_json(raw_text: str, model_cls: Type[T]) -> Optional[T]:
        """
        Extracts and parses JSON wrapped in markdown code blocks or raw strings
        into a strongly-typed Pydantic model.
        """
        cleaned = raw_text.strip()
        match = MARKDOWN_JSON_PATTERN.search(cleaned)
        if match:
            cleaned = match.group(1).strip()

        try:
            parsed = json.loads(cleaned)
            return model_cls.model_validate(parsed)
        except Exception:
            # Fallback: scan for first { and last }
            first_brace = cleaned.find("{")
            last_brace = cleaned.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                try:
                    subset = cleaned[first_brace : last_brace + 1]
                    parsed = json.loads(subset)
                    return model_cls.model_validate(parsed)
                except Exception:
                    pass
        return None
