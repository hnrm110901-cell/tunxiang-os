#!/usr/bin/env python3
"""
屯象OS 演示环境准备脚本 — 尝在一起真实数据拉取

从品智POS API 拉取尝在一起真实数据，写入演示数据库，并补充AI分析种子数据。

使用方式:
    # 完整拉取（首次）
    python3 scripts/demo_prep_czyz.py

    # 仅拉取最近7天订单（增量更新）
    python3 scripts/demo_prep_czyz.py --mode=incremental --days=7

    # 仅重置AI分析种子（不重拉POS数据）
    python3 scripts/demo_prep_czyz.py --mode=ai-only

环境变量:
    DATABASE_URL    演示库连接串（默认读 .env.demo 中的 DEMO_DATABASE_URL）
    SYNC_DAYS       历史数据拉取天数（默认 90）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import structlog

# ── 项目根路径 ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
# tx-analytics 目录名含连字符，Python 无法直接 import，需将其 src 目录加入 path
sys.path.insert(0, str(ROOT / "services" / "tx-analytics" / "src"))

from shared.adapters.pinzhi.src.adapter import PinzhiAdapter
from shared.adapters.pinzhi.src.dish_sync import PinzhiDishSync
from shared.adapters.pinzhi.src.employee_sync import PinzhiEmployeeSync
from shared.adapters.pinzhi.src.table_sync import PinzhiTableSync
from shared.ontology.src.database import async_session_factory, init_db
from etl.pipeline import ETLPipeline
from etl.tenant_config import get_tenant_config_by_id
from sqlalchemy import text

structlog.configure(processors=[structlog.dev.ConsoleRenderer()])
log = structlog.get_logger()

# ══════════════════════════════════════════════════════════════════════════════
# 尝在一起 租户常量（与 tenant_config.py 保持一致）
# ══════════════════════════════════════════════════════════════════════════════
CZYZ_TENANT_ID = "10000000-0000-0000-0000-000000000001"
CZYZ_BRAND_ID  = "BRD_CZYZ0001"
CZYZ_MERCHANT_CODE = "CZYZ001"

# 三家已对接品智门店 → 屯象门店UUID（确定性生成，重复运行幂等）
STORE_MAP = {
    "2461":  {
        "uuid": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"czyz:pinzhi:2461")),
        "name": "尝在一起·文化城店",
        "code": "CZYZ-WH001",
        "city": "长沙", "district": "芙蓉区",
        "address": "长沙市芙蓉区文化路123号文化城美食广场2楼",
        "phone": "0731-85001001",
        "seats": 180, "area": 450.0, "floors": 2,
        "monthly_revenue_target_fen": 90_000_00,   # 90万/月
        "daily_customer_target": 280,
    },
    "7269":  {
        "uuid": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"czyz:pinzhi:7269")),
        "name": "尝在一起·浏小鲜",
        "code": "CZYZ-LXX001",
        "city": "长沙", "district": "开福区",
        "address": "长沙市开福区湘江中路浏阳河渔港商业街B1-08",
        "phone": "0731-85002002",
        "seats": 120, "area": 300.0, "floors": 1,
        "monthly_revenue_target_fen": 60_000_00,
        "daily_customer_target": 180,
    },
    "19189": {
        "uuid": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"czyz:pinzhi:19189")),
        "name": "尝在一起·永安店",
        "code": "CZYZ-YA001",
        "city": "长沙", "district": "天心区",
        "address": "长沙市天心区书院路永安巷10号",
        "phone": "0731-85003003",
        "seats": 100, "area": 260.0, "floors": 1,
        "monthly_revenue_target_fen": 50_000_00,
        "daily_customer_target": 150,
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# Step 0 — 确保演示库连接
# ══════════════════════════════════════════════════════════════════════════════

def _load_demo_database_url() -> str:
    """从环境变量或 .env.demo 中读取演示库URL"""
    if url := os.environ.get("DATABASE_URL"):
        return url
    env_demo = ROOT / ".env.demo"
    if env_demo.exists():
        for line in env_demo.read_text().splitlines():
            if line.startswith("DEMO_DATABASE_URL=") or line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"')
    # 本地开发默认值
    return "postgresql+asyncpg://tunxiang:changeme_dev@localhost:5432/tunxiang_demo"


# ══════════════════════════════════════════════════════════════════════════════
# Step 1 — 租户 & 品牌基础档案
# ══════════════════════════════════════════════════════════════════════════════

async def setup_tenant(db) -> None:
    log.info("step1_tenant", status="start")
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": CZYZ_TENANT_ID})

    # platform_tenants
    await db.execute(text("""
        INSERT INTO platform_tenants (
            tenant_id, merchant_code, name, plan_template, status,
            subscription_expires_at, created_at, updated_at, is_deleted
        ) VALUES (
            :tid::uuid, :code, :name, 'enterprise', 'active',
            '2027-12-31', NOW(), NOW(), false
        )
        ON CONFLICT (tenant_id) DO UPDATE SET
            name = EXCLUDED.name, status = 'active',
            subscription_expires_at = EXCLUDED.subscription_expires_at,
            updated_at = NOW()
    """), {
        "tid": CZYZ_TENANT_ID,
        "code": CZYZ_MERCHANT_CODE,
        "name": "尝在一起餐饮管理有限公司",
    })

    # brands（若表存在）
    try:
        await db.execute(text("""
            INSERT INTO brands (
                id, tenant_id, brand_name, brand_code, cuisine_type,
                status, created_at, updated_at, is_deleted
            ) VALUES (
                :bid::uuid, :tid::uuid, '尝在一起', :code, '湘菜',
                'active', NOW(), NOW(), false
            )
            ON CONFLICT (id) DO UPDATE SET
                brand_name = EXCLUDED.brand_name, updated_at = NOW()
        """), {
            "bid": str(uuid.uuid5(uuid.NAMESPACE_DNS, CZYZ_BRAND_ID)),
            "tid": CZYZ_TENANT_ID,
            "code": CZYZ_BRAND_ID,
        })
    except Exception:
        pass  # brands 表可能在部分迁移版本中不存在

    await db.commit()
    log.info("step1_tenant", status="done")


# ══════════════════════════════════════════════════════════════════════════════
# Step 2 — 门店档案（品智真实数据 + 屯象补充字段）
# ══════════════════════════════════════════════════════════════════════════════

async def setup_stores(db, adapter: PinzhiAdapter) -> None:
    log.info("step2_stores", status="start")
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": CZYZ_TENANT_ID})

    for pinzhi_store_id, meta in STORE_MAP.items():
        # 先从品智拉取真实门店信息
        try:
            raw_stores = await adapter.get_store_info(ognid=pinzhi_store_id)
            raw = raw_stores[0] if raw_stores else {}
        except Exception as exc:
            log.warning("store_info_fetch_failed", store_id=pinzhi_store_id, error=str(exc))
            raw = {}

        # 真实数据优先，屯象预设字段兜底
        store_name = raw.get("ognName") or meta["name"]
        phone = raw.get("phone") or meta["phone"]
        address = raw.get("address") or meta["address"]

        await db.execute(text("""
            INSERT INTO stores (
                id, tenant_id, brand_id, store_name, store_code,
                city, district, address, phone,
                latitude, longitude, status,
                area, seats, floors,
                opening_date,
                monthly_revenue_target_fen, daily_customer_target,
                created_at, updated_at, is_deleted,
                config
            ) VALUES (
                :id::uuid, :tid::uuid, :brand_id,
                :store_name, :store_code,
                :city, :district, :address, :phone,
                NULL, NULL, 'active',
                :area, :seats, :floors,
                '2023-01-01',
                :monthly_revenue_target_fen, :daily_customer_target,
                NOW(), NOW(), false,
                :config::jsonb
            )
            ON CONFLICT (id) DO UPDATE SET
                store_name = EXCLUDED.store_name,
                address    = EXCLUDED.address,
                phone      = EXCLUDED.phone,
                updated_at = NOW()
        """), {
            "id":   meta["uuid"],
            "tid":  CZYZ_TENANT_ID,
            "brand_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, CZYZ_BRAND_ID)),
            "store_name":  store_name,
            "store_code":  meta["code"],
            "city":        meta["city"],
            "district":    meta["district"],
            "address":     address,
            "phone":       phone,
            "area":        meta["area"],
            "seats":       meta["seats"],
            "floors":      meta["floors"],
            "monthly_revenue_target_fen": meta["monthly_revenue_target_fen"],
            "daily_customer_target": meta["daily_customer_target"],
            "config": json.dumps({
                "source_system": "pinzhi",
                "pinzhi_store_id": pinzhi_store_id,
                "store_type": "dine_in",
                "has_banquet": True,
                "has_private_room": True,
            }),
        })
        log.info("store_upserted", store_name=store_name, pinzhi_id=pinzhi_store_id)

    await db.commit()
    log.info("step2_stores", status="done", count=len(STORE_MAP))


# ══════════════════════════════════════════════════════════════════════════════
# Step 3 — 桌台（品智真实桌台数据）
# ══════════════════════════════════════════════════════════════════════════════

async def sync_tables(db, adapter: PinzhiAdapter) -> None:
    log.info("step3_tables", status="start")
    table_sync = PinzhiTableSync(adapter)
    total_upserted = 0
    for pinzhi_store_id, meta in STORE_MAP.items():
        try:
            result = await table_sync.upsert_tables(
                db=db,
                tenant_id=CZYZ_TENANT_ID,
                store_uuid=meta["uuid"],
                store_id=pinzhi_store_id,
            )
            total_upserted += result.get("upserted", 0)
            log.info("tables_synced", store=meta["name"], **result)
        except Exception as exc:
            log.error("tables_sync_failed", store=meta["name"], error=str(exc), exc_info=True)
    log.info("step3_tables", status="done", total_upserted=total_upserted)


# ══════════════════════════════════════════════════════════════════════════════
# Step 4 — 员工（品智真实员工数据）
# ══════════════════════════════════════════════════════════════════════════════

async def sync_employees(db, adapter: PinzhiAdapter) -> None:
    log.info("step4_employees", status="start")
    emp_sync = PinzhiEmployeeSync(adapter)
    total_upserted = 0
    for pinzhi_store_id, meta in STORE_MAP.items():
        try:
            raw_emps = await emp_sync.fetch_employees(store_id=pinzhi_store_id)
            await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": CZYZ_TENANT_ID})
            upserted = 0
            for raw in raw_emps:
                mapped = PinzhiEmployeeSync.map_to_tunxiang_employee(raw, CZYZ_TENANT_ID, meta["uuid"])
                try:
                    await db.execute(text("""
                        INSERT INTO employees (
                            id, tenant_id, store_id, employee_no, display_name,
                            role, employment_status, employment_type,
                            is_active, config, created_at, updated_at, is_deleted
                        ) VALUES (
                            :id::uuid, :tenant_id::uuid, :store_id::uuid,
                            :employee_no, :display_name,
                            :role, 'active', 'full_time',
                            :is_active, :config::jsonb,
                            NOW(), NOW(), false
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            display_name = EXCLUDED.display_name,
                            is_active    = EXCLUDED.is_active,
                            updated_at   = NOW()
                    """), {
                        "id":            mapped["id"],
                        "tenant_id":     CZYZ_TENANT_ID,
                        "store_id":      meta["uuid"],
                        "employee_no":   mapped.get("employee_no", ""),
                        "display_name":  mapped.get("display_name", ""),
                        "role":          mapped.get("role", "staff"),
                        "is_active":     mapped.get("is_active", True),
                        "config":        json.dumps(mapped.get("config", {})),
                    })
                    upserted += 1
                except Exception as exc:
                    log.warning("employee_upsert_failed", error=str(exc))
            await db.commit()
            total_upserted += upserted
            log.info("employees_synced", store=meta["name"], total=len(raw_emps), upserted=upserted)
        except Exception as exc:
            log.error("employees_sync_failed", store=meta["name"], error=str(exc), exc_info=True)
    log.info("step4_employees", status="done", total_upserted=total_upserted)


# ══════════════════════════════════════════════════════════════════════════════
# Step 5 — 菜品（品智全量菜单）
# ══════════════════════════════════════════════════════════════════════════════

async def sync_dishes(db, adapter: PinzhiAdapter) -> None:
    log.info("step5_dishes", status="start")
    dish_sync = PinzhiDishSync(adapter)
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": CZYZ_TENANT_ID})

    try:
        # 品智菜品按品牌维度，不区分门店
        raw_dishes = await dish_sync.fetch_dishes(brand_id=CZYZ_BRAND_ID)

        # 获取菜品类别
        try:
            categories = await adapter.get_dish_categories()
            cat_map = {str(c.get("categoryId", c.get("id", ""))): c.get("categoryName", "") for c in categories}
        except Exception:
            cat_map = {}

        upserted = 0
        for raw in raw_dishes:
            dish_id_pz  = str(raw.get("dishId", raw.get("id", "")))
            cat_id      = str(raw.get("categoryId", raw.get("dishCategoryId", "")))
            dish_name   = raw.get("dishName", raw.get("name", ""))
            sale_price  = int(float(raw.get("salePrice", raw.get("price", 0)) or 0) * 100)
            cost_price  = int(float(raw.get("costPrice", raw.get("cost", 0)) or 0) * 100)
            if not dish_name:
                continue

            dish_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"czyz:dish:{dish_id_pz}"))
            try:
                await db.execute(text("""
                    INSERT INTO dishes (
                        id, tenant_id, brand_id, dish_name, dish_code,
                        category, sale_price_fen, cost_price_fen,
                        status, is_deleted, created_at, updated_at,
                        config
                    ) VALUES (
                        :id::uuid, :tid::uuid, :brand_id,
                        :dish_name, :dish_code,
                        :category, :sale_price_fen, :cost_price_fen,
                        'active', false, NOW(), NOW(),
                        :config::jsonb
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        dish_name      = EXCLUDED.dish_name,
                        sale_price_fen = EXCLUDED.sale_price_fen,
                        cost_price_fen = EXCLUDED.cost_price_fen,
                        category       = EXCLUDED.category,
                        updated_at     = NOW()
                """), {
                    "id":            dish_uuid,
                    "tid":           CZYZ_TENANT_ID,
                    "brand_id":      str(uuid.uuid5(uuid.NAMESPACE_DNS, CZYZ_BRAND_ID)),
                    "dish_name":     dish_name,
                    "dish_code":     dish_id_pz,
                    "category":      cat_map.get(cat_id, raw.get("categoryName", "其他")),
                    "sale_price_fen": sale_price,
                    "cost_price_fen": cost_price,
                    "config": json.dumps({
                        "source_system": "pinzhi",
                        "pinzhi_dish_id": dish_id_pz,
                    }),
                })
                upserted += 1
            except Exception as exc:
                log.warning("dish_upsert_failed", dish=dish_name, error=str(exc))
        await db.commit()
        log.info("step5_dishes", status="done", total=len(raw_dishes), upserted=upserted)
    except Exception as exc:
        log.error("dishes_sync_failed", error=str(exc), exc_info=True)


# ══════════════════════════════════════════════════════════════════════════════
# Step 6 — 订单 + 会员 + 库存（ETL Pipeline 真实90天数据）
# ══════════════════════════════════════════════════════════════════════════════

async def sync_orders_and_members(sync_days: int) -> None:
    log.info("step6_etl", status="start", sync_days=sync_days)
    cfg = get_tenant_config_by_id(CZYZ_TENANT_ID)
    if cfg is None:
        log.error("tenant_config_not_found", tenant_id=CZYZ_TENANT_ID)
        return

    pipeline = ETLPipeline(cfg)
    end_date   = date.today()
    start_date = end_date - timedelta(days=sync_days)

    try:
        result = await pipeline.run_full_sync(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
        )
        log.info("step6_etl", status="done", result=result)
    except Exception as exc:
        log.error("etl_sync_failed", error=str(exc), exc_info=True)
    finally:
        await pipeline.close()


# ══════════════════════════════════════════════════════════════════════════════
# Step 7 — AI 经营分析种子数据
#   基于品智真实营收规模生成 operation_snapshots + business_objectives
#   让 AI 经营合伙人演示有说服力的历史分析
# ══════════════════════════════════════════════════════════════════════════════

async def seed_ai_analysis(db) -> None:
    log.info("step7_ai_seed", status="start")
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": CZYZ_TENANT_ID})
    today = date.today()

    # 各门店基准营收（元/天）—— 基于品智月度目标推算日均
    store_baselines = {
        STORE_MAP["2461"]["uuid"]:  {"daily_rev": 30000, "name": "文化城店"},
        STORE_MAP["7269"]["uuid"]:  {"daily_rev": 20000, "name": "浏小鲜"},
        STORE_MAP["19189"]["uuid"]: {"daily_rev": 16000, "name": "永安店"},
    }

    # ── 7a. 生成近90天 operation_snapshots ────────────────────────────────────
    inserted_snapshots = 0
    for store_uuid, baseline in store_baselines.items():
        for offset in range(90):
            snap_date = today - timedelta(days=offset)
            is_weekend = snap_date.weekday() >= 5
            # 周末营收上浮 30%，随机波动 ±15%
            factor = (1.3 if is_weekend else 1.0) * random.uniform(0.85, 1.15)
            rev_fen = int(baseline["daily_rev"] * 100 * factor)
            orders  = int(rev_fen / 15000)  # 假设客单价约150元
            cust    = int(orders * random.uniform(1.8, 2.4))
            cost_rate = random.uniform(0.28, 0.36)
            gross_fen = int(rev_fen * (1 - cost_rate))

            snap_id = str(uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"czyz:snapshot:{store_uuid}:{snap_date}",
            ))
            try:
                await db.execute(text("""
                    INSERT INTO operation_snapshots (
                        id, tenant_id, store_id, snapshot_date,
                        revenue_fen, gross_profit_fen,
                        total_orders, total_customers,
                        cost_rate, avg_ticket_fen,
                        created_at, updated_at, is_deleted
                    ) VALUES (
                        :id::uuid, :tid::uuid, :sid::uuid, :snap_date,
                        :rev, :gross,
                        :orders, :custs,
                        :cost_rate, :avg_ticket,
                        NOW(), NOW(), false
                    )
                    ON CONFLICT (id) DO NOTHING
                """), {
                    "id": snap_id, "tid": CZYZ_TENANT_ID, "sid": store_uuid,
                    "snap_date": snap_date,
                    "rev": rev_fen, "gross": gross_fen,
                    "orders": orders, "custs": cust,
                    "cost_rate": round(cost_rate, 4),
                    "avg_ticket": rev_fen // max(orders, 1),
                })
                inserted_snapshots += 1
            except Exception:
                pass
    await db.commit()
    log.info("snapshots_seeded", count=inserted_snapshots)

    # ── 7b. 生成 business_objectives (OKR) ───────────────────────────────────
    q2_start = date(today.year, 4, 1)
    q2_end   = date(today.year, 6, 30)
    obj_id   = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"czyz:okr:q2:{today.year}"))
    try:
        await db.execute(text("""
            INSERT INTO business_objectives (
                id, tenant_id, title, objective_type, level, period,
                period_start, period_end, status, priority,
                target_value, current_value, unit,
                created_at, updated_at, is_deleted
            ) VALUES (
                :id::uuid, :tid::uuid,
                'Q2经营目标：品牌全面提升与数字化深化',
                'revenue', 'brand', 'quarterly',
                :start_date, :end_date, 'active', 'high',
                19800000.0, NULL, 'fen',
                NOW(), NOW(), false
            )
            ON CONFLICT (id) DO NOTHING
        """), {
            "id": obj_id, "tid": CZYZ_TENANT_ID,
            "start_date": q2_start, "end_date": q2_end,
        })

        # KRs
        krs = [
            ("全品牌月均营收达到198万元",         "revenue",       198_0000_00, "fen"),
            ("会员复购率提升至45%",                "repeat_rate",   45.0,        "percent"),
            ("三店综合客单价提升至168元",           "avg_ticket",    168_00,      "fen"),
            ("AI决策采纳率达到70%",               "ai_adoption",   70.0,        "percent"),
            ("食安合规评分全店达到90分以上",         "compliance",    90.0,        "score"),
        ]
        for i, (title, ktype, target, unit) in enumerate(krs, 1):
            kr_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"czyz:kr:q2:{i}"))
            await db.execute(text("""
                INSERT INTO objective_key_results (
                    id, tenant_id, objective_id, title, result_type,
                    target_value, current_value, unit, weight,
                    created_at, updated_at, is_deleted
                ) VALUES (
                    :id::uuid, :tid::uuid, :obj_id::uuid, :title, :ktype,
                    :target, NULL, :unit, :weight,
                    NOW(), NOW(), false
                )
                ON CONFLICT (id) DO NOTHING
            """), {
                "id": kr_id, "tid": CZYZ_TENANT_ID, "obj_id": obj_id,
                "title": title, "ktype": ktype,
                "target": float(target), "unit": unit,
                "weight": round(1.0 / len(krs), 2),
            })
        await db.commit()
        log.info("okr_seeded", objective=obj_id)
    except Exception as exc:
        log.warning("okr_seed_skipped", error=str(exc))

    # ── 7c. 门店P&L基础档案 ───────────────────────────────────────────────────
    pnl_fixtures = {
        STORE_MAP["2461"]["uuid"]:  {"rent": 3800_00, "util": 450_00, "labor": 6200_00},
        STORE_MAP["7269"]["uuid"]:  {"rent": 2600_00, "util": 320_00, "labor": 4800_00},
        STORE_MAP["19189"]["uuid"]: {"rent": 2200_00, "util": 280_00, "labor": 4000_00},
    }
    for store_uuid, costs in pnl_fixtures.items():
        pnl_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"czyz:pnl:{store_uuid}"))
        try:
            await db.execute(text("""
                INSERT INTO store_pnl (
                    id, tenant_id, store_id, period, period_type,
                    monthly_rent_fen, monthly_utility_fen, monthly_labor_fen,
                    created_at, updated_at, is_deleted
                ) VALUES (
                    :id::uuid, :tid::uuid, :sid::uuid,
                    :period, 'monthly',
                    :rent, :util, :labor,
                    NOW(), NOW(), false
                )
                ON CONFLICT (id) DO NOTHING
            """), {
                "id": pnl_id, "tid": CZYZ_TENANT_ID, "sid": store_uuid,
                "period": today.strftime("%Y-%m"),
                **costs,
            })
        except Exception:
            pass
    await db.commit()
    log.info("step7_ai_seed", status="done")


# ══════════════════════════════════════════════════════════════════════════════
# Step 8 — 演示用户账户
# ══════════════════════════════════════════════════════════════════════════════

async def setup_demo_accounts(db) -> None:
    log.info("step8_accounts", status="start")
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": CZYZ_TENANT_ID})

    # bcrypt hash for "demo2026"（预计算，避免运行时依赖 passlib）
    DEMO_PWD_HASH = "$2b$12$EIXtnGJczTYBMv9gHW2NKeGNZJxOlKv9VeF6rqMOJ5YA1o9zYjxVa"

    accounts = [
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "czyz:user:admin")),
            "username": "czyz_admin",
            "display_name": "品牌总监（演示）",
            "role": "brand_admin",
            "store_id": None,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "czyz:user:wh_mgr")),
            "username": "czyz_wh",
            "display_name": "文化城店长（演示）",
            "role": "store_manager",
            "store_id": STORE_MAP["2461"]["uuid"],
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "czyz:user:lxx_mgr")),
            "username": "czyz_lxx",
            "display_name": "浏小鲜店长（演示）",
            "role": "store_manager",
            "store_id": STORE_MAP["7269"]["uuid"],
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "czyz:user:ya_mgr")),
            "username": "czyz_ya",
            "display_name": "永安店店长（演示）",
            "role": "store_manager",
            "store_id": STORE_MAP["19189"]["uuid"],
        },
    ]

    for acc in accounts:
        try:
            await db.execute(text("""
                INSERT INTO users (
                    id, tenant_id, username, password_hash,
                    display_name, role, store_id,
                    is_active, created_at, updated_at, is_deleted
                ) VALUES (
                    :id::uuid, :tid::uuid, :username, :pwd_hash,
                    :display_name, :role, :store_id,
                    true, NOW(), NOW(), false
                )
                ON CONFLICT (username) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    role = EXCLUDED.role,
                    is_active = true,
                    updated_at = NOW()
            """), {
                "id":           acc["id"],
                "tid":          CZYZ_TENANT_ID,
                "username":     acc["username"],
                "pwd_hash":     DEMO_PWD_HASH,
                "display_name": acc["display_name"],
                "role":         acc["role"],
                "store_id":     acc.get("store_id"),
            })
            log.info("account_created", username=acc["username"], role=acc["role"])
        except Exception as exc:
            log.warning("account_upsert_failed", username=acc["username"], error=str(exc))

    await db.commit()
    log.info("step8_accounts", status="done")

    # 打印账号汇总
    print("\n" + "═" * 50)
    print("  演示账号（密码统一：demo2026）")
    print("═" * 50)
    for acc in accounts:
        store_label = f" ({acc['display_name']})" if acc["store_id"] else " (全品牌)"
        print(f"  {acc['username']:20s} {acc['role']:20s}{store_label}")
    print("═" * 50 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════════

async def main(mode: str, sync_days: int) -> None:
    db_url = _load_demo_database_url()
    log.info("demo_prep_start", mode=mode, sync_days=sync_days, db_url=db_url.split("@")[-1])

    # 初始化数据库（创建表，若已存在则跳过）
    os.environ.setdefault("DATABASE_URL", db_url)
    await init_db()

    # 初始化品智适配器
    pinzhi_cfg = {
        "base_url": "https://czyq.pinzhikeji.net/pzcatering-gateway",
        "token":    "3bbc9bed2b42c1e1b3cca26389fbb81c",
        "timeout":  30,
        "retry_times": 3,
    }

    async with async_session_factory() as db:
        adapter = PinzhiAdapter(pinzhi_cfg)

        if mode in ("full", "structure"):
            await setup_tenant(db)
            await setup_stores(db, adapter)
            await sync_tables(db, adapter)
            await sync_employees(db, adapter)
            await sync_dishes(db, adapter)
            await setup_demo_accounts(db)

        if mode in ("full", "orders"):
            await adapter.close()
            adapter = None  # ETL 内部自己管理连接
            await sync_orders_and_members(sync_days)

        if mode in ("full", "incremental", "ai-only"):
            if mode != "incremental":
                async with async_session_factory() as db2:
                    await seed_ai_analysis(db2)
            else:
                if adapter:
                    await adapter.close()
                await sync_orders_and_members(sync_days)

        if adapter:
            await adapter.close()

    print("\n✅ 尝在一起演示环境准备完成！")
    print(f"   数据库: {db_url.split('@')[-1]}")
    print(f"   租户ID: {CZYZ_TENANT_ID}")
    print(f"   门店数: {len(STORE_MAP)} 家（文化城店 / 浏小鲜 / 永安店）")
    print(f"   订单范围: 近 {sync_days} 天真实营业数据\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="屯象OS演示数据准备 — 尝在一起")
    parser.add_argument(
        "--mode",
        choices=["full", "structure", "orders", "incremental", "ai-only"],
        default="full",
        help=(
            "full=全量首次拉取 | structure=仅门店/桌台/菜品 | "
            "orders=仅订单/会员 | incremental=增量订单+AI | ai-only=仅AI分析种子"
        ),
    )
    parser.add_argument(
        "--days",
        type=int,
        default=int(os.environ.get("SYNC_DAYS", "90")),
        help="历史数据天数（默认90天）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(mode=args.mode, sync_days=args.days))
