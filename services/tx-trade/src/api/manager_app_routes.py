import uuid
from datetime import datetime, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/manager", tags=["manager-app"])


# ---------- Mock Data ----------

def _mock_kpi(period: str) -> dict:
    base = {
        "today": {
            "revenue": 2845000,
            "revenue_vs_yesterday": 13.2,
            "order_count": 142,
            "avg_check": 20035,
            "table_turns": 3.2,
            "guest_count": 368,
            "labor_cost_pct": 22.4,
            "on_table_count": 8,
            "free_table_count": 5,
        },
        "week": {
            "revenue": 18920000,
            "revenue_vs_yesterday": 8.7,
            "order_count": 987,
            "avg_check": 19170,
            "table_turns": 2.9,
            "guest_count": 2540,
            "labor_cost_pct": 23.1,
            "on_table_count": 8,
            "free_table_count": 5,
        },
        "month": {
            "revenue": 76480000,
            "revenue_vs_yesterday": 5.3,
            "order_count": 3821,
            "avg_check": 20011,
            "table_turns": 2.8,
            "guest_count": 9880,
            "labor_cost_pct": 22.8,
            "on_table_count": 8,
            "free_table_count": 5,
        },
    }
    return base.get(period, base["today"])


_mock_alerts = [
    {
        "id": "alert-001",
        "type": "overtime_table",
        "severity": "critical",
        "message": "A03桌就餐已71分钟，建议催结账",
        "created_at": (datetime.now() - timedelta(minutes=5)).isoformat(),
        "is_read": False,
    },
    {
        "id": "alert-002",
        "type": "low_margin",
        "severity": "warning",
        "message": "热菜档毛利率跌至43%，低于设定阈值50%",
        "created_at": (datetime.now() - timedelta(minutes=18)).isoformat(),
        "is_read": False,
    },
    {
        "id": "alert-003",
        "type": "low_stock",
        "severity": "warning",
        "message": "剁椒酱库存仅剩2份，预计今晚用完",
        "created_at": (datetime.now() - timedelta(minutes=32)).isoformat(),
        "is_read": False,
    },
    {
        "id": "alert-004",
        "type": "complaint",
        "severity": "critical",
        "message": "B07桌客诉：等待上菜超过40分钟",
        "created_at": (datetime.now() - timedelta(minutes=8)).isoformat(),
        "is_read": False,
    },
    {
        "id": "alert-005",
        "type": "high_discount",
        "severity": "info",
        "message": "今日折扣率4.2%，高于历史均值3.1%",
        "created_at": (datetime.now() - timedelta(minutes=60)).isoformat(),
        "is_read": True,
    },
]

_read_alert_ids: set[str] = set()

_mock_discount_requests = [
    {
        "id": "disc-001",
        "applicant": "李四",
        "applicant_role": "服务员",
        "table": "A03桌",
        "discount_type": "整单9折",
        "discount_amount": 2850,
        "reason": "顾客等待时间较长，超过30分钟",
        "created_at": (datetime.now() - timedelta(minutes=3)).isoformat(),
        "status": "pending",
    },
    {
        "id": "disc-002",
        "applicant": "王五",
        "applicant_role": "服务员",
        "table": "C12桌",
        "discount_type": "赠送甜品",
        "discount_amount": 380,
        "reason": "庆生活动，顾客VIP会员",
        "created_at": (datetime.now() - timedelta(minutes=15)).isoformat(),
        "status": "pending",
    },
]

_mock_staff = [
    {"id": "staff-001", "name": "张三", "role": "服务员", "status": "on_duty", "table_count": 3},
    {"id": "staff-002", "name": "李四", "role": "服务员", "status": "on_duty", "table_count": 4},
    {"id": "staff-003", "name": "王五", "role": "服务员", "status": "on_duty", "table_count": 2},
    {"id": "staff-004", "name": "赵六", "role": "收银员", "status": "on_duty", "table_count": 0},
    {"id": "staff-005", "name": "陈七", "role": "传菜员", "status": "on_duty", "table_count": 0},
]


# ---------- Schemas ----------

class AlertReadRequest(BaseModel):
    pass


