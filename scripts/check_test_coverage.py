#!/usr/bin/env python3
"""屯象OS 测试覆盖率闸门检查脚本

扫描所有 services/ 目录，计算每个服务的测试函数数与非测试代码行数，
以 "tests per KLOC" 指标判断测试覆盖是否达标。

Usage:
  python scripts/check_test_coverage.py              # human-readable 输出
  python scripts/check_test_coverage.py --json       # JSON 供 CI 消费
  python scripts/check_test_coverage.py --threshold 40  # 自定义阈值

Exit codes:
  0 = 所有服务测试覆盖率达标
  1 = 存在服务低于阈值
  2 = 配置/执行错误

CLAUDE.md 引用:
  - § 17 Tier 1 零容忍路径
  - § 20 Tier 1 测试标准（TDD, 真实餐厅场景）
  - § 22 Week 8 DEMO 验收门槛（Tier 1 全绿 / 1k 测试）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Exit codes
# ─────────────────────────────────────────────────────────────────────────────

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICES_DIR = REPO_ROOT / "services"

# Regex for test function definitions: async def test_* or def test_*
TEST_FUNC_RE = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\(", re.MULTILINE)

# Default threshold: tests per 1000 lines of non-test code
# 40 tests/KLOC is the aspirational goal; CI can override.
DEFAULT_THRESHOLD = 40.0

# ANSI colors
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
RESET = "\033[0m"


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ServiceCoverage:
    service: str
    test_files: int = 0
    test_functions: int = 0
    non_test_files: int = 0
    non_test_lines: int = 0  # non-blank, non-comment lines
    threshold: float = DEFAULT_THRESHOLD

    @property
    def non_test_kloc(self) -> float:
        return self.non_test_lines / 1000.0

    @property
    def tests_per_kloc(self) -> float:
        """test functions per thousand lines of non-test code."""
        if self.non_test_kloc <= 0:
            return float("inf") if self.test_functions > 0 else 0.0
        return self.test_functions / self.non_test_kloc

    @property
    def passes(self) -> bool:
        return self.tests_per_kloc >= self.threshold

    @property
    def status_icon(self) -> str:
        return "PASS" if self.passes else "FAIL"

    @property
    def grade(self) -> str:
        """Grading based on tests/KLOC ratio."""
        r = self.tests_per_kloc
        if r >= 40:
            return "A"  # aspirational
        elif r >= 20:
            return "B"
        elif r >= 10:
            return "C"
        elif r >= 5:
            return "D"
        else:
            return "F"


# ─────────────────────────────────────────────────────────────────────────────
# Core counting logic
# ─────────────────────────────────────────────────────────────────────────────


def _count_test_functions(file_path: Path) -> int:
    """Count the number of test function definitions in a Python file."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0
    return len(TEST_FUNC_RE.findall(content))


