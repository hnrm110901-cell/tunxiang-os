"""销售任务自动调度器 — 每日凌晨扫描生成提醒任务

自动生成任务类型：
  - birthday_remind:      生日提醒（3天前瞻）
  - anniversary_remind:   纪念日提醒
  - dormant_recall:       沉默客户召回（30+天未到店）
  - reservation_confirm:  当日预订确认
  - 逾期标记:             自动将到期未完成任务标记为 overdue

运行频率：每日凌晨 02:30（APScheduler cron）
"""

import uuid
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)


class SalesTaskScheduler:
    """销售任务每日自动扫描调度器"""

    async def run_daily_scan(self, tenant_id: str, db: Any) -> dict:
        """执行每日全量扫描，返回各类任务生成数量

        Args:
            tenant_id: 租户ID
            db: AsyncSession（已设置 app.tenant_id）

        Returns:
            {birthday: N, anniversary: N, dormant: N, reservation: N, overdue: N}
        """
        tid = tenant_id
        today = date.today()
        results: dict[str, int] = {}

        results["birthday"] = await self._create_birthday_reminders(tid, today, db)
        results["anniversary"] = await self._create_anniversary_reminders(tid, today, db)
        results["dormant"] = await self._create_dormant_recalls(tid, today, db)
        results["reservation"] = await self._create_reservation_confirms(tid, today, db)
        results["overdue"] = await self._mark_overdue_tasks(tid, db)

        total = sum(results.values())
        log.info(
            "sales_daily_scan_done",
            tenant_id=tid,
            total=total,
            **results,
        )
        return results

    async def _create_birthday_reminders(self, tenant_id: str, today: date, db: Any) -> int:
        """生日提醒：3天前瞻，查找即将过生日的客户并创建提醒任务

        避免重复：同一客户同一天不重复创建。
        """
        # 查找3天内过生日的客户（按月日匹配）
        lookahead_dates = [(today + timedelta(days=i)) for i in range(4)]
        month_day_pairs = [(d.month, d.day) for d in lookahead_dates]

        # 构建 OR 条件
        conditions = " OR ".join(
            [f"(EXTRACT(MONTH FROM birthday) = {m} AND EXTRACT(DAY FROM birthday) = {d})" for m, d in month_day_pairs]
        )

        sql = f"""
            SELECT c.id as customer_id, c.name, c.birthday, c.store_id
            FROM customers c
            WHERE c.tenant_id = :tenant_id
              AND c.is_deleted = FALSE
              AND c.birthday IS NOT NULL
              AND ({conditions})
              AND NOT EXISTS (
                  SELECT 1 FROM sales_tasks st
                  WHERE st.tenant_id = :tenant_id
                    AND st.related_customer_id = c.id
                    AND st.task_type = 'birthday_remind'
                    AND st.due_at::DATE = c.birthday::DATE + (EXTRACT(YEAR FROM CURRENT_DATE) - EXTRACT(YEAR FROM c.birthday)) * INTERVAL '1 year'
                    AND st.is_deleted = FALSE
              )
        """
        result = await db.execute(text(sql), {"tenant_id": tenant_id})
        rows = result.mappings().all()

        created = 0
        for row in rows:
            # 分配给门店默认负责人（如果没有，后续由管理员手动分配）
            birthday = row["birthday"]
            birth_this_year = birthday.replace(year=today.year)

            await db.execute(
                text("""
                    INSERT INTO sales_tasks (
                        tenant_id, id, store_id, employee_id,
                        task_type, related_customer_id,
                        title, description, due_at, priority
                    ) VALUES (
                        :tenant_id, :id, :store_id,
                        COALESCE(
                            (SELECT id FROM employees WHERE tenant_id = :tenant_id AND store_id = :store_id AND role = 'store_manager' AND is_deleted = FALSE LIMIT 1),
                            (SELECT id FROM employees WHERE tenant_id = :tenant_id AND store_id = :store_id AND is_deleted = FALSE LIMIT 1)
                        ),
                        'birthday_remind', :customer_id,
                        :title, :description, :due_at, 'high'
                    )
                """),
                {
                    "tenant_id": tenant_id,
                    "id": str(uuid.uuid4()),
                    "store_id": str(row["store_id"]) if row.get("store_id") else None,
                    "customer_id": str(row["customer_id"]),
                    "title": f"生日提醒: {row.get('name', '未知客户')} {birth_this_year.strftime('%m-%d')}",
                    "description": f"客户 {row.get('name', '')} 即将在 {birth_this_year.strftime('%m月%d日')} 过生日，请提前联系祝福并推荐生日专享优惠。",
                    "due_at": datetime.combine(birth_this_year - timedelta(days=1), datetime.min.time()),
                },
            )
            created += 1

        return created

    async def _create_anniversary_reminders(self, tenant_id: str, today: date, db: Any) -> int:
        """纪念日提醒：3天前瞻"""
        lookahead_dates = [(today + timedelta(days=i)) for i in range(4)]
        conditions = " OR ".join(
            [
                f"(EXTRACT(MONTH FROM anniversary) = {d.month} AND EXTRACT(DAY FROM anniversary) = {d.day})"
                for d in lookahead_dates
            ]
        )

        sql = f"""
            SELECT c.id as customer_id, c.name, c.anniversary, c.store_id
            FROM customers c
            WHERE c.tenant_id = :tenant_id
              AND c.is_deleted = FALSE
              AND c.anniversary IS NOT NULL
              AND ({conditions})
              AND NOT EXISTS (
                  SELECT 1 FROM sales_tasks st
                  WHERE st.tenant_id = :tenant_id
                    AND st.related_customer_id = c.id
                    AND st.task_type = 'anniversary_remind'
                    AND EXTRACT(YEAR FROM st.created_at) = EXTRACT(YEAR FROM CURRENT_DATE)
                    AND st.is_deleted = FALSE
              )
        """
        result = await db.execute(text(sql), {"tenant_id": tenant_id})
        rows = result.mappings().all()

        created = 0
        for row in rows:
            anniv = row["anniversary"]
            anniv_this_year = anniv.replace(year=today.year)
            await db.execute(
                text("""
                    INSERT INTO sales_tasks (
                        tenant_id, id, store_id, employee_id,
                        task_type, related_customer_id,
                        title, description, due_at, priority
                    ) VALUES (
                        :tenant_id, :id, :store_id,
                        COALESCE(
                            (SELECT id FROM employees WHERE tenant_id = :tenant_id AND store_id = :store_id AND role = 'store_manager' AND is_deleted = FALSE LIMIT 1),
                            (SELECT id FROM employees WHERE tenant_id = :tenant_id AND store_id = :store_id AND is_deleted = FALSE LIMIT 1)
                        ),
                        'anniversary_remind', :customer_id,
                        :title, :description, :due_at, 'medium'
                    )
                """),
                {
                    "tenant_id": tenant_id,
                    "id": str(uuid.uuid4()),
                    "store_id": str(row["store_id"]) if row.get("store_id") else None,
                    "customer_id": str(row["customer_id"]),
                    "title": f"纪念日提醒: {row.get('name', '未知客户')} {anniv_this_year.strftime('%m-%d')}",
                    "description": f"客户 {row.get('name', '')} 的纪念日为 {anniv_this_year.strftime('%m月%d日')}，可推荐纪念日套餐。",
                    "due_at": datetime.combine(anniv_this_year - timedelta(days=1), datetime.min.time()),
                },
            )
            created += 1

        return created

    async def _create_dormant_recalls(self, tenant_id: str, today: date, db: Any) -> int:
        """沉默客户召回：30+天未到店"""
        cutoff = today - timedelta(days=30)
        sql = """
            SELECT c.id as customer_id, c.name, c.store_id, c.last_visit_at
            FROM customers c
            WHERE c.tenant_id = :tenant_id
              AND c.is_deleted = FALSE
              AND c.last_visit_at IS NOT NULL
              AND c.last_visit_at::DATE < :cutoff
              AND NOT EXISTS (
                  SELECT 1 FROM sales_tasks st
                  WHERE st.tenant_id = :tenant_id
                    AND st.related_customer_id = c.id
                    AND st.task_type = 'dormant_recall'
                    AND st.status IN ('pending', 'in_progress')
                    AND st.is_deleted = FALSE
              )
            LIMIT 200
        """
        result = await db.execute(text(sql), {"tenant_id": tenant_id, "cutoff": cutoff})
        rows = result.mappings().all()

        created = 0
        for row in rows:
            days_inactive = (today - row["last_visit_at"].date()).days if row.get("last_visit_at") else 30
            await db.execute(
                text("""
                    INSERT INTO sales_tasks (
                        tenant_id, id, store_id, employee_id,
                        task_type, related_customer_id,
                        title, description, due_at, priority
                    ) VALUES (
                        :tenant_id, :id, :store_id,
                        COALESCE(
                            (SELECT id FROM employees WHERE tenant_id = :tenant_id AND store_id = :store_id AND role = 'store_manager' AND is_deleted = FALSE LIMIT 1),
                            (SELECT id FROM employees WHERE tenant_id = :tenant_id AND store_id = :store_id AND is_deleted = FALSE LIMIT 1)
                        ),
                        'dormant_recall', :customer_id,
                        :title, :description, :due_at, :priority
                    )
                """),
                {
                    "tenant_id": tenant_id,
                    "id": str(uuid.uuid4()),
                    "store_id": str(row["store_id"]) if row.get("store_id") else None,
                    "customer_id": str(row["customer_id"]),
                    "title": f"沉默召回: {row.get('name', '未知客户')} ({days_inactive}天未到店)",
                    "description": f"客户 {row.get('name', '')} 已 {days_inactive} 天未到店消费，建议电话或微信关怀。",
                    "due_at": datetime.combine(today + timedelta(days=1), datetime.min.time()),
                    "priority": "high" if days_inactive >= 60 else "medium",
                },
            )
            created += 1

        return created

    async def _create_reservation_confirms(self, tenant_id: str, today: date, db: Any) -> int:
        """当日预订确认任务"""
        sql = """
            SELECT r.id as reservation_id, r.customer_id, r.customer_name,
                   r.store_id, r.reserved_at, r.party_size
            FROM reservations r
            WHERE r.tenant_id = :tenant_id
              AND r.is_deleted = FALSE
              AND r.status = 'confirmed'
              AND r.reserved_at::DATE = :today
              AND NOT EXISTS (
                  SELECT 1 FROM sales_tasks st
                  WHERE st.tenant_id = :tenant_id
                    AND st.related_customer_id = r.customer_id
                    AND st.task_type = 'reservation_confirm'
                    AND st.due_at::DATE = :today
                    AND st.is_deleted = FALSE
              )
        """
        result = await db.execute(text(sql), {"tenant_id": tenant_id, "today": today})
        rows = result.mappings().all()

        created = 0
        for row in rows:
            reserved_time = row["reserved_at"].strftime("%H:%M") if row.get("reserved_at") else "未知"
            await db.execute(
                text("""
                    INSERT INTO sales_tasks (
                        tenant_id, id, store_id, employee_id,
                        task_type, related_customer_id,
                        title, description, due_at, priority
                    ) VALUES (
                        :tenant_id, :id, :store_id,
                        COALESCE(
                            (SELECT id FROM employees WHERE tenant_id = :tenant_id AND store_id = :store_id AND role = 'store_manager' AND is_deleted = FALSE LIMIT 1),
                            (SELECT id FROM employees WHERE tenant_id = :tenant_id AND store_id = :store_id AND is_deleted = FALSE LIMIT 1)
                        ),
                        'reservation_confirm', :customer_id,
                        :title, :description, :due_at, 'high'
                    )
                """),
                {
                    "tenant_id": tenant_id,
                    "id": str(uuid.uuid4()),
                    "store_id": str(row["store_id"]) if row.get("store_id") else None,
                    "customer_id": str(row["customer_id"]) if row.get("customer_id") else None,
                    "title": f"预订确认: {row.get('customer_name', '客户')} {reserved_time} {row.get('party_size', '')}人",
                    "description": f"今日预订确认，预约时间 {reserved_time}，{row.get('party_size', '')}人就餐，请电话确认到店情况。",
                    "due_at": datetime.combine(today, datetime.min.time().replace(hour=10)),
                },
            )
            created += 1

        return created

    async def _mark_overdue_tasks(self, tenant_id: str, db: Any) -> int:
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
            {"tenant_id": tenant_id},
        )
        return result.rowcount
