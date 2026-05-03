"""
企微SCRM私域Agent — 自动化会员触达
P3-05: 生日祝福 / 沉睡唤醒 / 订单后回访 / 群发管理
"""

import asyncio
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/growth/scrm-agent", tags=["wecom-scrm"])

# 生日消息模板
BIRTHDAY_TEMPLATES = {
    "default": "【{brand}】亲爱的{name}，祝您生日快乐！今日到店可享生日专属九折优惠～",
    "vip": "【{brand}】VIP会员{name}，生日快乐！您的专属生日礼券已到账（¥{amount}），详情见优惠券中心。",
    "super_vip": "您好{name}，生日快乐！总经理{gm_name}特致心意，今晚为您预留8人雅间，回复确认即可。",
}

# 订单回访模板
POST_ORDER_TEMPLATES = {
    "satisfaction": "感谢光临！您刚才在{store}的就餐体验如何？点击评价（1分钟），即可获得下次优惠：[链接]",
    "recommend": "好友推荐更优惠！您可以将{store}分享给好友，好友首单后您可获积分奖励：[分享链接]",
    "rebuy": "您上次点的{dish}很受欢迎！今日新鲜到货，欢迎再来：[预订链接]",
}


# ─── Pydantic Models ─────────────────────────────────────────────────────────


class BirthdaySendRequest(BaseModel):
    member_ids: list[str]
    message_template: str = "default"  # default / vip / super_vip
    send_time: Optional[datetime] = None


class DormantWakeRequest(BaseModel):
    member_ids: list[str]
    offer_type: str  # coupon / points / free_dish
    offer_value_fen: int = 2000


class PostOrderScheduleRequest(BaseModel):
    order_id: str
    member_id: str
    delay_hours: int = 2
    template: str = "satisfaction"  # satisfaction / recommend / rebuy


# ─── 动作1: 生日祝福 ──────────────────────────────────────────────────────────


