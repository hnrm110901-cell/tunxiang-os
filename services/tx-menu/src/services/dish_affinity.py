"""菜品亲和矩阵服务 — 基于订单明细共现分析计算菜品间关联强度

核心功能：
  1. compute_affinity_matrix — 从order_items共现计算亲和矩阵，归一化0-1
  2. get_affinities — 查询指定菜品的关联菜品列表
  3. get_combo_suggestions — 根据购物车已选菜品推荐加购组合

数据源：
  order_items — dish_id, order_id
  orders — id, tenant_id, store_id, status='paid', created_at
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

log = structlog.get_logger(__name__)

# 周期天数映射
PERIOD_DAYS = {
    "last_7d": 7,
    "last_30d": 30,
    "last_90d": 90,
    "all_time": 3650,
}


async def _set_rls(db: Any, tenant_id: str) -> None:
    """设置RLS租户上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


async def compute_affinity_matrix(
    db: Any,
    tenant_id: str,
    store_id: str,
    period: str = "last_30d",
) -> dict:
    """从order_items共现关系计算菜品亲和矩阵

    算法:
      1. 取指定周期内已支付订单的order_items
      2. 同一订单内的菜品对计为一次共现
      3. affinity_score = co_occurrence / max_co_occurrence (归一化到0-1)
      4. UPSERT到dish_affinity_matrix表

    Returns: {pairs_computed: int, max_co_occurrence: int}
    """
    await _set_rls(db, tenant_id)

    days = PERIOD_DAYS.get(period, 30)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    log.info(
        "compute_affinity_start",
        tenant_id=str(tenant_id),
        store_id=str(store_id),
        period=period,
        since=since.isoformat(),
    )

    try:
        # 步骤1: 计算共现对及其出现次数
        co_result = await db.execute(
            text("""
                WITH paid_items AS (
                    SELECT oi.dish_id, oi.order_id
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    WHERE o.tenant_id = :tenant_id
                      AND o.store_id = :store_id
                      AND o.status = 'paid'
                      AND o.created_at >= :since
                      AND o.is_deleted = FALSE
                      AND oi.is_deleted = FALSE
                ),
                total_orders AS (
                    SELECT COUNT(DISTINCT order_id) AS cnt FROM paid_items
                )
                SELECT
                    a.dish_id AS dish_a_id,
                    b.dish_id AS dish_b_id,
                    COUNT(DISTINCT a.order_id) AS co_occurrence_count,
                    (SELECT cnt FROM total_orders) AS sample_order_count
                FROM paid_items a
                JOIN paid_items b
                    ON a.order_id = b.order_id
                    AND a.dish_id < b.dish_id
                GROUP BY a.dish_id, b.dish_id
                HAVING COUNT(DISTINCT a.order_id) >= 2
                ORDER BY co_occurrence_count DESC
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "since": since,
            },
        )
        pairs = co_result.mappings().all()

        if not pairs:
            log.info("compute_affinity_no_pairs", tenant_id=str(tenant_id))
            return {"pairs_computed": 0, "max_co_occurrence": 0}

        # 步骤2: 归一化 — max normalization到0-1
        max_co = max(row["co_occurrence_count"] for row in pairs)
        sample_count = pairs[0]["sample_order_count"] if pairs else 0

        # 步骤3: 软删除旧数据
        await db.execute(
            text("""
                UPDATE dish_affinity_matrix
                SET is_deleted = TRUE, updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND period = :period
                  AND is_deleted = FALSE
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "period": period,
            },
        )

        # 步骤4: 批量插入新亲和数据
        for row in pairs:
            score = row["co_occurrence_count"] / max_co if max_co > 0 else 0.0
            await db.execute(
                text("""
                    INSERT INTO dish_affinity_matrix
                        (tenant_id, store_id, dish_a_id, dish_b_id,
                         co_occurrence_count, affinity_score, period,
                         sample_order_count)
                    VALUES
                        (:tenant_id, :store_id, :dish_a_id, :dish_b_id,
                         :co_count, :score, :period, :sample_count)
                    ON CONFLICT (tenant_id, store_id, dish_a_id, dish_b_id, period)
                    DO UPDATE SET
                        co_occurrence_count = EXCLUDED.co_occurrence_count,
                        affinity_score = EXCLUDED.affinity_score,
                        sample_order_count = EXCLUDED.sample_order_count,
                        is_deleted = FALSE,
                        updated_at = NOW()
                """),
                {
                    "tenant_id": str(tenant_id),
                    "store_id": str(store_id),
                    "dish_a_id": str(row["dish_a_id"]),
                    "dish_b_id": str(row["dish_b_id"]),
                    "co_count": row["co_occurrence_count"],
                    "score": round(score, 6),
                    "period": period,
                    "sample_count": sample_count,
                },
            )

        await db.commit()

        log.info(
            "compute_affinity_done",
            tenant_id=str(tenant_id),
            pairs_computed=len(pairs),
            max_co_occurrence=max_co,
        )
        return {"pairs_computed": len(pairs), "max_co_occurrence": max_co}

    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("compute_affinity_db_error", error=str(exc), tenant_id=str(tenant_id))
        raise


