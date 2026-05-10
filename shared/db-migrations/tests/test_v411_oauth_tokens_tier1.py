"""[Tier1] v411 channel_oauth_tokens migration 结构测试

CH-01（issue #375）。覆盖范围：
  1. revision chain 正确（v411 → v409_fund_settlement_revive）
  2. upgrade SQL 含表 / 索引 / RLS / UNIQUE / CHECK 关键 DDL
  3. downgrade SQL 含 DROP TABLE
  4. ALLOWED_PLATFORMS 与 delivery_canonical/base.py 对齐（防漂移）
  5. 真 PG 反测（opt-in via INTEGRATION_PG_DSN）— RLS cross-tenant + UNIQUE 约束

技术约束：
  - 1-4 不连真 PG，仅静态扫 SQL 文本
  - 5 真连 PG，事务 rollback 隔离（fixture 见 conftest.py:integration_pg_session）
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text


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


def test_upgrade_has_three_write_policies():
    """写入侧 INSERT/UPDATE/DELETE 各有独立 policy，命名一致。"""
    src = _read_v411_source()
    for action in ("insert", "update", "delete"):
        policy_name = f"rls_{{_TABLE}}_{action}_with_check"
        assert policy_name in src, (
            f"缺 {action.upper()} policy 命名 `{policy_name}`"
        )


def test_insert_policy_only_with_check_no_using():
    """PG 语义：INSERT policy 只能 WITH CHECK，不能含 USING。

    根因：USING 是行筛选（SELECT/UPDATE/DELETE 用），INSERT 没有"已存在的行"
    可筛选；硬塞 USING 会导致 `only WITH CHECK expression allowed for INSERT`，
    fresh PG `alembic upgrade head` 100% 失败。
    """
    src = _read_v411_source()
    # 抓所有 `FOR INSERT TO PUBLIC` 之后到下一个 `;` 的 policy 块文本
    insert_blocks = re.findall(
        r"FOR\s+INSERT\s+TO\s+PUBLIC[^;]*",
        src, re.DOTALL | re.IGNORECASE,
    )
    assert insert_blocks, (
        "v411 缺 INSERT policy（应有 `FOR INSERT TO PUBLIC ...`）— "
        "若用 f-string 模板生成，此测试需配合 impl 改成显式 INSERT 块"
    )
    for block in insert_blocks:
        upper = block.upper()
        assert "USING" not in upper, (
            f"INSERT policy 不能含 USING（PG 拒绝）：{block!r}"
        )
        assert "WITH CHECK" in upper, (
            f"INSERT policy 必须 WITH CHECK：{block!r}"
        )


def test_delete_policy_only_using_no_with_check():
    """PG 语义：DELETE policy 只能 USING，不能含 WITH CHECK。

    根因：WITH CHECK 是写入校验（INSERT/UPDATE 后行的合法性），DELETE 不写入
    新行；硬塞 WITH CHECK 会导致 `WITH CHECK cannot be applied to DELETE`。
    """
    src = _read_v411_source()
    delete_blocks = re.findall(
        r"FOR\s+DELETE\s+TO\s+PUBLIC[^;]*",
        src, re.DOTALL | re.IGNORECASE,
    )
    assert delete_blocks, "v411 缺 DELETE policy"
    for block in delete_blocks:
        upper = block.upper()
        assert "WITH CHECK" not in upper, (
            f"DELETE policy 不能含 WITH CHECK（PG 拒绝）：{block!r}"
        )
        assert "USING" in upper, (
            f"DELETE policy 必须 USING（限定可删行）：{block!r}"
        )


def test_update_policy_has_using_and_with_check():
    """PG 语义：UPDATE policy USING + WITH CHECK 双重保护（v395 修法）。

    USING 限定可读/可改的旧行，WITH CHECK 限定改后新行属性。
    """
    src = _read_v411_source()
    update_blocks = re.findall(
        r"FOR\s+UPDATE\s+TO\s+PUBLIC[^;]*",
        src, re.DOTALL | re.IGNORECASE,
    )
    assert update_blocks, "v411 缺 UPDATE policy"
    for block in update_blocks:
        upper = block.upper()
        assert "USING" in upper, f"UPDATE policy 必须 USING：{block!r}"
        assert "WITH CHECK" in upper, f"UPDATE policy 必须 WITH CHECK：{block!r}"


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
# 5. 真 PG 反测（opt-in via INTEGRATION_PG_DSN，fixture 见 conftest.py）
# ─────────────────────────────────────────────────────────────────
#
# 共用 fixture：
#   - integration_pg_session  事务隔离 session（teardown 自动 rollback）
#   - set_tenant_guc          设 app.tenant_id GUC（事务级）
#
# 未配置 DSN 时 fixture 自身 pytest.skip — 不污染 default 测试套件。


_INSERT_TOKEN_SQL = text("""
    INSERT INTO channel_oauth_tokens
        (tenant_id, store_id, platform, account_id,
         access_token_enc, expires_at)
    VALUES (:tid, :sid, :platform, :account_id,
            :token_data, NOW() + INTERVAL '1 day')