class DiscountApproveRequest(BaseModel):
    request_id: str
    approved: bool
    reason: Optional[str] = None


class BroadcastRequest(BaseModel):
    store_id: str
    message: str
    target: str = "all"


# ---------- Routes ----------

@router.get("/realtime-kpi")
async def get_realtime_kpi(
    store_id: Optional[str] = Query(default=None),
    period: str = Query(default="today", pattern="^(today|week|month)$"),
):
    try:
        data = _mock_kpi(period)
        logger.info("manager_kpi_fetched", store_id=store_id, period=period)
        return {"ok": True, "data": data}
    except ValueError as exc:
        logger.error("manager_kpi_invalid_period", period=period, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/alerts")
async def get_alerts(store_id: Optional[str] = Query(default=None)):
    try:
        alerts = []
        for alert in _mock_alerts:
            a = dict(alert)
            if a["id"] in _read_alert_ids:
                a["is_read"] = True
            alerts.append(a)
        unread = [a for a in alerts if not a["is_read"]]
        logger.info("manager_alerts_fetched", store_id=store_id, unread_count=len(unread))
        return {"ok": True, "data": alerts}
    except KeyError as exc:
        logger.error("manager_alerts_key_error", error=str(exc))
        raise HTTPException(status_code=500, detail="内部数据错误") from exc


@router.post("/alerts/{alert_id}/read")
async def mark_alert_read(alert_id: str):
    try:
        _read_alert_ids.add(alert_id)
        logger.info("manager_alert_marked_read", alert_id=alert_id)
        return {"ok": True, "data": {"alert_id": alert_id, "is_read": True}}
    except TypeError as exc:
        logger.error("manager_alert_read_error", alert_id=alert_id, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/discount/approve")
async def approve_discount(body: DiscountApproveRequest):
    try:
        req = next((r for r in _mock_discount_requests if r["id"] == body.request_id), None)
        if req is None:
            raise HTTPException(status_code=404, detail=f"折扣申请 {body.request_id} 不存在")
        req["status"] = "approved" if body.approved else "rejected"
        if body.reason:
            req["manager_reason"] = body.reason
        logger.info(
            "discount_approval_processed",
            request_id=body.request_id,
            approved=body.approved,
            reason=body.reason,
        )
        return {"ok": True, "data": {"request_id": body.request_id, "approved": body.approved}}
    except HTTPException:
        raise
    except ValueError as exc:
        logger.error("discount_approval_error", request_id=body.request_id, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/staff-online")
async def get_staff_online(store_id: Optional[str] = Query(default=None)):
    try:
        logger.info("manager_staff_online_fetched", store_id=store_id)
        return {"ok": True, "data": _mock_staff}
    except KeyError as exc:
        logger.error("manager_staff_key_error", error=str(exc))
        raise HTTPException(status_code=500, detail="内部数据错误") from exc


@router.post("/broadcast-message")
async def broadcast_message(body: BroadcastRequest):
    try:
        if body.target not in ("all", "crew", "kitchen"):
            raise ValueError(f"无效的发送目标: {body.target}")
        msg_id = str(uuid.uuid4())
        logger.info(
            "manager_broadcast_sent",
            store_id=body.store_id,
            target=body.target,
            message_length=len(body.message),
            msg_id=msg_id,
        )
        return {
            "ok": True,
            "data": {
                "msg_id": msg_id,
                "store_id": body.store_id,
                "target": body.target,
                "message": body.message,
                "sent_at": datetime.now().isoformat(),
            },
        }
    except ValueError as exc:
        logger.error("manager_broadcast_invalid", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/discount-requests")
async def get_discount_requests(store_id: Optional[str] = Query(default=None)):
    try:
        pending = [r for r in _mock_discount_requests if r["status"] == "pending"]
        logger.info("manager_discount_requests_fetched", store_id=store_id, pending_count=len(pending))
        return {"ok": True, "data": _mock_discount_requests}
    except KeyError as exc:
        logger.error("manager_discount_requests_error", error=str(exc))
        raise HTTPException(status_code=500, detail="内部数据错误") from exc
