"""[Tier1] v412 raw_channel_events migration 结构测试

CH-02.5（issue #377）。覆盖范围：
  1. revision chain 正确（v412 → v411_channel_oauth_tokens）
  2. upgrade SQL 含表 / 索引 / RLS / UNIQUE / CHECK 关键 DDL
  3. downgrade SQL 含 DROP TABLE
  4. ALLOWED_PLATFORMS 与 v411 / canonical 对齐
  5. status CHECK 枚举包含 pending/processed/failed/skipped
  6. JSONB payload + dedup 复合 UNIQUE
  7. 真 PG 反测（opt-in via INTEGRATION_PG_DSN）— 幂等去重 + cross-tenant
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


def _read_v412_source() -> str:
    versions_dir = Path(__file__).parent.parent / "versions"
    return (versions_dir / "v412_raw_channel_events.py").read_text(encoding="utf-8")


def _parse_module_attr(name: str) -> str | None:
    src = _read_v412_source()
    pattern = rf'^{re.escape(name)}\s*[:].*?=\s*"([^"]+)"'
    match = re.search(pattern, src, re.MULTILINE)
    return match.group(1) if match else None


def _parse_module_none_attr(name: str) -> bool:
    src = _read_v412_source()
    pattern = rf'^{re.escape(name)}\s*[:].*?=\s*None\s*$'
    return bool(re.search(pattern, src, re.MULTILINE))


# ─────────────────────────────────────────────────────────────────
# 1. revision chain
# ─────────────────────────────────────────────────────────────────


def test_v412_revision_id():
    revision = _parse_module_attr("revision")
    assert revision == "v412_raw_channel_events", (
        f"v412.revision 错配，实际：{revision}"
    )


def test_v412_down_revision():
    down = _parse_module_attr("down_revision")
    assert down == "v411_channel_oauth_tokens", (
        f"v412.down_revision 应指向 v411_channel_oauth_tokens，实际：{down}"
    )


def test_v412_no_branch_labels():
    assert _parse_module_none_attr("branch_labels"), "v412 不应分支"


# ─────────────────────────────────────────────────────────────────
# 2. upgrade SQL DDL 关键字
# ─────────────────────────────────────────────────────────────────


def test_upgrade_creates_table():
    src = _read_v412_source()
    assert "CREATE TABLE IF NOT EXISTS" in src
    assert '_TABLE = "raw_channel_events"' in src


def test_upgrade_has_dedup_unique():
    """复合 UNIQUE (tenant_id, platform, external_event_id) 是幂等去重的核心。"""
    src = _read_v412_source()
    assert "UNIQUE (tenant_id, platform, external_event_id)" in src, (
        "缺幂等去重 UNIQUE 约束 (tenant_id, platform, external_event_id)"
    )


def test_upgrade_has_platform_check():
    src = _read_v412_source()
    assert "CHECK (platform IN" in src


def test_upgrade_has_status_check():
    """status 必须 CHECK 枚举，4 个值都在。"""
    src = _read_v412_source()
    assert "CHECK (status IN" in src
    for status in ("pending", "processed", "failed", "skipped"):
        assert f"'{status}'" in src, f"status CHECK 缺枚举值 {status!r}"


def test_payload_is_jsonb():
    """payload 字段必须 JSONB（非 TEXT），保证可索引可查。"""
    src = _read_v412_source()
    assert "payload             JSONB NOT NULL" in src


def test_upgrade_enables_rls():
    src = _read_v412_source()
    assert "ENABLE ROW LEVEL SECURITY" in src
    assert "FORCE ROW LEVEL SECURITY" in src


def test_upgrade_has_select_policy():
    src = _read_v412_source()
    assert "rls_{_TABLE}_select" in src
    assert "FOR SELECT" in src


def test_upgrade_has_three_write_policies():
    src = _read_v412_source()
    for action in ("insert", "update", "delete"):
        policy_name = f"rls_{{_TABLE}}_{action}_with_check"
        assert policy_name in src, f"缺 {action.upper()} policy 命名 `{policy_name}`"


def test_insert_policy_only_with_check_no_using():
    """PG 语义：INSERT policy 只能 WITH CHECK，不能含 USING。"""
    src = _read_v412_source()
    insert_blocks = re.findall(
        r"FOR\s+INSERT\s+TO\s+PUBLIC[^;]*",
        src, re.DOTALL | re.IGNORECASE,
    )
    assert insert_blocks, "v412 缺 INSERT policy"
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
    src = _read_v412_source()
    delete_blocks = re.findall(
        r"FOR\s+DELETE\s+TO\s+PUBLIC[^;]*",
        src, re.DOTALL | re.IGNORECASE,
    )
    assert delete_blocks, "v412 缺 DELETE policy"
    for block in delete_blocks:
        upper = block.upper()
        assert "WITH CHECK" not in upper, (
            f"DELETE policy 不能含 WITH CHECK（PG 拒绝）：{block!r}"
        )
        assert "USING" in upper, f"DELETE policy 必须 USING：{block!r}"


def test_update_policy_has_using_and_with_check():
    """UPDATE policy USING + WITH CHECK（v395 修法）。"""
    src = _read_v412_source()
    update_blocks = re.findall(
        r"FOR\s+UPDATE\s+TO\s+PUBLIC[^;]*",
        src, re.DOTALL | re.IGNORECASE,
    )
    assert update_blocks, "v412 缺 UPDATE policy"
    for block in update_blocks:
        upper = block.upper()
        assert "USING" in upper, f"UPDATE policy 必须 USING：{block!r}"
        assert "WITH CHECK" in upper, f"UPDATE policy 必须 WITH CHECK：{block!r}"


def test_upgrade_has_pending_index():
    """重试队列扫描索引 — 必须 partial index WHERE status='pending'。"""
    src = _read_v412_source()
    assert "ix_{_TABLE}_pending" in src
    assert "WHERE status = 'pending'" in src


def test_upgrade_has_received_index():
    """审计排查索引 — (tenant_id, received_at DESC) 倒序。"""
    src = _read_v412_source()
    assert "ix_{_TABLE}_received" in src
    assert "(tenant_id, received_at DESC)" in src


# ─────────────────────────────────────────────────────────────────
# 3. downgrade
# ─────────────────────────────────────────────────────────────────


def test_downgrade_drops_table():
    src = _read_v412_source()
    assert "DROP TABLE IF EXISTS {_TABLE}" in src


# ─────────────────────────────────────────────────────────────────
# 4. ALLOWED_PLATFORMS 跨文件一致性
# ─────────────────────────────────────────────────────────────────


def test_platforms_aligned_with_canonical():
    """v412 _ALLOWED_PLATFORMS 必须等于 delivery_canonical/base.py:ALLOWED_PLATFORMS。"""
    v412_src = _read_v412_source()
    v412_match = re.search(
        r"_ALLOWED_PLATFORMS\s*=\s*\([^)]*?((?:\"[^\"]+\"\s*,?\s*)+)\)",
        v412_src, re.DOTALL,
    )
    assert v412_match
    v412_platforms = set(re.findall(r'"([^"]+)"', v412_match.group(1)))

    canonical_path = (
        Path(__file__).parent.parent.parent
        / "adapters" / "delivery_canonical" / "base.py"
    )
    canonical_src = canonical_path.read_text(encoding="utf-8")
    canonical_match = re.search(
        r"ALLOWED_PLATFORMS\s*=\s*frozenset\s*\(\s*\{([^}]+)\}",
        canonical_src,
    )
    assert canonical_match
    canonical_platforms = set(re.findall(r'"([^"]+)"', canonical_match.group(1)))

    assert v412_platforms == canonical_platforms, (
        f"v412={v412_platforms} 与 canonical={canonical_platforms} 不一致"
    )


def test_platforms_aligned_with_v411():
    """v412 _ALLOWED_PLATFORMS 必须等于 v411_channel_oauth_tokens._ALLOWED_PLATFORMS。"""
    v412_src = _read_v412_source()
    v411_path = (
        Path(__file__).parent.parent / "versions" / "v411_channel_oauth_tokens.py"
    )
    v411_src = v411_path.read_text(encoding="utf-8")

    def _extract(src: str) -> set[str]:
        m = re.search(
            r"_ALLOWED_PLATFORMS\s*=\s*\([^)]*?((?:\"[^\"]+\"\s*,?\s*)+)\)",
            src, re.DOTALL,
        )
        assert m
        return set(re.findall(r'"([^"]+)"', m.group(1)))

    assert _extract(v412_src) == _extract(v411_src), (
        "v412 与 v411 _ALLOWED_PLATFORMS 不一致 — 新增平台两处必须同步"
    )


# ─────────────────────────────────────────────────────────────────
# 5. 真 PG 反测（opt-in via INTEGRATION_PG_DSN）
# ─────────────────────────────────────────────────────────────────


_INTEGRATION_PG_DSN = os.environ.get("INTEGRATION_PG_DSN")
pytestmark_integration = pytest.mark.skipif(
    not _INTEGRATION_PG_DSN,
    reason="INTEGRATION_PG_DSN 未配置，跳过真 PG 反测（opt-in）",
)


@pytestmark_integration
def test_real_pg_dedup_idempotent():
    """同 (tenant_id, platform, external_event_id) 二次 INSERT → ON CONFLICT 跳过。"""
    pytest.skip("待 INTEGRATION_PG_DSN fixture 配置后实施 — 见 issue #377 follow-up")


@pytestmark_integration
def test_real_pg_rls_cross_tenant():
    """tenant_A 设置 GUC 后查不到 tenant_B 的 events。"""
    pytest.skip("待 INTEGRATION_PG_DSN fixture 配置后实施 — 见 issue #377 follow-up")
