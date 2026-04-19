"""审批中心 API — 统一审批入口（汇聚折扣/采购/排班/薪资/加盟等审批）
真实DB + RLS。

表：approval_instances / approval_templates / approval_step_records (v121)

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/approval-center", tags=["approval-center"])


# ─── 辅助函数 ───


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _serialize_row(row_mapping: dict) -> dict:
    """序列化 UUID/datetime 字段"""
    result = {}
    for key, val in row_mapping.items():
        if val is None:
            result[key] = None
        elif hasattr(val, "isoformat"):
            result[key] = val.isoformat()
        elif hasattr(val, "hex"):
            result[key] = str(val)
        else:
            result[key] = val
    return result


# ─── 请求模型 ───


class ApprovalAction(BaseModel):
    action: str  # approve/reject
    comment: Optional[str] = None
    approver_id: str = "current_user"
    approver_name: str = "当前用户"


# ─── 端点 ───


@router.get("/pending")
async def list_pending(
    type_filter: Optional[str] = Query(None, description="业务类型过滤"),
    urgency: Optional[str] = Query(None, description="紧急程度过滤（high/normal/low）"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """待我审批列表 — 从 approval_instances 表查询 status=pending 的记录"""
    await _set_rls(db, x_tenant_id)

    where_clauses = [
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid",
        "status = 'pending'",
        "is_deleted = false",
    ]
    params: dict = {"limit": size, "offset": (page - 1) * size}

    if type_filter:
        where_clauses.append("business_type = :type_filter")
        params["type_filter"] = type_filter

    where_sql = " AND ".join(where_clauses)

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM approval_instances WHERE {where_sql}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar() or 0

        rows_result = await db.execute(
            text(
                f"""
                SELECT id, business_type, business_id, title, description,
                       amount_fen, initiator_id, initiator_name,
                       current_step, total_steps, status,
                       deadline_at, created_at, updated_at
                FROM approval_instances
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [_serialize_row(dict(row._mapping)) for row in rows_result]

        # 统计高紧急数量（deadline_at 在24小时内或amount_fen > 500000）
        high_urgency_result = await db.execute(
            text(
                """
                SELECT COUNT(*) FROM approval_instances
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND status = 'pending'
                  AND is_deleted = false
                  AND (
                    (deadline_at IS NOT NULL AND deadline_at <= NOW() + INTERVAL '24 hours')
                    OR (amount_fen IS NOT NULL AND amount_fen > 500000)
                  )
                """
            )
        )
        high_count = high_urgency_result.scalar() or 0

        return {
            "ok": True,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "size": size,
                "high_urgency_count": high_count,
            },
        }

    except SQLAlchemyError as exc:
        log.error("approval_pending_db_error", exc_info=True, error=str(exc), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size, "high_urgency_count": 0}}


@router.get("/history")
async def list_history(
    status: Optional[str] = Query(None, description="状态过滤: approved/rejected/cancelled"),
    type_filter: Optional[str] = Query(None, description="业务类型过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """已审批历史 — 查询非 pending 状态的记录"""
    await _set_rls(db, x_tenant_id)

    where_clauses = [
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid",
        "status != 'pending'",
        "is_deleted = false",
    ]
    params: dict = {"limit": size, "offset": (page - 1) * size}

    if status:
        where_clauses.append("status = :status")
        params["status"] = status
    if type_filter:
        where_clauses.append("business_type = :type_filter")
        params["type_filter"] = type_filter

    where_sql = " AND ".join(where_clauses)

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM approval_instances WHERE {where_sql}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar() or 0

        rows_result = await db.execute(
            text(
                f"""
                SELECT ai.id, ai.business_type, ai.business_id, ai.title,
                       ai.amount_fen, ai.initiator_id, ai.initiator_name,
                       ai.status, ai.updated_at AS action_at, ai.created_at,
                       (
                         SELECT asr.comment
                         FROM approval_step_records asr
                         WHERE asr.instance_id = ai.id
                         ORDER BY asr.acted_at DESC LIMIT 1
                       ) AS action_comment,
                       (
                         SELECT asr.approver_name
                         FROM approval_step_records asr
                         WHERE asr.instance_id = ai.id
                         ORDER BY asr.acted_at DESC LIMIT 1
                       ) AS approved_by
                FROM approval_instances ai
                WHERE {where_sql}
                ORDER BY ai.updated_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [_serialize_row(dict(row._mapping)) for row in rows_result]

        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}

    except SQLAlchemyError as exc:
        log.error("approval_history_db_error", exc_info=True, error=str(exc), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size}}


