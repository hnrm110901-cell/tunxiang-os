#!/usr/bin/env python3
"""PG.7 — assert RLS UPDATE/ALL policies always declare WITH CHECK.

Background:
    A `CREATE POLICY ... FOR UPDATE USING (tenant_id = X)` clause that omits
    `WITH CHECK` only restricts which rows the tenant can SEE in the UPDATE
    target list — it does NOT restrict which tenant_id the row may end up
    with after the UPDATE. An attacker who can write to a `tenant_id` column
    (via a business-logic bug or SQL injection) can flip a row to another
    tenant; the original row "escapes" cross-tenant. v395/v399/v400/v401/v402
    fixed every existing UPDATE-policy regression of this shape. This guard
    prevents regression in any future migration.

Rule:
    For every `CREATE POLICY` SQL emitted via `op.execute(...)` outside a
    `def downgrade(...)` function, if its FOR clause is UPDATE or ALL,
    the same statement MUST also contain `WITH CHECK`.

How it works:
    1. Parse migration with ast.
    2. Walk each `op.execute(<str>)` call.
    3. Skip calls inside `def downgrade(...)` — downgrade is allowed
       to be USING-only (it deliberately rolls back to pre-fix state).
    4. Extract the SQL string (Constant, JoinedStr/f-string, or BinOp +
       string concatenation).
    5. Within each CREATE POLICY chunk (split by `CREATE POLICY` keyword
       and bounded by `;` if present), look for FOR UPDATE/ALL and assert
       WITH CHECK exists in the same chunk.

Helper-generated SQL (v067-style `_create_rls(table)`) is checked at the
helper definition because the f-string itself contains FOR UPDATE.

Limitations:
    - Only `op.execute(...)` is recognized; `conn.execute(...)` and other
      forms are ignored. All current migrations in this repo use op.execute.
    - SQL passed via variables (e.g. `op.execute(SQL_CONST)`) is not
      followed; if you write that pattern, lint won't see it.

Usage:
    python3 scripts/check_rls_with_check.py
    python3 scripts/check_rls_with_check.py --versions-dir shared/db-migrations/versions
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path


_CREATE_POLICY_RE = re.compile(r"\bCREATE\s+POLICY\b", re.IGNORECASE)
_FOR_CLAUSE_RE = re.compile(
    r"\bFOR\s+(?P<cmd>SELECT|INSERT|UPDATE|DELETE|ALL)\b",
    re.IGNORECASE,
)
_WITH_CHECK_RE = re.compile(r"\bWITH\s+CHECK\b", re.IGNORECASE)


# Migration files where the original CREATE POLICY string is USING-only and
# CANNOT be fixed in place (CLAUDE.md §18 — applied migrations are immutable).
# Runtime policy state has been corrected by follow-up migrations:
#   v395 (delivery_dispatches), v399 (積分 3), v400 (13), v401 (v067 helper 2),
#   v402 (residual 14).
# This baseline excuses the *literal SQL text* in these legacy files. New
# migrations may NOT enter the baseline — they must declare WITH CHECK.
# Drain plan: as legacy migrations get squashed in a future major rebase.
_BASELINE_FILES: frozenset[str] = frozenset(
    {
        "v020_dispatch_rules.py",
        "v052_allergen_management.py",
        "v053_supply_chain_mobile.py",
        "v055_patrol_logs.py",
        "v065_patrol_inspection.py",
        "v067_three_way_match.py",
        "v068_ontology_snapshots.py",
        "v069_open_api_platform.py",
        "v072_mfa_auth.py",
        "v073_rbac_roles.py",
        "v076_role_permission_levels.py",
        "v151_crew_schedule_tables.py",
        "v284_payment_nexus.py",
        "v386_subsidy_programs.py",
        # v402 helper has `with_check=False` branch only called from downgrade()
        # — script doesn't trace call graph，AST walker 只见 op.execute(f"...FOR UPDATE
        # USING ({expr})") 单独触发 violation。downgrade 用 USING-only 是 intentional
        # rollback 行为（恢复 pre-fix state for 回退测试）。Baseline 这一处。
        "v402_fix_residual_update_policy_with_check.py",
    }
)


def _extract_string(node: ast.AST) -> str | None:
    """Best-effort extraction of a string value from a literal AST node.

    Handles plain strings, f-strings (formatted parts replaced by `{}`),
    and `+` concatenation of strings.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append("{}")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _extract_string(node.left)
        right = _extract_string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _is_op_execute(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "execute"
        and isinstance(func.value, ast.Name)
        and func.value.id == "op"
    )


def _downgrade_lines(tree: ast.Module) -> set[int]:
    """Return all line numbers covered by `def downgrade(...)` functions."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            end = getattr(node, "end_lineno", node.lineno)
            for ln in range(node.lineno, end + 1):
                out.add(ln)
    return out


def _check_sql_string(sql: str) -> list[str]:
    """Find FOR UPDATE/ALL CREATE POLICY clauses in `sql` that lack WITH CHECK.

    Returns a list of short snippets — one per violation.
    """
    snippets: list[str] = []
    chunks = _CREATE_POLICY_RE.split(sql)
    if len(chunks) <= 1:
        return snippets
    for body in chunks[1:]:
        head = body.split(";", 1)[0]
        for_match = _FOR_CLAUSE_RE.search(head)
        if not for_match:
            continue
        cmd = for_match.group("cmd").upper()
        if cmd not in ("UPDATE", "ALL"):
            continue
        if _WITH_CHECK_RE.search(head):
            continue
        snippet = "CREATE POLICY" + head.replace("\n", " ")[:140].rstrip()
        snippets.append(snippet)
    return snippets


def find_violations(text: str) -> list[tuple[int, str]]:
    """Return (line_number, snippet) for each upgrade-side violation."""
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [(getattr(e, "lineno", 1) or 1, f"[parse error] {e}")]

    skip = _downgrade_lines(tree)
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_op_execute(node):
            continue
        if node.lineno in skip:
            continue
        if not node.args:
            continue
        sql = _extract_string(node.args[0])
        if sql is None:
            continue
        for snippet in _check_sql_string(sql):
            violations.append((node.lineno, snippet))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--versions-dir",
        default="shared/db-migrations/versions",
        help="Path to alembic versions dir (default: %(default)s)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Ignore the legacy baseline; report every violation (CI optional).",
    )
    args = parser.parse_args(argv)

    versions_dir = Path(args.versions_dir)
    if not versions_dir.is_dir():
        print(f"::error::Versions directory not found: {versions_dir}", file=sys.stderr)
        return 1

    new_violations = 0
    excused_violations = 0
    files_scanned = 0
    for f in sorted(versions_dir.glob("v*.py")):
        if f.name.startswith("__"):
            continue
        files_scanned += 1
        text = f.read_text(encoding="utf-8")
        is_baseline = f.name in _BASELINE_FILES
        for line_no, snippet in find_violations(text):
            if is_baseline and not args.strict:
                excused_violations += 1
                print(
                    f"::warning file={f},line={line_no}::"
                    f"[baseline] UPDATE/ALL policy missing WITH CHECK: {snippet}"
                )
                continue
            new_violations += 1
            print(
                f"::error file={f},line={line_no}::"
                f"FOR UPDATE/ALL policy missing WITH CHECK: {snippet}"
            )

    print(
        f"check_rls_with_check: scanned {files_scanned} migrations, "
        f"{new_violations} new violation(s), "
        f"{excused_violations} baseline-excused"
    )
    return 1 if new_violations else 0


if __name__ == "__main__":
    sys.exit(main())
