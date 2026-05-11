"""Tier 1 — S4-02 PR2.D 真 PG 集成反测（opt-in）

issue #289 收尾：v404/v405/v406 静态扫描覆盖不了视图运行时行为。本文件用真 PG
连接验证四组关键反测：

  1. security_invoker=on 真生效：tenant_A 写 mv_daily_settlement → 切 tenant_B
     查 reports.daily_revenue 看不到（视图 RLS 跟调用者 app.tenant_id）
  2. 视图 WHERE 过滤真生效：插 status='open' + 'closed' 各 1 条 → 视图只见 closed
  3. 敏感字段在 runtime 不暴露：SELECT * FROM reports.daily_revenue 返回的列
     不含 cash_discrepancy_fen / pending_items（v404 设计的脱敏字段）
  4. tx_nlq_readonly role 权限边界：
     a) SET ROLE 后 SELECT FROM mv_daily_settlement → ProgrammingError（REVOKE public 生效）
     b) SET ROLE 后 INSERT INTO reports.daily_revenue → ProgrammingError（仅 SELECT 权限）

Opt-in 触发：
  INTEGRATION_PG_DSN=postgresql+asyncpg://user:pass@host/db pytest <this_file>

未设 INTEGRATION_PG_DSN 时全部 skip → CI 自然忽略，本地有库的 dev 可手跑。

前置假设：
  - DSN 指向已 alembic upgrade head（v404+v405+v406 已应用）的库
  - DSN 用户拥有非 BYPASSRLS 角色（否则 RLS 不生效，跨租户测试失效）
  - tx_nlq_readonly role 已建（v404）+ reports schema + 8 视图（v404/v405/v406）
  - 测试前后用 row_security=off 清空 mv_daily_settlement（避免污染）

D2b'（2026-05-11）：DSN/skipif/tenant GUC helper 切到 shared.test_utils.integration_pg；
module-scoped engine + 多 session + role 切换模式与 #418 shared fixture 不兼容，故
engine/session/cleanup 仍滚自己的。

Refs: issue #289
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.test_utils.integration_pg import (
    INTEGRATION_PG_DSN,
    requires_integration_pg,
    set_tenant_guc,
)

pytestmark = requires_integration_pg


_SOURCE_TABLE = "mv_daily_settlement"
_VIEW = "reports.daily_revenue"
_NLQ_ROLE = "tx_nlq_readonly"

_TENANT_A = str(uuid.uuid4())
_TENANT_B = str(uuid.uuid4())
_STORE_A1 = str(uuid.uuid4())
_STORE_B1 = str(uuid.uuid4())


# ─────────────── fixtures ───────────────


@pytest.fixture(scope="module")
def engine():
    """模块级 engine — 复用连接池避开多次 handshake。"""
    return create_async_engine(INTEGRATION_PG_DSN, echo=False, future=True)


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
    """每个测试前后清空 mv_daily_settlement（用 row_security=off 真删跨租户行）。"""
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL row_security = off"))
        await conn.execute(
            text(f"DELETE FROM {_SOURCE_TABLE} WHERE tenant_id IN (:a, :b)"),
            {"a": _TENANT_A, "b": _TENANT_B},
        )
    yield
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL row_security = off"))
        await conn.execute(
            text(f"DELETE FROM {_SOURCE_TABLE} WHERE tenant_id IN (:a, :b)"),
            {"a": _TENANT_A, "b": _TENANT_B},
        )


async def _insert_settlement(
    engine,
    *,
    tenant_id: str,
    store_id: str,
    stat_date: str,
    status: str,
    total_revenue_fen: int,
) -> None:
    """直接 INSERT mv_daily_settlement（用 row_security=off 跨 tenant 写）。"""
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL row_security = off"))
        await conn.execute(
            text(
                f"""
                INSERT INTO {_SOURCE_TABLE}
                  (tenant_id, store_id, stat_date, status,
                   total_revenue_fen, cash_system_fen, wechat_received_fen,
                   alipay_received_fen, card_received_fen,
                   stored_value_consumed_fen, cash_discrepancy_fen)
                VALUES
                  (:tid, :sid, :day, :st,
                   :rev, 0, 0, 0, 0, 0, 0)
                """
            ),
            {
                "tid": tenant_id,
                "sid": store_id,
                "day": stat_date,
                "st": status,
                "rev": total_revenue_fen,
            },
        )


# ─────────────── 1. security_invoker 真生效（跨 tenant 隔离） ───────────────


class TestViewSecurityInvokerTier1:
    """视图 WITH (security_invoker = on) 让 RLS 跟调用者 app.tenant_id 走。

    关键反测：tenant_A 数据 → 切 tenant_B 查视图必须看不到，即使视图 owner
    是 superuser 持 BYPASSRLS（PG 默认视图行为是按 owner 上下文）。
    """

    @pytest.mark.asyncio
    async def test_tenant_a_data_invisible_to_tenant_b(
        self, engine, session_factory
    ):
        """徐记海鲜（A）的日营收 → 其他餐厅（B）店长 NLQ 查不到。"""
        await _insert_settlement(
            engine,
            tenant_id=_TENANT_A,
            store_id=_STORE_A1,
            stat_date="2026-05-09",
            status="closed",
            total_revenue_fen=100_000,
        )

        async with await _open_session_with_tenant(
            session_factory, _TENANT_B
        ) as s:
            result = await s.execute(text(f"SELECT day, total_revenue_fen FROM {_VIEW}"))
            rows = list(result.mappings())
        assert rows == [], (
            f"security_invoker 失效：B 视角看到 {rows}，应见 0 行（A 的数据）"
        )

    @pytest.mark.asyncio
    async def test_tenant_a_sees_only_own_data(
        self, engine, session_factory
    ):
        """A 视角下查 reports.daily_revenue 仅见 A 自己的数据，不含 B 的。"""
        await _insert_settlement(
            engine,
            tenant_id=_TENANT_A,
            store_id=_STORE_A1,
            stat_date="2026-05-09",
            status="closed",
            total_revenue_fen=100_000,
        )
        await _insert_settlement(
            engine,
            tenant_id=_TENANT_B,
            store_id=_STORE_B1,
            stat_date="2026-05-09",
            status="closed",
            total_revenue_fen=200_000,
        )

        async with await _open_session_with_tenant(
            session_factory, _TENANT_A
        ) as s:
            result = await s.execute(text(f"SELECT total_revenue_fen FROM {_VIEW}"))
            revenues = [r["total_revenue_fen"] for r in result.mappings()]

        assert revenues == [100_000], (
            f"A 视角下应仅见 A 自己 100_000，实际 {revenues}"
        )


# ─────────────── 2. 视图 WHERE 过滤真生效 ───────────────


class TestViewClosedStatusFilterTier1:
    """daily_revenue 视图 SQL 内 WHERE status='closed' 过滤未结算行。"""

    @pytest.mark.asyncio
    async def test_view_excludes_open_status_rows(
        self, engine, session_factory
    ):
        """同 tenant 同 store 不同 day：1 closed + 1 open → 视图只见 closed 那条。"""
        await _insert_settlement(
            engine,
            tenant_id=_TENANT_A,
            store_id=_STORE_A1,
            stat_date="2026-05-08",
            status="open",       # 未结算 — 应被视图过滤
            total_revenue_fen=999,
        )
        await _insert_settlement(
            engine,
            tenant_id=_TENANT_A,
            store_id=_STORE_A1,
            stat_date="2026-05-09",
            status="closed",     # 已结算 — 应在视图中
            total_revenue_fen=100_000,
        )

        async with await _open_session_with_tenant(
            session_factory, _TENANT_A
        ) as s:
            result = await s.execute(
                text(f"SELECT day, total_revenue_fen FROM {_VIEW} ORDER BY day")
            )
            rows = list(result.mappings())

        assert len(rows) == 1, f"视图未过滤 open 状态，实际 {rows}"
        assert rows[0]["total_revenue_fen"] == 100_000


# ─────────────── 3. 敏感字段在 runtime 不暴露 ───────────────


class TestViewSensitiveColumnsTier1:
    """v404 视图 SELECT 子句剔除的敏感字段，runtime 真不出现在结果列中。"""

    @pytest.mark.asyncio
    async def test_view_columns_exclude_sensitive_fields(
        self, engine, session_factory
    ):
        """SELECT * FROM reports.daily_revenue 返回的列名集合不含敏感字段。"""
        await _insert_settlement(
            engine,
            tenant_id=_TENANT_A,
            store_id=_STORE_A1,
            stat_date="2026-05-09",
            status="closed",
            total_revenue_fen=100_000,
        )

        async with await _open_session_with_tenant(
            session_factory, _TENANT_A
        ) as s:
            result = await s.execute(text(f"SELECT * FROM {_VIEW}"))
            rows = list(result.mappings())

        assert len(rows) == 1
        cols = set(rows[0].keys())

        # 敏感字段必须不暴露
        for forbidden in (
            "cash_discrepancy_fen",   # v404 设计去 — 差异列
            "pending_items",          # v404 设计去 — 待审核 PII
            "closed_by",              # v404 注释提到 — 操作人
            "last_event_id",          # 实现细节
        ):
            assert forbidden not in cols, (
                f"视图泄露敏感列 {forbidden}（v404 应剔除）"
            )

        # 业务字段必须在
        for required in ("day", "total_revenue_fen", "tenant_id", "store_id"):
            assert required in cols, f"视图缺业务列 {required}"


# ─────────────── 4. tx_nlq_readonly role 权限边界 ───────────────


class TestNlqReadonlyRoleBoundaryTier1:
    """v404 创建的 tx_nlq_readonly role 应只能查 reports.* 视图，不能：
       - 直查 mv_* 原表（REVOKE public schema USAGE 防御）
       - 写入 reports.* 视图（仅 GRANT SELECT）
    """

    @pytest.mark.asyncio
    async def test_role_cannot_query_mv_source_table(
        self, engine, session_factory
    ):
        """SET ROLE tx_nlq_readonly + SELECT FROM mv_daily_settlement → 拒。"""
        async with await _open_session_with_tenant(
            session_factory, _TENANT_A
        ) as s:
            await s.execute(text(f"SET LOCAL ROLE {_NLQ_ROLE}"))
            with pytest.raises(ProgrammingError) as exc_info:
                await s.execute(text(f"SELECT * FROM {_SOURCE_TABLE} LIMIT 1"))
            # 应是 permission denied / does not exist（取决于 search_path）
            err = str(exc_info.value).lower()
            assert "permission" in err or "denied" in err or "does not exist" in err, (
                f"期望权限拒，实际 {exc_info.value}"
            )

    @pytest.mark.asyncio
    async def test_role_cannot_insert_into_view(
        self, engine, session_factory
    ):
        """SET ROLE tx_nlq_readonly + INSERT INTO reports.daily_revenue → 拒。"""
        async with await _open_session_with_tenant(
            session_factory, _TENANT_A
        ) as s:
            await s.execute(text(f"SET LOCAL ROLE {_NLQ_ROLE}"))
            with pytest.raises(ProgrammingError) as exc_info:
                await s.execute(
                    text(
                        f"INSERT INTO {_VIEW} (tenant_id, store_id, day, total_revenue_fen) "
                        "VALUES (gen_random_uuid(), gen_random_uuid(), CURRENT_DATE, 1)"
                    )
                )
            err = str(exc_info.value).lower()
            assert "permission" in err or "denied" in err or "read" in err, (
                f"期望写入拒，实际 {exc_info.value}"
            )

    @pytest.mark.asyncio
    async def test_role_can_select_from_reports_view(
        self, engine, session_factory
    ):
        """SET ROLE tx_nlq_readonly + SELECT FROM reports.daily_revenue → OK
        （证明 GRANT SELECT 真生效）。"""
        await _insert_settlement(
            engine,
            tenant_id=_TENANT_A,
            store_id=_STORE_A1,
            stat_date="2026-05-09",
            status="closed",
            total_revenue_fen=100_000,
        )

        async with await _open_session_with_tenant(
            session_factory, _TENANT_A
        ) as s:
            await s.execute(text(f"SET LOCAL ROLE {_NLQ_ROLE}"))
            result = await s.execute(text(f"SELECT total_revenue_fen FROM {_VIEW}"))
            rows = list(result.mappings())

        assert rows == [{"total_revenue_fen": 100_000}], (
            f"NLQ role SELECT 应成功，实际 {rows}"
        )
