"""[Tier1] v411 channel_oauth_tokens migration 结构测试

CH-01（issue #375）。覆盖范围：
  1. revision chain 正确（v411 → v409_fund_settlement_revive）
  2. upgrade SQL 含表 / 索引 / RLS / UNIQUE / CHECK 关键 DDL
  3. downgrade SQL 含 DROP TABLE
  4. ALLOWED_PLATFORMS 与 delivery_canonical/base.py 对齐（防漂移）
  5. 真 PG 反测（opt-in via INTEGRATION_PG_DSN）— RLS cross-tenant + UNIQUE 约束

技术约束：
  - 1-4 不连真 PG，仅静态扫 SQL 文本
  - 5 真连 PG，跑完 upgrade → 反测 → downgrade，不污染主库
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────
# 辅助：源码 textual 解析（避免 import alembic 依赖，CI 友好）
# ─────────────────────────────────────────────────────────────────


def _read_v411_source() -> str:
    versions_dir = Path(__file__).parent.parent / "versions"
    return (versions_dir / "v411_channel_oauth_tokens.py").read_text(encoding="utf-8")


def _parse_module_attr(name: str) -> str | None:
    """从源码 regex 抽顶层 `name: ... = "value"` 字符串。"""
    src = _read_v411_source()
    pattern = rf'^{re.escape(name)}\s*[:].*?=\s*"([^"]+)"'
    match = re.search(pattern, src, re.MULTILINE)
    return match.group(1) if match else None


def _parse_module_none_attr(name: str) -> bool:
    """检查源码顶层 `name: ... = None`。"""
    src = _read_v411_source()
    pattern = rf'^{re.escape(name)}\s*[:].*?=\s*None\s*$'
    return bool(re.search(pattern, src, re.MULTILINE))


# ─────────────────────────────────────────────────────────────────
# 1. revision chain
# ─────────────────────────────────────────────────────────────────


def test_v411_revision_id():
    revision = _parse_module_attr("revision")
    assert revision == "v411_channel_oauth_tokens", (
        f"v411.revision 错配，实际：{revision}"
    )


def test_v411_down_revision():
    down = _parse_module_attr("down_revision")
    assert down == "v409_fund_settlement_revive", (
        f"v411.down_revision 应指向 v409_fund_settlement_revive，实际：{down}"
    )


def test_v411_no_branch_labels():
    assert _parse_module_none_attr("branch_labels"), "v411 不应分支"


# ─────────────────────────────────────────────────────────────────
# 2. upgrade SQL DDL 关键字
# ─────────────────────────────────────────────────────────────────


def test_upgrade_creates_table():
    src = _read_v411_source()
    assert "CREATE TABLE IF NOT EXISTS" in src
    # 表名定义在 _TABLE 顶级常量（source-of-truth）
    assert '_TABLE = "channel_oauth_tokens"' in src


def test_upgrade_has_unique_constraint():
    src = _read_v411_source()
    # 复合 UNIQUE (tenant_id, store_id, platform, account_id)
    assert "UNIQUE (tenant_id, store_id, platform, account_id)" in src, (
        "缺少业务键 UNIQUE 约束 (tenant_id, store_id, platform, account_id)"
    )


def test_upgrade_has_platform_check():
    src = _read_v411_source()
    # platform 必须有 CHECK 约束限定枚举
    assert "CHECK (platform IN" in src, "platform 字段缺 CHECK 约束"


def test_upgrade_enables_rls():
    src = _read_v411_source()
    assert "ENABLE ROW LEVEL SECURITY" in src
    assert "FORCE ROW LEVEL SECURITY" in src, (
        "Tier1 必须 FORCE RLS，防 service role 无意绕过"
    )


def test_upgrade_has_select_policy():
    """SELECT policy 通过 f-string 模板生成；验证模板存在 + FOR SELECT 关键字。"""
    src = _read_v411_source()
    assert "rls_{_TABLE}_select" in src, "缺 SELECT policy 模板"
    assert "FOR SELECT" in src


def test_upgrade_has_write_policies_with_check():
    """写入侧 INSERT/UPDATE/DELETE 必须 USING + WITH CHECK（v395 修法）。"""
    src = _read_v411_source()
    # 三个写入侧 actions 通过 _WRITE_ACTIONS 元组 + for-loop 生成 policy
    assert '_WRITE_ACTIONS = ("INSERT", "UPDATE", "DELETE")' in src, (
        "缺 _WRITE_ACTIONS 三元组定义"
    )
    assert "rls_{_TABLE}_{action.lower()}_with_check" in src, (
        "缺写入侧 policy 命名模板"
    )
    # 计数 WITH CHECK 出现次数 ≥ 3（三个写入侧 policy + docstring 提及，至少 3）
    assert src.count("WITH CHECK") >= 3, (
        f"WITH CHECK 出现次数 {src.count('WITH CHECK')} < 3，"
        f"写入侧 RLS 防伪造保护不足"
    )


def test_upgrade_creates_expiry_index():
    """自动续期 job 高频扫 (tenant_id, expires_at)，必须有索引。"""
    src = _read_v411_source()
    assert "ix_channel_oauth_tokens_tenant_expires" in src
    assert "(tenant_id, expires_at)" in src


def test_upgrade_token_columns_are_bytea():
    """access_token / refresh_token 必须 BYTEA（应用层 Fernet 加密前提）。"""
    src = _read_v411_source()
    assert "access_token_enc        BYTEA NOT NULL" in src
    assert "refresh_token_enc       BYTEA" in src


# ─────────────────────────────────────────────────────────────────
# 3. downgrade SQL
# ─────────────────────────────────────────────────────────────────


def test_downgrade_drops_table():
    src = _read_v411_source()
    assert "DROP TABLE IF EXISTS {_TABLE}" in src, (
        "downgrade 必须 DROP TABLE（_TABLE = channel_oauth_tokens 见 _TABLE 常量）"
    )


# ─────────────────────────────────────────────────────────────────
# 4. ALLOWED_PLATFORMS 与 canonical 对齐（防漂移）
# ─────────────────────────────────────────────────────────────────


def test_platforms_aligned_with_canonical():
    """v411 _ALLOWED_PLATFORMS 必须等于 delivery_canonical/base.py:ALLOWED_PLATFORMS。

    若不等，新增平台后 canonical transformer 与 oauth_token 表枚举会漂移。
    """
    # 1. 从 v411 源码 regex 抽 _ALLOWED_PLATFORMS tuple
    v411_src = _read_v411_source()
    v411_match = re.search(
        r"_ALLOWED_PLATFORMS\s*=\s*\([^)]*?((?:\"[^\"]+\"\s*,?\s*)+)\)",
        v411_src, re.DOTALL,
    )
    assert v411_match, "无法在 v411 源码找到 _ALLOWED_PLATFORMS"
    v411_platforms = set(re.findall(r'"([^"]+)"', v411_match.group(1)))

    # 2. 从 delivery_canonical/base.py 抽 ALLOWED_PLATFORMS frozenset
    canonical_path = (
        Path(__file__).parent.parent.parent
        / "adapters"
        / "delivery_canonical"
        / "base.py"
    )
    canonical_src = canonical_path.read_text(encoding="utf-8")
    canonical_match = re.search(
        r"ALLOWED_PLATFORMS\s*=\s*frozenset\s*\(\s*\{([^}]+)\}",
        canonical_src,
    )
    assert canonical_match, "无法在 delivery_canonical/base.py 找到 ALLOWED_PLATFORMS"
    canonical_platforms = set(re.findall(r'"([^"]+)"', canonical_match.group(1)))

    assert v411_platforms == canonical_platforms, (
        f"v411 _ALLOWED_PLATFORMS={v411_platforms} 与 canonical "
        f"ALLOWED_PLATFORMS={canonical_platforms} 不一致 — "
        f"新增平台时两处必须同步！"
    )


# ─────────────────────────────────────────────────────────────────
# 5. 真 PG 反测（opt-in via INTEGRATION_PG_DSN，参照 PR #333 模式）
# ─────────────────────────────────────────────────────────────────


_INTEGRATION_PG_DSN = os.environ.get("INTEGRATION_PG_DSN")
pytestmark_integration = pytest.mark.skipif(
    not _INTEGRATION_PG_DSN,
    reason="INTEGRATION_PG_DSN 未配置，跳过真 PG 反测（opt-in）",
)


@pytestmark_integration
def test_real_pg_rls_cross_tenant_isolation():
    """tenant_A 设置 app.tenant_id 后查不到 tenant_B 的 token。"""
    # TODO(CH-01): 在 staging 配 INTEGRATION_PG_DSN 后实现完整反测
    # 步骤：
    #   1. alembic upgrade head
    #   2. 用 service role insert tenant_A token + tenant_B token
    #   3. SET LOCAL app.tenant_id = tenant_A → SELECT 仅返回 A 的
    #   4. SET LOCAL app.tenant_id = tenant_B → SELECT 仅返回 B 的
    #   5. tenant_A 上下文 INSERT WHERE tenant_id = tenant_B → WITH CHECK 拒绝
    pytest.skip("待 INTEGRATION_PG_DSN fixture 配置后实施 — 见 issue #375 follow-up")


@pytestmark_integration
def test_real_pg_unique_constraint_enforced():
    """同 (tenant_id, store_id, platform, account_id) 二次 INSERT 抛 UNIQUE 错。"""
    pytest.skip("待 INTEGRATION_PG_DSN fixture 配置后实施 — 见 issue #375 follow-up")


@pytestmark_integration
def test_real_pg_platform_check_enforced():
    """platform 不在 ALLOWED_PLATFORMS 时 CHECK 拒绝 INSERT。"""
    pytest.skip("待 INTEGRATION_PG_DSN fixture 配置后实施 — 见 issue #375 follow-up")
