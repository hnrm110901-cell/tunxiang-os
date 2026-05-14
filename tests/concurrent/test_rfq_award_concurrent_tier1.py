"""RFQ award 路径 — 真 PG N=10 并发反测（PRD-04 sub-B / #579 闭环）

W9 sub-B Tier 1 关键不变量：award_rfq UNIQUE(tenant_id, rfq_id) + FOR UPDATE 串行化 →
N 路并发 award 同一 rfq 仅 1 个成功，其余 raise/conflict 让出。

  T1 award_rfq N=10 并发同 rfq → 仅 1 成功 + 9 raise "已 award" 拒绝
     (FOR UPDATE 串行化 + UNIQUE(rfq_id) DB-level 双保险)

跑法（同 test_payment_saga_concurrent_tier1.py / PR #642 模式）：

    docker compose -f infra/compose/test-pg.yml up -d
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/db-bootstrap.sh --skip-create
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/migrate-all.sh --include-legacy
    INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        pytest tests/concurrent/test_rfq_award_concurrent_tier1.py -v

未设 INTEGRATION_PG_DSN → 全部 skip（opt-in 模式）。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.test_utils.concurrent_runner import (
    assert_final_consistency,
    run_concurrent,
)
from shared.test_utils.integration_pg import requires_integration_pg

pytestmark = [requires_integration_pg]


# v431 alembic chain drift-tolerant skip 守卫（同 PR #645 W7-W8 supply pattern）
# 若 alembic 漂移阻塞 v431 不应用，RFQ 5 表均不存在 → pytest.skip 整 module
_REQUIRED_TABLES = (
    "rfqs",
    "rfq_items",
    "rfq_invitees",
    "rfq_quotes",
    "rfq_awards",
)


@pytest_asyncio.fixture(autouse=True)
async def _require_rfq_tables(engine):
    """RFQ 5 表都存在才跑 — drift-tolerant skip。"""
    async with engine.begin() as conn:
        missing = []
        for tbl in _REQUIRED_TABLES:
            result = await conn.execute(
                text("SELECT to_regclass(:t)"), {"t": f"public.{tbl}"}
            )
            if result.scalar() is None:
                missing.append(tbl)
    if missing:
        pytest.skip(
            f"RFQ 表 alembic 未应用（drift 阻塞 v431+）: missing {missing}. "
            "drift 修走独立 issue，本 workflow drift-tolerant 跳过。"
        )


def _new_tenant() -> uuid.UUID:
    return uuid.uuid4()


# ─── T1 — award_rfq UNIQUE 幂等 + FOR UPDATE 串行化（PRD-04 #579 关键不变量）──


async def test_rfq_award_for_update_unique_serializes_n10(session_factory):
    """N=10 workers 并发 award 同 rfq → 仅 1 成功，其余 raise "已 award" 拒绝。

    Tier 1 资金路径关键不变量（PRD-04）：
    - FOR UPDATE on rfqs 串行化并发 award (PR-A/B/C/D/E pattern)
    - UNIQUE(tenant_id, rfq_id) on rfq_awards 防重复 INSERT (DB-level 双保险)
    - 状态机校验：status='awarded' 后续并发尝试看到 status 已变 → raise

    防错：双 award 致下游采购单生成两次，资金重复挂账（合规风险 + 资金损失）。
    """
    tenant_a = _new_tenant()
    rfq_id = uuid.uuid4()
    ingredient_id = uuid.uuid4()
    supplier_id = uuid.uuid4()
    quote_id = uuid.uuid4()
    created_by = uuid.uuid4()
    approver_id = uuid.uuid4()  # 与 created_by 不同 — 满足二级审批

    # 准备 — INSERT RFQ + RFQQuote (绕 RLS 用 superuser 引擎)
    async with session_factory() as s:
        await s.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_a)},
        )
        future = datetime.now(timezone.utc) + timedelta(days=7)
        await s.execute(
            text("""
                INSERT INTO rfqs (
                    id, tenant_id, rfq_number, initiator_id, deadline, status,
                    notes, created_by, created_at, updated_at, is_deleted
                ) VALUES (
                    CAST(:id AS uuid), CAST(:tid AS uuid), NULL,
                    CAST(:by AS uuid), :deadline, 'comparing',
                    NULL, CAST(:by AS uuid), NOW(), NOW(), FALSE
                )
                ON CONFLICT DO NOTHING
            """),
            {
                "id": str(rfq_id),
                "tid": str(tenant_a),
                "by": str(created_by),
                "deadline": future,
            },
        )
        await s.execute(
            text("""
                INSERT INTO rfq_quotes (
                    id, tenant_id, rfq_id, supplier_id, ingredient_id,
                    unit_price_fen, qty_offered, valid_until, notes,
                    submitted_at, created_at, updated_at, is_deleted
                ) VALUES (
                    CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:rfq AS uuid),
                    CAST(:supp AS uuid), CAST(:ing AS uuid),
                    88800, NULL, NULL, NULL,
                    NOW(), NOW(), NOW(), FALSE
                )
                ON CONFLICT DO NOTHING
            """),
            {
                "id": str(quote_id),
                "tid": str(tenant_a),
                "rfq": str(rfq_id),
                "supp": str(supplier_id),
                "ing": str(ingredient_id),
            },
        )
        await s.commit()

    async def _award(s: AsyncSession) -> str:
        """模拟 award_rfq 服务路径：FOR UPDATE + 状态检查 + INSERT award + UPDATE rfqs."""
        # 1. SELECT FOR UPDATE 行锁
        row = (
            await s.execute(
                text("""
                    SELECT status, created_by::text AS created_by
                    FROM rfqs
                    WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:tid AS uuid)
                    FOR UPDATE
                """),
                {"id": str(rfq_id), "tid": str(tenant_a)},
            )
        ).mappings().first()
        if row is None:
            raise ValueError("rfq 不存在")
        if row["status"] == "awarded":
            raise ValueError("已 award — FOR UPDATE 串行化生效")

        # 2. INSERT rfq_awards (UNIQUE(tenant_id, rfq_id) 防重复)
        try:
            await s.execute(
                text("""
                    INSERT INTO rfq_awards (
                        id, tenant_id, rfq_id, selected_quote_id, reason,
                        ai_recommendation_followed, approved_by, approved_at,
                        created_by, created_at, updated_at, is_deleted
                    ) VALUES (
                        CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:rfq AS uuid),
                        CAST(:quote AS uuid), 'concurrent race test',
                        NULL, CAST(:apr AS uuid), NOW(),
                        CAST(:by AS uuid), NOW(), NOW(), FALSE
                    )
                """),
                {
                    "id": str(uuid.uuid4()),
                    "tid": str(tenant_a),
                    "rfq": str(rfq_id),
                    "quote": str(quote_id),
                    "apr": str(approver_id),
                    "by": str(created_by),
                },
            )
        except IntegrityError as exc:
            # §19 round-1 P1-B: 具体异常类型 (CLAUDE.md §13 禁 broad except)
            # UNIQUE(tenant_id, rfq_id) 冲突 PG 抛 IntegrityError，但 FOR UPDATE 已串行化通常不应到此
            raise ValueError(f"award INSERT failed: UNIQUE 冲突 {exc.__class__.__name__}") from exc

        # 3. UPDATE rfqs.status = 'awarded'
        await s.execute(
            text("""
                UPDATE rfqs
                SET status = 'awarded', updated_at = NOW()
                WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:tid AS uuid)
                  AND status != 'awarded'
            """),
            {"id": str(rfq_id), "tid": str(tenant_a)},
        )
        return "awarded"

    results = await run_concurrent(session_factory, tenant_a, n=10, operation=_award)

    successes = [r for r in results if r == "awarded"]
    duplicate_rejects = [
        r for r in results
        if isinstance(r, ValueError) and "已 award" in str(r)
    ]
    assert len(successes) == 1, (
        f"应仅 1 个 worker 成功 award，实际 {len(successes)}"
        f"（FOR UPDATE 失效或 PG drift — Tier 1 资金路径重大破坏）"
    )
    assert len(duplicate_rejects) == 9, (
        f"其余 9 worker 应都被串行化后看到已 award 拒绝，实际 {len(duplicate_rejects)}"
    )

    # 表内 rfq_awards count=1 — 确认下游采购单不双发
    async with session_factory() as s:
        await s.execute(text("SET LOCAL row_security=off"))
        await assert_final_consistency(
            s,
            "rfq_awards",
            {"tenant_id": str(tenant_a)},
            {"count": 1},
        )
