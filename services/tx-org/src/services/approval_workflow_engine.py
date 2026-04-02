"""通用审批流引擎（v2）

基于 approval_workflow_templates / approval_instances / approval_step_records 三张表。

核心能力：
- 按 business_type + context_data 条件匹配模板，支持多级步骤 + 条件路由
- 无模板时自动降级为单级店长审批
- on_approved 按业务类型分发回调（purchase_order/discount/menu_change/hr_request/expense）
- check_timeouts 定时任务：检查超时实例，按模板步骤配置自动标记 timeout
- 所有通知失败不阻塞主流程

日志格式：structlog JSON。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import UniversalPublisher

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_SUPPLY_URL = os.getenv("TX_SUPPLY_SERVICE_URL", "http://tx-supply:8001")
_TRADE_URL = os.getenv("TX_TRADE_SERVICE_URL", "http://tx-trade:8002")
_MENU_URL = os.getenv("TX_MENU_SERVICE_URL", "http://tx-menu:8003")
_FINANCE_URL = os.getenv("TX_FINANCE_SERVICE_URL", "http://tx-finance:8004")
_ORG_URL = os.getenv("TX_ORG_SERVICE_URL", "http://tx-org:8005")


async def _post_callback_wf(url: str, tenant_id: str, business_id: str) -> None:
    """向下游服务发送审批通过回调，失败只记日志不抛异常。"""
    headers = {"X-Tenant-ID": tenant_id, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, headers=headers)
            if resp.status_code >= 400:
                log.warning(
                    "approval_wf_callback_http_error",
                    url=url,
                    status_code=resp.status_code,
                    business_id=business_id,
                )
            else:
                log.info("approval_wf_callback_ok", url=url, business_id=business_id)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        log.warning("approval_wf_callback_failed", url=url, business_id=business_id, error=str(exc))


# ── 常量 ──────────────────────────────────────────────────────────────────────

VALID_BUSINESS_TYPES = frozenset(
    ["purchase_order", "discount", "menu_change", "hr_request", "expense", "leave"]
)

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"
STATUS_TIMEOUT = "timeout"

ACTION_APPROVE = "approve"
ACTION_REJECT = "reject"
ACTION_FORWARD = "forward"

# 无模板时的默认降级步骤
_DEFAULT_STEP = {"step": 1, "approver_role": "store_manager", "timeout_hours": 24}


# ── 通知存根 ──────────────────────────────────────────────────────────────────


async def _notify(
    recipient_id: str,
    title: str,
    body: str,
    meta: dict[str, Any],
) -> None:
    """推送审批通知到 manager app（WebSocket/Redis Streams）。失败时只记日志。

    通过 Redis Pub/Sub 发布到频道 notifications:{recipient_id}，
    mac-station 订阅后通过 WebSocket 推送至员工的 manager app。
    """
    log.info(
        "approval_notification",
        recipient_id=recipient_id,
        title=title,
        body=body,
        meta=meta,
    )
    try:
        redis = await UniversalPublisher.get_redis()
        payload = json.dumps(
            {"title": title, "body": body, "meta": meta},
            ensure_ascii=False,
        )
        await redis.publish(f"notifications:{recipient_id}", payload)
    except (OSError, RuntimeError) as exc:
        log.warning(
            "approval_notification_redis_failed",
            recipient_id=recipient_id,
            error=str(exc),
        )


# ── 条件评估 ──────────────────────────────────────────────────────────────────


def _eval_condition(condition: dict[str, Any] | None, ctx: dict[str, Any]) -> bool:
    """
    评估单个步骤条件是否满足。

    condition 格式：{"field": "amount", "op": ">", "value": 5000}
    condition 为 None 时无条件执行（返回 True）。
    """
    if condition is None:
        return True
    field = condition.get("field")
    op = condition.get("op")
    threshold = condition.get("value")
    if field is None or op is None or threshold is None:
        return True
    actual = ctx.get(field)
    if actual is None:
        return False
    try:
        actual_f = float(actual)
        threshold_f = float(threshold)
    except (TypeError, ValueError):
        return False
    ops: dict[str, bool] = {
        ">": actual_f > threshold_f,
        ">=": actual_f >= threshold_f,
        "<": actual_f < threshold_f,
        "<=": actual_f <= threshold_f,
        "==": actual_f == threshold_f,
        "!=": actual_f != threshold_f,
    }
    return ops.get(op, False)


def _eval_template_conditions(
    conditions: dict[str, Any], ctx: dict[str, Any]
) -> bool:
    """
    评估模板级 conditions 是否匹配 context_data。

    conditions 格式：{"amount": {"op": ">", "value": 1000}}
    空 conditions 表示通用模板（总是匹配）。
    """
    if not conditions:
        return True
    for field, rule in conditions.items():
        if not _eval_condition({"field": field, **rule}, ctx):
            return False
    return True


def _get_applicable_steps(
    steps: list[dict[str, Any]], ctx: dict[str, Any]
) -> list[dict[str, Any]]:
    """返回在当前 context 下生效的步骤（按 step 升序）。"""
    result = []
    for step in sorted(steps, key=lambda s: s.get("step", 0)):
        cond = step.get("condition")
        if _eval_condition(cond, ctx):
            result.append(step)
    return result


# ── DB 辅助 ───────────────────────────────────────────────────────────────────


async def _find_template(
    tenant_id: str,
    business_type: str,
    ctx: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any] | None:
    """
    按业务类型查找最合适的模板。

    策略：
    1. 查出该租户该业务类型所有活跃模板
    2. 过滤满足 conditions 的模板
    3. 选条件最多（最具体）的那个（简单优先级策略）
    4. 无匹配则返回 None（调用方降级为单级审批）
    """
    rows = await db.execute(
        text(
            "SELECT id, name, steps, conditions "
            "FROM approval_workflow_templates "
            "WHERE tenant_id = :tid AND business_type = :bt "
            "AND is_active = TRUE AND is_deleted = FALSE "
            "ORDER BY created_at DESC"
        ),
        {"tid": tenant_id, "bt": business_type},
    )
    templates = [dict(r) for r in rows.mappings().fetchall()]

    matched = []
    for t in templates:
        raw_cond = t.get("conditions") or {}
        if isinstance(raw_cond, str):
            raw_cond = json.loads(raw_cond)
        if _eval_template_conditions(raw_cond, ctx):
            matched.append((len(raw_cond), t))

    if not matched:
        return None
    # 选条件最多的（最具体的）
    matched.sort(key=lambda x: x[0], reverse=True)
    return matched[0][1]


async def _get_instance(
    instance_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any] | None:
    row = await db.execute(
        text(
            "SELECT id, tenant_id, template_id, business_type, business_id, "
            "title, initiator_id, current_step, status, context_data, "
            "created_at, updated_at, completed_at "
            "FROM approval_instances "
            "WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE"
        ),
        {"id": instance_id, "tid": tenant_id},
    )
    result = row.mappings().first()
    return dict(result) if result else None


async def _find_approvers_by_role(
    role: str,
    tenant_id: str,
    ctx: dict[str, Any],
    db: AsyncSession,
) -> list[str]:
    """
    按角色查找审批人。优先从 context_data.store_id 限定门店范围。
    无门店时跨租户查。
    """
    store_id = ctx.get("store_id")
    if store_id:
        rows = await db.execute(
            text(
                "SELECT id FROM employees "
                "WHERE tenant_id = :tid AND store_id = :sid "
                "AND role = :role AND is_deleted = FALSE"
            ),
            {"tid": tenant_id, "sid": store_id, "role": role},
        )
    else:
        rows = await db.execute(
            text(
                "SELECT id FROM employees "
                "WHERE tenant_id = :tid AND role = :role AND is_deleted = FALSE"
            ),
            {"tid": tenant_id, "role": role},
        )
    return [str(r[0]) for r in rows.fetchall()]


# ── 业务回调 ──────────────────────────────────────────────────────────────────


async def _dispatch_on_approved(
    business_type: str,
    business_id: str,
    ctx: dict[str, Any],
    tenant_id: str,
) -> None:
    """
    审批通过后按业务类型分发回调。
    各业务服务的 HTTP 调用或事件发布在此实现。
    """
    log.info(
        "approval_on_approved",
        business_type=business_type,
        business_id=business_id,
        tenant_id=tenant_id,
    )
    if business_type == "purchase_order":
        await _post_callback_wf(
            f"{_SUPPLY_URL}/api/v1/purchase-orders/{business_id}/confirm",
            tenant_id, business_id,
        )
    elif business_type == "discount":
        await _post_callback_wf(
            f"{_TRADE_URL}/api/v1/discounts/{business_id}/approve",
            tenant_id, business_id,
        )
    elif business_type == "menu_change":
        await _post_callback_wf(
            f"{_MENU_URL}/api/v1/menu-changes/{business_id}/apply",
            tenant_id, business_id,
        )
    elif business_type == "hr_request":
        await _post_callback_wf(
            f"{_ORG_URL}/api/v1/hr-requests/{business_id}/confirm",
            tenant_id, business_id,
        )
    elif business_type == "expense":
        await _post_callback_wf(
            f"{_FINANCE_URL}/api/v1/expenses/{business_id}/approve",
            tenant_id, business_id,
        )
    elif business_type == "leave":
        await _post_callback_wf(
            f"{_ORG_URL}/api/v1/leave-requests/{business_id}/approve-callback",
            tenant_id, business_id,
        )


async def _dispatch_on_rejected(
    business_type: str,
    business_id: str,
    ctx: dict[str, Any],
    tenant_id: str,
) -> None:
    """审批拒绝后按业务类型分发通知（通常只需通知发起人）。"""
    log.info(
        "approval_on_rejected",
        business_type=business_type,
        business_id=business_id,
        tenant_id=tenant_id,
    )


# ── 核心引擎 ──────────────────────────────────────────────────────────────────


class ApprovalEngine:
    """
    通用审批流引擎。

    所有方法为静态异步方法，通过显式参数接受 tenant_id 和 db。
    不持有实例状态，兼容 FastAPI 依赖注入。
    """

    # ── 发起审批 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def create_instance(
        tenant_id: str,
        business_type: str,
        business_id: str,
        title: str,
        initiator_id: str,
        context_data: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        发起审批：

        1. 查找匹配的审批模板（按 business_type + context_data 条件匹配）
        2. 如无模板，使用默认单级审批（store_manager 审批，24h 超时）
        3. 创建 approval_instances 记录，status='pending', current_step=1
        4. 通知第一步审批人（推送到 manager app）

        Returns:
            新建的审批实例 dict
        """
        if business_type not in VALID_BUSINESS_TYPES:
            raise ValueError(
                f"不支持的业务类型: {business_type}，"
                f"支持: {', '.join(sorted(VALID_BUSINESS_TYPES))}"
            )

        # 1. 匹配模板
        template = await _find_template(tenant_id, business_type, context_data, db)
        template_id = str(template["id"]) if template else None

        # 2. 确定第一步
        if template:
            raw_steps = template.get("steps") or []
            if isinstance(raw_steps, str):
                raw_steps = json.loads(raw_steps)
            applicable = _get_applicable_steps(raw_steps, context_data)
        else:
            applicable = [_DEFAULT_STEP]

        if not applicable:
            raise ValueError("当前上下文没有匹配的审批步骤，请检查模板条件配置")

        first_step = applicable[0]
        ctx_json = json.dumps(context_data, ensure_ascii=False)

        # 3. 写入实例
        result = await db.execute(
            text(
                "INSERT INTO approval_instances "
                "(tenant_id, template_id, business_type, business_id, title, "
                " initiator_id, current_step, status, context_data) "
                "VALUES (:tid, :template_id, :bt, :bid, :title, "
                "        :initiator_id, :current_step, :status, :ctx::jsonb) "
                "RETURNING id, tenant_id, template_id, business_type, business_id, "
                "          title, initiator_id, current_step, status, context_data, "
                "          created_at, updated_at, completed_at"
            ),
            {
                "tid": tenant_id,
                "template_id": template_id,
                "bt": business_type,
                "bid": business_id,
                "title": title,
                "initiator_id": initiator_id,
                "current_step": first_step.get("step", 1),
                "status": STATUS_PENDING,
                "ctx": ctx_json,
            },
        )
        await db.commit()
        instance = dict(result.mappings().first())

        # 4. 通知第一步审批人
        first_role = first_step.get("approver_role", "store_manager")
        approvers = await _find_approvers_by_role(
            role=first_role, tenant_id=tenant_id, ctx=context_data, db=db
        )
        for approver_id in approvers:
            await _notify(
                recipient_id=approver_id,
                title=f"【待审批】{title}",
                body=(
                    f"您有一条新的审批待处理"
                    f"（步骤 {first_step.get('step', 1)}：{first_role}）"
                ),
                meta={
                    "instance_id": str(instance["id"]),
                    "step": first_step.get("step", 1),
                    "business_type": business_type,
                },
            )

        log.info(
            "approval_instance_created",
            instance_id=str(instance["id"]),
            business_type=business_type,
            business_id=business_id,
            tenant_id=tenant_id,
            template_id=template_id,
        )
        return instance

    # ── 审批通过 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def approve(
        instance_id: str,
        approver_id: str,
        comment: str | None,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        审批人通过一步：

        1. 验证实例存在且处于 pending 状态
        2. 记录 approval_step_records（action='approve'）
        3. 如还有下一步：current_step++，通知下一步审批人
        4. 如最后一步：status='approved'，触发 on_approved 回调
        5. 通知发起人结果

        Returns:
            更新后的审批实例 dict
        """
        instance = await _get_instance(instance_id, tenant_id, db)
        if not instance:
            raise ValueError(f"审批实例不存在: {instance_id}")
        if instance["status"] != STATUS_PENDING:
            raise ValueError(f"审批已结束，当前状态: {instance['status']}")

        current_step = instance["current_step"]

        # 写步骤记录
        await db.execute(
            text(
                "INSERT INTO approval_step_records "
                "(tenant_id, instance_id, step, approver_id, action, comment) "
                "VALUES (:tid, :iid, :step, :approver_id, :action, :comment)"
            ),
            {
                "tid": tenant_id,
                "iid": instance_id,
                "step": current_step,
                "approver_id": approver_id,
                "action": ACTION_APPROVE,
                "comment": comment,
            },
        )

        # 取模板步骤
        ctx = instance.get("context_data") or {}
        if isinstance(ctx, str):
            ctx = json.loads(ctx)

        next_step_def: dict[str, Any] | None = None
        template_id = instance.get("template_id")
        if template_id:
            tpl_row = await db.execute(
                text(
                    "SELECT steps FROM approval_workflow_templates "
                    "WHERE id = :tid_tpl AND tenant_id = :tid AND is_deleted = FALSE"
                ),
                {"tid_tpl": str(template_id), "tid": tenant_id},
            )
            tpl = tpl_row.mappings().first()
            if tpl:
                raw_steps = tpl["steps"]
                if isinstance(raw_steps, str):
                    raw_steps = json.loads(raw_steps)
                applicable = _get_applicable_steps(raw_steps, ctx)
                idx = next(
                    (i for i, s in enumerate(applicable) if s.get("step") == current_step),
                    None,
                )
                if idx is not None and idx + 1 < len(applicable):
                    next_step_def = applicable[idx + 1]

        if next_step_def:
            # 流转到下一步
            await db.execute(
                text(
                    "UPDATE approval_instances "
                    "SET current_step = :next_step, updated_at = NOW() "
                    "WHERE id = :iid AND tenant_id = :tid"
                ),
                {
                    "next_step": next_step_def.get("step"),
                    "iid": instance_id,
                    "tid": tenant_id,
                },
            )
            await db.commit()

            next_role = next_step_def.get("approver_role", "store_manager")
            approvers = await _find_approvers_by_role(
                role=next_role, tenant_id=tenant_id, ctx=ctx, db=db
            )
            for aid in approvers:
                await _notify(
                    recipient_id=aid,
                    title=f"【待审批】{instance['title']}",
                    body=(
                        f"审批流转至步骤 {next_step_def.get('step')}（{next_role}），请处理"
                    ),
                    meta={
                        "instance_id": instance_id,
                        "step": next_step_def.get("step"),
                        "business_type": instance["business_type"],
                    },
                )
        else:
            # 最后一步，审批全部通过
            await db.execute(
                text(
                    "UPDATE approval_instances "
                    "SET status = :status, completed_at = NOW(), updated_at = NOW() "
                    "WHERE id = :iid AND tenant_id = :tid"
                ),
                {"status": STATUS_APPROVED, "iid": instance_id, "tid": tenant_id},
            )
            await db.commit()

            # 触发业务回调
            await _dispatch_on_approved(
                business_type=instance["business_type"],
                business_id=str(instance["business_id"]),
                ctx=ctx,
                tenant_id=tenant_id,
            )

            # 通知发起人
            await _notify(
                recipient_id=str(instance["initiator_id"]),
                title=f"【审批通过】{instance['title']}",
                body="您发起的审批已全部通过",
                meta={"instance_id": instance_id},
            )

        log.info(
            "approval_approved",
            instance_id=instance_id,
            approver_id=approver_id,
            step=current_step,
            has_next=next_step_def is not None,
        )
        updated = await _get_instance(instance_id, tenant_id, db)
        return updated or {}

    # ── 拒绝审批 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def reject(
        instance_id: str,
        approver_id: str,
        comment: str | None,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        拒绝：status='rejected'，触发 on_rejected 回调，通知发起人。

        Returns:
            更新后的审批实例 dict
        """
        instance = await _get_instance(instance_id, tenant_id, db)
        if not instance:
            raise ValueError(f"审批实例不存在: {instance_id}")
        if instance["status"] != STATUS_PENDING:
            raise ValueError(f"审批已结束，当前状态: {instance['status']}")

        current_step = instance["current_step"]

        await db.execute(
            text(
                "INSERT INTO approval_step_records "
                "(tenant_id, instance_id, step, approver_id, action, comment) "
                "VALUES (:tid, :iid, :step, :approver_id, :action, :comment)"
            ),
            {
                "tid": tenant_id,
                "iid": instance_id,
                "step": current_step,
                "approver_id": approver_id,
                "action": ACTION_REJECT,
                "comment": comment,
            },
        )

        await db.execute(
            text(
                "UPDATE approval_instances "
                "SET status = :status, completed_at = NOW(), updated_at = NOW() "
                "WHERE id = :iid AND tenant_id = :tid"
            ),
            {"status": STATUS_REJECTED, "iid": instance_id, "tid": tenant_id},
        )
        await db.commit()

        ctx = instance.get("context_data") or {}
        if isinstance(ctx, str):
            ctx = json.loads(ctx)

        await _dispatch_on_rejected(
            business_type=instance["business_type"],
            business_id=str(instance["business_id"]),
            ctx=ctx,
            tenant_id=tenant_id,
        )

        await _notify(
            recipient_id=str(instance["initiator_id"]),
            title=f"【审批拒绝】{instance['title']}",
            body=f"您发起的审批在步骤 {current_step} 被拒绝。原因：{comment or '无'}",
            meta={"instance_id": instance_id, "step": current_step},
        )

        log.info(
            "approval_rejected",
            instance_id=instance_id,
            approver_id=approver_id,
            step=current_step,
        )
        updated = await _get_instance(instance_id, tenant_id, db)
        return updated or {}

    # ── 撤回审批 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def cancel(
        instance_id: str,
        initiator_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        撤回：仅发起人可撤回，且只有 pending 状态可撤。

        Returns:
            更新后的审批实例 dict
        """
        instance = await _get_instance(instance_id, tenant_id, db)
        if not instance:
            raise ValueError(f"审批实例不存在: {instance_id}")
        if str(instance["initiator_id"]) != str(initiator_id):
            raise ValueError("只有发起人可以撤回审批")
        if instance["status"] != STATUS_PENDING:
            raise ValueError(f"只有 pending 状态可撤回，当前状态: {instance['status']}")

        await db.execute(
            text(
                "UPDATE approval_instances "
                "SET status = :status, completed_at = NOW(), updated_at = NOW() "
                "WHERE id = :iid AND tenant_id = :tid"
            ),
            {"status": STATUS_CANCELLED, "iid": instance_id, "tid": tenant_id},
        )
        await db.commit()

        log.info(
            "approval_cancelled",
            instance_id=instance_id,
            initiator_id=initiator_id,
        )
        updated = await _get_instance(instance_id, tenant_id, db)
        return updated or {}

    # ── 超时检查 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def check_timeouts(
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        定时任务：检查所有 pending 实例，对超时的实例：
        - 若模板步骤配置了 timeout_hours，超过则标记 status='timeout'
        - 向发起人和当前审批人发催办通知

        Returns:
            {"checked": int, "timed_out": int}
        """
        rows = await db.execute(
            text(
                "SELECT ai.id, ai.tenant_id, ai.template_id, ai.business_type, "
                "ai.business_id, ai.title, ai.current_step, ai.initiator_id, "
                "ai.context_data, ai.created_at, "
                "awt.steps "
                "FROM approval_instances ai "
                "LEFT JOIN approval_workflow_templates awt ON ai.template_id = awt.id "
                "WHERE ai.tenant_id = :tid AND ai.status = 'pending' "
                "AND ai.is_deleted = FALSE"
            ),
            {"tid": tenant_id},
        )
        pending = rows.mappings().fetchall()

        checked = 0
        timed_out = 0
        now = datetime.now(tz=timezone.utc)

        for row in pending:
            checked += 1
            try:
                ctx = row["context_data"] or {}
                if isinstance(ctx, str):
                    ctx = json.loads(ctx)

                # 确定当前步骤的 timeout_hours
                timeout_hours = 24  # 默认降级值
                raw_steps = row.get("steps")
                if raw_steps:
                    if isinstance(raw_steps, str):
                        raw_steps = json.loads(raw_steps)
                    applicable = _get_applicable_steps(raw_steps, ctx)
                    step_def = next(
                        (s for s in applicable if s.get("step") == row["current_step"]),
                        None,
                    )
                    if step_def:
                        timeout_hours = int(step_def.get("timeout_hours", 24))

                created_at = row["created_at"]
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)

                deadline = created_at + timedelta(hours=timeout_hours)
                if now < deadline:
                    continue

                # 超时：标记状态
                await db.execute(
                    text(
                        "UPDATE approval_instances "
                        "SET status = :status, completed_at = NOW(), updated_at = NOW() "
                        "WHERE id = :iid AND tenant_id = :tid"
                    ),
                    {
                        "status": STATUS_TIMEOUT,
                        "iid": str(row["id"]),
                        "tid": tenant_id,
                    },
                )
                timed_out += 1

                # 通知发起人
                await _notify(
                    recipient_id=str(row["initiator_id"]),
                    title=f"【审批超时】{row['title']}",
                    body=(
                        f"您发起的审批在步骤 {row['current_step']} "
                        f"已超过 {timeout_hours} 小时未处理，已自动超时"
                    ),
                    meta={
                        "instance_id": str(row["id"]),
                        "step": row["current_step"],
                        "business_type": row["business_type"],
                    },
                )

            except (KeyError, ValueError, TypeError) as exc:
                log.warning(
                    "timeout_check_error",
                    instance_id=str(row.get("id")),
                    error=str(exc),
                )

        await db.commit()
        log.info(
            "approval_timeout_check_done",
            tenant_id=tenant_id,
            checked=checked,
            timed_out=timed_out,
        )
        return {"checked": checked, "timed_out": timed_out}
