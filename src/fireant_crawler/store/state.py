"""crawl_state checkpoints: one row per (job, key, chunk) task."""

from datetime import datetime
from typing import Literal

from fireant_crawler.store.warehouse import Warehouse

Status = Literal["done", "failed", "skipped"]


class CrawlState:
    def __init__(self, warehouse: Warehouse) -> None:
        self._wh = warehouse

    def status(self, job: str, key: str, chunk: str) -> str | None:
        row = self._wh.connection.execute(
            "SELECT status FROM crawl_state WHERE job = ? AND key = ? AND chunk = ?", [job, key, chunk]
        ).fetchone()
        return row[0] if row else None

    def attempts(self, job: str, key: str, chunk: str) -> int:
        row = self._wh.connection.execute(
            "SELECT attempts FROM crawl_state WHERE job = ? AND key = ? AND chunk = ?", [job, key, chunk]
        ).fetchone()
        return row[0] if row else 0

    def mark(self, job: str, key: str, chunk: str, status: Status, now: datetime, error: str | None = None) -> None:
        self._wh.upsert("crawl_state", [{
            "job": job,
            "key": key,
            "chunk": chunk,
            "status": status,
            "attempts": self.attempts(job, key, chunk) + 1,
            "last_error": error[:500] if error else None,
            "updated_at": now,
        }])

    def summary(self) -> list[tuple[str, str, int]]:
        return self._wh.connection.execute(
            "SELECT job, status, count(*) FROM crawl_state GROUP BY 1, 2 ORDER BY 1, 2"
        ).fetchall()
