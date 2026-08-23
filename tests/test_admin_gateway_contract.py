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


def test_redact_hides_compound_credential_keys() -> None:
    payload = _redact(
        {
            "accessToken": "token-value",
            "client_secret": "secret-value",
            "webhook-key": "key-value",
            "database_dsn": "postgres://user:password@db/app",
            "risk_score": 0.91,
            "nested": {"apiKey": "api-key-value", "category": "spam"},
        }
    )

    assert payload == {
        "accessToken": "[REDACTED]",
        "client_secret": "[REDACTED]",
        "webhook-key": "[REDACTED]",
        "database_dsn": "[REDACTED]",
        "risk_score": 0.91,
        "nested": {"apiKey": "[REDACTED]", "category": "spam"},
    }


def test_redact_preserves_non_sensitive_key_containing_safe_words() -> None:
    assert _redact({"tokenizer": "wordpiece", "secretary_name": "Ada"}) == {
        "tokenizer": "wordpiece",
        "secretary_name": "Ada",
    }


def test_redact_handles_non_string_mapping_keys() -> None:
    assert _redact({1: {"token": "hidden"}}) == {"1": {"token": "[REDACTED]"}}


def test_redact_recurses_through_lists() -> None:
    assert _redact([{"authorization_header": "Bearer hidden"}, {"status": "ok"}]) == [
        {"authorization_header": "[REDACTED]"},
        {"status": "ok"},
    ]
