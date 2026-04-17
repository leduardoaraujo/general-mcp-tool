import base64
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

MAX_MARKDOWN_CELL_LENGTH = 120


def serialize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, tuple):
        return [serialize_value(item) for item in value]
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): serialize_value(item) for key, item in value.items()}
    return value


def records_to_dict(records: list) -> list[dict[str, Any]]:
    return [
        {key: serialize_value(value) for key, value in dict(record).items()}
        for record in records
    ]


def _stringify_markdown_value(value: Any) -> str:
    serialized = serialize_value(value)
    if serialized is None:
        return ""
    if isinstance(serialized, (dict, list)):
        text = json.dumps(serialized, ensure_ascii=False)
    else:
        text = str(serialized)

    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    text = text.replace("|", "\\|")
    if len(text) > MAX_MARKDOWN_CELL_LENGTH:
        text = f"{text[: MAX_MARKDOWN_CELL_LENGTH - 3]}..."
    return text


def format_as_markdown_table(records: list[dict[str, Any]]) -> str:
    if not records:
        return "No records found."

    headers = list(records[0].keys())
    header_row = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join(["---"] * len(headers)) + " |"
    rows = [
        "| " + " | ".join(_stringify_markdown_value(record.get(header)) for header in headers) + " |"
        for record in records
    ]
    return "\n".join([header_row, separator] + rows)


def format_as_json(value: Any) -> str:
    return json.dumps(serialize_value(value), indent=2, ensure_ascii=False)
