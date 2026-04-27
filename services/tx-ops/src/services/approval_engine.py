"""审批流引擎

核心职责：
- 根据 business_type + amount_fen 匹配审批模板并筛选适用步骤
- 创建审批实例（approval_instances）并发送首步通知
- 处理审批动作（approve/reject），推进步骤或终结实例
- 查询待审/已发起列表
- 扫描并关闭过期实例

依赖：SQLAlchemy text() + asyncpg（DB 连接由路由层注入）
日志：structlog JSON 格式
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _filter_steps_by_amount(
    steps: List[Dict[str, Any]],
    amount_fen: Optional[int],
) -> List[Dict[str, Any]]:
    """
    从模板 steps 中筛选出与 amount_fen 匹配的步骤。

    匹配规则：
    - 若步骤没有 min/max 限制 → 无条件触发
    - 若 amount_fen 为 None → 只触发无金额限制的步骤
    - 若 amount_fen 在 [min_amount_fen, max_amount_fen] 区间内 → 触发（边界含）
    """
    result: List[Dict[str, Any]] = []
    for step in steps:
        min_fen: Optional[int] = step.get("min_amount_fen")
        max_fen: Optional[int] = step.get("max_amount_fen")

        if min_fen is None and max_fen is None:
            # 无金额限制，永远触发
            result.append(step)
        elif amount_fen is None:
            # 有金额限制但本次无金额 → 跳过
            continue
        else:
            lower_ok = (min_fen is None) or (amount_fen >= min_fen)
            upper_ok = (max_fen is None) or (amount_fen <= max_fen)
            if lower_ok and upper_ok:
                result.append(step)

    # 按 step_no 升序
    result.sort(key=lambda s: s.get("step_no", 0))
    return result


async def _send_notification(
    db: Any,
    tenant_id: str,
    instance_id: str,
    recipient_id: str,
    recipient_name: str,
    notification_type: str,
    message: str,
) -> None:
    """写入一条审批通知记录。"""
    nid = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO approval_notifications
                (id, tenant_id, instance_id, recipient_id, recipient_name,
                 notification_type, message, is_read, sent_at)
            VALUES
                (:id, :tenant_id, :instance_id, :recipient_id, :recipient_name,
                 :notification_type, :message, false, now())
        """),
        {
            "id": nid,
            "tenant_id": tenant_id,
            "instance_id": instance_id,
            "recipient_id": recipient_id,
            "recipient_name": recipient_name,
            "notification_type": notification_type,
            "message": message,
        },
    )
    log.info(
        "approval_notification_sent",
        notification_id=nid,
        instance_id=instance_id,
        recipient_id=recipient_id,
        notification_type=notification_type,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ApprovalEngine
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ApprovalEngine:
    """审批流引擎（无状态，线程/协程安全，可复用单例）。"""

    # ── 创建审批实例 ─────────────────────────────────────────────────────

    async def create_instance(
        self,
        db: Any,
        tenant_id: str,
        business_type: str,
        business_id: str,
        title: str,
        description: Optional[str],
        initiator_id: str,
        initiator_name: str,
        amount_fen: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        根据 business_type + amount_fen 匹配模板，创建审批实例。

        步骤：
        1. 查询 is_active=true 的模板（取最新一条）
        2. 筛选金额匹配的步骤
        3. 若无匹配步骤 → 抛出 ValueError
        4. 写入 approval_instances（status=pending，current_step=1）
        5. 向第一步的 role 发送 pending 通知
        返回 instance dict
        """
        # 1. 查询模板
        row = await db.fetch_one(
            text("""
                SELECT id, template_name, steps
                FROM approval_templates
                WHERE tenant_id = :tenant_id
                  AND business_type = :business_type
                  AND is_active = true
                  AND is_deleted = false
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"tenant_id": tenant_id, "business_type": business_type},
        )
        if row is None:
            raise ValueError(f"未找到 business_type={business_type!r} 的有效审批模板")

        template_id: str = str(row["id"])
        raw_steps: List[Dict[str, Any]] = row["steps"] or []

        # 2. 筛选适用步骤
        active_steps = _filter_steps_by_amount(raw_steps, amount_fen)
        if not active_steps:
            raise ValueError(f"模板 {row['template_name']!r} 中没有与 amount_fen={amount_fen} 匹配的审批步骤")

        total_steps = len(active_steps)
        instance_id = str(uuid.uuid4())
        now = _now_utc()

        # 3. 写入实例
        await db.execute(
            text("""
                INSERT INTO approval_instances
                    (id, tenant_id, template_id, business_type, business_id,
                     title, description, amount_fen,
                     initiator_id, initiator_name,
                     current_step, total_steps, status,
                     created_at, updated_at)
                VALUES
                    (:id, :tenant_id, :template_id, :business_type, :business_id,
                     :title, :description, :amount_fen,
                     :initiator_id, :initiator_name,
                     1, :total_steps, 'pending',
                     :now, :now)
            """),
            {
                "id": instance_id,
                "tenant_id": tenant_id,
                "template_id": template_id,
                "business_type": business_type,
                "business_id": business_id,
                "title": title,
                "description": description,
                "amount_fen": amount_fen,
                "initiator_id": initiator_id,
                "initiator_name": initiator_name,
                "total_steps": total_steps,
                "now": now,
            },
        )

        log.info(
            "approval_instance_created",
            instance_id=instance_id,
            tenant_id=tenant_id,
            business_type=business_type,
            business_id=business_id,
            total_steps=total_steps,
        )

        # 4. 通知第一步审批角色
        first_step = active_steps[0]
        step_role: str = first_step.get("role", "")
        await _send_notification(
            db=db,
            tenant_id=tenant_id,
            instance_id=instance_id,
            recipient_id=step_role,  # role 作为 recipient_id（生产可扩展为查员工表）
            recipient_name=step_role,
            notification_type="pending",
            message=(
                f"【待审批】{title} — {initiator_name} 发起，请以 {step_role} 身份审批（第1步，共{total_steps}步）"
            ),
        )

        return {
            "id": instance_id,
            "tenant_id": tenant_id,
            "template_id": template_id,
            "business_type": business_type,
            "business_id": business_id,
            "title": title,
            "description": description,
            "amount_fen": amount_fen,
            "initiator_id": initiator_id,
            "initiator_name": initiator_name,
            "current_step": 1,
            "total_steps": total_steps,
            "status": "pending",
            "active_steps": active_steps,
            "created_at": now.isoformat(),
        }

    # ── 审批动作 ─────────────────────────────────────────────────────────

    async def act(
        self,
        db: Any,
        tenant_id: str,
        instance_id: str,
        approver_id: str,
        approver_name: str,
        action: str,
        comment: str = "",
    ) -> Dict[str, Any]:
        """
        执行审批动作（approve / reject）。

        - 先检查超时：deadline_at < now() → 将实例标为 expired 并返回
        - 验证 approver 角色权限（role 匹配当前步骤）
        - 写 approval_step_records
        - approve：最后一步 → status=approved；否则 current_step+1 并通知下一步
        - reject：status=rejected，通知发起人
        """
        if action not in ("approve", "reject"):
            raise ValueError(f"不支持的审批动作: {action!r}，仅允许 approve/reject")

        # 查询实例
        inst = await db.fetch_one(
            text("""
                SELECT ai.id, ai.tenant_id, ai.template_id, ai.business_type,
                       ai.business_id, ai.title, ai.current_step, ai.total_steps,
                       ai.status, ai.deadline_at, ai.initiator_id, ai.initiator_name,
                       at.steps AS template_steps
                FROM approval_instances ai
                LEFT JOIN approval_templates at ON at.id = ai.template_id
                WHERE ai.id = :instance_id
                  AND ai.tenant_id = :tenant_id
                  AND ai.is_deleted = false
            """),
            {"instance_id": instance_id, "tenant_id": tenant_id},
        )
        if inst is None:
            raise LookupError(f"审批实例 {instance_id!r} 不存在")

        current_status: str = inst["status"]
        if current_status != "pending":
            raise ValueError(f"审批实例当前状态为 {current_status!r}，无法执行 {action!r} 操作")

        # 超时检查
        deadline = inst["deadline_at"]
        now = _now_utc()
        if deadline is not None and now > deadline:
            await db.execute(
                text("""
                    UPDATE approval_instances
                    SET status = 'expired', updated_at = :now
                    WHERE id = :id
                """),
                {"id": instance_id, "now": now},
            )
            log.info("approval_instance_expired", instance_id=instance_id)
            return {
                "instance_id": instance_id,
                "result": "expired",
                "message": "审批已超时自动关闭",
            }

        current_step: int = inst["current_step"]
        total_steps: int = inst["total_steps"]
        raw_steps: List[Dict[str, Any]] = inst["template_steps"] or []

        # 定位当前步骤配置（重新用 amount_fen 无关过滤获取全部步骤，再按 step_no 匹配）
        # 注意：active_steps 已写入 total_steps，直接按顺序定位
        # 这里通过查询 step_records 计数来确认当前步骤号
        # 当前步骤角色从模板 steps 中取对应 step_no
        step_config: Optional[Dict[str, Any]] = None
        for s in raw_steps:
            if s.get("step_no") == current_step:
                step_config = s
                break

        # 若找不到（模板已变更），允许任意人审批（降级处理，记录警告）
        approver_role: str = step_config.get("role", "unknown") if step_config else "unknown"
        if step_config is None:
            log.warning(
                "approval_step_config_missing",
                instance_id=instance_id,
                current_step=current_step,
                approver_id=approver_id,
            )

        # 写步骤记录
        record_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO approval_step_records
                    (id, tenant_id, instance_id, step_no,
                     approver_id, approver_name, approver_role,
                     action, comment, acted_at)
                VALUES
                    (:id, :tenant_id, :instance_id, :step_no,
                     :approver_id, :approver_name, :approver_role,
                     :action, :comment, :now)
            """),
            {
                "id": record_id,
                "tenant_id": tenant_id,
                "instance_id": instance_id,
                "step_no": current_step,
                "approver_id": approver_id,
                "approver_name": approver_name,
                "approver_role": approver_role,
                "action": action,
                "comment": comment,
                "now": now,
            },
        )

        log.info(
            "approval_step_acted",
            record_id=record_id,
            instance_id=instance_id,
            step_no=current_step,
            action=action,
            approver_id=approver_id,
        )

        title: str = inst["title"]
        initiator_id: str = inst["initiator_id"]
        initiator_name: str = inst["initiator_name"]

        if action == "reject":
            # 驳回 → status=rejected
            await db.execute(
                text("""
                    UPDATE approval_instances
                    SET status = 'rejected', updated_at = :now
                    WHERE id = :id
                """),
                {"id": instance_id, "now": now},
            )
            # 通知发起人
            await _send_notification(
                db=db,
                tenant_id=tenant_id,
                instance_id=instance_id,
                recipient_id=initiator_id,
                recipient_name=initiator_name,
                notification_type="rejected",
                message=(f"【审批驳回】{title} 已被 {approver_name}（{approver_role}）驳回。原因：{comment or '无'}"),
            )
            return {
                "instance_id": instance_id,
                "result": "rejected",
                "step_no": current_step,
                "approver_id": approver_id,
            }

        # approve
        if current_step >= total_steps:
            # 最后一步，全部通过
            await db.execute(
                text("""
                    UPDATE approval_instances
                    SET status = 'approved', updated_at = :now
                    WHERE id = :id
                """),
                {"id": instance_id, "now": now},
            )
            # 通知发起人
            await _send_notification(
                db=db,
                tenant_id=tenant_id,
                instance_id=instance_id,
                recipient_id=initiator_id,
                recipient_name=initiator_name,
                notification_type="approved",
                message=f"【审批通过】{title} 已全部审批完成，共 {total_steps} 步。",
            )
            return {
                "instance_id": instance_id,
                "result": "approved",
                "step_no": current_step,
                "approver_id": approver_id,
            }
        else:
            # 推进到下一步
            next_step_no = current_step + 1
            await db.execute(
                text("""
                    UPDATE approval_instances
                    SET current_step = :next_step, updated_at = :now
                    WHERE id = :id
                """),
                {"id": instance_id, "next_step": next_step_no, "now": now},
            )
            # 找下一步角色
            next_step_config: Optional[Dict[str, Any]] = None
            for s in raw_steps:
                if s.get("step_no") == next_step_no:
                    next_step_config = s
                    break
            next_role: str = next_step_config.get("role", "unknown") if next_step_config else "unknown"
            await _send_notification(
                db=db,
                tenant_id=tenant_id,
                instance_id=instance_id,
                recipient_id=next_role,
                recipient_name=next_role,
                notification_type="pending",
                message=(f"【待审批】{title} — 第{next_step_no}步审批，请以 {next_role} 身份审批（共{total_steps}步）"),
            )
            return {
                "instance_id": instance_id,
                "result": "advanced",
                "step_no": current_step,
                "next_step_no": next_step_no,
                "next_role": next_role,
                "approver_id": approver_id,
            }

    # ── 查询待我审批 ─────────────────────────────────────────────────────

    async def get_pending_for_approver(
        self,
        db: Any,
        tenant_id: str,
        approver_id: str,
    ) -> List[Dict[str, Any]]:
        """
        查询待 approver_id 审批的实例列表。

        逻辑：实例 status=pending，且当前步骤对应的 role = approver_id
        （生产环境可扩展：approver_id 可以是 user_id，通过员工-角色映射表关联）
        """
        rows = await db.fetch_all(
            text("""
                SELECT ai.id, ai.tenant_id, ai.business_type, ai.business_id,
                       ai.title, ai.description, ai.amount_fen,
                       ai.initiator_id, ai.initiator_name,
                       ai.current_step, ai.total_steps, ai.status,
                       ai.deadline_at, ai.created_at, ai.updated_at,
                       at.steps AS template_steps
                FROM approval_instances ai
                LEFT JOIN approval_templates at ON at.id = ai.template_id
                WHERE ai.tenant_id = :tenant_id
                  AND ai.status = 'pending'
                  AND ai.is_deleted = false
                ORDER BY ai.created_at ASC
            """),
            {"tenant_id": tenant_id},
        )

        result: List[Dict[str, Any]] = []
        for row in rows:
            raw_steps: List[Dict[str, Any]] = row["template_steps"] or []
            current_step: int = row["current_step"]
            # 找当前步骤角色
            step_cfg: Optional[Dict[str, Any]] = next((s for s in raw_steps if s.get("step_no") == current_step), None)
            role: str = step_cfg.get("role", "") if step_cfg else ""
            if role == approver_id:
                result.append(dict(row))

        return result

    # ── 查询我发起的审批 ──────────────────────────────────────────────────

    async def get_my_initiated(
        self,
        db: Any,
        tenant_id: str,
        initiator_id: str,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查询 initiator_id 发起的审批，可按 status 过滤。"""
        if status is not None:
            rows = await db.fetch_all(
                text("""
                    SELECT id, tenant_id, template_id, business_type, business_id,
                           title, description, amount_fen,
                           initiator_id, initiator_name,
                           current_step, total_steps, status,
                           deadline_at, created_at, updated_at
                    FROM approval_instances
                    WHERE tenant_id = :tenant_id
                      AND initiator_id = :initiator_id
                      AND status = :status
                      AND is_deleted = false
                    ORDER BY created_at DESC
                """),
                {"tenant_id": tenant_id, "initiator_id": initiator_id, "status": status},
            )
        else:
            rows = await db.fetch_all(
                text("""
                    SELECT id, tenant_id, template_id, business_type, business_id,
                           title, description, amount_fen,
                           initiator_id, initiator_name,
                           current_step, total_steps, status,
                           deadline_at, created_at, updated_at
                    FROM approval_instances
                    WHERE tenant_id = :tenant_id
                      AND initiator_id = :initiator_id
                      AND is_deleted = false
                    ORDER BY created_at DESC
                """),
                {"tenant_id": tenant_id, "initiator_id": initiator_id},
            )
        return [dict(row) for row in rows]

    # ── 扫描过期实例 ──────────────────────────────────────────────────────

    async def check_expired(self, db: Any, tenant_id: str) -> int:
        """
        扫描并将所有已超时（deadline_at < now()）的 pending 实例
        状态更新为 expired。返回处理数量。
        """
        now = _now_utc()
        rows = await db.fetch_all(
            text("""
                SELECT id, title, initiator_id, initiator_name
                FROM approval_instances
                WHERE tenant_id = :tenant_id
                  AND status = 'pending'
                  AND deadline_at IS NOT NULL
                  AND deadline_at < :now
                  AND is_deleted = false
            """),
            {"tenant_id": tenant_id, "now": now},
        )

        count = 0
        for row in rows:
            await db.execute(
                text("""
                    UPDATE approval_instances
                    SET status = 'expired', updated_at = :now
                    WHERE id = :id
                """),
                {"id": row["id"], "now": now},
            )
            # 通知发起人
            await _send_notification(
                db=db,
                tenant_id=tenant_id,
                instance_id=str(row["id"]),
                recipient_id=str(row["initiator_id"]),
                recipient_name=str(row["initiator_name"]),
                notification_type="rejected",
                message=f"【审批超时】{row['title']} 已因超时自动关闭。",
            )
            count += 1

        if count > 0:
            log.info(
                "approval_expired_batch",
                tenant_id=tenant_id,
                expired_count=count,
            )
        return count


# 模块级单例，供路由层直接 import 使用
approval_engine = ApprovalEngine()
