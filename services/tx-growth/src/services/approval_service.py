"""营销审批流引擎

职责：
  - 根据审批流模板触发条件，判断营销操作是否需要审批
  - 创建审批单，推送企微通知给审批人
  - 处理审批通过/拒绝，推进多级审批
  - 审批全部通过后自动激活对应营销对象
  - 定时检查超时审批单（auto_approve_on_timeout）

金额单位：分(fen)
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from models.approval import ApprovalRequest, ApprovalWorkflow
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 内置预置审批流模板（首次迁移或手动调用 seed_default_workflows 插入）
# ---------------------------------------------------------------------------

DEFAULT_WORKFLOWS: list[dict] = [
    {
        "name": "大额优惠审批",
        "trigger_conditions": {
            "type": "campaign_activation",
            "conditions": [
                {"field": "max_discount_fen", "op": "gt", "value": 5000},  # 优惠 > 50元
            ],
        },
        "steps": [
            {
                "step": 1,
                "role": "store_manager",
                "timeout_hours": 24,
                "auto_approve_on_timeout": False,
            },
        ],
        "is_active": True,
        "priority": 10,
    },
    {
        "name": "大规模活动审批",
        "trigger_conditions": {
            "type": "campaign_activation",
            "conditions": [
                {"field": "target_count", "op": "gt", "value": 500},  # 目标人数 > 500
            ],
        },
        "steps": [
            {
                "step": 1,
                "role": "regional_manager",
                "timeout_hours": 48,
                "auto_approve_on_timeout": True,
            },
        ],
        "is_active": True,
        "priority": 5,
    },
]


# ---------------------------------------------------------------------------
# 条件匹配辅助
# ---------------------------------------------------------------------------

_OP_MAP: dict[str, str] = {
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "eq": "==",
    "neq": "!=",
    "in": "in",
}


def _evaluate_condition(field: str, op: str, value: object, data: dict) -> bool:
    """评估单个条件是否满足。

    Args:
        field: 数据字段名（对应 object_data 的 key）
        op:    比较运算符（gt/gte/lt/lte/eq/neq/in）
        value: 阈值
        data:  被审批对象数据字典

    Returns:
        True 表示条件满足。
    """
    actual = data.get(field)
    if actual is None:
        return False

    if op == "gt":
        return actual > value
    if op == "gte":
        return actual >= value
    if op == "lt":
        return actual < value
    if op == "lte":
        return actual <= value
    if op == "eq":
        return actual == value
    if op == "neq":
        return actual != value
    if op == "in":
        if isinstance(value, (list, tuple, set)):
            return actual in value
        return False

    log.warning("approval.unknown_op", op=op)
    return False


def _evaluate_conditions(conditions: list[dict], data: dict) -> bool:
    """评估一组条件（AND 逻辑，所有条件必须全部满足）。

    Args:
        conditions: 条件列表 [{field, op, value}, ...]
        data: 被审批对象数据字典

    Returns:
        True 表示所有条件均满足。空条件列表返回 False。
    """
    if not conditions:
        return False

    for cond in conditions:
        field = cond.get("field", "")
        op = cond.get("op", "eq")
        threshold = cond.get("value")
        if not _evaluate_condition(field, op, threshold, data):
            return False

    return True


def _match_workflow(workflow: ApprovalWorkflow, object_type: str, object_data: dict) -> bool:
    """判断工作流是否与本次操作匹配（AND 逻辑，所有条件全部满足）。"""
    conds = workflow.trigger_conditions
    if not conds:
        return False

    # 触发类型检查（如 campaign_activation）
    cond_type = conds.get("type", "")
    if cond_type and cond_type != f"{object_type}_activation":
        return False

    for cond in conds.get("conditions", []):
        field = cond.get("field", "")
        op = cond.get("op", "eq")
        threshold = cond.get("value")
        if not _evaluate_condition(field, op, threshold, object_data):
            return False

    return True


# ---------------------------------------------------------------------------
# ApprovalService
# ---------------------------------------------------------------------------


class ApprovalService:
    """营销审批流服务"""

    GATEWAY_URL: str = os.getenv("GATEWAY_SERVICE_URL", "http://gateway:8000")
    FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "https://os.tunxiang.com")

    # ------------------------------------------------------------------
    # 核心业务方法
    # ------------------------------------------------------------------

    async def check_trigger(
        self,
        tenant_id: uuid.UUID,
        object_type: str,
        object_data: dict,
        db: AsyncSession,
    ) -> dict:
        """触发条件评估引擎 — 检查对象数据是否匹配审批流模板。

        扫描租户下所有启用的审批流模板，按优先级降序逐个匹配。
        使用 _evaluate_conditions 对触发条件进行 AND 评估。

        Args:
            tenant_id: 租户 ID
            object_type: 对象类型，如 campaign/journey
            object_data: 对象数据字典
            db: 数据库会话

        Returns:
            {"needs_approval": True, "workflow_id": UUID, "workflow_name": str}
            或 {"needs_approval": False}
        """
        needs, workflow_id = await self.check_needs_approval(
            object_type=object_type,
            object_data=object_data,
            tenant_id=tenant_id,
            db=db,
        )
        if needs and workflow_id is not None:
            # 获取工作流名称
            try:
                wf = await self._get_workflow(workflow_id, tenant_id, db)
                return {
                    "needs_approval": True,
                    "workflow_id": workflow_id,
                    "workflow_name": wf.name,
                }
            except ValueError:
                return {"needs_approval": True, "workflow_id": workflow_id}
        return {"needs_approval": False}

    async def check_needs_approval(
        self,
        object_type: str,
        object_data: dict,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> tuple[bool, Optional[uuid.UUID]]:
        """判断某操作是否需要审批。

        查询租户下所有启用的审批流模板，对触发条件进行 AND 匹配，
        取优先级（priority）最高的匹配工作流。

        Returns:
            (True, workflow_id)  — 需要审批
            (False, None)        — 无需审批
        """
        stmt = (
            select(ApprovalWorkflow)
            .where(
                and_(
                    ApprovalWorkflow.tenant_id == tenant_id,
                    ApprovalWorkflow.is_active == True,  # noqa: E712
                    ApprovalWorkflow.is_deleted == False,  # noqa: E712
                )
            )
            .order_by(ApprovalWorkflow.priority.desc())
        )

        result = await db.execute(stmt)
        workflows: list[ApprovalWorkflow] = list(result.scalars().all())

        for wf in workflows:
            if _match_workflow(wf, object_type, object_data):
                log.info(
                    "approval.workflow_matched",
                    workflow_id=str(wf.id),
                    workflow_name=wf.name,
                    object_type=object_type,
                    tenant_id=str(tenant_id),
                )
                return True, wf.id

        return False, None

    async def create_request(
        self,
        workflow_id: uuid.UUID,
        object_type: str,
        object_id: str,
        object_summary: dict,
        requester_id: uuid.UUID,
        requester_name: str,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> ApprovalRequest:
        """创建审批单（幂等：同 object 存在 pending 单时直接返回现有单）。

        Steps:
            1. 幂等检查：若已有 pending 审批单则直接返回
            2. 查询工作流第一步，设置超时时间
            3. INSERT ApprovalRequest
            4. 推送企微通知给第一步审批人
        """
        # 幂等：同一对象存在进行中审批单时不重复创建
        existing = await self._find_pending_request(object_type, object_id, tenant_id, db)
        if existing is not None:
            log.info(
                "approval.create_request_idempotent",
                request_id=str(existing.id),
                object_type=object_type,
                object_id=object_id,
                tenant_id=str(tenant_id),
            )
            return existing

        # 查工作流
        workflow = await self._get_workflow(workflow_id, tenant_id, db)
        first_step = workflow.steps[0] if workflow.steps else None
        timeout_hours: int = first_step.get("timeout_hours", 24) if first_step else 24
        now = datetime.now(timezone.utc)

        request = ApprovalRequest(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            object_type=object_type,
            object_id=object_id,
            object_summary=object_summary,
            requester_id=requester_id,
            requester_name=requester_name,
            status="pending",
            current_step=1,
            approval_history=[],
            expires_at=now + timedelta(hours=timeout_hours),
        )
        db.add(request)
        await db.flush()  # 获取 id，不立即 commit（由调用方 commit）

        log.info(
            "approval.request_created",
            request_id=str(request.id),
            workflow_id=str(workflow_id),
            object_type=object_type,
            object_id=object_id,
            requester_id=str(requester_id),
            tenant_id=str(tenant_id),
        )

        # 异步推送企微通知（非阻塞，通知失败不影响主流程）
        await self._notify_approver_by_role(
            role=first_step.get("role", "") if first_step else "",
            request=request,
            tenant_id=tenant_id,
        )

        return request

    async def approve(
        self,
        request_id: uuid.UUID,
        approver_id: uuid.UUID,
        comment: Optional[str],
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict:
        """审批通过当前步骤。

        Steps:
            1. 加载审批单，验证状态为 pending
            2. 追加审批历史记录
            3. 若还有下一步：推进 current_step，更新 expires_at，通知下一级
            4. 若已是最后一步：更新 status=approved，approved_at=now，触发激活
            5. 通知申请人（最终结果）
        """
        request = await self._get_request(request_id, tenant_id, db)

        if request.status != "pending":
            return {
                "ok": False,
                "reason": f"审批单当前状态为 {request.status}，无法审批",
            }

        now = datetime.now(timezone.utc)
        workflow = await self._get_workflow(request.workflow_id, tenant_id, db)
        steps: list[dict] = workflow.steps or []
        current_idx = request.current_step - 1  # 转为 0-indexed

        # 追加历史记录（追加写，不修改已有条目）
        history_entry = {
            "step": request.current_step,
            "approver_id": str(approver_id),
            "action": "approved",
            "comment": comment or "",
            "at": now.isoformat(),
        }
        updated_history = list(request.approval_history) + [history_entry]
        request.approval_history = updated_history

        next_idx = current_idx + 1
        if next_idx < len(steps):
            # 还有下一步
            next_step = steps[next_idx]
            request.current_step = next_step["step"]
            timeout_hours = next_step.get("timeout_hours", 24)
            request.expires_at = now + timedelta(hours=timeout_hours)
            await db.flush()

            log.info(
                "approval.advanced_to_next_step",
                request_id=str(request_id),
                next_step=request.current_step,
                tenant_id=str(tenant_id),
            )

            await self._notify_approver_by_role(
                role=next_step.get("role", ""),
                request=request,
                tenant_id=tenant_id,
            )

            return {
                "ok": True,
                "status": "pending",
                "current_step": request.current_step,
                "message": f"已推进至第 {request.current_step} 步审批",
            }

        # 最后一步全部通过
        request.status = "approved"
        request.approved_at = now
        request.expires_at = None
        await db.flush()

        log.info(
            "approval.fully_approved",
            request_id=str(request_id),
            object_type=request.object_type,
            object_id=request.object_id,
            tenant_id=str(tenant_id),
        )

        # 触发对象激活
        await self._activate_approved_object(
            object_type=request.object_type,
            object_id=request.object_id,
            tenant_id=tenant_id,
        )

        # 通知申请人
        await self._notify_requester(
            request=request,
            message=f"您的 {request.object_type}「{request.object_summary.get('name', request.object_id)}」审批已全部通过，系统将自动激活。",
            tenant_id=tenant_id,
        )

        return {
            "ok": True,
            "status": "approved",
            "approved_at": now.isoformat(),
        }

    async def reject(
        self,
        request_id: uuid.UUID,
        approver_id: uuid.UUID,
        reason: str,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict:
        """审批拒绝。

        Steps:
            1. 更新 status=rejected，reject_reason，追加历史
            2. 对应对象保持 draft 状态（由前端/调用方处理）
            3. 企微通知申请人
        """
        request = await self._get_request(request_id, tenant_id, db)

        if request.status != "pending":
            return {
                "ok": False,
                "reason": f"审批单当前状态为 {request.status}，无法拒绝",
            }

        now = datetime.now(timezone.utc)

        history_entry = {
            "step": request.current_step,
            "approver_id": str(approver_id),
            "action": "rejected",
            "comment": reason,
            "at": now.isoformat(),
        }
        request.approval_history = list(request.approval_history) + [history_entry]
        request.status = "rejected"
        request.reject_reason = reason
        request.expires_at = None
        await db.flush()

        log.info(
            "approval.rejected",
            request_id=str(request_id),
            approver_id=str(approver_id),
            object_type=request.object_type,
            object_id=request.object_id,
            reason=reason,
            tenant_id=str(tenant_id),
        )

        obj_name = request.object_summary.get("name", request.object_id)
        await self._notify_requester(
            request=request,
            message=(f"您的 {request.object_type}「{obj_name}」审批被拒绝，原因：{reason}。请修改后重新提交。"),
            tenant_id=tenant_id,
        )

        # 驳回回调：将关联对象状态改为 rejected
        await self._reject_callback(
            object_type=request.object_type,
            object_id=request.object_id,
            tenant_id=tenant_id,
        )

        return {
            "ok": True,
            "status": "rejected",
            "reason": reason,
        }

    async def cancel(
        self,
        request_id: uuid.UUID,
        requester_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict:
        """申请人撤销审批单（幂等：已 cancelled 则直接返回 ok）。"""
        request = await self._get_request(request_id, tenant_id, db)

        if request.status == "cancelled":
            return {"ok": True, "status": "cancelled"}

        if request.status != "pending":
            return {
                "ok": False,
                "reason": f"审批单当前状态为 {request.status}，无法撤销",
            }

        if request.requester_id != requester_id:
            return {"ok": False, "reason": "只有申请人可撤销审批单"}

        now = datetime.now(timezone.utc)
        history_entry = {
            "step": request.current_step,
            "approver_id": str(requester_id),
            "action": "cancelled",
            "comment": "申请人主动撤销",
            "at": now.isoformat(),
        }
        request.approval_history = list(request.approval_history) + [history_entry]
        request.status = "cancelled"
        request.expires_at = None
        await db.flush()

        log.info(
            "approval.cancelled",
            request_id=str(request_id),
            requester_id=str(requester_id),
            tenant_id=str(tenant_id),
        )

        return {"ok": True, "status": "cancelled"}

    async def batch_approve(
        self,
        request_ids: list[uuid.UUID],
        approver_id: uuid.UUID,
        comment: Optional[str],
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict:
        """批量审批通过。

        逐条调用 approve()，汇总结果。单条失败不影响其他审批单。

        Returns:
            {
                "total": int,
                "succeeded": int,
                "failed": int,
                "results": [{"request_id": str, "ok": bool, ...}, ...]
            }
        """
        results: list[dict] = []
        succeeded = 0
        failed = 0

        for request_id in request_ids:
            try:
                result = await self.approve(
                    request_id=request_id,
                    approver_id=approver_id,
                    comment=comment,
                    tenant_id=tenant_id,
                    db=db,
                )
                result["request_id"] = str(request_id)
                results.append(result)
                if result.get("ok"):
                    succeeded += 1
                else:
                    failed += 1
            except ValueError as exc:
                results.append({
                    "request_id": str(request_id),
                    "ok": False,
                    "reason": str(exc),
                })
                failed += 1

        log.info(
            "approval.batch_approve",
            total=len(request_ids),
            succeeded=succeeded,
            failed=failed,
            tenant_id=str(tenant_id),
        )

        return {
            "total": len(request_ids),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        }

    async def check_expired_requests(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict:
        """定时任务：检查超时审批单并按策略处理。

        - auto_approve_on_timeout=True：自动通过当前步骤，推进或最终批准
        - auto_approve_on_timeout=False：标记 expired，通知申请人
        """
        now = datetime.now(timezone.utc)

        stmt = select(ApprovalRequest).where(
            and_(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.status == "pending",
                ApprovalRequest.expires_at < now,
                ApprovalRequest.is_deleted == False,  # noqa: E712
            )
        )
        result = await db.execute(stmt)
        expired_requests: list[ApprovalRequest] = list(result.scalars().all())

        auto_approved = 0
        expired_count = 0

        for req in expired_requests:
            workflow = await self._get_workflow(req.workflow_id, tenant_id, db)
            steps: list[dict] = workflow.steps or []
            current_idx = req.current_step - 1
            current_step_cfg = steps[current_idx] if current_idx < len(steps) else {}
            auto_approve: bool = current_step_cfg.get("auto_approve_on_timeout", False)

            if auto_approve:
                # 系统自动通过当前步骤（使用 nil UUID 标识系统操作）
                sys_approver_id = uuid.UUID(int=0)
                result_dict = await self.approve(
                    request_id=req.id,
                    approver_id=sys_approver_id,
                    comment="超时自动通过",
                    tenant_id=tenant_id,
                    db=db,
                )
                if result_dict.get("ok"):
                    auto_approved += 1
                    log.info(
                        "approval.timeout_auto_approved",
                        request_id=str(req.id),
                        tenant_id=str(tenant_id),
                    )
            else:
                history_entry = {
                    "step": req.current_step,
                    "approver_id": None,
                    "action": "expired",
                    "comment": "审批超时，已标记为过期",
                    "at": now.isoformat(),
                }
                req.approval_history = list(req.approval_history) + [history_entry]
                req.status = "expired"
                req.expires_at = None
                await db.flush()
                expired_count += 1

                obj_name = req.object_summary.get("name", req.object_id)
                await self._notify_requester(
                    request=req,
                    message=(f"您的 {req.object_type}「{obj_name}」审批已超时，请重新提交审批申请。"),
                    tenant_id=tenant_id,
                )

                log.info(
                    "approval.timeout_expired",
                    request_id=str(req.id),
                    tenant_id=str(tenant_id),
                )

        return {
            "processed": len(expired_requests),
            "auto_approved": auto_approved,
            "expired": expired_count,
        }

    # ------------------------------------------------------------------
    # 种子数据
    # ------------------------------------------------------------------

    async def seed_default_workflows(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict:
        """为指定租户插入内置审批流模板（幂等：已存在同名模板则跳过）。"""
        inserted = 0
        for wf_def in DEFAULT_WORKFLOWS:
            # 按名称幂等检查
            stmt = select(ApprovalWorkflow).where(
                and_(
                    ApprovalWorkflow.tenant_id == tenant_id,
                    ApprovalWorkflow.name == wf_def["name"],
                    ApprovalWorkflow.is_deleted == False,  # noqa: E712
                )
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                continue

            wf = ApprovalWorkflow(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                name=wf_def["name"],
                trigger_conditions=wf_def["trigger_conditions"],
                steps=wf_def["steps"],
                is_active=wf_def.get("is_active", True),
                priority=wf_def.get("priority", 0),
            )
            db.add(wf)
            inserted += 1

        await db.flush()
        log.info("approval.seed_workflows", inserted=inserted, tenant_id=str(tenant_id))
        return {"inserted": inserted}

    # ------------------------------------------------------------------
    # 私有辅助方法
    # ------------------------------------------------------------------

    async def _get_workflow(
        self,
        workflow_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> ApprovalWorkflow:
        stmt = select(ApprovalWorkflow).where(
            and_(
                ApprovalWorkflow.id == workflow_id,
                ApprovalWorkflow.tenant_id == tenant_id,
                ApprovalWorkflow.is_deleted == False,  # noqa: E712
            )
        )
        wf = (await db.execute(stmt)).scalar_one_or_none()
        if wf is None:
            raise ValueError(f"审批流模板不存在: {workflow_id}")
        return wf

    async def _get_request(
        self,
        request_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> ApprovalRequest:
        stmt = select(ApprovalRequest).where(
            and_(
                ApprovalRequest.id == request_id,
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.is_deleted == False,  # noqa: E712
            )
        )
        req = (await db.execute(stmt)).scalar_one_or_none()
        if req is None:
            raise ValueError(f"审批单不存在: {request_id}")
        return req

    async def _find_pending_request(
        self,
        object_type: str,
        object_id: str,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> Optional[ApprovalRequest]:
        """查找同一对象的待审批单（幂等保障）。"""
        stmt = select(ApprovalRequest).where(
            and_(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.object_type == object_type,
                ApprovalRequest.object_id == object_id,
                ApprovalRequest.status == "pending",
                ApprovalRequest.is_deleted == False,  # noqa: E712
            )
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def _notify_approver_by_role(
        self,
        role: str,
        request: ApprovalRequest,
        tenant_id: uuid.UUID,
    ) -> None:
        """根据角色查找审批人并推送企微通知。

        当前实现：通过 gateway 内部接口查询对应角色的员工列表，
        再调用 gateway 推送企微文本卡片消息。
        角色查询失败时只记录日志，不抛出异常（通知失败不阻断审批流）。
        """
        if not role:
            return

        try:
            approver_wecom_ids = await self._fetch_approver_wecom_ids(role, tenant_id)
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
            log.warning(
                "approval.notify_fetch_approvers_failed",
                role=role,
                error=str(exc),
                tenant_id=str(tenant_id),
            )
            return

        obj_name = request.object_summary.get("name", request.object_id)
        title = f"【待审批】{request.object_type} - {obj_name}"
        description = (
            f"申请人：{request.requester_name}\n类型：{request.object_type}\n摘要：{obj_name}\n请在审批截止前处理"
        )
        detail_url = f"{self.FRONTEND_BASE_URL}/approval/{request.id}"

        for wecom_id in approver_wecom_ids:
            await self._notify_approver(
                wecom_user_id=wecom_id,
                title=title,
                description=description,
                url=detail_url,
                tenant_id=tenant_id,
            )

    async def _notify_approver(
        self,
        wecom_user_id: str,
        title: str,
        description: str,
        url: str,
        tenant_id: uuid.UUID,
    ) -> None:
        """通过 gateway 推送企微文本卡片给审批人。"""
        payload = {
            "wecom_user_id": wecom_user_id,
            "type": "text_card",
            "title": title,
            "description": description,
            "url": url,
            "btntxt": "去审批",
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.GATEWAY_URL}/internal/wecom/send",
                    json=payload,
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
            log.info(
                "approval.notify_approver_sent",
                wecom_user_id=wecom_user_id,
                title=title,
            )
        except httpx.HTTPStatusError as exc:
            log.error(
                "approval.notify_approver_http_error",
                status=exc.response.status_code,
                wecom_user_id=wecom_user_id,
            )
        except httpx.ConnectError as exc:
            log.error(
                "approval.notify_approver_connect_error",
                error=str(exc),
                wecom_user_id=wecom_user_id,
            )
        except httpx.TimeoutException as exc:
            log.error(
                "approval.notify_approver_timeout",
                error=str(exc),
                wecom_user_id=wecom_user_id,
            )

    async def _notify_requester(
        self,
        request: ApprovalRequest,
        message: str,
        tenant_id: uuid.UUID,
    ) -> None:
        """通过 gateway 推送企微文本消息给申请人。"""
        payload = {
            "employee_id": str(request.requester_id),
            "type": "text",
            "content": message,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.GATEWAY_URL}/internal/wecom/send",
                    json=payload,
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
            log.info(
                "approval.notify_requester_sent",
                requester_id=str(request.requester_id),
                request_id=str(request.id),
            )
        except httpx.HTTPStatusError as exc:
            log.error(
                "approval.notify_requester_http_error",
                status=exc.response.status_code,
                requester_id=str(request.requester_id),
            )
        except httpx.ConnectError as exc:
            log.error(
                "approval.notify_requester_connect_error",
                error=str(exc),
                requester_id=str(request.requester_id),
            )
        except httpx.TimeoutException as exc:
            log.error(
                "approval.notify_requester_timeout",
                error=str(exc),
                requester_id=str(request.requester_id),
            )

    async def _fetch_approver_wecom_ids(
        self,
        role: str,
        tenant_id: uuid.UUID,
    ) -> list[str]:
        """从 tx-org（通过 gateway）查询指定角色的员工企微 ID 列表。"""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.GATEWAY_URL}/internal/org/employees",
                params={"role": role},
                headers={"X-Tenant-ID": str(tenant_id)},
            )
            resp.raise_for_status()

        data = resp.json()
        employees: list[dict] = data.get("data", {}).get("items", [])
        return [emp["wecom_user_id"] for emp in employees if emp.get("wecom_user_id")]

    async def _reject_callback(
        self,
        object_type: str,
        object_id: str,
        tenant_id: uuid.UUID,
    ) -> None:
        """驳回回调：将关联对象状态改为 rejected。

        object_type=campaign → POST /internal/growth/campaigns/{id}/reject
        其他类型暂不处理（仅记录日志）。
        """
        url_map = {
            "campaign": f"{self.GATEWAY_URL}/internal/growth/campaigns/{object_id}/reject",
            "journey": f"{self.GATEWAY_URL}/internal/growth/journeys/{object_id}/reject",
        }
        url = url_map.get(object_type)
        if url is None:
            log.info(
                "approval.reject_callback_no_handler",
                object_type=object_type,
                object_id=object_id,
            )
            return

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url,
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
            log.info(
                "approval.object_rejected",
                object_type=object_type,
                object_id=object_id,
                tenant_id=str(tenant_id),
            )
        except httpx.HTTPStatusError as exc:
            log.error(
                "approval.reject_callback_http_error",
                status=exc.response.status_code,
                object_type=object_type,
                object_id=object_id,
            )
        except httpx.ConnectError as exc:
            log.error(
                "approval.reject_callback_connect_error",
                error=str(exc),
                object_type=object_type,
                object_id=object_id,
            )
        except httpx.TimeoutException as exc:
            log.error(
                "approval.reject_callback_timeout",
                error=str(exc),
                object_type=object_type,
                object_id=object_id,
            )

    async def _activate_approved_object(
        self,
        object_type: str,
        object_id: str,
        tenant_id: uuid.UUID,
    ) -> None:
        """审批通过后通过内部接口激活对应营销对象。

        object_type=campaign  → POST /internal/growth/campaigns/{id}/activate
        object_type=journey   → POST /internal/growth/journeys/{id}/publish
        """
        url_map = {
            "campaign": f"{self.GATEWAY_URL}/internal/growth/campaigns/{object_id}/activate",
            "journey": f"{self.GATEWAY_URL}/internal/growth/journeys/{object_id}/publish",
        }
        url = url_map.get(object_type)
        if url is None:
            log.warning(
                "approval.activate_unknown_object_type",
                object_type=object_type,
                object_id=object_id,
            )
            return

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url,
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
            log.info(
                "approval.object_activated",
                object_type=object_type,
                object_id=object_id,
                tenant_id=str(tenant_id),
            )
        except httpx.HTTPStatusError as exc:
            log.error(
                "approval.activate_http_error",
                status=exc.response.status_code,
                object_type=object_type,
                object_id=object_id,
            )
        except httpx.ConnectError as exc:
            log.error(
                "approval.activate_connect_error",
                error=str(exc),
                object_type=object_type,
                object_id=object_id,
            )
        except httpx.TimeoutException as exc:
            log.error(
                "approval.activate_timeout",
                error=str(exc),
                object_type=object_type,
                object_id=object_id,
            )
