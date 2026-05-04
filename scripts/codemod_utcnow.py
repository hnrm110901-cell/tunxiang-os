#!/usr/bin/env python3
"""
One-shot codemod: datetime.utcnow() -> datetime.now(timezone.utc)

Python 3.12 deprecates datetime.utcnow(). This script:
  1. regex-replaces all bare `datetime.utcnow()` call sites
  2. ensures `timezone` is imported from the existing `from datetime import ...` line
  3. preserves all chained semantics (.isoformat(), + timedelta(...), etc.)
  4. skips files that don't have any `from datetime import ...` (rare; logged for human review)

Usage:
  python3 scripts/codemod_utcnow.py file1.py file2.py ...
  python3 scripts/codemod_utcnow.py --dry-run file1.py
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

UTCNOW_RE = re.compile(r"\bdatetime\.utcnow\(\)")
# matches: from datetime import a, b, c    (single-line; multi-line `from datetime import (...)` handled separately)
FROM_DATETIME_LINE_RE = re.compile(
    r"^(?P<indent>\s*)from\s+datetime\s+import\s+(?P<names>[^\n()]+)$",
    re.MULTILINE,
)
# matches: from datetime import (\n  a,\n  b,\n)
FROM_DATETIME_PAREN_RE = re.compile(
    r"^(?P<indent>\s*)from\s+datetime\s+import\s+\((?P<names>[^)]*)\)",
    re.MULTILINE,
)


def _names_have_timezone(names_text: str) -> bool:
    return any(tok.strip() == "timezone" for tok in names_text.split(","))


def _add_timezone_to_names(names_text: str) -> str:
    """Insert `timezone` into the comma-separated import list, keeping order roughly alphabetical."""
    parts = [p.strip() for p in names_text.split(",") if p.strip()]
    if "timezone" in parts:
        return names_text
    parts.append("timezone")
    parts = sorted(set(parts))
    return ", ".join(parts)


def ensure_timezone_import(src: str) -> tuple[str, bool]:
    """
    If the file imports from datetime but lacks `timezone`, add it.
    Returns (new_src, modified).
    """
    # Try parenthesised multi-line form first (more permissive match).
    m_paren = FROM_DATETIME_PAREN_RE.search(src)
    if m_paren and not _names_have_timezone(m_paren.group("names")):
        names_text = m_paren.group("names")
        # preserve original formatting inside parens by appending `, timezone`
        # before the closing paren if missing. Simpler: rebuild names sorted.
        parts = [p.strip() for p in names_text.replace("\n", "").split(",") if p.strip()]
        parts.append("timezone")
        parts = sorted(set(parts))
        new_block = f"{m_paren.group('indent')}from datetime import ({', '.join(parts)})"
        src = src[: m_paren.start()] + new_block + src[m_paren.end() :]
        return src, True

    m = FROM_DATETIME_LINE_RE.search(src)
    if m and not _names_have_timezone(m.group("names")):
        new_names = _add_timezone_to_names(m.group("names"))
        new_line = f"{m.group('indent')}from datetime import {new_names}"
        src = src[: m.start()] + new_line + src[m.end() :]
        return src, True

    # No `from datetime import ...` at all: caller decides whether to skip.
    if not m and not m_paren:
        # check if module uses `import datetime` (qualified) — that's fine, no change needed
        if re.search(r"^\s*import\s+datetime\b", src, re.MULTILINE):
            return src, False
        return src, False

    return src, False


def process_file(path: Path, dry_run: bool = False) -> tuple[bool, int, str]:
    """
    Returns (modified, replacements_count, status_message).
    """
    try:
        original = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False, 0, f"SKIP (non-utf8): {path}"

    if "datetime.utcnow()" not in original:
        return False, 0, f"SKIP (no utcnow): {path}"

    # Detect import style
    has_from_datetime = bool(
        FROM_DATETIME_LINE_RE.search(original) or FROM_DATETIME_PAREN_RE.search(original)
    )
    has_qualified_import = bool(re.search(r"^\s*import\s+datetime\b", original, re.MULTILINE))

    if not has_from_datetime and not has_qualified_import:
        return False, 0, f"SKIP (no datetime import found): {path}"

    # Replace utcnow()
    new_src, n = UTCNOW_RE.subn("datetime.now(timezone.utc)", original)

    if has_from_datetime:
        new_src, _added_tz = ensure_timezone_import(new_src)
    else:
        # Pure `import datetime` style → use `datetime.timezone.utc`
        # (rare in this codebase; fix the replacement to use the qualified name)
        new_src = new_src.replace("datetime.now(timezone.utc)", "datetime.now(datetime.timezone.utc)")

    if new_src == original:
        return False, 0, f"NOOP: {path}"

    if not dry_run:
        path.write_text(new_src, encoding="utf-8")

    return True, n, f"OK ({n} repl): {path}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    total_files = 0
    total_repls = 0
    skipped: list[str] = []

    for f in args.files:
        if not f.exists():
            print(f"MISSING: {f}", file=sys.stderr)
            skipped.append(str(f))
            continue
        modified, n, msg = process_file(f, dry_run=args.dry_run)
        print(msg)
        if modified:
            total_files += 1
            total_repls += n
        elif "SKIP" in msg:
            skipped.append(str(f))

    print(f"\n--- summary ---")
    print(f"files modified: {total_files}")
    print(f"replacements:   {total_repls}")
    print(f"skipped:        {len(skipped)}")
    for s in skipped:
        print(f"  - {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
