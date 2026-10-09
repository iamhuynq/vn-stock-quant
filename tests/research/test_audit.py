"""Point-in-time audit report: read-only, logs nothing, every section present, no future table in features."""

from datetime import UTC, datetime

from quant_research.audit import future_tables_in_features, render
from quant_research.build import build
from tests.research.synthetic import build_synthetic_warehouse

NOW = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)


def test_feature_sql_reads_no_report_fundamental_or_target_table():
    assert future_tables_in_features() == []


def test_audit_report_is_read_only_and_complete(tmp_path):
    build_synthetic_warehouse(tmp_path / "w.duckdb")
    build(tmp_path / "w.duckdb", tmp_path / "r.duckdb", NOW)
    before = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()}
    build_id, text = render(tmp_path / "w.duckdb", tmp_path / "r.duckdb")
    assert {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()} == before          # nothing written
    assert build_id == NOW.strftime("%Y%m%dT%H%M%S")
    for heading in ("## 1. Coverage", "## 2. Stocks that stopped trading", "## 3. Attributes known only",
                    "## 4. Corporate actions", "## 5. Data availability", "## 6. Valuation of stuck positions"):
        assert heading in text
    assert "none found." in text
    stopped = text.split("## 2. Stocks that stopped trading")[1].split("## 3.")[0]
    assert "| listed, silent | 1 |" in stopped               # synthetic DEL stops trading after session 200
