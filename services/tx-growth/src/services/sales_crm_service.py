"""销售CRM服务 — 目标/线索/任务/拜访/画像完整度

核心功能：
  - Targets:  销售目标CRUD + 实际值更新（自动计算达成率）+ 排名
  - Leads:    线索全生命周期（漏斗/转化率/流失分析）
  - Tasks:    任务管理（创建/完成/逾期标记/统计）
  - Visits:   拜访记录（电话/微信/到店/短信）
  - Profile:  客户画像完整度评分（批量UPSERT）
  - Dashboard: 销售仪表盘（聚合所有维度）

金额单位：分(fen)
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 阶段转换验证
# ---------------------------------------------------------------------------

_VALID_STAGE_TRANSITIONS: dict[str, list[str]] = {
    "new": ["contacted", "lost"],
    "contacted": ["qualified", "lost"],
    "qualified": ["proposal", "lost"],
    "proposal": ["negotiation", "lost"],
    "negotiation": ["won", "lost"],
    "won": [],
    "lost": ["new"],  # 允许重启
}


class SalesCRMError(Exception):
    """销售CRM业务异常"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SalesCRMService:
    """销售CRM核心服务"""

    # ===================================================================
    # Targets — 销售目标
    # ===================================================================

    async def create_target(
        self,
        tenant_id: uuid.UUID,
        target_type: str,
        year: int,
        *,
        store_id: Optional[uuid.UUID] = None,
        brand_id: Optional[uuid.UUID] = None,
        employee_id: Optional[uuid.UUID] = None,
        month: Optional[int] = None,
        target_revenue_fen: int = 0,
        target_orders: int = 0,
        target_new_customers: int = 0,
        target_reservations: int = 0,
        db: Any,
    ) -> dict:
        """创建销售目标"""
        target_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO sales_targets (
                    tenant_id, id, store_id, brand_id, employee_id,
                    target_type, year, month,
                    target_revenue_fen, target_orders,
                    target_new_customers, target_reservations
                ) VALUES (
                    :tenant_id, :id, :store_id, :brand_id, :employee_id,
                    :target_type, :year, :month,
                    :target_revenue_fen, :target_orders,
                    :target_new_customers, :target_reservations
                )
            """),
            {
                "tenant_id": str(tenant_id),
                "id": str(target_id),
                "store_id": str(store_id) if store_id else None,
                "brand_id": str(brand_id) if brand_id else None,
                "employee_id": str(employee_id) if employee_id else None,
                "target_type": target_type,
                "year": year,
                "month": month,
                "target_revenue_fen": target_revenue_fen,
                "target_orders": target_orders,
                "target_new_customers": target_new_customers,
                "target_reservations": target_reservations,
            },
        )
        log.info("sales_target_created", target_id=str(target_id), target_type=target_type)
        return {"target_id": str(target_id)}

    async def list_targets(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
        year: Optional[int] = None,
        target_type: Optional[str] = None,
    ) -> list[dict]:
        """查询销售目标列表"""
        sql = """
            SELECT * FROM sales_targets
            WHERE tenant_id = :tenant_id AND is_deleted = FALSE
        """
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}

        if store_id:
            sql += " AND store_id = :store_id"
            params["store_id"] = str(store_id)
        if year:
            sql += " AND year = :year"
            params["year"] = year
        if target_type:
            sql += " AND target_type = :target_type"
            params["target_type"] = target_type

        sql += " ORDER BY year DESC, month DESC NULLS LAST"
        result = await db.execute(text(sql), params)
        rows = result.mappings().all()
        return [dict(r) for r in rows]

    async def update_target(
        self,
        tenant_id: uuid.UUID,
        target_id: uuid.UUID,
        updates: dict,
        db: Any,
    ) -> dict:
        """更新销售目标设定值"""
        allowed = {
            "target_revenue_fen", "target_orders",
            "target_new_customers", "target_reservations",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            raise SalesCRMError("EMPTY_UPDATE", "无有效更新字段")

        set_parts = [f"{k} = :{k}" for k in filtered]
        set_parts.append("updated_at = now()")
        sql = f"""
            UPDATE sales_targets SET {', '.join(set_parts)}
            WHERE tenant_id = :tenant_id AND id = :target_id AND is_deleted = FALSE
        """
        filtered["tenant_id"] = str(tenant_id)
        filtered["target_id"] = str(target_id)
        result = await db.execute(text(sql), filtered)
        if result.rowcount == 0:
            raise SalesCRMError("NOT_FOUND", "目标不存在")
        return {"updated": True}

    async def update_actuals(
        self,
        tenant_id: uuid.UUID,
        target_id: uuid.UUID,
        *,
        actual_revenue_fen: Optional[int] = None,
        actual_orders: Optional[int] = None,
        actual_new_customers: Optional[int] = None,
        actual_reservations: Optional[int] = None,
        db: Any,
    ) -> dict:
        """更新实际值并自动计算达成率"""
        set_parts = ["updated_at = now()"]
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "target_id": str(target_id),
        }
        if actual_revenue_fen is not None:
            set_parts.append("actual_revenue_fen = :actual_revenue_fen")
            params["actual_revenue_fen"] = actual_revenue_fen
        if actual_orders is not None:
            set_parts.append("actual_orders = :actual_orders")
            params["actual_orders"] = actual_orders
        if actual_new_customers is not None:
            set_parts.append("actual_new_customers = :actual_new_customers")
            params["actual_new_customers"] = actual_new_customers
        if actual_reservations is not None:
            set_parts.append("actual_reservations = :actual_reservations")
            params["actual_reservations"] = actual_reservations

        # 自动计算达成率（以营收为主）
        set_parts.append("""
            achievement_rate = CASE
                WHEN COALESCE(target_revenue_fen, 0) > 0
                THEN ROUND(
                    COALESCE(actual_revenue_fen, 0)::NUMERIC
                    / target_revenue_fen * 100, 2
                )
                ELSE 0
            END
        """)

        sql = f"""
            UPDATE sales_targets SET {', '.join(set_parts)}
            WHERE tenant_id = :tenant_id AND id = :target_id AND is_deleted = FALSE
            RETURNING achievement_rate
        """
        result = await db.execute(text(sql), params)
        row = result.fetchone()
        if row is None:
            raise SalesCRMError("NOT_FOUND", "目标不存在")
        log.info("sales_actuals_updated", target_id=str(target_id), achievement_rate=float(row[0]))
        return {"achievement_rate": float(row[0])}

    async def get_achievement_ranking(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        year: int,
        month: Optional[int] = None,
        store_id: Optional[uuid.UUID] = None,
        limit: int = 20,
    ) -> list[dict]:
        """获取达成率排名"""
        sql = """
            SELECT id, store_id, employee_id, target_type,
                   target_revenue_fen, actual_revenue_fen,
                   achievement_rate
            FROM sales_targets
            WHERE tenant_id = :tenant_id AND year = :year AND is_deleted = FALSE
        """
        params: dict[str, Any] = {"tenant_id": str(tenant_id), "year": year}
        if month:
            sql += " AND month = :month"
            params["month"] = month
        if store_id:
            sql += " AND store_id = :store_id"
            params["store_id"] = str(store_id)
        sql += " ORDER BY achievement_rate DESC LIMIT :limit"
        params["limit"] = limit

        result = await db.execute(text(sql), params)
        return [dict(r) for r in result.mappings().all()]

    # ===================================================================
    # Leads — 销售线索
    # ===================================================================

    async def create_lead(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        *,
        customer_name: Optional[str] = None,
        customer_phone: Optional[str] = None,
        customer_id: Optional[uuid.UUID] = None,
        lead_source: str = "other",
        lead_type: str = "dining",
        expected_revenue_fen: Optional[int] = None,
        expected_date: Optional[date] = None,
        assigned_to: Optional[uuid.UUID] = None,
        priority: str = "medium",
        notes: Optional[str] = None,
        db: Any,
    ) -> dict:
        """创建销售线索"""
        lead_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO sales_leads (
                    tenant_id, id, store_id, customer_id,
                    customer_name, customer_phone,
                    lead_source, lead_type, stage,
                    expected_revenue_fen, expected_date,
                    assigned_to, priority, notes
                ) VALUES (
                    :tenant_id, :id, :store_id, :customer_id,
                    :customer_name, :customer_phone,
                    :lead_source, :lead_type, 'new',
                    :expected_revenue_fen, :expected_date,
                    :assigned_to, :priority, :notes
                )
            """),
            {
                "tenant_id": str(tenant_id),
                "id": str(lead_id),
                "store_id": str(store_id),
                "customer_id": str(customer_id) if customer_id else None,
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "lead_source": lead_source,
                "lead_type": lead_type,
                "expected_revenue_fen": expected_revenue_fen,
                "expected_date": expected_date,
                "assigned_to": str(assigned_to) if assigned_to else None,
                "priority": priority,
                "notes": notes,
            },
        )
        log.info("sales_lead_created", lead_id=str(lead_id), source=lead_source)
        return {"lead_id": str(lead_id)}

    async def list_leads(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
        stage: Optional[str] = None,
        assigned_to: Optional[uuid.UUID] = None,
        lead_source: Optional[str] = None,
        priority: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询线索列表"""
        where = "tenant_id = :tenant_id AND is_deleted = FALSE"
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}

        if store_id:
            where += " AND store_id = :store_id"
            params["store_id"] = str(store_id)
        if stage:
            where += " AND stage = :stage"
            params["stage"] = stage
        if assigned_to:
            where += " AND assigned_to = :assigned_to"
            params["assigned_to"] = str(assigned_to)
        if lead_source:
            where += " AND lead_source = :lead_source"
            params["lead_source"] = lead_source
        if priority:
            where += " AND priority = :priority"
            params["priority"] = priority

        count_sql = f"SELECT COUNT(*) FROM sales_leads WHERE {where}"
        count_result = await db.execute(text(count_sql), params)
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        data_sql = f"""
            SELECT * FROM sales_leads WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = size
        params["offset"] = offset
        result = await db.execute(text(data_sql), params)
        items = [dict(r) for r in result.mappings().all()]

        return {"items": items, "total": total, "page": page, "size": size}

    async def get_lead(
        self,
        tenant_id: uuid.UUID,
        lead_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """获取线索详情"""
        result = await db.execute(
            text("""
                SELECT * FROM sales_leads
                WHERE tenant_id = :tenant_id AND id = :lead_id AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "lead_id": str(lead_id)},
        )
        row = result.mappings().first()
        if row is None:
            raise SalesCRMError("NOT_FOUND", "线索不存在")
        return dict(row)

    async def advance_stage(
        self,
        tenant_id: uuid.UUID,
        lead_id: uuid.UUID,
        new_stage: str,
        db: Any,
        *,
        lost_reason: Optional[str] = None,
        won_order_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """推进线索阶段（含转换验证）"""
        lead = await self.get_lead(tenant_id, lead_id, db)
        current = lead["stage"]
        valid_next = _VALID_STAGE_TRANSITIONS.get(current, [])
        if new_stage not in valid_next:
            raise SalesCRMError(
                "INVALID_TRANSITION",
                f"不允许从 {current} 转换到 {new_stage}，有效: {valid_next}",
            )

        set_parts = ["stage = :new_stage", "updated_at = now()"]
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "lead_id": str(lead_id),
            "new_stage": new_stage,
        }
        if new_stage == "lost" and lost_reason:
            set_parts.append("lost_reason = :lost_reason")
            params["lost_reason"] = lost_reason
        if new_stage == "won" and won_order_id:
            set_parts.append("won_order_id = :won_order_id")
            params["won_order_id"] = str(won_order_id)

        sql = f"""
            UPDATE sales_leads SET {', '.join(set_parts)}
            WHERE tenant_id = :tenant_id AND id = :lead_id AND is_deleted = FALSE
        """
        await db.execute(text(sql), params)
        log.info("sales_lead_stage_advanced", lead_id=str(lead_id), from_stage=current, to_stage=new_stage)
        return {"lead_id": str(lead_id), "from_stage": current, "to_stage": new_stage}

    async def assign_lead(
        self,
        tenant_id: uuid.UUID,
        lead_id: uuid.UUID,
        assigned_to: uuid.UUID,
        db: Any,
    ) -> dict:
        """分配线索给员工"""
        result = await db.execute(
            text("""
                UPDATE sales_leads
                SET assigned_to = :assigned_to, updated_at = now()
                WHERE tenant_id = :tenant_id AND id = :lead_id AND is_deleted = FALSE
            """),
            {
                "tenant_id": str(tenant_id),
                "lead_id": str(lead_id),
                "assigned_to": str(assigned_to),
            },
        )
        if result.rowcount == 0:
            raise SalesCRMError("NOT_FOUND", "线索不存在")
        return {"assigned_to": str(assigned_to)}

    async def get_funnel(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
    ) -> list[dict]:
        """获取销售漏斗统计"""
        sql = """
            SELECT stage, COUNT(*) as count,
                   COALESCE(SUM(expected_revenue_fen), 0) as total_expected_fen
            FROM sales_leads
            WHERE tenant_id = :tenant_id AND is_deleted = FALSE
        """
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}
        if store_id:
            sql += " AND store_id = :store_id"
            params["store_id"] = str(store_id)
        sql += " GROUP BY stage ORDER BY ARRAY_POSITION(ARRAY['new','contacted','qualified','proposal','negotiation','won','lost'], stage)"

        result = await db.execute(text(sql), params)
        return [dict(r) for r in result.mappings().all()]

    async def get_conversion_stats(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
        days: int = 30,
    ) -> dict:
        """获取转化率统计"""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        where = "tenant_id = :tenant_id AND is_deleted = FALSE AND created_at >= :since"
        params: dict[str, Any] = {"tenant_id": str(tenant_id), "since": since}
        if store_id:
            where += " AND store_id = :store_id"
            params["store_id"] = str(store_id)

        sql = f"""
            SELECT
                COUNT(*) as total_leads,
                COUNT(*) FILTER (WHERE stage = 'won') as won,
                COUNT(*) FILTER (WHERE stage = 'lost') as lost,
                COALESCE(SUM(expected_revenue_fen) FILTER (WHERE stage = 'won'), 0) as won_revenue_fen,
                CASE WHEN COUNT(*) > 0
                    THEN ROUND(COUNT(*) FILTER (WHERE stage = 'won')::NUMERIC / COUNT(*) * 100, 2)
                    ELSE 0
                END as win_rate
            FROM sales_leads WHERE {where}
        """
        result = await db.execute(text(sql), params)
        row = result.mappings().first()
        return dict(row) if row else {}

    async def get_lost_reasons(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
        days: int = 90,
    ) -> list[dict]:
        """获取流失原因统计"""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        sql = """
            SELECT lost_reason, COUNT(*) as count
            FROM sales_leads
            WHERE tenant_id = :tenant_id AND is_deleted = FALSE
              AND stage = 'lost' AND lost_reason IS NOT NULL
              AND updated_at >= :since
        """
        params: dict[str, Any] = {"tenant_id": str(tenant_id), "since": since}
        if store_id:
            sql += " AND store_id = :store_id"
            params["store_id"] = str(store_id)
        sql += " GROUP BY lost_reason ORDER BY count DESC"

        result = await db.execute(text(sql), params)
        return [dict(r) for r in result.mappings().all()]

    # ===================================================================
    # Tasks — 销售任务
    # ===================================================================

    async def create_task(
        self,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        title: str,
        task_type: str,
        due_at: datetime,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
        related_lead_id: Optional[uuid.UUID] = None,
        related_customer_id: Optional[uuid.UUID] = None,
        description: Optional[str] = None,
        priority: str = "medium",
        reminder_at: Optional[datetime] = None,
    ) -> dict:
        """创建销售任务"""
        task_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO sales_tasks (
                    tenant_id, id, store_id, employee_id,
                    task_type, related_lead_id, related_customer_id,
                    title, description, due_at, priority, reminder_at
                ) VALUES (
                    :tenant_id, :id, :store_id, :employee_id,
                    :task_type, :related_lead_id, :related_customer_id,
                    :title, :description, :due_at, :priority, :reminder_at
                )
            """),
            {
                "tenant_id": str(tenant_id),
                "id": str(task_id),
                "store_id": str(store_id) if store_id else None,
                "employee_id": str(employee_id),
                "task_type": task_type,
                "related_lead_id": str(related_lead_id) if related_lead_id else None,
                "related_customer_id": str(related_customer_id) if related_customer_id else None,
                "title": title,
                "description": description,
                "due_at": due_at,
                "priority": priority,
                "reminder_at": reminder_at,
            },
        )
        log.info("sales_task_created", task_id=str(task_id), task_type=task_type)
        return {"task_id": str(task_id)}

    async def list_tasks(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
        employee_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询任务列表"""
        where = "tenant_id = :tenant_id AND is_deleted = FALSE"
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}

        if store_id:
            where += " AND store_id = :store_id"
            params["store_id"] = str(store_id)
        if employee_id:
            where += " AND employee_id = :employee_id"
            params["employee_id"] = str(employee_id)
        if status:
            where += " AND status = :status"
            params["status"] = status
        if task_type:
            where += " AND task_type = :task_type"
            params["task_type"] = task_type

        count_result = await db.execute(text(f"SELECT COUNT(*) FROM sales_tasks WHERE {where}"), params)
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        data_sql = f"""
            SELECT * FROM sales_tasks WHERE {where}
            ORDER BY due_at ASC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = size
        params["offset"] = offset
        result = await db.execute(text(data_sql), params)
        items = [dict(r) for r in result.mappings().all()]
        return {"items": items, "total": total, "page": page, "size": size}

    async def get_my_tasks(
        self,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        db: Any,
        *,
        status: Optional[str] = None,
        include_overdue: bool = True,
    ) -> list[dict]:
        """获取我的任务（含逾期）"""
        sql = """
            SELECT * FROM sales_tasks
            WHERE tenant_id = :tenant_id AND employee_id = :employee_id AND is_deleted = FALSE
        """
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "employee_id": str(employee_id),
        }
        if status:
            sql += " AND status = :status"
            params["status"] = status
        elif not include_overdue:
            sql += " AND status IN ('pending', 'in_progress')"
        else:
            sql += " AND status IN ('pending', 'in_progress', 'overdue')"

        sql += " ORDER BY CASE WHEN status = 'overdue' THEN 0 ELSE 1 END, due_at ASC"
        result = await db.execute(text(sql), params)
        return [dict(r) for r in result.mappings().all()]

    async def complete_task(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        db: Any,
        *,
        result_text: Optional[str] = None,
    ) -> dict:
        """完成任务"""
        res = await db.execute(
            text("""
                UPDATE sales_tasks
                SET status = 'completed',
                    completed_at = now(),
                    result = :result_text,
                    updated_at = now()
                WHERE tenant_id = :tenant_id AND id = :task_id
                  AND is_deleted = FALSE AND status IN ('pending', 'in_progress', 'overdue')
            """),
            {
                "tenant_id": str(tenant_id),
                "task_id": str(task_id),
                "result_text": result_text,
            },
        )
        if res.rowcount == 0:
            raise SalesCRMError("NOT_FOUND", "任务不存在或已完成")
        log.info("sales_task_completed", task_id=str(task_id))
        return {"completed": True}

    async def get_task_stats(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
        employee_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """获取任务统计"""
        where = "tenant_id = :tenant_id AND is_deleted = FALSE"
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}
        if store_id:
            where += " AND store_id = :store_id"
            params["store_id"] = str(store_id)
        if employee_id:
            where += " AND employee_id = :employee_id"
            params["employee_id"] = str(employee_id)

        sql = f"""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'overdue') as overdue,
                COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled,
                CASE WHEN COUNT(*) > 0
                    THEN ROUND(
                        COUNT(*) FILTER (WHERE status = 'completed')::NUMERIC / COUNT(*) * 100, 2
                    ) ELSE 0
                END as completion_rate
            FROM sales_tasks WHERE {where}
        """
        result = await db.execute(text(sql), params)
        row = result.mappings().first()
        return dict(row) if row else {}

    async def mark_overdue(
        self,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """标记逾期任务"""
        result = await db.execute(
            text("""
                UPDATE sales_tasks
                SET status = 'overdue', updated_at = now()
                WHERE tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND status IN ('pending', 'in_progress')
                  AND due_at < now()
            """),
            {"tenant_id": str(tenant_id)},
        )
        count = result.rowcount
        if count > 0:
            log.info("sales_tasks_marked_overdue", tenant_id=str(tenant_id), count=count)
        return {"marked_overdue": count}

    # ===================================================================
    # Visits — 拜访记录
    # ===================================================================

    async def create_visit(
        self,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        customer_id: uuid.UUID,
        visit_type: str,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
        purpose: Optional[str] = None,
        summary: Optional[str] = None,
        customer_satisfaction: Optional[int] = None,
        next_action: Optional[str] = None,
        next_action_date: Optional[date] = None,
    ) -> dict:
        """创建拜访记录"""
        visit_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO sales_visit_logs (
                    tenant_id, id, store_id, employee_id, customer_id,
                    visit_type, purpose, summary,
                    customer_satisfaction, next_action, next_action_date
                ) VALUES (
                    :tenant_id, :id, :store_id, :employee_id, :customer_id,
                    :visit_type, :purpose, :summary,
                    :customer_satisfaction, :next_action, :next_action_date
                )
            """),
            {
                "tenant_id": str(tenant_id),
                "id": str(visit_id),
                "store_id": str(store_id) if store_id else None,
                "employee_id": str(employee_id),
                "customer_id": str(customer_id),
                "visit_type": visit_type,
                "purpose": purpose,
                "summary": summary,
                "customer_satisfaction": customer_satisfaction,
                "next_action": next_action,
                "next_action_date": next_action_date,
            },
        )
        log.info("sales_visit_created", visit_id=str(visit_id), visit_type=visit_type)
        return {"visit_id": str(visit_id)}

    async def list_visits(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
        employee_id: Optional[uuid.UUID] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询拜访记录"""
        where = "tenant_id = :tenant_id AND is_deleted = FALSE"
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}
        if store_id:
            where += " AND store_id = :store_id"
            params["store_id"] = str(store_id)
        if employee_id:
            where += " AND employee_id = :employee_id"
            params["employee_id"] = str(employee_id)

        count_result = await db.execute(text(f"SELECT COUNT(*) FROM sales_visit_logs WHERE {where}"), params)
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        data_sql = f"""
            SELECT * FROM sales_visit_logs WHERE {where}
            ORDER BY created_at DESC LIMIT :limit OFFSET :offset
        """
        params["limit"] = size
        params["offset"] = offset
        result = await db.execute(text(data_sql), params)
        items = [dict(r) for r in result.mappings().all()]
        return {"items": items, "total": total, "page": page, "size": size}

    async def get_customer_visits(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        db: Any,
        *,
        limit: int = 50,
    ) -> list[dict]:
        """获取指定客户的拜访记录"""
        result = await db.execute(
            text("""
                SELECT * FROM sales_visit_logs
                WHERE tenant_id = :tenant_id AND customer_id = :customer_id AND is_deleted = FALSE
                ORDER BY created_at DESC LIMIT :limit
            """),
            {"tenant_id": str(tenant_id), "customer_id": str(customer_id), "limit": limit},
        )
        return [dict(r) for r in result.mappings().all()]

    # ===================================================================
    # Profile — 客户画像完整度
    # ===================================================================

    async def calculate_profile_scores(
        self,
        tenant_id: uuid.UUID,
        customer_ids: list[uuid.UUID],
        customer_data: list[dict],
        db: Any,
    ) -> dict:
        """批量计算并UPSERT客户画像完整度评分

        customer_data: [{customer_id, name, phone, birthday, anniversary, company, preference, allergy, service_req}]
        """
        if not customer_data:
            return {"upserted": 0}

        # 定义权重
        weights = {
            "has_name": 15,
            "has_phone": 15,
            "has_birthday": 15,
            "has_anniversary": 10,
            "has_company": 10,
            "has_preference": 15,
            "has_allergy": 10,
            "has_service_req": 10,
        }

        values_parts = []
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}

        for i, cd in enumerate(customer_data):
            has_name = bool(cd.get("name"))
            has_phone = bool(cd.get("phone"))
            has_birthday = bool(cd.get("birthday"))
            has_anniversary = bool(cd.get("anniversary"))
            has_company = bool(cd.get("company"))
            has_preference = bool(cd.get("preference"))
            has_allergy = bool(cd.get("allergy"))
            has_service_req = bool(cd.get("service_req"))

            score = sum([
                weights["has_name"] if has_name else 0,
                weights["has_phone"] if has_phone else 0,
                weights["has_birthday"] if has_birthday else 0,
                weights["has_anniversary"] if has_anniversary else 0,
                weights["has_company"] if has_company else 0,
                weights["has_preference"] if has_preference else 0,
                weights["has_allergy"] if has_allergy else 0,
                weights["has_service_req"] if has_service_req else 0,
            ])

            params[f"cid_{i}"] = str(cd["customer_id"])
            params[f"hn_{i}"] = has_name
            params[f"hp_{i}"] = has_phone
            params[f"hb_{i}"] = has_birthday
            params[f"ha_{i}"] = has_anniversary
            params[f"hc_{i}"] = has_company
            params[f"hpf_{i}"] = has_preference
            params[f"hal_{i}"] = has_allergy
            params[f"hs_{i}"] = has_service_req
            params[f"sc_{i}"] = score

            values_parts.append(
                f"(:tenant_id, :cid_{i}, :hn_{i}, :hp_{i}, :hb_{i}, :ha_{i}, "
                f":hc_{i}, :hpf_{i}, :hal_{i}, :hs_{i}, :sc_{i})"
            )

        sql = f"""
            INSERT INTO customer_profile_scores (
                tenant_id, customer_id,
                has_name, has_phone, has_birthday, has_anniversary,
                has_company, has_preference, has_allergy, has_service_req,
                completeness_score
            ) VALUES {', '.join(values_parts)}
            ON CONFLICT (tenant_id, customer_id) DO UPDATE SET
                has_name = EXCLUDED.has_name,
                has_phone = EXCLUDED.has_phone,
                has_birthday = EXCLUDED.has_birthday,
                has_anniversary = EXCLUDED.has_anniversary,
                has_company = EXCLUDED.has_company,
                has_preference = EXCLUDED.has_preference,
                has_allergy = EXCLUDED.has_allergy,
                has_service_req = EXCLUDED.has_service_req,
                completeness_score = EXCLUDED.completeness_score,
                scored_at = now(),
                updated_at = now()
        """
        await db.execute(text(sql), params)
        log.info("profile_scores_upserted", tenant_id=str(tenant_id), count=len(customer_data))
        return {"upserted": len(customer_data)}

    async def get_profile_ranking(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        limit: int = 50,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
        order: str = "asc",
    ) -> list[dict]:
        """获取画像完整度排名（默认升序=最需完善的在前）"""
        sql = """
            SELECT * FROM customer_profile_scores
            WHERE tenant_id = :tenant_id AND is_deleted = FALSE
        """
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}
        if min_score is not None:
            sql += " AND completeness_score >= :min_score"
            params["min_score"] = min_score
        if max_score is not None:
            sql += " AND completeness_score <= :max_score"
            params["max_score"] = max_score

        direction = "ASC" if order == "asc" else "DESC"
        sql += f" ORDER BY completeness_score {direction} LIMIT :limit"
        params["limit"] = limit

        result = await db.execute(text(sql), params)
        return [dict(r) for r in result.mappings().all()]

    # ===================================================================
    # Dashboard — 销售仪表盘
    # ===================================================================

    async def get_sales_dashboard(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """聚合销售仪表盘数据"""
        now = datetime.now(timezone.utc)
        current_year = now.year
        current_month = now.month

        # 当月目标达成
        target_sql = """
            SELECT
                COALESCE(SUM(target_revenue_fen), 0) as target_revenue_fen,
                COALESCE(SUM(actual_revenue_fen), 0) as actual_revenue_fen,
                COALESCE(SUM(target_orders), 0) as target_orders,
                COALESCE(SUM(actual_orders), 0) as actual_orders,
                CASE WHEN COALESCE(SUM(target_revenue_fen), 0) > 0
                    THEN ROUND(
                        SUM(actual_revenue_fen)::NUMERIC / SUM(target_revenue_fen) * 100, 2
                    ) ELSE 0
                END as overall_achievement
            FROM sales_targets
            WHERE tenant_id = :tenant_id AND is_deleted = FALSE
              AND year = :year AND month = :month AND target_type = 'monthly'
        """
        target_params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "year": current_year,
            "month": current_month,
        }
        if store_id:
            target_sql += " AND store_id = :store_id"
            target_params["store_id"] = str(store_id)

        target_result = await db.execute(text(target_sql), target_params)
        target_data = dict(target_result.mappings().first() or {})

        # 线索漏斗
        funnel = await self.get_funnel(tenant_id, db, store_id=store_id)

        # 任务统计
        task_stats = await self.get_task_stats(tenant_id, db, store_id=store_id)

        # 近30天转化率
        conversion = await self.get_conversion_stats(tenant_id, db, store_id=store_id, days=30)

        # 画像完整度分布
        profile_sql = """
            SELECT
                COUNT(*) as total_customers,
                COUNT(*) FILTER (WHERE completeness_score >= 80) as high_completeness,
                COUNT(*) FILTER (WHERE completeness_score >= 40 AND completeness_score < 80) as medium_completeness,
                COUNT(*) FILTER (WHERE completeness_score < 40) as low_completeness,
                COALESCE(ROUND(AVG(completeness_score), 2), 0) as avg_score
            FROM customer_profile_scores
            WHERE tenant_id = :tenant_id AND is_deleted = FALSE
        """
        profile_result = await db.execute(text(profile_sql), {"tenant_id": str(tenant_id)})
        profile_data = dict(profile_result.mappings().first() or {})

        return {
            "targets": target_data,
            "funnel": funnel,
            "tasks": task_stats,
            "conversion": conversion,
            "profile_completeness": profile_data,
        }