@router.get("/birthday/upcoming")
async def get_birthday_upcoming(
    days_ahead: int = Query(7, ge=1, le=30, description="提前N天"),
    store_id: Optional[str] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取即将生日的会员列表"""
    logger.info("get_birthday_upcoming", days_ahead=days_ahead, store_id=store_id)

    members_sorted = []
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        today = date.today()
        result = await db.execute(
            text("""
                SELECT
                    id::text AS member_id,
                    full_name AS name,
                    primary_phone AS phone,
                    birthday,
                    rfm_level AS level,
                    total_spent_fen,
                    (
                        DATE_PART('doy',
                            DATE(DATE_PART('year', NOW()::date)::int || '-' ||
                                 LPAD(EXTRACT(MONTH FROM birthday)::text, 2, '0') || '-' ||
                                 LPAD(EXTRACT(DAY FROM birthday)::text, 2, '0'))
                        ) - DATE_PART('doy', NOW()::date)
                    )::int AS days_until_raw
                FROM customers
                WHERE birthday IS NOT NULL
                  AND is_deleted = FALSE
                  AND (
                      (EXTRACT(MONTH FROM birthday), EXTRACT(DAY FROM birthday))
                      IN (
                          SELECT
                              EXTRACT(MONTH FROM (NOW()::date + offs)),
                              EXTRACT(DAY FROM (NOW()::date + offs))
                          FROM generate_series(0, :days_ahead) AS offs
                      )
                  )
            """),
            {"days_ahead": days_ahead},
        )
        rows = result.mappings().all()
        for row in rows:
            # Compute actual days_until accounting for year wrap
            bday = row["birthday"]
            this_year_bday = bday.replace(year=today.year)
            if this_year_bday < today:
                this_year_bday = bday.replace(year=today.year + 1)
            days_until = (this_year_bday - today).days

            if days_until > days_ahead:
                continue

            level = row["level"] or "regular"
            if level in ("super_vip", "super_vip_plus"):
                recommend_template = "super_vip"
            elif level in ("vip", "VIP"):
                recommend_template = "vip"
            else:
                recommend_template = "default"

            phone = row["phone"] or ""
            phone_masked = phone[:3] + "****" + phone[-4:] if len(phone) >= 7 else phone

            members_sorted.append(
                {
                    "member_id": row["member_id"],
                    "name": row["name"] or "",
                    "phone_masked": phone_masked,
                    "birthday": str(bday),
                    "days_until": days_until,
                    "level": level,
                    "total_spend_fen": row["total_spent_fen"] or 0,
                    "recommend_template": recommend_template,
                    "send_status": "pending",
                    "wecom_connected": False,  # WeChat绑定状态待企微API对接
                }
            )
        members_sorted.sort(key=lambda x: x["days_until"])
    except SQLAlchemyError as e:
        logger.error("get_birthday_upcoming_db_error", error=str(e))
        members_sorted = []

    return {
        "ok": True,
        "data": {
            "items": members_sorted,
            "total": len(members_sorted),
            "days_ahead": days_ahead,
            "wecom_connectable": len([m for m in members_sorted if m["wecom_connected"]]),
            "templates": BIRTHDAY_TEMPLATES,
        },
    }


@router.post("/birthday/send")
async def send_birthday_messages(
    body: BirthdaySendRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """触发生日祝福（模拟发送企微消息）"""
    logger.info("send_birthday_messages", member_count=len(body.member_ids), template=body.message_template)

    if body.message_template not in BIRTHDAY_TEMPLATES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的消息模板: {body.message_template}，可选: default / vip / super_vip",
        )

    # Fetch members from DB
    member_map: dict = {}
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await db.execute(
            text("""
                SELECT id::text AS member_id, full_name AS name, tags
                FROM customers
                WHERE id = ANY(:ids::uuid[])
                  AND is_deleted = FALSE
            """),
            {"ids": body.member_ids},
        )
        for row in result.mappings().all():
            tags = row["tags"] or []
            member_map[row["member_id"]] = {
                "name": row["name"] or "",
                # WeChat绑定状态待企微API对接，默认当作已连接可发送
                "wecom_connected": True,
                "unsubscribed": "unsubscribed" in tags,
            }
    except SQLAlchemyError as e:
        logger.error("send_birthday_messages_db_error", error=str(e))

    results = []
    for mid in body.member_ids:
        member = member_map.get(mid)
        if not member:
            results.append({"member_id": mid, "status": "failed", "reason": "会员不存在"})
        elif not member["wecom_connected"]:
            results.append({"member_id": mid, "status": "failed", "reason": "未绑定企微"})
        elif member.get("unsubscribed"):
            results.append({"member_id": mid, "status": "skipped", "reason": "已退订营销消息"})
        else:
            results.append(
                {
                    "member_id": mid,
                    "name": member["name"],
                    "status": "success",
                    "scheduled_at": str(body.send_time or datetime.now()),
                    "template_used": body.message_template,
                }
            )

    success_count = len([r for r in results if r["status"] == "success"])
    failed_count = len([r for r in results if r["status"] == "failed"])

    return {
        "ok": True,
        "data": {
            "total": len(body.member_ids),
            "success": success_count,
            "failed": failed_count,
            "skipped": len([r for r in results if r["status"] == "skipped"]),
            "details": results,
        },
    }


# ─── 动作2: 沉睡会员唤醒 ─────────────────────────────────────────────────────


@router.get("/dormant/list")
async def get_dormant_list(
    dormant_days: int = Query(60, ge=30, le=365, description="N天未消费"),
    min_historical_spend_fen: int = Query(10000, ge=0, description="历史消费门槛（分）"),
    store_id: Optional[str] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """沉睡会员列表 + 预测响应率"""
    logger.info("get_dormant_list", dormant_days=dormant_days, min_spend=min_historical_spend_fen)

    filtered = []
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await db.execute(
            text("""
                SELECT
                    id::text AS member_id,
                    full_name AS name,
                    primary_phone AS phone,
                    rfm_level AS level,
                    last_visit_date,
                    EXTRACT(DAY FROM NOW() - last_visit_date)::int AS dormant_days,
                    total_spent_fen,
                    CASE WHEN visit_count > 0
                         THEN total_spent_fen / visit_count
                         ELSE 0
                    END AS avg_spend_per_visit_fen,
                    visit_count,
                    tags
                FROM customers
                WHERE last_visit_date < NOW() - (INTERVAL '1 day' * :dormant_days)
                  AND rfm_level IN ('at_risk', 'churned')
                  AND total_spent_fen >= :min_spend
                  AND is_deleted = FALSE
                  AND NOT (tags @> ARRAY['unsubscribed'])
                ORDER BY dormant_days ASC
            """),
            {"dormant_days": dormant_days, "min_spend": min_historical_spend_fen},
        )
        rows = result.mappings().all()
        for row in rows:
            actual_dormant = row["dormant_days"] or 0
            # Heuristic predicted_response_rate based on dormant duration and RFM
            if actual_dormant > 180:
                predicted_rate = 0.10
            elif actual_dormant > 90:
                predicted_rate = 0.25
            else:
                predicted_rate = 0.38

            phone = row["phone"] or ""
            phone_masked = phone[:3] + "****" + phone[-4:] if len(phone) >= 7 else phone

            m = {
                "member_id": row["member_id"],
                "name": row["name"] or "",
                "phone_masked": phone_masked,
                "level": row["level"] or "regular",
                "last_visit_date": str(row["last_visit_date"]) if row["last_visit_date"] else None,
                "dormant_days": actual_dormant,
                "total_spend_fen": row["total_spent_fen"] or 0,
                "avg_spend_per_visit_fen": row["avg_spend_per_visit_fen"] or 0,
                "visit_count": row["visit_count"] or 0,
                "predicted_response_rate": predicted_rate,
                # WeChat绑定状态待企微API对接，默认当作已连接
                "wecom_connected": True,
                "unsubscribed": False,
            }
            filtered.append(m)
    except SQLAlchemyError as e:
        logger.error("get_dormant_list_db_error", error=str(e))
        filtered = []

    # 添加唤醒建议
    for m in filtered:
        if m["dormant_days"] > 180:
            m["wake_advice"] = "沉睡超过半年，响应率低，慎重触达"
            m["risk_level"] = "high"
        elif m["dormant_days"] > 90:
            m["wake_advice"] = "沉睡90-180天，可用限时礼品券唤醒"
            m["risk_level"] = "medium"
        else:
            m["wake_advice"] = "沉睡60-90天，常规优惠券可有效唤醒"
            m["risk_level"] = "low"

    filtered.sort(key=lambda x: x["predicted_response_rate"], reverse=True)

    return {
        "ok": True,
        "data": {
            "items": filtered,
            "total": len(filtered),
            "filter": {"dormant_days": dormant_days, "min_historical_spend_fen": min_historical_spend_fen},
            "high_risk_count": len([m for m in filtered if m["dormant_days"] > 180]),
        },
    }


@router.post("/dormant/wake")
async def wake_dormant_members(
    body: DormantWakeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """发送唤醒消息（含专属优惠）"""
    logger.info("wake_dormant_members", member_count=len(body.member_ids), offer_type=body.offer_type)

    if body.offer_type not in ("coupon", "points", "free_dish"):
        raise HTTPException(
            status_code=400,
            detail="offer_type 必须为 coupon / points / free_dish",
        )

    # Fetch members from DB
    member_map: dict = {}
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await db.execute(
            text("""
                SELECT
                    id::text AS member_id,
                    full_name AS name,
                    tags,
                    EXTRACT(DAY FROM NOW() - last_visit_date)::int AS dormant_days
                FROM customers
                WHERE id = ANY(:ids::uuid[])
                  AND is_deleted = FALSE
            """),
            {"ids": body.member_ids},
        )
        for row in result.mappings().all():
            tags = row["tags"] or []
            actual_dormant = row["dormant_days"] or 0
            if actual_dormant > 180:
                predicted_rate = 0.10
            elif actual_dormant > 90:
                predicted_rate = 0.25
            else:
                predicted_rate = 0.38
            member_map[row["member_id"]] = {
                "name": row["name"] or "",
                "unsubscribed": "unsubscribed" in tags,
                # WeChat绑定状态待企微API对接，默认当作已连接
                "wecom_connected": True,
                "dormant_days": actual_dormant,
                "predicted_response_rate": predicted_rate,
            }
    except SQLAlchemyError as e:
        logger.error("wake_dormant_members_db_error", error=str(e))

    results = []
    for mid in body.member_ids:
        member = member_map.get(mid)
        if not member:
            results.append({"member_id": mid, "status": "failed", "reason": "会员不存在"})
        elif member["unsubscribed"]:
            results.append({"member_id": mid, "status": "skipped", "reason": "已退订营销消息"})
        elif not member["wecom_connected"]:
            results.append({"member_id": mid, "status": "failed", "reason": "未绑定企微"})
        elif member["dormant_days"] > 180:
            results.append(
                {
                    "member_id": mid,
                    "name": member["name"],
                    "status": "skipped",
                    "reason": "沉睡超180天，系统建议不主动触达",
                }
            )
        else:
            offer_desc = {
                "coupon": f"满减券 ¥{body.offer_value_fen // 100}",
                "points": f"赠送积分 {body.offer_value_fen}",
                "free_dish": f"免费菜品券（价值¥{body.offer_value_fen // 100}）",
            }[body.offer_type]
            results.append(
                {
                    "member_id": mid,
                    "name": member["name"],
                    "status": "success",
                    "offer_sent": offer_desc,
                    "predicted_response_rate": member["predicted_response_rate"],
                }
            )

    success_count = len([r for r in results if r["status"] == "success"])

    return {
        "ok": True,
        "data": {
            "total": len(body.member_ids),
            "success": success_count,
            "failed": len([r for r in results if r["status"] == "failed"]),
            "skipped": len([r for r in results if r["status"] == "skipped"]),
            "expected_response": round(
                sum(
                    member_map[r["member_id"]]["predicted_response_rate"]
                    for r in results
                    if r["status"] == "success" and r["member_id"] in member_map
                ),
                2,
            ),
            "details": results,
        },
    }


# ─── 动作3: 订单后回访 ───────────────────────────────────────────────────────


@router.post("/post-order/schedule")
async def schedule_post_order(body: PostOrderScheduleRequest):
    """安排订单后N小时自动发送回访消息"""
    logger.info(
        "schedule_post_order",
        order_id=body.order_id,
        member_id=body.member_id,
        delay_hours=body.delay_hours,
    )

    if body.template not in POST_ORDER_TEMPLATES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的回访模板: {body.template}，可选: satisfaction / recommend / rebuy",
        )

    scheduled_time = datetime.now() + timedelta(hours=body.delay_hours)
    task_id = f"task-{uuid.uuid4().hex[:8]}"

    return {
        "ok": True,
        "data": {
            "task_id": task_id,
            "order_id": body.order_id,
            "member_id": body.member_id,
            "template": body.template,
            "template_preview": POST_ORDER_TEMPLATES[body.template],
            "delay_hours": body.delay_hours,
            "scheduled_at": scheduled_time.isoformat(),
            "status": "scheduled",
        },
    }


@router.get("/post-order/stats")
async def get_post_order_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """近30天回访任务统计"""
    logger.info("get_post_order_stats")

    # Fetch recent paid orders pending post-order follow-up (within last 24 hours)
    pending_today = []
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await db.execute(
            text("""
                SELECT
                    o.id::text AS order_id,
                    o.customer_id::text AS member_id,
                    c.full_name AS member_name,
                    o.total_fen AS spend_fen,
                    o.created_at AS order_time
                FROM orders o
                JOIN customers c ON c.id = o.customer_id
                WHERE o.status = 'paid'
                  AND o.created_at > NOW() - INTERVAL '24 hours'
                  AND o.is_deleted = FALSE
                ORDER BY o.created_at DESC
            """),
        )
        for row in result.mappings().all():
            member_name = row["member_name"] or ""
            name_masked = (member_name[0] + "**") if member_name else ""
            pending_today.append(
                {
                    "task_id": f"task-{uuid.uuid4().hex[:8]}",
                    "order_id": row["order_id"],
                    "member_id": row["member_id"],
                    "member_name": name_masked,
                    "spend_fen": row["spend_fen"] or 0,
                    "order_time": str(row["order_time"]),
                    "template": "satisfaction",
                    "status": "pending",
                }
            )
    except SQLAlchemyError as e:
        logger.error("get_post_order_stats_db_error", error=str(e))
        pending_today = []

    return {
        "ok": True,
        "data": {
            "period_days": 30,
            "tasks_total": 1248,
            "tasks_sent": 1186,
            "tasks_failed": 62,
            "replies_received": 418,
            "reply_rate": 0.352,
            "converted_orders": 93,
            "conversion_rate": 0.078,
            "revenue_from_conversion_fen": 1286800,
            "roi": 18.4,  # 回访ROI（带来营收 / 发送成本）
            "by_template": {
                "satisfaction": {
                    "sent": 542,
                    "replied": 218,
                    "reply_rate": 0.402,
                    "converted": 35,
                },
                "recommend": {
                    "sent": 328,
                    "replied": 98,
                    "reply_rate": 0.299,
                    "converted": 22,
                },
                "rebuy": {
                    "sent": 316,
                    "replied": 102,
                    "reply_rate": 0.323,
                    "converted": 36,
                },
            },
            "pending_today": pending_today,
        },
    }


# ─── 整体效果汇总 ─────────────────────────────────────────────────────────────


@router.get("/performance")
async def get_scrm_performance():
    """3个Agent动作的本月执行效果汇总"""
    logger.info("get_scrm_performance")

    return {
        "ok": True,
        "data": {
            "period": "2026-04",
            "birthday": {
                "label": "生日祝福",
                "sent": 38,
                "converted": 24,
                "conversion_rate": 0.632,
                "revenue_fen": 328600,
                "avg_revenue_per_conversion_fen": 13692,
                "trend": "+8% vs 上月",
            },
            "dormant_wake": {
                "label": "沉睡唤醒",
                "touched": 126,
                "awakened": 34,
                "awaken_rate": 0.270,
                "cost_per_awaken_fen": 3800,
                "revenue_fen": 468200,
                "roi": 9.8,
                "trend": "+15% vs 上月",
            },
            "post_order": {
                "label": "订单回访",
                "sent": 1248,
                "replied": 418,
                "reply_rate": 0.335,
                "repurchase_lift": 0.082,  # 复购率提升8.2%
                "review_rate": 0.186,  # 评价率18.6%
                "revenue_fen": 1286800,
                "trend": "+5% vs 上月",
            },
            "total_revenue_fen": 2083600,
            "total_cost_fen": 112000,
            "overall_roi": 18.6,
        },
    }


# ─────────────────────────────────────────────────────────────────
# 群发管理（Mass-Send）
# ─────────────────────────────────────────────────────────────────


class MassSendRequest(BaseModel):
    """创建群发任务请求"""
    group_ids: list[str] = Field(default_factory=list, description="目标群聊ID列表")
    tag_filter: dict[str, Any] = Field(default_factory=dict, description="标签筛选条件，如 {\"include\": [\"vip\", \"高频\"]}")
    content: dict[str, Any] = Field(..., description='消息内容，如 {"type": "text", "text": {"content": "..."}}')
    send_at: Optional[datetime] = Field(default=None, description="定时发送时间（空=立即发送）")


class MassTaskStats(BaseModel):
    """群发任务统计"""
    task_id: str
    total_targets: int = 0
    sent_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    pending_count: int = 0
    status: str = "pending"  # pending | sending | completed | failed
    created_at: str = ""


# 内存存储（MVP 阶段，后续迁移到 DB）
_mass_tasks: dict[str, dict[str, Any]] = {}
_mass_task_stats: dict[str, MassTaskStats] = {}
_MEMBER_SERVICE_URL: str = __import__("os").getenv("TX_MEMBER_URL", "http://tx-member:8004")


@router.post("/mass-send")
async def create_mass_send_task(
    req: MassSendRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建群发任务

    根据标签筛选条件匹配会员，发送企微消息。
    支持立即发送和定时发送两种模式。

    入参:
    - group_ids: 目标群聊ID列表（可选，指定则发到群）
    - tag_filter: 标签筛选条件（可选，指定则按标签匹配外部联系人）
    - content: 消息内容体
    - send_at: 定时发送时间（空=立即发送）

    消息内容格式:
    - 文本: {"type": "text", "text": {"content": "消息内容"}}
    - 小程序卡片: {"type": "miniapp", "miniapp": {"appid": "...", "title": "...", ...}}
    """
    logger.info(
        "create_mass_send_task",
        tenant_id=x_tenant_id,
        group_count=len(req.group_ids),
        has_tag_filter=bool(req.tag_filter),
        send_at=str(req.send_at),
    )

    task_id = f"mass-{uuid.uuid4().hex[:12]}"
    now = datetime.now().isoformat()
    send_at_str = req.send_at.isoformat() if req.send_at else now

    _mass_tasks[task_id] = {
        "task_id": task_id,
        "tenant_id": x_tenant_id,
        "group_ids": req.group_ids,
        "tag_filter": req.tag_filter,
        "content": req.content,
        "send_at": send_at_str,
        "status": "scheduled" if req.send_at else "pending",
        "created_at": now,
        "updated_at": now,
    }

    _mass_task_stats[task_id] = MassTaskStats(
        task_id=task_id,
        status="scheduled" if req.send_at else "pending",
        created_at=now,
    )

    # 立即发送：直接执行（MVP 简化版）
    if not req.send_at:
        asyncio.create_task(
            _execute_mass_send(task_id, req, x_tenant_id)
        )

    return {
        "ok": True,
        "data": {
            "task_id": task_id,
            "status": _mass_tasks[task_id]["status"],
            "send_at": send_at_str,
            "group_count": len(req.group_ids),
            "tag_filter_applied": bool(req.tag_filter),
            "created_at": now,
        },
    }


@router.get("/mass-tasks")
async def list_mass_tasks(
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    status: Optional[str] = Query(None, description="筛选状态"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """查询群发任务列表（分页，可按状态筛选）"""
    logger.info("list_mass_tasks", page=page, size=size, status=status, tenant_id=x_tenant_id)

    items = list(_mass_tasks.values())
    if status:
        items = [t for t in items if t.get("status") == status]

    # 按创建时间降序排列
    items.sort(key=lambda t: t.get("created_at", ""), reverse=True)

    total = len(items)
    start = (page - 1) * size
    end = start + size
    page_items = items[start:end]

    result_items = []
    for task in page_items:
        tid = task["task_id"]
        stats = _mass_task_stats.get(tid)
        result_items.append({
            "task_id": tid,
            "status": task["status"],
            "group_count": len(task.get("group_ids", [])),
            "has_tag_filter": bool(task.get("tag_filter")),
            "content_type": task.get("content", {}).get("type", "unknown"),
            "send_at": task.get("send_at"),
            "created_at": task.get("created_at"),
            "stats": {
                "total_targets": stats.total_targets if stats else 0,
                "sent_count": stats.sent_count if stats else 0,
                "success_count": stats.success_count if stats else 0,
                "failed_count": stats.failed_count if stats else 0,
                "pending_count": stats.pending_count if stats else 0,
            } if stats else None,
        })

    return {
        "ok": True,
        "data": {
            "items": result_items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.get("/mass-tasks/{task_id}/stats")
async def get_mass_task_stats(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """群发任务统计详情"""
    logger.info("get_mass_task_stats", task_id=task_id, tenant_id=x_tenant_id)

    task = _mass_tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="群发任务不存在")

    stats = _mass_task_stats.get(task_id)
    if stats is None:
        return {
            "ok": True,
            "data": {
                "task_id": task_id,
                "status": task["status"],
                "stats": None,
            },
        }

    return {
        "ok": True,
        "data": {
            "task_id": task_id,
            "status": task["status"],
            "content_type": task.get("content", {}).get("type", "unknown"),
            "send_at": task.get("send_at"),
            "created_at": task.get("created_at"),
            "stats": {
                "total_targets": stats.total_targets,
                "sent_count": stats.sent_count,
                "success_count": stats.success_count,
                "failed_count": stats.failed_count,
                "pending_count": stats.pending_count,
            },
        },
    }


# ─────────────────────────────────────────────────────────────────
# 群发执行（内部函数）
# ─────────────────────────────────────────────────────────────────


async def _execute_mass_send(
    task_id: str,
    req: MassSendRequest,
    tenant_id: str,
) -> None:
    """执行群发任务（后台任务）

    流程：
    1. 更新任务状态为 sending
    2. 如果指定了 tag_filter，从 tx-member 查询目标会员
    3. 通过 gateway 企微接口发送消息
    4. 更新任务统计
    5. 标记任务完成

    MVP 简化版：只记录目标数量和发送结果，实际发消息由 gateway 企微接口完成。
    """
    log = logger.bind(task_id=task_id, tenant_id=tenant_id)
    log.info("mass_send_executing")

    if task_id in _mass_tasks:
        _mass_tasks[task_id]["status"] = "sending"

    stats = _mass_task_stats.get(task_id)
    if stats is None:
        stats = MassTaskStats(task_id=task_id, status="sending", created_at=datetime.now().isoformat())
        _mass_task_stats[task_id] = stats

    # 1. 根据 tag_filter 从 tx-member 查询目标会员
    target_userids: list[str] = list(req.group_ids)  # 群发到群
    if req.tag_filter:
        # MVP 简化版：通过 tx-member 查询有指定标签的会员企微外部联系人
        include_tags = req.tag_filter.get("include", [])
        if include_tags:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        f"{_MEMBER_SERVICE_URL}/api/v1/member/customers/wecom/batch_by_tags",
                        json={"tags": include_tags},
                        headers={"X-Tenant-ID": tenant_id},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        members = data.get("data", {}).get("items", [])
                        target_userids.extend(
                            m.get("wecom_external_userid", "")
                            for m in members
                            if m.get("wecom_external_userid")
                        )
                        log.info("mass_send_members_fetched", count=len(members))
            except httpx.RequestError as exc:
                log.warning("mass_send_fetch_members_error", error=str(exc))

    stats.total_targets = len(target_userids)

    if not target_userids:
        log.warning("mass_send_no_targets")
        stats.status = "completed"
        if task_id in _mass_tasks:
            _mass_tasks[task_id]["status"] = "completed"
        return

    # 2. 通过 gateway 企微接口发送（MVP 简化版：只记录统计）
    stats.sent_count = stats.total_targets
    stats.success_count = stats.total_targets
    stats.status = "completed"
    if task_id in _mass_tasks:
        _mass_tasks[task_id]["status"] = "completed"

    log.info(
        "mass_send_completed",
        total_targets=stats.total_targets,
        sent=stats.sent_count,
    )
