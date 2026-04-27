"""菜品利润图谱增强 — 定价建议引擎 + 桌均利润 + 品类配比 + 共现分析 + 食材联动

核心功能：
  a) generate_pricing_suggestions()     — 基于BCG四象限生成智能定价建议
  b) compute_table_profit()             — 桌均利润分析（按桌型/坪效）
  c) compute_category_mix()             — 品类配比健康度（对标行业标准）
  d) compute_dish_co_occurrence()       — 菜品共现图谱（Jaccard相似度 + 下架影响评估）
  e) compute_ingredient_price_impact()  — 食材价格→菜品成本联动分析

金额单位: 分(fen), int
"""

import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# ─── 常量 ─────────────────────────────────────────────────────────────────────

# BCG象限→建议策略映射
_BCG_STRATEGY: dict[str, dict[str, Any]] = {
    "star": {
        "type": "raise",
        "price_adjust_min": 0.05,
        "price_adjust_max": 0.15,
        "reason": "高人气高毛利明星菜，有提价余地，建议探测提价空间+5%~+15%",
    },
    "question_mark": {
        "type": "promote",
        "price_adjust_min": 0.0,
        "price_adjust_max": 0.0,
        "reason": "毛利好但点单少，建议加强推广或调入套餐/组合，提高曝光度",
    },
    "cash_cow": {
        "type": "lower",
        "price_adjust_min": 0.0,
        "price_adjust_max": 0.0,
        "reason": "走量但薄利耕牛菜，严控BOM成本，防止食材涨价侵蚀利润",
    },
    "dog": {
        "type": "delist",
        "price_adjust_min": 0.0,
        "price_adjust_max": 0.0,
        "reason": "低人气低毛利瘦狗菜，占用菜单空间，建议观察或下架",
    },
}

# 行业标准品类营收占比（中式正餐）
_CATEGORY_BENCHMARK: dict[str, float] = {
    "凉菜": 0.15,
    "热菜": 0.45,
    "主食": 0.20,
    "饮品": 0.20,
}

# 品类偏差告警阈值
_CATEGORY_DEVIATION_THRESHOLD = 0.05

# 毛利预警阈值（百分比）
_MARGIN_ALERT_THRESHOLD = Decimal("30.00")

# 桌型→座位数映射
_TABLE_TYPE_SEATS: dict[str, int] = {
    "2人桌": 2,
    "4人桌": 4,
    "6人桌": 6,
    "包厢": 10,
}

# 共现率超过此阈值时，下架影响告警
_CO_OCCURRENCE_IMPACT_THRESHOLD = 0.40


# ─── RLS ──────────────────────────────────────────────────────────────────────


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS 租户上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── 金额工具 ────────────────────────────────────────────────────────────────


def _fen_to_yuan(fen: int) -> float:
    """分→元，保留2位小数"""
    return round(fen / 100.0, 2)


