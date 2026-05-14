"""W7-W8 供应链标准库 — 真 PG 并发反测（PR #631 §6.2 扩展）

W7-1 (PRD-02) ingredient_weight_standards / W7-2 (PRD-06) ingredient_yield_standards /
W8 (PRD-05) supplier_delivery_violations 各反测一项关键并发不变量：

  T1 weight_standard 二级审批 FOR UPDATE 串行化（PR-A/B/C/D/E pattern）
     — N=5 workers 并发 approve 同一草稿 → 仅 1 个成功，其他 raise（重复审批拒绝）

  T2 yield_standard 二级审批 FOR UPDATE 串行化
     — 与 T1 同 pattern，验证 W7-2 ship 后行锁实际生效

  T3 delivery_violations UNIQUE 幂等串行化（W8 PRD-05 关键不变量）
     — N=5 workers 并发 record_violation 同一 receiving_order_id
     → ON CONFLICT DO NOTHING 保证仅 1 条记录入表，supplier_scoring 不双计扣分

跑法（同 test_runner_smoke_tier1.py）:

    docker compose -f infra/compose/test-pg.yml up -d
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/db-bootstrap.sh --skip-create
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/migrate-all.sh --include-legacy
    INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        pytest tests/concurrent/test_w7_w8_supply_standards_concurrent_tier1.py -v

未设 INTEGRATION_PG_DSN → 全部 skip（opt-in 模式）。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.test_utils.concurrent_runner import (
    assert_final_consistency,
    run_concurrent,
)
from shared.test_utils.integration_pg import requires_integration_pg

pytestmark = [requires_integration_pg]


def _new_tenant() -> uuid.UUID:
    return uuid.uuid4()


# ─── T1 — weight_standard FOR UPDATE 串行化（PRD-02 / W7-1 二级审批）────────


async def test_weight_standard_approve_for_update_serializes_n5(session_factory):
    """N=5 workers 并发 approve 同一草稿 → 仅 1 成功，其余 SELECT FOR UPDATE 串行后看到已审批 → raise。

    防错：双审批可能同时 race 写 approved_by，无 FOR UPDATE 会双 UPDATE 致 audit log 噪音。
    """
    tenant_a = _new_tenant()
    ingredient_id = uuid.uuid4()
    std_id = uuid.uuid4()
    created_by = uuid.uuid4()
    approver_id = uuid.uuid4()  # 与 created_by 不同 — 满足二级审批

    # 准备 — 直接 INSERT 草稿（绕 RLS 用 superuser 引擎）
    async with session_factory() as s:
        await s.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_a)})
        await s.execute(
            text("""
                INSERT INTO ingredient_weight_standards (
                    id, tenant_id, ingredient_id, deduction_pct,
                    season, effective_from, tolerance_pct, approved_by, approved_at,
                    notes, created_by, created_at, updated_at, is_deleted
                ) VALUES (
                    CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:ing AS uuid), :pct,
                    'all', :today, 5.0, NULL, NULL,
                    NULL, CAST(:by AS uuid), NOW(), NOW(), FALSE
                )
                ON CONFLICT DO NOTHING
            """),
            {
                "id": str(std_id),
                "tid": str(tenant_a),
                "ing": str(ingredient_id),
                "pct": Decimal("8.0"),
                "today": date(2026, 5, 1),
                "by": str(created_by),
            },
        )
        await s.commit()

    async def _approve(s: AsyncSession) -> bool:
        # Worker 内不调 service 层（绕 import 冲突），直接 raw SQL 模拟 service.approve 路径
        # 1) SELECT ... FOR UPDATE 行锁
        # 2) 检查 approved_by 是否仍为 NULL；NOT NULL 则 raise
        # 3) UPDATE approved_by + approved_at
        row = (
            await s.execute(
                text("""
                    SELECT approved_by FROM ingredient_weight_standards
                    WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:tid AS uuid)
                    FOR UPDATE
                """),
                {"id": str(std_id), "tid": str(tenant_a)},
            )
        ).mappings().first()
        if row is None:
            raise ValueError("std 不存在")
        if row["approved_by"] is not None:
            raise ValueError("已审批 — FOR UPDATE 串行化生效")
        await s.execute(
            text("""
                UPDATE ingredient_weight_standards
                SET approved_by = CAST(:by AS uuid),
                    approved_at = NOW(),
                    updated_at  = NOW()
                WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:tid AS uuid)
            """),
            {"by": str(approver_id), "id": str(std_id), "tid": str(tenant_a)},
        )
        return True

    results = await run_concurrent(session_factory, tenant_a, n=5, operation=_approve)

    successes = [r for r in results if r is True]
    duplicate_rejects = [
        r for r in results
        if isinstance(r, ValueError) and "已审批" in str(r)
    ]
    assert len(successes) == 1, (
        f"应仅 1 个 worker 审批成功，实际 {len(successes)}（FOR UPDATE 失效或 PG drift）"
    )
    assert len(duplicate_rejects) == 4, (
        f"其余 4 worker 应都被串行化后看到已审批拒绝，实际 {len(duplicate_rejects)}"
    )


# ─── T2 — yield_standard FOR UPDATE 串行化（PRD-06 / W7-2 二级审批）─────────


async def test_yield_standard_approve_for_update_serializes_n5(session_factory):
    """与 T1 同 pattern — 验证 W7-2 PRD-06 yield_standard 行锁实际生效。"""
    tenant_a = _new_tenant()
    ingredient_id = uuid.uuid4()
    std_id = uuid.uuid4()
    created_by = uuid.uuid4()
    approver_id = uuid.uuid4()

    async with session_factory() as s:
        await s.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_a)})
        await s.execute(
            text("""
                INSERT INTO ingredient_yield_standards (
                    id, tenant_id, ingredient_id, yield_rate,
                    season, effective_from, tolerance_pct, approved_by, approved_at,
                    notes, created_by, created_at, updated_at, is_deleted
                ) VALUES (
                    CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:ing AS uuid), :rate,
                    'all', :today, 5.0, NULL, NULL,
                    NULL, CAST(:by AS uuid), NOW(), NOW(), FALSE
                )
                ON CONFLICT DO NOTHING
            """),
            {
                "id": str(std_id),
                "tid": str(tenant_a),
                "ing": str(ingredient_id),
                "rate": Decimal("0.6500"),
                "today": date(2026, 5, 1),
                "by": str(created_by),
            },
        )
        await s.commit()

    async def _approve(s: AsyncSession) -> bool:
        row = (
            await s.execute(
                text("""
                    SELECT approved_by FROM ingredient_yield_standards
                    WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:tid AS uuid)
                    FOR UPDATE
                """),
                {"id": str(std_id), "tid": str(tenant_a)},
            )
        ).mappings().first()
        if row is None:
            raise ValueError("std 不存在")
        if row["approved_by"] is not None:
            raise ValueError("已审批 — FOR UPDATE 串行化生效")
        await s.execute(
            text("""
                UPDATE ingredient_yield_standards
                SET approved_by = CAST(:by AS uuid),
                    approved_at = NOW(),
                    updated_at  = NOW()
                WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:tid AS uuid)
            """),
            {"by": str(approver_id), "id": str(std_id), "tid": str(tenant_a)},
        )
        return True

    results = await run_concurrent(session_factory, tenant_a, n=5, operation=_approve)
    successes = [r for r in results if r is True]
    duplicate_rejects = [
        r for r in results if isinstance(r, ValueError) and "已审批" in str(r)
    ]
    assert len(successes) == 1
    assert len(duplicate_rejects) == 4


# ─── T3 — delivery_violations UNIQUE 幂等串行化（PRD-05 / W8 关键不变量）────


async def test_delivery_violations_unique_idempotent_n5(session_factory):
    """N=5 workers 并发 record_violation 同一 receiving_order_id → UNIQUE 保证仅 1 条入表。

    PRD-05 关键不变量：supplier_scoring_engine 按 violation count 扣 delivery_rate 分；
    任何并发重试都不可双计，UNIQUE(tenant, receiving_order_id) + ON CONFLICT DO NOTHING 保证。
    """
    tenant_a = _new_tenant()
    supplier_id = uuid.uuid4()
    store_id = uuid.uuid4()
    receiving_order_id = uuid.uuid4()
    window_id = uuid.uuid4()
    signed_at = datetime(2026, 5, 15, 7, 45, tzinfo=timezone.utc)

    async def _record(s: AsyncSession) -> str:
        # ON CONFLICT DO NOTHING — 同 service.record_violation 路径
        row_id = uuid.uuid4()
        result = await s.execute(
            text("""
                INSERT INTO supplier_delivery_violations (
                    id, tenant_id, supplier_id, store_id,
                    receiving_order_id, window_id,
                    scheduled_earliest, scheduled_latest,
                    actual_signed_at, violation_minutes, violation_kind, recorded_at
                ) VALUES (
                    CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:supp AS uuid), CAST(:store AS uuid),
                    CAST(:ord AS uuid), CAST(:win AS uuid),
                    :early, :late, :signed, :minutes, 'late', NOW()
                )
                ON CONFLICT (tenant_id, receiving_order_id) DO NOTHING
                RETURNING id::text
            """),
            {
                "id": str(row_id),
                "tid": str(tenant_a),
                "supp": str(supplier_id),
                "store": str(store_id),
                "ord": str(receiving_order_id),
                "win": str(window_id),
                "early": time(4, 0),
                "late": time(7, 0),
                "signed": signed_at,
                "minutes": 30,
            },
        )
        row = result.mappings().first()
        return row["id"] if row else "CONFLICT"

    results = await run_concurrent(session_factory, tenant_a, n=5, operation=_record)
    exceptions = [r for r in results if isinstance(r, BaseException)]
    assert not exceptions, f"runner exceptions: {exceptions}"

    inserted = [r for r in results if r != "CONFLICT"]
    conflicts = [r for r in results if r == "CONFLICT"]
    assert len(inserted) == 1, (
        f"应仅 1 worker INSERT 成功，实际 {len(inserted)}（UNIQUE 失效或 ON CONFLICT 漂移）"
    )
    assert len(conflicts) == 4

    # 表内 count=1 — 确认 supplier_scoring 不双计
    async with session_factory() as s:
        await s.execute(text("SET LOCAL row_security=off"))
        await assert_final_consistency(
            s,
            "supplier_delivery_violations",
            {"tenant_id": str(tenant_a)},
            {"count": 1},
        )
