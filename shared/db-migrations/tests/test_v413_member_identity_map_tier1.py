"""[Tier1] v413 member_identity_map migration 结构测试

CH-13（issue #393）。覆盖范围：
  1. revision chain 正确（v413 → v412_raw_channel_events）
  2. upgrade SQL 含表 / 索引 / RLS / UNIQUE NULLS NOT DISTINCT / CHECK
  3. identity_type CHECK 枚举完整
  4. confidence CHECK 范围
  5. platform 可空 + 在枚举内
  6. SHA256 hash 字段长度 CHAR(64)
  7. 真 PG 反测（opt-in via INTEGRATION_PG_DSN）— cross-tenant + UNIQUE NULLS NOT DISTINCT
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


def _read_v413_source() -> str:
    versions_dir = Path(__file__).parent.parent / "versions"
    return (versions_dir / "v413_member_identity_map.py").read_text(encoding="utf-8")


def _parse_module_attr(name: str) -> str | None:
    src = _read_v413_source()
    pattern = rf'^{re.escape(name)}\s*[:].*?=\s*"([^"]+)"'
    match = re.search(pattern, src, re.MULTILINE)
    return match.group(1) if match else None


def _parse_module_none_attr(name: str) -> bool:
    src = _read_v413_source()
    pattern = rf'^{re.escape(name)}\s*[:].*?=\s*None\s*$'
    return bool(re.search(pattern, src, re.MULTILINE))


# ─────────────────────────────────────────────────────────────────
# 1. revision chain
# ─────────────────────────────────────────────────────────────────


def test_v413_revision_id():
    revision = _parse_module_attr("revision")
    assert revision == "v413_member_identity_map", (
        f"v413.revision 错配，实际：{revision}"
    )


def test_v413_down_revision():
    """假设 CH-02.5 (v412) 先 merge；若实际反转 → 改 down_revision = v411。"""
    down = _parse_module_attr("down_revision")
    assert down == "v412_raw_channel_events", (
        f"v413.down_revision 应指向 v412_raw_channel_events，实际：{down}"
    )


def test_v413_no_branch_labels():
    assert _parse_module_none_attr("branch_labels"), "v413 不应分支"


# ─────────────────────────────────────────────────────────────────
# 2. upgrade SQL DDL 关键字
# ─────────────────────────────────────────────────────────────────


def test_upgrade_creates_table():
    src = _read_v413_source()
    assert "CREATE TABLE IF NOT EXISTS" in src
    assert '_TABLE = "member_identity_map"' in src


def test_upgrade_unique_uses_nulls_not_distinct():
    """复合 UNIQUE 必须用 NULLS NOT DISTINCT（PG 15+）— 让 platform=NULL 也参与去重。

    若不带 NULLS NOT DISTINCT：phone 类型（platform=NULL）可重复插入相同 hash，
    破坏"同一手机号 = 同一 member"语义。
    """
    src = _read_v413_source()
    assert "UNIQUE NULLS NOT DISTINCT" in src, (
        "缺 NULLS NOT DISTINCT — phone 类型 (platform=NULL) 将重复插入同 hash"
    )
    assert "(tenant_id, identity_type, identity_value_hash, platform)" in src


def test_identity_type_check_complete():
    """identity_type CHECK 枚举必须含 phone / openid / card_no / email。"""
    src = _read_v413_source()
    assert "CHECK (identity_type IN" in src
    for itype in ("phone", "openid", "card_no", "email"):
        assert f"'{itype}'" in src, f"identity_type CHECK 缺 {itype!r}"


def test_platform_check_allows_null():
    """platform CHECK 必须显式允许 NULL（phone/email/card_no 类型 platform=NULL）。"""
    src = _read_v413_source()
    assert "CHECK (platform IS NULL OR platform IN" in src, (
        "platform CHECK 必须 IS NULL OR — 否则 phone 跨平台用例无法存储"
    )


def test_confidence_check_range():
    """confidence 必须 CHECK 在 [0,1]。"""
    src = _read_v413_source()
    assert "CHECK (confidence BETWEEN 0 AND 1)" in src


def test_hash_field_is_char_64():
    """SHA256 hex 必须 CHAR(64) 固定长度，防变长字段索引膨胀。"""
    src = _read_v413_source()
    assert "identity_value_hash     CHAR(64) NOT NULL" in src


def test_upgrade_enables_rls():
    src = _read_v413_source()
    assert "ENABLE ROW LEVEL SECURITY" in src
    assert "FORCE ROW LEVEL SECURITY" in src


def test_upgrade_has_select_policy():
    src = _read_v413_source()
    assert "rls_{_TABLE}_select" in src


def test_upgrade_has_three_write_policies():
    src = _read_v413_source()
    for action in ("insert", "update", "delete"):
        policy_name = f"rls_{{_TABLE}}_{action}_with_check"
        assert policy_name in src, f"缺 {action.upper()} policy 命名 `{policy_name}`"


def test_insert_policy_only_with_check_no_using():
    """PG 语义：INSERT policy 只能 WITH CHECK，不能含 USING。"""
    src = _read_v413_source()
    insert_blocks = re.findall(
        r"FOR\s+INSERT\s+TO\s+PUBLIC[^;]*",
        src, re.DOTALL | re.IGNORECASE,
    )
    assert insert_blocks, "v413 缺 INSERT policy"
    for block in insert_blocks:
        upper = block.upper()
        assert "USING" not in upper, (
            f"INSERT policy 不能含 USING（PG 拒绝）：{block!r}"
        )
        assert "WITH CHECK" in upper, (
            f"INSERT policy 必须 WITH CHECK：{block!r}"
        )


def test_delete_policy_only_using_no_with_check():
    """PG 语义：DELETE policy 只能 USING，不能含 WITH CHECK。"""
    src = _read_v413_source()
    delete_blocks = re.findall(
        r"FOR\s+DELETE\s+TO\s+PUBLIC[^;]*",
        src, re.DOTALL | re.IGNORECASE,
    )
    assert delete_blocks, "v413 缺 DELETE policy"
    for block in delete_blocks:
        upper = block.upper()
        assert "WITH CHECK" not in upper, (
            f"DELETE policy 不能含 WITH CHECK（PG 拒绝）：{block!r}"
        )
        assert "USING" in upper, f"DELETE policy 必须 USING：{block!r}"


def test_update_policy_has_using_and_with_check():
    """UPDATE policy USING + WITH CHECK（v395 修法）。"""
    src = _read_v413_source()
    update_blocks = re.findall(
        r"FOR\s+UPDATE\s+TO\s+PUBLIC[^;]*",
        src, re.DOTALL | re.IGNORECASE,
    )
    assert update_blocks, "v413 缺 UPDATE policy"
    for block in update_blocks:
        upper = block.upper()
        assert "USING" in upper, f"UPDATE policy 必须 USING：{block!r}"
        assert "WITH CHECK" in upper, f"UPDATE policy 必须 WITH CHECK：{block!r}"


def test_upgrade_has_member_index():
    """list_member_identities 反查路径必须有 (tenant_id, member_id) 索引。"""
    src = _read_v413_source()
    assert "ix_{_TABLE}_member" in src
    assert "(tenant_id, member_id)" in src


def test_upgrade_has_hash_lookup_index():
    """resolve() 高频路径必须有 (tenant_id, hash, type) 索引。"""
    src = _read_v413_source()
    assert "ix_{_TABLE}_hash_lookup" in src
    assert "(tenant_id, identity_value_hash, identity_type)" in src


# ─────────────────────────────────────────────────────────────────
# 3. downgrade
# ─────────────────────────────────────────────────────────────────


def test_downgrade_drops_table():
    src = _read_v413_source()
    assert "DROP TABLE IF EXISTS {_TABLE}" in src


# ─────────────────────────────────────────────────────────────────
# 4. 真 PG 反测（opt-in via INTEGRATION_PG_DSN）
# ─────────────────────────────────────────────────────────────────


_INTEGRATION_PG_DSN = os.environ.get("INTEGRATION_PG_DSN")
pytestmark_integration = pytest.mark.skipif(
    not _INTEGRATION_PG_DSN,
    reason="INTEGRATION_PG_DSN 未配置，跳过真 PG 反测（opt-in）",
)


@pytestmark_integration
def test_real_pg_unique_nulls_not_distinct():
    """phone 类型 (platform=NULL) 同 hash 二次 INSERT → ON CONFLICT 触发。"""
    pytest.skip("待 INTEGRATION_PG_DSN fixture 配置后实施 — issue #393 follow-up")


@pytestmark_integration
def test_real_pg_concurrent_upsert_no_duplicate():
    """并发 link 同 (tenant_id, type, hash, platform) → 只产生一行。"""
    pytest.skip("待 INTEGRATION_PG_DSN fixture 配置后实施 — issue #393 follow-up")


@pytestmark_integration
def test_real_pg_rls_cross_tenant():
    """tenant_A 设置 GUC 后查不到 tenant_B 的 identity 映射。"""
    pytest.skip("待 INTEGRATION_PG_DSN fixture 配置后实施 — issue #393 follow-up")
