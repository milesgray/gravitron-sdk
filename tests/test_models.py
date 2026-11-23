from google.antigravity import types

from gravitron_sdk.models import ModelTier
from gravitron_sdk.telemetry.storage import resolve_gravitron_data_dir, TelemetryStorage
from gravitron_sdk.history.manager import AgentHistoryManager


def _text_target(name):
    return types.ModelTarget(name=name, types=[types.ModelType.TEXT])


def test_model_tier_from_any():
    assert ModelTier.from_any("pro") == ModelTier.PRO
    assert ModelTier.from_any("flash_lite") == ModelTier.FLASH_LITE
    assert ModelTier.from_any("flash-lite") == ModelTier.FLASH_LITE
    assert ModelTier.from_any("gemini-2.5-pro") == ModelTier.PRO
    assert ModelTier.from_any("gemini-4-argon-medium") == ModelTier.PRO
    assert ModelTier.from_any("gemini-2.5-flash-lite") == ModelTier.FLASH_LITE
    assert ModelTier.from_any("gemini-2.5-flash") == ModelTier.FLASH
    assert ModelTier.from_any("FLASH") == ModelTier.FLASH
    assert ModelTier.from_any(ModelTier.PRO) == ModelTier.PRO
    assert ModelTier.from_any(_text_target("gemini-2.5-pro")) == ModelTier.PRO
    assert ModelTier.from_any(None, models=[_text_target("gemini-2.5-pro")]) == ModelTier.PRO
    assert ModelTier.from_any(None) == ModelTier.FLASH
    assert ModelTier.from_any("") == ModelTier.FLASH
    # "pro" must match as a token, not as a substring of an unrelated word
    assert ModelTier.from_any("gemini-prototype-flash") == ModelTier.FLASH


def test_resolve_gravitron_data_dir_env_override(tmp_path, monkeypatch):
    custom = tmp_path / "custom_data"
    monkeypatch.setenv("GRAVITRON_DATA_DIR", str(custom))
    assert resolve_gravitron_data_dir() == custom.resolve()
    assert TelemetryStorage().db_path == (custom / "telemetry.db").resolve()
    assert AgentHistoryManager().base_dir == (custom / "history").resolve()


def test_resolve_gravitron_data_dir_standalone_machine(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAVITRON_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert resolve_gravitron_data_dir() == (tmp_path / ".gemini" / "gravitron" / "data").resolve()
    hub = tmp_path / ".gemini" / "config"
    hub.mkdir(parents=True)
    (hub / "hub_server.py").write_text("")
    assert resolve_gravitron_data_dir() == (hub / "data").resolve()
