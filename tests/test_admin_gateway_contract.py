from __future__ import annotations

import pytest

from src.admin_gateway.server import _group_id, _redact, _safe_int


def test_gateway_safe_integer_accepts_group_and_operator_ranges() -> None:
    assert _safe_int("123", field="operatorTelegramId") == 123
    assert _safe_int("-1001234567890", field="groupId", minimum=-(2**53 - 1)) == -1001234567890
    assert _group_id("-1001234567890") == -1001234567890


@pytest.mark.parametrize("raw", [None, "", "abc", "0", "99999999999999999"])
def test_gateway_safe_integer_rejects_invalid_values(raw: str | None) -> None:
    with pytest.raises(ValueError):
        _safe_int(raw, field="value")


def test_gateway_redacts_nested_sensitive_fields() -> None:
    payload = {
        "token": "secret",
        "nested": {"api_key": "hidden", "safe": "visible"},
        "items": [{"authorization": "Bearer hidden"}],
    }

    assert _redact(payload) == {
        "token": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]", "safe": "visible"},
        "items": [{"authorization": "[REDACTED]"}],
    }
