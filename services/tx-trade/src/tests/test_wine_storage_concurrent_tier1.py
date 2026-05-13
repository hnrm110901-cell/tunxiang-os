"""Tier 1 — wine_storage 真并发 e2e 反测（opt-in via INTEGRATION_PG_DSN）

issue #531 收尾：PR #272 (`f249ae27` wine_storage Decimal→fen) §19 reviewer MUST FIX
一起修补 3 路由 FOR UPDATE 行锁 (extend / transfer / write_off, take 历史已有), 但
0 测试验真并发语义 — aiosqlite 不支持 PostgreSQL row-level locking 同语义, 单 pytest
session 内跨包模型导入又会触发 SQLAlchemy MetaData 重复注册.

本文件**直接对 `wine_storage_records` / `wine_storage_transactions` 表跑 raw SQL**, 复现
路由层 (`services/tx-trade/src/api/wine_storage_routes.py`) 4 入口的 SQL 序列骨架, 真 PG
+ asyncio.gather 两 session 并发, 验证 FOR UPDATE 序列化语义.

四个反测覆盖 issue #531 验收清单:

  1. test_concurrent_take_no_oversell
     双并发 take_wine 各取 6/10 (总 12/10) → 先获锁者落地 → 后获锁者读到
     remaining=4 触发"取酒数量超过剩余数量" 业务校验, 库存不超取.

  2. test_concurrent_extend_serializes
     双并发 extend_wine_storage 不同 new_expiry_date → 2 条 extend 流水 +
     final expiry_date = 后获锁者写入 (last-writer-wins, 仍序列化).

  3. test_concurrent_transfer_one_succeeds
     双并发 transfer_wine (A→B, A→C) → 序列化执行, 第二者 last-writer-wins 改 table.

  4. test_concurrent_write_off_one_succeeds
     双并发 write_off → 先获锁者落地, 第二者读 status='written_off' 触发
     "存酒状态 written_off 不允许核销" 业务校验, 流水表只 1 条 write_off
     (押金核销 Tier 1 资金路径不双扣).

Opt-in 触发:
    INTEGRATION_PG_DSN=postgresql+asyncpg://user:pass@host/db pytest \\
      services/tx-trade/src/tests/test_wine_storage_concurrent_tier1.py

未设 INTEGRATION_PG_DSN 时 `requires_integration_pg` 整文件 skip → CI 自然忽略 (与
`services/tx-brain/src/tests/test_nlq_pg_integration_tier1.py` / D2b' shared helper
完全同模式).

并发反测设计要点 (设计陷阱):
  - 必须把 set_tenant_guc + FOR UPDATE + UPDATE + INSERT + asyncio.sleep 全部
    放在同一个 `async with s.begin():` 块内. AsyncSession 默认 autobegin 行为下,
    每条 .execute() 隐式起独立事务并立即提交, 锁会瞬时释放, 第二者 SELECT FOR UPDATE
    不会撞上 → 锁失效时测试仍 pass (伪绿). 显式 begin() 让事务跨越所有语句, 锁真持有.
  - set_tenant_guc 第三参 TRUE = transaction-scoped GUC, 必须在 begin() 内调用,
    否则 GUC 设在了"前一个 auto 事务"里, begin() 启动新事务后 RLS 立刻看不到 GUC.

前置假设:
  - DSN 指向已 alembic upgrade head (v415+) 的库: wine_storage_records 含
    `storage_price_fen BIGINT NULLABLE` / wine_storage_transactions 含
    `price_at_trans_fen BIGINT NULLABLE`.
  - DSN 用户非 BYPASSRLS (否则 set_tenant_guc 无意义, 跨 session 隔离假象).
  - 测试前后用 row_security=off 清空 test tenant 数据避污染.

Refs:
  - issue #531 (本文件 owner, PR #272 follow-up)
  - PR #272 (FOR UPDATE 加入 extend/transfer/write_off, take 历史已有)
  - shared/test_utils/integration_pg.py (skipif + GUC helper, D2b' 2026-05-11)
  - CLAUDE.md §17 Tier 1 存酒押金路径 + §20 真 PG 反测 staging 验收
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from shared.test_utils.integration_pg import (
    INTEGRATION_PG_DSN,
    requires_integration_pg,
    set_tenant_guc,
)

pytestmark = requires_integration_pg


# UUID 类型直接传 uuid.UUID 对象, asyncpg 自动绑成 UUID type — 比 :tid 文本 cast
# 在 sqlalchemy text() 内冒号歧义 (bind 解析吃第二冒号) 安全.
_TENANT = uuid.uuid4()
_STORE = "STORE-WINE-CONCURRENT-TEST"
_TABLE_FROM = "T-WINE-FROM"
_TABLE_TO_B = "T-WINE-TO-B"
_TABLE_TO_C = "T-WINE-TO-C"


# ─────────────── fixtures ───────────────


@pytest.fixture(scope="module")
def engine():
    """模块级 async engine — NullPool 强制每 begin() 新连接, 避 asyncpg
    "another operation in progress" (连接池跨 test 复用时 session.close() 与
    fixture _cleanup 间微弱时序窗口暴露)."""
    return create_async_engine(
        INTEGRATION_PG_DSN, echo=False, future=True, poolclass=NullPool
    )


@pytest.fixture(scope="module")
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture(autouse=True)
async def _cleanup(engine):
    """每个测试前后清空 test tenant 的存酒/流水 (RLS off 跨 tenant 真删)."""

    async def _clean() -> None:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL row_security = off"))
            await conn.execute(
                text("DELETE FROM wine_storage_transactions WHERE tenant_id = :tid"),
                {"tid": _TENANT},
            )
            await conn.execute(
                text("DELETE FROM wine_storage_records WHERE tenant_id = :tid"),
                {"tid": _TENANT},
            )

    await _clean()
    yield
    await _clean()


async def _insert_record(
    engine,
    *,
    record_id: uuid.UUID,
    quantity: int = 10,
    remaining: int = 10,
    status: str = "stored",
    table_id: str | None = _TABLE_FROM,
    expiry_date: date | None = None,
) -> None:
    """SET row_security=off 后 INSERT (绕开 RLS, fixture 用)."""
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL row_security = off"))
        await conn.execute(
            text(
                """
                INSERT INTO wine_storage_records
                    (id, tenant_id, store_id, table_id, bottle_code, wine_name,
                     quantity, remaining_quantity, storage_date, expiry_date,
                     status)
                VALUES
                    (:rid, :tid, :sid, :table_id, :code, :name,
                     :quantity, :remaining, :storage_date, :expiry_date,
                     :status)
                """
            ),
            {
                "rid": record_id,
                "tid": _TENANT,
                "sid": _STORE,
                "table_id": table_id,
                "code": f"CODE-{str(record_id)[:8]}",
                "name": f"试酒-{str(record_id)[:8]}",
                "quantity": quantity,
                "remaining": remaining,
                "storage_date": date.today(),
                "expiry_date": expiry_date,
                "status": status,
            },
        )


async def _count_trans(engine, *, record_id: str, trans_type: str) -> int:
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL row_security = off"))
        r = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) AS c FROM wine_storage_transactions "
                    "WHERE record_id = :rid AND trans_type = :t"
                ),
                {"rid": record_id, "t": trans_type},
            )
        ).mappings().first()
    return int(r["c"])


async def _read_record(engine, *, record_id: str) -> dict:
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL row_security = off"))
        r = (
            await conn.execute(
                text(
                    "SELECT remaining_quantity, status, table_id, expiry_date "
                    "FROM wine_storage_records WHERE id = :rid"
                ),
                {"rid": record_id},
            )
        ).mappings().first()
    return dict(r)


# ─────────────── 4 并发反测 ───────────────


class TestWineStorageConcurrentTier1:
    """4 路由 FOR UPDATE 行锁真并发语义 — 200 桌徐记海鲜峰值场景."""

    @pytest.mark.asyncio
    async def test_concurrent_take_no_oversell(self, engine, session_factory):
        """双并发 take_wine 各取 6/10 → 仅一者成功, 库存不超取 (无负 remaining)."""
        rid = uuid.uuid4()
        await _insert_record(engine, record_id=rid, quantity=10, remaining=10)

        async def take_attempt(qty: int, delay: float) -> tuple[str, int]:
            s: AsyncSession = session_factory()
            try:
                # 整个事务跨锁 + 业务 + sleep, 第二者真撞 FOR UPDATE 等待
                async with s.begin():
                    await set_tenant_guc(s, _TENANT)
                    if delay:
                        await asyncio.sleep(delay)
                    row = (
                        await s.execute(
                            text(
                                "SELECT remaining_quantity, status FROM wine_storage_records "
                                "WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE "
                                "FOR UPDATE"
                            ),
                            {"rid": rid, "tid": _TENANT},
                        )
                    ).mappings().first()
                    assert row is not None, "存酒应已建"
                    if row["status"] in ("fully_taken", "written_off", "expired"):
                        return ("rejected_status", row["remaining_quantity"])
                    if qty > row["remaining_quantity"]:
                        return ("rejected_oversell", row["remaining_quantity"])
                    new_remain = row["remaining_quantity"] - qty
                    new_status = "fully_taken" if new_remain == 0 else "partial_taken"
                    await s.execute(
                        text(
                            "UPDATE wine_storage_records SET remaining_quantity = :r, "
                            "status = :st, updated_at = now() WHERE id = :rid"
                        ),
                        {"r": new_remain, "st": new_status, "rid": rid},
                    )
                    await s.execute(
                        text(
                            "INSERT INTO wine_storage_transactions "
                            "(id, tenant_id, record_id, store_id, trans_type, quantity, "
                            " operated_at, created_at, updated_at) "
                            "VALUES (gen_random_uuid(), :tid, :rid, :sid, "
                            "'take_out', :q, now(), now(), now())"
                        ),
                        {"tid": _TENANT, "rid": rid, "sid": _STORE, "q": qty},
                    )
                    # 持锁短延迟 — 强制对端在 FOR UPDATE 上真阻塞 (非 happen-before 巧合)
                    await asyncio.sleep(0.1)
                    return ("succeeded", new_remain)
            finally:
                await s.close()

        outcomes = await asyncio.gather(
            take_attempt(qty=6, delay=0.0),
            take_attempt(qty=6, delay=0.02),
        )

        succeeded = [o for o in outcomes if o[0] == "succeeded"]
        oversell = [o for o in outcomes if o[0] == "rejected_oversell"]
        assert len(succeeded) == 1, f"应仅 1 个 take 成功, 实得 {outcomes}"
        assert len(oversell) == 1, f"应仅 1 个 reject_oversell, 实得 {outcomes}"
        assert oversell[0][1] == 4, f"第二者应见 remaining=4 (序列化后), 实见 {oversell[0][1]}"

        # DB 最终态: remaining=4, status=partial_taken, take_out 流水仅 1 条
        final = await _read_record(engine, record_id=rid)
        assert final["remaining_quantity"] == 4
        assert final["status"] == "partial_taken"
        take_count = await _count_trans(engine, record_id=rid, trans_type="take_out")
        assert take_count == 1, f"take_out 流水应 1 条, 实 {take_count}"

    @pytest.mark.asyncio
    async def test_concurrent_extend_serializes(self, engine, session_factory):
        """双并发 extend 不同 new_expiry_date → 序列化 + 2 条 extend 流水 + LWW expiry."""
        rid = uuid.uuid4()
        base_expiry = date.today() + timedelta(days=30)
        await _insert_record(engine, record_id=rid, expiry_date=base_expiry)

        # 两个 new_expiry_date 互不相同
        expiry_first = base_expiry + timedelta(days=30)   # +60d total
        expiry_second = base_expiry + timedelta(days=90)  # +120d total

        async def extend_attempt(new_expiry: date, delay: float) -> str:
            s: AsyncSession = session_factory()
            try:
                async with s.begin():
                    await set_tenant_guc(s, _TENANT)
                    if delay:
                        await asyncio.sleep(delay)
                    row = (
                        await s.execute(
                            text(
                                "SELECT status FROM wine_storage_records "
                                "WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE "
                                "FOR UPDATE"
                            ),
                            {"rid": rid, "tid": _TENANT},
                        )
                    ).mappings().first()
                    assert row is not None
                    if row["status"] in ("fully_taken", "written_off"):
                        return "rejected_status"
                    new_status = "stored" if row["status"] == "expired" else row["status"]
                    await s.execute(
                        text(
                            "UPDATE wine_storage_records SET expiry_date = :exp, "
                            "status = :st, updated_at = now() WHERE id = :rid"
                        ),
                        {"exp": new_expiry, "st": new_status, "rid": rid},
                    )
                    await s.execute(
                        text(
                            "INSERT INTO wine_storage_transactions "
                            "(id, tenant_id, record_id, store_id, trans_type, quantity, "
                            " operated_at, created_at, updated_at) "
                            "VALUES (gen_random_uuid(), :tid, :rid, :sid, "
                            "'extend', 0, now(), now(), now())"
                        ),
                        {"tid": _TENANT, "rid": rid, "sid": _STORE},
                    )
                    await asyncio.sleep(0.1)
                    return "succeeded"
            finally:
                await s.close()

        outcomes = await asyncio.gather(
            extend_attempt(expiry_first, delay=0.0),
            extend_attempt(expiry_second, delay=0.02),
        )

        assert all(o == "succeeded" for o in outcomes), f"两 extend 都应成功, 实 {outcomes}"

        # 序列化 + LWW: final expiry = 后获锁者 = expiry_second
        final = await _read_record(engine, record_id=rid)
        assert final["expiry_date"] == expiry_second, (
            f"LWW 期望 final={expiry_second}, 实 {final['expiry_date']}"
        )
        extend_count = await _count_trans(engine, record_id=rid, trans_type="extend")
        assert extend_count == 2, f"extend 流水应 2 条 (序列化各落 1 条), 实 {extend_count}"

    @pytest.mark.asyncio
    async def test_concurrent_transfer_one_succeeds(self, engine, session_factory):
        """双并发 transfer (A→B, A→C) → 序列化 + LWW table_id."""
        rid = uuid.uuid4()
        await _insert_record(engine, record_id=rid, table_id=_TABLE_FROM)

        async def transfer_attempt(to_table: str, delay: float) -> tuple[str, str | None]:
            s: AsyncSession = session_factory()
            try:
                async with s.begin():
                    await set_tenant_guc(s, _TENANT)
                    if delay:
                        await asyncio.sleep(delay)
                    row = (
                        await s.execute(
                            text(
                                "SELECT status, table_id, remaining_quantity FROM wine_storage_records "
                                "WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE "
                                "FOR UPDATE"
                            ),
                            {"rid": rid, "tid": _TENANT},
                        )
                    ).mappings().first()
                    assert row is not None
                    if row["status"] in ("fully_taken", "written_off"):
                        return ("rejected_status", row["table_id"])
                    if row["table_id"] == to_table:
                        # 路由层 line 797 "目标台位与当前台位相同" 业务校验
                        return ("rejected_same_table", row["table_id"])
                    await s.execute(
                        text(
                            "UPDATE wine_storage_records SET table_id = :tt, "
                            "updated_at = now() WHERE id = :rid"
                        ),
                        {"tt": to_table, "rid": rid},
                    )
                    await s.execute(
                        text(
                            "INSERT INTO wine_storage_transactions "
                            "(id, tenant_id, record_id, store_id, trans_type, quantity, "
                            " table_id, operated_at, created_at, updated_at) "
                            "VALUES (gen_random_uuid(), :tid, :rid, :sid, "
                            "'transfer_out', :q, :ft, now(), now(), now())"
                        ),
                        {
                            "tid": _TENANT,
                            "rid": rid,
                            "sid": _STORE,
                            "q": row["remaining_quantity"],
                            "ft": row["table_id"],
                        },
                    )
                    await asyncio.sleep(0.1)
                    return ("succeeded", to_table)
            finally:
                await s.close()

        outcomes = await asyncio.gather(
            transfer_attempt(_TABLE_TO_B, delay=0.0),
            transfer_attempt(_TABLE_TO_C, delay=0.02),
        )

        # 序列化下两者都 succeeded (路由层目前不拦 "from != original table" 二次检查),
        # 但锁失效时 table_id 可能花式错位.
        succeeded = [o for o in outcomes if o[0] == "succeeded"]
        assert len(succeeded) == 2, f"两 transfer 应序列化成功, 实 {outcomes}"

        final = await _read_record(engine, record_id=rid)

        # 锁序列化关键断言: final.table_id 必是后获锁者 (LWW). delay=0.02 一定排在后.
        # 若 FOR UPDATE 失效 (两并行写), final 可能是任意值或两次 UPDATE 互相覆盖错位.
        assert final["table_id"] == _TABLE_TO_C, (
            f"序列化下后获锁者 LWW 应 final={_TABLE_TO_C}, 实 {final['table_id']} — 锁可能失效"
        )

        transfer_count = await _count_trans(engine, record_id=rid, trans_type="transfer_out")
        assert transfer_count == 2, (
            f"transfer_out 流水应 2 条 (序列化各落 1 条), 实 {transfer_count}"
        )

    @pytest.mark.asyncio
    async def test_concurrent_write_off_one_succeeds(self, engine, session_factory):
        """双并发 write_off → 仅 1 落地, 押金 Tier 1 资金路径不双扣."""
        rid = uuid.uuid4()
        await _insert_record(engine, record_id=rid)

        async def write_off_attempt(delay: float) -> str:
            s: AsyncSession = session_factory()
            try:
                async with s.begin():
                    await set_tenant_guc(s, _TENANT)
                    if delay:
                        await asyncio.sleep(delay)
                    row = (
                        await s.execute(
                            text(
                                "SELECT status, remaining_quantity FROM wine_storage_records "
                                "WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE "
                                "FOR UPDATE"
                            ),
                            {"rid": rid, "tid": _TENANT},
                        )
                    ).mappings().first()
                    assert row is not None
                    if row["status"] in ("fully_taken", "written_off"):
                        return "rejected_status"
                    await s.execute(
                        text(
                            "UPDATE wine_storage_records SET status = 'written_off', "
                            "updated_at = now() WHERE id = :rid"
                        ),
                        {"rid": rid},
                    )
                    await s.execute(
                        text(
                            "INSERT INTO wine_storage_transactions "
                            "(id, tenant_id, record_id, store_id, trans_type, quantity, "
                            " operated_at, created_at, updated_at) "
                            "VALUES (gen_random_uuid(), :tid, :rid, :sid, "
                            "'write_off', :q, now(), now(), now())"
                        ),
                        {"tid": _TENANT, "rid": rid, "sid": _STORE, "q": row["remaining_quantity"]},
                    )
                    await asyncio.sleep(0.1)
                    return "succeeded"
            finally:
                await s.close()

        outcomes = await asyncio.gather(
            write_off_attempt(delay=0.0),
            write_off_attempt(delay=0.02),
        )

        succeeded = [o for o in outcomes if o == "succeeded"]
        rejected = [o for o in outcomes if o == "rejected_status"]
        assert len(succeeded) == 1, f"应仅 1 个 write_off 落地, 实 {outcomes}"
        assert len(rejected) == 1, f"应仅 1 个 reject_status, 实 {outcomes}"

        # DB 最终态: status='written_off', write_off 流水仅 1 条 (Tier 1 押金不双扣)
        final = await _read_record(engine, record_id=rid)
        assert final["status"] == "written_off"
        write_off_count = await _count_trans(engine, record_id=rid, trans_type="write_off")
        assert write_off_count == 1, (
            f"write_off 流水应 1 条 (押金 Tier 1 不双扣), 实 {write_off_count}"
        )
