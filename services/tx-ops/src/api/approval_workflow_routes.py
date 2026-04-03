"""审批流 API 路由

端点 (prefix /api/v1/ops/approvals)：
  GET  /templates                          — 查询审批模板列表
  POST /templates                          — 创建/更新模板

  POST /instances                          — 发起审批
  GET  /instances/pending-mine             — 待我审批列表 (?approver_id=)
  GET  /instances/my-initiated             — 我发起的审批 (?initiator_id=&status=)
  GET  /instances/{id}                     — 审批实例详情（含步骤记录）
  POST /instances/{id}/act                 — 执行审批动作 (approve/reject)
  DELETE /instances/{id}                   — 撤回（仅 pending + current_step=1）

  GET  /notifications                      — 我的通知 (?recipient_id=&is_read=)
  POST /notifications/{id}/read            — 标记已读

统一响应格式：{"ok": bool, "data": {}}
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/ops/approvals", tags=["ops-approvals"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DB 依赖注入占位（生产替换为 Depends(get_db)）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from fastapi import Depends


async def get_db():  # noqa: ANN201
    """生产环境替换为真实 asyncpg / SQLAlchemy async session。"""
    raise NotImplementedError("请在 main.py 中覆盖 get_db 依赖")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TemplateStepModel(BaseModel):
    step_no: int = Field(..., ge=1, description="步骤序号，从 1 开始")
    role: str = Field(..., max_length=50, description="审批角色名")
    approver_type: str = Field(
        "role",
        pattern="^(role|specific_user)$",
        description="role=按角色，specific_user=指定人",
    )
    min_amount_fen: Optional[int] = Field(None, ge=0, description="触发此步骤的最小金额（分）")
    max_amount_fen: Optional[int] = Field(None, ge=0, description="触发此步骤的最大金额（分）")


class CreateTemplateRequest(BaseModel):
    template_name: str = Field(..., max_length=100)
    business_type: str = Field(
        ...,
        pattern="^(discount|refund|void_order|large_purchase|staff_leave|payroll)$",
    )
    steps: List[TemplateStepModel] = Field(..., min_length=1)
    is_active: bool = Field(True)


class CreateInstanceRequest(BaseModel):
    business_type: str = Field(
        ...,
        pattern="^(discount|refund|void_order|large_purchase|staff_leave|payroll)$",
    )
    business_id: str = Field(..., max_length=100, description="关联业务单号")
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(None)
    amount_fen: Optional[int] = Field(None, ge=0, description="涉及金额（分），可空")
    initiator_id: str = Field(..., max_length=100)
    initiator_name: str = Field(..., max_length=100)
    deadline_hours: Optional[int] = Field(
        None, ge=1, le=720,
        description="超时自动关闭小时数（1-720），不填则无 deadline",
    )


class ActRequest(BaseModel):
    approver_id: str = Field(..., max_length=100)
    approver_name: str = Field(..., max_length=100)
    action: str = Field(..., pattern="^(approve|reject)$")
    comment: str = Field("", max_length=500)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  模板端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/templates")
async def list_templates(
    business_type: Optional[str] = Query(None, description="按业务类型过滤"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: Any = Depends(get_db),
) -> Dict[str, Any]:
    """查询审批模板列表（仅返回未删除的）。"""
    if business_type is not None:
        rows = await db.fetch_all(
            text("""
                SELECT id, tenant_id, template_name, business_type,
                       steps, is_active, created_at, updated_at
                FROM approval_templates
                WHERE tenant_id = :tenant_id
                  AND business_type = :business_type
                  AND is_deleted = false
                ORDER BY created_at DESC
            """),
            {"tenant_id": x_tenant_id, "business_type": business_type},
        )
    else:
        rows = await db.fetch_all(
            text("""
                SELECT id, tenant_id, template_name, business_type,
                       steps, is_active, created_at, updated_at
                FROM approval_templates
                WHERE tenant_id = :tenant_id
                  AND is_deleted = false
                ORDER BY created_at DESC
            """),
            {"tenant_id": x_tenant_id},
        )
    return {"ok": True, "data": {"items": [dict(r) for r in rows], "total": len(rows)}}


@router.post("/templates")
async def upsert_template(
    body: CreateTemplateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: Any = Depends(get_db),
) -> Dict[str, Any]:
    """
    创建或更新审批模板。
    若同一 tenant + business_type 已有同名模板则覆盖 steps；否则新建。
    """
    now = datetime.now(tz=timezone.utc)
    steps_json = [s.model_dump() for s in body.steps]

    # 尝试查找同名同 business_type 模板
    existing = await db.fetch_one(
        text("""
            SELECT id FROM approval_templates
            WHERE tenant_id = :tenant_id
              AND business_type = :business_type
              AND template_name = :template_name
              AND is_deleted = false
            LIMIT 1
        """),
        {
            "tenant_id": x_tenant_id,
            "business_type": body.business_type,
            "template_name": body.template_name,
        },
    )

    if existing:
        template_id = str(existing["id"])
        await db.execute(
            text("""
                UPDATE approval_templates
                SET steps = :steps, is_active = :is_active, updated_at = :now
                WHERE id = :id
            """),
            {
                "id": template_id,
                "steps": steps_json,
                "is_active": body.is_active,
                "now": now,
            },
        )
        log.info("approval_template_updated", template_id=template_id, tenant_id=x_tenant_id)
    else:
        template_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO approval_templates
                    (id, tenant_id, template_name, business_type, steps, is_active,
                     created_at, updated_at)
                VALUES
                    (:id, :tenant_id, :template_name, :business_type, :steps, :is_active,
                     :now, :now)
            """),
            {
                "id": template_id,
                "tenant_id": x_tenant_id,
                "template_name": body.template_name,
                "business_type": body.business_type,
                "steps": steps_json,
                "is_active": body.is_active,
                "now": now,
            },
        )
        log.info("approval_template_created", template_id=template_id, tenant_id=x_tenant_id)

    return {"ok": True, "data": {"id": template_id, "template_name": body.template_name}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  实例端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/instances")
async def create_instance(
    body: CreateInstanceRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: Any = Depends(get_db),
) -> Dict[str, Any]:
    """发起审批实例。"""
    from ..services.approval_engine import approval_engine

    try:
        instance = await approval_engine.create_instance(
            db=db,
            tenant_id=x_tenant_id,
            business_type=body.business_type,
            business_id=body.business_id,
            title=body.title,
            description=body.description,
            initiator_id=body.initiator_id,
            initiator_name=body.initiator_name,
            amount_fen=body.amount_fen,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # 若指定了 deadline_hours，补充写入 deadline_at
    if body.deadline_hours is not None:
        from datetime import timedelta
        deadline = datetime.now(tz=timezone.utc) + timedelta(hours=body.deadline_hours)
        await db.execute(
            text("UPDATE approval_instances SET deadline_at = :dl WHERE id = :id"),
            {"dl": deadline, "id": instance["id"]},
        )
        instance["deadline_at"] = deadline.isoformat()

    return {"ok": True, "data": instance}


@router.get("/instances/pending-mine")
async def pending_mine(
    approver_id: str = Query(..., description="审批人ID（或角色名）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: Any = Depends(get_db),
) -> Dict[str, Any]:
    """查询待我审批的实例列表。"""
    from ..services.approval_engine import approval_engine

    items = await approval_engine.get_pending_for_approver(
        db=db, tenant_id=x_tenant_id, approver_id=approver_id
    )
    return {"ok": True, "data": {"items": items, "total": len(items)}}


@router.get("/instances/my-initiated")
async def my_initiated(
    initiator_id: str = Query(..., description="发起人ID"),
    status: Optional[str] = Query(
        None,
        description="过滤状态: pending/approved/rejected/cancelled/expired",
    ),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: Any = Depends(get_db),
) -> Dict[str, Any]:
    """查询我发起的审批列表，可按 status 过滤。"""
    from ..services.approval_engine import approval_engine

    items = await approval_engine.get_my_initiated(
        db=db, tenant_id=x_tenant_id, initiator_id=initiator_id, status=status
    )
    return {"ok": True, "data": {"items": items, "total": len(items)}}


@router.get("/instances/{instance_id}")
async def get_instance_detail(
    instance_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: Any = Depends(get_db),
) -> Dict[str, Any]:
    """查询审批实例详情，包含所有步骤操作记录。"""
    inst = await db.fetch_one(
        text("""
            SELECT id, tenant_id, template_id, business_type, business_id,
                   title, description, amount_fen,
                   initiator_id, initiator_name,
                   current_step, total_steps, status,
                   deadline_at, created_at, updated_at
            FROM approval_instances
            WHERE id = :id
              AND tenant_id = :tenant_id
              AND is_deleted = false
        """),
        {"id": instance_id, "tenant_id": x_tenant_id},
    )
    if inst is None:
        raise HTTPException(status_code=404, detail="审批实例不存在")

    step_records = await db.fetch_all(
        text("""
            SELECT id, step_no, approver_id, approver_name, approver_role,
                   action, comment, delegated_to, acted_at
            FROM approval_step_records
            WHERE instance_id = :instance_id
              AND tenant_id = :tenant_id
            ORDER BY acted_at ASC
        """),
        {"instance_id": instance_id, "tenant_id": x_tenant_id},
    )

    return {
        "ok": True,
        "data": {
            **dict(inst),
            "step_records": [dict(r) for r in step_records],
        },
    }


@router.post("/instances/{instance_id}/act")
async def act_on_instance(
    instance_id: str,
    body: ActRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: Any = Depends(get_db),
) -> Dict[str, Any]:
    """对审批实例执行 approve 或 reject 动作。"""
    from ..services.approval_engine import approval_engine

    try:
        result = await approval_engine.act(
            db=db,
            tenant_id=x_tenant_id,
            instance_id=instance_id,
            approver_id=body.approver_id,
            approver_name=body.approver_name,
            action=body.action,
            comment=body.comment,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"ok": True, "data": result}


@router.delete("/instances/{instance_id}")
async def cancel_instance(
    instance_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: Any = Depends(get_db),
) -> Dict[str, Any]:
    """
    撤回审批实例（发起人自撤）。
    仅允许 status=pending 且 current_step=1 时操作。
    """
    inst = await db.fetch_one(
        text("""
            SELECT id, status, current_step
            FROM approval_instances
            WHERE id = :id
              AND tenant_id = :tenant_id
              AND is_deleted = false
        """),
        {"id": instance_id, "tenant_id": x_tenant_id},
    )
    if inst is None:
        raise HTTPException(status_code=404, detail="审批实例不存在")
    if inst["status"] != "pending":
        raise HTTPException(
            status_code=422,
            detail=f"当前状态 {inst['status']!r} 不允许撤回，仅 pending 可撤回",
        )
    if inst["current_step"] != 1:
        raise HTTPException(
            status_code=422,
            detail="审批已进入第2步或以上，无法撤回",
        )

    now = datetime.now(tz=timezone.utc)
    await db.execute(
        text("""
            UPDATE approval_instances
            SET status = 'cancelled', updated_at = :now
            WHERE id = :id
        """),
        {"id": instance_id, "now": now},
    )
    log.info("approval_instance_cancelled", instance_id=instance_id, tenant_id=x_tenant_id)
    return {"ok": True, "data": {"instance_id": instance_id, "result": "cancelled"}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  通知端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/notifications")
async def list_notifications(
    recipient_id: str = Query(..., description="接收人ID"),
    is_read: Optional[bool] = Query(None, description="true=已读，false=未读，不填=全部"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: Any = Depends(get_db),
) -> Dict[str, Any]:
    """查询指定接收人的通知列表。"""
    offset = (page - 1) * size

    if is_read is not None:
        rows = await db.fetch_all(
            text("""
                SELECT id, instance_id, recipient_id, recipient_name,
                       notification_type, message, is_read, sent_at, read_at
                FROM approval_notifications
                WHERE tenant_id = :tenant_id
                  AND recipient_id = :recipient_id
                  AND is_read = :is_read
                ORDER BY sent_at DESC
                LIMIT :size OFFSET :offset
            """),
            {
                "tenant_id": x_tenant_id,
                "recipient_id": recipient_id,
                "is_read": is_read,
                "size": size,
                "offset": offset,
            },
        )
        total_row = await db.fetch_one(
            text("""
                SELECT COUNT(*) AS cnt FROM approval_notifications
                WHERE tenant_id = :tenant_id
                  AND recipient_id = :recipient_id
                  AND is_read = :is_read
            """),
            {"tenant_id": x_tenant_id, "recipient_id": recipient_id, "is_read": is_read},
        )
    else:
        rows = await db.fetch_all(
            text("""
                SELECT id, instance_id, recipient_id, recipient_name,
                       notification_type, message, is_read, sent_at, read_at
                FROM approval_notifications
                WHERE tenant_id = :tenant_id
                  AND recipient_id = :recipient_id
                ORDER BY sent_at DESC
                LIMIT :size OFFSET :offset
            """),
            {
                "tenant_id": x_tenant_id,
                "recipient_id": recipient_id,
                "size": size,
                "offset": offset,
            },
        )
        total_row = await db.fetch_one(
            text("""
                SELECT COUNT(*) AS cnt FROM approval_notifications
                WHERE tenant_id = :tenant_id
                  AND recipient_id = :recipient_id
            """),
            {"tenant_id": x_tenant_id, "recipient_id": recipient_id},
        )

    total = total_row["cnt"] if total_row else 0
    return {
        "ok": True,
        "data": {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: Any = Depends(get_db),
) -> Dict[str, Any]:
    """标记通知为已读。"""
    now = datetime.now(tz=timezone.utc)
    result = await db.fetch_one(
        text("""
            SELECT id FROM approval_notifications
            WHERE id = :id AND tenant_id = :tenant_id
        """),
        {"id": notification_id, "tenant_id": x_tenant_id},
    )
    if result is None:
        raise HTTPException(status_code=404, detail="通知不存在")

    await db.execute(
        text("""
            UPDATE approval_notifications
            SET is_read = true, read_at = :now
            WHERE id = :id
        """),
        {"id": notification_id, "now": now},
    )
    return {"ok": True, "data": {"notification_id": notification_id, "read_at": now.isoformat()}}