""")


async def test_real_pg_rls_cross_tenant_isolation(
    integration_pg_session, set_tenant_guc,
):
    """tenant_A 设置 app.tenant_id 后查不到 tenant_B 的 token；
    跨租户 INSERT 被 WITH CHECK 拒绝。
    """
    session = integration_pg_session
    tenant_a, tenant_b = uuid4(), uuid4()
    store_id = uuid4()

    # tenant_a 上下文写 A 的 token
    await set_tenant_guc(session, tenant_a)
    await session.execute(_INSERT_TOKEN_SQL, {
        "tid": str(tenant_a), "sid": str(store_id),
        "platform": "meituan", "account_id": "POI_A",
        "token_data": b"A_encrypted_token",
    })

    # tenant_b 上下文写 B 的 token
    await set_tenant_guc(session, tenant_b)
    await session.execute(_INSERT_TOKEN_SQL, {
        "tid": str(tenant_b), "sid": str(store_id),
        "platform": "meituan", "account_id": "POI_B",
        "token_data": b"B_encrypted_token",
    })

    # tenant_a 视角只看到 A
    await set_tenant_guc(session, tenant_a)
    rows = (await session.execute(
        text("SELECT account_id FROM channel_oauth_tokens ORDER BY account_id")
    )).scalars().all()
    assert rows == ["POI_A"], f"tenant_a 应只看到 POI_A，实际：{rows}"

    # tenant_b 视角只看到 B
    await set_tenant_guc(session, tenant_b)
    rows = (await session.execute(
        text("SELECT account_id FROM channel_oauth_tokens ORDER BY account_id")
    )).scalars().all()
    assert rows == ["POI_B"], f"tenant_b 应只看到 POI_B，实际：{rows}"

    # 跨租户写：tenant_a 上下文 INSERT tenant_id=tenant_b → WITH CHECK 拒绝
    await set_tenant_guc(session, tenant_a)
    with pytest.raises(Exception) as exc_info:
        await session.execute(_INSERT_TOKEN_SQL, {
            "tid": str(tenant_b), "sid": str(store_id),
            "platform": "eleme", "account_id": "EVADE_001",
            "token_data": b"evade",
        })
    err = str(exc_info.value).lower()
    assert "policy" in err or "row-level" in err or "with check" in err, (
        f"应抛 RLS WITH CHECK 错误，实际：{exc_info.value}"
    )


async def test_real_pg_unique_constraint_enforced(
    integration_pg_session, set_tenant_guc,
):
    """同 (tenant_id, store_id, platform, account_id) 二次 INSERT 抛 UNIQUE 错。"""
    session = integration_pg_session
    tenant = uuid4()
    store = uuid4()

    await set_tenant_guc(session, tenant)
    await session.execute(_INSERT_TOKEN_SQL, {
        "tid": str(tenant), "sid": str(store),
        "platform": "meituan", "account_id": "POI_DUP",
        "token_data": b"first",
    })

    # 二次 INSERT 同业务键
    with pytest.raises(Exception) as exc_info:
        await session.execute(_INSERT_TOKEN_SQL, {
            "tid": str(tenant), "sid": str(store),
            "platform": "meituan", "account_id": "POI_DUP",
            "token_data": b"second",
        })
    err = str(exc_info.value).lower()
    assert "unique" in err or "duplicate" in err, (
        f"应抛 UNIQUE 约束错误，实际：{exc_info.value}"
    )


async def test_real_pg_platform_check_enforced(
    integration_pg_session, set_tenant_guc,
):
    """platform 不在 ALLOWED_PLATFORMS 时 CHECK 拒绝 INSERT。"""
    session = integration_pg_session
    tenant = uuid4()
    store = uuid4()

    await set_tenant_guc(session, tenant)
    with pytest.raises(Exception) as exc_info:
        await session.execute(_INSERT_TOKEN_SQL, {
            "tid": str(tenant), "sid": str(store),
            "platform": "tiktok_us",  # 不在 ALLOWED_PLATFORMS
            "account_id": "POI_X", "token_data": b"x",
        })
    err = str(exc_info.value).lower()
    assert "check" in err or "constraint" in err, (
        f"应抛 platform CHECK 错误，实际：{exc_info.value}"
    )
