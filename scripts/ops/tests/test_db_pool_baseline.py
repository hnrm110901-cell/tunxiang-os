"""scripts/ops/db_pool_baseline.py 单元测试 (helper-only, 不连真 PG).

per memory feedback_helper_only_test_for_import_blocked_module — parse / render /
threshold 拆为 pure function, 主 main() 通过 monkeypatch _fetch_baseline 测.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# 把仓库根加到 sys.path, 让 scripts.ops 包可 import
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ops.db_pool_baseline import (  # noqa: E402
    BaselineReport,
    ConnRow,
    build_parser,
    build_report,
    parse_pg_stat_rows,
    render_markdown,
)


def test_argparse_defaults() -> None:
    """argparse 默认值: service=all / output=markdown / warn=60 / error=80."""
    parser = build_parser()
    args = parser.parse_args([])
    assert args.service == "all"
    assert args.output == "markdown"
    assert args.report_path == "-"
    assert args.threshold_warn == 60.0
    assert args.threshold_error == 80.0


def test_parse_pg_stat_rows_groups_by_application_name() -> None:
    """parse_pg_stat_rows: 多 row 输入 → ConnRow 结构, None 字段 → '<unknown>'."""
    raw = [
        {"state": "active", "application_name": "tx-supply", "backend_type": "client backend", "conn_count": 12},
        {"state": "idle", "application_name": None, "backend_type": "client backend", "conn_count": 5},
        {"state": None, "application_name": "tx-agent", "backend_type": None, "conn_count": 0},
    ]
    parsed = parse_pg_stat_rows(raw)
    assert len(parsed) == 3
    assert parsed[0] == ConnRow("active", "tx-supply", "client backend", 12)
    assert parsed[1].application_name == "<unknown>"
    assert parsed[2].state == "<unknown>"
    assert parsed[2].backend_type == "<unknown>"
    assert parsed[2].conn_count == 0


def test_threshold_below_warn_exits_zero() -> None:
    """usage_pct < threshold_warn → severity=healthy, exit_code=0."""
    report = build_report(
        raw_rows=[
            {"state": "active", "application_name": "tx-supply", "backend_type": "client backend", "conn_count": 50},
        ],
        max_connections=200,  # 50/200 = 25%
        service="tx-supply",
        threshold_warn=60.0,
        threshold_error=80.0,
    )
    assert report.usage_pct == 25.0
    assert report.severity == "healthy"
    assert report.exit_code == 0


def test_threshold_warn_exits_one() -> None:
    """60% <= usage_pct < 80% → severity=warn, exit_code=1."""
    report = build_report(
        raw_rows=[
            {"state": "active", "application_name": "tx-supply", "backend_type": "client backend", "conn_count": 70},
            {"state": "idle", "application_name": "tx-analytics", "backend_type": "client backend", "conn_count": 70},
        ],
        max_connections=200,  # 140/200 = 70%
        service="all",
        threshold_warn=60.0,
        threshold_error=80.0,
    )
    assert report.usage_pct == 70.0
    assert report.severity == "warn"
    assert report.exit_code == 1


def test_threshold_error_exits_two() -> None:
    """usage_pct >= threshold_error → severity=error, exit_code=2."""
    report = build_report(
        raw_rows=[
            {"state": "active", "application_name": "tx-supply", "backend_type": "client backend", "conn_count": 180},
        ],
        max_connections=200,  # 180/200 = 90%
        service="tx-supply",
        threshold_warn=60.0,
        threshold_error=80.0,
    )
    assert report.usage_pct == 90.0
    assert report.severity == "error"
    assert report.exit_code == 2


def test_markdown_render_includes_table_header() -> None:
    """markdown 输出含 'state | application_name' 表头 + 数值行."""
    report = BaselineReport(
        service="tx-supply",
        rows=[ConnRow("active", "tx-supply", "client backend", 12)],
        max_connections=200,
        total_connections=12,
        threshold_warn_pct=60.0,
        threshold_error_pct=80.0,
    )
    md = render_markdown(report)
    assert "# DB Pool Baseline" in md
    assert "service=tx-supply" in md
    assert "| state | application_name | backend_type | conn_count |" in md
    assert "| active | tx-supply | client backend | 12 |" in md
    assert "max_connections: **200**" in md
    assert "usage: **6.0%**" in md
    assert "severity: **healthy**" in md


def test_zero_max_connections_does_not_crash() -> None:
    """max_connections=0 (DSN 错配) → usage_pct=0.0, 不 ZeroDivisionError."""
    report = build_report(
        raw_rows=[],
        max_connections=0,
        service="all",
        threshold_warn=60.0,
        threshold_error=80.0,
    )
    assert report.usage_pct == 0.0
    assert report.severity == "healthy"
    assert report.exit_code == 0
