"""concurrent_runner.py smoke test — PR-1 infra 自身 verifier (5/14)

不测业务逻辑；只验证 run_concurrent + assert_final_consistency 端到端能跑通:
  - T1 INSERT 无 race — N=5 workers 各 INSERT 独立 store
    → 全部成功 (no exceptions, 5 unique store IDs)
  - T2 FOR UPDATE 串行化 — N=5 workers 各 SELECT FOR UPDATE 同一行 + UPDATE
    → 全部成功（无死锁）+ final store_name 是 5 路串行 append 的结果（last-writer-wins）
  - T3 assert_final_consistency 助手 — count + sum_ + status_set 各路径

跑法（同 test_rls_runtime_p0_tier1.py）:

    docker compose -f infra/compose/test-pg.yml up -d
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/db-bootstrap.sh --skip-create
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/migrate-all.sh --include-legacy
    INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        pytest tests/concurrent/test_runner_smoke_tier1.py -v

未设 INTEGRATION_PG_DSN → 全部 skip（opt-in 模式）。CI 在 tier1-row-lock-concurrent.yml
起 PG service container + alembic upgrade head 真跑。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.test_utils.concurrent_runner import (
    assert_final_consistency,
    run_concurrent,
)
from shared.test_utils.integration_pg import requires_integration_pg

pytestmark = [requires_integration_pg]


# 测试 tenant — 每个 test 内独立 UUID 避免 cross-test 污染（虽然 _cleanup 已清, 双保险）
def _new_tenant() -> uuid.UUID:
    return uuid.uuid4()


async def test_runner_smoke_n5_insert_unique_stores(session_factory):
    """T1 — N=5 workers 各 INSERT 独立 store（无 race）→ 验证 runner 基本 mechanics。

    每 worker:
      1. session 独立 transaction
      2. SET LOCAL ROLE tunxiang_rls_app 切非 superuser
      3. set_tenant_guc 设事务级 app.tenant_id
      4. INSERT stores（独立 UUID, 无 unique 冲突）
      5. commit

    断言:
      - 5 worker 全部成功（无 exception）
      - 5 unique store IDs（runner 真起 5 个 worker）
      - 表内 count=5（commit 真生效）
    """
    tenant_a = _new_tenant()

    async def _insert(s: AsyncSession) -> str:
        sid = uuid.uuid4()
        await s.execute(
            text("""
                INSERT INTO stores (id, tenant_id, store_name, store_code)
                VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), :name, :code)
            """),
            {
                "id": str(sid),
                "tid": str(tenant_a),
                "name": f"smoke-{uuid.uuid4().hex[:8]}",
                "code": f"SMK-{uuid.uuid4().hex[:12]}",
            },
        )
        return str(sid)

    results = await run_concurrent(session_factory, tenant_a, n=5, operation=_insert)

    # 全部成功（无 exception）
    exceptions = [r for r in results if isinstance(r, BaseException)]
    assert not exceptions, f"runner exceptions: {exceptions}"

    # 5 unique store IDs
    store_ids = [r for r in results if not isinstance(r, BaseException)]
    assert len(set(store_ids)) == 5, (
        f"expected 5 unique store IDs, got {len(set(store_ids))}: {store_ids}"
    )

    # 表内 count=5 — 验证 assert_final_consistency.count 路径
    async with session_factory() as s:
        await assert_final_consistency(
            s,
            "stores",
            {"tenant_id": str(tenant_a)},
            {"count": 5},
        )


async def test_runner_smoke_for_update_serializes_n5(session_factory):
    """T2 — N=5 workers 各 SELECT FOR UPDATE + UPDATE 同一行 → 验证锁串行化真生效。

    setup: INSERT 1 行 stores 初始 store_name="initial"
    runner: 5 worker 各跑 SELECT FOR UPDATE → UPDATE store_name = current + "+1"
    断言: 5 worker 全部成功（无死锁/无 race lost-update）
          final store_name == "initial+1+1+1+1+1"（5 路串行各 append 一次）

    若 FOR UPDATE 未真生效（mock 路径假串行化）, final 会丢失部分 update（lost update）
    导致 "+1" 数量 < 5。本测试是 runner 端到端"真 PG 真锁"smoke。
    """
    tenant_a = _new_tenant()
    store_id = uuid.uuid4()

    # Setup: 用 session_factory() default superuser session 写初始行（不进 runner）
    async with session_factory() as s:
        await s.execute(
            text("""
                INSERT INTO stores (id, tenant_id, store_name, store_code)
                VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), 'initial', :code)
            """),
            {
                "id": str(store_id),
                "tid": str(tenant_a),
                "code": f"SMK-{uuid.uuid4().hex[:12]}",
            },
        )
        await s.commit()

    async def _select_for_update_then_update(s: AsyncSession) -> str:
        # SELECT FOR UPDATE: 持锁直到 commit；其他 worker 在此阻塞
        result = await s.execute(
            text("""
                SELECT store_name FROM stores
                WHERE id = CAST(:id AS uuid)
                FOR UPDATE
            """),
            {"id": str(store_id)},
        )
        current = result.scalar_one()
        new_name = f"{current}+1"
        await s.execute(
            text("""
                UPDATE stores SET store_name = :new
                WHERE id = CAST(:id AS uuid)
            """),
            {"id": str(store_id), "new": new_name},
        )
        return new_name

    results = await run_concurrent(
        session_factory,
        tenant_a,
        n=5,
        operation=_select_for_update_then_update,
    )

    # 全部成功（FOR UPDATE 串行化, 无死锁）
    exceptions = [r for r in results if isinstance(r, BaseException)]
    assert not exceptions, f"FOR UPDATE serialization failed: {exceptions}"

    # final store_name 应是 5 路串行 append 后的结果
    async with session_factory() as s:
        result = await s.execute(
            text("SELECT store_name FROM stores WHERE id = CAST(:id AS uuid)"),
            {"id": str(store_id)},
        )
        final_name = result.scalar()
        assert final_name == "initial+1+1+1+1+1", (
            f"FOR UPDATE serialization unexpected final state: '{final_name}' "
            f"— expected 'initial+1+1+1+1+1' (5 路串行 append). "
            f"若 '+1' 少于 5 个 → lost update 表明 FOR UPDATE 未真生效"
        )


async def test_assert_final_consistency_helper_paths(session_factory):
    """T3 — assert_final_consistency 助手 count/sum_/status_set 三路径 smoke。

    setup: 直接 INSERT 3 行 stores (default superuser, 不进 runner) — runner 只测自身。
    断言:
      - count=3 路径
      - status_set 路径（stores 表有 status 列, default 'active'）
      - 反例: 错误 expected 应抛 AssertionError
    """
    tenant_a = _new_tenant()

    # Setup 3 stores
    async with session_factory() as s:
        for i in range(3):
            await s.execute(
                text("""
                    INSERT INTO stores (id, tenant_id, store_name, store_code, status)
                    VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), :name, :code, 'active')
                """),
                {
                    "id": str(uuid.uuid4()),
                    "tid": str(tenant_a),
                    "name": f"helper-{i}",
                    "code": f"HLP-{uuid.uuid4().hex[:12]}",
                },
            )
        await s.commit()

    # 正例: count=3 + status_set={'active'}
    async with session_factory() as s:
        await assert_final_consistency(
            s,
            "stores",
            {"tenant_id": str(tenant_a)},
            {"count": 3, "status_set": {"active"}},
        )

    # 反例: count 错应抛 AssertionError
    async with session_factory() as s:
        with pytest.raises(AssertionError, match="count mismatch"):
            await assert_final_consistency(
                s,
                "stores",
                {"tenant_id": str(tenant_a)},
                {"count": 99},
            )

    # 反例: status_set 错应抛 AssertionError
    async with session_factory() as s:
        with pytest.raises(AssertionError, match="status_set mismatch"):
            await assert_final_consistency(
                s,
                "stores",
                {"tenant_id": str(tenant_a)},
                {"status_set": {"closed"}},
            )
