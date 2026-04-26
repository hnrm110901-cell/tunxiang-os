"""营销任务日历服务 — 任务CRUD/生命周期/分配/执行/日历/效果/排行榜

核心功能：
  - CRUD:                   任务创建/查询/更新/删除
  - 生命周期:               schedule/start/pause/cancel/complete
  - create_assignments:     展开门店→员工分配
  - record_execution:       记录单条执行结果
  - batch_execute:          批量执行（群发）
  - get_calendar:           月视图日历
  - 效果统计:               任务/门店/员工/优惠券维度
  - leaderboard:            执行排行榜（门店/员工维度）
  - check_scheduled_tasks:  检查到期任务（定时任务调用）
"""

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)


class MarketingTaskError(Exception):
    """营销任务业务异常"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 状态转换验证
# ---------------------------------------------------------------------------

_VALID_STATUS_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["scheduled", "cancelled"],
    "scheduled": ["executing", "paused", "cancelled"],
    "executing": ["completed", "paused", "cancelled"],
    "paused": ["scheduled", "executing", "cancelled"],
    "completed": [],
    "cancelled": ["draft"],
}


class MarketingTaskService:
    """营销任务日历核心服务"""

    # ===================================================================
    # CRUD — 任务管理
    # ===================================================================

    async def create_task(
        self,
        tenant_id: uuid.UUID,
        task_name: str,
        channel: str,
        content: dict,
        created_by: uuid.UUID,
        db: Any,
        *,
        description: Optional[str] = None,
        task_type: str = "one_time",
        audience_pack_id: Optional[uuid.UUID] = None,
        audience_filter: Optional[dict] = None,
        schedule_at: Optional[datetime] = None,
        schedule_end_at: Optional[datetime] = None,
        recurrence_rule: Optional[dict] = None,
        target_store_ids: Optional[list] = None,
        target_employee_ids: Optional[list] = None,
        priority: str = "normal",
    ) -> dict:
        """创建营销任务"""
        task_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO marketing_tasks (
                    id, tenant_id, task_name, description, task_type,
                    channel, audience_pack_id, audience_filter,
                    content, schedule_at, schedule_end_at,
                    recurrence_rule, target_store_ids, target_employee_ids,
                    priority, created_by
                ) VALUES (
                    :id, :tenant_id, :task_name, :description, :task_type,
                    :channel, :audience_pack_id, :audience_filter::jsonb,
                    :content::jsonb, :schedule_at, :schedule_end_at,
                    :recurrence_rule::jsonb, :target_store_ids::jsonb,
                    :target_employee_ids::jsonb,
                    :priority, :created_by
                )
            """),
            {
                "id": str(task_id),
                "tenant_id": str(tenant_id),
                "task_name": task_name,
                "description": description,
                "task_type": task_type,
                "channel": channel,
                "audience_pack_id": str(audience_pack_id) if audience_pack_id else None,
                "audience_filter": json.dumps(audience_filter) if audience_filter else None,
                "content": json.dumps(content),
                "schedule_at": schedule_at,
                "schedule_end_at": schedule_end_at,
                "recurrence_rule": json.dumps(recurrence_rule) if recurrence_rule else None,
                "target_store_ids": json.dumps(target_store_ids or []),
                "target_employee_ids": json.dumps(target_employee_ids or []),
                "priority": priority,
                "created_by": str(created_by),
            },
        )
        log.info("marketing_task_created", task_id=str(task_id), channel=channel)
        return {"task_id": str(task_id)}

    async def get_task(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """获取任务详情"""
        result = await db.execute(
            text("""
                SELECT * FROM marketing_tasks
                WHERE tenant_id = :tenant_id AND id = :task_id AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "task_id": str(task_id)},
        )
        row = result.mappings().first()
        if row is None:
            raise MarketingTaskError("NOT_FOUND", "营销任务不存在")
        return dict(row)

    async def list_tasks(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        status: Optional[str] = None,
        channel: Optional[str] = None,
        task_type: Optional[str] = None,
        priority: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询任务列表"""
        where = "tenant_id = :tenant_id AND is_deleted = FALSE"
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}

        if status:
            where += " AND status = :status"
            params["status"] = status
        if channel:
            where += " AND channel = :channel"
            params["channel"] = channel
        if task_type:
            where += " AND task_type = :task_type"
            params["task_type"] = task_type
        if priority:
            where += " AND priority = :priority"
            params["priority"] = priority

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM marketing_tasks WHERE {where}"),
            params,
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        data_sql = f"""
            SELECT * FROM marketing_tasks WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = size
        params["offset"] = offset
        result = await db.execute(text(data_sql), params)
        items = [dict(r) for r in result.mappings().all()]
        return {"items": items, "total": total, "page": page, "size": size}

    async def update_task(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        updates: dict,
        db: Any,
    ) -> dict:
        """更新任务（仅draft状态允许）"""
        task = await self.get_task(tenant_id, task_id, db)
        if task["status"] != "draft":
            raise MarketingTaskError("INVALID_STATE", "仅草稿状态可编辑")

        allowed = {
            "task_name",
            "description",
            "channel",
            "content",
            "audience_pack_id",
            "audience_filter",
            "schedule_at",
            "schedule_end_at",
            "recurrence_rule",
            "target_store_ids",
            "target_employee_ids",
            "priority",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            raise MarketingTaskError("EMPTY_UPDATE", "无有效更新字段")

        # JSON字段序列化
        json_fields = {"content", "audience_filter", "recurrence_rule", "target_store_ids", "target_employee_ids"}
        set_parts = []
        for k in filtered:
            if k in json_fields and filtered[k] is not None:
                filtered[k] = json.dumps(filtered[k])
                set_parts.append(f"{k} = :{k}::jsonb")
            else:
                set_parts.append(f"{k} = :{k}")
        set_parts.append("updated_at = now()")

        sql = f"""
            UPDATE marketing_tasks SET {", ".join(set_parts)}
            WHERE tenant_id = :tenant_id AND id = :task_id AND is_deleted = FALSE
        """
        filtered["tenant_id"] = str(tenant_id)
        filtered["task_id"] = str(task_id)
        result = await db.execute(text(sql), filtered)
        if result.rowcount == 0:
            raise MarketingTaskError("NOT_FOUND", "营销任务不存在")
        return {"updated": True}

    async def delete_task(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """软删除任务"""
        result = await db.execute(
            text("""
                UPDATE marketing_tasks SET is_deleted = TRUE, updated_at = now()
                WHERE tenant_id = :tenant_id AND id = :task_id AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "task_id": str(task_id)},
        )
        if result.rowcount == 0:
            raise MarketingTaskError("NOT_FOUND", "营销任务不存在")
        return {"deleted": True}

    # ===================================================================
    # Lifecycle — 生命周期管理
    # ===================================================================

    async def _transition_status(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        new_status: str,
        db: Any,
        *,
        extra_sets: Optional[dict] = None,
    ) -> dict:
        """状态转换（含验证）"""
        task = await self.get_task(tenant_id, task_id, db)
        current = task["status"]
        valid_next = _VALID_STATUS_TRANSITIONS.get(current, [])
        if new_status not in valid_next:
            raise MarketingTaskError(
                "INVALID_TRANSITION",
                f"不允许从 {current} 转换到 {new_status}，有效: {valid_next}",
            )

        set_parts = ["status = :new_status", "updated_at = now()"]
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "task_id": str(task_id),
            "new_status": new_status,
        }

        if extra_sets:
            for k, v in extra_sets.items():
                set_parts.append(f"{k} = :{k}")
                params[k] = v

        sql = f"""
            UPDATE marketing_tasks SET {", ".join(set_parts)}
            WHERE tenant_id = :tenant_id AND id = :task_id AND is_deleted = FALSE
        """
        await db.execute(text(sql), params)
        log.info("marketing_task_status_changed", task_id=str(task_id), from_status=current, to_status=new_status)
        return {"task_id": str(task_id), "from_status": current, "to_status": new_status}

    async def schedule_task(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        db: Any,
        *,
        approved_by: Optional[uuid.UUID] = None,
    ) -> dict:
        """排期任务"""
        extra = {}
        if approved_by:
            extra["approved_by"] = str(approved_by)
            extra["approved_at"] = datetime.now(timezone.utc)
        return await self._transition_status(tenant_id, task_id, "scheduled", db, extra_sets=extra)

    async def start_task(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """开始执行任务"""
        return await self._transition_status(tenant_id, task_id, "executing", db)

    async def pause_task(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """暂停任务"""
        return await self._transition_status(tenant_id, task_id, "paused", db)

    async def cancel_task(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """取消任务"""
        return await self._transition_status(tenant_id, task_id, "cancelled", db)

    async def complete_task(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """完成任务"""
        return await self._transition_status(tenant_id, task_id, "completed", db)

    # ===================================================================
    # Assignments — 任务分配
    # ===================================================================

    async def create_assignments(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        store_employee_map: list[dict],
        db: Any,
    ) -> dict:
        """展开门店→员工分配

        store_employee_map: [{"store_id": "...", "employee_id": "...", "customer_count": N}]
        """
        task = await self.get_task(tenant_id, task_id, db)
        created = 0
        total_customers = 0

        for item in store_employee_map:
            assignment_id = uuid.uuid4()
            customer_count = item.get("customer_count", 0)
            await db.execute(
                text("""
                    INSERT INTO marketing_task_assignments (
                        id, tenant_id, task_id, store_id, employee_id,
                        assigned_customer_count
                    ) VALUES (
                        :id, :tenant_id, :task_id, :store_id, :employee_id,
                        :customer_count
                    )
                """),
                {
                    "id": str(assignment_id),
                    "tenant_id": str(tenant_id),
                    "task_id": str(task_id),
                    "store_id": str(item["store_id"]),
                    "employee_id": str(item["employee_id"]) if item.get("employee_id") else None,
                    "customer_count": customer_count,
                },
            )
            created += 1
            total_customers += customer_count

        # 更新任务的目标人数
        await db.execute(
            text("""
                UPDATE marketing_tasks
                SET total_target_count = :count, updated_at = now()
                WHERE id = :task_id
            """),
            {"task_id": str(task_id), "count": total_customers},
        )

        log.info("marketing_assignments_created", task_id=str(task_id), count=created)
        return {"created": created, "total_target_count": total_customers}

    async def list_assignments(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        db: Any,
        *,
        status: Optional[str] = None,
    ) -> list[dict]:
        """查询任务分配列表"""
        sql = """
            SELECT * FROM marketing_task_assignments
            WHERE tenant_id = :tenant_id AND task_id = :task_id AND is_deleted = FALSE
        """
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "task_id": str(task_id),
        }
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at ASC"

        result = await db.execute(text(sql), params)
        return [dict(r) for r in result.mappings().all()]

    # ===================================================================
    # Execution — 执行记录
    # ===================================================================

    async def record_execution(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        db: Any,
        *,
        assignment_id: Optional[uuid.UUID] = None,
        store_id: Optional[uuid.UUID] = None,
        employee_id: Optional[uuid.UUID] = None,
        customer_id: Optional[uuid.UUID] = None,
        wecom_external_userid: Optional[str] = None,
        group_chat_id: Optional[str] = None,
        channel: Optional[str] = None,
        send_status: str = "sent",
        coupon_instance_id: Optional[uuid.UUID] = None,
        failure_reason: Optional[str] = None,
    ) -> dict:
        """记录单条执行结果"""
        exec_id = uuid.uuid4()
        sent_at = datetime.now(timezone.utc) if send_status == "sent" else None

        await db.execute(
            text("""
                INSERT INTO marketing_task_executions (
                    id, tenant_id, task_id, assignment_id,
                    store_id, employee_id, customer_id,
                    wecom_external_userid, group_chat_id, channel,
                    send_status, coupon_instance_id, failure_reason, sent_at
                ) VALUES (
                    :id, :tenant_id, :task_id, :assignment_id,
                    :store_id, :employee_id, :customer_id,
                    :wecom_external_userid, :group_chat_id, :channel,
                    :send_status, :coupon_instance_id, :failure_reason, :sent_at
                )
            """),
            {
                "id": str(exec_id),
                "tenant_id": str(tenant_id),
                "task_id": str(task_id),
                "assignment_id": str(assignment_id) if assignment_id else None,
                "store_id": str(store_id) if store_id else None,
                "employee_id": str(employee_id) if employee_id else None,
                "customer_id": str(customer_id) if customer_id else None,
                "wecom_external_userid": wecom_external_userid,
                "group_chat_id": group_chat_id,
                "channel": channel,
                "send_status": send_status,
                "coupon_instance_id": str(coupon_instance_id) if coupon_instance_id else None,
                "failure_reason": failure_reason,
                "sent_at": sent_at,
            },
        )
        return {"execution_id": str(exec_id)}

    async def batch_execute(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        executions: list[dict],
        db: Any,
    ) -> dict:
        """批量执行"""
        success = 0
        failed = 0
        for exec_item in executions:
            try:
                await self.record_execution(
                    tenant_id,
                    task_id,
                    db,
                    store_id=uuid.UUID(exec_item["store_id"]) if exec_item.get("store_id") else None,
                    employee_id=uuid.UUID(exec_item["employee_id"]) if exec_item.get("employee_id") else None,
                    customer_id=uuid.UUID(exec_item["customer_id"]) if exec_item.get("customer_id") else None,
                    wecom_external_userid=exec_item.get("wecom_external_userid"),
                    group_chat_id=exec_item.get("group_chat_id"),
                    channel=exec_item.get("channel"),
                    send_status=exec_item.get("send_status", "sent"),
                    failure_reason=exec_item.get("failure_reason"),
                )
                success += 1
            except (ValueError, RuntimeError, OSError) as exc:
                log.error("batch_execute_item_failed", error=str(exc))
                failed += 1

        log.info("marketing_batch_executed", task_id=str(task_id), success=success, failed=failed)
        return {"success": success, "failed": failed}

    # ===================================================================
    # Calendar — 月视图日历
    # ===================================================================

    async def get_calendar(
        self,
        tenant_id: uuid.UUID,
        year: int,
        month: int,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
    ) -> list[dict]:
        """获取月视图日历"""
        first_day = date(year, month, 1)
        if month == 12:
            last_day = date(year + 1, 1, 1)
        else:
            last_day = date(year, month + 1, 1)

        sql = """
            SELECT id, task_name, task_type, channel, status, priority,
                   schedule_at, schedule_end_at, total_target_count
            FROM marketing_tasks
            WHERE tenant_id = :tenant_id AND is_deleted = FALSE
              AND schedule_at IS NOT NULL
              AND schedule_at >= :first_day
              AND schedule_at < :last_day
        """
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "first_day": first_day,
            "last_day": last_day,
        }
        if store_id:
            sql += " AND target_store_ids @> :store_filter::jsonb"
            params["store_filter"] = json.dumps([str(store_id)])

        sql += " ORDER BY schedule_at ASC"
        result = await db.execute(text(sql), params)
        return [dict(r) for r in result.mappings().all()]

    # ===================================================================
    # Effects — 效果统计
    # ===================================================================

    async def get_task_effect(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """获取任务整体效果"""
        result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(total_sent), 0) AS total_sent,
                    COALESCE(SUM(delivered), 0) AS total_delivered,
                    COALESCE(SUM(read), 0) AS total_read,
                    COALESCE(SUM(clicked), 0) AS total_clicked,
                    COALESCE(SUM(converted), 0) AS total_converted,
                    COALESCE(SUM(coupon_issued_count), 0) AS total_coupon_issued,
                    COALESCE(SUM(redeemed_count), 0) AS total_redeemed,
                    COALESCE(SUM(revenue_fen), 0) AS total_revenue_fen,
                    CASE WHEN COALESCE(SUM(total_sent), 0) > 0
                        THEN ROUND(SUM(delivered)::NUMERIC / SUM(total_sent) * 100, 2)
                        ELSE 0
                    END AS delivery_rate,
                    CASE WHEN COALESCE(SUM(delivered), 0) > 0
                        THEN ROUND(SUM(read)::NUMERIC / SUM(delivered) * 100, 2)
                        ELSE 0
                    END AS read_rate,
                    CASE WHEN COALESCE(SUM(read), 0) > 0
                        THEN ROUND(SUM(converted)::NUMERIC / SUM(read) * 100, 2)
                        ELSE 0
                    END AS conversion_rate
                FROM marketing_task_effects
                WHERE tenant_id = :tenant_id AND task_id = :task_id AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "task_id": str(task_id)},
        )
        row = result.mappings().first()
        return dict(row) if row else {}

    async def get_store_effect(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        db: Any,
    ) -> list[dict]:
        """按门店维度统计效果"""
        result = await db.execute(
            text("""
                SELECT store_id,
                    SUM(total_sent) AS total_sent,
                    SUM(delivered) AS total_delivered,
                    SUM(read) AS total_read,
                    SUM(converted) AS total_converted,
                    SUM(revenue_fen) AS total_revenue_fen
                FROM marketing_task_effects
                WHERE tenant_id = :tenant_id AND task_id = :task_id AND is_deleted = FALSE
                GROUP BY store_id
                ORDER BY total_revenue_fen DESC
            """),
            {"tenant_id": str(tenant_id), "task_id": str(task_id)},
        )
        return [dict(r) for r in result.mappings().all()]

    async def get_employee_effect(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        db: Any,
    ) -> list[dict]:
        """按员工维度统计效果"""
        result = await db.execute(
            text("""
                SELECT employee_id,
                    SUM(total_sent) AS total_sent,
                    SUM(delivered) AS total_delivered,
                    SUM(read) AS total_read,
                    SUM(converted) AS total_converted,
                    SUM(revenue_fen) AS total_revenue_fen
                FROM marketing_task_effects
                WHERE tenant_id = :tenant_id AND task_id = :task_id
                  AND is_deleted = FALSE AND employee_id IS NOT NULL
                GROUP BY employee_id
                ORDER BY total_revenue_fen DESC
            """),
            {"tenant_id": str(tenant_id), "task_id": str(task_id)},
        )
        return [dict(r) for r in result.mappings().all()]

    async def get_coupon_effect(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """优惠券效果统计"""
        result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(coupon_issued_count), 0) AS total_issued,
                    COALESCE(SUM(redeemed_count), 0) AS total_redeemed,
                    CASE WHEN COALESCE(SUM(coupon_issued_count), 0) > 0
                        THEN ROUND(SUM(redeemed_count)::NUMERIC / SUM(coupon_issued_count) * 100, 2)
                        ELSE 0
                    END AS redeem_rate,
                    COALESCE(SUM(revenue_fen), 0) AS revenue_from_coupons_fen
                FROM marketing_task_effects
                WHERE tenant_id = :tenant_id AND task_id = :task_id AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "task_id": str(task_id)},
        )
        row = result.mappings().first()
        return dict(row) if row else {}

    async def get_execution_leaderboard(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        dimension: str,
        db: Any,
        *,
        limit: int = 20,
    ) -> list[dict]:
        """执行排行榜（dimension: store/employee）"""
        if dimension == "store":
            group_col = "store_id"
        elif dimension == "employee":
            group_col = "employee_id"
        else:
            raise MarketingTaskError("INVALID_DIMENSION", f"不支持的维度: {dimension}")

        result = await db.execute(
            text(f"""
                SELECT {group_col},
                    COUNT(*) AS total_executions,
                    COUNT(*) FILTER (WHERE send_status = 'sent') AS sent_count,
                    COUNT(*) FILTER (WHERE send_status = 'delivered') AS delivered_count,
                    COUNT(*) FILTER (WHERE send_status = 'read') AS read_count,
                    COUNT(*) FILTER (WHERE send_status = 'failed') AS failed_count,
                    CASE WHEN COUNT(*) > 0
                        THEN ROUND(
                            COUNT(*) FILTER (WHERE send_status IN ('sent', 'delivered', 'read'))::NUMERIC
                            / COUNT(*) * 100, 2
                        ) ELSE 0
                    END AS success_rate
                FROM marketing_task_executions
                WHERE tenant_id = :tenant_id AND task_id = :task_id
                  AND is_deleted = FALSE AND {group_col} IS NOT NULL
                GROUP BY {group_col}
                ORDER BY sent_count DESC
                LIMIT :limit
            """),
            {
                "tenant_id": str(tenant_id),
                "task_id": str(task_id),
                "limit": limit,
            },
        )
        return [dict(r) for r in result.mappings().all()]

    # ===================================================================
    # Scheduler — 定时任务检查
    # ===================================================================

    async def check_scheduled_tasks(
        self,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """检查到期的 scheduled 任务，自动转为 executing"""
        now = datetime.now(timezone.utc)
        result = await db.execute(
            text("""
                UPDATE marketing_tasks
                SET status = 'executing', updated_at = now()
                WHERE tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND status = 'scheduled'
                  AND schedule_at IS NOT NULL
                  AND schedule_at <= :now
                RETURNING id
            """),
            {"tenant_id": str(tenant_id), "now": now},
        )
        started_ids = [str(r[0]) for r in result.fetchall()]

        # 检查已到结束时间的 executing 任务
        end_result = await db.execute(
            text("""
                UPDATE marketing_tasks
                SET status = 'completed', updated_at = now()
                WHERE tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND status = 'executing'
                  AND schedule_end_at IS NOT NULL
                  AND schedule_end_at <= :now
                RETURNING id
            """),
            {"tenant_id": str(tenant_id), "now": now},
        )
        completed_ids = [str(r[0]) for r in end_result.fetchall()]

        if started_ids or completed_ids:
            log.info(
                "marketing_tasks_schedule_check",
                tenant_id=str(tenant_id),
                started=len(started_ids),
                completed=len(completed_ids),
            )
        return {"started": len(started_ids), "completed": len(completed_ids)}
