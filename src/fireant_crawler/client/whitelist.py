"""The only requests the crawler may send: GET on read-only market-data paths.

Anything else (orders, accounts, me, admin, posts, any write) is unreachable by construction.
"""

import re

# Ticker: upper-case letters and digits, with at most one upper-case suffix (HNX-INDEX). Lower-case words are
# endpoint names, never tickers: the old pattern [A-Za-z0-9-] also matched paths such as
# /symbols/all-financial-data, which is not market data the crawler is meant to read.
_SYMBOL = r"[A-Z0-9]{1,20}(?:-[A-Z0-9]{1,10})?"
_ICB_CODE = r"[0-9]{1,10}"

ALLOWED_PATH_PATTERNS: tuple[str, ...] = (
    r"/instruments",
    r"/symbols/search",
    rf"/symbols/{_SYMBOL}",
    rf"/symbols/{_SYMBOL}/historical-quotes",
    rf"/symbols/{_SYMBOL}/timescale-marks",
    rf"/symbols/{_SYMBOL}/fundamental",
    rf"/symbols/{_SYMBOL}/dividends",
    rf"/symbols/{_SYMBOL}/profile",
    r"/events/search",
    r"/icb",
    rf"/icb/{_ICB_CODE}/symbols",
)

_COMPILED = tuple(re.compile(p) for p in ALLOWED_PATH_PATTERNS)


def is_allowed(method: str, path: str) -> bool:
    if method.upper() != "GET":
        return False
    if not path.startswith("/") or any(c in path for c in "?#%\\") or ".." in path:
        return False
    return any(p.fullmatch(path) for p in _COMPILED)
