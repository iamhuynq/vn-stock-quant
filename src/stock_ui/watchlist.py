"""The user's watchlist for the Market watch page: a small JSON file, data/ui/watchlist.json.

Not a database: the UI's read-only rule for DuckDB files is unaffected. Written atomically.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

SYMBOL = re.compile(r"^[A-Z0-9]{2,10}$")
MAX_SYMBOLS = 60


def path(data_dir: Path) -> Path:
    return data_dir / "ui" / "watchlist.json"


def parse(text: str, known: set[str] | None = None) -> tuple[list[str], list[str]]:
    """(valid symbols in input order without duplicates, rejected tokens). Separators: comma, space, newline."""
    valid, rejected = [], []
    for token in re.split(r"[\s,;]+", text.upper()):
        if not token:
            continue
        if SYMBOL.match(token) and (known is None or token in known):
            if token not in valid:
                valid.append(token)
        else:
            rejected.append(token)
    return valid[:MAX_SYMBOLS], rejected


def load(data_dir: Path) -> list[str]:
    try:
        data = json.loads(path(data_dir).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    return [s for s in data.get("symbols", []) if isinstance(s, str) and SYMBOL.match(s)][:MAX_SYMBOLS]


def save(data_dir: Path, symbols: list[str], now: datetime) -> None:
    target = path(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({"symbols": symbols[:MAX_SYMBOLS], "updated_at": now.isoformat(timespec="seconds")},
                              indent=1), encoding="utf-8")
    os.replace(tmp, target)
