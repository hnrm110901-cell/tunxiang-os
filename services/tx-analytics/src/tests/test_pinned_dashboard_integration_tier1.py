"""Tier 1 — S4-04 PR2.B-2 driven integration test 真 PG 反测

issue #291 收尾：mock-based 单测覆盖不了 RLS USING / WITH CHECK / FIFO 真行为。
本文件用真 PG 连接验证三组关键反测：

  1. FIFO 行为：连续 add 21 条 → 第 1 条被软删，list 只返 PIN_LIMIT_PER_TENANT=20 条
  2. RLS 跨 tenant 隔离：tenant=A add → tenant=B list 看不到（USING 子句生效）
  3. WITH CHECK 反测：app.tenant_id=A 但 INSERT 行 tenant_id=B → IntegrityError
     （v403 INSERT/UPDATE/DELETE 三策略 WITH CHECK 子句生效，防写入端跨租户伪造）

Opt-in 触发：
  INTEGRATION_PG_DSN=postgresql+asyncpg://user:pass@host/db pytest <this_file>

未设 INTEGRATION_PG_DSN 时全部 skip → CI 自然忽略，本地有库的 dev 可手跑。

前置假设：
  - DSN 指向已 alembic upgrade head 的库（v403 dashboard_pinned 表 + RLS 已建）
  - DSN 用户拥有非 BYPASSRLS 角色（否则 RLS 不生效，跨租户测试失效）
  - 测试前后用 fixture 清空 dashboard_pinned 表（用 row_security=off / 直接 DELETE）

D2b'（2026-05-11）：DSN/skipif/tenant GUC helper 切到 shared.test_utils.integration_pg；
module-scoped engine + 多 session + cross-tenant commit 模式与 #418 shared fixture
不兼容，故 engine/session/cleanup 仍滚自己的。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.test_utils.integration_pg import (
    INTEGRATION_PG_DSN,
    requires_integration_pg,
    set_tenant_guc,
)

from ..services.pinned_dashboard import (
    PIN_LIMIT_PER_TENANT,
    add_pin,
    list_pins,
    remove_pin,
)

pytestmark = requires_integration_pg


_TABLE = "dashboard_pinned"
_TENANT_A = str(uuid.uuid4())
_TENANT_B = str(uuid.uuid4())
_USER_A1 = str(uuid.uuid4())
_USER_B1 = str(uuid.uuid4())

_SAMPLE_SURFACE = {
    "version": "0.8",
    "surface": {
        "id": "card-1",
        "type": "card",
        "props": {"title": "本周营收", "severity": "info"},
    },
}


# ─────────────── fixtures ───────────────


@pytest.fixture(scope="module")
def engine():
    """模块级 engine — 复用连接池避开多次 handshake。"""
    eng = create_async_engine(INTEGRATION_PG_DSN, echo=False, future=True)
    yield eng
    # teardown: dispose 由 pytest-asyncio 间接处理；这里 sync 调用避免 await 嵌套


@pytest.fixture(scope="module")
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _open_session_with_tenant(
    session_factory, tenant_id: str
) -> AsyncSession:
    """开 session + 注入 app.tenant_id（mimic get_db_with_tenant 行为）。"""
    session = session_factory()
    await set_tenant_guc(session, tenant_id)
    return session


@pytest.fixture(autouse=True)
async def _cleanup_table(engine):
    """每个测试前后清空 dashboard_pinned（用 row_security=off 绕 RLS 真删）。"""
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL row_security = off"))
        await conn.execute(text(f"DELETE FROM {_TABLE}"))
    yield
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL row_security = off"))
        await conn.execute(text(f"DELETE FROM {_TABLE}"))


# ─────────────── 1. FIFO 行为 ───────────────


class TestFifoBehaviorTier1:
    """连续 add 超 PIN_LIMIT_PER_TENANT 条 → 最旧软删，list 只返上限条。"""

    @pytest.mark.asyncio
    async def test_21st_pin_evicts_first(self, session_factory):
        """店长一天连续 Pin 21 条洞察 → 第 1 条（最旧）被软删，list 返 20 条。"""
        # add 21 条
        first_pin_id = None
        async with await _open_session_with_tenant(session_factory, _TENANT_A) as s:
            for i in range(PIN_LIMIT_PER_TENANT + 1):
                item = await add_pin(
                    s,
                    tenant_id=_TENANT_A,
                    pinner_user_id=_USER_A1,
                    surface_snapshot={**_SAMPLE_SURFACE, "i": i},
                )
                if i == 0:
                    first_pin_id = item.pin_id
            await s.commit()

        # list 必须返 20 条且第 1 条不在内
        async with await _open_session_with_tenant(session_factory, _TENANT_A) as s:
            pins = await list_pins(s, _TENANT_A)
        assert len(pins) == PIN_LIMIT_PER_TENANT, (
            f"FIFO 上限失效：返 {len(pins)} 条 vs 期望 {PIN_LIMIT_PER_TENANT}"
        )
        assert all(p.pin_id != first_pin_id for p in pins), (
            "FIFO 软删失效：第 1 条仍在 list 中"
        )


# ─────────────── 2. RLS 跨 tenant 隔离 ───────────────


class TestRlsCrossTenantIsolationTier1:
    """tenant=A Pin → tenant=B 完全看不到（USING 子句生效）。"""

    @pytest.mark.asyncio
    async def test_tenant_a_pin_invisible_to_tenant_b(self, session_factory):
        """徐记海鲜（A）店长 Pin 一条洞察 → 其他餐厅（B）店长 list 看不到。"""
        async with await _open_session_with_tenant(session_factory, _TENANT_A) as s:
            await add_pin(
                s,
                tenant_id=_TENANT_A,
                pinner_user_id=_USER_A1,
                surface_snapshot={**_SAMPLE_SURFACE, "owner": "tenant-A"},
            )
            await s.commit()

        async with await _open_session_with_tenant(session_factory, _TENANT_B) as s:
            pins_b = await list_pins(s, _TENANT_B)
        assert pins_b == [], (
            "RLS USING 失效：tenant=B list 返了 tenant=A 的 Pin —— 严重数据泄露"
        )

        # tenant=A 自己 list 仍能看到
        async with await _open_session_with_tenant(session_factory, _TENANT_A) as s:
            pins_a = await list_pins(s, _TENANT_A)
        assert len(pins_a) == 1
        assert pins_a[0].surface_snapshot["owner"] == "tenant-A"

    @pytest.mark.asyncio
    async def test_cross_tenant_remove_returns_false(self, session_factory):
        """tenant=A 的 Pin 被 tenant=B 调 remove → RLS 阻挡 → rowcount=0 → False（不抛异常）。"""
        async with await _open_session_with_tenant(session_factory, _TENANT_A) as s:
            item = await add_pin(
                s,
                tenant_id=_TENANT_A,
                pinner_user_id=_USER_A1,
                surface_snapshot=_SAMPLE_SURFACE,
            )
            await s.commit()

        async with await _open_session_with_tenant(session_factory, _TENANT_B) as s:
            ok = await remove_pin(s, tenant_id=_TENANT_B, pin_id=item.pin_id)
            await s.commit()
        assert ok is False, (
            "跨 tenant remove 必须返 False（RLS 阻挡可见性 → rowcount=0）"
        )

        # tenant=A 自己的 Pin 不应被影响
        async with await _open_session_with_tenant(session_factory, _TENANT_A) as s:
            pins_a = await list_pins(s, _TENANT_A)
        assert len(pins_a) == 1, "原 tenant 的 Pin 不可被跨 tenant 删除"


# ─────────────── 3. WITH CHECK 反测 ───────────────


class TestRlsWithCheckTier1:
    """v403 INSERT/UPDATE/DELETE 三策略 WITH CHECK 子句 — 防写入端跨租户伪造。

    场景：app.tenant_id=A 的 session 偷偷 INSERT 一条 tenant_id=B 的行 → 必须被 PG 拒。
    （RLS USING 只管"读不到"，WITH CHECK 才管"写不进"。v391 早期漏写 WITH CHECK 被
    PR #139 §19 验证发现，v395 全表补，v403 从一开始就带。）
    """

    @pytest.mark.asyncio
    async def test_insert_other_tenant_id_violates_with_check(self, session_factory):
        """app.tenant_id=A 的 session INSERT tenant_id=B → IntegrityError 拒。"""
        async with await _open_session_with_tenant(session_factory, _TENANT_A) as s:
            with pytest.raises((IntegrityError, ProgrammingError)) as exc_info:
                # 直接走 raw SQL 而非 add_pin（service 层的 tenant_id 参数等于 app.tenant_id，
                # 测不到伪造场景；这里手动构造攻击 payload）
                await s.execute(
                    text(
                        """
                        INSERT INTO dashboard_pinned (
                            tenant_id, pinner_user_id, surface_snapshot
                        ) VALUES (
                            :tenant_id::uuid, :pinner_user_id::uuid, :surface::jsonb
                        )
                        """
                    ),
                    {
                        "tenant_id": _TENANT_B,  # 伪造：与 app.tenant_id 不一致
                        "pinner_user_id": _USER_A1,
                        "surface": '{"v": "evil"}',
                    },
                )
                await s.commit()

            # PG 错误信息含 "row-level security policy" 字样
            assert "row-level security" in str(exc_info.value).lower() or \
                "rls" in str(exc_info.value).lower(), (
                f"未触发 WITH CHECK；实际异常：{exc_info.value}"
            )

        # 确认表里确实没多出 evil 行（事务已 rollback）
        async with await _open_session_with_tenant(session_factory, _TENANT_B) as s:
            pins_b = await list_pins(s, _TENANT_B)
        assert pins_b == [], "WITH CHECK 失效：伪造的 tenant=B 行写入成功"
