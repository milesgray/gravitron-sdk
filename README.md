# Gravitron SDK

**Run [Google Antigravity SDK](https://pypi.org/project/google-antigravity/) agents on your personal Antigravity quota.**

The official `google-antigravity` SDK only talks to the Gemini API (`GEMINI_API_KEY`) or Vertex AI. If you already use the Antigravity IDE or CLI, you have model quota sitting on your machine that the SDK can't reach. Gravitron SDK adds a connection strategy that routes your agent through the local `agentapi` binary that ships with Antigravity, so the same agent code runs on that quota. You don't need an API key or a GCP project.

```bash
pip install gravitron-sdk
```

## Migrating: change one import

```python
# Before: needs GEMINI_API_KEY or Vertex AI billing
# from google.antigravity import Agent, LocalAgentConfig

# After: runs on your Antigravity IDE quota
from gravitron_sdk import Agent, LocalAgentConfig, policy

config = LocalAgentConfig(
    model="gemini-2.5-pro",          # mapped to the agentapi "pro" tier
    workspaces=["."],
    system_instructions="You are a careful code reviewer.",
    policies=[policy.allow_all()],
)

async with Agent(config) as agent:
    response = await agent.chat("Summarize the open TODOs in this repo.")
    print(await response.text())
```

Everything else stays the same: tools, hooks, policies, triggers and `Conversation`. `gravitron_sdk` re-exports the full `google.antigravity` public API, so `import gravitron_sdk as antigravity` also works.

### Other ways to switch

```python
# Keep your existing upstream config and swap only Agent:
import google.antigravity as upstream
from gravitron_sdk import Agent

agent = Agent(upstream.LocalAgentConfig(model="gemini-2.5-flash", workspaces=["."]))

# Explicit names:
from gravitron_sdk import GravitronAgent, GravitronAgentConfig
agent = GravitronAgent(GravitronAgentConfig(model="pro", title="Nightly audit"))

# Keyword shorthand:
agent = GravitronAgent(model="flash")
```

### Model mapping

`agentapi` exposes three tiers. Model names are mapped as follows:

| You pass | Tier |
| :--- | :--- |
| `"flash_lite"`, `"flash-lite"`, anything containing `lite` | `flash_lite` |
| `"pro"`, or a name containing `pro` / `argon` / `opus` / `sonnet` / `ultra` | `pro` |
| `"flash"`, any other name, or nothing | `flash` |

`types.ModelTarget` objects and `models=[...]` lists are also accepted.

Cloud-only `LocalAgentConfig` arguments (`api_key`, `vertex`, `project`, `location`, `env`) are accepted so that existing code doesn't break, but they have no effect.

## Reactive background agents

```python
import asyncio
from gravitron_sdk import Agent, LocalAgentConfig, every, on_file_change, on_ipc_message

async def nightly(ctx):
    await ctx.send("Scan the workspace for circular imports and report findings.")

async def on_ui_command(cmd, ctx):
    if cmd.get("action") == "reindex":
        await ctx.send("Rebuild the architecture summary.")

config = LocalAgentConfig(
    model="flash",
    triggers=[
        every("15m", nightly),
        on_file_change("src/**/*.py", lambda change, ctx: ctx.send(f"{change.path} changed; re-check types.")),
        on_ipc_message(on_ui_command, socket_path="/tmp/my-agent.sock"),
    ],
)

async def main():
    async with Agent(config):
        await asyncio.Event().wait()

asyncio.run(main())
```

`on_ipc_message` listens on a Unix domain socket for newline-delimited JSON commands. It needs Linux, macOS or WSL.

## Configuration

| Option | Default | Description |
| :--- | :--- | :--- |
| `model` | `flash` | Tier or model name (see mapping above). |
| `title` | `None` | Conversation title shown in Antigravity. |
| `profile` | `None` | agentapi execution profile. |
| `timeout_seconds` | `120` | Per-turn subprocess timeout (5–600). |
| `binary_path` | auto | Path to `agentapi`. |
| `app_data_dir` | auto | Antigravity data dir that contains `brain/` transcripts. |
| `enable_telemetry` | `True` | Record local token estimates and turn history. |

| Environment variable | Purpose |
| :--- | :--- |
| `AGENTAPI_BINARY_PATH` | Explicit `agentapi` location. Otherwise `$PATH`, `~/.gemini/antigravity/bin`, `~/.gemini/antigravity-ide/bin` are searched. |
| `ANTIGRAVITY_APP_DATA_DIR` | Explicit app data dir. Otherwise `~/.gemini/antigravity` or `~/.gemini/antigravity-ide`, whichever has a `brain/` folder. |
| `GRAVITRON_DATA_DIR` | Where telemetry (`telemetry.db`) and history are written. Default `~/.gemini/gravitron/data`. |
| `DISABLE_AGENTAPI=1` | Block real `agentapi` calls (useful in tests). |

## Requirements

- Python 3.10+
- An installed, signed-in Antigravity IDE that provides the `agentapi` binary

## Development

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest
uv build
```

## License

MIT
