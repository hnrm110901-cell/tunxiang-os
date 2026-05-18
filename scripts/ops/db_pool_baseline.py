#!/usr/bin/env python3
"""DB pool baseline 测量脚本 (#737 Phase A) — pg_stat_activity → JSON/Markdown 报表.

用法:
    python scripts/ops/db_pool_baseline.py \\
        --service all \\
        --output markdown \\
        --report-path - \\
        --threshold-warn 60 \\
        --threshold-error 80

退出码 (用 CI 真门禁 / cron alert 用):
    0 — 当前连接数 < threshold-warn% (健康)
    1 — threshold-warn% <= 当前 < threshold-error% (预警)
    2 — 当前 >= threshold-error% (危险, 应立即扩 pool 或 scale-down)
    3 — DB 连接失败 / 解析异常 (infra 故障)

读 env:
    DATABASE_URL  — asyncpg DSN, 必填 (postgresql://user:pass@host:port/db)

参考:
    - feedback_planner_verified_claims_must_regrep.md (起手前 grep ground truth)
    - feedback_helper_only_test_for_import_blocked_module.md (parse/render 抽 pure function)
    - #737 Phase 0 baseline methodology (decision matrix 60%/80% 阈值)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Sequence


# ─── 数据结构 ────────────────────────────────────────────────────────────────


@dataclass
class ConnRow:
    """pg_stat_activity 一行聚合 (按 state/application_name/backend_type 分组)."""

    state: str
    application_name: str
    backend_type: str
    conn_count: int


@dataclass
class BaselineReport:
    """单 service / all service 的 baseline 报表."""

    service: str
    rows: list[ConnRow] = field(default_factory=list)
    max_connections: int = 0
    total_connections: int = 0
    threshold_warn_pct: float = 60.0
    threshold_error_pct: float = 80.0

    @property
    def usage_pct(self) -> float:
        if self.max_connections == 0:
            return 0.0
        return round(100.0 * self.total_connections / self.max_connections, 2)

    @property
    def severity(self) -> str:
        """healthy | warn | error."""
        pct = self.usage_pct
        if pct >= self.threshold_error_pct:
            return "error"
        if pct >= self.threshold_warn_pct:
            return "warn"
        return "healthy"

    @property
    def exit_code(self) -> int:
        sev = self.severity
        if sev == "error":
            return 2
        if sev == "warn":
            return 1
        return 0


# ─── pure helper (可独立测试) ───────────────────────────────────────────────


def parse_pg_stat_rows(raw_rows: Sequence[dict[str, Any]]) -> list[ConnRow]:
    """asyncpg fetch 返回的 Record-like dict 列表 → ConnRow.

    每 row 期望含 state / application_name / backend_type / conn_count 4 keys.
    None / 空字段标准化为 '<unknown>' 避免渲染时 KeyError.
    """
    parsed: list[ConnRow] = []
    for row in raw_rows:
        parsed.append(
            ConnRow(
                state=str(row.get("state") or "<unknown>"),
                application_name=str(row.get("application_name") or "<unknown>"),
                backend_type=str(row.get("backend_type") or "<unknown>"),
                conn_count=int(row.get("conn_count") or 0),
            )
        )
    return parsed


def render_markdown(report: BaselineReport) -> str:
    """渲染 markdown 报表 (含表头, 用于 PR 评论 / Slack)."""
    lines = [
        f"# DB Pool Baseline — service={report.service}",
        "",
        f"- max_connections: **{report.max_connections}**",
        f"- total_connections: **{report.total_connections}**",
        f"- usage: **{report.usage_pct}%** (severity: **{report.severity}**)",
        f"- threshold: warn={report.threshold_warn_pct}% / error={report.threshold_error_pct}%",
        "",
        "## Breakdown (pg_stat_activity)",
        "",
        "| state | application_name | backend_type | conn_count |",
        "| --- | --- | --- | --- |",
    ]
    for row in report.rows:
        lines.append(
            f"| {row.state} | {row.application_name} | {row.backend_type} | {row.conn_count} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_json(report: BaselineReport) -> str:
    """渲染 JSON 报表 (用于 Prometheus / 决策矩阵 ingest)."""
    payload = {
        "service": report.service,
        "max_connections": report.max_connections,
        "total_connections": report.total_connections,
        "usage_pct": report.usage_pct,
        "severity": report.severity,
        "threshold_warn_pct": report.threshold_warn_pct,
        "threshold_error_pct": report.threshold_error_pct,
        "rows": [
            {
                "state": r.state,
                "application_name": r.application_name,
                "backend_type": r.backend_type,
                "conn_count": r.conn_count,
            }
            for r in report.rows
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_report(
    raw_rows: Sequence[dict[str, Any]],
    max_connections: int,
    service: str,
    threshold_warn: float,
    threshold_error: float,
) -> BaselineReport:
    rows = parse_pg_stat_rows(raw_rows)
    total = sum(r.conn_count for r in rows)
    return BaselineReport(
        service=service,
        rows=rows,
        max_connections=max_connections,
        total_connections=total,
        threshold_warn_pct=threshold_warn,
        threshold_error_pct=threshold_error,
    )


# ─── argparse ────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="db_pool_baseline",
        description="DB pool baseline 测量 (#737 Phase A)",
    )
    parser.add_argument(
        "--service",
        choices=["tx-supply", "tx-analytics", "all"],
        default="all",
        help="只看某 service 的 application_name (filter), 或 all (聚合)",
    )
    parser.add_argument(
        "--output",
        choices=["json", "markdown", "both"],
        default="markdown",
        help="输出格式",
    )
    parser.add_argument(
        "--report-path",
        default="-",
        help="输出文件路径; '-' 表示 stdout",
    )
    parser.add_argument(
        "--threshold-warn",
        type=float,
        default=60.0,
        help="预警阈值 (usage_pct >= 此值 退码 1)",
    )
    parser.add_argument(
        "--threshold-error",
        type=float,
        default=80.0,
        help="危险阈值 (usage_pct >= 此值 退码 2)",
    )
    return parser


# ─── 主入口 (async, asyncpg connect) ────────────────────────────────────────


async def _fetch_baseline(dsn: str) -> tuple[list[dict[str, Any]], int]:
    """连 PG 读 pg_stat_activity + SHOW max_connections.

    helper-only test 模式下不被覆盖; 走 mock asyncpg.connect 路径.
    """
    import asyncpg  # type: ignore[import-untyped]

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT state, application_name, backend_type, COUNT(*) AS conn_count
            FROM pg_stat_activity
            WHERE datname = current_database()
            GROUP BY state, application_name, backend_type
            ORDER BY conn_count DESC
            """
        )
        max_conn_row = await conn.fetchrow("SHOW max_connections")
        max_connections = int(max_conn_row[0]) if max_conn_row else 0
        return [dict(r) for r in rows], max_connections
    finally:
        await conn.close()


def _write_report(report: BaselineReport, output: str, path: str) -> None:
    if output == "json":
        text = render_json(report)
    elif output == "markdown":
        text = render_markdown(report)
    else:  # both
        text = render_markdown(report) + "\n\n```json\n" + render_json(report) + "\n```\n"

    if path == "-" or path == "":
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)


async def _async_main(args: argparse.Namespace) -> int:
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        sys.stderr.write("ERROR: DATABASE_URL env not set\n")
        return 3

    try:
        raw_rows, max_connections = await _fetch_baseline(dsn)
    except Exception as exc:  # noqa: BLE001
        # 最外层兜底 — 仅 infra 故障; 由 exit code 3 区分 (不算业务 warn/error)
        sys.stderr.write(f"ERROR: DB baseline fetch failed: {exc!r}\n")
        return 3

    # service filter (POC: 只 metadata 注记, 不在 SQL 层 filter — Phase A baseline 阶段)
    report = build_report(
        raw_rows=raw_rows,
        max_connections=max_connections,
        service=args.service,
        threshold_warn=args.threshold_warn,
        threshold_error=args.threshold_error,
    )
    _write_report(report, args.output, args.report_path)
    return report.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    sys.exit(main())
