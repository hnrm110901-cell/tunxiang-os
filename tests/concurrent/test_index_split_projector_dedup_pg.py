"""IndexSplitProjector F2 P0 dedup 真 PG regression (PRD-11 sub-B.2 / 2026-05-16).

opt-in via INTEGRATION_PG_DSN (与 tests/concurrent/ 其他 tier1 测试同模式, CI 默认 skip).

测试目标 (F2 P0 — sub-B.2 design doc §6 / D2 ① 锁定):
  - INSERT 同 event_id 触 v437 UNIQUE (tenant_id, source_event_id) → IntegrityError
  - projector handle() 在 SQLAlchemy SAVEPOINT 内捕获 → savepoint rollback
  - 同 event 重放 ingredient_transactions row count 不变 (无重复扣料)
  - ingredients.current_quantity 仅一次扣减 (毛利底线硬约束)

业务场景:
  徐记海鲜 200 桌晚高峰, projector OOM 重启后从 checkpoint 重放. 若 F2 dedup 失效
  → 同一 ITEMS_SETTLED 事件触发 N 次 BOM 扣料 → ingredients.current_quantity 错算
  → 毛利底线告警 + 物理库存账实不符. 本测试用单事件双消费验证 v437 UNIQUE 守门.

跑法:
    docker compose -f infra/compose/test-pg.yml up -d
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/db-bootstrap.sh --skip-create
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/migrate-all.sh --include-legacy
    INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        pytest tests/concurrent/test_index_split_projector_dedup_pg.py \\
        --confcutdir tests/concurrent --override-ini asyncio_mode=auto -v

200 桌并发 full regression: P2 follow-up issue (本 PR scope 限 F2 dedup 单 event 路径,
200 桌真并发 deduplication 留 Phase 2 W12 灰度激活前的容量测试 PR).

关联:
  - shared/db-migrations/versions/v437_ingredient_split_attribution_dedup.py
  - services/tx-supply/src/projectors/index_split.py
  - services/tx-supply/src/tests/test_index_split_projector_tier1.py (mock 19 用例)
  - docs/architecture/prd-11-sub-b2-projector-design.md §6 F2
"""
from __future__ import annotations

import os
import sys
import types
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

# ── 路径 + namespace 包 (与 PR-2/3/4 同 pattern) ──────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TX_SUPPLY_DIR = os.path.join(ROOT, "services", "tx-supply")
TX_SUPPLY_SRC = os.path.join(TX_SUPPLY_DIR, "src")
for p in [ROOT, TX_SUPPLY_SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


def _ensure_ns(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]  # type: ignore[attr-defined]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_ns("services", os.path.join(ROOT, "services"))
_ensure_ns("services.tx_supply", TX_SUPPLY_DIR)
_ensure_ns("services.tx_supply.src", TX_SUPPLY_SRC)


# ── opt-in gate (与 tests/concurrent/conftest.py 一致) ────────────────────────
from shared.test_utils.integration_pg import (  # noqa: E402
    INTEGRATION_PG_DSN,
    requires_integration_pg,
)


@pytest_asyncio.fixture
async def seed_fixture(integration_pg_session):  # type: ignore[no-untyped-def]
    """seed: tenant + store + 1 dish + 2 ingredients + dish_ingredients (BOM)."""
    db = integration_pg_session
    tenant_id = uuid.uuid4()
    store_id = uuid.uuid4()
    dish_id = uuid.uuid4()
    ing_fish = uuid.uuid4()
    ing_seasoning = uuid.uuid4()

    await db.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )
    # store
    await db.execute(
        text(
            """
            INSERT INTO stores (id, tenant_id, store_code, store_name, is_deleted)
            VALUES (:id, :t, 'XJ-001', '徐记海鲜测试店', false)
            """
        ),
        {"id": store_id, "t": tenant_id},
    )
    # dish
    await db.execute(
        text(
            """
            INSERT INTO dishes (id, tenant_id, dish_name, is_deleted)
            VALUES (:id, :t, '酸菜鱼-测试', false)
            """
        ),
        {"id": dish_id, "t": tenant_id},
    )
    # ingredients (current_quantity 高于扣料量, 验证扣减后差值)
    for ing_id, name, qty, unit_price in [
        (ing_fish, "黑鱼", 100.0, 5000),
        (ing_seasoning, "酸菜底料", 50.0, 200),
    ]:
        await db.execute(
            text(
                """
                INSERT INTO ingredients
                    (id, tenant_id, store_id, ingredient_name, current_quantity,
                     min_quantity, unit, unit_price_fen, status, is_deleted)
                VALUES (:id, :t, :s, :n, :q, 0, '份', :up, 'normal', false)
                """
            ),
            {
                "id": ing_id,
                "t": tenant_id,
                "s": store_id,
                "n": name,
                "q": qty,
                "up": unit_price,
            },
        )
    # BOM
    for ing_id, qty_per_dish in [(ing_fish, 0.5), (ing_seasoning, 0.1)]:
        await db.execute(
            text(
                """
                INSERT INTO dish_ingredients
                    (id, tenant_id, dish_id, ingredient_id, ingredient_name,
                     quantity, unit, is_deleted)
                VALUES (gen_random_uuid(), :t, :d, :i, '_', :q, '份', false)
                """
            ),
            {"t": tenant_id, "d": dish_id, "i": str(ing_id), "q": qty_per_dish},
        )
    await db.commit()
    return {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "dish_id": dish_id,
        "ingredients": [ing_fish, ing_seasoning],
    }


