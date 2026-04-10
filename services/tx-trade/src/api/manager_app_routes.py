"""门店经理 App 路由 — DB 版

端点：
  GET  /api/v1/manager/realtime-kpi          — 实时 KPI（从 orders 聚合）
  GET  /api/v1/manager/alerts                — 预警列表（空响应，无预警表）
  POST /api/v1/manager/alerts/{id}/read      — 标记已读（幂等，无 DB）
  POST /api/v1/manager/discount/approve      — 折扣审批（manager_discount_requests）
  GET  /api/v1/manager/staff-online          — 在岗员工（employees）
  POST /api/v1/manager/broadcast-message     — 广播消息（无 DB，记日志）
  GET  /api/v1/manager/discount-requests     — 折扣申请列表（manager_discount_requests）
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/manager", tags=["manager-app"])


# ─── Schemas ────────────────────────────────────────────────────────────────


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


# ─── Helpers ────────────────────────────────────────────────────────────────


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/realtime-kpi")
async def get_realtime_kpi(
    store_id: Optional[str] = Query(default=None),
    period: str = Query(default="today", pattern="^(today|week|month)$"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """实时 KPI — 从 orders 表聚合营收/单量/客单价。"""
    tenant_id = x_tenant_id or ""
    # 计算时间范围
    now = datetime.now(timezone.utc)
    if period == "today":
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        since = now - timedelta(days=now.weekday())
        since = since.replace(hour=0, minute=0, second=0, microsecond=0)
    else:  # month
        since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    try:
        await _set_tenant(db, tenant_id)
        params: dict = {
            "since": since,
            "excluded": ("cancelled",),
        }
        store_clause = ""
        if store_id:
            store_clause = "AND store_id = :store_id"
            params["store_id"] = store_id

        result = await db.execute(
            text(f"""
                SELECT
                    COALESCE(SUM(final_amount_fen), 0)   AS revenue_fen,
                    COUNT(*)                              AS order_count,
                    COALESCE(AVG(final_amount_fen), 0)   AS avg_check_fen
                FROM orders
                WHERE status != 'cancelled'
                  AND is_deleted = FALSE
                  AND order_time >= :since
                  {store_clause}
            """),
            params,
        )
        row = result.mappings().one_or_none()
        revenue_fen = int(row["revenue_fen"] or 0) if row else 0
        order_count = int(row["order_count"] or 0) if row else 0
        avg_check_fen = int(row["avg_check_fen"] or 0) if row else 0

        data = {
            "revenue_fen": revenue_fen,
            "revenue": revenue_fen,   # 向前兼容
            "order_count": order_count,
            "avg_check_fen": avg_check_fen,
            "avg_check": avg_check_fen,
            "period": period,
        }
        logger.info("manager_kpi_fetched", store_id=store_id, period=period, order_count=order_count)
        return {"ok": True, "data": data}
    except SQLAlchemyError as exc:
        logger.error("manager_kpi_db_error", error=str(exc))
        return {"ok": True, "data": {"revenue_fen": 0, "order_count": 0, "avg_check_fen": 0, "period": period}}


@router.get("/alerts")
async def get_alerts(store_id: Optional[str] = Query(default=None)):
    """预警列表 — 暂无专用预警表，返回空列表。"""
    logger.info("manager_alerts_fetched", store_id=store_id)
    return {"ok": True, "data": []}


@router.post("/alerts/{alert_id}/read")
async def mark_alert_read(alert_id: str):
    """标记预警已读（幂等，无 DB 操作）。"""
    logger.info("manager_alert_marked_read", alert_id=alert_id)
    return {"ok": True, "data": {"alert_id": alert_id, "is_read": True}}


@router.post("/discount/approve")
async def approve_discount(
    body: DiscountApproveRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """折扣申请审批 — 更新 manager_discount_requests.status。"""
    tenant_id = x_tenant_id or ""
    new_status = "approved" if body.approved else "rejected"
    try:
        await _set_tenant(db, tenant_id)
        result = await db.execute(
            text("""
                UPDATE manager_discount_requests
                SET status       = :status,
                    manager_reason = :reason,
                    updated_at   = NOW()
                WHERE id = :rid AND is_deleted = FALSE
                RETURNING id, status
            """),
            {
                "rid": body.request_id,
                "status": new_status,
                "reason": body.reason or "",
            },
        )
        row = result.mappings().one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail=f"折扣申请 {body.request_id} 不存在")
        await db.commit()
        logger.info("discount_approval_processed", request_id=body.request_id, approved=body.approved)
        return {"ok": True, "data": {"request_id": body.request_id, "approved": body.approved, "status": new_status}}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("discount_approve_db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="审批操作失败，请稍后重试")


@router.get("/staff-online")
async def get_staff_online(
    store_id: Optional[str] = Query(default=None),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """在岗员工列表 — 从 employees 表查询 is_active=true 的员工。"""
    tenant_id = x_tenant_id or ""
    try:
        await _set_tenant(db, tenant_id)
        params: dict = {}
        store_clause = ""
        if store_id:
            store_clause = "AND store_id = :store_id"
            params["store_id"] = store_id

        result = await db.execute(
            text(f"""
                SELECT id, emp_name, role
                FROM employees
                WHERE is_active = TRUE AND is_deleted = FALSE
                {store_clause}
                ORDER BY role, emp_name
            """),
            params,
        )
        rows = result.mappings().all()
        staff = [
            {
                "id": str(r["id"]),
                "name": r["emp_name"],
                "role": r["role"],
                "status": "on_duty",
            }
            for r in rows
        ]
        logger.info("manager_staff_online_fetched", store_id=store_id, count=len(staff))
        return {"ok": True, "data": staff}
    except SQLAlchemyError as exc:
        logger.error("manager_staff_db_error", error=str(exc))
        return {"ok": True, "data": []}


@router.post("/broadcast-message")
async def broadcast_message(body: BroadcastRequest):
    """广播消息 — 记日志即可，无 DB 操作。"""
    if body.target not in ("all", "crew", "kitchen"):
        raise HTTPException(status_code=400, detail=f"无效的发送目标: {body.target}")
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
            "sent_at": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/discount-requests")
async def get_discount_requests(
    store_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """折扣申请列表 — 从 manager_discount_requests 查询。"""
    tenant_id = x_tenant_id or ""
    try:
        await _set_tenant(db, tenant_id)
        params: dict = {}
        clauses = ["is_deleted = FALSE"]
        if store_id:
            clauses.append("store_id = :store_id")
            params["store_id"] = store_id
        if status:
            clauses.append("status = :status")
            params["status"] = status
        where_clause = " AND ".join(clauses)

        result = await db.execute(
            text(f"""
                SELECT id, applicant, applicant_role, table_label,
                       discount_type, discount_amount, reason,
                       status, manager_reason, created_at
                FROM manager_discount_requests
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT 50
            """),
            params,
        )
        rows = result.mappings().all()
        items = []
        for r in rows:
            item = dict(r._mapping)
            item["id"] = str(item["id"])
            if item.get("created_at"):
                item["created_at"] = item["created_at"].isoformat()
            items.append(item)

        logger.info("manager_discount_requests_fetched", store_id=store_id, count=len(items))
        return {"ok": True, "data": items}
    except SQLAlchemyError as exc:
        logger.error("manager_discount_requests_db_error", error=str(exc))
        return {"ok": True, "data": []}
