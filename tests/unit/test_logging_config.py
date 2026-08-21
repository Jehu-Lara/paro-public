"""JsonFormatter: valid, parseable JSON with the expected keys. Not
testing configure_logging() itself -- it
mutates the root logger's handlers process-wide, which would leak
between tests; the formatter is the actual unit under test.
"""

import json
import logging

from paro.logging_config import JsonFormatter


def _make_record(**kwargs: object) -> logging.LogRecord:
    defaults: dict[str, object] = {
        "name": "paro.test",
        "level": logging.INFO,
        "pathname": __file__,
        "lineno": 1,
        "msg": "request",
        "args": (),
        "exc_info": None,
    }
    defaults.update(kwargs)
    return logging.LogRecord(**defaults)  # type: ignore[arg-type]


def test_format_produces_valid_json_with_expected_keys() -> None:
    record = _make_record()

    parsed = json.loads(JsonFormatter().format(record))

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "paro.test"
    assert parsed["message"] == "request"
    assert "timestamp" in parsed
    assert "exception" not in parsed


def test_format_includes_extra_fields() -> None:
    record = _make_record()
    record.method = "POST"
    record.status_code = 201
    record.duration_ms = 12.34

    parsed = json.loads(JsonFormatter().format(record))

    assert parsed["method"] == "POST"
    assert parsed["status_code"] == 201
    assert parsed["duration_ms"] == 12.34