@router.post("/pending/{approval_id}/action")
async def take_action(
    approval_id: str,
    body: ApprovalAction,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """审批操作（同意/拒绝）"""
    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action 必须是 approve 或 reject")

    await _set_rls(db, x_tenant_id)

    try:
        # 检查实例存在且 pending
        check_result = await db.execute(
            text(
                """
                SELECT id, status, current_step, total_steps, business_type, title
                FROM approval_instances
                WHERE id = :id
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND is_deleted = false
                LIMIT 1
                """
            ),
            {"id": approval_id},
        )
        instance = check_result.fetchone()
        if not instance:
            raise HTTPException(status_code=404, detail="审批实例不存在")
        if instance.status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"当前状态 {instance.status!r} 不允许操作，仅 pending 可审批",
            )

        now = datetime.now(timezone.utc)
        new_status = "approved" if body.action == "approve" else "rejected"

        # 更新实例状态
        await db.execute(
            text(
                """
                UPDATE approval_instances
                SET status = :status, updated_at = :now
                WHERE id = :id
                """
            ),
            {"status": new_status, "now": now, "id": approval_id},
        )

        # 写入步骤记录
        await db.execute(
            text(
                """
                INSERT INTO approval_step_records
                  (tenant_id, instance_id, step_no, approver_id, approver_name,
                   approver_role, action, comment, acted_at)
                VALUES
                  (NULLIF(current_setting('app.tenant_id', true), '')::uuid,
                   :instance_id, :step_no, :approver_id, :approver_name,
                   'manager', :action, :comment, :acted_at)
                """
            ),
            {
                "instance_id": approval_id,
                "step_no": instance.current_step,
                "approver_id": body.approver_id,
                "approver_name": body.approver_name,
                "action": body.action,
                "comment": body.comment or "",
                "acted_at": now,
            },
        )

        log.info(
            "approval_action_taken",
            id=approval_id,
            action=body.action,
            approver_id=body.approver_id,
            tenant_id=x_tenant_id,
        )

        return {
            "ok": True,
            "data": {
                "id": approval_id,
                "status": new_status,
                "action": body.action,
                "comment": body.comment,
                "action_at": now.isoformat(),
            },
        }

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("approval_action_db_error", exc_info=True, error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="审批操作失败") from exc


@router.post("/pending/batch-action")
async def batch_action(
    body: dict,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """批量审批操作"""
    ids = body.get("ids", [])
    action = body.get("action", "approve")
    comment = body.get("comment", "")

    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action 必须是 approve 或 reject")
    if not ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    await _set_rls(db, x_tenant_id)

    new_status = "approved" if action == "approve" else "rejected"
    now = datetime.now(timezone.utc)
    results = []

    try:
        for aid in ids:
            check_result = await db.execute(
                text(
                    """
                    SELECT id, status, current_step FROM approval_instances
                    WHERE id = :id
                      AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND status = 'pending'
                      AND is_deleted = false
                    LIMIT 1
                    """
                ),
                {"id": aid},
            )
            instance = check_result.fetchone()
            if not instance:
                continue

            await db.execute(
                text("UPDATE approval_instances SET status = :status, updated_at = :now WHERE id = :id"),
                {"status": new_status, "now": now, "id": aid},
            )
            await db.execute(
                text(
                    """
                    INSERT INTO approval_step_records
                      (tenant_id, instance_id, step_no, approver_id, approver_name,
                       approver_role, action, comment, acted_at)
                    VALUES
                      (NULLIF(current_setting('app.tenant_id', true), '')::uuid,
                       :instance_id, :step_no, 'current_user', '当前用户',
                       'manager', :action, :comment, :acted_at)
                    """
                ),
                {
                    "instance_id": aid,
                    "step_no": instance.current_step,
                    "action": action,
                    "comment": comment,
                    "acted_at": now,
                },
            )
            results.append({"id": aid, "status": new_status})

        log.info("approval_batch_action", count=len(results), action=action, tenant_id=x_tenant_id)
        return {"ok": True, "data": {"results": results, "processed": len(results)}}

    except SQLAlchemyError as exc:
        log.error("approval_batch_action_db_error", exc_info=True, error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="批量审批操作失败") from exc


@router.get("/stats")
async def approval_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """审批统计（当前状态分布）"""
    await _set_rls(db, x_tenant_id)

    try:
        # 各状态计数
        stats_result = await db.execute(
            text(
                """
                SELECT
                  COUNT(*) FILTER (WHERE status = 'pending' AND is_deleted = false) AS pending_count,
                  COUNT(*) FILTER (WHERE status = 'pending' AND is_deleted = false
                                   AND (
                                     (deadline_at IS NOT NULL AND deadline_at <= NOW() + INTERVAL '24 hours')
                                     OR (amount_fen IS NOT NULL AND amount_fen > 500000)
                                   )) AS high_urgency_count,
                  COUNT(*) FILTER (WHERE status = 'approved'
                                   AND updated_at >= NOW() - INTERVAL '1 day') AS today_approved,
                  COUNT(*) FILTER (WHERE status = 'rejected'
                                   AND updated_at >= NOW() - INTERVAL '1 day') AS today_rejected
                FROM approval_instances
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                """
            )
        )
        stats = stats_result.fetchone()

        # 按业务类型分布
        type_result = await db.execute(
            text(
                """
                SELECT business_type, COUNT(*) AS cnt
                FROM approval_instances
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND status = 'pending'
                  AND is_deleted = false
                GROUP BY business_type
                """
            )
        )
        type_breakdown = {row.business_type: row.cnt for row in type_result}

        return {
            "ok": True,
            "data": {
                "pending_count": stats.pending_count if stats else 0,
                "high_urgency_count": stats.high_urgency_count if stats else 0,
                "today_approved": stats.today_approved if stats else 0,
                "today_rejected": stats.today_rejected if stats else 0,
                "avg_response_minutes": None,  # 需要 step_records 聚合计算，暂不实现
                "type_breakdown": type_breakdown,
            },
        }

    except SQLAlchemyError as exc:
        log.error("approval_stats_db_error", exc_info=True, error=str(exc), tenant_id=x_tenant_id)
        return {
            "ok": True,
            "data": {
                "pending_count": 0,
                "high_urgency_count": 0,
                "today_approved": 0,
                "today_rejected": 0,
                "avg_response_minutes": None,
                "type_breakdown": {},
            },
        }
