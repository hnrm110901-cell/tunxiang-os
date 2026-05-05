#!/usr/bin/env python3
"""PG.7 — assert RLS UPDATE/ALL policies always declare WITH CHECK.

Background:
    A `CREATE POLICY ... FOR UPDATE USING (tenant_id = X)` clause that omits
    `WITH CHECK` only restricts which rows the tenant can SEE in the UPDATE
    target list — it does NOT restrict which tenant_id the row may end up
    with after the UPDATE. An attacker who can write to a `tenant_id` column
    (via a business-logic bug or SQL injection) can flip a row to another
    tenant; the original row "escapes" cross-tenant. v395/v399/v400 fixed
    every existing UPDATE-policy regression of this shape. This guard
    prevents regression in any future migration.

Rule:
    For every `CREATE POLICY` in `shared/db-migrations/versions/v*.py`:
        if the FOR clause is UPDATE or ALL → the same statement MUST also
        contain `WITH CHECK`.

Scope:
    - Scans only literal SQL inside migration files (raw strings handed to
      `op.execute` / `cur.execute` / heredoc).
    - Helper-generated SQL (e.g. `setup_rls_policies(table)`) is INVISIBLE
      to this lint — those helpers must be reviewed at definition site.
    - Reports violations and exits 1; otherwise exits 0.

Usage:
    python3 scripts/check_rls_with_check.py
    python3 scripts/check_rls_with_check.py --versions-dir shared/db-migrations/versions
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Match each CREATE POLICY ... ; statement, capturing everything up to the
# terminating semicolon. Multi-line. Case-insensitive. Non-greedy on body.
# Supports `IF NOT EXISTS` and policy names with quotes.
_CREATE_POLICY_RE = re.compile(
    r"CREATE\s+POLICY\b(?P<body>[^;]+);",
    re.IGNORECASE | re.DOTALL,
)

_FOR_CLAUSE_RE = re.compile(
    r"\bFOR\s+(?P<cmd>SELECT|INSERT|UPDATE|DELETE|ALL)\b",
    re.IGNORECASE,
)


def find_violations(text: str) -> list[tuple[int, str]]:
    """Return (line_number, snippet) for each FOR UPDATE/ALL policy missing WITH CHECK."""
    violations: list[tuple[int, str]] = []
    for m in _CREATE_POLICY_RE.finditer(text):
        body = m.group("body")
        for_match = _FOR_CLAUSE_RE.search(body)
        if not for_match:
            continue
        cmd = for_match.group("cmd").upper()
        if cmd not in ("UPDATE", "ALL"):
            continue
        if re.search(r"\bWITH\s+CHECK\b", body, re.IGNORECASE):
            continue
        line_no = text.count("\n", 0, m.start()) + 1
        snippet = "CREATE POLICY" + body.strip().replace("\n", " ")[:120]
        violations.append((line_no, snippet))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--versions-dir",
        default="shared/db-migrations/versions",
        help="Path to alembic versions dir (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    versions_dir = Path(args.versions_dir)
    if not versions_dir.is_dir():
        print(f"::error::Versions directory not found: {versions_dir}", file=sys.stderr)
        return 1

    total_violations = 0
    files_scanned = 0
    for f in sorted(versions_dir.glob("v*.py")):
        if f.name.startswith("__"):
            continue
        files_scanned += 1
        text = f.read_text(encoding="utf-8")
        for line_no, snippet in find_violations(text):
            total_violations += 1
            print(
                f"::error file={f},line={line_no}::"
                f"FOR UPDATE/ALL policy missing WITH CHECK: {snippet}"
            )

    print(
        f"check_rls_with_check: scanned {files_scanned} migrations, "
        f"{total_violations} violation(s)"
    )
    return 1 if total_violations else 0


if __name__ == "__main__":
    sys.exit(main())
