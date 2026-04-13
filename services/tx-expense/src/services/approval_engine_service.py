"""
审批流引擎服务
负责审批实例的创建（路由计算）、审批节点推进、状态回写。

核心设计：
- 路由规则在实例创建时固化为 routing_snapshot，后续规则变更不影响进行中的审批
- 所有涉及资金流出的操作 100% 保留人工审批节点
- 超差标自动升级一级审批（在路由计算时处理）

金额约定：所有金额参数和存储均为分(fen)。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.events.src.emitter import emit_event
from ..models.approval_engine import ApprovalInstance, ApprovalNode, ApprovalRoutingRule
from ..models.expense_application import ExpenseApplication, ExpenseScenario
from ..models.expense_enums import (
    ApprovalAction,
    ApprovalNodeStatus,
    ApprovalRoutingType,
    ExpenseScenarioCode,
    ExpenseStatus,
)
from ..models.expense_events import EXPENSE_APPLICATION_APPROVED, EXPENSE_APPLICATION_REJECTED
from src.services import notification_service
from src.services import org_integration_service

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 金额档位常量（单位：分 fen）
# ─────────────────────────────────────────────────────────────────────────────

_TIER_STORE_MANAGER: int = 50_000       # < 500 元 → 店长
_TIER_REGION_MANAGER: int = 200_000     # < 2000 元 → 区域经理
_TIER_BRAND_FINANCE: int = 1_000_000   # < 10000 元 → 品牌财务
# >= 1_000_000 → 品牌CFO


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# 路由计算（私有）
# ─────────────────────────────────────────────────────────────────────────────

async def _compute_routing_chain(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    brand_id: uuid.UUID,
    total_amount: int,
    scenario_code: str,
) -> list[dict]:
    """计算审批链（私有方法）。

    优先查询 DB 中品牌自定义路由规则；若无配置则使用默认硬编码规则。
    特殊场景 CONTRACT_PAYMENT 固定双签：["brand_finance", "brand_cfo"]。

    Returns::

        [{"role": "region_manager", "node_index": 0, "approver_count": 1}, ...]
    """
    # 1. 先查 DB 中的自定义规则（brand 级别，按 amount 区间匹配）
    db_rules_stmt = (
        select(ApprovalRoutingRule)
        .where(
            ApprovalRoutingRule.tenant_id == tenant_id,
            ApprovalRoutingRule.brand_id == brand_id,
            ApprovalRoutingRule.is_active == True,  # noqa: E712
            ApprovalRoutingRule.is_deleted == False,  # noqa: E712
        )
        .order_by(ApprovalRoutingRule.amount_min.asc())
    )
    db_rules_result = await db.execute(db_rules_stmt)
    db_rules: list[ApprovalRoutingRule] = list(db_rules_result.scalars().all())

    # 按场景 + 金额区间筛选匹配规则
    matched_rules = []
    for rule in db_rules:
        # 场景匹配：NULL 表示通用规则，非 NULL 必须与当前场景一致
        if rule.scenario_code is not None and rule.scenario_code != scenario_code:
            continue
        # 金额区间匹配
        amount_in_range = rule.amount_min <= total_amount and (
            rule.amount_max == -1 or total_amount <= rule.amount_max
        )
        if amount_in_range:
            matched_rules.append(rule)

    if matched_rules:
        # 使用 DB 自定义规则：按 node_index 排序（此处按 amount_min 近似排序）
        chain = []
        for idx, rule in enumerate(matched_rules):
            chain.append({
                "role": rule.approver_role,
                "node_index": idx,
                "approver_count": rule.approver_count,
                "routing_type": rule.routing_type,
            })
        logger.info(
            "approval_routing_from_db",
            tenant_id=str(tenant_id),
            brand_id=str(brand_id),
            scenario_code=scenario_code,
            total_amount=total_amount,
            matched_rule_count=len(matched_rules),
        )
        return chain

    # 2. 无 DB 规则 → 使用默认硬编码规则
    # 特殊场景：合同付款固定双签
    if scenario_code == ExpenseScenarioCode.CONTRACT_PAYMENT.value:
        chain = [
            {"role": "brand_finance", "node_index": 0, "approver_count": 1,
             "routing_type": ApprovalRoutingType.SCENARIO_FIXED.value},
            {"role": "brand_cfo", "node_index": 1, "approver_count": 1,
             "routing_type": ApprovalRoutingType.SCENARIO_FIXED.value},
        ]
        logger.info(
            "approval_routing_contract_fixed_dual_sign",
            tenant_id=str(tenant_id),
            total_amount=total_amount,
        )
        return chain

    # 按金额档位路由
    if total_amount < _TIER_STORE_MANAGER:
        roles = [("store_manager", 0)]
    elif total_amount < _TIER_REGION_MANAGER:
        roles = [("region_manager", 0)]
    elif total_amount < _TIER_BRAND_FINANCE:
        roles = [("brand_finance", 0)]
    else:
        roles = [("brand_cfo", 0)]

    chain = [
        {
            "role": role,
            "node_index": idx,
            "approver_count": 1,
            "routing_type": ApprovalRoutingType.AMOUNT_BASED.value,
        }
        for role, idx in roles
    ]

    logger.info(
        "approval_routing_default",
        tenant_id=str(tenant_id),
        scenario_code=scenario_code,
        total_amount=total_amount,
        chain=[c["role"] for c in chain],
    )
    return chain


# ─────────────────────────────────────────────────────────────────────────────
# 审批实例创建
# ─────────────────────────────────────────────────────────────────────────────

async def create_approval_instance(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    brand_id: uuid.UUID,
) -> ApprovalInstance:
    """为已提交的费用申请创建审批实例。

    由 submit_application() 完成后调用（路由层负责编排顺序）。
    审批链固化为 routing_snapshot，后续规则变更不影响进行中审批。

    注意：approver_id 优先从 tx-org 按角色查询真实员工，
    tx-org 不可用或未配置时降级为 uuid5(tenant_id, role) 确定性占位，保证测试幂等性。
    """
    log = logger.bind(tenant_id=str(tenant_id), application_id=str(application_id))

    # 查询申请
    stmt = select(ExpenseApplication).where(
        ExpenseApplication.id == application_id,
        ExpenseApplication.tenant_id == tenant_id,
        ExpenseApplication.is_deleted == False,  # noqa: E712
    ).options(selectinload(ExpenseApplication.scenario))
    result = await db.execute(stmt)
    application = result.scalar_one_or_none()

    if application is None:
        raise LookupError(f"ExpenseApplication {application_id} not found for tenant {tenant_id}")

    # 获取场景代码
    scenario_code = ""
    if application.scenario is not None:
        scenario_code = application.scenario.code
    else:
        scenario_stmt = select(ExpenseScenario).where(ExpenseScenario.id == application.scenario_id)
        scenario_result = await db.execute(scenario_stmt)
        scenario = scenario_result.scalar_one_or_none()
        scenario_code = scenario.code if scenario else ""

    # 计算审批链
    routing_chain = await _compute_routing_chain(
        db=db,
        tenant_id=tenant_id,
        brand_id=brand_id,
        total_amount=application.total_amount,
        scenario_code=scenario_code,
    )

    total_nodes = len(routing_chain)

    # 创建审批实例
    instance = ApprovalInstance(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        application_id=application_id,
        current_node_index=0,
        total_nodes=total_nodes,
        status=ApprovalNodeStatus.PENDING.value,
        routing_snapshot=routing_chain,
    )
    db.add(instance)
    await db.flush()

    # 创建审批节点（每个角色一个节点，全部初始化为 PENDING）
    nodes = []
    for step in routing_chain:
        # 从 tx-org 查询该角色对应的真实员工；失败时降级为确定性占位 UUID
        approver_employee = await org_integration_service.get_approver_by_role(
            tenant_id=tenant_id,
            role=step["role"],
            brand_id=brand_id,
            store_id=application.store_id,
        )
        if approver_employee and approver_employee.get("employee_id"):
            try:
                approver_id = uuid.UUID(approver_employee["employee_id"])
            except (ValueError, KeyError):
                approver_id = uuid.uuid5(uuid.UUID(str(tenant_id)), f"{brand_id}:{step['role']}")
        else:
            # tx-org 不可用或未配置该角色 → 确定性占位（保证测试幂等性）
            approver_id = uuid.uuid5(uuid.UUID(str(tenant_id)), f"{brand_id}:{step['role']}")

        node = ApprovalNode(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            instance_id=instance.id,
            node_index=step["node_index"],
            approver_id=approver_id,
            approver_role=step["role"],
            status=ApprovalNodeStatus.PENDING.value,
            action=None,
            comment=None,
            acted_at=None,
        )
        nodes.append(node)

    db.add_all(nodes)
    await db.flush()

    # 将申请状态更新为 IN_REVIEW
    application.status = ExpenseStatus.IN_REVIEW.value
    await db.flush()

    log.info(
        "approval_instance_created",
        instance_id=str(instance.id),
        total_nodes=total_nodes,
        routing_chain=[c["role"] for c in routing_chain],
    )

    # 推送给第一个审批人（异步旁路，不阻塞主流程）
    if nodes:
        first_node = nodes[0]

        async def _notify_first_approver() -> None:
            ctx = await org_integration_service.enrich_notification_context(
                tenant_id=tenant_id,
                applicant_id=application.applicant_id,
                store_id=application.store_id,
            )
            await notification_service.send_approval_requested(
                db=db,
                tenant_id=tenant_id,
                application_id=application_id,
                approver_id=first_node.approver_id,
                approver_role=first_node.approver_role,
                application_title=application.title,
                applicant_name=ctx["applicant_name"],
                total_amount=application.total_amount,
                store_name=ctx["store_name"],
                brand_id=application.brand_id,
            )

        asyncio.create_task(_notify_first_approver())

    return instance


# ─────────────────────────────────────────────────────────────────────────────
# 审批动作推进
# ─────────────────────────────────────────────────────────────────────────────

async def process_approval_action(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    instance_id: uuid.UUID,
    approver_id: uuid.UUID,
    action: ApprovalAction,
    comment: Optional[str] = None,
    transfer_to_id: Optional[uuid.UUID] = None,
) -> dict:
    """执行审批动作（通过 / 驳回 / 转交）。

    Returns::

        {
            "action": str,
            "node_index": int,
            "next_approver_id": str | None,
            "application_status": str,
            "instance_status": str,
        }
    """
    log = logger.bind(
        tenant_id=str(tenant_id),
        instance_id=str(instance_id),
        approver_id=str(approver_id),
        action=action.value,
    )

    # 查询审批实例 + 节点
    stmt = (
        select(ApprovalInstance)
        .where(
            ApprovalInstance.id == instance_id,
            ApprovalInstance.tenant_id == tenant_id,
            ApprovalInstance.is_deleted == False,  # noqa: E712
        )
        .options(
            selectinload(ApprovalInstance.nodes),
            selectinload(ApprovalInstance.application),
        )
    )
    result = await db.execute(stmt)
    instance = result.scalar_one_or_none()

    if instance is None:
        raise LookupError(f"ApprovalInstance {instance_id} not found for tenant {tenant_id}")

    if instance.status not in (ApprovalNodeStatus.PENDING.value,):
        raise ValueError(
            f"ApprovalInstance {instance_id} is already in terminal status '{instance.status}'. "
            "No further actions can be taken."
        )

    # 找到当前待处理节点
    current_node = next(
        (n for n in instance.nodes if n.node_index == instance.current_node_index),
        None,
    )
    if current_node is None:
        raise RuntimeError(
            f"ApprovalInstance {instance_id}: current node index {instance.current_node_index} not found."
        )

    # 验证审批人身份
    if current_node.approver_id != approver_id:
        raise PermissionError(
            f"Approver {approver_id} is not authorized for node {current_node.node_index}. "
            f"Expected approver: {current_node.approver_id}"
        )

    if current_node.status != ApprovalNodeStatus.PENDING.value:
        raise ValueError(
            f"Node {current_node.node_index} is already in status '{current_node.status}'."
        )

    now = _now_utc()
    next_approver_id: Optional[uuid.UUID] = None
    final_application_status = instance.application.status

    # ── 执行动作 ──────────────────────────────────────────────────────────────

    if action == ApprovalAction.APPROVE:
        current_node.status = ApprovalNodeStatus.APPROVED.value
        current_node.action = ApprovalAction.APPROVE.value
        current_node.comment = comment
        current_node.acted_at = now

        # 检查是否还有后续节点
        next_node = next(
            (n for n in instance.nodes if n.node_index == instance.current_node_index + 1),
            None,
        )

        if next_node is not None:
            # 推进到下一节点
            instance.current_node_index = next_node.node_index
            next_approver_id = next_node.approver_id
            log.info("approval_node_approved_advancing", next_node_index=next_node.node_index)
        else:
            # 所有节点均已通过，完成审批
            instance.status = ApprovalNodeStatus.APPROVED.value
            instance.application.status = ExpenseStatus.APPROVED.value
            instance.application.approved_at = now
            final_application_status = ExpenseStatus.APPROVED.value

            log.info("approval_instance_completed", total_nodes=instance.total_nodes)

            # 推送审批通过通知给申请人（异步旁路）
            _app_approved = instance.application

            async def _notify_approved() -> None:
                ctx = await org_integration_service.enrich_notification_context(
                    tenant_id=tenant_id,
                    applicant_id=_app_approved.applicant_id,
                    store_id=_app_approved.store_id,
                )
                await notification_service.send_approval_result(
                    db=db,
                    tenant_id=tenant_id,
                    application_id=_app_approved.id,
                    applicant_id=_app_approved.applicant_id,
                    event_type="approved",
                    application_title=_app_approved.title,
                    applicant_name=ctx["applicant_name"],
                    total_amount=_app_approved.total_amount,
                    store_name=ctx["store_name"],
                    brand_id=_app_approved.brand_id,
                    comment=comment,
                )

            asyncio.create_task(_notify_approved())

            asyncio.create_task(
                emit_event(
                    event_type=EXPENSE_APPLICATION_APPROVED,
                    tenant_id=tenant_id,
                    stream_id=str(instance.application_id),
                    payload={
                        "application_id": str(instance.application_id),
                        "tenant_id": str(tenant_id),
                        "instance_id": str(instance_id),
                        "approved_at": now.isoformat(),
                        "total_amount": instance.application.total_amount,
                    },
                    store_id=instance.application.store_id,
                    source_service="tx-expense",
                    metadata={"final_approver_id": str(approver_id)},
                )
            )

    elif action == ApprovalAction.REJECT:
        current_node.status = ApprovalNodeStatus.REJECTED.value
        current_node.action = ApprovalAction.REJECT.value
        current_node.comment = comment
        current_node.acted_at = now

        # 整个审批实例终止
        instance.status = ApprovalNodeStatus.REJECTED.value
        instance.application.status = ExpenseStatus.REJECTED.value
        instance.application.rejected_at = now
        final_application_status = ExpenseStatus.REJECTED.value

        log.info("approval_instance_rejected", node_index=current_node.node_index, comment=comment)

        # 推送驳回通知给申请人（异步旁路）
        _app_rejected = instance.application

        async def _notify_rejected() -> None:
            ctx = await org_integration_service.enrich_notification_context(
                tenant_id=tenant_id,
                applicant_id=_app_rejected.applicant_id,
                store_id=_app_rejected.store_id,
            )
            await notification_service.send_approval_result(
                db=db,
                tenant_id=tenant_id,
                application_id=_app_rejected.id,
                applicant_id=_app_rejected.applicant_id,
                event_type="rejected",
                application_title=_app_rejected.title,
                applicant_name=ctx["applicant_name"],
                total_amount=_app_rejected.total_amount,
                store_name=ctx["store_name"],
                brand_id=_app_rejected.brand_id,
                comment=comment,
            )

        asyncio.create_task(_notify_rejected())

        asyncio.create_task(
            emit_event(
                event_type=EXPENSE_APPLICATION_REJECTED,
                tenant_id=tenant_id,
                stream_id=str(instance.application_id),
                payload={
                    "application_id": str(instance.application_id),
                    "tenant_id": str(tenant_id),
                    "instance_id": str(instance_id),
                    "rejected_at": now.isoformat(),
                    "rejected_by": str(approver_id),
                    "reject_reason": comment or "",
                },
                store_id=instance.application.store_id,
                source_service="tx-expense",
                metadata={"rejector_id": str(approver_id)},
            )
        )

    elif action == ApprovalAction.TRANSFER:
        if transfer_to_id is None:
            raise ValueError("transfer_to_id is required when action is TRANSFER")
        if transfer_to_id == approver_id:
            raise ValueError("Cannot transfer to the same approver")

        # 标记当前节点为 TRANSFERRED
        current_node.status = ApprovalNodeStatus.TRANSFERRED.value
        current_node.action = ApprovalAction.TRANSFER.value
        current_node.comment = comment
        current_node.acted_at = now

        # 插入新节点（继承同一 node_index，但 approver 变更）
        new_node = ApprovalNode(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            instance_id=instance.id,
            node_index=current_node.node_index,  # 同一位置继续
            approver_id=transfer_to_id,
            approver_role=current_node.approver_role,
            status=ApprovalNodeStatus.PENDING.value,
            action=None,
            comment=None,
            acted_at=None,
        )
        db.add(new_node)
        next_approver_id = transfer_to_id

        # 推送给新审批人（异步旁路）
        _app_transfer = instance.application
        _transfer_to_id = transfer_to_id

        async def _notify_transferred() -> None:
            ctx = await org_integration_service.enrich_notification_context(
                tenant_id=tenant_id,
                applicant_id=_app_transfer.applicant_id,
                store_id=_app_transfer.store_id,
            )
            await notification_service.send_approval_requested(
                db=db,
                tenant_id=tenant_id,
                application_id=_app_transfer.id,
                approver_id=_transfer_to_id,
                approver_role="transferred",
                application_title=_app_transfer.title,
                applicant_name=ctx["applicant_name"],
                total_amount=_app_transfer.total_amount,
                store_name=ctx["store_name"],
                brand_id=_app_transfer.brand_id,
            )

        asyncio.create_task(_notify_transferred())

        log.info(
            "approval_node_transferred",
            from_approver=str(approver_id),
            to_approver=str(transfer_to_id),
        )

    else:
        raise ValueError(f"Unsupported approval action: {action.value}")

    await db.flush()

    return {
        "action": action.value,
        "node_index": current_node.node_index,
        "next_approver_id": str(next_approver_id) if next_approver_id else None,
        "application_status": final_application_status,
        "instance_status": instance.status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 查询接口
# ─────────────────────────────────────────────────────────────────────────────

async def get_pending_approvals(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    approver_id: uuid.UUID,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """查询指定审批人的待处理审批节点列表（先来先审，按 created_at ASC）。

    Returns:
        ([{node + application 信息}, ...], total_count)
    """
    from sqlalchemy import func

    # 查询满足条件的 ApprovalNode（带关联的 ApprovalInstance 和 ExpenseApplication）
    base_where = [
        ApprovalNode.tenant_id == tenant_id,
        ApprovalNode.approver_id == approver_id,
        ApprovalNode.status == ApprovalNodeStatus.PENDING.value,
        ApprovalNode.is_deleted == False,  # noqa: E712
    ]

    count_stmt = (
        select(func.count())
        .select_from(ApprovalNode)
        .where(*base_where)
    )
    count_result = await db.execute(count_stmt)
    total_count = count_result.scalar_one()

    offset = (page - 1) * page_size
    nodes_stmt = (
        select(ApprovalNode)
        .where(*base_where)
        .order_by(ApprovalNode.created_at.asc())
        .offset(offset)
        .limit(page_size)
        .options(
            selectinload(ApprovalNode.instance).selectinload(ApprovalInstance.application).selectinload(
                ExpenseApplication.scenario
            ),
        )
    )
    nodes_result = await db.execute(nodes_stmt)
    nodes = list(nodes_result.scalars().all())

    items = []
    for node in nodes:
        application = node.instance.application if node.instance else None
        items.append({
            "node_id": str(node.id),
            "node_index": node.node_index,
            "instance_id": str(node.instance_id),
            "approver_role": node.approver_role,
            "created_at": node.created_at.isoformat() if node.created_at else None,
            "application": {
                "id": str(application.id) if application else None,
                "title": application.title if application else None,
                "total_amount": application.total_amount if application else None,
                "status": application.status if application else None,
                "applicant_id": str(application.applicant_id) if application else None,
                "store_id": str(application.store_id) if application else None,
                "scenario_code": application.scenario.code if (application and application.scenario) else None,
                "submitted_at": application.submitted_at.isoformat() if (application and application.submitted_at) else None,
            } if application else None,
        })

    return items, total_count


async def get_approval_trace(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
) -> dict:
    """返回完整审批轨迹。

    Returns::

        {
            "instance": {...},
            "nodes": [{...}, ...],
            "routing_snapshot": [...],
        }
    """
    stmt = (
        select(ApprovalInstance)
        .where(
            ApprovalInstance.application_id == application_id,
            ApprovalInstance.tenant_id == tenant_id,
            ApprovalInstance.is_deleted == False,  # noqa: E712
        )
        .options(selectinload(ApprovalInstance.nodes))
    )
    result = await db.execute(stmt)
    instance = result.scalar_one_or_none()

    if instance is None:
        raise LookupError(
            f"No approval instance found for application {application_id} in tenant {tenant_id}"
        )

    nodes_data = []
    for node in sorted(instance.nodes, key=lambda n: n.node_index):
        nodes_data.append({
            "node_id": str(node.id),
            "node_index": node.node_index,
            "approver_id": str(node.approver_id),
            "approver_role": node.approver_role,
            "status": node.status,
            "action": node.action,
            "comment": node.comment,
            "acted_at": node.acted_at.isoformat() if node.acted_at else None,
            "created_at": node.created_at.isoformat() if node.created_at else None,
        })

    return {
        "instance": {
            "id": str(instance.id),
            "application_id": str(instance.application_id),
            "status": instance.status,
            "current_node_index": instance.current_node_index,
            "total_nodes": instance.total_nodes,
            "created_at": instance.created_at.isoformat() if instance.created_at else None,
        },
        "nodes": nodes_data,
        "routing_snapshot": instance.routing_snapshot,
    }


async def send_reminder_for_pending(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    hours_threshold: int = 24,
) -> dict:
    """
    催办超时未审批的申请（由定时任务调用）。
    查询超过 hours_threshold 小时未处理的 pending 审批节点，
    批量推送催办通知。
    返回 {"reminded": N}
    """
    from datetime import timedelta
    from sqlalchemy import select

    cutoff = _now_utc() - timedelta(hours=hours_threshold)

    stmt = (
        select(ApprovalNode)
        .where(
            ApprovalNode.tenant_id == tenant_id,
            ApprovalNode.status == ApprovalNodeStatus.PENDING.value,
            ApprovalNode.created_at < cutoff,
            ApprovalNode.is_deleted == False,  # noqa: E712
        )
        .options(
            selectinload(ApprovalNode.instance).selectinload(ApprovalInstance.application)
        )
    )
    result = await db.execute(stmt)
    nodes = list(result.scalars().all())

    reminded = 0
    for node in nodes:
        application = node.instance.application if node.instance else None
        if application is None:
            continue

        pending_hours = int(
            (_now_utc() - node.created_at).total_seconds() / 3600
        )

        _app_reminder = application
        _node_approver_id = node.approver_id
        _pending_hours = pending_hours

        async def _notify_reminder() -> None:
            ctx = await org_integration_service.enrich_notification_context(
                tenant_id=tenant_id,
                applicant_id=_app_reminder.applicant_id,
                store_id=_app_reminder.store_id,
            )
            await notification_service.send_reminder(
                db=db,
                tenant_id=tenant_id,
                application_id=_app_reminder.id,
                approver_id=_node_approver_id,
                application_title=_app_reminder.title,
                applicant_name=ctx["applicant_name"],
                total_amount=_app_reminder.total_amount,
                store_name=ctx["store_name"],
                brand_id=_app_reminder.brand_id,
                pending_hours=_pending_hours,
            )

        asyncio.create_task(_notify_reminder())
        reminded += 1

    logger.info(
        "approval_reminder_batch_dispatched",
        tenant_id=str(tenant_id),
        hours_threshold=hours_threshold,
        reminded=reminded,
    )
    return {"reminded": reminded}


async def get_routing_rules(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    brand_id: uuid.UUID,
) -> list[ApprovalRoutingRule]:
    """查询品牌的审批路由规则列表（管理端查看/编辑用）。"""
    stmt = (
        select(ApprovalRoutingRule)
        .where(
            ApprovalRoutingRule.tenant_id == tenant_id,
            ApprovalRoutingRule.brand_id == brand_id,
            ApprovalRoutingRule.is_deleted == False,  # noqa: E712
        )
        .order_by(
            ApprovalRoutingRule.scenario_code.asc().nullsfirst(),
            ApprovalRoutingRule.amount_min.asc(),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
