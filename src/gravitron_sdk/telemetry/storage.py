#!/usr/bin/env python3
"""
Persistent SQLite storage engine for Gravitron SDK Telemetry & Quota Tracking.
Configured with WAL mode, busy timeouts, and indexed queries for sub-5ms performance.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
import sqlite3
import threading
from typing import List, Optional

from gravitron_sdk.telemetry.models import (
    AgentTelemetrySummary,
    GlobalTelemetrySummary,
    GranularMetricRecord,
    PluginQuotaSummary,
    TelemetryEvent,
    TelemetryEventStatus,
    UsageQueryFilter,
)

def resolve_gravitron_data_dir() -> Path:
    """Resolve where Gravitron persists telemetry and history.

    Order: ``GRAVITRON_DATA_DIR`` env var, then ``~/.gemini/config/data`` when a
    Gravitron Hub install is present, else ``~/.gemini/gravitron/data``.
    """
    env_dir = os.environ.get("GRAVITRON_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    hub_config = Path.home() / ".gemini" / "config"
    if (hub_config / "hub_server.py").exists():
        return (hub_config / "data").resolve()
    return (Path.home() / ".gemini" / "gravitron" / "data").resolve()


class TelemetryStorage:
    """Thread-safe SQLite store for telemetry events and rolling quota summaries."""

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = Path(db_path or (resolve_gravitron_data_dir() / "telemetry.db")).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Retrieves or creates a thread-local SQLite connection with WAL mode."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=5.0,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            # Execute performance & concurrency pragmas
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute("PRAGMA temp_store = MEMORY;")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        """Creates table and composite indexes if they do not exist."""
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_events (
                    id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    plugin_slug TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    model_tier TEXT NOT NULL,
                    prompt_tokens_est INTEGER NOT NULL,
                    completion_tokens_est INTEGER NOT NULL,
                    total_tokens_est INTEGER NOT NULL,
                    turn_duration_ms REAL NOT NULL,
                    tool_calls_count INTEGER NOT NULL,
                    messages_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_telemetry_plugin_ts ON telemetry_events(plugin_slug, timestamp);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_telemetry_agent_ts ON telemetry_events(agent_id, timestamp);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_telemetry_ts ON telemetry_events(timestamp);"
            )

    def record_event(self, event: TelemetryEvent) -> None:
        """Atomically inserts a new TelemetryEvent using BEGIN IMMEDIATE."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE;")
            cursor.execute(
                """
                INSERT OR REPLACE INTO telemetry_events (
                    id, timestamp, plugin_slug, agent_id, conversation_id,
                    model_tier, prompt_tokens_est, completion_tokens_est,
                    total_tokens_est, turn_duration_ms, tool_calls_count,
                    messages_count, status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    event.id,
                    event.timestamp,
                    event.plugin_slug,
                    event.agent_id,
                    event.conversation_id,
                    event.model_tier,
                    event.prompt_tokens_est,
                    event.completion_tokens_est,
                    event.total_tokens_est,
                    event.turn_duration_ms,
                    event.tool_calls_count,
                    event.messages_count,
                    event.status.value,
                    event.error_message,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def list_events(self, filters: Optional[UsageQueryFilter] = None, limit: int = 100) -> List[TelemetryEvent]:
        """Lists events matching optional filter parameters."""
        conn = self._get_connection()
        query = "SELECT * FROM telemetry_events WHERE 1=1"
        params: list[object] = []

        if filters:
            if filters.plugin_slug:
                query += " AND plugin_slug = ?"
                params.append(filters.plugin_slug)
            if filters.agent_id:
                query += " AND agent_id = ?"
                params.append(filters.agent_id)
            if filters.since_timestamp is not None:
                query += " AND timestamp >= ?"
                params.append(filters.since_timestamp)
            if filters.until_timestamp is not None:
                query += " AND timestamp <= ?"
                params.append(filters.until_timestamp)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        events: List[TelemetryEvent] = []
        for r in rows:
            events.append(
                TelemetryEvent(
                    id=r["id"],
                    timestamp=r["timestamp"],
                    plugin_slug=r["plugin_slug"],
                    agent_id=r["agent_id"],
                    conversation_id=r["conversation_id"],
                    model_tier=r["model_tier"],
                    prompt_tokens_est=r["prompt_tokens_est"],
                    completion_tokens_est=r["completion_tokens_est"],
                    total_tokens_est=r["total_tokens_est"],
                    turn_duration_ms=r["turn_duration_ms"],
                    tool_calls_count=r["tool_calls_count"],
                    messages_count=r["messages_count"],
                    status=TelemetryEventStatus(r["status"]),
                    error_message=r["error_message"],
                )
            )
        return events

    def get_plugin_quota_summary(
        self, plugin_slug: str, window_minutes: int = 60
    ) -> PluginQuotaSummary:
        """Calculates high-fidelity quota summary and per-agent metrics for a plugin."""
        conn = self._get_connection()
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        since = now - (window_minutes * 60)
        recent_window_5m = now - 300  # 5 minutes for rate calculation

        # Overall totals for the plugin
        totals_row = conn.execute(
            """
            SELECT 
                COUNT(*) as total_calls,
                COUNT(DISTINCT conversation_id) as total_turns,
                COALESCE(SUM(total_tokens_est), 0) as total_tokens,
                COALESCE(SUM(prompt_tokens_est), 0) as prompt_tokens,
                COALESCE(SUM(completion_tokens_est), 0) as completion_tokens,
                COALESCE(SUM(tool_calls_count), 0) as tool_calls
            FROM telemetry_events
            WHERE plugin_slug = ?;
            """,
            (plugin_slug,),
        ).fetchone()

        # Recent 5-minute rates
        rates_row = conn.execute(
            """
            SELECT 
                COALESCE(SUM(total_tokens_est), 0) as recent_tokens,
                COUNT(*) as recent_calls
            FROM telemetry_events
            WHERE plugin_slug = ? AND timestamp >= ?;
            """,
            (plugin_slug, recent_window_5m),
        ).fetchone()

        tokens_per_minute = round(rates_row["recent_tokens"] / 5.0, 2) if rates_row else 0.0
        calls_per_minute = round(rates_row["recent_calls"] / 5.0, 2) if rates_row else 0.0

        # Per-agent breakdown
        agent_rows = conn.execute(
            """
            SELECT 
                agent_id,
                COUNT(*) as calls_count,
                COUNT(DISTINCT conversation_id) as turns_count,
                COALESCE(SUM(total_tokens_est), 0) as tokens_sum,
                COALESCE(AVG(turn_duration_ms), 0.0) as avg_latency,
                COALESCE(SUM(tool_calls_count), 0) as tools_sum,
                MAX(timestamp) as last_seen
            FROM telemetry_events
            WHERE plugin_slug = ?
            GROUP BY agent_id;
            """,
            (plugin_slug,),
        ).fetchall()

        agent_summaries: List[AgentTelemetrySummary] = []
        for ar in agent_rows:
            # Agent recent 5-min rate
            ar_rate = conn.execute(
                """
                SELECT COALESCE(SUM(total_tokens_est), 0) as recent_tokens
                FROM telemetry_events
                WHERE plugin_slug = ? AND agent_id = ? AND timestamp >= ?;
                """,
                (plugin_slug, ar["agent_id"], recent_window_5m),
            ).fetchone()
            agent_tokens_per_min = round((ar_rate["recent_tokens"] or 0) / 5.0, 2)

            agent_summaries.append(
                AgentTelemetrySummary(
                    agent_id=ar["agent_id"],
                    plugin_slug=plugin_slug,
                    total_calls=ar["calls_count"],
                    total_turns=ar["turns_count"],
                    total_tokens_est=ar["tokens_sum"],
                    avg_latency_ms=round(ar["avg_latency"], 2),
                    tool_calls_count=ar["tools_sum"],
                    last_active_timestamp=ar["last_seen"],
                    tokens_per_min_recent=agent_tokens_per_min,
                )
            )

        # Granular recent metrics (by minute bucket)
        recent_metrics = self.get_granular_metrics(plugin_slug=plugin_slug, window_minutes=window_minutes)

        return PluginQuotaSummary(
            plugin_slug=plugin_slug,
            total_calls=totals_row["total_calls"] if totals_row else 0,
            total_turns=totals_row["total_turns"] if totals_row else 0,
            total_tokens_est=totals_row["total_tokens"] if totals_row else 0,
            prompt_tokens_est=totals_row["prompt_tokens"] if totals_row else 0,
            completion_tokens_est=totals_row["completion_tokens"] if totals_row else 0,
            tool_calls_count=totals_row["tool_calls"] if totals_row else 0,
            tokens_per_minute=tokens_per_minute,
            calls_per_minute=calls_per_minute,
            agents=agent_summaries,
            recent_metrics=recent_metrics,
        )

    def get_granular_metrics(
        self, plugin_slug: Optional[str] = None, window_minutes: int = 60
    ) -> List[GranularMetricRecord]:
        """Calculates 1-minute time-bucket series for charts and visualization."""
        conn = self._get_connection()
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        since = now - (window_minutes * 60)

        query = """
            SELECT 
                strftime('%Y-%m-%dT%H:%M:00', datetime(timestamp, 'unixepoch')) as minute_bucket,
                COALESCE(SUM(total_tokens_est), 0) as tokens_sum,
                COUNT(*) as calls_count,
                COALESCE(AVG(turn_duration_ms), 0.0) as avg_latency,
                COALESCE(SUM(tool_calls_count), 0) as tools_sum
            FROM telemetry_events
            WHERE timestamp >= ?
        """
        params: list[object] = [since]
        if plugin_slug:
            query += " AND plugin_slug = ?"
            params.append(plugin_slug)

        query += " GROUP BY minute_bucket ORDER BY minute_bucket ASC;"

        rows = conn.execute(query, params).fetchall()
        metrics: List[GranularMetricRecord] = []
        for r in rows:
            metrics.append(
                GranularMetricRecord(
                    timestamp_bucket=r["minute_bucket"],
                    tokens_per_minute=float(r["tokens_sum"]),
                    calls_per_minute=int(r["calls_count"]),
                    avg_latency_ms=round(float(r["avg_latency"]), 2),
                    tool_calls_count=int(r["tools_sum"]),
                )
            )
        return metrics

    def get_global_summary(self) -> GlobalTelemetrySummary:
        """Rolls up system-wide quota telemetry across all monitored plugins."""
        conn = self._get_connection()
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        recent_window_5m = now - 300

        plugins = conn.execute("SELECT DISTINCT plugin_slug FROM telemetry_events;").fetchall()
        plugin_slugs = [p["plugin_slug"] for p in plugins]

        totals = conn.execute(
            """
            SELECT 
                COUNT(*) as total_calls,
                COALESCE(SUM(total_tokens_est), 0) as total_tokens
            FROM telemetry_events;
            """
        ).fetchone()

        recent = conn.execute(
            """
            SELECT 
                COALESCE(SUM(total_tokens_est), 0) as recent_tokens,
                COUNT(*) as recent_calls
            FROM telemetry_events
            WHERE timestamp >= ?;
            """,
            (recent_window_5m,),
        ).fetchone()

        active_tokens_per_min = round((recent["recent_tokens"] or 0) / 5.0, 2) if recent else 0.0
        active_calls_per_min = round((recent["recent_calls"] or 0) / 5.0, 2) if recent else 0.0

        plugin_summaries = [self.get_plugin_quota_summary(slug) for slug in plugin_slugs]

        return GlobalTelemetrySummary(
            total_plugins_monitored=len(plugin_slugs),
            total_calls_all_time=totals["total_calls"] if totals else 0,
            total_tokens_all_time=totals["total_tokens"] if totals else 0,
            active_tokens_per_minute=active_tokens_per_min,
            active_calls_per_minute=active_calls_per_min,
            plugin_summaries=plugin_summaries,
        )
