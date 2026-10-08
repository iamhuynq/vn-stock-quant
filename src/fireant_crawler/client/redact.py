"""Strip credentials from any text before it is logged, raised or written."""

import re
from collections.abc import Iterable

_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_MIN_SECRET_LENGTH = 8


def redact(text: str, secrets: Iterable[str | None] = ()) -> str:
    for secret in secrets:
        if secret and len(secret) >= _MIN_SECRET_LENGTH:
            text = text.replace(secret, "***")
    return _BEARER.sub(r"\1***", text)
