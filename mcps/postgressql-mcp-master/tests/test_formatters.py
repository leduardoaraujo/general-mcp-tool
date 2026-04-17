from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from core.formatters import format_as_json, format_as_markdown_table, serialize_value


def test_markdown_formatter_escapes_pipes_breaks_and_truncates():
    table = format_as_markdown_table(
        [
            {
                "name": "alpha|beta",
                "notes": "line1\nline2",
                "long": "x" * 200,
            }
        ]
    )

    assert "\\|" in table
    assert "<br>" in table
    assert "..." in table


def test_json_formatter_serializes_common_postgres_types():
    payload = {
        "timestamp": datetime(2024, 1, 2, 3, 4, 5),
        "date": date(2024, 1, 2),
        "time": time(3, 4, 5),
        "amount": Decimal("10.50"),
        "uuid": UUID("12345678-1234-5678-1234-567812345678"),
        "bytes": b"abc",
        "none": None,
    }

    rendered = format_as_json(payload)

    assert "2024-01-02T03:04:05" in rendered
    assert "10.50" in rendered
    assert "12345678-1234-5678-1234-567812345678" in rendered
    assert '"YWJj"' in rendered
    assert '"none": null' in rendered


def test_serialize_value_recurses_lists_and_dicts():
    value = serialize_value({"items": [Decimal("1.25"), {"nested": b"xy"}]})

    assert value == {"items": ["1.25", {"nested": "eHk="}]}
