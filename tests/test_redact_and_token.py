import base64
import json
from datetime import UTC, datetime

from fireant_crawler.client.redact import redact
from fireant_crawler.client.token_info import inspect_token
from fireant_crawler.config import load_settings


def _jwt(payload: dict) -> str:
    def enc(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(payload)}.signature"


def test_redact_removes_known_secret_and_bearer_values():
    secret = "abcdefghijklmnop"
    text = f"failed with token {secret}; header Authorization: Bearer xyz.123-abc"
    out = redact(text, [secret])
    assert secret not in out
    assert "xyz.123-abc" not in out
    assert "Bearer ***" in out


def test_redact_ignores_short_or_empty_secrets():
    assert redact("value abc", ["abc", None, ""]) == "value abc"


def test_inspect_token_reads_expiry_and_scopes():
    token = _jwt({"exp": 1_900_000_000, "scope": ["symbols-read", "orders-write"]})
    info = inspect_token(token)
    assert info.is_jwt
    assert info.expires_at == datetime.fromtimestamp(1_900_000_000, tz=UTC)
    assert info.scopes == ("orders-write", "symbols-read")
    assert not info.is_expired(datetime(2026, 10, 3, tzinfo=UTC))


def test_inspect_token_handles_space_separated_scope_and_garbage():
    assert inspect_token(_jwt({"scope": "a b"})).scopes == ("a", "b")
    assert not inspect_token("not-a-jwt").is_jwt
    assert not inspect_token("a.!!!.c").is_jwt


def test_settings_strip_bearer_prefix_and_defaults():
    settings = load_settings({"FIREANT_TOKEN": "  Bearer tok123456  "})
    assert settings.token == "tok123456"
    assert settings.rate_limit_rps == 2.5
    assert load_settings({}).token is None