def _margin_rate(price_fen: int, cost_fen: int) -> Decimal:
    """计算毛利率（百分比）"""
    if price_fen <= 0:
        return Decimal("0.00")
    return (Decimal(price_fen - cost_fen) / Decimal(price_fen) * 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# a) 定价建议引擎
# ═══════════════════════════════════════════════════════════════════════════════


async def generate_pricing_suggestions(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    period_days: int = 14,
) -> list[dict[str, Any]]:
    """基于BCG四象限生成菜品定价建议

    策略：
      star(明星菜):         探测提价空间 +5%~+15%
      question_mark(问题菜): 加强推广或调入套餐
      cash_cow(耕牛菜):     严控BOM成本，成本上涨>5%预警
      dog(瘦狗菜):          连续2周dog → 建议下架

    Returns:
        建议列表，已写入 dish_pricing_suggestions 表
    """
    await _set_rls(db, tenant_id)

    today = date.today()
    period_start = today - timedelta(days=period_days)

    # 1. 获取门店全部菜品 + 销量 + 成本
    dishes = await _fetch_dish_bcg_data(db, tenant_id, store_id, period_start, today)
    if not dishes:
        log.info("pricing_advisor.no_dishes", store_id=store_id)
        return []

    # 2. 计算BCG象限
    dishes_with_bcg = _classify_bcg(dishes)

    # 3. 查询上一周期BCG分类（用于检测连续dog）
    prev_period_start = period_start - timedelta(days=period_days)
    prev_dishes = await _fetch_dish_bcg_data(db, tenant_id, store_id, prev_period_start, period_start)
    prev_bcg_map: dict[str, str] = {}
    if prev_dishes:
        for d in _classify_bcg(prev_dishes):
            prev_bcg_map[d["dish_id"]] = d["bcg_quadrant"]

    # 4. 生成建议
    suggestions: list[dict[str, Any]] = []
    for dish in dishes_with_bcg:
        quadrant = dish["bcg_quadrant"]
        strategy = _BCG_STRATEGY[quadrant]
        current_price = dish["price_fen"]

        suggestion_type = strategy["type"]
        suggested_price: Optional[int] = None
        estimated_impact = 0
        reason = strategy["reason"]

        if quadrant == "star":
            # 探测提价空间: +10% 作为建议价
            adjust_rate = (strategy["price_adjust_min"] + strategy["price_adjust_max"]) / 2
            suggested_price = int(current_price * (1 + adjust_rate))
            # 预估月利润影响 = 提价部分 * 月销量
            monthly_qty = dish["sales_qty"] * (30 / max(period_days, 1))
            estimated_impact = int((suggested_price - current_price) * monthly_qty)

        elif quadrant == "question_mark":
            suggestion_type = "promote"
            reason = "毛利好但点单少，建议加强推广或调入套餐/组合，提高曝光度"

        elif quadrant == "cash_cow":
            # 检查成本是否上涨
            cost_change = await _check_cost_change(db, tenant_id, dish["dish_id"], period_days)
            if cost_change > 0.05:
                suggestion_type = "lower"
                reason = f"耕牛菜成本上涨{cost_change:.0%}，超过5%预警线，需严控BOM成本或微调售价"
            else:
                reason = "走量但薄利，成本暂稳定，继续严控BOM成本"

        elif quadrant == "dog":
            prev_q = prev_bcg_map.get(dish["dish_id"])
            if prev_q == "dog":
                suggestion_type = "delist"
                reason = "连续2周处于瘦狗象限，低人气低毛利，建议下架释放菜单空间"
            else:
                suggestion_type = "promote"
                reason = "本周进入瘦狗象限，建议观察1周，若下周仍为瘦狗则下架"

        suggestion = {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "dish_id": dish["dish_id"],
            "dish_name": dish["dish_name"],
            "suggestion_date": str(today),
            "current_price_fen": current_price,
            "current_price_yuan": _fen_to_yuan(current_price),
            "suggested_price_fen": suggested_price,
            "suggested_price_yuan": _fen_to_yuan(suggested_price) if suggested_price else None,
            "suggestion_type": suggestion_type,
            "bcg_quadrant": quadrant,
            "reason": reason,
            "estimated_impact_fen": estimated_impact,
            "estimated_impact_yuan": _fen_to_yuan(estimated_impact),
            "status": "pending",
            "margin_rate": float(dish["margin_rate"]),
            "sales_qty": dish["sales_qty"],
        }
        suggestions.append(suggestion)

        # 写入DB
        await db.execute(
            text("""
                INSERT INTO dish_pricing_suggestions
                    (tenant_id, store_id, dish_id, suggestion_date,
                     current_price_fen, suggested_price_fen, suggestion_type,
                     bcg_quadrant, reason, estimated_impact_fen, status)
                VALUES
                    (:tenant_id::uuid, :store_id::uuid, :dish_id::uuid, :suggestion_date,
                     :current_price_fen, :suggested_price_fen, :suggestion_type,
                     :bcg_quadrant, :reason, :estimated_impact_fen, 'pending')
                ON CONFLICT DO NOTHING
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "dish_id": dish["dish_id"],
                "suggestion_date": today,
                "current_price_fen": current_price,
                "suggested_price_fen": suggested_price,
                "suggestion_type": suggestion_type,
                "bcg_quadrant": quadrant,
                "reason": reason,
                "estimated_impact_fen": estimated_impact,
            },
        )

    await db.commit()
    log.info(
        "pricing_advisor.suggestions_generated",
        store_id=store_id,
        count=len(suggestions),
        bcg_counts={q: sum(1 for s in suggestions if s["bcg_quadrant"] == q) for q in _BCG_STRATEGY},
    )
    return suggestions


async def apply_suggestions(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    suggestion_ids: list[str],
) -> dict[str, Any]:
    """批量应用定价建议 — 更新菜品价格 + 标记建议状态

    Returns:
        {"applied": int, "skipped": int, "details": [...]}
    """
    await _set_rls(db, tenant_id)
    applied = 0
    skipped = 0
    details: list[dict[str, Any]] = []

    for sid in suggestion_ids:
        row = await db.execute(
            text("""
                SELECT id, dish_id, suggested_price_fen, suggestion_type, status
                FROM dish_pricing_suggestions
                WHERE id = :sid::uuid
                  AND tenant_id = :tenant_id::uuid
                  AND store_id = :store_id::uuid
                  AND is_deleted = FALSE
            """),
            {"sid": sid, "tenant_id": tenant_id, "store_id": store_id},
        )
        suggestion = row.mappings().first()
        if not suggestion:
            skipped += 1
            details.append({"id": sid, "status": "not_found"})
            continue

        if suggestion["status"] != "pending":
            skipped += 1
            details.append({"id": sid, "status": f"already_{suggestion['status']}"})
            continue

        # 有建议价格时更新菜品售价
        if suggestion["suggested_price_fen"] and suggestion["suggestion_type"] == "raise":
            await db.execute(
                text("""
                    UPDATE dishes SET price_fen = :new_price, updated_at = NOW()
                    WHERE id = :dish_id::uuid
                      AND tenant_id = :tenant_id::uuid
                      AND is_deleted = FALSE
                """),
                {
                    "new_price": suggestion["suggested_price_fen"],
                    "dish_id": str(suggestion["dish_id"]),
                    "tenant_id": tenant_id,
                },
            )

        # 下架处理
        if suggestion["suggestion_type"] == "delist":
            await db.execute(
                text("""
                    UPDATE dishes SET is_available = FALSE, updated_at = NOW()
                    WHERE id = :dish_id::uuid
                      AND tenant_id = :tenant_id::uuid
                      AND is_deleted = FALSE
                """),
                {"dish_id": str(suggestion["dish_id"]), "tenant_id": tenant_id},
            )

        # 更新建议状态
        await db.execute(
            text("""
                UPDATE dish_pricing_suggestions
                SET status = 'applied', applied_at = NOW(), updated_at = NOW()
                WHERE id = :sid::uuid AND tenant_id = :tenant_id::uuid
            """),
            {"sid": sid, "tenant_id": tenant_id},
        )
        applied += 1
        details.append({"id": sid, "status": "applied", "type": suggestion["suggestion_type"]})

    await db.commit()
    log.info("pricing_advisor.applied", store_id=store_id, applied=applied, skipped=skipped)
    return {"applied": applied, "skipped": skipped, "details": details}


async def get_suggestions(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """查询定价建议列表"""
    await _set_rls(db, tenant_id)

    where_clause = """
        WHERE dps.tenant_id = :tenant_id::uuid
          AND dps.store_id = :store_id::uuid
          AND dps.is_deleted = FALSE
    """
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "limit": limit,
        "offset": offset,
    }
    if status_filter:
        where_clause += " AND dps.status = :status_filter"
        params["status_filter"] = status_filter

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM dish_pricing_suggestions dps {where_clause}"),
        params,
    )
    total = count_result.scalar_one()

    result = await db.execute(
        text(f"""
            SELECT dps.*, d.dish_name
            FROM dish_pricing_suggestions dps
            LEFT JOIN dishes d ON d.id = dps.dish_id AND d.tenant_id = dps.tenant_id
            {where_clause}
            ORDER BY dps.suggestion_date DESC, dps.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.mappings().all()

    items = []
    for r in rows:
        items.append({
            "id": str(r["id"]),
            "dish_id": str(r["dish_id"]),
            "dish_name": r.get("dish_name", ""),
            "suggestion_date": str(r["suggestion_date"]),
            "current_price_fen": r["current_price_fen"],
            "current_price_yuan": _fen_to_yuan(r["current_price_fen"]),
            "suggested_price_fen": r["suggested_price_fen"],
            "suggested_price_yuan": _fen_to_yuan(r["suggested_price_fen"]) if r["suggested_price_fen"] else None,
            "suggestion_type": r["suggestion_type"],
            "bcg_quadrant": r["bcg_quadrant"],
            "reason": r["reason"],
            "estimated_impact_fen": r["estimated_impact_fen"],
            "estimated_impact_yuan": _fen_to_yuan(r["estimated_impact_fen"] or 0),
            "status": r["status"],
            "applied_at": str(r["applied_at"]) if r["applied_at"] else None,
        })

    return {"items": items, "total": total}


# ═══════════════════════════════════════════════════════════════════════════════
# b) 桌均利润分析
# ═══════════════════════════════════════════════════════════════════════════════


async def compute_table_profit(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    """桌均利润分析 — 按桌型分组统计

    计算逻辑：
      1. 从 orders + order_items 聚合每桌总收入、总成本、总毛利
      2. 按桌型分组：2人桌/4人桌/6人桌/包厢
      3. 坪效 = 桌均利润 / 座位数 / 用餐时长(小时) = 每座位小时利润

    Returns:
        {
            "overall": { avg_revenue_fen, avg_cost_fen, avg_profit_fen, total_tables },
            "by_table_type": [ { table_type, avg_profit_fen, seat_hour_profit_fen, ... } ],
        }
    """
    await _set_rls(db, tenant_id)

    # 按桌型聚合
    result = await db.execute(
        text("""
            WITH table_orders AS (
                SELECT
                    o.id AS order_id,
                    o.table_no,
                    COALESCE(t.table_type, '4人桌') AS table_type,
                    COALESCE(t.seat_count, 4) AS seat_count,
                    SUM(oi.quantity * oi.unit_price_fen) AS revenue_fen,
                    SUM(oi.quantity * COALESCE(d.cost_fen, 0)) AS cost_fen,
                    EXTRACT(EPOCH FROM (
                        COALESCE(o.checkout_time, o.updated_at) - o.order_time
                    )) / 3600.0 AS duration_hours
                FROM orders o
                JOIN order_items oi ON oi.order_id = o.id AND oi.is_deleted = FALSE
                LEFT JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = o.tenant_id
                LEFT JOIN tables t ON t.table_no = o.table_no
                    AND t.store_id = o.store_id AND t.tenant_id = o.tenant_id
                WHERE o.tenant_id = :tenant_id::uuid
                  AND o.store_id = :store_id::uuid
                  AND o.status IN ('completed', 'paid')
                  AND o.is_deleted = FALSE
                  AND o.order_time::date BETWEEN :date_from AND :date_to
                GROUP BY o.id, o.table_no, t.table_type, t.seat_count,
                         o.checkout_time, o.updated_at, o.order_time
            )
            SELECT
                table_type,
                seat_count,
                COUNT(*) AS table_count,
                AVG(revenue_fen)::INT AS avg_revenue_fen,
                AVG(cost_fen)::INT AS avg_cost_fen,
                AVG(revenue_fen - cost_fen)::INT AS avg_profit_fen,
                AVG(GREATEST(duration_hours, 0.5)) AS avg_duration_hours
            FROM table_orders
            WHERE duration_hours > 0
            GROUP BY table_type, seat_count
            ORDER BY avg_profit_fen DESC
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "date_from": str(date_from),
            "date_to": str(date_to),
        },
    )
    rows = result.mappings().all()

    by_table_type: list[dict[str, Any]] = []
    total_tables = 0
    sum_revenue = 0
    sum_cost = 0

    for r in rows:
        avg_profit = r["avg_profit_fen"] or 0
        seats = r["seat_count"] or 4
        duration_h = float(r["avg_duration_hours"] or 1.0)
        seat_hour_profit = int(avg_profit / seats / duration_h) if seats > 0 and duration_h > 0 else 0

        entry = {
            "table_type": r["table_type"],
            "seat_count": seats,
            "table_count": r["table_count"],
            "avg_revenue_fen": r["avg_revenue_fen"] or 0,
            "avg_revenue_yuan": _fen_to_yuan(r["avg_revenue_fen"] or 0),
            "avg_cost_fen": r["avg_cost_fen"] or 0,
            "avg_cost_yuan": _fen_to_yuan(r["avg_cost_fen"] or 0),
            "avg_profit_fen": avg_profit,
            "avg_profit_yuan": _fen_to_yuan(avg_profit),
            "avg_duration_hours": round(duration_h, 1),
            "seat_hour_profit_fen": seat_hour_profit,
            "seat_hour_profit_yuan": _fen_to_yuan(seat_hour_profit),
        }
        by_table_type.append(entry)
        total_tables += r["table_count"]
        sum_revenue += (r["avg_revenue_fen"] or 0) * r["table_count"]
        sum_cost += (r["avg_cost_fen"] or 0) * r["table_count"]

    overall_avg_revenue = int(sum_revenue / total_tables) if total_tables > 0 else 0
    overall_avg_cost = int(sum_cost / total_tables) if total_tables > 0 else 0
    overall_avg_profit = overall_avg_revenue - overall_avg_cost

    log.info(
        "pricing_advisor.table_profit",
        store_id=store_id,
        total_tables=total_tables,
        avg_profit_fen=overall_avg_profit,
    )

    return {
        "overall": {
            "total_tables": total_tables,
            "avg_revenue_fen": overall_avg_revenue,
            "avg_revenue_yuan": _fen_to_yuan(overall_avg_revenue),
            "avg_cost_fen": overall_avg_cost,
            "avg_cost_yuan": _fen_to_yuan(overall_avg_cost),
            "avg_profit_fen": overall_avg_profit,
            "avg_profit_yuan": _fen_to_yuan(overall_avg_profit),
        },
        "by_table_type": by_table_type,
        "date_from": str(date_from),
        "date_to": str(date_to),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# c) 品类配比健康度
# ═══════════════════════════════════════════════════════════════════════════════


async def compute_category_mix(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    """品类配比健康度 — 对标行业标准

    行业标准（中式正餐）：凉菜15% / 热菜45% / 主食20% / 饮品20%
    偏差>5%标记异常
    酒水占比<15%时提醒加强推荐

    Returns:
        {"categories": [...], "alerts": [...], "health_score": float}
    """
    await _set_rls(db, tenant_id)

    result = await db.execute(
        text("""
            SELECT
                COALESCE(dc.name, '其他') AS category_name,
                SUM(oi.quantity * oi.unit_price_fen) AS revenue_fen,
                SUM(oi.quantity) AS total_qty,
                COUNT(DISTINCT oi.order_id) AS order_count
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
                AND o.tenant_id = :tenant_id::uuid
                AND o.store_id = :store_id::uuid
                AND o.status IN ('completed', 'paid')
                AND o.is_deleted = FALSE
                AND o.order_time::date BETWEEN :date_from AND :date_to
            LEFT JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = o.tenant_id
            LEFT JOIN dish_categories dc ON dc.id = d.category_id
            WHERE oi.is_deleted = FALSE
            GROUP BY dc.name
            ORDER BY revenue_fen DESC
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "date_from": str(date_from),
            "date_to": str(date_to),
        },
    )
    rows = result.mappings().all()

    total_revenue = sum(r["revenue_fen"] or 0 for r in rows) or 1
    categories: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    beverage_ratio = 0.0

    for r in rows:
        revenue = r["revenue_fen"] or 0
        ratio = round(revenue / total_revenue, 4)
        cat_name = r["category_name"]

        entry = {
            "category": cat_name,
            "revenue_fen": revenue,
            "revenue_yuan": _fen_to_yuan(revenue),
            "ratio": ratio,
            "ratio_pct": round(ratio * 100, 1),
            "total_qty": r["total_qty"] or 0,
            "order_count": r["order_count"] or 0,
        }

        # 对比行业标准
        benchmark = _CATEGORY_BENCHMARK.get(cat_name)
        if benchmark is not None:
            deviation = ratio - benchmark
            entry["benchmark_pct"] = round(benchmark * 100, 1)
            entry["deviation_pct"] = round(deviation * 100, 1)
            entry["is_abnormal"] = abs(deviation) > _CATEGORY_DEVIATION_THRESHOLD

            if abs(deviation) > _CATEGORY_DEVIATION_THRESHOLD:
                direction = "偏高" if deviation > 0 else "偏低"
                alerts.append({
                    "category": cat_name,
                    "message": f"{cat_name}营收占比{ratio:.0%}，{direction}于行业标准{benchmark:.0%}，偏差{abs(deviation):.0%}",
                    "severity": "warning" if abs(deviation) <= 0.10 else "critical",
                    "deviation_pct": round(deviation * 100, 1),
                })
        else:
            entry["benchmark_pct"] = None
            entry["deviation_pct"] = None
            entry["is_abnormal"] = False

        # 统计酒水/饮品占比
        if cat_name in ("饮品", "酒水", "饮料"):
            beverage_ratio += ratio

        categories.append(entry)

    # 酒水提醒
    if beverage_ratio < 0.15:
        alerts.append({
            "category": "酒水/饮品",
            "message": f"酒水饮品占比仅{beverage_ratio:.0%}，低于15%。酒水是纯利润品类，建议加强服务员推荐话术和菜单露出",
            "severity": "info",
            "deviation_pct": round((beverage_ratio - 0.15) * 100, 1),
        })

    # 健康度评分：偏差越大分越低（满分100）
    abnormal_count = sum(1 for c in categories if c.get("is_abnormal"))
    health_score = max(0, 100 - abnormal_count * 15)

    log.info(
        "pricing_advisor.category_mix",
        store_id=store_id,
        category_count=len(categories),
        health_score=health_score,
    )

    return {
        "categories": categories,
        "alerts": alerts,
        "health_score": health_score,
        "total_revenue_fen": total_revenue,
        "total_revenue_yuan": _fen_to_yuan(total_revenue),
        "date_from": str(date_from),
        "date_to": str(date_to),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# d) 菜品共现分析
# ═══════════════════════════════════════════════════════════════════════════════


async def compute_dish_co_occurrence(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    date_from: date,
    date_to: date,
    min_co_count: int = 3,
) -> dict[str, Any]:
    """菜品共现分析 — Jaccard相似度 + 下架影响评估

    从同一order_id的order_items中提取菜品对，计算：
      - co_occurrence_count: 同桌出现次数
      - correlation_score: Jaccard相似度 = |A∩B| / |A∪B|

    用途：避免盲目下架。若dog菜与star菜共现率>40%，下架可能影响star菜销量。

    Returns:
        {"pairs": [...], "delist_impact": [...], "total_pairs": int}
    """
    await _set_rls(db, tenant_id)

    # 1. 计算每道菜的独立出现订单数
    dish_orders_result = await db.execute(
        text("""
            SELECT
                oi.dish_id,
                MAX(oi.dish_name) AS dish_name,
                COUNT(DISTINCT oi.order_id) AS order_count
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
                AND o.tenant_id = :tenant_id::uuid
                AND o.store_id = :store_id::uuid
                AND o.status IN ('completed', 'paid')
                AND o.is_deleted = FALSE
                AND o.order_time::date BETWEEN :date_from AND :date_to
            WHERE oi.dish_id IS NOT NULL AND oi.is_deleted = FALSE
            GROUP BY oi.dish_id
            HAVING COUNT(DISTINCT oi.order_id) >= 2
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "date_from": str(date_from),
            "date_to": str(date_to),
        },
    )
    dish_orders = {
        str(r["dish_id"]): {"name": r["dish_name"], "count": r["order_count"]}
        for r in dish_orders_result.mappings().all()
    }

    if len(dish_orders) < 2:
        return {"pairs": [], "delist_impact": [], "total_pairs": 0}

    # 2. 计算共现对（DB侧高效计算）
    co_result = await db.execute(
        text("""
            WITH order_dishes AS (
                SELECT DISTINCT oi.order_id, oi.dish_id
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                    AND o.tenant_id = :tenant_id::uuid
                    AND o.store_id = :store_id::uuid
                    AND o.status IN ('completed', 'paid')
                    AND o.is_deleted = FALSE
                    AND o.order_time::date BETWEEN :date_from AND :date_to
                WHERE oi.dish_id IS NOT NULL AND oi.is_deleted = FALSE
            )
            SELECT
                LEAST(a.dish_id, b.dish_id) AS dish_a_id,
                GREATEST(a.dish_id, b.dish_id) AS dish_b_id,
                COUNT(DISTINCT a.order_id) AS co_count
            FROM order_dishes a
            JOIN order_dishes b ON a.order_id = b.order_id AND a.dish_id < b.dish_id
            GROUP BY LEAST(a.dish_id, b.dish_id), GREATEST(a.dish_id, b.dish_id)
            HAVING COUNT(DISTINCT a.order_id) >= :min_co_count
            ORDER BY co_count DESC
            LIMIT 200
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "date_from": str(date_from),
            "date_to": str(date_to),
            "min_co_count": min_co_count,
        },
    )
    co_rows = co_result.mappings().all()

    pairs: list[dict[str, Any]] = []
    for r in co_rows:
        dish_a = str(r["dish_a_id"])
        dish_b = str(r["dish_b_id"])
        co_count = r["co_count"]

        count_a = dish_orders.get(dish_a, {}).get("count", 0)
        count_b = dish_orders.get(dish_b, {}).get("count", 0)

        # Jaccard = |A∩B| / |A∪B| = co_count / (count_a + count_b - co_count)
        union_count = count_a + count_b - co_count
        jaccard = round(co_count / union_count, 4) if union_count > 0 else 0.0

        pair = {
            "dish_a_id": dish_a,
            "dish_a_name": dish_orders.get(dish_a, {}).get("name", ""),
            "dish_b_id": dish_b,
            "dish_b_name": dish_orders.get(dish_b, {}).get("name", ""),
            "co_occurrence_count": co_count,
            "correlation_score": jaccard,
        }
        pairs.append(pair)

        # 写入 dish_co_occurrence 表
        await db.execute(
            text("""
                INSERT INTO dish_co_occurrence
                    (tenant_id, store_id, dish_a_id, dish_b_id,
                     co_occurrence_count, correlation_score, period_start, period_end)
                VALUES
                    (:tenant_id::uuid, :store_id::uuid, :dish_a::uuid, :dish_b::uuid,
                     :co_count, :jaccard, :period_start, :period_end)
                ON CONFLICT (tenant_id, store_id, dish_a_id, dish_b_id, period_start)
                DO UPDATE SET
                    co_occurrence_count = EXCLUDED.co_occurrence_count,
                    correlation_score = EXCLUDED.correlation_score,
                    period_end = EXCLUDED.period_end,
                    updated_at = NOW()
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "dish_a": dish_a,
                "dish_b": dish_b,
                "co_count": co_count,
                "jaccard": jaccard,
                "period_start": date_from,
                "period_end": date_to,
            },
        )

    await db.commit()

    # 3. 下架影响评估：识别与高价值菜品强关联的低价值菜品
    delist_impact = await _assess_delist_impact(db, tenant_id, store_id, pairs, date_from, date_to)

    log.info(
        "pricing_advisor.co_occurrence",
        store_id=store_id,
        total_pairs=len(pairs),
        high_correlation=sum(1 for p in pairs if p["correlation_score"] > 0.4),
    )

    return {
        "pairs": pairs,
        "delist_impact": delist_impact,
        "total_pairs": len(pairs),
        "date_from": str(date_from),
        "date_to": str(date_to),
    }


async def get_co_occurrence(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    dish_id: Optional[str] = None,
    min_score: float = 0.1,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """查询已存储的共现数据"""
    await _set_rls(db, tenant_id)

    where_extra = ""
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "min_score": min_score,
        "limit": limit,
    }
    if dish_id:
        where_extra = " AND (dco.dish_a_id = :dish_id::uuid OR dco.dish_b_id = :dish_id::uuid)"
        params["dish_id"] = dish_id

    result = await db.execute(
        text(f"""
            SELECT dco.*,
                   da.dish_name AS dish_a_name,
                   db.dish_name AS dish_b_name
            FROM dish_co_occurrence dco
            LEFT JOIN dishes da ON da.id = dco.dish_a_id AND da.tenant_id = dco.tenant_id
            LEFT JOIN dishes db ON db.id = dco.dish_b_id AND db.tenant_id = dco.tenant_id
            WHERE dco.tenant_id = :tenant_id::uuid
              AND dco.store_id = :store_id::uuid
              AND dco.correlation_score >= :min_score
              AND dco.is_deleted = FALSE
              {where_extra}
            ORDER BY dco.correlation_score DESC
            LIMIT :limit
        """),
        params,
    )
    rows = result.mappings().all()

    return [
        {
            "dish_a_id": str(r["dish_a_id"]),
            "dish_a_name": r.get("dish_a_name", ""),
            "dish_b_id": str(r["dish_b_id"]),
            "dish_b_name": r.get("dish_b_name", ""),
            "co_occurrence_count": r["co_occurrence_count"],
            "correlation_score": float(r["correlation_score"]),
            "period_start": str(r["period_start"]),
            "period_end": str(r["period_end"]),
        }
        for r in rows
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# e) 食材价格→菜品成本联动
# ═══════════════════════════════════════════════════════════════════════════════


async def compute_ingredient_price_impact(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
) -> dict[str, Any]:
    """食材价格→菜品成本联动分析

    1. 从最近采购价 vs 上月均价，计算食材涨跌幅
    2. 通过BOM展开：哪些菜品受影响、成本变化多少
    3. 标红毛利跌破30%阈值的菜品

    Returns:
        {
            "ingredient_changes": [...],     # 食材涨跌排行
            "dish_impacts": [...],           # 受影响菜品
            "critical_dishes": [...],        # 毛利跌破阈值
        }
    """
    await _set_rls(db, tenant_id)

    # 1. 食材价格变动：最近采购价 vs 上月均价
    price_changes_result = await db.execute(
        text("""
            WITH latest_price AS (
                SELECT DISTINCT ON (ingredient_id)
                    ingredient_id,
                    unit_price_fen
                FROM purchase_order_items poi
                JOIN purchase_orders po ON po.id = poi.purchase_order_id
                    AND po.tenant_id = :tenant_id::uuid
                    AND po.is_deleted = FALSE
                WHERE poi.is_deleted = FALSE
                ORDER BY ingredient_id, po.order_date DESC
            ),
            last_month_avg AS (
                SELECT
                    poi.ingredient_id,
                    AVG(poi.unit_price_fen)::INT AS avg_price_fen
                FROM purchase_order_items poi
                JOIN purchase_orders po ON po.id = poi.purchase_order_id
                    AND po.tenant_id = :tenant_id::uuid
                    AND po.is_deleted = FALSE
                    AND po.order_date >= (CURRENT_DATE - INTERVAL '30 days')
                    AND po.order_date < CURRENT_DATE
                WHERE poi.is_deleted = FALSE
                GROUP BY poi.ingredient_id
            )
            SELECT
                lp.ingredient_id,
                i.name AS ingredient_name,
                i.unit AS ingredient_unit,
                lp.unit_price_fen AS current_price_fen,
                COALESCE(lma.avg_price_fen, lp.unit_price_fen) AS prev_avg_price_fen
            FROM latest_price lp
            JOIN ingredients i ON i.id = lp.ingredient_id
                AND i.tenant_id = :tenant_id::uuid AND i.is_deleted = FALSE
            LEFT JOIN last_month_avg lma ON lma.ingredient_id = lp.ingredient_id
            ORDER BY ABS(lp.unit_price_fen - COALESCE(lma.avg_price_fen, lp.unit_price_fen)) DESC
            LIMIT 50
        """),
        {"tenant_id": tenant_id},
    )
    price_changes = price_changes_result.mappings().all()

    ingredient_changes: list[dict[str, Any]] = []
    changed_ingredients: dict[str, dict[str, Any]] = {}

    for r in price_changes:
        current = r["current_price_fen"]
        prev = r["prev_avg_price_fen"] or current
        if prev <= 0:
            continue
        change_rate = round((current - prev) / prev, 4) if prev > 0 else 0.0
        ingredient_id = str(r["ingredient_id"])

        entry = {
            "ingredient_id": ingredient_id,
            "ingredient_name": r["ingredient_name"],
            "ingredient_unit": r["ingredient_unit"],
            "current_price_fen": current,
            "current_price_yuan": _fen_to_yuan(current),
            "prev_avg_price_fen": prev,
            "prev_avg_price_yuan": _fen_to_yuan(prev),
            "change_rate": change_rate,
            "change_pct": round(change_rate * 100, 1),
            "direction": "up" if change_rate > 0 else ("down" if change_rate < 0 else "stable"),
        }
        ingredient_changes.append(entry)

        if abs(change_rate) > 0.01:  # 忽略<1%的变动
            changed_ingredients[ingredient_id] = {
                "name": r["ingredient_name"],
                "current_fen": current,
                "prev_fen": prev,
                "change_rate": change_rate,
            }

    # 2. 通过BOM展开受影响菜品
    dish_impacts: list[dict[str, Any]] = []
    critical_dishes: list[dict[str, Any]] = []

    if changed_ingredients:
        ingredient_ids = list(changed_ingredients.keys())
        # 查BOM展开
        bom_result = await db.execute(
            text("""
                SELECT
                    bt.dish_id,
                    d.dish_name,
                    d.price_fen,
                    bi.ingredient_id,
                    bi.standard_qty,
                    COALESCE(bi.waste_factor, 0) AS waste_factor,
                    COALESCE(bi.unit_cost_fen, 0) AS old_unit_cost_fen
                FROM bom_items bi
                JOIN bom_templates bt ON bt.id = bi.bom_id
                    AND bt.tenant_id = :tenant_id::uuid
                    AND bt.is_active = TRUE AND bt.is_deleted = FALSE
                JOIN dishes d ON d.id = bt.dish_id AND d.tenant_id = :tenant_id::uuid
                    AND d.is_deleted = FALSE AND d.is_available = TRUE
                WHERE bi.ingredient_id = ANY(:ingredient_ids::uuid[])
                  AND bi.is_deleted = FALSE
                  AND bi.item_action != 'REMOVE'
            """),
            {"tenant_id": tenant_id, "ingredient_ids": ingredient_ids},
        )
        bom_rows = bom_result.mappings().all()

        # 按菜品聚合影响
        dish_cost_delta: dict[str, dict[str, Any]] = {}
        for br in bom_rows:
            dish_id = str(br["dish_id"])
            ing_id = str(br["ingredient_id"])
            ing_change = changed_ingredients.get(ing_id)
            if not ing_change:
                continue

            qty = float(br["standard_qty"])
            waste = float(br["waste_factor"])
            usage = qty * (1 + waste)

            old_cost_per_use = float(br["old_unit_cost_fen"]) * usage
            new_cost_per_use = float(ing_change["current_fen"]) * usage
            delta_fen = int(new_cost_per_use - old_cost_per_use)

            if dish_id not in dish_cost_delta:
                dish_cost_delta[dish_id] = {
                    "dish_name": br["dish_name"],
                    "price_fen": br["price_fen"],
                    "total_delta_fen": 0,
                    "affected_ingredients": [],
                }
            dish_cost_delta[dish_id]["total_delta_fen"] += delta_fen
            dish_cost_delta[dish_id]["affected_ingredients"].append({
                "ingredient_name": ing_change["name"],
                "change_pct": round(ing_change["change_rate"] * 100, 1),
                "cost_delta_fen": delta_fen,
            })

        for dish_id, info in dish_cost_delta.items():
            price = info["price_fen"] or 0
            # 估算新成本 = 旧BOM成本 + delta
            old_bom_cost = await _get_dish_bom_cost(db, tenant_id, dish_id)
            new_cost = old_bom_cost + info["total_delta_fen"]
            new_margin = _margin_rate(price, new_cost)

            impact = {
                "dish_id": dish_id,
                "dish_name": info["dish_name"],
                "price_fen": price,
                "price_yuan": _fen_to_yuan(price),
                "old_cost_fen": old_bom_cost,
                "new_cost_fen": new_cost,
                "cost_delta_fen": info["total_delta_fen"],
                "cost_delta_yuan": _fen_to_yuan(info["total_delta_fen"]),
                "new_margin_rate": float(new_margin),
                "is_critical": new_margin < _MARGIN_ALERT_THRESHOLD,
                "affected_ingredients": info["affected_ingredients"],
            }
            dish_impacts.append(impact)

            if new_margin < _MARGIN_ALERT_THRESHOLD:
                critical_dishes.append(impact)

    # 排序
    dish_impacts.sort(key=lambda x: x["cost_delta_fen"], reverse=True)
    ingredient_changes.sort(key=lambda x: abs(x["change_rate"]), reverse=True)

    log.info(
        "pricing_advisor.ingredient_impact",
        total_ingredients=len(ingredient_changes),
        affected_dishes=len(dish_impacts),
        critical=len(critical_dishes),
    )

    return {
        "ingredient_changes": ingredient_changes,
        "dish_impacts": dish_impacts,
        "critical_dishes": critical_dishes,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 内部辅助函数
# ═══════════════════════════════════════════════════════════════════════════════


async def _fetch_dish_bcg_data(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    date_from: date,
    date_to: date,
) -> list[dict[str, Any]]:
    """获取菜品BCG分类所需的销量+毛利数据"""
    result = await db.execute(
        text("""
            SELECT
                d.id AS dish_id,
                d.dish_name,
                d.price_fen,
                COALESCE(d.cost_fen, 0) AS cost_fen,
                COALESCE(dc.name, '其他') AS category_name,
                COALESCE(SUM(oi.quantity), 0) AS sales_qty,
                COALESCE(SUM(oi.quantity * oi.unit_price_fen), 0) AS revenue_fen
            FROM dishes d
            LEFT JOIN dish_categories dc ON dc.id = d.category_id
            LEFT JOIN order_items oi ON oi.dish_id = d.id AND oi.is_deleted = FALSE
            LEFT JOIN orders o ON o.id = oi.order_id
                AND o.tenant_id = :tenant_id::uuid
                AND o.store_id = :store_id::uuid
                AND o.status IN ('completed', 'paid')
                AND o.is_deleted = FALSE
                AND o.order_time::date BETWEEN :date_from AND :date_to
            WHERE d.tenant_id = :tenant_id::uuid
              AND d.is_deleted = FALSE
              AND d.is_available = TRUE
            GROUP BY d.id, d.dish_name, d.price_fen, d.cost_fen, dc.name
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "date_from": str(date_from),
            "date_to": str(date_to),
        },
    )
    rows = result.mappings().all()

    return [
        {
            "dish_id": str(r["dish_id"]),
            "dish_name": r["dish_name"] or "",
            "price_fen": r["price_fen"] or 0,
            "cost_fen": r["cost_fen"] or 0,
            "category": r["category_name"],
            "sales_qty": r["sales_qty"] or 0,
            "revenue_fen": r["revenue_fen"] or 0,
            "margin_rate": _margin_rate(r["price_fen"] or 0, r["cost_fen"] or 0),
        }
        for r in rows
    ]


def _classify_bcg(dishes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """BCG四象限分类

    横轴：销量（相对中位数）
    纵轴：毛利率（相对中位数）

    star:          高销量 + 高毛利
    cash_cow:      高销量 + 低毛利
    question_mark: 低销量 + 高毛利
    dog:           低销量 + 低毛利
    """
    if not dishes:
        return []

    sales_list = sorted(d["sales_qty"] for d in dishes)
    margin_list = sorted(float(d["margin_rate"]) for d in dishes)

    n = len(dishes)
    median_sales = sales_list[n // 2] if n > 0 else 0
    median_margin = margin_list[n // 2] if n > 0 else 0.0

    for d in dishes:
        high_sales = d["sales_qty"] >= median_sales
        high_margin = float(d["margin_rate"]) >= median_margin

        if high_sales and high_margin:
            d["bcg_quadrant"] = "star"
        elif high_sales and not high_margin:
            d["bcg_quadrant"] = "cash_cow"
        elif not high_sales and high_margin:
            d["bcg_quadrant"] = "question_mark"
        else:
            d["bcg_quadrant"] = "dog"

    return dishes


async def _check_cost_change(
    db: AsyncSession,
    tenant_id: str,
    dish_id: str,
    period_days: int,
) -> float:
    """检查菜品BOM成本变动幅度（返回变动比例，如0.08表示上涨8%）"""
    result = await db.execute(
        text("""
            WITH current_cost AS (
                SELECT COALESCE(SUM(
                    CAST(bi.standard_qty * (1 + COALESCE(bi.waste_factor, 0))
                         * COALESCE(bi.unit_cost_fen, 0) AS INTEGER)
                ), 0) AS cost
                FROM bom_items bi
                JOIN bom_templates bt ON bt.id = bi.bom_id
                    AND bt.dish_id = :dish_id::uuid
                    AND bt.tenant_id = :tenant_id::uuid
                    AND bt.is_active = TRUE AND bt.is_deleted = FALSE
                WHERE bi.is_deleted = FALSE AND bi.item_action != 'REMOVE'
            )
            SELECT cost FROM current_cost
        """),
        {"tenant_id": tenant_id, "dish_id": dish_id},
    )
    current_cost = result.scalar_one_or_none() or 0
    if current_cost <= 0:
        return 0.0

    # 简化：假设上期成本 = dishes.cost_fen（BOM历史版本暂不追踪）
    dish_result = await db.execute(
        text("""
            SELECT cost_fen FROM dishes
            WHERE id = :dish_id::uuid AND tenant_id = :tenant_id::uuid AND is_deleted = FALSE
        """),
        {"tenant_id": tenant_id, "dish_id": dish_id},
    )
    base_cost = dish_result.scalar_one_or_none() or current_cost
    if base_cost <= 0:
        return 0.0

    return (current_cost - base_cost) / base_cost


async def _assess_delist_impact(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    pairs: list[dict[str, Any]],
    date_from: date,
    date_to: date,
) -> list[dict[str, Any]]:
    """评估下架菜品对关联菜品的影响

    规则：如果dog菜与star菜共现率>40%，下架可能影响star菜销量
    """
    if not pairs:
        return []

    # 获取BCG分类
    dishes = await _fetch_dish_bcg_data(db, tenant_id, store_id, date_from, date_to)
    dishes_with_bcg = _classify_bcg(dishes)
    bcg_map: dict[str, dict[str, Any]] = {d["dish_id"]: d for d in dishes_with_bcg}

    impact_list: list[dict[str, Any]] = []
    for pair in pairs:
        if pair["correlation_score"] < _CO_OCCURRENCE_IMPACT_THRESHOLD:
            continue

        dish_a = bcg_map.get(pair["dish_a_id"], {})
        dish_b = bcg_map.get(pair["dish_b_id"], {})

        # 检查是否有dog与star/cash_cow的高共现
        for candidate, partner in [(dish_a, dish_b), (dish_b, dish_a)]:
            if not candidate or not partner:
                continue
            if candidate.get("bcg_quadrant") == "dog" and partner.get("bcg_quadrant") in ("star", "cash_cow"):
                estimated_sales_impact = int(
                    partner.get("sales_qty", 0) * pair["correlation_score"] * 0.3
                )
                impact_list.append({
                    "delist_dish_id": candidate["dish_id"],
                    "delist_dish_name": candidate.get("dish_name", ""),
                    "delist_bcg": "dog",
                    "impacted_dish_id": partner["dish_id"],
                    "impacted_dish_name": partner.get("dish_name", ""),
                    "impacted_bcg": partner.get("bcg_quadrant", ""),
                    "co_occurrence_rate": pair["correlation_score"],
                    "estimated_sales_loss_qty": estimated_sales_impact,
                    "warning": (
                        f"下架「{candidate.get('dish_name', '')}」可能导致"
                        f"「{partner.get('dish_name', '')}」销量下降约{estimated_sales_impact}份/周期，"
                        f"共现率{pair['correlation_score']:.0%}，建议谨慎评估"
                    ),
                })

    return impact_list


async def _get_dish_bom_cost(db: AsyncSession, tenant_id: str, dish_id: str) -> int:
    """获取菜品当前BOM理论成本（分）"""
    result = await db.execute(
        text("""
            SELECT COALESCE(SUM(
                CAST(bi.standard_qty * (1 + COALESCE(bi.waste_factor, 0))
                     * COALESCE(bi.unit_cost_fen, 0) AS INTEGER)
            ), 0) AS total_cost
            FROM bom_items bi
            JOIN bom_templates bt ON bt.id = bi.bom_id
                AND bt.dish_id = :dish_id::uuid
                AND bt.tenant_id = :tenant_id::uuid
                AND bt.is_active = TRUE AND bt.is_deleted = FALSE
            WHERE bi.is_deleted = FALSE AND bi.item_action != 'REMOVE'
        """),
        {"tenant_id": tenant_id, "dish_id": dish_id},
    )
    return result.scalar_one_or_none() or 0
