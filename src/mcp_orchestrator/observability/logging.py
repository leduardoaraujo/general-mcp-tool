from __future__ import annotations

import json
import logging
from typing import Any


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return logging.getLogger(name)


def log_stage(
    logger: logging.Logger,
    *,
    correlation_id: str,
    stage: str,
    status: str,
    duration_ms: float,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "correlation_id": correlation_id,
        "stage": stage,
        "status": status,
        "duration_ms": round(duration_ms, 3),
    }
    if extra:
        payload.update(extra)
    logger.info(json.dumps(payload, ensure_ascii=False))
