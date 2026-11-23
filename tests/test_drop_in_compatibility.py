import google.antigravity as upstream_agy
import pytest

import gravitron_sdk as agy
from gravitron_sdk import (
    Agent,
    AgentAPIAgentConfig,
    BuiltinTools,
    CapabilitiesConfig,
    GravitronAgent,
    GravitronAgentConfig,
    LocalAgentConfig,
    ModelTier,
    policy,
)


def test_all_upstream_antigravity_symbols_exported():
    for symbol in upstream_agy.__all__:
        assert hasattr(agy, symbol), f"Missing upstream symbol: {symbol}"
    # The drop-in names must be Gravitron's, not upstream's
    assert agy.Agent is GravitronAgent
    assert agy.LocalAgentConfig is GravitronAgentConfig


def test_swap_import_replacement():
    config = LocalAgentConfig(
        model="gemini-2.5-pro",
        workspaces=["/tmp"],
        capabilities=CapabilitiesConfig(enabled_tools=BuiltinTools.read_only()),
        policies=[policy.allow_all()],
    )
    agent = Agent(config)
    assert isinstance(agent, upstream_agy.Agent)
    assert isinstance(agent._config, AgentAPIAgentConfig)
    assert agent._config.model == ModelTier.PRO


def test_swap_pass_unmodified_upstream_config():
    upstream_config = upstream_agy.LocalAgentConfig(
        model="gemini-2.5-flash-lite",
        workspaces=["/tmp"],
        system_instructions="Use native quota",
        policies=[policy.allow_all()],
    )
    agent = Agent(upstream_config)
    assert isinstance(agent._config, GravitronAgentConfig)
    assert agent._config.model == ModelTier.FLASH_LITE
    assert agent._config.system_instructions == "Use native quota"


def test_zero_config_and_kwargs_shorthand():
    agent_default = Agent()
    assert isinstance(agent_default._config, GravitronAgentConfig)
    assert agent_default._config.model == ModelTier.FLASH

    agent_pro = GravitronAgent(model="pro", title="Quick Session")
    assert agent_pro._config.model == ModelTier.PRO
    assert agent_pro._config.title == "Quick Session"


def test_config_and_kwargs_together_is_an_error():
    with pytest.raises(TypeError):
        Agent(GravitronAgentConfig(), model="pro")
