"""
Reactive Triggers subsystem for Gravitron Sidecars and Agents.
Re-exports Google Antigravity SDK triggers and adds the Unix Domain Socket on_ipc_message trigger.
"""

from typing import Callable, Awaitable, Any
import asyncio
import json
import logging
from pathlib import Path

from google.antigravity.triggers import (
    every,
    on_file_change,
    trigger,
    TriggerContext,
)

logger = logging.getLogger("Gravitron.Triggers")


def on_ipc_message(
    callback: Callable[[dict[str, Any], TriggerContext], Awaitable[None]],
    socket_path: str | Path | None = None,
):
    """
    Reactive trigger that listens on a Unix Domain Socket (ipc.sock) for commands
    dispatched from Bespoke Agent Web UIs, invoking the callback with the parsed
    payload and TriggerContext.
    """

    @trigger
    async def _ipc_trigger_loop(ctx: TriggerContext) -> None:
        sock_file = Path(socket_path or (Path.home() / ".gemini" / "antigravity" / "ipc.sock"))
        sock_file.parent.mkdir(parents=True, exist_ok=True)
        if sock_file.exists():
            try:
                sock_file.unlink()
            except OSError:
                pass

        async def _client_connected(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                while not reader.at_eof():
                    line = await reader.readline()
                    if not line:
                        break
                    raw = line.decode("utf-8").strip()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        payload = {"raw": raw}
                    await callback(payload, ctx)
            except Exception as e:
                logger.error("Error in IPC trigger client handler: %s", e)
            finally:
                writer.close()
                await writer.wait_closed()

        try:
            server = await asyncio.start_unix_server(_client_connected, path=str(sock_file))
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            logger.info("IPC trigger loop cancelled, shutting down socket listener")
        finally:
            if sock_file.exists():
                try:
                    sock_file.unlink()
                except OSError:
                    pass

    return _ipc_trigger_loop


__all__ = [
    "every",
    "on_file_change",
    "on_ipc_message",
    "trigger",
    "TriggerContext",
]
