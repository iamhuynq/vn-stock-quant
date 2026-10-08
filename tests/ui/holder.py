"""Hold a DuckDB file open from another process (DuckDB locks are per process)."""

import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

CODE = """import duckdb, sys, time
con = duckdb.connect(sys.argv[1], read_only=sys.argv[2] == 'ro')
print('held', flush=True)
time.sleep(float(sys.argv[3]))
"""


@contextmanager
def held(path: Path, mode: str = "rw", seconds: float = 30.0):
    proc = subprocess.Popen([sys.executable, "-c", CODE, str(path), mode, str(seconds)], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "held"
        yield proc
    finally:
        proc.kill()
        proc.wait()
