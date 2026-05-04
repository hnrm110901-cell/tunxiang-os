"""Tier 1 — KNOWN_BROKEN 白名单作用域守门（PJ.5）

Background
----------
PI.1 给 ``.github/workflows/migration-ci.yml`` 加了 ``KNOWN_BROKEN`` 白名单
让 CI 容忍 main 上既存 3 处断链（``v301_refund_requests`` /
``v310_mv_performance_indexes`` / ``v387_pdpa_compliance``）。

CodeRabbit post-merge 发现作用域过宽：白名单只判断"该 down_revision 是否
落入白名单"，不判断"引用该断链的 child 是否是新增的"。后果：

  下个 PR 写 ``down_revision = "v301_refund_requests"`` 也会被误判为
  pre-existing，silent pass。坏链进一步扩散。

修复（``scripts/check_alembic_chain.py``）
------------------------------------------
KNOWN_BROKEN 拆成两组：
  KNOWN_BROKEN_PARENTS — 孤儿父 rev 名（被引用但无文件声明）；
  KNOWN_BROKEN_CHILDREN — 已经引用孤儿父的 child rev ID（v310/v311/v388）。

新规则：若 R.down_revision ∈ KNOWN_BROKEN_PARENTS 但 R.revision ∉
KNOWN_BROKEN_CHILDREN → fail。豁免只覆盖"既存的孤儿引用"，新 PR 想再
引用孤儿父 → 必须 fail（污染传播保护）。

注意：不级联到 child 的下游。一旦 child 自己是真 declared revision，
其后续 chain 是正常的（chain off real rev），毋须扩散白名单。

本测试覆盖 4 主场景 + 数个守门：
  1. 现状：白名单 rev 自身断链 → pass（豁免有效）
  2. 新 rev 引用孤儿父 → fail（污染传播保护）
  3. 白名单 child 与孤儿父互链 → pass（历史遗留 OK）
  4. 普通连续 chain 无问题 → pass

不依赖真 alembic env、不依赖 DB；用 tmp_path 构造假 migration 树。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scripts.check_alembic_chain import (
    KNOWN_BROKEN,
    KNOWN_BROKEN_CHILDREN,
    KNOWN_BROKEN_PARENTS,
    check_chain,
    collect_revisions,
    collect_revisions_with_duplicates,
)


# ─── helpers ───────────────────────────────────────────────────────────────


def _write_migration(
    versions_dir: Path,
    revision: str,
    down_revision: str | None,
    *,
    typed: bool = True,
    filename: str | None = None,
) -> Path:
    """Drop a stub alembic migration into ``versions_dir``.

    ``typed=True`` writes the alembic 1.13+ ``revision: str = "..."`` form;
    ``typed=False`` writes the older bare-assign form. We exercise both
    because the workflow originally only matched one of them.
    """
    if typed:
        rev_line = f'revision: str = "{revision}"'
        down_line = (
            f'down_revision: Union[str, Sequence[str], None] = "{down_revision}"'
            if down_revision is not None
            else "down_revision: Union[str, Sequence[str], None] = None"
        )
    else:
        rev_line = f'revision = "{revision}"'
        down_line = (
            f'down_revision = "{down_revision}"' if down_revision is not None else "down_revision = None"
        )

    name = filename or f"{revision}_stub.py"
    p = versions_dir / name
    p.write_text(
        textwrap.dedent(
            f"""\
            \"\"\"stub migration {revision}\"\"\"
            from typing import Sequence, Union

            {rev_line}
            {down_line}

            def upgrade() -> None:
                pass

            def downgrade() -> None:
                pass
            """
        ),
        encoding="utf-8",
    )
    return p


# ─── scenario 1: pre-existing self-broken whitelisted rev → pass ──────────


def test_scenario_pre_existing_self_break_is_excused(tmp_path: Path) -> None:
    """白名单 rev 自身 down_revision 指向不存在的父 → 豁免（pre-existing 警告，不 fail）。"""
    versions = tmp_path / "versions"
    versions.mkdir()

    # Real-world shape: v310 (whitelisted child) points at orphan
    # v301_refund_requests (whitelisted parent).
    _write_migration(versions, "v309", down_revision=None)
    _write_migration(versions, "v310", down_revision="v301_refund_requests", typed=False)

    revisions = collect_revisions(versions)
    errors, warnings = check_chain(revisions)

    assert errors == [], f"unexpected errors: {errors}"
    assert any("v310" in w and "v301_refund_requests" in w for w in warnings), (
        f"expected pre-existing warning for v310 → v301_refund_requests, got: {warnings}"
    )


# ─── scenario 2: NEW rev references whitelisted rev → MUST FAIL ───────────


def test_scenario_new_rev_referencing_whitelist_fails(tmp_path: Path) -> None:
    """新 rev (不在白名单) 把 down_revision 指向 KNOWN_BROKEN → fail。

    这是 PJ.5 修复的核心：CodeRabbit 发现的污染传播路径。
    """
    versions = tmp_path / "versions"
    versions.mkdir()

    # v500 is brand-new (not in KNOWN_BROKEN) and tries to chain off
    # v301_refund_requests (whitelisted orphan parent). Must be rejected.
    _write_migration(versions, "v500_new_pollutant", down_revision="v301_refund_requests")

    revisions = collect_revisions(versions)
    errors, warnings = check_chain(revisions)

    assert any(
        "v500_new_pollutant" in e and "v301_refund_requests" in e and "KNOWN_BROKEN" in e
        for e in errors
    ), (
        f"expected scope-guard error for v500_new_pollutant → v301_refund_requests, "
        f"got errors={errors} warnings={warnings}"
    )


def test_scenario_downstream_of_legacy_child_is_normal_chain(tmp_path: Path) -> None:
    """白名单 child 自己是真 declared revision → 其下游是正常 chain，不级联豁免。

    e.g. v311 在 KNOWN_BROKEN_CHILDREN（因为它已经 references 孤儿
    ``v310_mv_performance_indexes``）。但 v311 本身是 declared rev，所以
    NEW v600 down_revision="v311" 是 OK 的（chain off real rev）。

    这条很重要：否则白名单要级联整个下游链，无穷扩散。
    """
    versions = tmp_path / "versions"
    versions.mkdir()

    # v311 itself is a real declared revision (and a whitelisted child).
    _write_migration(versions, "v311", down_revision="v310_mv_performance_indexes")
    # NEW v600 chains off v311. v311 is a real rev, so this is normal chain — pass.
    _write_migration(versions, "v600_legitimate_downstream", down_revision="v311")

    revisions = collect_revisions(versions)
    errors, warnings = check_chain(revisions)

    assert errors == [], (
        f"downstream of declared child must pass, got errors: {errors}"
    )
    # The only warning should be the v311 → orphan-parent edge.
    assert any("v311" in w and "v310_mv_performance_indexes" in w for w in warnings), (
        f"expected pre-existing warning for v311, got: {warnings}"
    )


# ─── scenario 3: whitelisted ↔ whitelisted links → pass ───────────────────


def test_scenario_whitelist_to_whitelist_link_is_allowed(tmp_path: Path) -> None:
    """白名单 rev 之间互相链接允许（都是历史遗留 debt）。

    e.g. v311 → v310_mv_performance_indexes (both ∈ KNOWN_BROKEN) → 只报 warning。
    v310 → v301_refund_requests (both ∈ KNOWN_BROKEN) → 只报 warning。
    """
    versions = tmp_path / "versions"
    versions.mkdir()

    # All three legacy edges; none of these are "new" so all should be excused.
    _write_migration(versions, "v310", down_revision="v301_refund_requests", typed=False)
    _write_migration(versions, "v311", down_revision="v310_mv_performance_indexes")
    _write_migration(versions, "v388", down_revision="v387_pdpa_compliance")

    revisions = collect_revisions(versions)
    errors, warnings = check_chain(revisions)

    assert errors == [], f"whitelist→whitelist must not error, got: {errors}"
    assert len(warnings) == 3, (
        f"expected exactly 3 pre-existing warnings, got {len(warnings)}: {warnings}"
    )


# ─── scenario 4: clean chain → pass ───────────────────────────────────────


def test_scenario_clean_chain_passes(tmp_path: Path) -> None:
    """普通连续 chain 没有 KNOWN_BROKEN 参与 → 全绿无任何 error/warning。"""
    versions = tmp_path / "versions"
    versions.mkdir()

    _write_migration(versions, "v100", down_revision=None)
    _write_migration(versions, "v101", down_revision="v100")
    _write_migration(versions, "v102", down_revision="v101")
    _write_migration(versions, "v103", down_revision="v102")

    revisions = collect_revisions(versions)
    errors, warnings = check_chain(revisions)

    assert errors == [], f"clean chain must pass, got errors: {errors}"
    assert warnings == [], f"clean chain must produce no warnings, got: {warnings}"


# ─── auxiliary: brand-new orphan parent (not in whitelist) still fails ────


def test_scenario_new_orphan_parent_still_fails(tmp_path: Path) -> None:
    """完全新出现的孤儿父 revision (不在白名单) → fail（旧规则没退化）。"""
    versions = tmp_path / "versions"
    versions.mkdir()

    _write_migration(versions, "v700_orphan_consumer", down_revision="v699_does_not_exist")

    revisions = collect_revisions(versions)
    errors, _ = check_chain(revisions)

    assert any(
        "v700_orphan_consumer" in e and "v699_does_not_exist" in e for e in errors
    ), f"new orphan parent should fail with error, got: {errors}"


# ─── auxiliary: KNOWN_BROKEN constant sanity ──────────────────────────────


def test_known_broken_parents_match_documented_orphans() -> None:
    """KNOWN_BROKEN_PARENTS 必须严格等于 docs/migration-chain-debt.md 里追踪的 3 处孤儿父。

    严格相等：多了说明有未文档化的债；少了说明 CI 可能漏放过既存断链。
    """
    expected_orphan_parents = {
        "v301_refund_requests",
        "v310_mv_performance_indexes",
        "v387_pdpa_compliance",
    }
    assert set(KNOWN_BROKEN_PARENTS) == expected_orphan_parents, (
        f"KNOWN_BROKEN_PARENTS drift vs docs/migration-chain-debt.md: "
        f"missing={expected_orphan_parents - set(KNOWN_BROKEN_PARENTS)}, "
        f"extra={set(KNOWN_BROKEN_PARENTS) - expected_orphan_parents}"
    )


def test_known_broken_children_match_main_baseline() -> None:
    """KNOWN_BROKEN_CHILDREN 必须严格等于 main 上已经引用孤儿父的 child rev ID。

    扫一遍 shared/db-migrations/versions 真实文件，确认白名单孩子集合与磁盘吻合。
    若新增/删减引用孤儿的文件，需同步更新 KNOWN_BROKEN_CHILDREN，否则 CI 红。
    """
    versions_dir = (
        Path(__file__).resolve().parents[4] / "shared" / "db-migrations" / "versions"
    )
    if not versions_dir.is_dir():
        pytest.skip(f"versions dir not present in this checkout: {versions_dir}")

    revisions = collect_revisions(versions_dir)
    actual_children = {
        rev for rev, down in revisions.items() if down in KNOWN_BROKEN_PARENTS
    }
    assert set(KNOWN_BROKEN_CHILDREN) == actual_children, (
        f"KNOWN_BROKEN_CHILDREN drift vs disk: "
        f"missing={actual_children - set(KNOWN_BROKEN_CHILDREN)}, "
        f"extra={set(KNOWN_BROKEN_CHILDREN) - actual_children}"
    )


def test_known_broken_union_is_disjoint_partition() -> None:
    """KNOWN_BROKEN union helper 应等于 PARENTS ∪ CHILDREN，且两集合不相交。"""
    assert KNOWN_BROKEN == KNOWN_BROKEN_PARENTS | KNOWN_BROKEN_CHILDREN
    assert (KNOWN_BROKEN_PARENTS & KNOWN_BROKEN_CHILDREN) == frozenset(), (
        f"a rev cannot be both an orphan parent and a declared child: "
        f"{KNOWN_BROKEN_PARENTS & KNOWN_BROKEN_CHILDREN}"
    )


# ─── auxiliary: duplicate detection still works ───────────────────────────


def test_duplicate_revisions_detected(tmp_path: Path) -> None:
    """``collect_revisions_with_duplicates`` 仍能识别重复 revision (v148 例外)。"""
    versions = tmp_path / "versions"
    versions.mkdir()

    _write_migration(versions, "v200", down_revision="v199", filename="v200_a.py")
    _write_migration(versions, "v200", down_revision="v199", filename="v200_b.py")

    _, dups = collect_revisions_with_duplicates(versions)
    assert any(rev == "v200" for rev, _ in dups), (
        f"duplicate v200 should be flagged, got: {dups}"
    )


def test_v148_double_branch_is_intentionally_allowed(tmp_path: Path) -> None:
    """v148 故意双分支（event_materialized_views + invite_invoice_tables），不报重复。"""
    versions = tmp_path / "versions"
    versions.mkdir()

    _write_migration(versions, "v148", down_revision="v147", filename="v148_event.py")
    _write_migration(versions, "v148", down_revision="v147", filename="v148_invite.py")

    _, dups = collect_revisions_with_duplicates(versions)
    assert dups == [], f"v148 double-branch should not be flagged, got: {dups}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