def _count_non_blank_lines(file_path: Path) -> int:
    """Count non-blank, non-comment-only lines in a Python file."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0
    count = 0
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            count += 1
    return count


def _is_test_file(path: Path) -> bool:
    """Check if a Python file appears to be a test file.

    Criteria:
      - filename starts with test_ or ends with _test
      - OR file is inside a 'tests' directory
    """
    name = path.stem  # filename without .py
    if name.startswith("test_") or name.endswith("_test"):
        return True
    # Check if any parent directory is named 'tests'
    if "tests" in [p.name for p in path.parents]:
        return True
    return False


def scan_service(service_dir: Path, threshold: float = DEFAULT_THRESHOLD) -> ServiceCoverage:
    """Scan a service directory for test and non-test code."""
    service_name = service_dir.name
    cov = ServiceCoverage(service=service_name, threshold=threshold)

    py_files = sorted(service_dir.rglob("*.py"))
    # Filter out __pycache__
    py_files = [f for f in py_files if "__pycache__" not in str(f)]

    test_files = [f for f in py_files if _is_test_file(f)]
    non_test_files = [f for f in py_files if not _is_test_file(f)]

    cov.test_files = len(test_files)
    cov.non_test_files = len(non_test_files)

    cov.test_functions = sum(_count_test_functions(tf) for tf in test_files)
    cov.non_test_lines = sum(_count_non_blank_lines(ntf) for ntf in non_test_files)

    return cov


def scan_all_services(threshold: float = DEFAULT_THRESHOLD) -> Dict[str, ServiceCoverage]:
    """Scan all service directories under services/.

    Returns:
        Dict mapping service_name -> ServiceCoverage.
    """
    if not SERVICES_DIR.exists():
        return {}

    results: Dict[str, ServiceCoverage] = {}
    for entry in sorted(SERVICES_DIR.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            # Skip empty dirs or non-service dirs
            has_py = any(entry.rglob("*.py"))
            if has_py:
                results[entry.name] = scan_service(entry, threshold)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Report output
# ─────────────────────────────────────────────────────────────────────────────


def print_text_report(results: Dict[str, ServiceCoverage], threshold: float) -> int:
    """Print human-readable report to stderr. Returns number of failing services."""
    if not results:
        print(f"{RED}ERROR: No services found in {SERVICES_DIR}{RESET}", file=sys.stderr)
        return 0

    from datetime import datetime

    print(file=sys.stderr)
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}", file=sys.stderr)
    print(f"{BOLD}{CYAN}  屯象OS 测试覆盖率闸门检查{RESET}", file=sys.stderr)
    print(f"{BOLD}{CYAN}  检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}", file=sys.stderr)
    print(f"{BOLD}{CYAN}  阈值: {threshold:.0f} tests/KLOC{RESET}", file=sys.stderr)
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}", file=sys.stderr)

    # Summary table
    print(file=sys.stderr)
    header = f"  {'Service':<20} {'Tests':>8} {'KLOC':>10} {'Tests/KLOC':>12} {'Grade':>6}  {'Status':>6}"
    print(f"{BOLD}{header}{RESET}", file=sys.stderr)
    print(f"  {'-' * 68}", file=sys.stderr)

    passing: List[ServiceCoverage] = []
    failing: List[ServiceCoverage] = []

    for cov in sorted(results.values(), key=lambda c: c.tests_per_kloc, reverse=True):
        if cov.passes:
            passing.append(cov)
        else:
            failing.append(cov)

        color = GREEN if cov.passes else RED
        row = (
            f"  {cov.service:<20} "
            f"{cov.test_functions:>8} "
            f"{cov.non_test_kloc:>10.1f} "
            f"{cov.tests_per_kloc:>12.1f} "
            f"{cov.grade:>6}  "
            f"{color}{cov.status_icon:>6}{RESET}"
        )
        print(row, file=sys.stderr)

    # Summary stats
    total_tests = sum(c.test_functions for c in results.values())
    total_kloc = sum(c.non_test_kloc for c in results.values())
    overall_ratio = total_tests / total_kloc if total_kloc > 0 else 0

    print(file=sys.stderr)
    print(f"{BOLD}【检查汇总】{RESET}", file=sys.stderr)
    print(f"  扫描服务:       {len(results)}", file=sys.stderr)
    print(f"  通过服务:       {len(passing)}", file=sys.stderr)
    print(f"  未通过服务:     {len(failing)}", file=sys.stderr)
    print(f"  总测试函数:     {total_tests}", file=sys.stderr)
    print(f"  总非测试 KLOC:  {total_kloc:.1f}", file=sys.stderr)
    print(f"  整体 ratio:     {overall_ratio:.1f} tests/KLOC", file=sys.stderr)
    print(f"  阈值要求:       >= {threshold:.0f} tests/KLOC", file=sys.stderr)

    if failing:
        print(file=sys.stderr)
        print(f"{YELLOW}【低于阈值的服务】（{len(failing)} 个）{RESET}", file=sys.stderr)
        for cov in sorted(failing, key=lambda c: c.tests_per_kloc):
            shortfall = cov.threshold - cov.tests_per_kloc
            if cov.non_test_kloc > 0:
                tests_needed = int(shortfall * cov.non_test_kloc) + 1
                print(
                    f"  {RED}{cov.service:<20} {cov.tests_per_kloc:.1f} tests/KLOC "
                    f"(需要约 {tests_needed} 个测试达到阈值){RESET}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"  {RED}{cov.service:<20} 无代码（KLOC=0），可豁免{RESET}",
                    file=sys.stderr,
                )

    print(file=sys.stderr)
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}", file=sys.stderr)
    if failing:
        print(f"{RED}{BOLD}  结论: {len(failing)} 个服务未通过测试覆盖率闸门{RESET}", file=sys.stderr)
    else:
        print(f"{GREEN}{BOLD}  结论: 所有 {len(results)} 个服务测试覆盖率达标{RESET}", file=sys.stderr)
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}", file=sys.stderr)
    print(file=sys.stderr)

    return len(failing)


def print_json_report(
    results: Dict[str, ServiceCoverage], threshold: float
) -> int:
    """Print JSON report to stdout. Returns number of failing services."""
    total_tests = sum(c.test_functions for c in results.values())
    total_kloc = sum(c.non_test_kloc for c in results.values())
    overall_ratio = total_tests / total_kloc if total_kloc > 0 else 0
    failing_count = sum(1 for c in results.values() if not c.passes)

    services = []
    for cov in sorted(results.values(), key=lambda c: c.tests_per_kloc, reverse=True):
        services.append(
            {
                "service": cov.service,
                "test_files": cov.test_files,
                "test_functions": cov.test_functions,
                "non_test_files": cov.non_test_files,
                "non_test_lines": cov.non_test_lines,
                "non_test_kloc": round(cov.non_test_kloc, 2),
                "tests_per_kloc": round(cov.tests_per_kloc, 1),
                "grade": cov.grade,
                "passes": cov.passes,
                "threshold": threshold,
            }
        )

    payload = {
        "threshold": threshold,
        "summary": {
            "total_services": len(results),
            "passing_services": len(results) - failing_count,
            "failing_services": failing_count,
            "total_test_functions": total_tests,
            "total_non_test_kloc": round(total_kloc, 2),
            "overall_tests_per_kloc": round(overall_ratio, 1),
            "passed": failing_count == 0,
        },
        "services": services,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return failing_count


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="屯象OS 测试覆盖率闸门检查 — 计算 tests/KLOC 并校验阈值",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON 格式输出到 stdout（CI 消费）",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"tests/KLOC 的最低阈值（默认: {DEFAULT_THRESHOLD:.0f}）",
    )
    parser.add_argument(
        "--service",
        type=str,
        default=None,
        help="只检查指定服务（如: tx-trade, tx-civic）",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Validate threshold
    if args.threshold < 0:
        msg = f"阈值不能为负数 (got {args.threshold})"
        if args.json:
            print(json.dumps({"error": msg}, ensure_ascii=False, indent=2))
        else:
            print(f"{RED}ERROR: {msg}{RESET}", file=sys.stderr)
        return EXIT_ERROR

    # Scan services
    if not SERVICES_DIR.exists():
        msg = f"未找到 services 目录: {SERVICES_DIR}"
        if args.json:
            print(json.dumps({"error": msg}, ensure_ascii=False, indent=2))
        else:
            print(f"{RED}ERROR: {msg}{RESET}", file=sys.stderr)
        return EXIT_ERROR

    results = scan_all_services(threshold=args.threshold)

    # Filter to single service if requested
    if args.service:
        if args.service not in results:
            msg = f"找不到服务 '{args.service}'。可用服务: {sorted(results.keys())}"
            if args.json:
                print(json.dumps({"error": msg}, ensure_ascii=False, indent=2))
            else:
                print(f"{RED}ERROR: {msg}{RESET}", file=sys.stderr)
            return EXIT_ERROR
        results = {args.service: results[args.service]}

    if args.json:
        failing_count = print_json_report(results, args.threshold)
    else:
        failing_count = print_text_report(results, args.threshold)

    return EXIT_FAIL if failing_count > 0 else EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
