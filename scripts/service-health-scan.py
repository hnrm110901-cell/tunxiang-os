#!/usr/bin/env python3
"""服务粒度健康度扫描

为 12 周升级战略提供 baseline。每周一自动跑，输出 docs/service-health/YYYY-WXX.md。

维度：
  - main.py 行数
  - include_router 调用数（路由数）
  - try/except 块数
  - silent failure 数（except 后 .warning / pass / return None）
  - 30 天 commit 数
  - test_*_tier1.py 文件数 + 用例数
  - 健康度评分（0-10）

评分扣分规则：
  - main.py > 300 行 -1，> 600 -2，> 1000 -3
  - try-except > 10 -1，> 30 -2
  - silent failure > 5 -2，> 15 -3
  - main.py 路由数 > 50 -2（小单体征兆）

使用：python3 scripts/service-health-scan.py
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICES_DIR = ROOT / "services"
OUTPUT_DIR = ROOT / "docs" / "service-health"

SILENT_FAILURE_PATTERNS = [
    re.compile(r"except[^:]*:\s*(?:#[^\n]*\n)?\s*pass\b"),
    re.compile(r"except[^:]*:\s*(?:#[^\n]*\n)?\s*return\s+None\b"),
    re.compile(r"except[^:]*:\s*(?:#[^\n]*\n)?\s*(?:[a-zA-Z_][\w.]*\.)?logger?\.warning\("),
    re.compile(r"except[^:]*:\s*(?:#[^\n]*\n)?\s*structlog\.get_logger[^.]*\.\w*warning\("),
    re.compile(r"except\s+ImportError[^:]*:\s*(?:#[^\n]*\n)?\s*\w+\s*=\s*None"),
]


@dataclass
class ServiceMetrics:
    name: str
    main_lines: int = 0
    main_routers: int = 0
    py_files: int = 0
    py_total_lines: int = 0
    try_except_count: int = 0
    silent_failures: int = 0
    commits_30d: int = 0
    tier1_test_files: int = 0
    tier1_test_cases: int = 0
    score: int = 10
    deductions: list[str] = field(default_factory=list)


def count_lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore"))
    except OSError:
        return 0


def grep_count(path: Path, pattern: str) -> int:
    if not path.exists():
        return 0
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    return len(re.findall(pattern, text))


def scan_silent_failures(py_files: list[Path]) -> int:
    total = 0
    for f in py_files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in SILENT_FAILURE_PATTERNS:
            total += len(pat.findall(text))
    return total


def scan_try_except(py_files: list[Path]) -> int:
    total = 0
    pat = re.compile(r"^\s*except\b", re.MULTILINE)
    for f in py_files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        total += len(pat.findall(text))
    return total


def git_commits_30d(service_dir: Path) -> int:
    try:
        result = subprocess.run(
            [
                "git", "-C", str(ROOT), "log",
                "--since=30 days ago", "--oneline", "--", str(service_dir.relative_to(ROOT)),
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return 0
        return len([ln for ln in result.stdout.splitlines() if ln.strip()])
    except (subprocess.SubprocessError, OSError):
        return 0


def scan_tier1_tests(service_dir: Path) -> tuple[int, int]:
    files = list(service_dir.rglob("test_*_tier1.py"))
    if not files:
        return 0, 0
    pat = re.compile(r"^\s*(?:async\s+)?def\s+test_", re.MULTILINE)
    cases = 0
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        cases += len(pat.findall(text))
    return len(files), cases


def compute_score(m: ServiceMetrics) -> tuple[int, list[str]]:
    score = 10
    deductions: list[str] = []

    if m.main_lines > 1000:
        score -= 3
        deductions.append(f"main.py {m.main_lines} 行 (>1000) -3")
    elif m.main_lines > 600:
        score -= 2
        deductions.append(f"main.py {m.main_lines} 行 (>600) -2")
    elif m.main_lines > 300:
        score -= 1
        deductions.append(f"main.py {m.main_lines} 行 (>300) -1")

    if m.main_routers > 50:
        score -= 2
        deductions.append(f"main.py 注册 {m.main_routers} 个 router (>50) -2")

    if m.try_except_count > 30:
        score -= 2
        deductions.append(f"try/except {m.try_except_count} 处 (>30) -2")
    elif m.try_except_count > 10:
        score -= 1
        deductions.append(f"try/except {m.try_except_count} 处 (>10) -1")

    if m.silent_failures > 15:
        score -= 3
        deductions.append(f"silent failure {m.silent_failures} 处 (>15) -3")
    elif m.silent_failures > 5:
        score -= 2
        deductions.append(f"silent failure {m.silent_failures} 处 (>5) -2")

    return max(score, 0), deductions


def scan_service(svc_dir: Path) -> ServiceMetrics:
    m = ServiceMetrics(name=svc_dir.name)

    main_py = svc_dir / "src" / "main.py"
    if main_py.exists():
        m.main_lines = count_lines(main_py)
        m.main_routers = grep_count(main_py, r"\.include_router\(")

    py_files = [f for f in svc_dir.rglob("*.py")
                if "__pycache__" not in f.parts and "tests" not in f.parts]
    m.py_files = len(py_files)
    m.py_total_lines = sum(count_lines(f) for f in py_files)
    m.try_except_count = scan_try_except(py_files)
    m.silent_failures = scan_silent_failures(py_files)
    m.commits_30d = git_commits_30d(svc_dir)
    m.tier1_test_files, m.tier1_test_cases = scan_tier1_tests(svc_dir)

    m.score, m.deductions = compute_score(m)
    return m


def main() -> None:
    if not SERVICES_DIR.is_dir():
        print(f"ERROR: {SERVICES_DIR} not found")
        return

    services = sorted(d for d in SERVICES_DIR.iterdir()
                      if d.is_dir() and not d.name.startswith("."))
    metrics = [scan_service(s) for s in services]

    now = dt.datetime.now()
    iso_year, iso_week, _ = now.isocalendar()
    week_tag = f"{iso_year}-W{iso_week:02d}"
    commit = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()

    out = OUTPUT_DIR / f"{week_tag}.md"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append(f"# 屯象OS 服务健康度 baseline — {week_tag}")
    lines.append("")
    lines.append(f"生成时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"提交：`{commit}`")
    lines.append(f"扫描脚本：`scripts/service-health-scan.py`")
    lines.append("")
    lines.append("> 12 周升级战略的服务粒度 baseline。每周一自动跑。")
    lines.append("> 评分扣分规则见脚本头部。0-10 分，10 = 健康，0 = 必须收敛。")
    lines.append("")

    lines.append(f"## 总览（{len(metrics)} 个服务）")
    lines.append("")
    lines.append("| 服务 | 评分 | main.py | router | try/except | silent | 30天commit | Tier1测试 |")
    lines.append("|------|------|---------|--------|------------|--------|-----------|-----------|")
    for m in sorted(metrics, key=lambda x: (x.score, -x.main_lines)):
        score_mark = "🔴" if m.score <= 5 else ("🟡" if m.score <= 7 else "🟢")
        lines.append(
            f"| `{m.name}` | {score_mark} {m.score} | {m.main_lines} | "
            f"{m.main_routers} | {m.try_except_count} | {m.silent_failures} | "
            f"{m.commits_30d} | {m.tier1_test_files}文件/{m.tier1_test_cases}用例 |"
        )
    lines.append("")

    lines.append("## 全仓汇总")
    lines.append("")
    lines.append(f"- 服务总数：**{len(metrics)}**")
    lines.append(f"- main.py 总行数：**{sum(m.main_lines for m in metrics):,}**")
    lines.append(f"- Python 源文件总行数（不含 tests）：**{sum(m.py_total_lines for m in metrics):,}**")
    lines.append(f"- include_router 总注册数：**{sum(m.main_routers for m in metrics):,}**")
    lines.append(f"- try/except 总数：**{sum(m.try_except_count for m in metrics):,}**")
    lines.append(f"- silent failure 总数：**{sum(m.silent_failures for m in metrics):,}**")
    lines.append(f"- 30 天 commit 总数：**{sum(m.commits_30d for m in metrics):,}**")
    lines.append(f"- Tier 1 测试文件总数：**{sum(m.tier1_test_files for m in metrics):,}**")
    lines.append(f"- 健康度评分 ≤ 5 的服务：**{sum(1 for m in metrics if m.score <= 5)}**")
    lines.append("")

    danger = [m for m in metrics if m.score <= 5]
    if danger:
        lines.append("## 红色警报（评分 ≤ 5，必须收敛）")
        lines.append("")
        for m in danger:
            lines.append(f"### `{m.name}` — {m.score}/10")
            for d in m.deductions:
                lines.append(f"  - {d}")
            lines.append("")

    yellow = [m for m in metrics if 5 < m.score <= 7]
    if yellow:
        lines.append("## 黄色警告（评分 6-7，需关注）")
        lines.append("")
        for m in yellow:
            lines.append(f"- `{m.name}` ({m.score}/10): " + "; ".join(m.deductions))
        lines.append("")

    lines.append("## 12 周战略追踪指标")
    lines.append("")
    lines.append("以下指标后续每周对比，验证 12 周计划是否生效：")
    lines.append("")
    lines.append("| 指标 | 本周 baseline | W12 目标 |")
    lines.append("|------|---------------|----------|")
    lines.append(f"| 服务总数 | {len(metrics)} | 17 |")
    lines.append(f"| main.py 总行数 | {sum(m.main_lines for m in metrics):,} | < 50% baseline |")
    lines.append(f"| silent failure 总数 | {sum(m.silent_failures for m in metrics):,} | < 20% baseline |")
    lines.append(f"| 评分 ≤ 5 服务数 | {sum(1 for m in metrics if m.score <= 5)} | 0 |")
    lines.append(f"| Tier 1 测试用例总数 | {sum(m.tier1_test_cases for m in metrics):,} | ≥ 2× baseline |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*由 `scripts/service-health-scan.py` 自动生成。后续每周一自动跑，对比趋势。*")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✅ baseline 已生成: {out.relative_to(ROOT)}")
    print(f"   服务数: {len(metrics)} | 红色: {sum(1 for m in metrics if m.score <= 5)} | 黄色: {sum(1 for m in metrics if 5 < m.score <= 7)}")


if __name__ == "__main__":
    main()
