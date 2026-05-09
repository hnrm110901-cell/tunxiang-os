#!/usr/bin/env python3
"""Alembic migration chain integrity check.

Replaces the inline bash heredoc in `.github/workflows/migration-ci.yml`
so the same logic is unit-testable from Python.

Three checks:
  1. No duplicate revision IDs.
  2. No broken chain (every `down_revision` resolves to an existing revision),
     **except** for entries inside the `KNOWN_BROKEN` allow-list — those are
     pre-existing historical debt tracked in `docs/migration-chain-debt.md`.
  3. KNOWN_BROKEN scope guard (PJ.5):
     If a revision `R` declares `down_revision = X` where `X` ∈ KNOWN_BROKEN,
     then `R` itself MUST also be in KNOWN_BROKEN. Otherwise a brand-new
     migration could lean on a known-broken parent and silently propagate
     the breakage downstream. Whitelisted-to-whitelisted links are allowed
     (all participants are legacy debt).

Exit code 0 on pass, 1 on failure.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable


# ── KNOWN_BROKEN allow-lists ───────────────────────────────────────────────
# Pre-existing broken-chain participants split into two roles:
#
#   KNOWN_BROKEN_PARENTS — orphan rev names that are referenced by some
#     ``down_revision`` but never declared by any migration file. These are
#     the actual "missing" links. New migrations may NOT reference them.
#
#   KNOWN_BROKEN_CHILDREN — rev IDs of files that already declare a
#     ``down_revision`` pointing at a KNOWN_BROKEN_PARENTS entry. These are
#     pre-existing legacy debt; their dangling reference is excused.
#     Downstream of these children is normal chain (they chain off real
#     declared revisions), so we do NOT cascade the scope guard transitively.
#
# 2026-05-09 (B'): Both sets drained to empty — the 3 historical dangling
#   refs (v310 → v301_refund_requests / v311 → v310_mv_performance_indexes /
#   v388 → v387_pdpa_compliance) are now repaired with real revision IDs.
#   The scope-guard mechanism is retained as a defensive net so future debt
#   accrual is explicit. See docs/migration-chain-debt.md (debt cleared).
KNOWN_BROKEN_PARENTS: frozenset[str] = frozenset()

KNOWN_BROKEN_CHILDREN: frozenset[str] = frozenset()

# Backwards-compat union — some callers / tests may want the combined view.
KNOWN_BROKEN: frozenset[str] = KNOWN_BROKEN_PARENTS | KNOWN_BROKEN_CHILDREN


# ── parsing ────────────────────────────────────────────────────────────────

# Matches both `revision = "vXXX"` and `revision: str = "vXXX"`.
_REVISION_RE = re.compile(
    r'^revision(?:\s*:\s*[^=]+)?\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE
)
# Matches `down_revision = "vXXX"` and `down_revision: Union[...] = "vXXX"`.
# Down revision can also be None / a tuple, those are skipped here.
_DOWN_REVISION_RE = re.compile(
    r'^down_revision(?:\s*:\s*[^=]+)?\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE
)


def parse_migration_file(text: str) -> tuple[str | None, str | None]:
    """Extract (revision, down_revision) from a migration file's source text.

    Returns (None, None) for files that don't declare a revision.
    `down_revision` may be None for the chain root or for tuple/None forms.
    """
    rev_m = _REVISION_RE.search(text)
    down_m = _DOWN_REVISION_RE.search(text)
    revision = rev_m.group(1) if rev_m else None
    down_revision = down_m.group(1) if down_m else None
    return revision, down_revision


def collect_revisions(versions_dir: Path) -> dict[str, str | None]:
    """Walk ``versions_dir`` and return {revision: down_revision}.

    Files whose revision can't be parsed are skipped. Duplicate revision IDs
    overwrite — duplicate detection is the caller's job (see ``check_chain``).
    """
    out: dict[str, str | None] = {}
    for f in sorted(versions_dir.glob("v*.py")):
        if f.name.startswith("__"):
            continue
        rev, down = parse_migration_file(f.read_text(encoding="utf-8"))
        if rev is not None:
            out[rev] = down
    return out


def collect_revisions_with_duplicates(
    versions_dir: Path,
) -> tuple[dict[str, str | None], list[tuple[str, list[str]]]]:
    """Like :func:`collect_revisions` but also returns duplicate revision IDs.

    Returns (revisions, duplicates) where duplicates is a list of
    ``(revision_id, [filenames...])`` for every revision declared by 2+ files.
    """
    rev_to_files: dict[str, list[str]] = {}
    rev_to_down: dict[str, str | None] = {}
    for f in sorted(versions_dir.glob("v*.py")):
        if f.name.startswith("__"):
            continue
        rev, down = parse_migration_file(f.read_text(encoding="utf-8"))
        if rev is None:
            continue
        rev_to_files.setdefault(rev, []).append(f.name)
        rev_to_down[rev] = down
    duplicates = [(r, files) for r, files in rev_to_files.items() if len(files) > 1]
    # v148 is intentionally double-branched (event_materialized_views + invite_invoice_tables);
    # the legacy duplicate check upstream excluded it. Keep that exception.
    duplicates = [d for d in duplicates if d[0] != "v148"]
    return rev_to_down, duplicates


# ── checks ─────────────────────────────────────────────────────────────────


def check_chain(
    revisions: dict[str, str | None],
    known_broken_parents: Iterable[str] = KNOWN_BROKEN_PARENTS,
    known_broken_children: Iterable[str] = KNOWN_BROKEN_CHILDREN,
) -> tuple[list[str], list[str]]:
    """Run the broken-chain + KNOWN_BROKEN scope checks.

    Returns ``(errors, warnings)``. Empty errors means pass.

    Rules (PJ.5 — narrowed scope vs. PI.1):
      For each rev ``R`` with ``down_revision = D``:

        * If ``D`` is in ``KNOWN_BROKEN_PARENTS`` (i.e. ``D`` is a known
          orphan parent — referenced but never declared):
            - If ``R`` is in ``KNOWN_BROKEN_CHILDREN`` → warning, pre-existing
              tracked debt; excused.
            - Else → ERROR: a new migration is trying to extend a
              known-broken chain by leaning on the orphan parent. This is
              the regression that the PI.1 whitelist failed to catch.

        * Else if ``D`` resolves (in ``revisions``) → OK. (This is the
          common case, including downstream chains that ride on top of
          a ``KNOWN_BROKEN_CHILDREN`` rev — that child IS a real declared
          revision, so its descendants are normal chain.)

        * Else → ERROR: brand-new broken chain (D is unresolved and not
          on the legacy allow-list).

    Why scope only fires on parents (not children): once a legacy child
    like ``v311`` is declared as a real revision, downstream migrations
    chain off a real entity and aren't propagating the orphan reference.
    Cascading the guard transitively would force every migration after
    v311 / v388 / v310 to be added to the allow-list — that defeats the
    point of having a chain check.
    """
    known_parents = frozenset(known_broken_parents)
    known_children = frozenset(known_broken_children)
    errors: list[str] = []
    warnings: list[str] = []

    for rev, down in revisions.items():
        if down is None:
            continue  # chain root
        if down in known_parents:
            if rev in known_children:
                warnings.append(
                    f"Pre-existing broken chain (tracked debt): "
                    f"revision '{rev}' down_revision='{down}'"
                )
            else:
                errors.append(
                    f"Revision '{rev}' has down_revision='{down}' which is "
                    f"a KNOWN_BROKEN orphan parent. New migrations may not "
                    f"extend a known-broken chain by referencing the orphan. "
                    f"Either fix the upstream chain first (preferred — see "
                    f"docs/migration-chain-debt.md), or add '{rev}' to "
                    f"KNOWN_BROKEN_CHILDREN if it is genuinely pre-existing "
                    f"legacy debt."
                )
            continue
        if down in revisions:
            continue  # resolves cleanly
        errors.append(
            f"Broken chain: revision '{rev}' has down_revision='{down}' "
            f"which is not declared by any migration."
        )

    return errors, warnings


# ── CLI entrypoint ─────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--versions-dir",
        default="shared/db-migrations/versions",
        help="Path to the alembic versions directory (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    versions_dir = Path(args.versions_dir)
    if not versions_dir.is_dir():
        print(f"::error::Versions directory not found: {versions_dir}", file=sys.stderr)
        return 1

    revisions, duplicates = collect_revisions_with_duplicates(versions_dir)

    print(f"Found {len(revisions)} unique revisions in {versions_dir}")

    if duplicates:
        print("::error::Duplicate revision IDs found:")
        for rev, files in duplicates:
            print(f"  {rev}: {files}")
        return 1
    print("No duplicate revisions")

    errors, warnings = check_chain(revisions)
    for w in warnings:
        print(f"::warning::{w}")
    for e in errors:
        print(f"::error::{e}")

    if errors:
        print(
            "::error::Chain integrity FAILED. "
            "Pre-existing debt is tracked in docs/migration-chain-debt.md; "
            "new breakage is not allowed."
        )
        return 1

    print(
        f"Chain integrity OK ({len(warnings)} pre-existing warnings, "
        f"{len(revisions)} revisions checked)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
