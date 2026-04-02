"""可配置审批流引擎（v3）

基于 approval_flow_templates + approval_flow_nodes +
     approval_instances + approval_node_instances 四张表（v060 迁移）。

核心能力：
  - 支持 role_level / specific_role / specific_person / auto 四种节点类型
  - 支持 any_one（任一通过）/ all_must（全部通过）多人审批策略
  - 模板级 trigger_conditions：不满足则审批单自动通过，无需人工
  - 节点级 auto_approve_condition：满足时节点自动通过
  - 超时动作：auto_approve / auto_reject / escalate
  - on_approval_complete 按业务类型分发回调（leave/purchase/discount/price_change/refund/expense）
  - 通知失败不阻塞主流程

架构约定：
  - ApprovalEngine 为实例化类，可通过 FastAPI 依赖注入注入
  - 所有 DB 操作通过 AsyncSession，tenant_id 显式传入
  - 禁止 except Exception，精确捕获已知错误类型
  - 全函数 type hints，日志用 structlog JSON 格式
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import UniversalPublisher, OrgEventType

from ..models.approval_flow_engine import (
    eval_condition,
    eval_trigger_conditions,
    NodeRow,
    TemplateRow,
    InstanceRow,
    NodeInstanceRow,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ── 内部状态常量 ──────────────────────────────────────────────────────────────

_STATUS_PENDING = "pending"
_STATUS_APPROVED = "approved"
_STATUS_REJECTED = "rejected"
_STATUS_CANCELLED = "cancelled"
_STATUS_TIMEOUT = "timeout"
_STATUS_SKIPPED = "skipped"

# 系统用户 UUID（自动审批时使用）
_SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"


# ── 通知存根 ──────────────────────────────────────────────────────────────────


async def _send_notification(
    recipient_id: str,
    title: str,
    body: str,
    meta: dict[str, Any],
) -> None:
    """发送审批通知。失败时仅记录日志，不抛出异常（不阻塞主流程）。"""
    try:
        # TODO: 接入消息中心（Redis Streams / PG LISTEN-NOTIFY / WeChat Work API）
        log.info(
            "approval_notification",
            recipient_id=recipient_id,
            title=title,
            body=body,
            meta=meta,
        )
    except (OSError, RuntimeError) as exc:
        log.warning(
            "approval_notification_failed",
            recipient_id=recipient_id,
            error=str(exc),
        )


# ── DB 辅助函数 ───────────────────────────────────────────────────────────────


async def _fetch_template(
    template_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> TemplateRow | None:
    """查询审批流模板（只返回 is_active=TRUE 的）"""
    row = await db.execute(
        text(
            "SELECT id, tenant_id, template_name, business_type, "
            "       trigger_conditions, is_active, created_by, created_at "
            "FROM approval_flow_templates "
            "WHERE id = :id AND tenant_id = :tid AND is_active = TRUE"
        ),
        {"id": template_id, "tid": tenant_id},
    )
    result = row.mappings().first()
    return dict(result) if result else None


async def _fetch_nodes(
    template_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[NodeRow]:
    """查询模板下所有节点，按 node_order 升序"""
    rows = await db.execute(
        text(
            "SELECT id, tenant_id, template_id, node_order, node_name, "
            "       node_type, approver_role_level, approver_role_id, "
            "       approver_employee_id, approve_type, "
            "       auto_approve_condition, timeout_hours, timeout_action, "
            "       created_at "
            "FROM approval_flow_nodes "
            "WHERE template_id = :tmpl_id AND tenant_id = :tid "
            "ORDER BY node_order ASC"
        ),
        {"tmpl_id": template_id, "tid": tenant_id},
    )
    return [dict(r) for r in rows.mappings().fetchall()]


async def _fetch_instance(
    instance_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> InstanceRow | None:
    """查询审批实例（含 v060 新增字段）"""
    row = await db.execute(
        text(
            "SELECT id, tenant_id, flow_template_id, "
            "       business_type, business_id, title, initiator_id, "
            "       store_id, current_node_order, status, summary, "
            "       context_data, created_at, updated_at, completed_at "
            "FROM approval_instances "
            "WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE"
        ),
        {"id": instance_id, "tid": tenant_id},
    )
    result = row.mappings().first()
    return dict(result) if result else None


async def _fetch_node_instances(
    instance_id: str,
    node_order: int,
    tenant_id: str,
    db: AsyncSession,
) -> list[NodeInstanceRow]:
    """查询某节点的所有审批记录"""
    rows = await db.execute(
        text(
            "SELECT id, tenant_id, instance_id, node_order, "
            "       approver_id, status, comment, decided_at, created_at "
            "FROM approval_node_instances "
            "WHERE instance_id = :iid AND node_order = :node_order "
            "AND tenant_id = :tid"
        ),
        {"iid": instance_id, "node_order": node_order, "tid": tenant_id},
    )
    return [dict(r) for r in rows.mappings().fetchall()]


async def _find_approvers_by_role_level(
    store_id: str,
    min_level: int,
    tenant_id: str,
    db: AsyncSession,
) -> list[str]:
    """查找门店内角色等级 >= min_level 的员工 ID 列表（按等级升序，取最低满足等级）"""
    rows = await db.execute(
        text(
            "SELECT e.id FROM employees e "
            "JOIN role_configs rc "
            "    ON rc.tenant_id = e.tenant_id AND rc.role_code = e.role "
            "WHERE e.tenant_id = :tid AND e.store_id = :sid "
            "AND rc.role_level >= :min_level "
            "AND e.is_deleted = FALSE "
            "ORDER BY rc.role_level ASC"
        ),
        {"tid": tenant_id, "sid": store_id, "min_level": min_level},
    )
    return [str(r[0]) for r in rows.fetchall()]


async def _find_approvers_by_role_id(
    store_id: str,
    role_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[str]:
    """查找门店内持有指定角色配置的员工 ID 列表"""
    rows = await db.execute(
        text(
            "SELECT e.id FROM employees e "
            "JOIN role_configs rc "
            "    ON rc.id = :role_id "
            "    AND rc.tenant_id = e.tenant_id "
            "    AND rc.role_code = e.role "
            "WHERE e.tenant_id = :tid AND e.store_id = :sid "
            "AND e.is_deleted = FALSE"
        ),
        {"tid": tenant_id, "sid": store_id, "role_id": role_id},
    )
    return [str(r[0]) for r in rows.fetchall()]


async def _find_approvers_for_node(
    node: NodeRow,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[str]:
    """根据节点配置找到实际审批人 ID 列表"""
    node_type: str = node["node_type"]

    if node_type == "role_level":
        min_level: int = int(node.get("approver_role_level") or 1)
        return await _find_approvers_by_role_level(store_id, min_level, tenant_id, db)

    if node_type == "specific_role":
        role_id = str(node["approver_role_id"])
        return await _find_approvers_by_role_id(store_id, role_id, tenant_id, db)

    if node_type == "specific_person":
        emp_id = node.get("approver_employee_id")
        return [str(emp_id)] if emp_id else []

    # node_type == "auto"：无需审批人
    return []


def _parse_jsonb(value: Any) -> dict[str, Any]:
    """将 DB 返回的 JSONB（可能是 str/dict/None）统一解析为 dict"""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return {}


# ── 业务回调 ──────────────────────────────────────────────────────────────────


_SUPPLY_URL = os.getenv("TX_SUPPLY_SERVICE_URL", "http://tx-supply:8001")
_TRADE_URL = os.getenv("TX_TRADE_SERVICE_URL", "http://tx-trade:8002")
_MENU_URL = os.getenv("TX_MENU_SERVICE_URL", "http://tx-menu:8003")
_FINANCE_URL = os.getenv("TX_FINANCE_SERVICE_URL", "http://tx-finance:8004")
_ORG_URL = os.getenv("TX_ORG_SERVICE_URL", "http://tx-org:8005")


async def _post_callback(url: str, tenant_id: str, business_id: str) -> None:
    """向下游服务发送审批通过回调，失败只记日志不抛异常。"""
    headers = {"X-Tenant-ID": tenant_id, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, headers=headers)
            if resp.status_code >= 400:
                log.warning(
                    "approval_callback_http_error",
                    url=url,
                    status_code=resp.status_code,
                    business_id=business_id,
                )
            else:
                log.info("approval_callback_ok", url=url, business_id=business_id)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        log.warning("approval_callback_failed", url=url, business_id=business_id, error=str(exc))


async def _dispatch_on_approved(
    business_type: str,
    business_id: str,
    summary: dict[str, Any],
    tenant_id: str,
) -> None:
    """审批通过后按业务类型分发回调（HTTP 调用 / 事件发布）。"""
    log.info(
        "approval_on_approved",
        business_type=business_type,
        business_id=business_id,
        tenant_id=tenant_id,
    )
    if business_type == "leave":
        await _post_callback(
            f"{_ORG_URL}/api/v1/leave-requests/{business_id}/confirm",
            tenant_id, business_id,
        )
    elif business_type == "purchase":
        await _post_callback(
            f"{_SUPPLY_URL}/api/v1/purchase-orders/{business_id}/confirm",
            tenant_id, business_id,
        )
    elif business_type == "discount":
        await _post_callback(
            f"{_TRADE_URL}/api/v1/discounts/{business_id}/approve",
            tenant_id, business_id,
        )
    elif business_type == "price_change":
        await _post_callback(
            f"{_MENU_URL}/api/v1/menu-changes/{business_id}/apply",
            tenant_id, business_id,
        )
    elif business_type == "refund":
        await _post_callback(
            f"{_TRADE_URL}/api/v1/refunds/{business_id}/approve",
            tenant_id, business_id,
        )
    elif business_type == "expense":
        await _post_callback(
            f"{_FINANCE_URL}/api/v1/expenses/{business_id}/approve",
            tenant_id, business_id,
        )
    # custom 类型无标准回调


async def _dispatch_on_rejected(
    business_type: str,
    business_id: str,
    tenant_id: str,
) -> None:
    """审批拒绝后通知，各业务服务自行订阅事件。"""
    log.info(
        "approval_on_rejected",
        business_type=business_type,
        business_id=business_id,
        tenant_id=tenant_id,
    )


# ── 核心引擎 ──────────────────────────────────────────────────────────────────


class ApprovalEngine:
    """
    可配置审批流引擎。

    支持：
      - role_level / specific_role / specific_person / auto 四种节点类型
      - any_one（任一通过）/ all_must（全部通过）多人审批策略
      - 模板级触发条件（不满足则自动通过，无需人工审批）
      - 节点级自动审批条件（满足时跳过人工，直接通过该节点）
      - 超时动作（auto_approve / auto_reject / escalate）

    用法（FastAPI 依赖注入）：
        engine = ApprovalEngine()
        instance = await engine.create_instance(...)
    """

    # ── 创建审批实例 ──────────────────────────────────────────────────────────

    async def create_instance(
        self,
        template_id: str,
        business_type: str,
        business_id: str,
        initiator_id: str,
        store_id: str,
        title: str,
        summary: dict[str, Any],
        tenant_id: str,
        db: AsyncSession,
    ) -> InstanceRow:
        """
        发起审批：
        1. 验证模板存在且有效
        2. 检查触发条件（不满足 → 直接创建已通过实例，无需人工）
        3. 创建 approval_instances 记录（status=pending）
        4. 激活第一个节点（创建 node_instances + 发通知）

        Returns:
            新建的审批实例 dict
        Raises:
            ValueError: 模板不存在、无节点配置等业务错误
        """
        template = await _fetch_template(template_id, tenant_id, db)
        if not template:
            raise ValueError(f"审批流模板不存在或已停用: {template_id}")

        trigger_cond = _parse_jsonb(template.get("trigger_conditions"))

        # 触发条件不满足 → 自动通过，无需人工审批
        if not eval_trigger_conditions(trigger_cond, summary):
            return await self._create_auto_approved_instance(
                template_id=template_id,
                business_type=business_type,
                business_id=business_id,
                initiator_id=initiator_id,
                store_id=store_id,
                title=title,
                summary=summary,
                tenant_id=tenant_id,
                db=db,
            )

        # 加载节点
        nodes = await _fetch_nodes(template_id, tenant_id, db)
        if not nodes:
            raise ValueError(f"审批流模板没有配置节点，请先添加审批节点: {template_id}")

        summary_json = json.dumps(summary, ensure_ascii=False)

        result = await db.execute(
            text(
                "INSERT INTO approval_instances "
                "(tenant_id, flow_template_id, business_type, business_id, "
                " title, initiator_id, store_id, current_node_order, status, "
                " summary, context_data) "
                "VALUES (:tid, :tmpl_id, :bt, :bid, :title, :initiator_id, "
                "        :store_id, :node_order, :status, "
                "        :summary::jsonb, :summary::jsonb) "
                "RETURNING id, tenant_id, flow_template_id, business_type, "
                "          business_id, title, initiator_id, store_id, "
                "          current_node_order, status, summary, created_at, updated_at"
            ),
            {
                "tid": tenant_id,
                "tmpl_id": template_id,
                "bt": business_type,
                "bid": business_id,
                "title": title,
                "initiator_id": initiator_id,
                "store_id": store_id,
                "node_order": nodes[0]["node_order"],
                "status": _STATUS_PENDING,
                "summary": summary_json,
            },
        )
        await db.commit()
        instance = dict(result.mappings().first())
        instance_id = str(instance["id"])

        # 激活第一节点
        await self._activate_node(
            instance_id=instance_id,
            node=nodes[0],
            store_id=store_id,
            title=title,
            summary=summary,
            tenant_id=tenant_id,
            db=db,
        )

        log.info(
            "approval_instance_created",
            instance_id=instance_id,
            template_id=template_id,
            business_type=business_type,
            tenant_id=tenant_id,
        )
        return await _fetch_instance(instance_id, tenant_id, db) or instance

    # ── 激活节点（内部）──────────────────────────────────────────────────────

    async def _activate_node(
        self,
        instance_id: str,
        node: NodeRow,
        store_id: str,
        title: str,
        summary: dict[str, Any],
        tenant_id: str,
        db: AsyncSession,
    ) -> None:
        """
        激活指定节点：
        1. auto 节点 → 直接自动通过
        2. 检查节点级 auto_approve_condition → 满足则自动通过
        3. 查找审批人 → 创建 node_instance 记录 → 发通知
        4. 无审批人时自动通过（避免卡死）
        """
        node_order: int = node["node_order"]
        node_type: str = node["node_type"]

        # auto 节点
        if node_type == "auto":
            await self._auto_approve_node(
                instance_id=instance_id,
                node=node,
                tenant_id=tenant_id,
                db=db,
            )
            return

        # 节点级自动审批条件
        auto_cond_raw = node.get("auto_approve_condition")
        if auto_cond_raw:
            auto_cond = _parse_jsonb(auto_cond_raw)
            if eval_condition(auto_cond, summary):
                await self._auto_approve_node(
                    instance_id=instance_id,
                    node=node,
                    tenant_id=tenant_id,
                    db=db,
                )
                return

        # 查找审批人
        approvers = await _find_approvers_for_node(node, store_id, tenant_id, db)
        if not approvers:
            log.warning(
                "approval_no_approvers_found_auto_approve",
                instance_id=instance_id,
                node_order=node_order,
                node_type=node_type,
                tenant_id=tenant_id,
            )
            # 无审批人时自动通过，避免卡死
            await self._auto_approve_node(
                instance_id=instance_id,
                node=node,
                tenant_id=tenant_id,
                db=db,
            )
            return

        # 创建各审批人的 node_instance 记录
        for approver_id in approvers:
            await db.execute(
                text(
                    "INSERT INTO approval_node_instances "
                    "(tenant_id, instance_id, node_order, approver_id, status) "
                    "VALUES (:tid, :iid, :node_order, :approver_id, :status)"
                ),
                {
                    "tid": tenant_id,
                    "iid": instance_id,
                    "node_order": node_order,
                    "approver_id": approver_id,
                    "status": _STATUS_PENDING,
                },
            )
            await _send_notification(
                recipient_id=approver_id,
                title=f"【待审批】{title}",
                body=(
                    f"您有一条新的审批待处理"
                    f"（节点 {node_order}：{node['node_name']}）"
                ),
                meta={
                    "instance_id": instance_id,
                    "node_order": node_order,
                    "node_name": node["node_name"],
                },
            )

        await db.commit()

    # ── 自动通过节点（内部）──────────────────────────────────────────────────

    async def _auto_approve_node(
        self,
        instance_id: str,
        node: NodeRow,
        tenant_id: str,
        db: AsyncSession,
    ) -> None:
        """自动通过节点，写系统审批记录，然后推进到下一节点或完成。"""
        node_order: int = node["node_order"]

        await db.execute(
            text(
                "INSERT INTO approval_node_instances "
                "(tenant_id, instance_id, node_order, approver_id, "
                " status, comment, decided_at) "
                "VALUES (:tid, :iid, :node_order, :approver_id, "
                "        :status, :comment, NOW())"
            ),
            {
                "tid": tenant_id,
                "iid": instance_id,
                "node_order": node_order,
                "approver_id": _SYSTEM_USER_ID,
                "status": _STATUS_APPROVED,
                "comment": "系统自动审批通过",
            },
        )
        await db.commit()

        await self._advance_instance(
            instance_id=instance_id,
            current_node_order=node_order,
            tenant_id=tenant_id,
            db=db,
        )

    # ── 推进实例到下一节点（内部）────────────────────────────────────────────

    async def _advance_instance(
        self,
        instance_id: str,
        current_node_order: int,
        tenant_id: str,
        db: AsyncSession,
    ) -> None:
        """
        当前节点完成后推进流程：
        - 有下一节点 → 更新 current_node_order，激活下一节点
        - 无下一节点 → 标记整体 approved，触发回调，通知发起人
        """
        instance = await _fetch_instance(instance_id, tenant_id, db)
        if not instance:
            return

        template_id = str(instance.get("flow_template_id") or "")
        nodes = await _fetch_nodes(template_id, tenant_id, db) if template_id else []

        next_node: NodeRow | None = None
        for node in nodes:
            if int(node["node_order"]) > current_node_order:
                next_node = node
                break

        if next_node:
            await db.execute(
                text(
                    "UPDATE approval_instances "
                    "SET current_node_order = :node_order, updated_at = NOW() "
                    "WHERE id = :iid AND tenant_id = :tid"
                ),
                {
                    "node_order": next_node["node_order"],
                    "iid": instance_id,
                    "tid": tenant_id,
                },
            )
            await db.commit()

            store_id = str(instance.get("store_id") or "")
            summary = _parse_jsonb(instance.get("summary"))
            title = str(instance.get("title") or "")

            await self._activate_node(
                instance_id=instance_id,
                node=next_node,
                store_id=store_id,
                title=title,
                summary=summary,
                tenant_id=tenant_id,
                db=db,
            )
        else:
            # 所有节点完成，审批整体通过
            await db.execute(
                text(
                    "UPDATE approval_instances "
                    "SET status = :status, completed_at = NOW(), updated_at = NOW() "
                    "WHERE id = :iid AND tenant_id = :tid"
                ),
                {"status": _STATUS_APPROVED, "iid": instance_id, "tid": tenant_id},
            )
            await db.commit()

            await _dispatch_on_approved(
                business_type=str(instance.get("business_type") or ""),
                business_id=str(instance.get("business_id") or ""),
                summary=_parse_jsonb(instance.get("summary")),
                tenant_id=tenant_id,
            )
            await _send_notification(
                recipient_id=str(instance.get("initiator_id") or ""),
                title=f"【审批通过】{instance.get('title')}",
                body="您发起的审批已全部通过",
                meta={"instance_id": instance_id},
            )
            log.info(
                "approval_instance_completed",
                instance_id=instance_id,
                status=_STATUS_APPROVED,
                tenant_id=tenant_id,
            )
            asyncio.create_task(UniversalPublisher.publish(
                event_type=OrgEventType.APPROVAL_COMPLETED,
                tenant_id=tenant_id,
                store_id=instance.get("store_id"),
                entity_id=instance_id,
                event_data={"instance_id": instance_id, "business_type": str(instance.get("business_type") or ""), "result": _STATUS_APPROVED},
                source_service="tx-org",
            ))

    # ── 创建自动通过实例（触发条件不满足时）────────────────────────────────────

    async def _create_auto_approved_instance(
        self,
        template_id: str,
        business_type: str,
        business_id: str,
        initiator_id: str,
        store_id: str,
        title: str,
        summary: dict[str, Any],
        tenant_id: str,
        db: AsyncSession,
    ) -> InstanceRow:
        """触发条件不满足，直接创建状态为 approved 的实例，无需人工审批。"""
        summary_json = json.dumps(summary, ensure_ascii=False)
        result = await db.execute(
            text(
                "INSERT INTO approval_instances "
                "(tenant_id, flow_template_id, business_type, business_id, "
                " title, initiator_id, store_id, current_node_order, status, "
                " summary, context_data, completed_at) "
                "VALUES (:tid, :tmpl_id, :bt, :bid, :title, :initiator_id, "
                "        :store_id, 0, :status, "
                "        :summary::jsonb, :summary::jsonb, NOW()) "
                "RETURNING id, status, created_at"
            ),
            {
                "tid": tenant_id,
                "tmpl_id": template_id,
                "bt": business_type,
                "bid": business_id,
                "title": title,
                "initiator_id": initiator_id,
                "store_id": store_id,
                "status": _STATUS_APPROVED,
                "summary": summary_json,
            },
        )
        await db.commit()
        row = dict(result.mappings().first())
        instance_id = str(row["id"])

        log.info(
            "approval_auto_approved_trigger_not_met",
            instance_id=instance_id,
            template_id=template_id,
            tenant_id=tenant_id,
        )
        return await _fetch_instance(instance_id, tenant_id, db) or row

    # ── 审批同意 ──────────────────────────────────────────────────────────────

    async def approve(
        self,
        instance_id: str,
        node_order: int,
        approver_id: str,
        comment: str | None,
        tenant_id: str,
        db: AsyncSession,
    ) -> InstanceRow:
        """
        审批人同意：
        1. 验证实例状态 = pending，当前节点序号匹配
        2. 验证审批人在节点审批人列表中且状态为 pending
        3. 更新 node_instance.status = 'approved'
        4. 判断节点是否完成（any_one / all_must 策略）
        5. 节点完成后推进到下一节点或完成整体审批
           - any_one：同节点其他人标记为 skipped

        Returns:
            更新后的审批实例 dict
        Raises:
            ValueError: 实例不存在、状态不对、审批人不在列表等
        """
        instance = await _fetch_instance(instance_id, tenant_id, db)
        if not instance:
            raise ValueError(f"审批实例不存在: {instance_id}")
        if instance["status"] != _STATUS_PENDING:
            raise ValueError(f"审批已结束，当前状态: {instance['status']}")

        current_node_order: int = int(instance.get("current_node_order") or 1)
        if current_node_order != node_order:
            raise ValueError(
                f"当前节点为 {current_node_order}，不能处理节点 {node_order}"
            )

        node_instances = await _fetch_node_instances(instance_id, node_order, tenant_id, db)
        my_record = next(
            (ni for ni in node_instances if str(ni["approver_id"]) == approver_id),
            None,
        )
        if not my_record:
            raise ValueError(
                f"审批人 {approver_id} 不在节点 {node_order} 的审批人列表中"
            )
        if my_record["status"] != _STATUS_PENDING:
            raise ValueError(
                f"该审批人已处理此节点，当前状态: {my_record['status']}"
            )

        # 更新 node_instance
        await db.execute(
            text(
                "UPDATE approval_node_instances "
                "SET status = :status, comment = :comment, decided_at = NOW() "
                "WHERE id = :id AND tenant_id = :tid"
            ),
            {
                "status": _STATUS_APPROVED,
                "comment": comment,
                "id": str(my_record["id"]),
                "tid": tenant_id,
            },
        )
        await db.commit()

        # 获取节点配置以判断 approve_type
        template_id = str(instance.get("flow_template_id") or "")
        nodes = await _fetch_nodes(template_id, tenant_id, db) if template_id else []
        current_node = next((n for n in nodes if int(n["node_order"]) == node_order), None)
        approve_type: str = current_node["approve_type"] if current_node else "any_one"

        node_complete = await self._is_node_complete(
            instance_id=instance_id,
            node_order=node_order,
            approve_type=approve_type,
            tenant_id=tenant_id,
            db=db,
        )

        if node_complete:
            # any_one：将同节点其他 pending 记录标记为 skipped
            if approve_type == "any_one":
                await db.execute(
                    text(
                        "UPDATE approval_node_instances "
                        "SET status = :skipped, decided_at = NOW() "
                        "WHERE instance_id = :iid AND node_order = :node_order "
                        "AND tenant_id = :tid AND status = :pending"
                    ),
                    {
                        "skipped": _STATUS_SKIPPED,
                        "iid": instance_id,
                        "node_order": node_order,
                        "tid": tenant_id,
                        "pending": _STATUS_PENDING,
                    },
                )
                await db.commit()

            log.info(
                "approval_node_completed",
                instance_id=instance_id,
                node_order=node_order,
                approve_type=approve_type,
                tenant_id=tenant_id,
            )
            await self._advance_instance(
                instance_id=instance_id,
                current_node_order=node_order,
                tenant_id=tenant_id,
                db=db,
            )

        return await _fetch_instance(instance_id, tenant_id, db) or instance

    # ── 判断节点是否完成（内部）──────────────────────────────────────────────

    async def _is_node_complete(
        self,
        instance_id: str,
        node_order: int,
        approve_type: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> bool:
        """
        判断节点是否已满足完成条件：
        - any_one：只要有一人 approved 即完成
        - all_must：所有非 skipped 记录都 approved 才完成
        """
        node_instances = await _fetch_node_instances(instance_id, node_order, tenant_id, db)

        if approve_type == "any_one":
            return any(ni["status"] == _STATUS_APPROVED for ni in node_instances)

        # all_must
        active = [ni for ni in node_instances if ni["status"] != _STATUS_SKIPPED]
        if not active:
            return True
        return all(ni["status"] == _STATUS_APPROVED for ni in active)

    # ── 审批拒绝 ──────────────────────────────────────────────────────────────

    async def reject(
        self,
        instance_id: str,
        node_order: int,
        approver_id: str,
        comment: str | None,
        tenant_id: str,
        db: AsyncSession,
    ) -> InstanceRow:
        """
        审批人拒绝：整个审批单立即拒绝（不等其他人），
        同节点其他待审批记录标记为 skipped。

        Returns:
            更新后的审批实例 dict
        Raises:
            ValueError: 实例不存在、状态不对、审批人不在列表等
        """
        instance = await _fetch_instance(instance_id, tenant_id, db)
        if not instance:
            raise ValueError(f"审批实例不存在: {instance_id}")
        if instance["status"] != _STATUS_PENDING:
            raise ValueError(f"审批已结束，当前状态: {instance['status']}")

        current_node_order: int = int(instance.get("current_node_order") or 1)
        if current_node_order != node_order:
            raise ValueError(
                f"当前节点为 {current_node_order}，不能处理节点 {node_order}"
            )

        node_instances = await _fetch_node_instances(instance_id, node_order, tenant_id, db)
        my_record = next(
            (ni for ni in node_instances if str(ni["approver_id"]) == approver_id),
            None,
        )
        if not my_record:
            raise ValueError(
                f"审批人 {approver_id} 不在节点 {node_order} 的审批人列表中"
            )
        if my_record["status"] != _STATUS_PENDING:
            raise ValueError(
                f"该审批人已处理此节点，当前状态: {my_record['status']}"
            )

        # 更新拒绝记录
        await db.execute(
            text(
                "UPDATE approval_node_instances "
                "SET status = :status, comment = :comment, decided_at = NOW() "
                "WHERE id = :id AND tenant_id = :tid"
            ),
            {
                "status": _STATUS_REJECTED,
                "comment": comment,
                "id": str(my_record["id"]),
                "tid": tenant_id,
            },
        )

        # 同节点其他 pending → skipped
        await db.execute(
            text(
                "UPDATE approval_node_instances "
                "SET status = :skipped, decided_at = NOW() "
                "WHERE instance_id = :iid AND node_order = :node_order "
                "AND tenant_id = :tid AND status = :pending"
            ),
            {
                "skipped": _STATUS_SKIPPED,
                "iid": instance_id,
                "node_order": node_order,
                "tid": tenant_id,
                "pending": _STATUS_PENDING,
            },
        )

        # 整体实例标记为 rejected
        await db.execute(
            text(
                "UPDATE approval_instances "
                "SET status = :status, completed_at = NOW(), updated_at = NOW() "
                "WHERE id = :iid AND tenant_id = :tid"
            ),
            {"status": _STATUS_REJECTED, "iid": instance_id, "tid": tenant_id},
        )
        await db.commit()

        await _dispatch_on_rejected(
            business_type=str(instance.get("business_type") or ""),
            business_id=str(instance.get("business_id") or ""),
            tenant_id=tenant_id,
        )
        await _send_notification(
            recipient_id=str(instance.get("initiator_id") or ""),
            title=f"【审批拒绝】{instance.get('title')}",
            body=f"您发起的审批在节点 {node_order} 被拒绝。原因：{comment or '无'}",
            meta={"instance_id": instance_id, "node_order": node_order},
        )

        log.info(
            "approval_rejected",
            instance_id=instance_id,
            approver_id=approver_id,
            node_order=node_order,
            tenant_id=tenant_id,
        )
        asyncio.create_task(UniversalPublisher.publish(
            event_type=OrgEventType.APPROVAL_COMPLETED,
            tenant_id=tenant_id,
            store_id=instance.get("store_id"),
            entity_id=instance_id,
            event_data={"instance_id": instance_id, "business_type": str(instance.get("business_type") or ""), "result": _STATUS_REJECTED},
            source_service="tx-org",
        ))
        return await _fetch_instance(instance_id, tenant_id, db) or instance

    # ── 撤回审批 ──────────────────────────────────────────────────────────────

    async def cancel(
        self,
        instance_id: str,
        initiator_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> InstanceRow:
        """
        撤回：仅发起人可撤回，且只有 pending 状态可撤。
        将当前节点所有 pending 记录标记为 skipped。

        Returns:
            更新后的审批实例 dict
        Raises:
            ValueError: 不是发起人、非 pending 状态
        """
        instance = await _fetch_instance(instance_id, tenant_id, db)
        if not instance:
            raise ValueError(f"审批实例不存在: {instance_id}")
        if str(instance.get("initiator_id") or "") != initiator_id:
            raise ValueError("只有发起人可以撤回审批")
        if instance["status"] != _STATUS_PENDING:
            raise ValueError(f"只有 pending 状态可撤回，当前状态: {instance['status']}")

        current_node_order: int = int(instance.get("current_node_order") or 1)

        # 当前节点所有 pending 记录 → skipped
        await db.execute(
            text(
                "UPDATE approval_node_instances "
                "SET status = :skipped, decided_at = NOW() "
                "WHERE instance_id = :iid AND node_order = :node_order "
                "AND tenant_id = :tid AND status = :pending"
            ),
            {
                "skipped": _STATUS_SKIPPED,
                "iid": instance_id,
                "node_order": current_node_order,
                "tid": tenant_id,
                "pending": _STATUS_PENDING,
            },
        )
        await db.execute(
            text(
                "UPDATE approval_instances "
                "SET status = :status, completed_at = NOW(), updated_at = NOW() "
                "WHERE id = :iid AND tenant_id = :tid"
            ),
            {"status": _STATUS_CANCELLED, "iid": instance_id, "tid": tenant_id},
        )
        await db.commit()

        log.info(
            "approval_cancelled",
            instance_id=instance_id,
            initiator_id=initiator_id,
            tenant_id=tenant_id,
        )
        return await _fetch_instance(instance_id, tenant_id, db) or instance

    # ── 超时检查（定时任务）──────────────────────────────────────────────────

    async def check_timeouts(
        self,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        定时任务：检查所有 pending 实例，对超时的节点执行 timeout_action。

        超时判定：实例 created_at + 当前节点 timeout_hours < now

        timeout_action 行为：
          - auto_approve：当前节点自动通过，推进到下一节点
          - auto_reject：整体标记为 timeout 拒绝
          - escalate：仅发催办通知，不修改状态

        Returns:
            {"checked": int, "timed_out": int, "auto_approved": int, "auto_rejected": int}
        """
        rows = await db.execute(
            text(
                "SELECT id, tenant_id, flow_template_id, "
                "       business_type, business_id, title, "
                "       current_node_order, initiator_id, store_id, "
                "       summary, created_at "
                "FROM approval_instances "
                "WHERE tenant_id = :tid AND status = :status "
                "AND is_deleted = FALSE "
                "AND flow_template_id IS NOT NULL"
            ),
            {"tid": tenant_id, "status": _STATUS_PENDING},
        )
        pending_instances = rows.mappings().fetchall()

        checked = 0
        timed_out = 0
        auto_approved = 0
        auto_rejected = 0
        now = datetime.now(tz=timezone.utc)

        for row in pending_instances:
            checked += 1
            try:
                instance_id = str(row["id"])
                template_id = str(row["flow_template_id"])
                current_node_order = int(row["current_node_order"] or 1)

                nodes = await _fetch_nodes(template_id, tenant_id, db)
                current_node = next(
                    (n for n in nodes if int(n["node_order"]) == current_node_order),
                    None,
                )
                if not current_node:
                    continue

                timeout_hours = current_node.get("timeout_hours")
                if timeout_hours is None:
                    continue  # 该节点不超时

                created_at: datetime = row["created_at"]
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)

                deadline = created_at + timedelta(hours=int(timeout_hours))
                if now < deadline:
                    continue

                timed_out += 1
                timeout_action: str = current_node.get("timeout_action") or "escalate"

                if timeout_action == "auto_approve":
                    # 当前节点超时记录 → timeout，推进
                    await db.execute(
                        text(
                            "UPDATE approval_node_instances "
                            "SET status = :status, decided_at = NOW() "
                            "WHERE instance_id = :iid AND node_order = :node_order "
                            "AND tenant_id = :tid AND status = :pending"
                        ),
                        {
                            "status": _STATUS_TIMEOUT,
                            "iid": instance_id,
                            "node_order": current_node_order,
                            "tid": tenant_id,
                            "pending": _STATUS_PENDING,
                        },
                    )
                    await db.commit()
                    await self._advance_instance(
                        instance_id=instance_id,
                        current_node_order=current_node_order,
                        tenant_id=tenant_id,
                        db=db,
                    )
                    auto_approved += 1

                elif timeout_action == "auto_reject":
                    await db.execute(
                        text(
                            "UPDATE approval_node_instances "
                            "SET status = :status, decided_at = NOW() "
                            "WHERE instance_id = :iid AND node_order = :node_order "
                            "AND tenant_id = :tid AND status = :pending"
                        ),
                        {
                            "status": _STATUS_TIMEOUT,
                            "iid": instance_id,
                            "node_order": current_node_order,
                            "tid": tenant_id,
                            "pending": _STATUS_PENDING,
                        },
                    )
                    await db.execute(
                        text(
                            "UPDATE approval_instances "
                            "SET status = :status, completed_at = NOW(), "
                            "    updated_at = NOW() "
                            "WHERE id = :iid AND tenant_id = :tid"
                        ),
                        {
                            "status": _STATUS_TIMEOUT,
                            "iid": instance_id,
                            "tid": tenant_id,
                        },
                    )
                    await db.commit()
                    auto_rejected += 1
                    await _send_notification(
                        recipient_id=str(row["initiator_id"]),
                        title=f"【审批超时】{row['title']}",
                        body=(
                            f"您发起的审批在节点 {current_node_order} "
                            f"（{current_node['node_name']}）已超过 "
                            f"{timeout_hours} 小时未处理，已自动超时拒绝"
                        ),
                        meta={
                            "instance_id": instance_id,
                            "node_order": current_node_order,
                        },
                    )

                else:  # escalate — 仅催办，不改状态
                    store_id = str(row.get("store_id") or "")
                    approvers = await _find_approvers_for_node(
                        current_node, store_id, tenant_id, db
                    )
                    for approver_id in approvers:
                        await _send_notification(
                            recipient_id=approver_id,
                            title=f"【催办提醒】{row['title']}",
                            body=(
                                f"审批节点 {current_node_order}"
                                f"（{current_node['node_name']}）"
                                f"已超过 {timeout_hours} 小时未处理，请尽快审批"
                            ),
                            meta={
                                "instance_id": instance_id,
                                "node_order": current_node_order,
                            },
                        )

            except (KeyError, ValueError, TypeError) as exc:
                log.warning(
                    "approval_timeout_check_error",
                    instance_id=str(row.get("id")),
                    error=str(exc),
                    tenant_id=tenant_id,
                )

        await db.commit()
        log.info(
            "approval_timeout_check_done",
            tenant_id=tenant_id,
            checked=checked,
            timed_out=timed_out,
            auto_approved=auto_approved,
            auto_rejected=auto_rejected,
        )
        return {
            "checked": checked,
            "timed_out": timed_out,
            "auto_approved": auto_approved,
            "auto_rejected": auto_rejected,
        }

    # ── 模板详情查询（含节点列表）────────────────────────────────────────────

    async def get_template_with_nodes(
        self,
        template_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """查询审批流模板详情（含节点列表）"""
        row = await db.execute(
            text(
                "SELECT id, tenant_id, template_name, business_type, "
                "       trigger_conditions, is_active, created_by, "
                "       created_at, updated_at "
                "FROM approval_flow_templates "
                "WHERE id = :id AND tenant_id = :tid"
            ),
            {"id": template_id, "tid": tenant_id},
        )
        template = row.mappings().first()
        if not template:
            raise ValueError(f"模板不存在: {template_id}")
        template_dict = dict(template)
        template_dict["nodes"] = await _fetch_nodes(template_id, tenant_id, db)
        return template_dict
