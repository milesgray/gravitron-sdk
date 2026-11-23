#!/usr/bin/env python3
"""
Unit and integration test suite for AgentAPI Connection Strategy and Gravitron SDK.
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from google.antigravity import types
from gravitron_sdk import (
    Agent,
    AgentAPIAgentConfig,
    AgentAPIConnection,
    AgentAPIConnectionStrategy,
    Context7Client,
    TranscriptStreamer,
)
from gravitron_sdk.models import ModelTier, TranscriptStepRecord


class TestAgentAPIAgentConfig(unittest.TestCase):
    """Tests for declarative AgentAPIAgentConfig."""

    def test_default_config(self):
        config = AgentAPIAgentConfig()
        self.assertEqual(config.model, ModelTier.FLASH)
        self.assertEqual(config.timeout_seconds, 120)
        self.assertIsNotNone(config.app_data_dir)

    def test_custom_config(self):
        config = AgentAPIAgentConfig(
            model="pro",
            title="Architecture Reviewer",
            profile="architect",
            timeout_seconds=45,
        )
        self.assertEqual(config.model, ModelTier.PRO)
        self.assertEqual(config.title, "Architecture Reviewer")
        self.assertEqual(config.profile, "architect")
        self.assertEqual(config.timeout_seconds, 45)

    def test_create_strategy(self):
        config = AgentAPIAgentConfig()
        strategy = config.create_strategy(tool_runner=None, hook_runner=None)
        self.assertIsInstance(strategy, AgentAPIConnectionStrategy)


class TestTranscriptStreamer(unittest.IsolatedAsyncioTestCase):
    """Tests for the asynchronous transcript streamer."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app_data_dir = Path(self.temp_dir.name)
        self.conv_id = "test-conv-12345678-1234-1234-1234-123456789abc"
        self.logs_dir = self.app_data_dir / "brain" / self.conv_id / ".system_generated" / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_file = self.logs_dir / "transcript_full.jsonl"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_record_to_step(self):
        streamer = TranscriptStreamer(self.conv_id, self.app_data_dir)
        record = TranscriptStepRecord(
            step_index=1,
            source="MODEL",
            type="PLANNER_RESPONSE",
            status="DONE",
            content="Plan execution in progress.",
            tool_calls=[{"name": "view_file", "id": "call-1", "arguments": {"path": "a.txt"}}],
        )
        step = streamer.parse_record_to_step(record)
        self.assertEqual(step.step_index, 1)
        self.assertEqual(step.source, types.StepSource.MODEL)
        self.assertEqual(step.status, types.StepStatus.DONE)
        self.assertEqual(step.content_delta, "Plan execution in progress.")
        self.assertIsNotNone(step.tool_calls)
        self.assertEqual(len(step.tool_calls), 1)
        self.assertEqual(step.tool_calls[0].name, "view_file")

    async def test_stream_steps_from_file(self):
        streamer = TranscriptStreamer(self.conv_id, self.app_data_dir, poll_interval=0.01)

        # Write lines to transcript
        records = [
            {"step_index": 1, "source": "USER", "type": "USER_INPUT", "status": "DONE", "content": "Hello"},
            {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE", "content": "Hi there!"},
        ]
        with open(self.transcript_file, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        stop_event = asyncio.Event()
        stop_event.set()  # Stop immediately after draining

        steps = []
        async for step in streamer.stream_steps(stop_event):
            steps.append(step)

        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0].content_delta, "Hello")
        self.assertEqual(steps[1].content_delta, "Hi there!")


class TestAgentAPIConnection(unittest.IsolatedAsyncioTestCase):
    """Tests for the AgentAPIConnection command builder and turn lifecycle."""

    def test_command_generation(self):
        conn = AgentAPIConnection(
            binary_path="/mock/bin/agentapi",
            app_data_dir=Path("/mock/app"),
            model_tier="flash",
            title="Test Session",
        )
        new_cmd = conn._build_new_conversation_cmd("Analyze this code")
        self.assertEqual(new_cmd, ["/mock/bin/agentapi", "new-conversation", "--model=flash", "--title=Test Session", "Analyze this code"])

        send_cmd = conn._build_send_message_cmd("conv-uuid", "Next step")
        self.assertEqual(send_cmd, ["/mock/bin/agentapi", "send-message", "--title=Test Session", "conv-uuid", "Next step"])

    @patch("asyncio.create_subprocess_exec")
    async def test_send_and_conversation_id_extraction(self, mock_subprocess):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"Started session: 12345678-1234-1234-1234-123456789abc\n",
            b"",
        )
        mock_proc.returncode = 0
        mock_subprocess.return_value = mock_proc

        conn = AgentAPIConnection(
            binary_path="/mock/bin/agentapi",
            app_data_dir=Path("/mock/app"),
        )
        await conn.send("Initialize agent")
        # Allow monitor task to run
        await asyncio.sleep(0.05)

        self.assertEqual(conn.conversation_id, "12345678-1234-1234-1234-123456789abc")
        self.assertTrue(conn.is_idle)
        self.assertEqual(conn._last_turn_stop_reason, types.StopReason.UNSPECIFIED)


class TestContext7Client(unittest.TestCase):
    """Tests for the Context 7 documentation grounding client."""

    def test_resolve_library(self):
        client = Context7Client()
        self.assertEqual(client.resolve_library("antigravity"), "/google/antigravity")
        self.assertEqual(client.resolve_library("fastapi"), "/fastapi")


class TestAgentIntegration(unittest.TestCase):
    """Tests Agent compatibility with AgentAPIAgentConfig."""

    def test_agent_initialization(self):
        from google.antigravity.hooks import policy
        config = AgentAPIAgentConfig(
            model="flash",
            title="SDK Test Session",
            policies=[policy.allow_all()],
        )
        agent = Agent(config)
        self.assertIsNotNone(agent)
        self.assertEqual(agent._config.model, ModelTier.FLASH)


if __name__ == "__main__":
    unittest.main()
