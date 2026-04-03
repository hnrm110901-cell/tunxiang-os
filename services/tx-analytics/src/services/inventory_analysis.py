"""库存成本深度分析服务 — D6 模块

提供库存周转率、原料涨跌监控、损耗排行、盘点差异、采购偏差、
菜品成本偏差、活鲜损耗专项、食安风险图谱等分析能力。
"""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant context"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── 库存周转率 ───


async def inventory_turnover(
    store_id: str,
    date_range: dict,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """计算库存周转率（天）

    公式: 库存周转天数 = 平均库存成本 / (期间消耗成本 / 天数)
    即: 周转天数 = 平均库存成本 * 天数 / 期间消耗成本

    Args:
        store_id: 门店 ID
        date_range: {"start": "2026-03-01", "end": "2026-03-27"}
        tenant_id: 租户 ID
        db: 数据库会话
    """
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)
    start_date = date_range["start"]
    end_date = date_range["end"]

    # 查询期间消耗成本
    consumption_result = await db.execute(
        text("""
            SELECT COALESCE(SUM(cost_fen), 0) AS total_consumption_fen
            FROM inventory_transactions
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND tx_type = 'consumption'
              AND tx_date BETWEEN :start_date AND :end_date
              AND is_deleted = false
        """),
        {
            "store_id": store_uuid,
            "tenant_id": tenant_uuid,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    total_consumption_fen = consumption_result.scalar() or 0

    # 查询期初和期末库存成本，计算平均库存
    inventory_result = await db.execute(
        text("""
            SELECT
                COALESCE(SUM(CASE WHEN snapshot_date = :start_date THEN cost_fen END), 0)
                    AS start_cost_fen,
                COALESCE(SUM(CASE WHEN snapshot_date = :end_date THEN cost_fen END), 0)
                    AS end_cost_fen
            FROM inventory_snapshots
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND snapshot_date IN (:start_date, :end_date)
              AND is_deleted = false
        """),
        {
            "store_id": store_uuid,
            "tenant_id": tenant_uuid,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    inv_row = inventory_result.mappings().first()
    start_cost = inv_row["start_cost_fen"] if inv_row else 0
    end_cost = inv_row["end_cost_fen"] if inv_row else 0
    avg_inventory_fen = (start_cost + end_cost) / 2

    # 计算天数
    from datetime import date as date_type
    d_start = date_type.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    d_end = date_type.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    days = max((d_end - d_start).days, 1)

    # 库存周转天数 = 平均库存成本 * 天数 / 期间消耗成本
    if total_consumption_fen > 0:
        turnover_days = round(avg_inventory_fen * days / total_consumption_fen, 1)
    else:
        turnover_days = None  # 无消耗则无法计算

    log.info(
        "inventory_turnover_calculated",
        store_id=store_id,
        turnover_days=turnover_days,
        total_consumption_fen=total_consumption_fen,
        avg_inventory_fen=avg_inventory_fen,
        tenant_id=tenant_id,
    )

    return {
        "store_id": store_id,
        "date_range": date_range,
        "total_consumption_fen": total_consumption_fen,
        "avg_inventory_fen": round(avg_inventory_fen),
        "days": days,
        "turnover_days": turnover_days,
    }


# ─── 原料涨跌监控 ───


async def price_fluctuation_monitor(
    tenant_id: str,
    date_range: dict,
    db: AsyncSession,
) -> dict:
    """原料涨跌监控 — 对比期间首尾采购价

    Args:
        tenant_id: 租户 ID
        date_range: {"start": "2026-03-01", "end": "2026-03-27"}
        db: 数据库会话
    """
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    start_date = date_range["start"]
    end_date = date_range["end"]

    result = await db.execute(
        text("""
            WITH period_prices AS (
                SELECT
                    ingredient_id,
                    MIN(CASE WHEN purchase_date = first_dates.first_date
                        THEN unit_price_fen END) AS start_price_fen,
                    MIN(CASE WHEN purchase_date = last_dates.last_date
                        THEN unit_price_fen END) AS end_price_fen,
                    AVG(unit_price_fen) AS avg_price_fen,
                    COUNT(*) AS purchase_count
                FROM purchase_records pr
                CROSS JOIN LATERAL (
                    SELECT MIN(purchase_date) AS first_date
                    FROM purchase_records
                    WHERE ingredient_id = pr.ingredient_id
                      AND tenant_id = :tenant_id
                      AND purchase_date BETWEEN :start_date AND :end_date
                      AND is_deleted = false
                ) first_dates
                CROSS JOIN LATERAL (
                    SELECT MAX(purchase_date) AS last_date
                    FROM purchase_records
                    WHERE ingredient_id = pr.ingredient_id
                      AND tenant_id = :tenant_id
                      AND purchase_date BETWEEN :start_date AND :end_date
                      AND is_deleted = false
                ) last_dates
                WHERE pr.tenant_id = :tenant_id
                  AND pr.purchase_date BETWEEN :start_date AND :end_date
                  AND pr.is_deleted = false
                GROUP BY pr.ingredient_id, first_dates.first_date, last_dates.last_date
            )
            SELECT
                pp.ingredient_id,
                i.name AS ingredient_name,
                pp.start_price_fen,
                pp.end_price_fen,
                pp.avg_price_fen,
                pp.purchase_count,
                CASE WHEN pp.start_price_fen > 0
                    THEN ROUND((pp.end_price_fen - pp.start_price_fen)::numeric
                         / pp.start_price_fen * 100, 1)
                    ELSE 0 END AS change_pct
            FROM period_prices pp
            LEFT JOIN ingredients i ON i.id = pp.ingredient_id AND i.tenant_id = :tenant_id
            ORDER BY ABS(COALESCE(pp.end_price_fen, 0) - COALESCE(pp.start_price_fen, 0)) DESC
            LIMIT 50
        """),
        {
            "tenant_id": tenant_uuid,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    rows = result.mappings().all()

    items = [
        {
            "ingredient_id": str(r["ingredient_id"]),
            "ingredient_name": r["ingredient_name"],
            "start_price_fen": r["start_price_fen"],
            "end_price_fen": r["end_price_fen"],
            "avg_price_fen": round(r["avg_price_fen"]) if r["avg_price_fen"] else None,
            "change_pct": float(r["change_pct"]) if r["change_pct"] else 0,
            "purchase_count": r["purchase_count"],
        }
        for r in rows
    ]

    up_count = sum(1 for i in items if i["change_pct"] > 0)
    down_count = sum(1 for i in items if i["change_pct"] < 0)

    log.info(
        "price_fluctuation_monitored",
        total=len(items),
        up_count=up_count,
        down_count=down_count,
        tenant_id=tenant_id,
    )

    return {
        "date_range": date_range,
        "total": len(items),
        "up_count": up_count,
        "down_count": down_count,
        "items": items,
    }


# ─── 损耗排行 ───


async def waste_ranking(
    store_id: str,
    date_range: dict,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """损耗排行（金额/数量/频率）

    Args:
        store_id: 门店 ID
        date_range: {"start": ..., "end": ...}
        tenant_id: 租户 ID
        db: 数据库会话
    """
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    result = await db.execute(
        text("""
            SELECT
                w.ingredient_id,
                i.name AS ingredient_name,
                SUM(w.waste_cost_fen) AS total_cost_fen,
                SUM(w.waste_qty) AS total_qty,
                COUNT(*) AS frequency,
                w.unit
            FROM waste_records w
            LEFT JOIN ingredients i ON i.id = w.ingredient_id AND i.tenant_id = :tenant_id
            WHERE w.store_id = :store_id
              AND w.tenant_id = :tenant_id
              AND w.waste_date BETWEEN :start_date AND :end_date
              AND w.is_deleted = false
            GROUP BY w.ingredient_id, i.name, w.unit
            ORDER BY SUM(w.waste_cost_fen) DESC
            LIMIT 30
        """),
        {
            "store_id": store_uuid,
            "tenant_id": tenant_uuid,
            "start_date": date_range["start"],
            "end_date": date_range["end"],
        },
    )
    rows = result.mappings().all()

    items = [
        {
            "rank": idx + 1,
            "ingredient_id": str(r["ingredient_id"]),
            "ingredient_name": r["ingredient_name"],
            "total_cost_fen": int(r["total_cost_fen"]),
            "total_qty": float(r["total_qty"]),
            "unit": r["unit"],
            "frequency": r["frequency"],
        }
        for idx, r in enumerate(rows)
    ]

    total_waste_fen = sum(i["total_cost_fen"] for i in items)

    log.info(
        "waste_ranking_calculated",
        store_id=store_id,
        total_waste_fen=total_waste_fen,
        item_count=len(items),
        tenant_id=tenant_id,
    )

    return {
        "store_id": store_id,
        "date_range": date_range,
        "total_waste_fen": total_waste_fen,
        "items": items,
    }


# ─── 盘点差异分析 ───


async def stocktake_variance_analysis(
    store_id: str,
    date_range: dict,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """盘点差异分析（按原料/按门店）

    差异 = 实际盘点量 - 系统期望量
    """
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    result = await db.execute(
        text("""
            SELECT
                s.ingredient_id,
                i.name AS ingredient_name,
                s.unit,
                SUM(s.expected_qty) AS total_expected,
                SUM(s.actual_qty) AS total_actual,
                SUM(s.actual_qty - s.expected_qty) AS total_variance_qty,
                SUM(s.variance_cost_fen) AS total_variance_cost_fen,
                COUNT(*) AS stocktake_count
            FROM stocktake_records s
            LEFT JOIN ingredients i ON i.id = s.ingredient_id AND i.tenant_id = :tenant_id
            WHERE s.store_id = :store_id
              AND s.tenant_id = :tenant_id
              AND s.stocktake_date BETWEEN :start_date AND :end_date
              AND s.is_deleted = false
            GROUP BY s.ingredient_id, i.name, s.unit
            ORDER BY ABS(SUM(s.variance_cost_fen)) DESC
            LIMIT 30
        """),
        {
            "store_id": store_uuid,
            "tenant_id": tenant_uuid,
            "start_date": date_range["start"],
            "end_date": date_range["end"],
        },
    )
    rows = result.mappings().all()

    items = [
        {
            "ingredient_id": str(r["ingredient_id"]),
            "ingredient_name": r["ingredient_name"],
            "unit": r["unit"],
            "total_expected": float(r["total_expected"]),
            "total_actual": float(r["total_actual"]),
            "variance_qty": float(r["total_variance_qty"]),
            "variance_cost_fen": int(r["total_variance_cost_fen"]) if r["total_variance_cost_fen"] else 0,
            "stocktake_count": r["stocktake_count"],
        }
        for r in rows
    ]

    net_variance_fen = sum(i["variance_cost_fen"] for i in items)
    shortage_count = sum(1 for i in items if i["variance_qty"] < 0)
    surplus_count = sum(1 for i in items if i["variance_qty"] > 0)

    log.info(
        "stocktake_variance_analyzed",
        store_id=store_id,
        net_variance_fen=net_variance_fen,
        shortage_count=shortage_count,
        surplus_count=surplus_count,
        tenant_id=tenant_id,
    )

    return {
        "store_id": store_id,
        "date_range": date_range,
        "net_variance_fen": net_variance_fen,
        "shortage_count": shortage_count,
        "surplus_count": surplus_count,
        "items": items,
    }


# ─── 采购偏差 ───


async def procurement_variance(
    store_id: str,
    date_range: dict,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """采购偏差（计划 vs 实际）"""
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    result = await db.execute(
        text("""
            SELECT
                po.ingredient_id,
                i.name AS ingredient_name,
                po.unit,
                SUM(po.planned_qty) AS total_planned,
                SUM(po.actual_qty) AS total_actual,
                SUM(po.planned_cost_fen) AS total_planned_cost,
                SUM(po.actual_cost_fen) AS total_actual_cost,
                COUNT(*) AS order_count
            FROM procurement_orders po
            LEFT JOIN ingredients i ON i.id = po.ingredient_id AND i.tenant_id = :tenant_id
            WHERE po.store_id = :store_id
              AND po.tenant_id = :tenant_id
              AND po.order_date BETWEEN :start_date AND :end_date
              AND po.is_deleted = false
            GROUP BY po.ingredient_id, i.name, po.unit
            ORDER BY ABS(SUM(po.actual_cost_fen) - SUM(po.planned_cost_fen)) DESC
            LIMIT 30
        """),
        {
            "store_id": store_uuid,
            "tenant_id": tenant_uuid,
            "start_date": date_range["start"],
            "end_date": date_range["end"],
        },
    )
    rows = result.mappings().all()

    items = []
    for r in rows:
        planned_cost = int(r["total_planned_cost"]) if r["total_planned_cost"] else 0
        actual_cost = int(r["total_actual_cost"]) if r["total_actual_cost"] else 0
        cost_variance = actual_cost - planned_cost
        variance_pct = round(cost_variance / planned_cost * 100, 1) if planned_cost > 0 else 0

        items.append({
            "ingredient_id": str(r["ingredient_id"]),
            "ingredient_name": r["ingredient_name"],
            "unit": r["unit"],
            "total_planned_qty": float(r["total_planned"]),
            "total_actual_qty": float(r["total_actual"]),
            "planned_cost_fen": planned_cost,
            "actual_cost_fen": actual_cost,
            "cost_variance_fen": cost_variance,
            "variance_pct": variance_pct,
            "order_count": r["order_count"],
        })

    total_planned = sum(i["planned_cost_fen"] for i in items)
    total_actual = sum(i["actual_cost_fen"] for i in items)

    log.info(
        "procurement_variance_analyzed",
        store_id=store_id,
        total_planned_fen=total_planned,
        total_actual_fen=total_actual,
        tenant_id=tenant_id,
    )

    return {
        "store_id": store_id,
        "date_range": date_range,
        "total_planned_cost_fen": total_planned,
        "total_actual_cost_fen": total_actual,
        "total_variance_fen": total_actual - total_planned,
        "items": items,
    }


# ─── 菜品成本偏差 ───


async def dish_cost_variance_deep(
    store_id: str,
    date_range: dict,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """菜品成本偏差（理论 vs 实际，细到原料级）"""
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    # 查询菜品维度汇总
    result = await db.execute(
        text("""
            SELECT
                dcv.dish_id,
                d.name AS dish_name,
                SUM(dcv.theoretical_cost_fen) AS total_theoretical,
                SUM(dcv.actual_cost_fen) AS total_actual,
                SUM(dcv.sold_qty) AS total_sold
            FROM dish_cost_variances dcv
            LEFT JOIN dishes d ON d.id = dcv.dish_id AND d.tenant_id = :tenant_id
            WHERE dcv.store_id = :store_id
              AND dcv.tenant_id = :tenant_id
              AND dcv.calc_date BETWEEN :start_date AND :end_date
              AND dcv.is_deleted = false
            GROUP BY dcv.dish_id, d.name
            ORDER BY ABS(SUM(dcv.actual_cost_fen) - SUM(dcv.theoretical_cost_fen)) DESC
            LIMIT 20
        """),
        {
            "store_id": store_uuid,
            "tenant_id": tenant_uuid,
            "start_date": date_range["start"],
            "end_date": date_range["end"],
        },
    )
    dish_rows = result.mappings().all()

    dishes = []
    for dr in dish_rows:
        theoretical = int(dr["total_theoretical"]) if dr["total_theoretical"] else 0
        actual = int(dr["total_actual"]) if dr["total_actual"] else 0
        variance = actual - theoretical
        variance_pct = round(variance / theoretical * 100, 1) if theoretical > 0 else 0

        # 查询原料级明细
        detail_result = await db.execute(
            text("""
                SELECT
                    dcvd.ingredient_id,
                    i.name AS ingredient_name,
                    SUM(dcvd.theoretical_qty) AS total_theo_qty,
                    SUM(dcvd.actual_qty) AS total_actual_qty,
                    SUM(dcvd.theoretical_cost_fen) AS theo_cost,
                    SUM(dcvd.actual_cost_fen) AS actual_cost,
                    dcvd.unit
                FROM dish_cost_variance_details dcvd
                LEFT JOIN ingredients i ON i.id = dcvd.ingredient_id AND i.tenant_id = :tenant_id
                WHERE dcvd.dish_id = :dish_id
                  AND dcvd.store_id = :store_id
                  AND dcvd.tenant_id = :tenant_id
                  AND dcvd.calc_date BETWEEN :start_date AND :end_date
                  AND dcvd.is_deleted = false
                GROUP BY dcvd.ingredient_id, i.name, dcvd.unit
                ORDER BY ABS(SUM(dcvd.actual_cost_fen) - SUM(dcvd.theoretical_cost_fen)) DESC
            """),
            {
                "dish_id": dr["dish_id"],
                "store_id": store_uuid,
                "tenant_id": tenant_uuid,
                "start_date": date_range["start"],
                "end_date": date_range["end"],
            },
        )
        detail_rows = detail_result.mappings().all()

        ingredients_detail = [
            {
                "ingredient_id": str(dd["ingredient_id"]),
                "ingredient_name": dd["ingredient_name"],
                "unit": dd["unit"],
                "theoretical_qty": float(dd["total_theo_qty"]),
                "actual_qty": float(dd["total_actual_qty"]),
                "theoretical_cost_fen": int(dd["theo_cost"]) if dd["theo_cost"] else 0,
                "actual_cost_fen": int(dd["actual_cost"]) if dd["actual_cost"] else 0,
            }
            for dd in detail_rows
        ]

        dishes.append({
            "dish_id": str(dr["dish_id"]),
            "dish_name": dr["dish_name"],
            "total_sold": int(dr["total_sold"]) if dr["total_sold"] else 0,
            "theoretical_cost_fen": theoretical,
            "actual_cost_fen": actual,
            "variance_fen": variance,
            "variance_pct": variance_pct,
            "ingredients": ingredients_detail,
        })

    log.info(
        "dish_cost_variance_deep_analyzed",
        store_id=store_id,
        dish_count=len(dishes),
        tenant_id=tenant_id,
    )

    return {
        "store_id": store_id,
        "date_range": date_range,
        "dishes": dishes,
    }


# ─── 活鲜损耗专项 ───


async def seafood_waste_analysis(
    store_id: str,
    date_range: dict,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """活鲜损耗专项分析（徐记海鲜核心）

    分类: 存活 / 死亡 / 品质降级
    """
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    result = await db.execute(
        text("""
            SELECT
                sw.ingredient_id,
                i.name AS ingredient_name,
                sw.waste_category,
                SUM(sw.waste_qty) AS total_qty,
                SUM(sw.waste_cost_fen) AS total_cost_fen,
                sw.unit,
                COUNT(*) AS occurrence_count
            FROM seafood_waste_records sw
            LEFT JOIN ingredients i ON i.id = sw.ingredient_id AND i.tenant_id = :tenant_id
            WHERE sw.store_id = :store_id
              AND sw.tenant_id = :tenant_id
              AND sw.record_date BETWEEN :start_date AND :end_date
              AND sw.is_deleted = false
            GROUP BY sw.ingredient_id, i.name, sw.waste_category, sw.unit
            ORDER BY SUM(sw.waste_cost_fen) DESC
        """),
        {
            "store_id": store_uuid,
            "tenant_id": tenant_uuid,
            "start_date": date_range["start"],
            "end_date": date_range["end"],
        },
    )
    rows = result.mappings().all()

    # 按品类汇总
    by_category: dict = {"death": [], "quality_downgrade": [], "alive_loss": []}
    total_by_category: dict = {"death": 0, "quality_downgrade": 0, "alive_loss": 0}

    for r in rows:
        category = r["waste_category"] or "death"
        item = {
            "ingredient_id": str(r["ingredient_id"]),
            "ingredient_name": r["ingredient_name"],
            "qty": float(r["total_qty"]),
            "unit": r["unit"],
            "cost_fen": int(r["total_cost_fen"]) if r["total_cost_fen"] else 0,
            "occurrence_count": r["occurrence_count"],
        }
        if category in by_category:
            by_category[category].append(item)
            total_by_category[category] += item["cost_fen"]

    grand_total = sum(total_by_category.values())

    log.info(
        "seafood_waste_analyzed",
        store_id=store_id,
        grand_total_fen=grand_total,
        death_fen=total_by_category["death"],
        downgrade_fen=total_by_category["quality_downgrade"],
        alive_loss_fen=total_by_category["alive_loss"],
        tenant_id=tenant_id,
    )

    return {
        "store_id": store_id,
        "date_range": date_range,
        "grand_total_cost_fen": grand_total,
        "by_category": {
            "death": {
                "total_cost_fen": total_by_category["death"],
                "items": by_category["death"],
            },
            "quality_downgrade": {
                "total_cost_fen": total_by_category["quality_downgrade"],
                "items": by_category["quality_downgrade"],
            },
            "alive_loss": {
                "total_cost_fen": total_by_category["alive_loss"],
                "items": by_category["alive_loss"],
            },
        },
    }


# ─── 食安风险图谱 ───


async def food_safety_risk_graph(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """食安风险图谱（临期/过期/异常温度/高风险原料）"""
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)
    now = datetime.now(timezone.utc)

    # 1. 临期/过期原料
    expiry_result = await db.execute(
        text("""
            SELECT
                inv.ingredient_id,
                i.name AS ingredient_name,
                inv.batch_no,
                inv.expiry_date,
                inv.qty_on_hand,
                inv.unit,
                CASE
                    WHEN inv.expiry_date < :now THEN 'expired'
                    WHEN inv.expiry_date < :now + interval '3 days' THEN 'near_expiry'
                    ELSE 'normal'
                END AS expiry_status
            FROM inventory_batches inv
            LEFT JOIN ingredients i ON i.id = inv.ingredient_id AND i.tenant_id = :tenant_id
            WHERE inv.store_id = :store_id
              AND inv.tenant_id = :tenant_id
              AND inv.qty_on_hand > 0
              AND inv.is_deleted = false
              AND inv.expiry_date < :now + interval '3 days'
            ORDER BY inv.expiry_date ASC
        """),
        {
            "store_id": store_uuid,
            "tenant_id": tenant_uuid,
            "now": now,
        },
    )
    expiry_rows = expiry_result.mappings().all()

    expiry_risks = [
        {
            "ingredient_id": str(r["ingredient_id"]),
            "ingredient_name": r["ingredient_name"],
            "batch_no": r["batch_no"],
            "expiry_date": r["expiry_date"].isoformat() if r["expiry_date"] else None,
            "qty_on_hand": float(r["qty_on_hand"]),
            "unit": r["unit"],
            "status": r["expiry_status"],
        }
        for r in expiry_rows
    ]

    # 2. 异常温度记录
    temp_result = await db.execute(
        text("""
            SELECT
                ta.equipment_id,
                ta.equipment_name,
                ta.recorded_temp,
                ta.threshold_min,
                ta.threshold_max,
                ta.recorded_at
            FROM temperature_alerts ta
            WHERE ta.store_id = :store_id
              AND ta.tenant_id = :tenant_id
              AND ta.recorded_at > :now - interval '24 hours'
              AND ta.is_deleted = false
            ORDER BY ta.recorded_at DESC
            LIMIT 20
        """),
        {
            "store_id": store_uuid,
            "tenant_id": tenant_uuid,
            "now": now,
        },
    )
    temp_rows = temp_result.mappings().all()

    temp_alerts = [
        {
            "equipment_id": str(r["equipment_id"]),
            "equipment_name": r["equipment_name"],
            "recorded_temp": float(r["recorded_temp"]),
            "threshold_min": float(r["threshold_min"]) if r["threshold_min"] else None,
            "threshold_max": float(r["threshold_max"]) if r["threshold_max"] else None,
            "recorded_at": r["recorded_at"].isoformat() if r["recorded_at"] else None,
        }
        for r in temp_rows
    ]

    # 3. 高风险原料（过敏原 / 高耗损 / 特殊储存要求）
    risk_result = await db.execute(
        text("""
            SELECT
                i.id AS ingredient_id,
                i.name AS ingredient_name,
                i.risk_level,
                i.risk_tags,
                inv.qty_on_hand,
                inv.unit
            FROM ingredients i
            JOIN inventory_batches inv ON inv.ingredient_id = i.id
                AND inv.store_id = :store_id
                AND inv.tenant_id = :tenant_id
                AND inv.qty_on_hand > 0
                AND inv.is_deleted = false
            WHERE i.tenant_id = :tenant_id
              AND i.risk_level >= 3
              AND i.is_deleted = false
            ORDER BY i.risk_level DESC
        """),
        {
            "store_id": store_uuid,
            "tenant_id": tenant_uuid,
        },
    )
    risk_rows = risk_result.mappings().all()

    high_risk_items = [
        {
            "ingredient_id": str(r["ingredient_id"]),
            "ingredient_name": r["ingredient_name"],
            "risk_level": r["risk_level"],
            "risk_tags": r["risk_tags"],
            "qty_on_hand": float(r["qty_on_hand"]),
            "unit": r["unit"],
        }
        for r in risk_rows
    ]

    expired_count = sum(1 for e in expiry_risks if e["status"] == "expired")
    near_expiry_count = sum(1 for e in expiry_risks if e["status"] == "near_expiry")

    # 综合风险评分 (0-100, 越高越危险)
    risk_score = min(100, expired_count * 20 + near_expiry_count * 5
                     + len(temp_alerts) * 10 + len(high_risk_items) * 3)

    log.info(
        "food_safety_risk_graph_generated",
        store_id=store_id,
        risk_score=risk_score,
        expired_count=expired_count,
        near_expiry_count=near_expiry_count,
        temp_alert_count=len(temp_alerts),
        tenant_id=tenant_id,
    )

    return {
        "store_id": store_id,
        "risk_score": risk_score,
        "expiry_risks": {
            "expired_count": expired_count,
            "near_expiry_count": near_expiry_count,
            "items": expiry_risks,
        },
        "temperature_alerts": temp_alerts,
        "high_risk_ingredients": high_risk_items,
    }
