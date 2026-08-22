from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.settings import Settings
from src.management.group_settings import validate_setting


def test_admin_gateway_is_disabled_by_default() -> None:
    settings = Settings()

    assert settings.admin_gateway_enabled is False
    assert settings.admin_gateway_token == ""


def test_enabled_admin_gateway_requires_strong_token() -> None:
    with pytest.raises(ValidationError, match="ADMIN_GATEWAY_TOKEN"):
        Settings(admin_gateway_enabled=True, admin_gateway_token="too-short")


def test_enabled_admin_gateway_accepts_local_bind_and_token() -> None:
    settings = Settings(
        admin_gateway_enabled=True,
        admin_gateway_host="127.0.0.1",
        admin_gateway_token="A" * 32,
    )

    assert settings.admin_gateway_enabled is True


def test_gateway_does_not_accept_nonlocal_bind_address() -> None:
    with pytest.raises(ValidationError, match="ADMIN_GATEWAY_HOST"):
        Settings(
            admin_gateway_enabled=True,
            admin_gateway_host="admin.example.test",
            admin_gateway_token="A" * 32,
        )


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("warn_limit", "7", "7"),
        ("max_links", "12", "12"),
        ("smart_responses", "on", "on"),
        ("rules_text", "لا روابط مختصرة بلا سياق", "لا روابط مختصرة بلا سياق"),
    ],
)
def test_canonical_gateway_setting_validation(field: str, value: str, expected: str) -> None:
    assert validate_setting(field, value) == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unknown", "on"),
        ("warn_limit", "11"),
        ("max_mentions", "51"),
        ("smart_responses", "maybe"),
    ],
)
def test_canonical_gateway_setting_validation_rejects_invalid_values(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        validate_setting(field, value)
