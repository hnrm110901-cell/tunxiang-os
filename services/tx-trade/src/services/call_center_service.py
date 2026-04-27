"""呼叫中心服务 — 预订电话集成

来电弹屏 · 客户自动匹配 · 通话记录 · 回拨任务 · 统计分析
"""

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class CallCenterService:
    """预订电话集成核心服务"""

    # ──────────────────────────────────────────────
    # 1. 来电处理
    # ──────────────────────────────────────────────

    @staticmethod
    async def handle_incoming_call(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        caller_phone: str,
        agent_ext: Optional[str] = None,
    ) -> dict[str, Any]:
        """处理来电：创建通话记录 + 匹配客户 + 返回客户画像 + 近期预订/订单"""
        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )

        # 插入通话记录
        call_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                INSERT INTO call_records
                    (tenant_id, id, store_id, caller_phone, call_type, agent_ext, status, started_at)
                VALUES
                    (:tid, :cid, :sid, :phone, 'inbound', :ext, 'ringing', :now)
            """),
            {
                "tid": str(tenant_id),
                "cid": str(call_id),
                "sid": str(store_id),
                "phone": caller_phone,
                "ext": agent_ext,
                "now": now,
            },
        )

        # 按手机号匹配客户
        customer_row = await db.execute(
            text("""
                SELECT id, name, phone, membership_level, total_spend_fen, visit_count
                FROM customers
                WHERE tenant_id = :tid AND phone = :phone AND is_deleted = FALSE
                LIMIT 1
            """),
            {"tid": str(tenant_id), "phone": caller_phone},
        )
        customer = customer_row.mappings().first()

        customer_profile: Optional[dict] = None
        recent_reservations: list[dict] = []
        recent_orders: list[dict] = []

        if customer:
            customer_profile = dict(customer)
            cust_id = str(customer["id"])

            # 写入匹配记录
            await db.execute(
                text("""
                    INSERT INTO call_customer_matches
                        (tenant_id, id, call_record_id, customer_id, match_type, confidence)
                    VALUES
                        (:tid, :mid, :cid, :cust_id, 'phone_exact', 1.00)
                """),
                {
                    "tid": str(tenant_id),
                    "mid": str(uuid.uuid4()),
                    "cid": str(call_id),
                    "cust_id": cust_id,
                },
            )

            # 更新通话记录关联客户
            await db.execute(
                text("""
                    UPDATE call_records SET customer_id = :cust_id, caller_name = :name
                    WHERE id = :cid
                """),
                {"cust_id": cust_id, "name": customer["name"], "cid": str(call_id)},
            )

            # 近期预订（最近5条）
            res_rows = await db.execute(
                text("""
                    SELECT id, store_id, party_size, reservation_date, reservation_time, status
                    FROM reservations
                    WHERE tenant_id = :tid AND customer_id = :cust_id AND is_deleted = FALSE
                    ORDER BY reservation_date DESC
                    LIMIT 5
                """),
                {"tid": str(tenant_id), "cust_id": cust_id},
            )
            recent_reservations = [dict(r) for r in res_rows.mappings().all()]

            # 近期订单（最近5条）
            ord_rows = await db.execute(
                text("""
                    SELECT id, store_id, total_fen, status, created_at
                    FROM orders
                    WHERE tenant_id = :tid AND customer_id = :cust_id AND is_deleted = FALSE
                    ORDER BY created_at DESC
                    LIMIT 5
                """),
                {"tid": str(tenant_id), "cust_id": cust_id},
            )
            recent_orders = [dict(r) for r in ord_rows.mappings().all()]

        await db.commit()

        logger.info(
            "incoming_call_handled",
            call_id=str(call_id),
            phone=caller_phone,
            matched=customer_profile is not None,
        )

        return {
            "call_id": str(call_id),
            "customer": customer_profile,
            "recent_reservations": recent_reservations,
            "recent_orders": recent_orders,
        }

    # ──────────────────────────────────────────────
    # 2. 客户弹屏
    # ──────────────────────────────────────────────

    @staticmethod
    async def get_customer_popup(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        phone: str,
    ) -> Optional[dict[str, Any]]:
        """根据手机号查询客户画像：基本信息 + RFM + 最近5单 + 即将到来的预订"""
        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )

        # 客户基本信息
        cust_row = await db.execute(
            text("""
                SELECT id, name, phone, membership_level, total_spend_fen, visit_count,
                       last_visit_at, tags
                FROM customers
                WHERE tenant_id = :tid AND phone = :phone AND is_deleted = FALSE
                LIMIT 1
            """),
            {"tid": str(tenant_id), "phone": phone},
        )
        customer = cust_row.mappings().first()
        if not customer:
            return None

        cust_id = str(customer["id"])
        profile = dict(customer)

        # RFM 数据
        rfm_row = await db.execute(
            text("""
                SELECT recency_days, frequency, monetary_fen, rfm_segment
                FROM customer_rfm
                WHERE tenant_id = :tid AND customer_id = :cust_id
                LIMIT 1
            """),
            {"tid": str(tenant_id), "cust_id": cust_id},
        )
        rfm = rfm_row.mappings().first()
        profile["rfm"] = dict(rfm) if rfm else None

        # 最近5单
        ord_rows = await db.execute(
            text("""
                SELECT id, store_id, total_fen, status, created_at
                FROM orders
                WHERE tenant_id = :tid AND customer_id = :cust_id AND is_deleted = FALSE
                ORDER BY created_at DESC
                LIMIT 5
            """),
            {"tid": str(tenant_id), "cust_id": cust_id},
        )
        profile["recent_orders"] = [dict(r) for r in ord_rows.mappings().all()]

        # 即将到来的预订
        res_rows = await db.execute(
            text("""
                SELECT id, store_id, party_size, reservation_date, reservation_time, status
                FROM reservations
                WHERE tenant_id = :tid AND customer_id = :cust_id
                      AND reservation_date >= CURRENT_DATE
                      AND is_deleted = FALSE
                ORDER BY reservation_date ASC
                LIMIT 5
            """),
            {"tid": str(tenant_id), "cust_id": cust_id},
        )
        profile["upcoming_reservations"] = [dict(r) for r in res_rows.mappings().all()]

        return profile

    # ──────────────────────────────────────────────
    # 3. 挂断记录
    # ──────────────────────────────────────────────

    @staticmethod
    async def record_call_hangup(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        call_id: uuid.UUID,
        duration_sec: int,
        recording_url: Optional[str] = None,
        status: str = "answered",
    ) -> dict[str, Any]:
        """通话挂断：更新通话时长、录音地址、最终状态"""
        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )

        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                UPDATE call_records
                SET duration_sec  = :dur,
                    recording_url = :url,
                    status        = :st,
                    ended_at      = :now,
                    updated_at    = :now
                WHERE id = :cid AND tenant_id = :tid
            """),
            {
                "tid": str(tenant_id),
                "cid": str(call_id),
                "dur": duration_sec,
                "url": recording_url,
                "st": status,
                "now": now,
            },
        )

        # 如果是未接来电，自动创建回拨任务
        if status == "missed":
            row = await db.execute(
                text("""
                    SELECT caller_phone, store_id, customer_id
                    FROM call_records
                    WHERE id = :cid AND tenant_id = :tid
                """),
                {"tid": str(tenant_id), "cid": str(call_id)},
            )
            call = row.mappings().first()
            if call and call["caller_phone"]:
                await db.execute(
                    text("""
                        INSERT INTO callback_tasks
                            (tenant_id, id, store_id, call_record_id, customer_id,
                             callback_phone, reason, status)
                        VALUES
                            (:tid, :task_id, :sid, :cid, :cust_id,
                             :phone, 'missed_call', 'pending')
                    """),
                    {
                        "tid": str(tenant_id),
                        "task_id": str(uuid.uuid4()),
                        "sid": str(call["store_id"]),
                        "cid": str(call_id),
                        "cust_id": str(call["customer_id"]) if call["customer_id"] else None,
                        "phone": call["caller_phone"],
                    },
                )

        await db.commit()

        logger.info(
            "call_hangup_recorded",
            call_id=str(call_id),
            duration_sec=duration_sec,
            status=status,
        )
        return {"call_id": str(call_id), "status": status, "duration_sec": duration_sec}

    # ──────────────────────────────────────────────
    # 4. 回拨任务
    # ──────────────────────────────────────────────

    @staticmethod
    async def create_callback_task(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """创建回拨任务"""
        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )

        task_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO callback_tasks
                    (tenant_id, id, store_id, call_record_id, customer_id,
                     callback_phone, reason, status, assigned_to, scheduled_at, notes)
                VALUES
                    (:tid, :task_id, :sid, :crid, :cust_id,
                     :phone, :reason, 'pending', :assigned, :scheduled, :notes)
            """),
            {
                "tid": str(tenant_id),
                "task_id": str(task_id),
                "sid": str(store_id),
                "crid": data.get("call_record_id"),
                "cust_id": data.get("customer_id"),
                "phone": data["callback_phone"],
                "reason": data.get("reason", "custom"),
                "assigned": data.get("assigned_to"),
                "scheduled": data.get("scheduled_at"),
                "notes": data.get("notes"),
            },
        )
        await db.commit()

        logger.info("callback_task_created", task_id=str(task_id))
        return {"task_id": str(task_id), "status": "pending"}

    @staticmethod
    async def complete_callback(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        notes: Optional[str] = None,
    ) -> dict[str, Any]:
        """完成回拨任务"""
        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )

        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                UPDATE callback_tasks
                SET status       = 'completed',
                    completed_at = :now,
                    notes        = COALESCE(:notes, notes),
                    updated_at   = :now
                WHERE id = :tid_task AND tenant_id = :tid
            """),
            {
                "tid": str(tenant_id),
                "tid_task": str(task_id),
                "now": now,
                "notes": notes,
            },
        )
        await db.commit()

        logger.info("callback_task_completed", task_id=str(task_id))
        return {"task_id": str(task_id), "status": "completed"}

    # ──────────────────────────────────────────────
    # 5. 查询：通话历史 / 未接来电 / 回拨任务列表
    # ──────────────────────────────────────────────

    @staticmethod
    async def get_call_history(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        phone: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """通话历史（分页）"""
        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )

        where = "tenant_id = :tid AND store_id = :sid AND is_deleted = FALSE"
        params: dict[str, Any] = {"tid": str(tenant_id), "sid": str(store_id)}

        if phone:
            where += " AND caller_phone = :phone"
            params["phone"] = phone

        # 总数
        count_row = await db.execute(
            text(f"SELECT COUNT(*) AS cnt FROM call_records WHERE {where}"),
            params,
        )
        total = count_row.scalar() or 0

        # 分页数据
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        rows = await db.execute(
            text(f"""
                SELECT id, caller_phone, caller_name, call_type, duration_sec,
                       status, customer_id, agent_ext, started_at, ended_at, notes
                FROM call_records
                WHERE {where}
                ORDER BY started_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in rows.mappings().all()]

        return {"items": items, "total": total, "page": page, "size": size}

    @staticmethod
    async def get_missed_calls(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        target_date: Optional[date] = None,
    ) -> list[dict[str, Any]]:
        """获取未接来电列表"""
        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )

        d = target_date or date.today()
        rows = await db.execute(
            text("""
                SELECT id, caller_phone, caller_name, customer_id, agent_ext,
                       started_at, notes
                FROM call_records
                WHERE tenant_id = :tid AND store_id = :sid
                      AND status = 'missed'
                      AND started_at::date = :d
                      AND is_deleted = FALSE
                ORDER BY started_at DESC
            """),
            {"tid": str(tenant_id), "sid": str(store_id), "d": d},
        )
        return [dict(r) for r in rows.mappings().all()]

    @staticmethod
    async def get_callback_tasks(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        assigned_to: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """获取回拨任务列表"""
        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )

        where = "tenant_id = :tid AND store_id = :sid AND is_deleted = FALSE"
        params: dict[str, Any] = {"tid": str(tenant_id), "sid": str(store_id)}

        if assigned_to:
            where += " AND assigned_to = :assigned"
            params["assigned"] = str(assigned_to)
        if status:
            where += " AND status = :st"
            params["st"] = status

        rows = await db.execute(
            text(f"""
                SELECT id, call_record_id, customer_id, callback_phone, reason,
                       status, assigned_to, scheduled_at, completed_at, notes, created_at
                FROM callback_tasks
                WHERE {where}
                ORDER BY created_at DESC
            """),
            params,
        )
        return [dict(r) for r in rows.mappings().all()]

    # ──────────────────────────────────────────────
    # 6. 统计
    # ──────────────────────────────────────────────

    @staticmethod
    async def get_call_stats(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        period: str = "today",
    ) -> dict[str, Any]:
        """通话统计：接通率、未接率、平均通话时长

        period: today / week / month
        """
        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )

        period_filter = {
            "today": "started_at::date = CURRENT_DATE",
            "week": "started_at >= CURRENT_DATE - INTERVAL '7 days'",
            "month": "started_at >= CURRENT_DATE - INTERVAL '30 days'",
        }
        date_cond = period_filter.get(period, period_filter["today"])

        row = await db.execute(
            text(f"""
                SELECT
                    COUNT(*)                                         AS total_calls,
                    COUNT(*) FILTER (WHERE status = 'answered')      AS answered,
                    COUNT(*) FILTER (WHERE status = 'missed')        AS missed,
                    ROUND(AVG(duration_sec) FILTER (WHERE status = 'answered'), 1)
                                                                     AS avg_duration_sec,
                    ROUND(
                        COUNT(*) FILTER (WHERE status = 'answered') * 100.0
                        / NULLIF(COUNT(*), 0), 1
                    )                                                AS answer_rate,
                    ROUND(
                        COUNT(*) FILTER (WHERE status = 'missed') * 100.0
                        / NULLIF(COUNT(*), 0), 1
                    )                                                AS miss_rate
                FROM call_records
                WHERE tenant_id = :tid AND store_id = :sid
                      AND {date_cond}
                      AND is_deleted = FALSE
            """),
            {"tid": str(tenant_id), "sid": str(store_id)},
        )
        stats = row.mappings().first()
        return (
            dict(stats)
            if stats
            else {
                "total_calls": 0,
                "answered": 0,
                "missed": 0,
                "avg_duration_sec": 0,
                "answer_rate": 0,
                "miss_rate": 0,
            }
        )