async def get_affinities(
    db: Any,
    tenant_id: str,
    store_id: str,
    dish_id: str,
    period: str = "last_30d",
    limit: int = 10,
) -> list[dict]:
    """查询指定菜品的关联菜品列表，按affinity_score降序

    Returns: [{dish_id, affinity_score, co_occurrence_count}, ...]
    """
    await _set_rls(db, tenant_id)

    try:
        result = await db.execute(
            text("""
                SELECT
                    CASE WHEN dish_a_id = :dish_id THEN dish_b_id ELSE dish_a_id END AS related_dish_id,
                    affinity_score,
                    co_occurrence_count
                FROM dish_affinity_matrix
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND period = :period
                  AND is_deleted = FALSE
                  AND (dish_a_id = :dish_id OR dish_b_id = :dish_id)
                ORDER BY affinity_score DESC
                LIMIT :lim
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "dish_id": str(dish_id),
                "period": period,
                "lim": limit,
            },
        )
        rows = result.mappings().all()
        return [
            {
                "dish_id": str(r["related_dish_id"]),
                "affinity_score": r["affinity_score"],
                "co_occurrence_count": r["co_occurrence_count"],
            }
            for r in rows
        ]
    except SQLAlchemyError as exc:
        log.error("get_affinities_error", error=str(exc), dish_id=str(dish_id))
        raise


async def get_combo_suggestions(
    db: Any,
    tenant_id: str,
    store_id: str,
    cart_dish_ids: list[str],
    period: str = "last_30d",
    limit: int = 5,
) -> list[dict]:
    """根据购物车已选菜品推荐加购组合

    算法: 查找与购物车内所有菜品都有亲和关系的菜品，
    按累计affinity_score排序，排除已在购物车中的菜品。

    Returns: [{dish_id, total_affinity, related_to_count, top_pair_score}, ...]
    """
    await _set_rls(db, tenant_id)

    if not cart_dish_ids:
        return []

    cart_ids_str = [str(d) for d in cart_dish_ids]

    try:
        result = await db.execute(
            text("""
                WITH cart_affinities AS (
                    SELECT
                        CASE
                            WHEN dish_a_id = ANY(:cart_ids) THEN dish_b_id
                            ELSE dish_a_id
                        END AS suggest_dish_id,
                        affinity_score
                    FROM dish_affinity_matrix
                    WHERE tenant_id = :tenant_id
                      AND store_id = :store_id
                      AND period = :period
                      AND is_deleted = FALSE
                      AND (dish_a_id = ANY(:cart_ids) OR dish_b_id = ANY(:cart_ids))
                )
                SELECT
                    suggest_dish_id AS dish_id,
                    SUM(affinity_score) AS total_affinity,
                    COUNT(*) AS related_to_count,
                    MAX(affinity_score) AS top_pair_score
                FROM cart_affinities
                WHERE suggest_dish_id != ALL(:cart_ids)
                GROUP BY suggest_dish_id
                ORDER BY total_affinity DESC
                LIMIT :lim
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "cart_ids": cart_ids_str,
                "period": period,
                "lim": limit,
            },
        )
        rows = result.mappings().all()
        return [
            {
                "dish_id": str(r["dish_id"]),
                "total_affinity": round(float(r["total_affinity"]), 4),
                "related_to_count": r["related_to_count"],
                "top_pair_score": round(float(r["top_pair_score"]), 4),
            }
            for r in rows
        ]
    except SQLAlchemyError as exc:
        log.error("get_combo_suggestions_error", error=str(exc))
        raise


def normalize_scores(co_occurrences: list[int]) -> list[float]:
    """将共现次数列表归一化到0-1区间（纯函数，供测试使用）

    Args:
        co_occurrences: 共现次数列表

    Returns:
        归一化后的分数列表，max=1.0, min>0
    """
    if not co_occurrences:
        return []
    max_val = max(co_occurrences)
    if max_val == 0:
        return [0.0] * len(co_occurrences)
    return [round(c / max_val, 6) for c in co_occurrences]
