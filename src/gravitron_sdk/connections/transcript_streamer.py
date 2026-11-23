#!/usr/bin/env python3
"""
Asynchronous Transcript Streamer for AgentAPI Conversations.
Tails transcript_full.jsonl non-blockingly, parsing JSONL records
into strongly typed Google Antigravity SDK Step objects.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncIterator, List, Optional, Dict, Any

from google.antigravity import types
from gravitron_sdk.models import TranscriptStepRecord

logger = logging.getLogger("Gravitron.TranscriptStreamer")

SOURCE_MAP = {
    "MODEL": types.StepSource.MODEL,
    "USER_EXPLICIT": types.StepSource.USER,
    "USER": types.StepSource.USER,
    "SYSTEM": types.StepSource.SYSTEM,
}

STATUS_MAP = {
    "DONE": types.StepStatus.DONE,
    "ERROR": types.StepStatus.ERROR,
    "RUNNING": types.StepStatus.ACTIVE,
    "ACTIVE": types.StepStatus.ACTIVE,
    "CANCELED": types.StepStatus.CANCELED,
    "WAITING_FOR_USER": types.StepStatus.WAITING_FOR_USER,
}

TYPE_MAP = {
    "USER_INPUT": types.StepType.TEXT_RESPONSE,
    "PLANNER_RESPONSE": types.StepType.TEXT_RESPONSE,
    "TEXT_RESPONSE": types.StepType.TEXT_RESPONSE,
    "TOOL_CALL": types.StepType.TOOL_CALL,
    "TOOL_RESPONSE": types.StepType.TOOL_CALL,
    "SYSTEM_MESSAGE": types.StepType.SYSTEM_MESSAGE,
    "FINISH": types.StepType.FINISH,
    "COMPACTION": types.StepType.COMPACTION,
    "THINKING": types.StepType.THINKING,
}


class TranscriptStreamer:
    """Streams and parses real-time execution steps from transcript_full.jsonl."""

    def __init__(
        self,
        conversation_id: str,
        app_data_dir: Path,
        poll_interval: float = 0.05,
        fallback_app_data_dirs: Optional[List[Path]] = None,
    ):
        self.conversation_id = conversation_id
        self.app_data_dir = Path(app_data_dir)
        self.poll_interval = poll_interval
        if fallback_app_data_dirs is None:
            fallback_app_data_dirs = [
                Path.home() / ".gemini" / "antigravity",
                Path.home() / ".gemini" / "antigravity-ide",
            ]
        self._search_dirs: List[Path] = [self.app_data_dir] + [
            Path(d) for d in fallback_app_data_dirs if Path(d) != self.app_data_dir
        ]
        self._transcript_path = self._transcript_path_for(self.app_data_dir)
        self._last_offset = 0
        self._seen_step_indices: set[int] = set()

    def _transcript_path_for(self, base: Path) -> Path:
        return (
            base
            / "brain"
            / self.conversation_id
            / ".system_generated"
            / "logs"
            / "transcript_full.jsonl"
        )

    @property
    def transcript_path(self) -> Path:
        return self._transcript_path

    def resolve_transcript_path(self) -> Path:
        """Return the first existing transcript across the primary and fallback dirs."""
        for base in self._search_dirs:
            candidate = self._transcript_path_for(base)
            if candidate.exists():
                self._transcript_path = candidate
                return candidate
        return self._transcript_path

    async def wait_for_transcript_file(self, timeout_seconds: float = 5.0) -> bool:
        """Polls for the creation of the transcript file in any known app data dir."""
        elapsed = 0.0
        while elapsed < timeout_seconds:
            path = self.resolve_transcript_path()
            if path.exists() and path.stat().st_size > 0:
                return True
            await asyncio.sleep(self.poll_interval)
            elapsed += self.poll_interval
        return self.resolve_transcript_path().exists()

    def parse_record_to_step(self, record: TranscriptStepRecord) -> types.Step:
        """Converts a parsed TranscriptStepRecord into a types.Step."""
        source = SOURCE_MAP.get(record.source.upper(), types.StepSource.SYSTEM)
        status = STATUS_MAP.get(record.status.upper(), types.StepStatus.DONE)
        step_type = TYPE_MAP.get(record.type.upper(), types.StepType.TEXT_RESPONSE)

        # Convert tool calls if present
        converted_tool_calls: List[types.ToolCall] = []
        if record.tool_calls:
            converted_tool_calls = []
            for tc in record.tool_calls:
                call_id = tc.get("id") or tc.get("call_id") or tc.get("name")
                tool_name = tc.get("name") or "unknown_tool"
                args = tc.get("arguments") or tc.get("args") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"raw": args}
                converted_tool_calls.append(
                    types.ToolCall(
                        id=str(call_id),
                        name=str(tool_name),
                        arguments=args if isinstance(args, dict) else {},
                    )
                )

        return types.Step(
            step_index=record.step_index,
            source=source,
            type=step_type,
            status=status,
            content_delta=record.content,
            tool_calls=converted_tool_calls,
        )

    async def stream_steps(
        self,
        stop_event: asyncio.Event,
        max_drain_attempts: int = 10,
    ) -> AsyncIterator[types.Step]:
        """
        Asynchronously tails transcript_full.jsonl and yields Step objects.
        Continues until stop_event is set and remaining complete lines are drained.
        """
        ready = await self.wait_for_transcript_file()
        if not ready:
            logger.warning("Transcript file %s not found within timeout", self._transcript_path)
            return

        drain_count = 0
        buffer = ""

        try:
            with open(self._transcript_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._last_offset)

                while True:
                    chunk = f.read()
                    if chunk:
                        buffer += chunk
                        self._last_offset = f.tell()

                        lines = buffer.split("\n")
                        # The last element after split is either empty (if ended with \n)
                        # or an incomplete partial line that must remain in the buffer.
                        buffer = lines.pop()

                        for line in lines:
                            cleaned = line.strip()
                            if not cleaned:
                                continue
                            try:
                                data = json.loads(cleaned)
                                record = TranscriptStepRecord.model_validate(data)
                                if record.step_index not in self._seen_step_indices:
                                    self._seen_step_indices.add(record.step_index)
                                    step = self.parse_record_to_step(record)
                                    yield step
                            except json.JSONDecodeError:
                                logger.debug("Skipping invalid JSON line: %s", cleaned[:80])
                            except Exception as e:
                                logger.warning("Error deserializing transcript record: %s", e)

                    if stop_event.is_set():
                        drain_count += 1
                        if drain_count >= max_drain_attempts or not chunk:
                            break

                    await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            logger.debug("Transcript streaming cancelled for %s", self.conversation_id)
            raise
        except Exception as e:
            logger.error("Error during transcript streaming: %s", e)
