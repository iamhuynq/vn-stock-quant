"""Immutable raw response store: data/raw/{job}/{key}/{fetch_date}/{chunk}__{HHMMSS}.json.gz

The run time in the file name keeps same-day re-runs from overwriting earlier responses.
"""

import gzip
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fireant_crawler.client.fireant_client import ApiResponse

_SAFE_NAME = re.compile(r"[A-Za-z0-9_.=-]{1,120}")


def _check_name(kind: str, value: str) -> str:
    if not _SAFE_NAME.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"Unsafe {kind} for raw store path: {value!r}")
    return value


class RawStore:
    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir / "raw"

    def write(self, job: str, key: str, chunk: str, response: ApiResponse, fetched_at: datetime) -> Path:
        directory = (
            self._root
            / _check_name("job", job)
            / _check_name("key", key)
            / fetched_at.date().isoformat()
        )
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{_check_name('chunk', chunk)}__{fetched_at:%H%M%S}.json.gz"

        envelope = {
            "fetched_at": fetched_at.isoformat(),
            "request": {"path": response.path, "params": response.params},
            "status": response.status,
            "data": response.data,
        }
        tmp = target.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(envelope, fh, ensure_ascii=False)
        os.replace(tmp, target)
        return target

    def iter_files(self, job: str) -> list[tuple[str, Path]]:
        """(key, path) for every raw file of a job, oldest fetch first."""
        base = self._root / _check_name("job", job)
        if not base.is_dir():
            return []
        files = [(p.parts[-3], p) for p in base.glob("*/*/*.json.gz")]
        return sorted(files, key=lambda kp: (kp[1].parts[-2], kp[1].name.rsplit("__", 1)[-1], kp[1].name))

    @staticmethod
    def read(path: Path) -> dict[str, Any]:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
