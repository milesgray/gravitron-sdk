from google.antigravity import LocalAgentConfig as UpstreamLocalAgentConfig
from google.antigravity.hooks import policy

from gravitron_sdk.models import ModelTier
from gravitron_sdk.connections.agentapi_config import (
    AgentAPIAgentConfig,
    GravitronAgentConfig,
    LocalAgentConfig,
)
from gravitron_sdk.connections.agentapi_connection import AgentAPIConnectionStrategy
from gravitron_sdk.connections.transcript_streamer import TranscriptStreamer


def test_drop_in_local_agent_config_accepts_all_upstream_params():
    cfg = LocalAgentConfig(
        model="gemini-2.5-pro",
        api_key="unused-cloud-key",
        vertex=True,
        project="unused-gcp-project",
        location="us-central1",
        workspaces=["/tmp"],
        system_instructions="You are a helpful coding agent.",
        policies=[policy.allow_all()],
        env={"CUSTOM_VAR": "1"},
        save_dir="/tmp",
    )
    assert isinstance(cfg, AgentAPIAgentConfig)
    assert cfg.model == ModelTier.PRO
    assert cfg.workspaces == ["/tmp"]
    assert isinstance(cfg.create_strategy(tool_runner=None, hook_runner=None), AgentAPIConnectionStrategy)


def test_eval_and_lightweight_presets_work():
    cfg = GravitronAgentConfig(model="flash")
    assert cfg.eval().model == ModelTier.FLASH
    assert cfg.lightweight().model == ModelTier.FLASH


def test_from_upstream_local_agent_config_conversion():
    upstream = UpstreamLocalAgentConfig(
        model="gemini-2.5-flash-lite",
        workspaces=["/tmp"],
        system_instructions="Inspect files carefully.",
        policies=[policy.allow_all()],
    )
    converted = GravitronAgentConfig.from_local_config(upstream)
    assert isinstance(converted, GravitronAgentConfig)
    assert converted.model == ModelTier.FLASH_LITE
    assert converted.workspaces == ["/tmp"]
    assert converted.system_instructions == "Inspect files carefully."
    assert len(converted.policies) == 1


def test_from_upstream_without_shorthand_model_defaults_to_flash():
    upstream = UpstreamLocalAgentConfig(workspaces=["/tmp"], policies=[policy.allow_all()])
    assert GravitronAgentConfig.from_local_config(upstream).model == ModelTier.FLASH


def test_transcript_streamer_fallback_across_antigravity_dirs(tmp_path):
    conv_id = "12345678-1234-1234-1234-123456789abc"
    ide_dir = tmp_path / "antigravity-ide"
    agy_dir = tmp_path / "antigravity"
    actual = agy_dir / "brain" / conv_id / ".system_generated" / "logs" / "transcript_full.jsonl"
    actual.parent.mkdir(parents=True)
    actual.write_text('{"step_index": 1, "source": "MODEL", "type": "TEXT_RESPONSE", "status": "DONE", "content": "ok"}\n')

    streamer = TranscriptStreamer(conv_id, ide_dir, poll_interval=0.01, fallback_app_data_dirs=[agy_dir])
    assert streamer.resolve_transcript_path() == actual
