#!/usr/bin/env python3
"""tier1-gate import-only carve-out 检测器（issue #417 / 流程 3 §"根治 follow-up" 方案 1）。

用途：判断 PR diff 是否仅由 Python `from`/`import` 行改动组成。

输出：单行 stdout `true` 或 `false`。
- `true`  → carve-out 通过（codemod / namespace 切换类 PR，无业务行为变化）
- `false` → 保守判，让原 tier1-gate `源改动必须配对测试改动` 校验走

判 false 的保守场景（即使本质 import-only）：
- 任何非 .py 文件改动（yaml / sql / md 等）
- import 续行多行括号形式（`from x import (\n    a,\n    b,\n)`）
- docstring / 注释 / 空行外的任何非 import 行

如此设计是因为：放过真业务 PR 的代价（无测试上线）远高于多走一次 admin-merge bypass。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# 匹配 `from X import Y` 或 `import X`，允许任意前导 whitespace。
# 同时覆盖 PEP 328 相对 import (`from .x import y`、`from ..x import y`)
# 和 import-as 形式 (`import x as y`、`from x import y as z`)。
#
# from 分支的尾段用 `[^;\n]+` 而非 `\S.*` — 排除分号（复合语句分隔符）。
# 防止 `from X import Y; side_effect()` 类伪 import 行被误判为纯 import。
IMPORT_LINE_RE = re.compile(
    r"^\s*(?:from\s+\.*\S+\s+import\s+[^;\n]+|import\s+\S+(?:\s+as\s+\S+)?(?:\s*,\s*\S+(?:\s+as\s+\S+)?)*)\s*$"
)


def _git(args: list[str]) -> str:
    """Run a git command, raise CalledProcessError on non-zero exit."""
    return subprocess.check_output(["git", *args], text=True)


def _changed_files(base: str, head: str) -> list[str]:
    out = _git(["diff", "--name-only", base, head])
    return [line for line in out.splitlines() if line]


def _line_is_import_only(content: str) -> bool:
    """True if a single content line is empty / a comment / or a from-import / import line."""
    stripped = content.strip()
    if not stripped:
        return True
    if stripped.startswith("#"):
        return True
    return bool(IMPORT_LINE_RE.match(content))


def is_import_only(base: str, head: str) -> bool:
    files = _changed_files(base, head)
    if not files:
        # No changes at all → conservative false (let the gate walk its normal path).
        return False

    # Any non-.py file change → conservative false.
    py_files = [f for f in files if f.endswith(".py")]
    if len(py_files) != len(files):
        return False
    if not py_files:
        return False

    # Pull unified diff with zero context, scoped to the .py files.
    diff_text = _git(["diff", "-U0", base, head, "--", *py_files])

    saw_import_change = False
    for raw in diff_text.splitlines():
        if not raw:
            continue
        # Skip diff metadata.
        if raw.startswith(("+++", "---", "diff ", "index ", "@@", "new file", "deleted file", "similarity ", "rename ")):
            continue
        # Only +/- lines are actual content changes.
        if not (raw.startswith("+") or raw.startswith("-")):
            continue
        content = raw[1:]
        if not _line_is_import_only(content):
            return False
        # Track whether the change includes at least one real import statement
        # (so pure comment/blank diffs don't sneak through as carve-out).
        if IMPORT_LINE_RE.match(content):
            saw_import_change = True

    return saw_import_change


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Base commit SHA")
    parser.add_argument("--head", required=True, help="Head commit SHA")
    args = parser.parse_args()

    try:
        result = is_import_only(args.base, args.head)
    except subprocess.CalledProcessError as exc:
        print(f"git error: {exc}", file=sys.stderr)
        return exc.returncode or 1

    print("true" if result else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
