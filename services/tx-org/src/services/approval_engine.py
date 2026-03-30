"""通用审批引擎

支持多级审批流、条件路由、超时催办、审批历史查询。
所有数据库操作通过 AsyncSession 执行，tenant_id 显式传入确保隔离。

审批通知失败不阻塞审批流程本身。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.approval_flow import (
    ApprovalFlowDefinition,
    ApprovalInstance,
    ApprovalRecord,
    FlowStep,
    InstanceStatus,
    RecordAction,
)

logger = logging.getLogger(__name__)

# ── 通知存根 ──────────────────────────────────────────────────────────────────


async def _send_notification(
    recipient_id: str,
    title: str,
    body: str,
    metadata: Dict[str, Any],
) -> None:
    """发送审批通知。失败时仅记录日志，不抛出异常。"""
    try:
        # TODO: 接入消息中心（Redis Streams / PG LISTEN-NOTIFY）
        logger.info(
            "approval_notification",
            extra={
                "recipient_id": recipient_id,
                "title": title,
                "body": body,
                "metadata": metadata,
            },
        )
    except Exception:  # noqa: BLE001 — 通知失败不阻塞主流程
        logger.warning("notification_failed", extra={"recipient_id": recipient_id})


# ── 数据库辅助函数 ─────────────────────────────────────────────────────────────


async def _get_flow_def(
    flow_def_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[Dict[str, Any]]:
    """从 DB 查询审批流定义"""
    row = await db.execute(
        text(
            "SELECT id, tenant_id, flow_name, business_type, steps, is_active, created_at "
            "FROM approval_flow_definitions "
            "WHERE id = :id AND tenant_id = :tenant_id AND is_active = TRUE"
        ),
        {"id": flow_def_id, "tenant_id": tenant_id},
    )
    result = row.mappings().first()
    return dict(result) if result else None


async def _get_instance(
    instance_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[Dict[str, Any]]:
    """从 DB 查询审批实例"""
    row = await db.execute(
        text(
            "SELECT id, tenant_id, flow_def_id, business_type, source_id, title, "
            "amount, current_step, status, initiator_id, store_id, context, "
            "created_at, completed_at "
            "FROM approval_instances "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": instance_id, "tenant_id": tenant_id},
    )
    result = row.mappings().first()
    return dict(result) if result else None


async def _find_approvers_by_role(
    role: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> List[str]:
    """按角色查找门店审批人 ID 列表"""
    rows = await db.execute(
        text(
            "SELECT id FROM employees "
            "WHERE tenant_id = :tenant_id AND store_id = :store_id "
            "AND role = :role AND is_deleted = FALSE"
        ),
        {"tenant_id": tenant_id, "store_id": store_id, "role": role},
    )
    return [str(r[0]) for r in rows.fetchall()]


# ── 核心引擎 ──────────────────────────────────────────────────────────────────


class ApprovalEngine:
    """
    通用审批引擎。

    所有方法为静态异步方法，通过显式参数接受 tenant_id 和 db，
    不持有任何实例状态，便于在 FastAPI 依赖注入体系中使用。
    """

    # ── 发起审批 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def submit(
        flow_def_id: str,
        source_id: Optional[str],
        title: str,
        context: Dict[str, Any],
        initiator_id: str,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        amount: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        发起审批：创建 instance，路由到第一个有效步骤的审批人，发通知。

        Args:
            flow_def_id: 审批流定义 ID
            source_id: 关联业务单据 ID（可选）
            title: 审批标题
            context: 业务上下文，用于条件路由
            initiator_id: 发起人 ID
            store_id: 门店 ID
            tenant_id: 租户 ID
            db: 数据库会话
            amount: 关联金额（用于条件路由，也可直接放在 context["amount"] 中）

        Returns:
            新建的 ApprovalInstance 字典
        """
        # 将 amount 写入 context 以便条件路由评估
        if amount is not None:
            context = {**context, "amount": amount}

        # 查询流程定义
        flow_raw = await _get_flow_def(flow_def_id, tenant_id, db)
        if not flow_raw:
            raise ValueError(f"审批流定义不存在或已停用: {flow_def_id}")

        # 反序列化以便调用 get_applicable_steps
        flow_def = ApprovalFlowDefinition.model_validate(
            {**flow_raw, "steps": flow_raw["steps"]}
        )
        applicable_steps = flow_def.get_applicable_steps(context)
        if not applicable_steps:
            raise ValueError("当前上下文没有匹配的审批步骤，请检查流程定义条件")

        first_step = applicable_steps[0]

        # 写入实例记录
        await db.execute(
            text(
                "INSERT INTO approval_instances "
                "(tenant_id, flow_def_id, business_type, source_id, title, amount, "
                " current_step, status, initiator_id, store_id, context) "
                "VALUES (:tenant_id, :flow_def_id, :business_type, :source_id, :title, :amount, "
                "        :current_step, :status, :initiator_id, :store_id, :context::jsonb) "
                "RETURNING id, created_at"
            ),
            {
                "tenant_id": tenant_id,
                "flow_def_id": flow_def_id,
                "business_type": flow_def.business_type,
                "source_id": source_id,
                "title": title,
                "amount": amount,
                "current_step": first_step.step,
                "status": InstanceStatus.PENDING,
                "initiator_id": initiator_id,
                "store_id": store_id,
                "context": __import__("json").dumps(context, ensure_ascii=False),
            },
        )
        await db.commit()

        # 重新查询以获取完整实例
        instance_row = await db.execute(
            text(
                "SELECT * FROM approval_instances "
                "WHERE tenant_id = :tenant_id AND initiator_id = :initiator_id "
                "AND title = :title ORDER BY created_at DESC LIMIT 1"
            ),
            {"tenant_id": tenant_id, "initiator_id": initiator_id, "title": title},
        )
        instance_data = dict(instance_row.mappings().first())

        # 通知第一审批人
        approvers = await _find_approvers_by_role(
            role=first_step.role,
            store_id=store_id,
            tenant_id=tenant_id,
            db=db,
        )
        for approver_id in approvers:
            await _send_notification(
                recipient_id=approver_id,
                title=f"【待审批】{title}",
                body=f"您有一条新的审批待处理（步骤 {first_step.step}：{first_step.role}）",
                metadata={"instance_id": str(instance_data["id"]), "step": first_step.step},
            )

        return instance_data

    # ── 同意审批 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def approve(
        instance_id: str,
        approver_id: str,
        comment: Optional[str],
        tenant_id: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """
        审批人同意：记录操作，判断是否有下一步，完成或流转。

        Returns:
            更新后的 ApprovalInstance 字典
        """
        instance_data = await _get_instance(instance_id, tenant_id, db)
        if not instance_data:
            raise ValueError(f"审批实例不存在: {instance_id}")
        if instance_data["status"] != InstanceStatus.PENDING:
            raise ValueError(f"审批已结束，当前状态: {instance_data['status']}")

        current_step = instance_data["current_step"]

        # 写审批记录
        await db.execute(
            text(
                "INSERT INTO approval_records "
                "(tenant_id, instance_id, step, approver_id, action, comment) "
                "VALUES (:tenant_id, :instance_id, :step, :approver_id, :action, :comment)"
            ),
            {
                "tenant_id": tenant_id,
                "instance_id": instance_id,
                "step": current_step,
                "approver_id": approver_id,
                "action": RecordAction.APPROVED,
                "comment": comment,
            },
        )

        # 获取流程定义以确定下一步
        flow_raw = await _get_flow_def(
            str(instance_data["flow_def_id"]), tenant_id, db
        )
        if not flow_raw:
            raise ValueError("审批流定义已停用，无法继续流转")

        ctx = instance_data.get("context") or {}
        if isinstance(ctx, str):
            ctx = __import__("json").loads(ctx)
        if instance_data.get("amount") is not None:
            ctx = {**ctx, "amount": float(instance_data["amount"])}

        flow_def = ApprovalFlowDefinition.model_validate(
            {**flow_raw, "steps": flow_raw["steps"]}
        )
        applicable_steps = flow_def.get_applicable_steps(ctx)

        # 找到当前步骤在适用步骤列表中的位置
        current_idx = next(
            (i for i, s in enumerate(applicable_steps) if s.step == current_step),
            None,
        )
        next_step: Optional[FlowStep] = None
        if current_idx is not None and current_idx + 1 < len(applicable_steps):
            next_step = applicable_steps[current_idx + 1]

        if next_step:
            # 流转到下一步
            await db.execute(
                text(
                    "UPDATE approval_instances SET current_step = :next_step "
                    "WHERE id = :id AND tenant_id = :tenant_id"
                ),
                {
                    "next_step": next_step.step,
                    "id": instance_id,
                    "tenant_id": tenant_id,
                },
            )
            await db.commit()

            # 通知下一级审批人
            approvers = await _find_approvers_by_role(
                role=next_step.role,
                store_id=str(instance_data["store_id"]),
                tenant_id=tenant_id,
                db=db,
            )
            for aid in approvers:
                await _send_notification(
                    recipient_id=aid,
                    title=f"【待审批】{instance_data['title']}",
                    body=f"审批流转至步骤 {next_step.step}（{next_step.role}），请处理",
                    metadata={"instance_id": instance_id, "step": next_step.step},
                )
        else:
            # 全部步骤完成，审批通过
            await db.execute(
                text(
                    "UPDATE approval_instances "
                    "SET status = :status, completed_at = NOW() "
                    "WHERE id = :id AND tenant_id = :tenant_id"
                ),
                {
                    "status": InstanceStatus.APPROVED,
                    "id": instance_id,
                    "tenant_id": tenant_id,
                },
            )
            await db.commit()

            # 通知发起人
            await _send_notification(
                recipient_id=str(instance_data["initiator_id"]),
                title=f"【审批通过】{instance_data['title']}",
                body="您发起的审批已全部通过",
                metadata={"instance_id": instance_id},
            )

        updated = await _get_instance(instance_id, tenant_id, db)
        return updated or {}

    # ── 拒绝审批 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def reject(
        instance_id: str,
        approver_id: str,
        comment: Optional[str],
        tenant_id: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """
        审批人拒绝：记录操作，终止流程，通知发起人。

        Returns:
            更新后的 ApprovalInstance 字典
        """
        instance_data = await _get_instance(instance_id, tenant_id, db)
        if not instance_data:
            raise ValueError(f"审批实例不存在: {instance_id}")
        if instance_data["status"] != InstanceStatus.PENDING:
            raise ValueError(f"审批已结束，当前状态: {instance_data['status']}")

        current_step = instance_data["current_step"]

        # 写审批记录
        await db.execute(
            text(
                "INSERT INTO approval_records "
                "(tenant_id, instance_id, step, approver_id, action, comment) "
                "VALUES (:tenant_id, :instance_id, :step, :approver_id, :action, :comment)"
            ),
            {
                "tenant_id": tenant_id,
                "instance_id": instance_id,
                "step": current_step,
                "approver_id": approver_id,
                "action": RecordAction.REJECTED,
                "comment": comment,
            },
        )

        # 终止流程
        await db.execute(
            text(
                "UPDATE approval_instances "
                "SET status = :status, completed_at = NOW() "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {
                "status": InstanceStatus.REJECTED,
                "id": instance_id,
                "tenant_id": tenant_id,
            },
        )
        await db.commit()

        # 通知发起人
        await _send_notification(
            recipient_id=str(instance_data["initiator_id"]),
            title=f"【审批拒绝】{instance_data['title']}",
            body=f"您发起的审批在步骤 {current_step} 被拒绝。原因：{comment or '无'}",
            metadata={"instance_id": instance_id, "step": current_step},
        )

        updated = await _get_instance(instance_id, tenant_id, db)
        return updated or {}

    # ── 路由到下一步（内部辅助） ───────────────────────────────────────────────

    @staticmethod
    async def _route_to_next_step(
        instance_data: Dict[str, Any],
        flow_def: ApprovalFlowDefinition,
        db: AsyncSession,
        tenant_id: str,
    ) -> None:
        """
        路由下一审批人：
        1. 读取 flow_def.steps[current_step]
        2. 检查 condition（如 amount > 500）
        3. 按 role 查找审批人（从员工表查对应角色的人）
        4. 发送审批通知
        """
        ctx = instance_data.get("context") or {}
        if isinstance(ctx, str):
            ctx = __import__("json").loads(ctx)
        if instance_data.get("amount") is not None:
            ctx = {**ctx, "amount": float(instance_data["amount"])}

        applicable_steps = flow_def.get_applicable_steps(ctx)
        current_step = instance_data["current_step"]
        target = next((s for s in applicable_steps if s.step == current_step), None)
        if not target:
            logger.warning(
                "no_applicable_step",
                extra={
                    "instance_id": str(instance_data["id"]),
                    "current_step": current_step,
                },
            )
            return

        approvers = await _find_approvers_by_role(
            role=target.role,
            store_id=str(instance_data["store_id"]),
            tenant_id=tenant_id,
            db=db,
        )
        for approver_id in approvers:
            await _send_notification(
                recipient_id=approver_id,
                title=f"【待审批】{instance_data['title']}",
                body=f"审批步骤 {current_step}（{target.role}）请处理",
                metadata={
                    "instance_id": str(instance_data["id"]),
                    "step": current_step,
                },
            )

    # ── 超时催办 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def check_timeouts(
        tenant_id: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """
        定时任务：检查超时未处理的审批，向当前步骤审批人发催办通知。

        逻辑：
        - 查询 status=pending 的实例
        - 结合流程定义中当前步骤的 timeout_hours，计算是否超时
        - 超时则发催办通知（不修改实例状态）

        Returns:
            {"checked": int, "reminded": int}
        """
        rows = await db.execute(
            text(
                "SELECT ai.id, ai.tenant_id, ai.flow_def_id, ai.business_type, "
                "ai.title, ai.current_step, ai.store_id, ai.context, ai.amount, "
                "ai.created_at, ai.initiator_id, "
                "afd.steps "
                "FROM approval_instances ai "
                "JOIN approval_flow_definitions afd ON ai.flow_def_id = afd.id "
                "WHERE ai.tenant_id = :tenant_id AND ai.status = 'pending'"
            ),
            {"tenant_id": tenant_id},
        )
        pending = rows.mappings().fetchall()

        checked = 0
        reminded = 0
        now = datetime.now(tz=timezone.utc)

        for row in pending:
            checked += 1
            try:
                import json

                steps_raw = row["steps"]
                if isinstance(steps_raw, str):
                    steps_raw = json.loads(steps_raw)

                flow_def = ApprovalFlowDefinition.model_validate(
                    {
                        "id": str(row["flow_def_id"]),
                        "tenant_id": str(row["tenant_id"]),
                        "flow_name": "",
                        "business_type": row["business_type"],
                        "steps": steps_raw,
                    }
                )

                ctx = row["context"] or {}
                if isinstance(ctx, str):
                    ctx = json.loads(ctx)
                if row["amount"] is not None:
                    ctx = {**ctx, "amount": float(row["amount"])}

                applicable_steps = flow_def.get_applicable_steps(ctx)
                current_step_num = row["current_step"]
                target = next(
                    (s for s in applicable_steps if s.step == current_step_num),
                    None,
                )
                if not target:
                    continue

                created_at = row["created_at"]
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)

                # 判断是否超过 timeout_hours
                deadline = created_at + timedelta(hours=target.timeout_hours)
                if now < deadline:
                    continue

                # 发催办
                approvers = await _find_approvers_by_role(
                    role=target.role,
                    store_id=str(row["store_id"]),
                    tenant_id=tenant_id,
                    db=db,
                )
                for aid in approvers:
                    await _send_notification(
                        recipient_id=aid,
                        title=f"【催办提醒】{row['title']}",
                        body=(
                            f"审批步骤 {current_step_num}（{target.role}）"
                            f"已超过 {target.timeout_hours} 小时未处理，请尽快审批"
                        ),
                        metadata={
                            "instance_id": str(row["id"]),
                            "step": current_step_num,
                        },
                    )
                reminded += 1

            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "timeout_check_error",
                    extra={"instance_id": str(row.get("id")), "error": str(exc)},
                )

        return {"checked": checked, "reminded": reminded}
