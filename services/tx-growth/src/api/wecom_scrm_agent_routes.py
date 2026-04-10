"""
企微SCRM私域Agent — 自动化会员触达
P3-05: 生日祝福 / 沉睡唤醒 / 订单后回访
"""
import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date, timedelta
import uuid

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/growth/scrm-agent", tags=["wecom-scrm"])

# ─── Mock 数据 ──────────────────────────────────────────────────────────────

TODAY = date(2026, 4, 6)

MOCK_BIRTHDAY_MEMBERS = [
    {
        "member_id": "mem-b01",
        "name": "陈**",
        "phone_masked": "138****8821",
        "birthday": "2026-04-09",
        "days_until": 3,
        "level": "VIP",
        "last_spend_fen": 88000,
        "total_spend_fen": 528000,
        "recommend_template": "vip",
        "send_status": "pending",
        "wecom_connected": True,
    },
    {
        "member_id": "mem-b02",
        "name": "刘**",
        "phone_masked": "186****3301",
        "birthday": "2026-04-11",
        "days_until": 5,
        "level": "super_vip",
        "last_spend_fen": 256000,
        "total_spend_fen": 3280000,
        "recommend_template": "super_vip",
        "send_status": "pending",
        "wecom_connected": True,
    },
    {
        "member_id": "mem-b03",
        "name": "张**",
        "phone_masked": "135****7762",
        "birthday": "2026-04-13",
        "days_until": 7,
        "level": "regular",
        "last_spend_fen": 12000,
        "total_spend_fen": 68000,
        "recommend_template": "default",
        "send_status": "pending",
        "wecom_connected": True,
    },
    {
        "member_id": "mem-b04",
        "name": "王**",
        "phone_masked": "159****4418",
        "birthday": "2026-04-08",
        "days_until": 2,
        "level": "VIP",
        "last_spend_fen": 45000,
        "total_spend_fen": 312000,
        "recommend_template": "vip",
        "send_status": "pending",
        "wecom_connected": False,
    },
    {
        "member_id": "mem-b05",
        "name": "李**",
        "phone_masked": "177****2290",
        "birthday": "2026-04-07",
        "days_until": 1,
        "level": "VIP",
        "last_spend_fen": 128000,
        "total_spend_fen": 980000,
        "recommend_template": "vip",
        "send_status": "pending",
        "wecom_connected": True,
    },
]

MOCK_DORMANT_MEMBERS = [
    {
        "member_id": "mem-d01",
        "name": "黄**",
        "phone_masked": "138****1189",
        "level": "VIP",
        "last_visit_date": "2026-01-28",
        "dormant_days": 68,
        "total_spend_fen": 486000,
        "avg_spend_per_visit_fen": 24300,
        "visit_count": 20,
        "favorite_dish": "招牌蒸鱼",
        "predicted_response_rate": 0.42,
        "suggest_offer": "专属9折券 + 双倍积分",
        "wecom_connected": True,
        "unsubscribed": False,
    },
    {
        "member_id": "mem-d02",
        "name": "吴**",
        "phone_masked": "150****3847",
        "level": "super_vip",
        "last_visit_date": "2025-12-15",
        "dormant_days": 112,
        "total_spend_fen": 1280000,
        "avg_spend_per_visit_fen": 53300,
        "visit_count": 24,
        "favorite_dish": "佛跳墙",
        "predicted_response_rate": 0.27,
        "suggest_offer": "限定礼品券 ¥200",
        "wecom_connected": True,
        "unsubscribed": False,
    },
    {
        "member_id": "mem-d03",
        "name": "郑**",
        "phone_masked": "181****9934",
        "level": "regular",
        "last_visit_date": "2026-01-10",
        "dormant_days": 86,
        "total_spend_fen": 98000,
        "avg_spend_per_visit_fen": 8167,
        "visit_count": 12,
        "favorite_dish": "白灼虾",
        "predicted_response_rate": 0.35,
        "suggest_offer": "满100减20优惠券",
        "wecom_connected": True,
        "unsubscribed": False,
    },
    {
        "member_id": "mem-d04",
        "name": "孙**",
        "phone_masked": "139****2256",
        "level": "VIP",
        "last_visit_date": "2025-08-20",
        "dormant_days": 229,
        "total_spend_fen": 328000,
        "avg_spend_per_visit_fen": 27300,
        "visit_count": 12,
        "favorite_dish": "清蒸石斑",
        "predicted_response_rate": 0.11,
        "suggest_offer": "建议不主动触达，避免骚扰",
        "wecom_connected": True,
        "unsubscribed": False,
    },
    {
        "member_id": "mem-d05",
        "name": "周**",
        "phone_masked": "158****8802",
        "level": "regular",
        "last_visit_date": "2025-10-01",
        "dormant_days": 187,
        "total_spend_fen": 58000,
        "avg_spend_per_visit_fen": 9667,
        "visit_count": 6,
        "favorite_dish": "煲仔饭（腊肉）",
        "predicted_response_rate": 0.09,
        "suggest_offer": "建议不主动触达，避免骚扰",
        "wecom_connected": False,
        "unsubscribed": True,
    },
    {
        "member_id": "mem-d06",
        "name": "赵**",
        "phone_masked": "186****5521",
        "level": "VIP",
        "last_visit_date": "2026-01-05",
        "dormant_days": 91,
        "total_spend_fen": 628000,
        "avg_spend_per_visit_fen": 34900,
        "visit_count": 18,
        "favorite_dish": "白切鸡",
        "predicted_response_rate": 0.28,
        "suggest_offer": "专属生日月双倍积分",
        "wecom_connected": True,
        "unsubscribed": False,
    },
]

