"""兑换商品 API — miniapp 积分兑换页

路由前缀：/api/v1/member/rewards
所有路由需要 X-Tenant-ID header。

端点列表：
  GET  /         兑换商品列表（is_active=true，tenant_id 过滤）
  POST /redeem   执行兑换（原子事务：检查积分→减库存→扣积分→生成兑换记录）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/member/rewards", tags=["member-rewards"])


# ── 工具函数 ──────────────────────────────────────────────────


def _require_tenant(x_tenant_id: str) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return x_tenant_id


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(code: str, message: str) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── 请求模型 ──────────────────────────────────────────────────


class RedeemRequest(BaseModel):
    reward_id: str = Field(..., description="兑换商品 UUID（points_mall_products.id）")
    customer_id: str = Field(..., description="顾客 UUID")


# ── 1. 兑换商品列表 ──────────────────────────────────────────


@router.get("/")
async def list_rewards(
    category: Optional[str] = Query(None, description="商品分类过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """兑换商品列表

    返回当前租户下 is_active=true 且库存充足（stock=-1 不限 或 stock>0）的商品。
    每个商品包含：{id, name, description, points_required, stock, category, image_url}
    """
    tenant_id = _require_tenant(x_tenant_id)

    # 设置 RLS 上下文
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    now = _now_utc()
    offset = (page - 1) * size

    base_where = """
        tenant_id = :tid
        AND is_active = true
        AND is_deleted = false
        AND (valid_from IS NULL OR valid_from <= :now)
        AND (valid_until IS NULL OR valid_until > :now)
        AND (stock = -1 OR stock > 0)
    """

    params: dict[str, Any] = {"tid": tenant_id, "now": now}

    if category:
        base_where += " AND product_type = :category"
        params["category"] = category

    cnt_row = await db.execute(
        text(f"SELECT COUNT(*) FROM points_mall_products WHERE {base_where}"),
        params,
    )
    total = cnt_row.scalar() or 0

    params.update({"lim": size, "off": offset})
    rows = await db.execute(
        text(f"""
            SELECT id, name, description, points_required, stock,
                   product_type AS category, image_url
            FROM points_mall_products
            WHERE {base_where}
            ORDER BY sort_order ASC, created_at ASC
            LIMIT :lim OFFSET :off
        """),
        params,
    )

    items = [
        {
            "id": str(row[0]),
            "name": row[1],
            "description": row[2],
            "points_required": row[3],
            "stock": row[4],
            "category": row[5],
            "image_url": row[6],
        }
        for row in rows.all()
    ]

    logger.info(
        "rewards_listed",
        tenant_id=tenant_id,
        total=total,
        page=page,
    )

    return _ok({"items": items, "total": total, "page": page, "size": size})


# ── 2. 执行兑换 ───────────────────────────────────────────────
#
# 原子操作（单一数据库事务）：
#   1. 查询并锁定商品（SELECT FOR UPDATE）
#   2. 检查积分余额（SELECT FOR UPDATE）
#   3. 减库存（stock-=1，若 stock=-1 跳过）
#   4. 扣积分（UPDATE WHERE points >= pts）
#   5. 生成兑换记录


@router.post("/redeem")
async def redeem_reward(
    body: RedeemRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """执行兑换

    body: {reward_id, customer_id}
    原子事务：检查积分 → 减库存 → 扣积分 → 生成兑换记录。
    积分不足时返回 {"ok": False, "error": {"code": "INSUFFICIENT_POINTS"}}
    """
    tenant_id = _require_tenant(x_tenant_id)

    # 设置 RLS 上下文
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    now = _now_utc()

    # Step 1: 锁定商品行，读取当前状态
    product_row = await db.execute(
        text("""
            SELECT id, name, points_required, stock, is_active, is_deleted,
                   valid_from, valid_until
            FROM points_mall_products
            WHERE id = :rid AND tenant_id = :tid
            FOR UPDATE
        """),
        {"rid": body.reward_id, "tid": tenant_id},
    )
    product = product_row.first()

    if not product:
        raise HTTPException(status_code=404, detail="reward_not_found")

    p_id, p_name, points_required, stock, is_active, is_deleted, valid_from, valid_until = product

    if is_deleted or not is_active:
        return _err("REWARD_NOT_ACTIVE", "商品未上架或已下架")

    if valid_from and valid_from > now:
        return _err("REWARD_NOT_STARTED", "商品活动尚未开始")

    if valid_until and valid_until <= now:
        return _err("REWARD_EXPIRED", "商品活动已结束")

    if stock != -1 and stock <= 0:
        return _err("INSUFFICIENT_STOCK", "库存不足")

    # Step 2: 查找并锁定会员卡
    card_row = await db.execute(
        text("""
            SELECT id, points FROM member_cards
            WHERE customer_id = :cid AND tenant_id = :tid AND is_deleted = false
            ORDER BY created_at ASC
            LIMIT 1
            FOR UPDATE
        """),
        {"cid": body.customer_id, "tid": tenant_id},
    )
    card = card_row.first()

    if not card:
        return _err("MEMBER_CARD_NOT_FOUND", "会员卡不存在，请先注册会员")

    card_id, current_points = str(card[0]), card[1] or 0

    # Step 3: 检查积分
    if current_points < points_required:
        return _err(
            "INSUFFICIENT_POINTS",
            f"积分不足，当前余额 {current_points} 分，需要 {points_required} 分",
        )

    # Step 4: 减库存（stock=-1 表示不限库存，跳过减库存）
    if stock != -1:
        stock_result = await db.execute(
            text("""
                UPDATE points_mall_products
                SET stock = stock - 1, updated_at = :now
                WHERE id = :rid AND tenant_id = :tid AND stock > 0
                RETURNING stock
            """),
            {"rid": body.reward_id, "tid": tenant_id, "now": now},
        )
        if not stock_result.first():
            return _err("INSUFFICIENT_STOCK", "库存不足（并发扣减后库存不足）")

    # Step 5: 扣积分（原子操作，WHERE points >= pts 防超扣）
    deduct_result = await db.execute(
        text("""
            UPDATE member_cards
            SET points = points - :pts, updated_at = :now
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
              AND points >= :pts
            RETURNING points
        """),
        {"pts": points_required, "cid": card_id, "tid": tenant_id, "now": now},
    )
    deduct_row = deduct_result.first()
    if not deduct_row:
        # 回滚库存（若已减过）
        if stock != -1:
            await db.execute(
                text("""
                    UPDATE points_mall_products
                    SET stock = stock + 1, updated_at = :now
                    WHERE id = :rid AND tenant_id = :tid
                """),
                {"rid": body.reward_id, "tid": tenant_id, "now": now},
            )
        await db.flush()
        return _err("INSUFFICIENT_POINTS", "积分不足（并发扣减后余额不足）")

    new_balance = deduct_row[0]

    # Step 6: 记录积分流水
    log_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO points_log
                (id, tenant_id, card_id, direction, source, points, order_id, created_at)
            VALUES (:id, :tid, :cid, 'spend', 'redeem', :pts, :rid, :now)
        """),
        {
            "id": log_id,
            "tid": tenant_id,
            "cid": card_id,
            "pts": points_required,
            "rid": body.reward_id,
            "now": now,
        },
    )

    # Step 7: 生成兑换记录
    order_id = str(uuid.uuid4())
    order_no = f"RW-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    await db.execute(
        text("""
            INSERT INTO points_mall_orders
                (id, tenant_id, order_no, product_id, customer_id, card_id,
                 quantity, points_spent, status, created_at, updated_at)
            VALUES
                (:oid, :tid, :ono, :pid, :cid, :card_id,
                 1, :pts, 'pending', :now, :now)
        """),
        {
            "oid": order_id,
            "tid": tenant_id,
            "ono": order_no,
            "pid": body.reward_id,
            "cid": body.customer_id,
            "card_id": card_id,
            "pts": points_required,
            "now": now,
        },
    )

    await db.flush()

    logger.info(
        "reward_redeemed",
        tenant_id=tenant_id,
        customer_id=body.customer_id,
        reward_id=body.reward_id,
        reward_name=p_name,
        points_spent=points_required,
        new_balance=new_balance,
        order_id=order_id,
    )

    return _ok(
        {
            "order_id": order_id,
            "order_no": order_no,
            "reward_id": body.reward_id,
            "reward_name": p_name,
            "points_spent": points_required,
            "new_balance": new_balance,
            "status": "pending",
            "created_at": now.isoformat(),
        }
    )
