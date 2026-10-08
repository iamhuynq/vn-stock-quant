"""The only requests the crawler may send: GET on read-only market-data paths.

Anything else (orders, accounts, me, admin, posts, any write) is unreachable by construction.
"""

import re

_SEGMENT = r"[A-Za-z0-9-]{1,30}"

ALLOWED_PATH_PATTERNS: tuple[str, ...] = (
    r"/instruments",
    r"/symbols/search",
    rf"/symbols/{_SEGMENT}",
    rf"/symbols/{_SEGMENT}/historical-quotes",
    rf"/symbols/{_SEGMENT}/timescale-marks",
    rf"/symbols/{_SEGMENT}/fundamental",
    rf"/symbols/{_SEGMENT}/dividends",
    rf"/symbols/{_SEGMENT}/profile",
    r"/events/search",
    r"/icb",
    rf"/icb/{_SEGMENT}/symbols",
)

_COMPILED = tuple(re.compile(p) for p in ALLOWED_PATH_PATTERNS)


def is_allowed(method: str, path: str) -> bool:
    if method.upper() != "GET":
        return False
    if not path.startswith("/") or any(c in path for c in "?#%\\") or ".." in path:
        return False
    return any(p.fullmatch(path) for p in _COMPILED)