MOCK_POST_ORDER_PENDING = [
    {
        "task_id": f"task-{uuid.uuid4().hex[:8]}",
        "order_id": "ord-20260406-001",
        "member_id": "mem-c01",
        "member_name": "林**",
        "store_name": "徐记海鲜·长沙万达店",
        "order_time": "2026-04-06 12:35:00",
        "spend_fen": 88600,
        "dishes": ["招牌蒸鱼", "白灼虾", "蒜蓉粉丝蒸扇贝"],
        "schedule_time": "2026-04-06 14:35:00",
        "template": "satisfaction",
        "status": "pending",
    },
    {
        "task_id": f"task-{uuid.uuid4().hex[:8]}",
        "order_id": "ord-20260406-002",
        "member_id": "mem-c02",
        "member_name": "钱**",
        "store_name": "徐记海鲜·长沙IFS店",
        "order_time": "2026-04-06 11:20:00",
        "spend_fen": 46800,
        "dishes": ["椰汁芋头糕", "干炒牛河"],
        "schedule_time": "2026-04-06 13:20:00",
        "template": "rebuy",
        "status": "sent",
    },
    {
        "task_id": f"task-{uuid.uuid4().hex[:8]}",
        "order_id": "ord-20260405-088",
        "member_id": "mem-c03",
        "member_name": "曾**",
        "store_name": "徐记海鲜·长沙万达店",
        "order_time": "2026-04-05 18:50:00",
        "spend_fen": 128800,
        "dishes": ["佛跳墙", "烤乳猪（半只）"],
        "schedule_time": "2026-04-05 20:50:00",
        "template": "recommend",
        "status": "replied",
    },
]

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
):
    """获取即将生日的会员列表"""
    logger.info("get_birthday_upcoming", days_ahead=days_ahead, store_id=store_id)

    members = [m for m in MOCK_BIRTHDAY_MEMBERS if m["days_until"] <= days_ahead]
    members_sorted = sorted(members, key=lambda x: x["days_until"])

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
async def send_birthday_messages(body: BirthdaySendRequest):
    """触发生日祝福（模拟发送企微消息）"""
    logger.info("send_birthday_messages", member_count=len(body.member_ids), template=body.message_template)

    if body.message_template not in BIRTHDAY_TEMPLATES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的消息模板: {body.message_template}，可选: default / vip / super_vip",
        )

    results = []
    for mid in body.member_ids:
        member = next((m for m in MOCK_BIRTHDAY_MEMBERS if m["member_id"] == mid), None)
        if not member:
            results.append({"member_id": mid, "status": "failed", "reason": "会员不存在"})
        elif not member["wecom_connected"]:
            results.append({"member_id": mid, "status": "failed", "reason": "未绑定企微"})
        elif member.get("unsubscribed"):
            results.append({"member_id": mid, "status": "skipped", "reason": "已退订营销消息"})
        else:
            results.append({
                "member_id": mid,
                "name": member["name"],
                "status": "success",
                "scheduled_at": str(body.send_time or datetime.now()),
                "template_used": body.message_template,
            })

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
):
    """沉睡会员列表 + 预测响应率"""
    logger.info("get_dormant_list", dormant_days=dormant_days, min_spend=min_historical_spend_fen)

    filtered = [
        m for m in MOCK_DORMANT_MEMBERS
        if m["dormant_days"] >= dormant_days
        and m["total_spend_fen"] >= min_historical_spend_fen
        and not m["unsubscribed"]
    ]

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
async def wake_dormant_members(body: DormantWakeRequest):
    """发送唤醒消息（含专属优惠）"""
    logger.info("wake_dormant_members", member_count=len(body.member_ids), offer_type=body.offer_type)

    if body.offer_type not in ("coupon", "points", "free_dish"):
        raise HTTPException(
            status_code=400,
            detail="offer_type 必须为 coupon / points / free_dish",
        )

    results = []
    for mid in body.member_ids:
        member = next((m for m in MOCK_DORMANT_MEMBERS if m["member_id"] == mid), None)
        if not member:
            results.append({"member_id": mid, "status": "failed", "reason": "会员不存在"})
        elif member["unsubscribed"]:
            results.append({"member_id": mid, "status": "skipped", "reason": "已退订营销消息"})
        elif not member["wecom_connected"]:
            results.append({"member_id": mid, "status": "failed", "reason": "未绑定企微"})
        elif member["dormant_days"] > 180:
            results.append({
                "member_id": mid,
                "name": member["name"],
                "status": "skipped",
                "reason": "沉睡超180天，系统建议不主动触达",
            })
        else:
            offer_desc = {
                "coupon": f"满减券 ¥{body.offer_value_fen // 100}",
                "points": f"赠送积分 {body.offer_value_fen}",
                "free_dish": f"免费菜品券（价值¥{body.offer_value_fen // 100}）",
            }[body.offer_type]
            results.append({
                "member_id": mid,
                "name": member["name"],
                "status": "success",
                "offer_sent": offer_desc,
                "predicted_response_rate": member["predicted_response_rate"],
            })

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
                    m["predicted_response_rate"]
                    for r in results
                    if r["status"] == "success"
                    for m in MOCK_DORMANT_MEMBERS
                    if m["member_id"] == r["member_id"]
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
async def get_post_order_stats():
    """近30天回访任务统计"""
    logger.info("get_post_order_stats")

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
            "pending_today": [t for t in MOCK_POST_ORDER_PENDING if t["status"] == "pending"],
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
                "review_rate": 0.186,       # 评价率18.6%
                "revenue_fen": 1286800,
                "trend": "+5% vs 上月",
            },
            "total_revenue_fen": 2083600,
            "total_cost_fen": 112000,
            "overall_roi": 18.6,
        },
    }
