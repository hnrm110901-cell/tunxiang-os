"""
清理演示数据脚本
删除所有 demo/seed 虚假数据，保留真实商户数据。

清理目标：
  - 闲庭食记演示数据（brand_id=B001_XIANTIN，stores XT001-XT010）
  - seed_database.py 创建的测试门店（STORE001, STORE002, STORE003 等）
  - 相关员工、订单、库存、排班、KPI 等子数据（CASCADE 删除）

运行方式（在 apps/api-gateway 目录下）：
  DATABASE_URL='postgresql+asyncpg://...' python scripts/cleanup_demo_data.py

  或在生产容器内：
  docker exec -it zhilian-api python scripts/cleanup_demo_data.py
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

for _k, _v in {
    "DATABASE_URL":          os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/zhilian_os"),
    "REDIS_URL":             os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    "CELERY_BROKER_URL":     os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    "CELERY_RESULT_BACKEND": os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
    "SECRET_KEY":            os.getenv("SECRET_KEY", "dev-secret"),
    "JWT_SECRET":            os.getenv("JWT_SECRET", "dev-jwt"),
}.items():
    os.environ.setdefault(_k, _v)

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# ──────────────────────────────────────────────────────────────────────────────
# 演示数据标识
# ──────────────────────────────────────────────────────────────────────────────

# 闲庭食记
DEMO_BRAND_IDS = ["B001_XIANTIN"]
DEMO_GROUP_IDS = ["GRP_XIANTIN"]
DEMO_STORE_IDS_XIANTIN = [f"XT{str(i).zfill(3)}" for i in range(1, 11)]

# seed_database.py 创建的测试数据
SEED_STORE_IDS = ["STORE001", "STORE002", "STORE003", "STORE_001", "STORE_002"]
SEED_BRAND_IDS = ["BRAND001", "BRAND_001", "B001"]
SEED_GROUP_IDS = ["GROUP001", "GROUP_001", "GRP001"]
SEED_USER_NAMES = ["test_admin", "demo_admin", "test_user", "demo_user"]

ALL_DEMO_STORE_IDS = DEMO_STORE_IDS_XIANTIN + SEED_STORE_IDS

# ──────────────────────────────────────────────────────────────────────────────

async def cleanup(conn):
    print("[cleanup] 开始清理演示数据...")

    # 构建占位符
    store_placeholders = ", ".join(f":s{i}" for i in range(len(ALL_DEMO_STORE_IDS)))
    store_params = {f"s{i}": sid for i, sid in enumerate(ALL_DEMO_STORE_IDS)}

    brand_ids_all = DEMO_BRAND_IDS + SEED_BRAND_IDS
    brand_placeholders = ", ".join(f":b{i}" for i in range(len(brand_ids_all)))
    brand_params = {f"b{i}": bid for i, bid in enumerate(brand_ids_all)}

    group_ids_all = DEMO_GROUP_IDS + SEED_GROUP_IDS
    group_placeholders = ", ".join(f":g{i}" for i in range(len(group_ids_all)))
    group_params = {f"g{i}": gid for i, gid in enumerate(group_ids_all)}

    # ── 按依赖顺序删除子表 ─────────────────────────────────────────────────────

    tables_by_store = [
        # 订单相关
        "order_items",
        "orders",
        # 库存
        "inventory_transactions",
        "inventory_items",
        # 排班
        "schedule_shifts",
        "schedules",
        # 员工
        "employees",
        # KPI / 损耗 / 能耗
        "kpis",
        "waste_events",
        "energy_readings",
        # 会员 / 私域
        "member_transactions",
        "members",
        # 宴会
        "banquet_reservations",
        # 通知
        "notifications",
        # AI决策日志
        "decision_logs",
        # 集成
        "external_systems",
    ]

    total_deleted = 0

    for table in tables_by_store:
        try:
            r = await conn.execute(
                text(f"DELETE FROM {table} WHERE store_id IN ({store_placeholders})"),
                store_params,
            )
            if r.rowcount:
                print(f"  [{table}] 删除 {r.rowcount} 行")
                total_deleted += r.rowcount
        except Exception as e:
            # 表不存在或无 store_id 列，跳过
            print(f"  [{table}] 跳过（{e}）")

    # ── 按品牌删除 ────────────────────────────────────────────────────────────

    tables_by_brand = [
        "dishes",
        "dish_masters",
        "bom_templates",
        "ingredient_masters",
        "menu_items",
    ]

    for table in tables_by_brand:
        try:
            r = await conn.execute(
                text(f"DELETE FROM {table} WHERE brand_id IN ({brand_placeholders})"),
                brand_params,
            )
            if r.rowcount:
                print(f"  [{table}/brand] 删除 {r.rowcount} 行")
                total_deleted += r.rowcount
        except Exception as e:
            print(f"  [{table}/brand] 跳过（{e}）")

    # ── 删除门店主表 ──────────────────────────────────────────────────────────

    try:
        r = await conn.execute(
            text(f"DELETE FROM stores WHERE id IN ({store_placeholders})"),
            store_params,
        )
        print(f"  [stores] 删除 {r.rowcount} 行")
        total_deleted += r.rowcount
    except Exception as e:
        print(f"  [stores] 错误: {e}")

    # ── 删除演示用户 ──────────────────────────────────────────────────────────

    user_placeholders = ", ".join(f":u{i}" for i in range(len(SEED_USER_NAMES)))
    user_params = {f"u{i}": n for i, n in enumerate(SEED_USER_NAMES)}
    try:
        r = await conn.execute(
            text(f"DELETE FROM users WHERE username IN ({user_placeholders}) OR brand_id IN ({brand_placeholders})"),
            {**user_params, **brand_params},
        )
        print(f"  [users] 删除 {r.rowcount} 行")
        total_deleted += r.rowcount
    except Exception as e:
        print(f"  [users] 跳过（{e}）")

    # ── 删除品牌 ──────────────────────────────────────────────────────────────

    try:
        r = await conn.execute(
            text(f"DELETE FROM brands WHERE brand_id IN ({brand_placeholders})"),
            brand_params,
        )
        print(f"  [brands] 删除 {r.rowcount} 行")
        total_deleted += r.rowcount
    except Exception as e:
        print(f"  [brands] 跳过（{e}）")

    # ── 删除集团 ──────────────────────────────────────────────────────────────

    try:
        r = await conn.execute(
            text(f"DELETE FROM groups WHERE group_id IN ({group_placeholders})"),
            group_params,
        )
        print(f"  [groups] 删除 {r.rowcount} 行")
        total_deleted += r.rowcount
    except Exception as e:
        print(f"  [groups] 跳过（{e}）")

    print(f"\n[cleanup] 完成！共删除 {total_deleted} 行演示数据。")
    print("[cleanup] 真实商户数据（BRD_CZYZ0001 / BRD_ZQX0001 / BRD_SGC0001）保持不变。")


async def main():
    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await cleanup(conn)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
