#!/usr/bin/env python3
"""P2.5 Phase 2 codemod — replace `raise HTTPException(status_code=N, detail=str(e))`
with `raise safe_http_exception(N, "<generic>", e) from e`.

Idempotent. Adds `from shared.security.src.error_handler import safe_http_exception`
import if missing. Handles multi-line `from x import (...)` blocks.

Usage:
  python scripts/codemod_safe_http_exception.py services/tx-trade/src/api
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HTTPEXC_DETAIL_RE = re.compile(
    r"raise\s+HTTPException\s*\(\s*"
    r"status_code\s*=\s*(?P<code>\d+)\s*,\s*"
    r"detail\s*=\s*str\(\s*(?P<var>[a-zA-Z_][a-zA-Z0-9_]*)\s*\)\s*,?\s*"
    r"\)"
    r"(?:\s+from\s+\w+)?",
    re.DOTALL,
)

GENERIC_MESSAGES: dict[int, str] = {
    400: "请求参数无效",
    401: "认证失败",
    403: "权限不足",
    404: "资源不存在",
    409: "操作冲突",
    422: "请求格式错误",
    429: "请求过于频繁",
    500: "服务器内部错误",
    502: "上游服务不可用",
    503: "服务暂时不可用",
    504: "上游服务超时",
}

IMPORT_LINE = "from shared.security.src.error_handler import safe_http_exception"


def _replacement(m: re.Match[str]) -> str:
    code = int(m.group("code"))
    var = m.group("var")
    msg = GENERIC_MESSAGES.get(code, "操作失败")
    return f'raise safe_http_exception({code}, "{msg}", {var}) from {var}'


def _ensure_import(lines: list[str]) -> list[str]:
    if any(IMPORT_LINE in ln for ln in lines):
        return lines

    last_import_idx = -1
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip("\n")
        # Only consider TOP-LEVEL imports (no leading whitespace).
        # Imports inside functions/classes must be ignored.
        is_top_level = ln.startswith(("import ", "from "))
        if is_top_level:
            if "(" in ln and ln.count("(") > ln.count(")"):
                depth = ln.count("(") - ln.count(")")
                j = i + 1
                while j < len(lines) and depth > 0:
                    depth += lines[j].count("(") - lines[j].count(")")
                    j += 1
                last_import_idx = j - 1
                i = j
                continue
            last_import_idx = i
        i += 1

    if last_import_idx == -1:
        return [IMPORT_LINE + "\n", "\n"] + lines

    insert_at = last_import_idx + 1
    return lines[:insert_at] + [IMPORT_LINE + "\n"] + lines[insert_at:]


def process_file(path: Path) -> tuple[bool, int]:
    text = path.read_text(encoding="utf-8")
    new_text, n = HTTPEXC_DETAIL_RE.subn(_replacement, text)
    if n == 0:
        return (False, 0)
    lines = new_text.splitlines(keepends=True)
    lines = _ensure_import(lines)
    path.write_text("".join(lines), encoding="utf-8")
    return (True, n)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: codemod_safe_http_exception.py <file_or_dir> [...]", file=sys.stderr)
        return 1

    paths: list[Path] = []
    for arg in argv[1:]:
        p = Path(arg)
        if p.is_dir():
            paths.extend(p.rglob("*.py"))
        elif p.is_file():
            paths.append(p)

    total_files = 0
    total_repls = 0
    for p in paths:
        changed, n = process_file(p)
        if changed:
            total_files += 1
            total_repls += n
            print(f"  {n:3d}  {p}")

    print(f"\nDone: {total_files} files, {total_repls} replacements")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
