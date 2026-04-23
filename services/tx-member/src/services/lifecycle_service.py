"""会员生命周期自动化服务

================================================================
DEPRECATED: 此模块已被 customer_lifecycle_fsm.py（v264 迁移）取代
================================================================

背景：
- 老版（本文件）阈值：new=7 / active=30 / dormant=90 天
- 新版 FSM：no_order / active(≤60) / dormant(≤180) / churned；事件溯源
- 并行存在会导致同一客户在两套系统被打不同标签 → Agent 取哪一个？

计划（独立审查报告 P0-3）：
- 当前阶段：**不删除**，保留现存调用（lifecycle_router.py / lifecycle_routes.py
  / test_lifecycle.py），避免在线业务中断。
- Sprint R3 前：完成所有调用方迁移到 customer_lifecycle_fsm.CustomerLifecycleFSM
- 2026-Q3：此文件计划删除。DEVLOG.md 需同步记录淘汰节点。
- 本文件**禁止新增调用点**。如果你在 review 中看到新代码 import 本模块，
  请 reject 并引导至 `services.customer_lifecycle_fsm`。

参考：
- docs/sprint-r1-independent-review.md P0-3
- services/tx-member/src/services/customer_lifecycle_fsm.py

----

四阶段生命周期：new → active → dormant → churned（可回流 reactivated）

设计原则：
- _compute_stage 是纯函数，不依赖 DB，便于测试
- 营销触发失败（发券/推送 API 报错）记录日志但不阻塞分类流程
- tenant_id 显式传入，所有 DB 查询带 tenant_id 参数
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy.exc import SQLAlchemyError

logger = structlog.get_logger(__name__)


# ── 阶段枚举 ──────────────────────────────────────────────────


class LifecycleStage(str):
    """生命周期阶段常量（使用 str 子类确保 JSON 序列化友好）"""

    NEW = "new"
    ACTIVE = "active"
    DORMANT = "dormant"
    CHURNED = "churned"
    REACTIVATED = "reactivated"

    def __new__(cls, value: str) -> "LifecycleStage":  # type: ignore[override]
        return str.__new__(cls, value)


# 为了方便外部使用，在类上直接挂载常量
LifecycleStage.NEW = LifecycleStage("new")  # type: ignore[attr-defined]
LifecycleStage.ACTIVE = LifecycleStage("active")  # type: ignore[attr-defined]
LifecycleStage.DORMANT = LifecycleStage("dormant")  # type: ignore[attr-defined]
LifecycleStage.CHURNED = LifecycleStage("churned")  # type: ignore[attr-defined]
LifecycleStage.REACTIVATED = LifecycleStage("reactivated")  # type: ignore[attr-defined]


# ── 服务类 ────────────────────────────────────────────────────


class LifecycleService:
    """会员生命周期自动分类与营销干预服务。

    默认阈值（可通过 lifecycle_configs 表覆盖）：
    - new:     首次消费后 ≤7 天
    - active:  最后消费距今 ≤30 天（且不在 new 阶段）
    - dormant: 最后消费距今 31-90 天
    - churned: 最后消费距今 >90 天
    """

    DEFAULT_THRESHOLDS: dict[str, int] = {
        "new": 7,
        "active": 30,
        "dormant": 90,
        "churned": 90,
    }

    # ── 纯函数：单会员阶段计算 ─────────────────────────────────

    def _compute_stage(self, customer: dict[str, Any]) -> LifecycleStage:
        """根据首次/最后消费时间计算应处于的生命周期阶段（纯函数，不访问 DB）。

        分类逻辑：
        1. 首次消费距今 ≤ new_threshold（默认 7 天）→ new
        2. 最后消费距今 ≤ active_threshold（默认 30 天）→ active
        3. 最后消费距今 ≤ dormant_threshold（默认 90 天）→ dormant
        4. 其余 → churned
        """
        now = datetime.now(timezone.utc)

        first_order_at: Optional[datetime] = customer.get("first_order_at")
        last_order_at: Optional[datetime] = customer.get("last_order_at")

        if first_order_at is None:
            return LifecycleStage.NEW

        # 确保 datetime 有 timezone 信息
        if first_order_at.tzinfo is None:
            first_order_at = first_order_at.replace(tzinfo=timezone.utc)
        if last_order_at is not None and last_order_at.tzinfo is None:
            last_order_at = last_order_at.replace(tzinfo=timezone.utc)

        days_since_first = (now - first_order_at).days
        days_since_last = (now - last_order_at).days if last_order_at is not None else days_since_first

        new_threshold = self.DEFAULT_THRESHOLDS["new"]
        active_threshold = self.DEFAULT_THRESHOLDS["active"]
        dormant_threshold = self.DEFAULT_THRESHOLDS["dormant"]

        if days_since_first <= new_threshold:
            return LifecycleStage.NEW
        if days_since_last <= active_threshold:
            return LifecycleStage.ACTIVE
        if days_since_last <= dormant_threshold:
            return LifecycleStage.DORMANT
        return LifecycleStage.CHURNED

    # ── 单会员分类（含 DB 写入） ────────────────────────────────

    async def classify_member(
        self,
        member_id: str,
        tenant_id: str,
        db: Any,
    ) -> str:
        """对单个会员重新分类，更新 DB 并返回新阶段。

        Args:
            member_id: 会员 UUID 字符串
            tenant_id: 租户 UUID 字符串
            db: AsyncSession

        Returns:
            新的生命周期阶段字符串
        """
        from sqlalchemy import text

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        result = await db.execute(
            text("""
                SELECT id, lifecycle_stage, first_order_at, last_order_at
                FROM customers
                WHERE id = :mid AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"mid": member_id, "tid": tenant_id},
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"会员不存在: member_id={member_id}, tenant_id={tenant_id}")

        customer = {
            "id": str(row[0]),
            "tenant_id": tenant_id,
            "lifecycle_stage": row[1],
            "first_order_at": row[2],
            "last_order_at": row[3],
        }

        new_stage = self._compute_stage(customer)
        old_stage = customer["lifecycle_stage"]

        if new_stage != old_stage:
            await self._update_member_stage(member_id, tenant_id, new_stage, db)
            days_since_last = (
                (datetime.now(timezone.utc) - customer["last_order_at"]).days if customer["last_order_at"] else None
            )
            trigger_reason = (
                f"days_since_last_visit={days_since_last}" if days_since_last is not None else "first_classification"
            )
            action_result = await self.trigger_intervention(
                member_id=member_id,
                new_stage=new_stage,
                tenant_id=tenant_id,
                db=db,
            )
            await self._record_event(
                member_id=member_id,
                tenant_id=tenant_id,
                from_stage=old_stage,
                to_stage=new_stage,
                trigger_reason=trigger_reason,
                action_taken=action_result.get("action_taken", "none"),
                db=db,
            )

        logger.info(
            "member_classified",
            member_id=member_id,
            tenant_id=tenant_id,
            old_stage=old_stage,
            new_stage=new_stage,
        )
        return new_stage

    # ── 批量重分类（夜批作业） ─────────────────────────────────

    async def batch_reclassify(
        self,
        tenant_id: str,
        db: Any,
    ) -> dict[str, int]:
        """批量重分类全体会员（夜批调用）。

        流程：
        1. 扫描所有会员的最后消费时间
        2. 计算新阶段，与现有阶段对比
        3. 对有变更的会员更新 lifecycle_stage
        4. 记录变更事件
        5. 触发营销干预

        Returns:
            {new: n, active: n, dormant: n, churned: n, reactivated: n, changed: n}
        """
        members = await self._fetch_all_members(tenant_id=tenant_id, db=db)

        counters: dict[str, int] = {
            "new": 0,
            "active": 0,
            "dormant": 0,
            "churned": 0,
            "reactivated": 0,
            "changed": 0,
        }

        for member in members:
            new_stage = self._compute_stage(member)
            old_stage = member.get("lifecycle_stage") or "new"

            # 更新计数
            if new_stage in counters:
                counters[new_stage] += 1

            # 只对有变更的会员操作
            if new_stage == old_stage:
                continue

            member_id = str(member["id"])
            counters["changed"] += 1

            # 计算触发原因
            last_order_at: Optional[datetime] = member.get("last_order_at")
            if last_order_at is not None:
                if last_order_at.tzinfo is None:
                    last_order_at = last_order_at.replace(tzinfo=timezone.utc)
                days_since_last = (datetime.now(timezone.utc) - last_order_at).days
                trigger_reason = f"days_since_last_visit={days_since_last}"
            else:
                trigger_reason = "first_classification"

            await self._update_member_stage(member_id, tenant_id, new_stage, db)

            action_result = await self.trigger_intervention(
                member_id=member_id,
                new_stage=new_stage,
                tenant_id=tenant_id,
                db=db,
            )

            await self._record_event(
                member_id=member_id,
                tenant_id=tenant_id,
                from_stage=old_stage,
                to_stage=new_stage,
                trigger_reason=trigger_reason,
                action_taken=action_result.get("action_taken", "none"),
                db=db,
            )

        logger.info(
            "lifecycle_batch_reclassify_done",
            tenant_id=tenant_id,
            **counters,
        )
        return counters

    # ── 营销干预 ───────────────────────────────────────────────

    async def trigger_intervention(
        self,
        member_id: str,
        new_stage: str,
        tenant_id: str,
        db: Any,
    ) -> dict[str, Any]:
        """根据新阶段触发营销干预。

        干预策略：
        - dormant → 从 lifecycle_configs 读取配置，发挽回优惠券
        - churned → 发企微消息 + 大额复活券
        - reactivated → 发欢迎回来礼包
        - 其余阶段 → 无动作

        营销动作失败时记录日志并返回 action_taken="none"，不抛异常。

        Returns:
            {"action_taken": str, "error": str | None}
        """
        config = await self._get_lifecycle_config(stage=new_stage, tenant_id=tenant_id, db=db)

        if config is None or not config.get("is_active", False):
            return {"action_taken": "none", "error": None}

        auto_action = config.get("auto_action", "none")
        if auto_action == "none":
            return {"action_taken": "none", "error": None}

        action_taken = "none"
        error_msg: Optional[str] = None

        try:
            if new_stage == LifecycleStage.DORMANT:
                action_taken = await self._handle_dormant(member_id, tenant_id, config, db)
            elif new_stage == LifecycleStage.CHURNED:
                action_taken = await self._handle_churned(member_id, tenant_id, config, db)
            elif new_stage == LifecycleStage.REACTIVATED:
                action_taken = await self._handle_reactivated(member_id, tenant_id, config, db)
        except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError) as exc:  # 营销失败兜底，记录日志不阻塞
            error_msg = str(exc)
            action_taken = "none"
            logger.warning(
                "lifecycle_intervention_failed",
                member_id=member_id,
                tenant_id=tenant_id,
                new_stage=new_stage,
                error=error_msg,
                exc_info=True,
            )

        return {"action_taken": action_taken, "error": error_msg}

    async def _handle_dormant(
        self,
        member_id: str,
        tenant_id: str,
        config: dict[str, Any],
        db: Any,
    ) -> str:
        """沉睡处理：发挽回优惠券"""
        coupon_template_id = config.get("coupon_template_id")
        if coupon_template_id:
            await self._issue_coupon_to_member(
                member_id=member_id,
                coupon_template_id=str(coupon_template_id),
                tenant_id=tenant_id,
                db=db,
            )
            return "coupon_sent"
        return "none"

    async def _handle_churned(
        self,
        member_id: str,
        tenant_id: str,
        config: dict[str, Any],
        db: Any,
    ) -> str:
        """流失处理：企微消息 + 大额复活券"""
        actions: list[str] = []

        message_template = config.get("message_template")
        if message_template:
            await self._send_wecom_message(
                member_id=member_id,
                message=message_template,
                tenant_id=tenant_id,
                db=db,
            )
            actions.append("wecom_pushed")

        coupon_template_id = config.get("coupon_template_id")
        if coupon_template_id:
            await self._issue_coupon_to_member(
                member_id=member_id,
                coupon_template_id=str(coupon_template_id),
                tenant_id=tenant_id,
                db=db,
            )
            actions.append("coupon_sent")

        return "+".join(actions) if actions else "none"

    async def _handle_reactivated(
        self,
        member_id: str,
        tenant_id: str,
        config: dict[str, Any],
        db: Any,
    ) -> str:
        """再激活处理：发欢迎回来礼包"""
        coupon_template_id = config.get("coupon_template_id")
        if coupon_template_id:
            await self._issue_coupon_to_member(
                member_id=member_id,
                coupon_template_id=str(coupon_template_id),
                tenant_id=tenant_id,
                db=db,
            )
            return "welcome_gift_sent"
        return "none"

    # ── 统计 ───────────────────────────────────────────────────

    async def get_lifecycle_stats(
        self,
        tenant_id: str,
        db: Any,
        store_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """统计各阶段会员数量和占比。

        Args:
            tenant_id: 租户 ID
            db: AsyncSession
            store_id: 可选，限定到特定门店

        Returns:
            {new, active, dormant, churned, reactivated, total,
             ratios: {new: float, active: float, ...}}
        """
        counts = await self._query_stage_counts(tenant_id=tenant_id, store_id=store_id, db=db)
        total = counts.get("total", 0)

        ratios: dict[str, float] = {}
        for stage in ("new", "active", "dormant", "churned", "reactivated"):
            cnt = counts.get(stage, 0)
            ratios[stage] = round(cnt / total, 4) if total > 0 else 0.0

        return {**counts, "ratios": ratios}

    # ── 内部 DB 操作（可被测试替换） ──────────────────────────

    async def _fetch_all_members(
        self,
        tenant_id: str,
        db: Any,
    ) -> list[dict[str, Any]]:
        """从 DB 获取指定 tenant 的所有有效会员。

        SQL：
            SELECT id, lifecycle_stage, first_order_at, last_order_at
            FROM customers
            WHERE tenant_id = :tid AND is_deleted = FALSE
        """
        from sqlalchemy import text

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        result = await db.execute(
            text("""
                SELECT id, lifecycle_stage, first_order_at, last_order_at
                FROM customers
                WHERE tenant_id = :tid AND is_deleted = FALSE
            """),
            {"tid": tenant_id},
        )
        rows = result.fetchall()
        return [
            {
                "id": str(row[0]),
                "lifecycle_stage": row[1],
                "first_order_at": row[2],
                "last_order_at": row[3],
            }
            for row in rows
        ]

    async def _update_member_stage(
        self,
        member_id: str,
        tenant_id: str,
        new_stage: str,
        db: Any,
    ) -> None:
        """更新会员的 lifecycle_stage 字段"""
        from sqlalchemy import text

        await db.execute(
            text("""
                UPDATE customers
                SET lifecycle_stage = :stage,
                    updated_at = NOW()
                WHERE id = :mid AND tenant_id = :tid
            """),
            {"stage": new_stage, "mid": member_id, "tid": tenant_id},
        )
        await db.commit()

    async def _record_event(
        self,
        *,
        member_id: str,
        tenant_id: str,
        from_stage: Optional[str],
        to_stage: str,
        trigger_reason: Optional[str],
        action_taken: str,
        db: Any,
    ) -> None:
        """记录生命周期事件到 lifecycle_events 表"""
        await self._insert_lifecycle_event(
            member_id=member_id,
            tenant_id=tenant_id,
            from_stage=from_stage,
            to_stage=to_stage,
            trigger_reason=trigger_reason,
            action_taken=action_taken,
            db=db,
        )

    async def _insert_lifecycle_event(
        self,
        *,
        member_id: str,
        tenant_id: str,
        from_stage: Optional[str],
        to_stage: str,
        trigger_reason: Optional[str],
        action_taken: str,
        db: Any,
    ) -> None:
        """向 lifecycle_events 插入一行记录"""
        from sqlalchemy import text

        await db.execute(
            text("""
                INSERT INTO lifecycle_events
                    (tenant_id, member_id, from_stage, to_stage,
                     trigger_reason, action_taken)
                VALUES
                    (:tid, :mid, :from_s, :to_s, :reason, :action)
            """),
            {
                "tid": tenant_id,
                "mid": member_id,
                "from_s": from_stage,
                "to_s": to_stage,
                "reason": trigger_reason,
                "action": action_taken,
            },
        )
        await db.commit()

    async def _query_stage_counts(
        self,
        tenant_id: str,
        db: Any,
        store_id: Optional[str] = None,
    ) -> dict[str, int]:
        """查询各阶段会员数量（支持门店过滤）"""
        from sqlalchemy import text

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        where_store = "AND store_id = :store_id" if store_id else ""
        sql = text(f"""
            SELECT lifecycle_stage, count(*) AS cnt
            FROM customers
            WHERE tenant_id = :tid
              AND is_deleted = FALSE
              {where_store}
            GROUP BY lifecycle_stage
        """)
        params: dict[str, Any] = {"tid": tenant_id}
        if store_id:
            params["store_id"] = store_id

        result = await db.execute(sql, params)
        rows = result.fetchall()

        counts: dict[str, int] = {
            "new": 0,
            "active": 0,
            "dormant": 0,
            "churned": 0,
            "reactivated": 0,
            "total": 0,
        }
        for stage, cnt in rows:
            if stage in counts:
                counts[stage] = int(cnt)
            counts["total"] += int(cnt)

        return counts

    # ── 营销动作（可被测试替换） ───────────────────────────────

    async def _get_lifecycle_config(
        self,
        stage: str,
        tenant_id: str,
        db: Any,
    ) -> Optional[dict[str, Any]]:
        """从 lifecycle_configs 表获取阶段配置。

        SQL：
            SELECT auto_action, coupon_template_id, message_template, is_active
            FROM lifecycle_configs
            WHERE tenant_id = :tid AND stage = :stage AND is_active = TRUE
        """
        from sqlalchemy import text

        result = await db.execute(
            text("""
                SELECT auto_action, coupon_template_id, message_template, is_active
                FROM lifecycle_configs
                WHERE tenant_id = :tid AND stage = :stage AND is_active = TRUE
                LIMIT 1
            """),
            {"tid": tenant_id, "stage": stage},
        )
        row = result.fetchone()
        if row is None:
            return None
        return {
            "auto_action": row[0],
            "coupon_template_id": str(row[1]) if row[1] else None,
            "message_template": row[2],
            "is_active": row[3],
        }

    async def _issue_coupon_to_member(
        self,
        *,
        member_id: str,
        coupon_template_id: str,
        tenant_id: str,
        db: Any,
    ) -> dict[str, Any]:
        """调用 coupon_engine.batch_issue 向单个会员发券"""
        from ..services.coupon_engine import batch_issue

        result = await batch_issue(
            coupon_id=coupon_template_id,
            target_customers=[member_id],
            tenant_id=tenant_id,
            db=db,
        )
        logger.info(
            "lifecycle_coupon_issued",
            member_id=member_id,
            coupon_template_id=coupon_template_id,
            tenant_id=tenant_id,
            result=result,
        )
        return result

    async def _send_wecom_message(
        self,
        *,
        member_id: str,
        message: str,
        tenant_id: str,
        db: Any,
    ) -> dict[str, Any]:
        """通过社交引擎发送企微消息（调用 social_engine）"""
        from ..services.social_engine import send_gift

        # 将生命周期消息包装为 gift 类型（card）推送
        result = await send_gift(
            sender_id="system",
            receiver_phone=member_id,  # social_engine 后续映射 member_id → phone
            gift_type="card",
            gift_config={
                "message": message,
                "lifecycle_notification": True,
            },
            tenant_id=tenant_id,
            db=db,
        )
        logger.info(
            "lifecycle_wecom_pushed",
            member_id=member_id,
            tenant_id=tenant_id,
        )
        return result
