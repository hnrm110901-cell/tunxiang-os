"""实时推荐引擎 API — 点餐推荐 + 加单推荐 + 回访推荐 + 推荐效果

端点列表：
  POST   /api/v1/member/recommend/order-time           点餐时实时推荐
  GET    /api/v1/member/recommend/upsell/{order_id}    加单推荐（结账前）
  GET    /api/v1/member/recommend/return/{customer_id}  回访推荐
  GET    /api/v1/member/recommend/metrics                推荐效果统计

对标：Olo Guest Intelligence 交叉推荐（篮子提升 10%）
"""
import uuid
from datetime import datetime, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..db import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/member/recommend", tags=["recommendation"])


# ── 工具函数 ─────────────────────────────────────────────────────────────────


async def _set_tenant(db, tenant_id: str) -> None:
    """设置 RLS app.tenant_id"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _current_meal_period() -> str:
    """根据当前时间判断餐段"""
    hour = datetime.now().hour
    if 6 <= hour < 10:
        return "breakfast"
    elif 10 <= hour < 14:
        return "lunch"
    elif 14 <= hour < 17:
        return "afternoon_tea"
    elif 17 <= hour < 21:
        return "dinner"
    else:
        return "late_night"


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────


class OrderTimeRecommendReq(BaseModel):
    customer_id: str = Field(description="顾客ID")
    store_id: str = Field(description="门店ID")
    current_cart_items: list[str] = Field(
        default_factory=list,
        description="当前购物车中的菜品ID列表",
    )
    meal_period: Optional[str] = Field(
        None,
        description="餐段（breakfast/lunch/dinner/afternoon_tea/late_night），不传则自动判断",
    )
    limit: int = Field(default=5, ge=1, le=20, description="推荐数量")


class RecommendItem(BaseModel):
    dish_id: str
    dish_name: str
    price_fen: int
    reason: str
    score: float = Field(description="推荐分数 0-1")
    reason_type: str = Field(description="推荐原因类型: history/hot/association/margin")


# ── 端点实现 ──────────────────────────────────────────────────────────────────


@router.post("/order-time")
async def recommend_at_order_time(
    req: OrderTimeRecommendReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """点餐时实时推荐

    推荐逻辑（按优先级加权）：
    1. 客户历史偏好（常点菜/口味/价格区间）— 权重 0.35
    2. 时段热销菜品 — 权重 0.25
    3. 购物篮关联规则（买了 A 常买 B）— 权重 0.25
    4. 高毛利菜品优先 — 权重 0.15

    输出：推荐菜品列表(top N) + 推荐理由
    """
    try:
        uuid.UUID(x_tenant_id)
        uuid.UUID(req.customer_id)
        uuid.UUID(req.store_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {e}") from e

    meal_period = req.meal_period or _current_meal_period()

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            candidates: dict[str, dict] = {}  # dish_id -> {score, reasons, ...}

            # ── 1. 客户历史偏好（常点菜 Top 10）──────────────────────────
            history_result = await db.execute(
                text("""
                    SELECT oi.dish_id, d.name AS dish_name,
                           d.price_fen, COUNT(*) AS order_count
                    FROM order_items oi
                    JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
                    JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                    WHERE oi.tenant_id = :tenant_id
                      AND o.customer_id = :customer_id
                      AND o.status = 'paid'
                      AND o.created_at >= NOW() - INTERVAL '90 days'
                      AND d.is_deleted = FALSE
                    GROUP BY oi.dish_id, d.name, d.price_fen
                    ORDER BY order_count DESC
                    LIMIT 10
                """),
                {"tenant_id": x_tenant_id, "customer_id": req.customer_id},
            )
            for r in history_result.fetchall():
                did = str(r.dish_id)
                if did not in req.current_cart_items:
                    score = min(r.order_count / 10.0, 1.0) * 0.35
                    candidates[did] = {
                        "dish_id": did,
                        "dish_name": r.dish_name,
                        "price_fen": r.price_fen,
                        "score": score,
                        "reason": f"您最近90天点过{r.order_count}次",
                        "reason_type": "history",
                    }

            # ── 2. 时段热销菜品 Top 10 ───────────────────────────────────
            hot_result = await db.execute(
                text("""
                    SELECT oi.dish_id, d.name AS dish_name,
                           d.price_fen, COUNT(*) AS sale_count
                    FROM order_items oi
                    JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
                    JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                    WHERE oi.tenant_id = :tenant_id
                      AND o.store_id = :store_id
                      AND o.status = 'paid'
                      AND o.created_at >= NOW() - INTERVAL '7 days'
                      AND d.is_deleted = FALSE
                    GROUP BY oi.dish_id, d.name, d.price_fen
                    ORDER BY sale_count DESC
                    LIMIT 10
                """),
                {
                    "tenant_id": x_tenant_id,
                    "store_id": req.store_id,
                },
            )
            for r in hot_result.fetchall():
                did = str(r.dish_id)
                if did in req.current_cart_items:
                    continue
                hot_score = min(r.sale_count / 50.0, 1.0) * 0.25
                if did in candidates:
                    candidates[did]["score"] += hot_score
                    candidates[did]["reason"] += f"，本店近7天热销{r.sale_count}份"
                else:
                    candidates[did] = {
                        "dish_id": did,
                        "dish_name": r.dish_name,
                        "price_fen": r.price_fen,
                        "score": hot_score,
                        "reason": f"本店近7天热销{r.sale_count}份",
                        "reason_type": "hot",
                    }

            # ── 3. 购物篮关联规则（买了 A 常买 B）──────────────────────────
            if req.current_cart_items:
                # 查找与当前购物车菜品经常一起购买的菜品
                cart_ids = [str(cid) for cid in req.current_cart_items]
                # 使用参数化查询（最多取前3个购物车商品做关联）
                for cart_item_id in cart_ids[:3]:
                    assoc_result = await db.execute(
                        text("""
                            SELECT oi2.dish_id, d.name AS dish_name,
                                   d.price_fen, COUNT(*) AS co_count
                            FROM order_items oi1
                            JOIN order_items oi2
                                ON oi1.order_id = oi2.order_id
                                AND oi1.tenant_id = oi2.tenant_id
                                AND oi1.dish_id != oi2.dish_id
                            JOIN dishes d ON d.id = oi2.dish_id AND d.tenant_id = oi2.tenant_id
                            WHERE oi1.tenant_id = :tenant_id
                              AND oi1.dish_id = :cart_dish_id
                              AND d.is_deleted = FALSE
                            GROUP BY oi2.dish_id, d.name, d.price_fen
                            ORDER BY co_count DESC
                            LIMIT 5
                        """),
                        {"tenant_id": x_tenant_id, "cart_dish_id": cart_item_id},
                    )
                    for r in assoc_result.fetchall():
                        did = str(r.dish_id)
                        if did in req.current_cart_items:
                            continue
                        assoc_score = min(r.co_count / 20.0, 1.0) * 0.25
                        if did in candidates:
                            candidates[did]["score"] += assoc_score
                        else:
                            candidates[did] = {
                                "dish_id": did,
                                "dish_name": r.dish_name,
                                "price_fen": r.price_fen,
                                "score": assoc_score,
                                "reason": f"常与您已选菜品搭配购买（{r.co_count}次）",
                                "reason_type": "association",
                            }

            # ── 4. 高毛利菜品加分 ──────────────────────────────────────────
            margin_result = await db.execute(
                text("""
                    SELECT id AS dish_id, name AS dish_name,
                           price_fen,
                           CASE WHEN cost_fen > 0
                                THEN (price_fen - cost_fen)::FLOAT / price_fen
                                ELSE 0.5
                           END AS margin_rate
                    FROM dishes
                    WHERE tenant_id = :tenant_id
                      AND is_deleted = FALSE
                      AND status = 'on_sale'
                    ORDER BY margin_rate DESC
                    LIMIT 20
                """),
                {"tenant_id": x_tenant_id},
            )
            for r in margin_result.fetchall():
                did = str(r.dish_id)
                if did in req.current_cart_items:
                    continue
                margin_score = r.margin_rate * 0.15
                if did in candidates:
                    candidates[did]["score"] += margin_score
                else:
                    candidates[did] = {
                        "dish_id": did,
                        "dish_name": r.dish_name,
                        "price_fen": r.price_fen,
                        "score": margin_score,
                        "reason": "厨师推荐",
                        "reason_type": "margin",
                    }

            # ── 排序取 Top N ──────────────────────────────────────────────
            sorted_candidates = sorted(
                candidates.values(),
                key=lambda x: x["score"],
                reverse=True,
            )[:req.limit]

            # 写入推荐日志
            for item in sorted_candidates:
                await db.execute(
                    text("""
                        INSERT INTO recommendation_logs
                            (id, tenant_id, customer_id, store_id, scene,
                             recommended_dish_id, recommended_dish_name,
                             score, reason, reason_type, is_accepted, created_at)
                        VALUES
                            (:id, :tenant_id, :customer_id, :store_id, 'order_time',
                             :dish_id, :dish_name,
                             :score, :reason, :reason_type, FALSE, NOW())
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "tenant_id": x_tenant_id,
                        "customer_id": req.customer_id,
                        "store_id": req.store_id,
                        "dish_id": item["dish_id"],
                        "dish_name": item["dish_name"],
                        "score": item["score"],
                        "reason": item["reason"],
                        "reason_type": item["reason_type"],
                    },
                )
            await db.commit()

            logger.info(
                "order_time_recommend",
                tenant_id=x_tenant_id,
                customer_id=req.customer_id,
                store_id=req.store_id,
                meal_period=meal_period,
                recommend_count=len(sorted_candidates),
            )
            return {
                "ok": True,
                "data": {
                    "customer_id": req.customer_id,
                    "store_id": req.store_id,
                    "meal_period": meal_period,
                    "recommendations": sorted_candidates,
                },
                "error": {},
            }

        except HTTPException:
            raise
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("order_time_recommend_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="点餐推荐失败") from e


@router.get("/upsell/{order_id}")
async def recommend_upsell(
    order_id: str,
    limit: int = Query(default=3, ge=1, le=10),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """加单推荐（结账前）

    "再加一个甜品？张先生上次很喜欢芒果班戟"

    逻辑：
    1. 获取当前订单中的菜品
    2. 查看客户历史上曾点但本次未点的高满意度菜品
    3. 当前订单缺少的品类（如无甜品/无饮品）
    4. 用个性化话术生成推荐理由
    """
    try:
        uuid.UUID(x_tenant_id)
        uuid.UUID(order_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {e}") from e

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            # 获取当前订单信息
            order_result = await db.execute(
                text("""
                    SELECT o.customer_id, o.store_id, o.total_fen,
                           c.display_name AS customer_name
                    FROM orders o
                    LEFT JOIN customers c
                        ON c.id = o.customer_id AND c.tenant_id = o.tenant_id
                    WHERE o.id = :order_id
                      AND o.tenant_id = :tenant_id
                """),
                {"order_id": order_id, "tenant_id": x_tenant_id},
            )
            order_row = order_result.fetchone()
            if not order_row:
                raise HTTPException(status_code=404, detail="订单不存在")

            customer_id = str(order_row.customer_id) if order_row.customer_id else None
            customer_name = order_row.customer_name or "顾客"
            store_id = str(order_row.store_id) if order_row.store_id else None

            # 获取当前订单菜品
            current_items_result = await db.execute(
                text("""
                    SELECT dish_id FROM order_items
                    WHERE order_id = :order_id
                      AND tenant_id = :tenant_id
                """),
                {"order_id": order_id, "tenant_id": x_tenant_id},
            )
            current_dish_ids = {str(r.dish_id) for r in current_items_result.fetchall()}

            # 获取当前订单菜品的品类
            current_categories_result = await db.execute(
                text("""
                    SELECT DISTINCT d.category
                    FROM order_items oi
                    JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
                    WHERE oi.order_id = :order_id
                      AND oi.tenant_id = :tenant_id
                """),
                {"order_id": order_id, "tenant_id": x_tenant_id},
            )
            current_categories = {r.category for r in current_categories_result.fetchall() if r.category}

            upsell_items: list[dict] = []

            # 策略1：客户曾点但本次未点的高频菜品
            if customer_id:
                history_fav = await db.execute(
                    text("""
                        SELECT oi.dish_id, d.name AS dish_name,
                               d.price_fen, d.category, COUNT(*) AS freq
                        FROM order_items oi
                        JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
                        JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                        WHERE oi.tenant_id = :tenant_id
                          AND o.customer_id = :customer_id
                          AND o.status = 'paid'
                          AND d.is_deleted = FALSE
                        GROUP BY oi.dish_id, d.name, d.price_fen, d.category
                        ORDER BY freq DESC
                        LIMIT 20
                    """),
                    {"tenant_id": x_tenant_id, "customer_id": customer_id},
                )
                for r in history_fav.fetchall():
                    did = str(r.dish_id)
                    if did not in current_dish_ids and len(upsell_items) < limit:
                        name_prefix = customer_name[:1] + ("先生" if len(customer_name) <= 3 else "")
                        upsell_items.append({
                            "dish_id": did,
                            "dish_name": r.dish_name,
                            "price_fen": r.price_fen,
                            "category": r.category,
                            "reason": f"{name_prefix}您之前点过{r.freq}次{r.dish_name}，要不要再来一份？",
                            "reason_type": "history_favorite",
                            "score": min(r.freq / 5.0, 1.0),
                        })

            # 策略2：补充缺失品类（甜品/饮品）
            complement_categories = {"甜品", "饮品", "小吃"} - current_categories
            if complement_categories and len(upsell_items) < limit:
                for cat in complement_categories:
                    cat_result = await db.execute(
                        text("""
                            SELECT id AS dish_id, name AS dish_name, price_fen, category
                            FROM dishes
                            WHERE tenant_id = :tenant_id
                              AND category = :category
                              AND status = 'on_sale'
                              AND is_deleted = FALSE
                            ORDER BY RANDOM()
                            LIMIT 2
                        """),
                        {"tenant_id": x_tenant_id, "category": cat},
                    )
                    for r in cat_result.fetchall():
                        did = str(r.dish_id)
                        if did not in current_dish_ids and len(upsell_items) < limit:
                            upsell_items.append({
                                "dish_id": did,
                                "dish_name": r.dish_name,
                                "price_fen": r.price_fen,
                                "category": r.category,
                                "reason": f"搭配一份{r.dish_name}，用餐体验更佳",
                                "reason_type": "category_complement",
                                "score": 0.6,
                            })

            # 写推荐日志
            for item in upsell_items:
                await db.execute(
                    text("""
                        INSERT INTO recommendation_logs
                            (id, tenant_id, customer_id, store_id, scene,
                             recommended_dish_id, recommended_dish_name,
                             score, reason, reason_type, is_accepted,
                             order_id, created_at)
                        VALUES
                            (:id, :tenant_id, :customer_id, :store_id, 'upsell',
                             :dish_id, :dish_name,
                             :score, :reason, :reason_type, FALSE,
                             :order_id, NOW())
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "tenant_id": x_tenant_id,
                        "customer_id": customer_id,
                        "store_id": store_id,
                        "dish_id": item["dish_id"],
                        "dish_name": item["dish_name"],
                        "score": item["score"],
                        "reason": item["reason"],
                        "reason_type": item["reason_type"],
                        "order_id": order_id,
                    },
                )
            await db.commit()

            logger.info(
                "upsell_recommend",
                tenant_id=x_tenant_id,
                order_id=order_id,
                customer_id=customer_id,
                recommend_count=len(upsell_items),
            )
            return {
                "ok": True,
                "data": {
                    "order_id": order_id,
                    "customer_name": customer_name,
                    "recommendations": upsell_items,
                },
                "error": {},
            }

        except HTTPException:
            raise
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("upsell_recommend_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="加单推荐失败") from e


@router.get("/return/{customer_id}")
async def recommend_return_visit(
    customer_id: str,
    limit: int = Query(default=5, ge=1, le=10),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """回访推荐：预测该客户下次可能想吃的菜

    逻辑：
    1. 分析最近5次消费的菜品偏好趋势
    2. 识别未尝试过的同品类热门菜（探索推荐）
    3. 季节性/时令菜品推荐
    4. 结合 RFM 分层调整推荐策略
    """
    try:
        uuid.UUID(x_tenant_id)
        uuid.UUID(customer_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {e}") from e

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            recommendations: list[dict] = []

            # 获取客户基本信息
            customer_result = await db.execute(
                text("""
                    SELECT display_name,
                           COALESCE(
                               (SELECT rfm_level FROM member_rfm
                                WHERE tenant_id = :tenant_id AND customer_id = :customer_id
                                LIMIT 1),
                               'S3'
                           ) AS rfm_level
                    FROM customers
                    WHERE id = :customer_id
                      AND tenant_id = :tenant_id
                """),
                {"tenant_id": x_tenant_id, "customer_id": customer_id},
            )
            cust_row = customer_result.fetchone()
            customer_name = cust_row.display_name if cust_row else "顾客"
            rfm_level = cust_row.rfm_level if cust_row else "S3"

            # 策略1：最近偏好的品类中的新菜品（探索推荐）
            recent_cats = await db.execute(
                text("""
                    SELECT d.category, COUNT(*) AS cat_count
                    FROM order_items oi
                    JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
                    JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                    WHERE oi.tenant_id = :tenant_id
                      AND o.customer_id = :customer_id
                      AND o.status = 'paid'
                      AND o.created_at >= NOW() - INTERVAL '60 days'
                    GROUP BY d.category
                    ORDER BY cat_count DESC
                    LIMIT 3
                """),
                {"tenant_id": x_tenant_id, "customer_id": customer_id},
            )
            fav_categories = [r.category for r in recent_cats.fetchall() if r.category]

            # 查该客户未吃过但同品类热门的菜
            already_tried = await db.execute(
                text("""
                    SELECT DISTINCT oi.dish_id
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                    WHERE oi.tenant_id = :tenant_id
                      AND o.customer_id = :customer_id
                      AND o.status = 'paid'
                """),
                {"tenant_id": x_tenant_id, "customer_id": customer_id},
            )
            tried_ids = {str(r.dish_id) for r in already_tried.fetchall()}

            for cat in fav_categories:
                if len(recommendations) >= limit:
                    break
                explore_result = await db.execute(
                    text("""
                        SELECT d.id AS dish_id, d.name AS dish_name, d.price_fen,
                               d.category, COUNT(oi.id) AS popularity
                        FROM dishes d
                        LEFT JOIN order_items oi
                            ON oi.dish_id = d.id AND oi.tenant_id = d.tenant_id
                        WHERE d.tenant_id = :tenant_id
                          AND d.category = :category
                          AND d.status = 'on_sale'
                          AND d.is_deleted = FALSE
                        GROUP BY d.id, d.name, d.price_fen, d.category
                        ORDER BY popularity DESC
                        LIMIT 5
                    """),
                    {"tenant_id": x_tenant_id, "category": cat},
                )
                for r in explore_result.fetchall():
                    did = str(r.dish_id)
                    if did not in tried_ids and len(recommendations) < limit:
                        recommendations.append({
                            "dish_id": did,
                            "dish_name": r.dish_name,
                            "price_fen": r.price_fen,
                            "category": r.category,
                            "reason": f"您喜欢{cat}类菜品，这道{r.dish_name}很受欢迎，推荐尝试",
                            "reason_type": "explore",
                            "score": 0.75,
                        })

            # 策略2：经典回购菜品（上次点过且复购率高）
            if len(recommendations) < limit:
                repurchase_result = await db.execute(
                    text("""
                        SELECT oi.dish_id, d.name AS dish_name, d.price_fen,
                               d.category, COUNT(*) AS buy_count,
                               MAX(o.created_at) AS last_ordered
                        FROM order_items oi
                        JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
                        JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                        WHERE oi.tenant_id = :tenant_id
                          AND o.customer_id = :customer_id
                          AND o.status = 'paid'
                          AND d.is_deleted = FALSE
                        GROUP BY oi.dish_id, d.name, d.price_fen, d.category
                        HAVING COUNT(*) >= 2
                        ORDER BY buy_count DESC, last_ordered DESC
                        LIMIT 5
                    """),
                    {"tenant_id": x_tenant_id, "customer_id": customer_id},
                )
                for r in repurchase_result.fetchall():
                    did = str(r.dish_id)
                    existing_ids = {rec["dish_id"] for rec in recommendations}
                    if did not in existing_ids and len(recommendations) < limit:
                        recommendations.append({
                            "dish_id": did,
                            "dish_name": r.dish_name,
                            "price_fen": r.price_fen,
                            "category": r.category,
                            "reason": f"您已回购{r.buy_count}次的{r.dish_name}，经典不错过",
                            "reason_type": "repurchase",
                            "score": min(r.buy_count / 5.0, 1.0),
                        })

            # RFM 高价值客户(S1/S2) 推荐更高客单价菜品
            if rfm_level in ("S1", "S2") and len(recommendations) < limit:
                premium_result = await db.execute(
                    text("""
                        SELECT id AS dish_id, name AS dish_name, price_fen, category
                        FROM dishes
                        WHERE tenant_id = :tenant_id
                          AND status = 'on_sale'
                          AND is_deleted = FALSE
                          AND price_fen >= 5000
                        ORDER BY price_fen DESC
                        LIMIT 3
                    """),
                    {"tenant_id": x_tenant_id},
                )
                for r in premium_result.fetchall():
                    did = str(r.dish_id)
                    existing_ids = {rec["dish_id"] for rec in recommendations}
                    if did not in existing_ids and len(recommendations) < limit:
                        recommendations.append({
                            "dish_id": did,
                            "dish_name": r.dish_name,
                            "price_fen": r.price_fen,
                            "category": r.category,
                            "reason": "尊享推荐，为您甄选高品质菜品",
                            "reason_type": "premium",
                            "score": 0.65,
                        })

            # 写推荐日志
            for item in recommendations:
                await db.execute(
                    text("""
                        INSERT INTO recommendation_logs
                            (id, tenant_id, customer_id, store_id, scene,
                             recommended_dish_id, recommended_dish_name,
                             score, reason, reason_type, is_accepted, created_at)
                        VALUES
                            (:id, :tenant_id, :customer_id, NULL, 'return_visit',
                             :dish_id, :dish_name,
                             :score, :reason, :reason_type, FALSE, NOW())
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "tenant_id": x_tenant_id,
                        "customer_id": customer_id,
                        "dish_id": item["dish_id"],
                        "dish_name": item["dish_name"],
                        "score": item["score"],
                        "reason": item["reason"],
                        "reason_type": item["reason_type"],
                    },
                )
            await db.commit()

            logger.info(
                "return_visit_recommend",
                tenant_id=x_tenant_id,
                customer_id=customer_id,
                rfm_level=rfm_level,
                recommend_count=len(recommendations),
            )
            return {
                "ok": True,
                "data": {
                    "customer_id": customer_id,
                    "customer_name": customer_name,
                    "rfm_level": rfm_level,
                    "recommendations": recommendations,
                },
                "error": {},
            }

        except HTTPException:
            raise
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("return_visit_recommend_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="回访推荐失败") from e


@router.get("/metrics")
async def get_recommendation_metrics(
    days: int = Query(default=30, ge=1, le=365),
    scene: Optional[str] = Query(None, description="场景过滤: order_time/upsell/return_visit"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """推荐效果统计：推荐次数/点击率/转化率/篮子提升额"""
    try:
        uuid.UUID(x_tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式错误: {e}") from e

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            scene_filter = ""
            params: dict = {"tenant_id": x_tenant_id, "days": days}
            if scene:
                scene_filter = "AND scene = :scene"
                params["scene"] = scene

            # 总体指标
            overview_result = await db.execute(
                text(f"""
                    SELECT
                        COUNT(*) AS total_recommendations,
                        COUNT(*) FILTER (WHERE is_accepted = TRUE) AS accepted_count,
                        COUNT(DISTINCT customer_id) AS unique_customers,
                        COUNT(DISTINCT DATE(created_at)) AS active_days,
                        ROUND(
                            COUNT(*) FILTER (WHERE is_accepted = TRUE)::NUMERIC
                            / NULLIF(COUNT(*), 0) * 100,
                            2
                        ) AS acceptance_rate_pct
                    FROM recommendation_logs
                    WHERE tenant_id = :tenant_id
                      AND created_at >= NOW() - (:days || ' days')::INTERVAL
                      {scene_filter}
                """),
                params,
            )
            overview = overview_result.fetchone()

            # 按场景分组统计
            by_scene_result = await db.execute(
                text(f"""
                    SELECT
                        scene,
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE is_accepted = TRUE) AS accepted,
                        ROUND(
                            COUNT(*) FILTER (WHERE is_accepted = TRUE)::NUMERIC
                            / NULLIF(COUNT(*), 0) * 100,
                            2
                        ) AS acceptance_rate_pct
                    FROM recommendation_logs
                    WHERE tenant_id = :tenant_id
                      AND created_at >= NOW() - (:days || ' days')::INTERVAL
                      {scene_filter}
                    GROUP BY scene
                    ORDER BY total DESC
                """),
                params,
            )
            by_scene = [
                {
                    "scene": r.scene,
                    "total_recommendations": r.total,
                    "accepted_count": r.accepted,
                    "acceptance_rate_pct": float(r.acceptance_rate_pct) if r.acceptance_rate_pct else 0.0,
                }
                for r in by_scene_result.fetchall()
            ]

            # 按推荐理由类型统计
            by_reason_result = await db.execute(
                text(f"""
                    SELECT
                        reason_type,
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE is_accepted = TRUE) AS accepted,
                        ROUND(AVG(score)::NUMERIC, 3) AS avg_score
                    FROM recommendation_logs
                    WHERE tenant_id = :tenant_id
                      AND created_at >= NOW() - (:days || ' days')::INTERVAL
                      {scene_filter}
                    GROUP BY reason_type
                    ORDER BY accepted DESC
                """),
                params,
            )
            by_reason = [
                {
                    "reason_type": r.reason_type,
                    "total": r.total,
                    "accepted": r.accepted,
                    "avg_score": float(r.avg_score) if r.avg_score else 0.0,
                }
                for r in by_reason_result.fetchall()
            ]

            # 篮子提升额估算（采纳推荐的订单 vs 未采纳的平均客单价差异）
            basket_lift_result = await db.execute(
                text(f"""
                    SELECT
                        COALESCE(AVG(o.total_fen) FILTER (
                            WHERE rl.is_accepted = TRUE
                        ), 0) AS avg_basket_accepted_fen,
                        COALESCE(AVG(o.total_fen) FILTER (
                            WHERE rl.is_accepted = FALSE
                        ), 0) AS avg_basket_rejected_fen
                    FROM recommendation_logs rl
                    JOIN orders o
                        ON o.id = rl.order_id AND o.tenant_id = rl.tenant_id
                    WHERE rl.tenant_id = :tenant_id
                      AND rl.created_at >= NOW() - (:days || ' days')::INTERVAL
                      AND rl.order_id IS NOT NULL
                      {scene_filter}
                """),
                params,
            )
            basket_row = basket_lift_result.fetchone()
            avg_accepted = int(basket_row.avg_basket_accepted_fen) if basket_row else 0
            avg_rejected = int(basket_row.avg_basket_rejected_fen) if basket_row else 0
            basket_lift_fen = avg_accepted - avg_rejected

            return {
                "ok": True,
                "data": {
                    "period_days": days,
                    "overview": {
                        "total_recommendations": overview.total_recommendations if overview else 0,
                        "accepted_count": overview.accepted_count if overview else 0,
                        "unique_customers": overview.unique_customers if overview else 0,
                        "active_days": overview.active_days if overview else 0,
                        "acceptance_rate_pct": float(overview.acceptance_rate_pct) if overview and overview.acceptance_rate_pct else 0.0,
                    },
                    "by_scene": by_scene,
                    "by_reason_type": by_reason,
                    "basket_lift": {
                        "avg_basket_accepted_fen": avg_accepted,
                        "avg_basket_rejected_fen": avg_rejected,
                        "lift_fen": basket_lift_fen,
                        "lift_pct": round(basket_lift_fen / avg_rejected * 100, 2) if avg_rejected > 0 else 0.0,
                    },
                },
                "error": {},
            }

        except SQLAlchemyError as e:
            logger.error("recommendation_metrics_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="推荐效果统计失败") from e
