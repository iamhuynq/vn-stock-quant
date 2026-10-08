"""Decode a JWT payload locally to show expiry and scopes. The token itself is never returned."""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class TokenInfo:
    is_jwt: bool
    expires_at: datetime | None
    scopes: tuple[str, ...]

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at


def inspect_token(token: str) -> TokenInfo:
    parts = token.split(".")
    if len(parts) != 3:
        return TokenInfo(is_jwt=False, expires_at=None, scopes=())
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, ValueError):
        return TokenInfo(is_jwt=False, expires_at=None, scopes=())
    if not isinstance(payload, dict):
        return TokenInfo(is_jwt=False, expires_at=None, scopes=())

    exp = payload.get("exp")
    expires_at = datetime.fromtimestamp(exp, tz=UTC) if isinstance(exp, (int, float)) else None
    raw_scopes = payload.get("scope", ())
    if isinstance(raw_scopes, str):
        raw_scopes = raw_scopes.split()
    scopes = tuple(sorted(str(s) for s in raw_scopes)) if isinstance(raw_scopes, (list, tuple)) else ()
    return TokenInfo(is_jwt=True, expires_at=expires_at, scopes=scopes)
