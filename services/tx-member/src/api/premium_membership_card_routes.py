"""
付费会员卡产品化路由 — 月卡/季卡/年卡/终身卡的独立产品体系
Y-D7

端点列表：
  GET  /api/v1/member/premium-memberships/products       付费卡产品列表
  POST /api/v1/member/premium-memberships/purchase       购买付费卡
  POST /api/v1/member/premium-memberships/{card_id}/renew    续费
  POST /api/v1/member/premium-memberships/{card_id}/refund   退款（按比例）
  GET  /api/v1/member/premium-memberships/check/{member_id}  检查会员是否持有有效付费卡
  GET  /api/v1/member/premium-memberships                卡档案列表
  GET  /api/v1/member/premium-memberships/stats          统计
  GET  /api/v1/member/premium-memberships/expiring       即将到期（7天内）
"""

from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/member/premium-memberships",
    tags=["premium-memberships"],
)

# ─── 默认产品配置 ────────────────────────────────────────────────────────────

PREMIUM_CARD_PRODUCTS = [
    {
        "card_type": "monthly",
        "name": "月卡",
        "price_fen": 9900,
        "duration_days": 30,
        "benefits": {
            "discount_rate": 0.95,
            "free_parking": False,
        },
        "description": "享受9.5折优惠，有效期30天",
        "highlight": "适合尝鲜用户",
    },
    {
        "card_type": "quarterly",
        "name": "季卡",
        "price_fen": 24900,
        "duration_days": 90,
        "benefits": {
            "discount_rate": 0.92,
            "birthday_bonus": True,
        },
        "description": "享受9.2折优惠 + 生日双倍积分，有效期90天",
        "highlight": "性价比首选",
    },
    {
        "card_type": "annual",
        "name": "年卡",
        "price_fen": 88800,
        "duration_days": 365,
        "benefits": {
            "discount_rate": 0.88,
            "free_dishes": ["招牌汤"],
            "priority_booking": True,
            "birthday_bonus": True,
        },
        "description": "享受8.8折 + 每月赠招牌汤 + 优先订位 + 生日双倍积分，有效期365天",
        "highlight": "忠实会员首选",
    },
    {
        "card_type": "lifetime",
        "name": "终身卡",
        "price_fen": 288800,
        "duration_days": None,
        "benefits": {
            "discount_rate": 0.85,
            "all_benefits": True,
            "free_dishes": ["招牌汤", "招牌蒸鱼（半份）"],
            "priority_booking": True,
            "birthday_bonus": True,
            "vip_lounge": True,
        },
        "description": "享受全部尊享权益，永久有效，一次购买终身使用",
        "highlight": "顶级体验",
        "refundable": False,
    },
]

# 快速查找
_PRODUCTS_BY_TYPE = {p["card_type"]: p for p in PREMIUM_CARD_PRODUCTS}


# ─── 工具函数 ────────────────────────────────────────────────────────────────


def _parse_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    try:
        _uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式错误: {x_tenant_id}") from exc
    return x_tenant_id


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _generate_card_no() -> str:
    """生成卡号：PMC-YYYYMM-XXXX（大写4位随机字母数字）"""
    ym = datetime.now().strftime("%Y%m")
    suffix = _uuid.uuid4().hex[:4].upper()
    return f"PMC-{ym}-{suffix}"


def _calc_end_date(card_type: str, start: date) -> Optional[date]:
    product = _PRODUCTS_BY_TYPE.get(card_type)
    if product is None:
        raise HTTPException(status_code=400, detail=f"不支持的卡类型: {card_type}")
    days = product["duration_days"]
    if days is None:
        return None  # 终身卡
    return start + timedelta(days=days)


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class PurchaseReq(BaseModel):
    member_id: str = Field(..., description="会员ID（UUID）")
    card_type: str = Field(..., description="月卡/季卡/年卡/终身卡: monthly/quarterly/annual/lifetime")
    payment_method: str = Field("wechat_pay", description="支付方式：wechat_pay/alipay/pos_cash/pos_card")
    purchase_channel: Optional[str] = Field("miniapp", description="购买渠道：miniapp/pos/wecom")
    auto_renew: bool = Field(False, description="是否自动续费")
    notes: Optional[str] = None


class RefundReq(BaseModel):
    refund_reason: Optional[str] = Field(None, max_length=200)
    operator_id: Optional[str] = None


# ─── 1. 付费卡产品列表 ────────────────────────────────────────────────────────


