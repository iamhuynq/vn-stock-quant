"""Task runner: fetch -> raw store -> ingest -> checkpoint, one task at a time.

Each task commits its warehouse rows and its crawl_state row in one transaction, so an
interrupted run resumes cleanly. 401/403 stops the whole run; other failures are recorded
and the run continues.
"""

import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from fireant_crawler.client.fireant_client import ApiError, AuthError, FireAntClient
from fireant_crawler.jobs.ingest import ingest
from fireant_crawler.normalize.values import NormalizationError
from fireant_crawler.store.raw_store import RawStore
from fireant_crawler.store.state import CrawlState
from fireant_crawler.store.warehouse import Warehouse


@dataclass
class JobContext:
    client: FireAntClient
    raw: RawStore
    warehouse: Warehouse
    state: CrawlState
    run_at: datetime          # one timestamp per run: snapshot keys and raw file names
    today: date               # last final session (fireant_crawler.sessions.final_session): fetch up to it
    log: Callable[[str], None] = print

    def fetch(self, job: str, key: str, chunk: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET, store raw, log, and return the envelope (same shape as a raw file)."""
        try:
            response = self.client.get(path, params)
        except ApiError as exc:
            self._log_request(job, path, exc.status, None, None, str(exc))
            raise
        self.raw.write(job, key, chunk, response, self.run_at)
        self._log_request(job, path, response.status, response.elapsed_seconds, response.attempts, None)
        return {
            "fetched_at": self.run_at.isoformat(),
            "request": {"path": response.path, "params": response.params},
            "status": response.status,
            "data": response.data,
        }

    def fetch_and_ingest(self, job: str, key: str, chunk: str, path: str,
                         params: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
        envelope = self.fetch(job, key, chunk, path, params)
        return envelope, ingest(self.warehouse, job, key, envelope)

    def _log_request(self, job: str, path: str, status: int | None, elapsed: float | None,
                     attempts: int | None, error: str | None) -> None:
        self.warehouse.connection.execute(
            "INSERT INTO crawl_log (logged_at, job, path, status, elapsed_seconds, attempts, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [datetime.now(self.run_at.tzinfo), job, path, status, elapsed, attempts, error],
        )


class NetworkDownError(RuntimeError):
    """Too many consecutive tasks gave up after retries: the network or the API is down. Stop and retry later."""


CIRCUIT_BREAKER_FAILURES = 10


@dataclass(frozen=True)
class Task:
    job: str
    key: str
    chunk: str
    run: Callable[[JobContext], int]   # returns rows written; may return -1 for "skipped"


@dataclass
class RunStats:
    counts: Counter = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{k}={v}" for k, v in sorted(self.counts.items())]
        return ", ".join(parts) or "nothing to do"


def run_tasks(ctx: JobContext, tasks: list[Task], force: bool = False, progress_every: int = 50,
              breaker: int = CIRCUIT_BREAKER_FAILURES) -> RunStats:
    stats = RunStats()
    consecutive_gave_up = 0
    for index, task in enumerate(tasks, start=1):
        if not force and ctx.state.status(task.job, task.key, task.chunk) == "done":
            stats.counts["already_done"] += 1
            continue
        try:
            with ctx.warehouse.transaction():
                written = task.run(ctx)
                status = "skipped" if written < 0 else "done"
                ctx.state.mark(task.job, task.key, task.chunk, status, ctx.run_at)
            stats.counts[status] += 1
            stats.counts["rows"] += max(written, 0)
            consecutive_gave_up = 0
        except AuthError:
            ctx.log(f"Stopped at {task.job}/{task.key}/{task.chunk}: token expired or missing scope. Re-run to resume.")
            raise
        except (ApiError, NormalizationError) as exc:
            message = f"{task.job}/{task.key}/{task.chunk}: {exc}"
            stats.errors.append(message)
            stats.counts["failed"] += 1
            ctx.state.mark(task.job, task.key, task.chunk, "failed", ctx.run_at, error=str(exc))
            print(f"FAILED {message}", file=sys.stderr)
            # status None = retries exhausted on network errors or 5xx (not a per-symbol 4xx)
            consecutive_gave_up = consecutive_gave_up + 1 if isinstance(exc, ApiError) and exc.status is None else 0
            if consecutive_gave_up >= breaker:
                raise NetworkDownError(f"{breaker} consecutive tasks failed after retries (last: {message})")
        if index % progress_every == 0 or index == len(tasks):
            ctx.log(f"  [{tasks[0].job}] {index}/{len(tasks)} ({stats.summary()})")
    return stats
