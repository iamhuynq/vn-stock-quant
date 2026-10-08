"""Read-only Reader: caching, stale fallback while a writer holds the file, pipeline lock; writer retry."""

import os

import duckdb
import pytest

from fireant_crawler.store.locking import connect_with_retry
from stock_ui.db import Reader
from tests.ui.holder import held


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t AS SELECT 1 AS a")
    con.close()
    clock = Clock()
    return Reader(tmp_path, ttl=60, clock=clock), clock, path


def test_cached_while_unchanged_reread_when_file_changes_or_ttl_expires(setup):
    reader, clock, path = setup
    calls = []

    def fn(con):
        calls.append(1)
        return con.execute("SELECT a FROM t").fetchall()
    assert reader.read("warehouse", "k", fn).value == [(1,)]
    assert reader.read("warehouse", "k", fn).value == [(1,)] and len(calls) == 1      # cached, file unchanged
    con = duckdb.connect(str(path))
    con.execute("UPDATE t SET a = 2")
    con.close()
    assert reader.read("warehouse", "k", fn).value == [(2,)] and len(calls) == 2      # writer committed
    clock.t += 61
    reader.read("warehouse", "k", fn)
    assert len(calls) == 3                                                             # TTL expired


def test_stale_pipeline_lock_does_not_block_reads(setup, tmp_path):
    reader, _clock, _path = setup
    lock = tmp_path / ".daily.lock"
    lock.mkdir()
    (lock / "pid").write_text("999999")                                                # dead process
    res = reader.query("warehouse", "SELECT a FROM t")
    assert not res.stale and res.value["a"].tolist() == [1]


def test_writer_in_another_process_gives_last_good_value_marked_stale(setup):
    reader, clock, path = setup
    reader.query("warehouse", "SELECT a FROM t")
    clock.t += 61
    with held(path, "rw"):
        res = reader.query("warehouse", "SELECT a FROM t")
        never_read = reader.query("warehouse", "SELECT a + 1 FROM t")
    assert res.stale and res.value["a"].tolist() == [1] and "being updated" in res.note
    assert never_read.stale and never_read.value is None


def test_pipeline_lock_skips_the_read(setup, tmp_path):
    reader, _clock, _path = setup
    (tmp_path / ".daily.lock").mkdir()
    (tmp_path / ".daily.lock" / "pid").write_text(str(os.getpid()))                    # live process
    res = reader.query("warehouse", "SELECT a FROM t")
    assert res.stale and res.value is None and "pipeline is running" in res.note


def test_missing_file_is_reported_not_raised(tmp_path):
    res = Reader(tmp_path).query("research", "SELECT 1")
    assert res.value is None and not res.stale and "not found" in res.note


def test_reader_never_writes(setup):
    reader, _clock, path = setup
    before = path.stat().st_mtime_ns
    with pytest.raises(duckdb.Error):
        reader.read("warehouse", "w", lambda con: con.execute("CREATE TABLE x (a INT)"))
    assert path.stat().st_mtime_ns == before


def test_writer_waits_for_a_short_reader_in_another_process(setup):
    _reader, _clock, path = setup
    with held(path, "ro", seconds=1.0):
        con = connect_with_retry(path, wait_seconds=15)
    con.execute("INSERT INTO t VALUES (3)")
    con.close()


def test_writer_gives_up_after_the_wait(setup):
    _reader, _clock, path = setup
    with held(path, "ro"), pytest.raises(duckdb.IOException):
        connect_with_retry(path, wait_seconds=0.5)
