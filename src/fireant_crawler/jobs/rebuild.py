"""`fireant normalize`: replay every raw file into the warehouse, oldest first, without API calls."""

from collections import Counter
from collections.abc import Callable

from fireant_crawler.jobs.ingest import INGESTED_JOBS, ingest
from fireant_crawler.normalize.values import NormalizationError
from fireant_crawler.store.raw_store import RawStore
from fireant_crawler.store.warehouse import Warehouse

# Corporate actions and universe first: later views (symbols_latest) depend on them.
REPLAY_ORDER = ("corporate_actions", "universe", "icb", "quotes", "report_marks", "fundamental")
assert set(REPLAY_ORDER) == set(INGESTED_JOBS)


def rebuild(raw: RawStore, warehouse: Warehouse | None, log: Callable[[str], None] = print) -> Counter:
    """With warehouse=None this is a dry run: count files per job and validate nothing is written."""
    counts: Counter = Counter()
    for job in REPLAY_ORDER:
        files = raw.iter_files(job)
        counts[f"{job}.files"] = len(files)
        if warehouse is None:
            continue
        for key, path in files:
            envelope = raw.read(path)
            try:
                with warehouse.transaction():
                    counts[f"{job}.rows"] += ingest(warehouse, job, key, envelope)
            except NormalizationError as exc:
                counts[f"{job}.failed"] += 1
                log(f"FAILED {path}: {exc}")
        log(f"  {job}: {len(files)} files")
    return counts