@pytest.mark.asyncio
@requires_integration_pg
async def test_f2_dedup_same_event_replay_no_duplicate_deduction(
    integration_pg_session, seed_fixture
):  # type: ignore[no-untyped-def]
    """F2 P0: 同 event_id 重放两次 — ingredient_transactions 行数与扣减量都只算一次.

    步骤:
      1. 调 deduct_for_order(source_event_id=E) 完成扣料 (5 BOM 行 INSERT)
      2. 再次调 deduct_for_order(source_event_id=E) 同参数 — v437 UNIQUE 命中
         IntegrityError, savepoint rollback
      3. 断言 ingredient_transactions WHERE source_event_id=E count=2 (两个 BOM 行),
         current_quantity 仅扣减一次差值
    """
    from sqlalchemy.exc import IntegrityError as _IE

    from services.tx_supply.src.services.auto_deduction import deduct_for_order

    db = integration_pg_session
    s = seed_fixture
    tenant_str = str(s["tenant_id"])
    store_str = str(s["store_id"])
    event_id = uuid.uuid4()
    order_id = uuid.uuid4()
    order_item_id = uuid.uuid4()

    # Step 1: 首次消费
    async with db.begin():
        await deduct_for_order(
            order_id=str(order_id),
            order_items=[
                {
                    "dish_id": str(s["dish_id"]),
                    "quantity": 1,
                    "order_item_id": str(order_item_id),
                    "share_split": {"method": "even", "count": 2},
                }
            ],
            store_id=store_str,
            tenant_id=tenant_str,
            db=db,
            source_event_id=event_id,
        )

    await db.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_str}
    )
    rows_after_1 = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) FROM ingredient_transactions
                WHERE tenant_id = :t AND source_event_id IS NOT NULL
                """
            ),
            {"t": s["tenant_id"]},
        )
    ).scalar_one()
    assert rows_after_1 == 2, f"首次消费应写 2 行 BOM, 实际 {rows_after_1}"

    # Step 2: 重放同 event_id — 期待 IntegrityError, savepoint rollback
    raised = False
    try:
        async with db.begin():
            await deduct_for_order(
                order_id=str(order_id),
                order_items=[
                    {
                        "dish_id": str(s["dish_id"]),
                        "quantity": 1,
                        "order_item_id": str(order_item_id),
                        "share_split": {"method": "even", "count": 2},
                    }
                ],
                store_id=store_str,
                tenant_id=tenant_str,
                db=db,
                source_event_id=event_id,
            )
    except _IE:
        raised = True
    assert raised, "重放同 event_id 应触发 v437 UNIQUE IntegrityError"

    # Step 3: 行数不变 (UNIQUE 守门有效)
    await db.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_str}
    )
    rows_after_2 = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) FROM ingredient_transactions
                WHERE tenant_id = :t AND source_event_id IS NOT NULL
                """
            ),
            {"t": s["tenant_id"]},
        )
    ).scalar_one()
    assert rows_after_2 == 2, (
        f"重放后行数应保持 2, 实际 {rows_after_2} — v437 UNIQUE 守门失效"
    )

    # 验证 current_quantity 仅扣减一次
    qty = (
        await db.execute(
            text(
                "SELECT current_quantity FROM ingredients WHERE id = :i"
            ),
            {"i": s["ingredients"][0]},
        )
    ).scalar_one()
    assert qty == 99.5, f"current_quantity 应仅扣减一次 (100 - 0.5 = 99.5), 实际 {qty}"


@pytest.mark.asyncio
@requires_integration_pg
async def test_f2_distinct_events_no_collision(
    integration_pg_session, seed_fixture
):  # type: ignore[no-untyped-def]
    """不同 event_id 互不影响 — projector 处理 N 个不同 event 全部成功扣料."""
    from services.tx_supply.src.services.auto_deduction import deduct_for_order

    db = integration_pg_session
    s = seed_fixture
    tenant_str = str(s["tenant_id"])
    store_str = str(s["store_id"])

    for _ in range(3):
        event_id = uuid.uuid4()
        async with db.begin():
            await deduct_for_order(
                order_id=str(uuid.uuid4()),
                order_items=[
                    {
                        "dish_id": str(s["dish_id"]),
                        "quantity": 1,
                        "order_item_id": str(uuid.uuid4()),
                        "share_split": {"method": "even", "count": 2},
                    }
                ],
                store_id=store_str,
                tenant_id=tenant_str,
                db=db,
                source_event_id=event_id,
            )

    await db.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_str}
    )
    rows = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) FROM ingredient_transactions
                WHERE tenant_id = :t AND source_event_id IS NOT NULL
                """
            ),
            {"t": s["tenant_id"]},
        )
    ).scalar_one()
    assert rows == 6, f"3 个不同 event * 2 BOM 行 = 6, 实际 {rows}"
