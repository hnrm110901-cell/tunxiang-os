"""
code-fact-scan.py — 代码事实扫描脚本 (屯象OS 治理四件套之一)

用法:
    python scripts/code-fact-scan.py
    python scripts/code-fact-scan.py --week-override 2026-W20

输出:
    - JSON 到 stdout (key=服务名)
    - Markdown 表格到 docs/service-health/{YYYY}-W{WW}.md

字段说明:
    service_name         目录名
    main_loc             main.py / server.py 行数 (找不到为 -1)
    router_count         app.include_router( 命中数 (main.py)
    commits_30d          最近 30 天该服务目录 commit 数
    try_except_count     src/ 下 try: 块数
    silent_failure_count src/ 下 except.*: pass 或 except.*: return None 模式数
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TypedDict


class ServiceStats(TypedDict):
    service_name: str
    main_loc: int
    router_count: int
    commits_30d: int
    try_except_count: int
    silent_failure_count: int


def _count_lines(path: Path) -> int:
    """Return line count of a file."""
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return -1


def _find_main_file(src_dir: Path) -> Path | None:
    """Return path to main.py or server.py under src_dir, preferring main.py."""
    main = src_dir / "main.py"
    if main.exists():
        return main
    server = src_dir / "server.py"
    if server.exists():
        return server
    return None


def _count_router_includes(main_path: Path | None) -> int:
    """Count app.include_router( occurrences in main file."""
    if main_path is None:
        return 0
    try:
        text = main_path.read_text(encoding="utf-8", errors="replace")
        return text.count("app.include_router(")
    except OSError:
        return 0


def _count_git_commits_30d(repo_root: Path, service_path: Path) -> int:
    """Count commits touching service_path in the last 30 days."""
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--since=30.days",
                "--oneline",
                "--",
                str(service_path.relative_to(repo_root)),
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=15,
        )
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        return len(lines)
    except (subprocess.TimeoutExpired, OSError):
        return -1


def _count_try_except(src_dir: Path) -> tuple[int, int]:
    r"""
    Walk src_dir for Python files and count:
        try_count          -- lines matching r'^\s*try:\s*$'
        silent_fail_count  -- lines matching silent patterns
    Returns (try_count, silent_fail_count).
    """
    try_pat = re.compile(r"^\s*try:\s*$")
    # silent: `except ...: pass` on same line OR `except ...: return None` on same line
    silent_pat = re.compile(
        r"^\s*except\b[^:]*:\s*(pass|return\s+None)\s*(?:#.*)?$"
    )

    try_count = 0
    silent_count = 0

    if not src_dir.is_dir():
        return 0, 0

    for py_file in src_dir.rglob("*.py"):
        # skip __pycache__
        if "__pycache__" in py_file.parts:
            continue
        try:
            for line in py_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if try_pat.match(line):
                    try_count += 1
                if silent_pat.match(line):
                    silent_count += 1
        except OSError:
            continue

    return try_count, silent_count


def scan_service(service_dir: Path, repo_root: Path) -> ServiceStats:
    """Collect stats for a single service directory."""
    name = service_dir.name
    src_dir = service_dir / "src"

    main_path = _find_main_file(src_dir)
    main_loc = _count_lines(main_path) if main_path else -1
    router_count = _count_router_includes(main_path)
    commits_30d = _count_git_commits_30d(repo_root, service_dir)
    try_count, silent_count = _count_try_except(src_dir)

    return ServiceStats(
        service_name=name,
        main_loc=main_loc,
        router_count=router_count,
        commits_30d=commits_30d,
        try_except_count=try_count,
        silent_failure_count=silent_count,
    )


def scan_all(repo_root: Path) -> dict[str, ServiceStats]:
    """Scan all services under repo_root/services/."""
    services_dir = repo_root / "services"
    results: dict[str, ServiceStats] = {}

    service_dirs = sorted(
        d for d in services_dir.iterdir()
        if d.is_dir() and not d.name.startswith("__")
    )

    for svc_dir in service_dirs:
        stats = scan_service(svc_dir, repo_root)
        results[stats["service_name"]] = stats

    return results


def _iso_week_label(dt: datetime.date) -> str:
    """Return YYYY-WXX label (ISO week, zero-padded)."""
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _build_markdown(
    stats: dict[str, ServiceStats],
    week_label: str,
    run_time: datetime.datetime,
    git_commit: str,
) -> str:
    rows = sorted(stats.values(), key=lambda s: s["service_name"])

    header_line = f"# 服务健康度报告 — {week_label}\n"
    meta = (
        f"- **执行时间**: {run_time.isoformat(timespec='seconds')}\n"
        f"- **Git commit**: `{git_commit}`\n"
        f"- **扫描服务数**: {len(rows)}\n"
    )

    # Main table
    table_header = (
        "| 服务名 | main_loc | router_count | commits_30d "
        "| try_except_count | silent_failure_count |\n"
        "| --- | ---: | ---: | ---: | ---: | ---: |"
    )
    table_rows = "\n".join(
        f"| {r['service_name']} | {r['main_loc']} | {r['router_count']} "
        f"| {r['commits_30d']} | {r['try_except_count']} | {r['silent_failure_count']} |"
        for r in rows
    )

    # TL;DR
    def top3(key: str, label: str) -> str:
        top = sorted(
            (s for s in rows if s[key] >= 0),  # type: ignore[literal-required]
            key=lambda s: s[key],  # type: ignore[literal-required]
            reverse=True,
        )[:3]
        items = ", ".join(f"{s['service_name']} ({s[key]})" for s in top)  # type: ignore[literal-required]
        return f"- **{label}**: {items}"

    tldr = "\n".join([
        "## TL;DR",
        top3("main_loc", "行数最长的 3 服务"),
        top3("try_except_count", "try-except 最多的 3 服务"),
        top3("commits_30d", "30 天最活跃的 3 服务"),
    ])

    notes = (
        "## 备注 (阈值参考)\n"
        "- `main_loc > 300`: 考虑拆分路由\n"
        "- `silent_failure_count > 5`: 审查静默异常\n"
        "- `commits_30d == -1`: git 调用失败\n"
        "- `main_loc == -1`: 未找到 main.py / server.py\n"
        "- mcp-server 入口为 `server.py` (非 main.py), 已正确识别\n"
    )

    return "\n\n".join([
        header_line + "\n" + meta,
        "## 主表格\n\n" + table_header + "\n" + table_rows,
        tldr,
        notes,
    ]) + "\n"


def _get_git_commit(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except (subprocess.TimeoutExpired, OSError):
        return "unknown"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="屯象OS 代码事实扫描 — 收集服务健康度指标",
    )
    parser.add_argument(
        "--week-override",
        metavar="YYYY-WXX",
        help="覆盖 ISO 周号 (供测试用, 例: 2026-W20)",
    )
    parser.add_argument(
        "--repo-root",
        metavar="PATH",
        help="仓库根目录 (默认: 脚本所在目录的父目录)",
    )
    args = parser.parse_args(argv)

    # Resolve repo root
    script_dir = Path(__file__).resolve().parent
    repo_root = Path(args.repo_root).resolve() if args.repo_root else script_dir.parent

    run_time = datetime.datetime.now(tz=datetime.timezone.utc)
    week_label = args.week_override or _iso_week_label(run_time.date())

    stats = scan_all(repo_root)

    # Output JSON to stdout
    print(json.dumps(stats, indent=2, ensure_ascii=False))

    # Write Markdown report
    git_commit = _get_git_commit(repo_root)
    md_content = _build_markdown(stats, week_label, run_time, git_commit)

    out_dir = repo_root / "docs" / "service-health"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{week_label}.md"
    out_path.write_text(md_content, encoding="utf-8")

    print(f"\n[code-fact-scan] Report written to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
