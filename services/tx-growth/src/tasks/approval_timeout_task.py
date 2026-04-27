"""审批超时定时任务

职责：
  - 定时扫描所有租户下已超时的 pending 审批单
  - 根据审批步骤配置执行超时策略：
    - auto_approve_on_timeout=True  → 系统自动通过当前步骤
    - auto_approve_on_timeout=False → 标记为 expired 并通知申请人
  - 支持升级机制：当步骤配置了 escalate_to_role 时，
    超时后将审批单升级到指定角色审批

调度方式：由外部调度器（APScheduler / celery beat / cron）定时调用 check_approval_timeouts()
建议间隔：每 5 分钟运行一次

金额单位：分(fen)
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from models.approval import ApprovalRequest, ApprovalWorkflow
from services.approval_service import ApprovalService
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 系统用户 UUID（超时自动审批时使用）
_SYSTEM_USER_ID = uuid.UUID(int=0)


async def check_approval_timeouts(
    db: AsyncSession,
    tenant_id: Optional[uuid.UUID] = None,
) -> dict:
    """检查并处理所有超时的审批单。

    支持两种模式：
      1. 指定 tenant_id — 仅处理该租户
      2. tenant_id=None — 扫描所有租户（全局定时任务模式）

    超时策略：
      - auto_approve_on_timeout=True  → 系统自动通过当前步骤（调用 approve）
      - auto_approve_on_timeout=False → 标记 expired，通知申请人
      - 支持 escalate_to_role → 升级审批（更新 expires_at，通知升级角色）

    Returns:
        {
            "processed": int,         # 处理的超时审批单总数
            "auto_approved": int,     # 自动通过数
            "escalated": int,         # 升级数
            "expired": int,           # 过期数
            "errors": int,            # 处理出错数
        }
    """
    now = datetime.now(timezone.utc)
    svc = ApprovalService()

    # 查询超时的 pending 审批单
    conditions = [
        ApprovalRequest.status == "pending",
        ApprovalRequest.expires_at < now,
        ApprovalRequest.is_deleted == False,  # noqa: E712
    ]
    if tenant_id is not None:
        conditions.append(ApprovalRequest.tenant_id == tenant_id)

    stmt = (
        select(ApprovalRequest)
        .where(and_(*conditions))
        .order_by(ApprovalRequest.expires_at.asc())
        .limit(500)  # 每次最多处理 500 条，防止单次运行时间过长
    )
    result = await db.execute(stmt)
    expired_requests: list[ApprovalRequest] = list(result.scalars().all())

    stats = {
        "processed": 0,
        "auto_approved": 0,
        "escalated": 0,
        "expired": 0,
        "errors": 0,
    }

    for req in expired_requests:
        stats["processed"] += 1
        try:
            await _handle_timeout(req, svc, db, now)
            outcome = _classify_outcome(req)
            stats[outcome] += 1
        except (ValueError, TypeError, KeyError) as exc:
            stats["errors"] += 1
            log.warning(
                "approval_timeout.process_error",
                request_id=str(req.id),
                tenant_id=str(req.tenant_id),
                error=str(exc),
            )

    if stats["processed"] > 0:
        await db.flush()

    log.info(
        "approval_timeout.check_done",
        tenant_id=str(tenant_id) if tenant_id else "ALL",
        **stats,
    )
    return stats


async def _handle_timeout(
    req: ApprovalRequest,
    svc: ApprovalService,
    db: AsyncSession,
    now: datetime,
) -> None:
    """处理单条超时审批单。

    根据当前步骤配置决定超时动作：
      1. 获取审批流模板和当前步骤配置
      2. 检查是否有 escalate_to_role → 升级
      3. 检查 auto_approve_on_timeout → 自动通过
      4. 否则 → 标记 expired
    """
    # 获取工作流和当前步骤配置
    workflow = await _get_workflow_safe(req.workflow_id, req.tenant_id, db)
    if workflow is None:
        # 工作流已删除，直接标记过期
        await _mark_expired(req, db, now, "审批流模板已不存在，自动过期")
        return

    steps: list[dict] = workflow.steps or []
    current_idx = req.current_step - 1
    if current_idx >= len(steps):
        await _mark_expired(req, db, now, "当前步骤超出工作流范围，自动过期")
        return

    step_cfg = steps[current_idx]
    auto_approve: bool = step_cfg.get("auto_approve_on_timeout", False)
    escalate_role: Optional[str] = step_cfg.get("escalate_to_role")

    # 优先级：升级 > 自动通过 > 过期
    if escalate_role:
        await _escalate(req, escalate_role, step_cfg, svc, db, now)
    elif auto_approve:
        await _auto_approve(req, svc, db)
    else:
        await _mark_expired(req, db, now, "审批超时，已标记为过期")


async def _auto_approve(
    req: ApprovalRequest,
    svc: ApprovalService,
    db: AsyncSession,
) -> None:
    """超时自动通过当前步骤。"""
    result = await svc.approve(
        request_id=req.id,
        approver_id=_SYSTEM_USER_ID,
        comment="超时自动通过",
        tenant_id=req.tenant_id,
        db=db,
    )
    if result.get("ok"):
        log.info(
            "approval_timeout.auto_approved",
            request_id=str(req.id),
            tenant_id=str(req.tenant_id),
        )
    else:
        log.warning(
            "approval_timeout.auto_approve_failed",
            request_id=str(req.id),
            reason=result.get("reason", ""),
        )


async def _escalate(
    req: ApprovalRequest,
    escalate_role: str,
    step_cfg: dict,
    svc: ApprovalService,
    db: AsyncSession,
    now: datetime,
) -> None:
    """超时升级：延长超时时间，通知升级角色。

    升级机制：
      1. 将 expires_at 延长（默认 48 小时，或 step_cfg.escalate_timeout_hours）
      2. 追加升级历史记录
      3. 通知升级角色的审批人
    """
    escalate_hours: int = step_cfg.get("escalate_timeout_hours", 48)
    new_expires = now + timedelta(hours=escalate_hours)

    history_entry = {
        "step": req.current_step,
        "approver_id": None,
        "action": "escalated",
        "comment": f"审批超时，已升级到 {escalate_role}",
        "escalate_to_role": escalate_role,
        "at": now.isoformat(),
    }
    req.approval_history = list(req.approval_history) + [history_entry]
    req.expires_at = new_expires
    await db.flush()

    log.info(
        "approval_timeout.escalated",
        request_id=str(req.id),
        escalate_role=escalate_role,
        new_expires=new_expires.isoformat(),
        tenant_id=str(req.tenant_id),
    )

    # 通知升级角色
    await svc._notify_approver_by_role(
        role=escalate_role,
        request=req,
        tenant_id=req.tenant_id,
    )


async def _mark_expired(
    req: ApprovalRequest,
    db: AsyncSession,
    now: datetime,
    comment: str,
) -> None:
    """标记审批单为 expired。"""
    history_entry = {
        "step": req.current_step,
        "approver_id": None,
        "action": "expired",
        "comment": comment,
        "at": now.isoformat(),
    }
    req.approval_history = list(req.approval_history) + [history_entry]
    req.status = "expired"
    req.expires_at = None
    await db.flush()

    log.info(
        "approval_timeout.expired",
        request_id=str(req.id),
        tenant_id=str(req.tenant_id),
    )


async def _get_workflow_safe(
    workflow_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[ApprovalWorkflow]:
    """安全获取工作流（不存在时返回 None 而非抛异常）。"""
    stmt = select(ApprovalWorkflow).where(
        and_(
            ApprovalWorkflow.id == workflow_id,
            ApprovalWorkflow.tenant_id == tenant_id,
            ApprovalWorkflow.is_deleted == False,  # noqa: E712
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _classify_outcome(req: ApprovalRequest) -> str:
    """根据审批单最后一条历史判断本次处理的结果类型。"""
    if not req.approval_history:
        return "errors"
    last = req.approval_history[-1] if isinstance(req.approval_history, list) else {}
    action = last.get("action", "")
    if action == "escalated":
        return "escalated"
    if action == "expired":
        return "expired"
    if action in ("approved", "auto_approved"):
        return "auto_approved"
    return "expired"
