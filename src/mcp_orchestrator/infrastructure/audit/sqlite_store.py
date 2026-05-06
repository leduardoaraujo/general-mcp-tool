from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp_orchestrator.domain.models import (
    ExecutionPolicyDecision,
    NormalizedResponse,
    UserRequest,
)


class SqliteAuditStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def record_response(
        self,
        *,
        request: UserRequest,
        understanding: dict[str, Any],
        retrieved_context_sources: list[str],
        policy_decision: ExecutionPolicyDecision,
        plan: dict[str, Any],
        response: NormalizedResponse,
    ) -> None:
        payload = {
            "request": request.model_dump(mode="json"),
            "understanding": understanding,
            "retrieved_context_sources": retrieved_context_sources,
            "policy_decision": policy_decision.model_dump(mode="json"),
            "plan": plan,
            "response": response.model_dump(mode="json"),
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO audit_events (
                    correlation_id,
                    confirmation_id,
                    status,
                    created_at,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    response.correlation_id,
                    policy_decision.confirmation_id,
                    response.status.value,
                    self._now(),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            self._insert_execution_traces(
                connection=connection,
                request=request,
                response=response,
                confirmation_id=policy_decision.confirmation_id,
            )

    def create_confirmation(
        self,
        *,
        confirmation_id: str,
        request: UserRequest,
        policy_decision: ExecutionPolicyDecision,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO confirmations (
                    confirmation_id,
                    status,
                    request_json,
                    policy_json,
                    created_at,
                    executed_at
                )
                VALUES (?, 'pending', ?, ?, ?, NULL)
                """,
                (
                    confirmation_id,
                    json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
                    json.dumps(policy_decision.model_dump(mode="json"), ensure_ascii=False),
                    self._now(),
                ),
            )

    def get_audit_event(self, correlation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT correlation_id, confirmation_id, status, created_at, payload_json
                FROM audit_events
                WHERE correlation_id = ?
                """,
                (correlation_id,),
            ).fetchone()
            trace_rows = connection.execute(
                """
                SELECT *
                FROM execution_traces
                WHERE correlation_id = ?
                ORDER BY step_index ASC
                """,
                (correlation_id,),
            ).fetchall()
        if row is None:
            return None
        audit_row = self._audit_row(row)
        audit_row["execution_traces"] = [self._trace_row(item) for item in trace_rows]
        return audit_row

    def get_confirmation(self, confirmation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT confirmation_id, status, request_json, policy_json, created_at, executed_at
                FROM confirmations
                WHERE confirmation_id = ?
                """,
                (confirmation_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "confirmation_id": row["confirmation_id"],
            "status": row["status"],
            "request": json.loads(row["request_json"]),
            "policy_decision": json.loads(row["policy_json"]),
            "created_at": row["created_at"],
            "executed_at": row["executed_at"],
        }

    def mark_confirmation_executed(self, confirmation_id: str, correlation_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE confirmations
                SET status = 'executed',
                    executed_at = ?,
                    executed_correlation_id = ?
                WHERE confirmation_id = ?
                """,
                (self._now(), correlation_id, confirmation_id),
            )

    def is_pending_confirmation(self, confirmation_id: str) -> bool:
        confirmation = self.get_confirmation(confirmation_id)
        return bool(confirmation and confirmation["status"] == "pending")

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    correlation_id TEXT PRIMARY KEY,
                    confirmation_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS confirmations (
                    confirmation_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    executed_at TEXT,
                    executed_correlation_id TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_traces (
                    correlation_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    confirmation_id TEXT,
                    request_message TEXT,
                    domain TEXT,
                    created_at TEXT NOT NULL,
                    target_mcp TEXT,
                    tool_name TEXT,
                    operation TEXT,
                    status TEXT,
                    duration_ms REAL,
                    input_json TEXT,
                    validation_json TEXT,
                    calculation_json TEXT,
                    output_summary_json TEXT,
                    output_sample_json TEXT,
                    errors_json TEXT,
                    warnings_json TEXT,
                    PRIMARY KEY (correlation_id, step_index)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _audit_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "correlation_id": row["correlation_id"],
            "confirmation_id": row["confirmation_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "payload": json.loads(row["payload_json"]),
        }

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _insert_execution_traces(
        self,
        *,
        connection: sqlite3.Connection,
        request: UserRequest,
        response: NormalizedResponse,
        confirmation_id: str | None,
    ) -> None:
        steps = self._collect_execution_trace_steps(response)
        domain = request.domain_hint or (request.tags[0] if request.tags else None)
        for idx, step in enumerate(steps):
            connection.execute(
                """
                INSERT OR REPLACE INTO execution_traces (
                    correlation_id,
                    step_index,
                    confirmation_id,
                    request_message,
                    domain,
                    created_at,
                    target_mcp,
                    tool_name,
                    operation,
                    status,
                    duration_ms,
                    input_json,
                    validation_json,
                    calculation_json,
                    output_summary_json,
                    output_sample_json,
                    errors_json,
                    warnings_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    response.correlation_id,
                    idx,
                    confirmation_id,
                    request.message,
                    domain,
                    self._now(),
                    step.get("target_mcp"),
                    step.get("tool_name"),
                    step.get("operation"),
                    step.get("status"),
                    step.get("duration_ms"),
                    json.dumps(step.get("input"), ensure_ascii=False),
                    json.dumps(step.get("validation"), ensure_ascii=False),
                    json.dumps(step.get("calculation"), ensure_ascii=False),
                    json.dumps(step.get("output_summary"), ensure_ascii=False),
                    json.dumps(step.get("output_sample"), ensure_ascii=False),
                    json.dumps(step.get("errors"), ensure_ascii=False),
                    json.dumps(step.get("warnings"), ensure_ascii=False),
                ),
            )

    def _collect_execution_trace_steps(self, response: NormalizedResponse) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for specialist in response.specialist_results:
            debug = specialist.debug if isinstance(specialist.debug, dict) else {}
            raw_steps = debug.get("execution_trace")
            if isinstance(raw_steps, list):
                for item in raw_steps:
                    if isinstance(item, dict):
                        steps.append(item)
        return steps

    def _trace_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "correlation_id": row["correlation_id"],
            "step_index": row["step_index"],
            "confirmation_id": row["confirmation_id"],
            "request_message": row["request_message"],
            "domain": row["domain"],
            "created_at": row["created_at"],
            "target_mcp": row["target_mcp"],
            "tool_name": row["tool_name"],
            "operation": row["operation"],
            "status": row["status"],
            "duration_ms": row["duration_ms"],
            "input": json.loads(row["input_json"]) if row["input_json"] else None,
            "validation": json.loads(row["validation_json"]) if row["validation_json"] else None,
            "calculation": json.loads(row["calculation_json"]) if row["calculation_json"] else None,
            "output_summary": json.loads(row["output_summary_json"]) if row["output_summary_json"] else None,
            "output_sample": json.loads(row["output_sample_json"]) if row["output_sample_json"] else None,
            "errors": json.loads(row["errors_json"]) if row["errors_json"] else [],
            "warnings": json.loads(row["warnings_json"]) if row["warnings_json"] else [],
        }
