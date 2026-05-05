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
        if row is None:
            return None
        return self._audit_row(row)

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