@router.get("/products", summary="付费卡产品列表（月卡/季卡/年卡/终身卡）")
async def list_products() -> dict:
    """返回系统默认付费会员卡产品列表，含价格、时长、权益说明。"""
    products = [
        {
            "card_type": p["card_type"],
            "name": p["name"],
            "price_fen": p["price_fen"],
            "price_yuan": p["price_fen"] / 100,
            "duration_days": p["duration_days"],
            "benefits": p["benefits"],
            "description": p["description"],
            "highlight": p["highlight"],
            "refundable": p.get("refundable", True),
        }
        for p in PREMIUM_CARD_PRODUCTS
    ]
    return {"ok": True, "data": {"products": products, "total": len(products)}, "error": None}


# ─── 2. 购买付费卡 ───────────────────────────────────────────────────────────


@router.post("/purchase", summary="购买付费会员卡", status_code=201)
async def purchase_card(
    req: PurchaseReq,
    tenant_id: str = Depends(_parse_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """购买付费会员卡：生成卡号、计算到期日、写入数据库。

    同一会员可持有多张不同类型的卡，但相同类型只保留最新激活状态的一张。
    与储值卡互斥规则：
      - 结算时付费卡折扣优先，储值卡余额作为补充支付
      - 可通过全局配置项调整优先级
    """
    product = _PRODUCTS_BY_TYPE.get(req.card_type)
    if product is None:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的卡类型: {req.card_type}，有效值: {list(_PRODUCTS_BY_TYPE)}",
        )

    try:
        _tid = _uuid.UUID(tenant_id)
        _mid = _uuid.UUID(req.member_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    await _set_rls(db, tenant_id)

    start_date = date.today()
    end_date = _calc_end_date(req.card_type, start_date)
    card_no = _generate_card_no()

    result = await db.execute(
        text("""
            INSERT INTO premium_membership_cards (
                tenant_id, card_no, member_id, card_type, price_fen,
                start_date, end_date, status, benefits,
                purchase_channel, auto_renew, notes
            ) VALUES (
                :tid, :card_no, :mid, :card_type, :price_fen,
                :start_date, :end_date, 'active', :benefits,
                :purchase_channel, :auto_renew, :notes
            )
            RETURNING id, card_no, created_at
        """),
        {
            "tid": _tid,
            "card_no": card_no,
            "mid": _mid,
            "card_type": req.card_type,
            "price_fen": product["price_fen"],
            "start_date": start_date,
            "end_date": end_date,
            "benefits": str(product["benefits"]).replace("'", '"'),  # JSON
            "purchase_channel": req.purchase_channel,
            "auto_renew": req.auto_renew,
            "notes": req.notes,
        },
    )
    row = result.fetchone()
    await db.commit()

    days_remaining: Optional[int] = None
    if end_date:
        days_remaining = (end_date - start_date).days

    log.info(
        "premium_membership_card.purchased",
        card_id=str(row[0]),
        card_no=row[1],
        member_id=req.member_id,
        card_type=req.card_type,
    )
    return {
        "ok": True,
        "data": {
            "id": str(row[0]),
            "card_no": row[1],
            "member_id": req.member_id,
            "card_type": req.card_type,
            "card_name": product["name"],
            "price_fen": product["price_fen"],
            "start_date": str(start_date),
            "end_date": str(end_date) if end_date else None,
            "days_remaining": days_remaining,
            "status": "active",
            "benefits": product["benefits"],
            "purchase_channel": req.purchase_channel,
            "auto_renew": req.auto_renew,
            "created_at": row[2].isoformat() if row[2] else None,
        },
        "error": None,
    }


# ─── 3. 续费 ─────────────────────────────────────────────────────────────────


@router.post("/{card_id}/renew", summary="付费卡续费（从当前end_date延续）")
async def renew_card(
    card_id: str,
    tenant_id: str = Depends(_parse_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """续费付费卡：从当前end_date延续一个周期，终身卡不支持续费。"""
    try:
        _cid = _uuid.UUID(card_id)
        _tid = _uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    await _set_rls(db, tenant_id)

    card_result = await db.execute(
        text("""
            SELECT id, card_type, end_date, status
            FROM premium_membership_cards
            WHERE id = :cid AND tenant_id = :tid
        """),
        {"cid": _cid, "tid": _tid},
    )
    card = card_result.fetchone()
    if not card:
        raise HTTPException(status_code=404, detail=f"付费卡不存在: {card_id}")

    _card_type = card[1]
    _end_date = card[2]
    _status = card[3]

    if _card_type == "lifetime":
        raise HTTPException(status_code=400, detail="终身卡无需续费")
    if _status == "cancelled":
        raise HTTPException(status_code=400, detail="已取消的卡无法续费")

    product = _PRODUCTS_BY_TYPE.get(_card_type)
    if product is None:
        raise HTTPException(status_code=400, detail=f"卡类型配置异常: {_card_type}")

    # 从当前end_date延续（若已过期则从今天开始）
    base_date = _end_date if (_end_date and _end_date >= date.today()) else date.today()
    new_end_date = base_date + timedelta(days=product["duration_days"])

    await db.execute(
        text("""
            UPDATE premium_membership_cards
            SET end_date = :new_end, status = 'active', updated_at = NOW()
            WHERE id = :cid AND tenant_id = :tid
        """),
        {"cid": _cid, "tid": _tid, "new_end": new_end_date},
    )
    await db.commit()

    days_remaining = (new_end_date - date.today()).days
    log.info("premium_membership_card.renewed", card_id=card_id, new_end=str(new_end_date))
    return {
        "ok": True,
        "data": {
            "id": card_id,
            "card_type": _card_type,
            "previous_end_date": str(_end_date) if _end_date else None,
            "new_end_date": str(new_end_date),
            "days_remaining": days_remaining,
            "status": "active",
        },
        "error": None,
    }


# ─── 4. 退款（按剩余天数比例） ───────────────────────────────────────────────


@router.post("/{card_id}/refund", summary="付费卡退款（按剩余天数比例计算）")
async def refund_card(
    card_id: str,
    req: RefundReq,
    tenant_id: str = Depends(_parse_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按剩余天数比例退款：退款金额 = 购买价格 × (剩余天数 / 总天数)。
    终身卡不可退款。已退款/取消的卡不可重复退款。
    """
    try:
        _cid = _uuid.UUID(card_id)
        _tid = _uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    await _set_rls(db, tenant_id)

    card_result = await db.execute(
        text("""
            SELECT id, card_type, price_fen, start_date, end_date, status, refund_amount_fen
            FROM premium_membership_cards
            WHERE id = :cid AND tenant_id = :tid
        """),
        {"cid": _cid, "tid": _tid},
    )
    card = card_result.fetchone()
    if not card:
        raise HTTPException(status_code=404, detail=f"付费卡不存在: {card_id}")

    _card_type = card[1]
    _price_fen = card[2]
    _start_date = card[3]
    _end_date = card[4]
    _status = card[5]
    _already_refunded = card[6]

    if _card_type == "lifetime":
        raise HTTPException(status_code=400, detail="终身卡不支持退款")
    if _status in ("cancelled",):
        raise HTTPException(status_code=400, detail="卡已取消，无法退款")
    if _already_refunded and _already_refunded > 0:
        raise HTTPException(status_code=400, detail="该卡已办理退款，不可重复退款")

    today = date.today()
    if _end_date is None:
        raise HTTPException(status_code=400, detail="该卡无到期日，不可退款")

    # 计算退款金额：按剩余天数比例
    total_days = (_end_date - _start_date).days
    used_days = min((today - _start_date).days, total_days)
    remaining_days = max(total_days - used_days, 0)

    if total_days <= 0:
        raise HTTPException(status_code=400, detail="卡期限计算异常，请联系客服")

    # 退款金额（精确到分）
    refund_fen = int(_price_fen * remaining_days / total_days)

    await db.execute(
        text("""
            UPDATE premium_membership_cards
            SET status = 'cancelled',
                refund_amount_fen = :refund_fen,
                refunded_at = NOW(),
                updated_at = NOW()
            WHERE id = :cid AND tenant_id = :tid
        """),
        {"cid": _cid, "tid": _tid, "refund_fen": refund_fen},
    )
    await db.commit()

    log.info(
        "premium_membership_card.refunded",
        card_id=card_id,
        total_days=total_days,
        used_days=used_days,
        remaining_days=remaining_days,
        refund_fen=refund_fen,
    )
    return {
        "ok": True,
        "data": {
            "id": card_id,
            "card_type": _card_type,
            "original_price_fen": _price_fen,
            "total_days": total_days,
            "used_days": used_days,
            "remaining_days": remaining_days,
            "refund_amount_fen": refund_fen,
            "refund_rate": round(remaining_days / total_days, 4),
            "status": "cancelled",
            "refund_reason": req.refund_reason,
        },
        "error": None,
    }


# ─── 5. 检查会员是否持有有效付费卡 ───────────────────────────────────────────


@router.get("/check/{member_id}", summary="检查会员是否持有有效付费卡")
async def check_premium_member(
    member_id: str,
    tenant_id: str = Depends(_parse_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """检查指定会员是否持有有效的付费会员卡，返回权益信息和剩余天数。
    若持有多张有效卡，返回权益最高的一张（discount_rate最低者）。
    """
    try:
        _mid = _uuid.UUID(member_id)
        _tid = _uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    await _set_rls(db, tenant_id)

    today = date.today()
    result = await db.execute(
        text("""
            SELECT id, card_no, card_type, end_date, status, benefits, start_date
            FROM premium_membership_cards
            WHERE tenant_id = :tid
              AND member_id  = :mid
              AND status     = 'active'
              AND (end_date IS NULL OR end_date >= :today)
            ORDER BY
                CASE card_type
                    WHEN 'lifetime'  THEN 1
                    WHEN 'annual'    THEN 2
                    WHEN 'quarterly' THEN 3
                    WHEN 'monthly'   THEN 4
                    ELSE 5
                END
            LIMIT 1
        """),
        {"tid": _tid, "mid": _mid, "today": today},
    )
    card = result.fetchone()

    if not card:
        return {
            "ok": True,
            "data": {
                "member_id": member_id,
                "has_premium": False,
                "card_type": None,
                "card_name": None,
                "benefits": None,
                "days_remaining": None,
                "expires_at": None,
            },
            "error": None,
        }

    _card_type = card[2]
    _end_date = card[3]
    product = _PRODUCTS_BY_TYPE.get(_card_type, {})

    days_remaining: Optional[int] = None
    if _end_date:
        days_remaining = (_end_date - today).days

    return {
        "ok": True,
        "data": {
            "member_id": member_id,
            "has_premium": True,
            "card_id": str(card[0]),
            "card_no": card[1],
            "card_type": _card_type,
            "card_name": product.get("name", _card_type),
            "benefits": product.get("benefits", {}),
            "days_remaining": days_remaining,
            "expires_at": str(_end_date) if _end_date else None,
            "is_lifetime": _end_date is None,
        },
        "error": None,
    }


# ─── 6. 付费卡列表 ───────────────────────────────────────────────────────────


@router.get("", summary="付费卡档案列表")
async def list_cards(
    status: Optional[str] = Query(None, description="状态过滤：active/expired/cancelled/suspended"),
    card_type: Optional[str] = Query(None, description="类型过滤：monthly/quarterly/annual/lifetime"),
    member_id: Optional[str] = Query(None, description="按会员ID过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(_parse_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """付费卡档案列表，支持状态/类型/会员过滤，分页返回。"""
    await _set_rls(db, tenant_id)

    try:
        _tid = _uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"tenant_id 格式错误: {tenant_id}") from exc

    conditions = ["tenant_id = :tid"]
    params: dict = {"tid": _tid}

    if status:
        conditions.append("status = :status")
        params["status"] = status

    if card_type:
        if card_type not in _PRODUCTS_BY_TYPE:
            raise HTTPException(status_code=400, detail=f"不支持的卡类型: {card_type}")
        conditions.append("card_type = :card_type")
        params["card_type"] = card_type

    if member_id:
        try:
            params["mid"] = _uuid.UUID(member_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"member_id 格式错误: {member_id}") from exc
        conditions.append("member_id = :mid")

    where_clause = " AND ".join(conditions)
    offset = (page - 1) * size

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM premium_membership_cards WHERE {where_clause}"),
        params,
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        text(f"""
            SELECT id, card_no, member_id, card_type, price_fen,
                   start_date, end_date, status, benefits,
                   purchase_channel, auto_renew, created_at
            FROM premium_membership_cards
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :size OFFSET :offset
        """),
        {**params, "size": size, "offset": offset},
    )
    rows = result.fetchall()
    today = date.today()

    items = []
    for r in rows:
        _end = r[6]
        days_remaining = (_end - today).days if _end else None
        product = _PRODUCTS_BY_TYPE.get(r[3], {})
        items.append(
            {
                "id": str(r[0]),
                "card_no": r[1],
                "member_id": str(r[2]),
                "card_type": r[3],
                "card_name": product.get("name", r[3]),
                "price_fen": r[4],
                "start_date": str(r[5]) if r[5] else None,
                "end_date": str(_end) if _end else None,
                "days_remaining": days_remaining,
                "status": r[7],
                "benefits": r[8],
                "purchase_channel": r[9],
                "auto_renew": r[10],
                "is_expiring_soon": 0 <= (days_remaining or 999) <= 7,
                "created_at": r[11].isoformat() if r[11] else None,
            }
        )

    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
        "error": None,
    }


# ─── 7. 统计 ─────────────────────────────────────────────────────────────────


@router.get("/stats", summary="付费卡销售统计")
async def get_stats(
    tenant_id: str = Depends(_parse_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """统计：在售数/本月售出/到期预警数/总收入。"""
    await _set_rls(db, tenant_id)

    try:
        _tid = _uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"tenant_id 格式错误: {tenant_id}") from exc

    today = date.today()
    month_start = today.replace(day=1)
    warn_deadline = today + timedelta(days=7)

    result = await db.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'active')                                 AS active_count,
                COUNT(*) FILTER (
                    WHERE created_at >= :month_start AND status != 'cancelled'
                )                                                                          AS sold_this_month,
                COUNT(*) FILTER (
                    WHERE status = 'active'
                      AND end_date IS NOT NULL
                      AND end_date BETWEEN :today AND :warn_deadline
                )                                                                          AS expiring_soon,
                COALESCE(SUM(price_fen) FILTER (WHERE status != 'cancelled'), 0)          AS total_revenue_fen,
                COUNT(*) FILTER (WHERE card_type = 'monthly'   AND status = 'active')    AS monthly_active,
                COUNT(*) FILTER (WHERE card_type = 'quarterly' AND status = 'active')    AS quarterly_active,
                COUNT(*) FILTER (WHERE card_type = 'annual'    AND status = 'active')    AS annual_active,
                COUNT(*) FILTER (WHERE card_type = 'lifetime'  AND status = 'active')    AS lifetime_active
            FROM premium_membership_cards
            WHERE tenant_id = :tid
        """),
        {"tid": _tid, "today": today, "warn_deadline": warn_deadline, "month_start": month_start},
    )
    r = result.fetchone()

    log.info("premium_membership_stats.fetched", tenant_id=tenant_id)
    return {
        "ok": True,
        "data": {
            "active_count": int(r[0]),
            "sold_this_month": int(r[1]),
            "expiring_soon": int(r[2]),
            "total_revenue_fen": int(r[3]),
            "total_revenue_yuan": round(int(r[3]) / 100, 2),
            "by_type": {
                "monthly": int(r[4]),
                "quarterly": int(r[5]),
                "annual": int(r[6]),
                "lifetime": int(r[7]),
            },
        },
        "error": None,
    }


# ─── 8. 即将到期（7天内） ─────────────────────────────────────────────────────


@router.get("/expiring", summary="即将到期的付费卡（7天内），可触发续费提醒")
async def get_expiring_cards(
    days_ahead: int = Query(7, ge=1, le=30, description="提前几天预警"),
    tenant_id: str = Depends(_parse_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询即将到期的付费卡列表，可用于触发续费提醒推送。"""
    await _set_rls(db, tenant_id)

    try:
        _tid = _uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"tenant_id 格式错误: {tenant_id}") from exc

    today = date.today()
    deadline = today + timedelta(days=days_ahead)

    result = await db.execute(
        text("""
            SELECT id, card_no, member_id, card_type, end_date, status, auto_renew
            FROM premium_membership_cards
            WHERE tenant_id = :tid
              AND status    = 'active'
              AND end_date IS NOT NULL
              AND end_date BETWEEN :today AND :deadline
            ORDER BY end_date ASC
        """),
        {"tid": _tid, "today": today, "deadline": deadline},
    )
    rows = result.fetchall()
    product_map = {p["card_type"]: p["name"] for p in PREMIUM_CARD_PRODUCTS}

    items = [
        {
            "id": str(r[0]),
            "card_no": r[1],
            "member_id": str(r[2]),
            "card_type": r[3],
            "card_name": product_map.get(r[3], r[3]),
            "expires_at": str(r[4]),
            "days_remaining": (r[4] - today).days,
            "auto_renew": r[6],
            "renew_suggestion": "已开启自动续费，将在到期前自动扣款" if r[6] else "建议发送续费提醒",
        }
        for r in rows
    ]

    log.info(
        "premium_membership_expiring.fetched",
        tenant_id=tenant_id,
        days_ahead=days_ahead,
        count=len(items),
    )
    return {
        "ok": True,
        "data": {
            "days_ahead": days_ahead,
            "deadline": str(deadline),
            "expiring_count": len(items),
            "items": items,
        },
        "error": None,
    }
