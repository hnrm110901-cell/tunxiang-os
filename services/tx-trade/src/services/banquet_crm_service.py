"""宴会CRM服务 — 线索获取/跟进/转化/客资保护

全业务闭环: 线索录入 → 销售分配 → 跟进记录 → 报价 → 签约 → 赢单/丢单
客资保护: 员工离职/调店时客资自动转移，历史跟进记录完整保留。
金额单位: 分(fen)。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


# ─── 状态流转 ───────────────────────────────────────────────────────────────

LEAD_STATUSES = ("new", "following", "quoted", "contracted", "won", "lost")

VALID_TRANSITIONS: dict[str, set[str]] = {
    "new": {"following", "lost"},
    "following": {"quoted", "lost"},
    "quoted": {"contracted", "lost"},
    "contracted": {"won", "lost"},
    # won / lost 为终态
}

FOLLOW_TYPES = ("phone", "wechat", "visit", "meeting", "other")


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


# ─── Service ────────────────────────────────────────────────────────────────


class BanquetCrmService:
    """宴会线索全生命周期管理"""

    def __init__(self, db: AsyncSession, tenant_id: str, store_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id
        self._store_id = store_id

    # ── 线索 CRUD ──────────────────────────────────────────────────────────

    async def create_lead(
        self,
        customer_name: str,
        phone: str,
        event_type: str,
        event_date: Optional[str] = None,
        guest_count_est: Optional[int] = None,
        table_count_est: Optional[int] = None,
        budget_per_table_fen: Optional[int] = None,
        source_channel: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """录入新线索。

        Args:
            customer_name: 客户姓名
            phone: 联系电话
            event_type: 宴会类型 (wedding/birthday/business/team_building/anniversary)
            event_date: 预计宴会日期 (ISO 格式)
            guest_count_est: 预计宾客人数
            table_count_est: 预计桌数
            budget_per_table_fen: 每桌预算（分）
            source_channel: 获客渠道 (walk_in/phone/wechat/referral/online/other)
            notes: 备注
        """
        if not customer_name or not customer_name.strip():
            raise ValueError("客户姓名不能为空")
        if not phone or not phone.strip():
            raise ValueError("联系电话不能为空")
        if budget_per_table_fen is not None and budget_per_table_fen < 0:
            raise ValueError("每桌预算不能为负数")

        lead_id = str(uuid.uuid4())
        lead_no = _gen_id("BQL")
        now = _now_utc()

        await self._db.execute(
            text("""
                INSERT INTO banquet_leads (
                    id, tenant_id, store_id, lead_no, customer_name, phone,
                    event_type, event_date, guest_count_est, table_count_est,
                    budget_per_table_fen, source_channel, notes,
                    status, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :store_id, :lead_no, :customer_name, :phone,
                    :event_type, :event_date, :guest_count_est, :table_count_est,
                    :budget_per_table_fen, :source_channel, :notes,
                    'new', :now, :now
                )
            """),
            {
                "id": lead_id,
                "tenant_id": self._tenant_id,
                "store_id": self._store_id,
                "lead_no": lead_no,
                "customer_name": customer_name.strip(),
                "phone": phone.strip(),
                "event_type": event_type,
                "event_date": event_date,
                "guest_count_est": guest_count_est,
                "table_count_est": table_count_est,
                "budget_per_table_fen": budget_per_table_fen,
                "source_channel": source_channel,
                "notes": notes,
                "now": now,
            },
        )
        await self._db.flush()

        logger.info(
            "banquet_lead_created",
            tenant_id=self._tenant_id,
            store_id=self._store_id,
            lead_id=lead_id,
            lead_no=lead_no,
            event_type=event_type,
            source_channel=source_channel,
        )

        return {
            "id": lead_id,
            "lead_no": lead_no,
            "customer_name": customer_name.strip(),
            "phone": phone.strip(),
            "event_type": event_type,
            "event_date": event_date,
            "guest_count_est": guest_count_est,
            "table_count_est": table_count_est,
            "budget_per_table_fen": budget_per_table_fen,
            "source_channel": source_channel,
            "notes": notes,
            "status": "new",
            "assigned_sales_id": None,
            "follow_up_at": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

    async def update_lead(self, lead_id: str, **kwargs: object) -> dict:
        """更新线索信息（不含状态和销售分配）。

        支持字段: customer_name, phone, event_type, event_date,
                  guest_count_est, table_count_est, budget_per_table_fen,
                  source_channel, notes
        """
        allowed = {
            "customer_name",
            "phone",
            "event_type",
            "event_date",
            "guest_count_est",
            "table_count_est",
            "budget_per_table_fen",
            "source_channel",
            "notes",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            raise ValueError("没有有效的更新字段")

        # 验证线索存在
        row = await self._db.execute(
            text("""
                SELECT id, status FROM banquet_leads
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
            """),
            {"id": lead_id, "tenant_id": self._tenant_id},
        )
        lead = row.mappings().first()
        if not lead:
            raise ValueError(f"线索不存在: {lead_id}")

        if lead["status"] in ("won", "lost"):
            raise ValueError(f"终态线索不可编辑: {lead['status']}")

        set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
        updates["updated_at"] = _now_utc()
        set_clauses += ", updated_at = :updated_at"
        updates["id"] = lead_id
        updates["tenant_id"] = self._tenant_id

        await self._db.execute(
            text(f"""
                UPDATE banquet_leads
                SET {set_clauses}
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            updates,
        )
        await self._db.flush()

        logger.info(
            "banquet_lead_updated",
            tenant_id=self._tenant_id,
            lead_id=lead_id,
            fields=list(kwargs.keys()),
        )

        return await self.get_lead(lead_id)

    async def assign_sales(self, lead_id: str, sales_id: str) -> dict:
        """分配销售负责人，若未设置跟进时间则自动设为24小时后。"""
        row = await self._db.execute(
            text("""
                SELECT id, status, follow_up_at FROM banquet_leads
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
            """),
            {"id": lead_id, "tenant_id": self._tenant_id},
        )
        lead = row.mappings().first()
        if not lead:
            raise ValueError(f"线索不存在: {lead_id}")
        if lead["status"] in ("won", "lost"):
            raise ValueError("终态线索不可分配销售")

        now = _now_utc()
        follow_up_at = lead["follow_up_at"] or (now + timedelta(hours=24))

        await self._db.execute(
            text("""
                UPDATE banquet_leads
                SET assigned_sales_id = :sales_id,
                    follow_up_at = :follow_up_at,
                    updated_at = :now
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {
                "id": lead_id,
                "tenant_id": self._tenant_id,
                "sales_id": sales_id,
                "follow_up_at": follow_up_at,
                "now": now,
            },
        )
        await self._db.flush()

        logger.info(
            "banquet_lead_sales_assigned",
            tenant_id=self._tenant_id,
            lead_id=lead_id,
            sales_id=sales_id,
            follow_up_at=follow_up_at.isoformat(),
        )

        return await self.get_lead(lead_id)

    # ── 跟进记录 ──────────────────────────────────────────────────────────

    async def add_follow_up(
        self,
        lead_id: str,
        sales_id: str,
        follow_type: str,
        content: str,
        next_action: Optional[str] = None,
        next_follow_at: Optional[str] = None,
    ) -> dict:
        """添加跟进记录。

        Args:
            lead_id: 线索ID
            sales_id: 销售ID
            follow_type: 跟进方式 (phone/wechat/visit/meeting/other)
            content: 跟进内容
            next_action: 下一步行动
            next_follow_at: 下次跟进时间 (ISO 格式)
        """
        if follow_type not in FOLLOW_TYPES:
            raise ValueError(f"无效的跟进方式: {follow_type}，可选: {FOLLOW_TYPES}")
        if not content or not content.strip():
            raise ValueError("跟进内容不能为空")

        # 验证线索存在且未终结
        row = await self._db.execute(
            text("""
                SELECT id, status FROM banquet_leads
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
            """),
            {"id": lead_id, "tenant_id": self._tenant_id},
        )
        lead = row.mappings().first()
        if not lead:
            raise ValueError(f"线索不存在: {lead_id}")
        if lead["status"] in ("won", "lost"):
            raise ValueError("终态线索不可添加跟进")

        follow_id = str(uuid.uuid4())
        now = _now_utc()

        await self._db.execute(
            text("""
                INSERT INTO banquet_lead_follow_ups (
                    id, tenant_id, lead_id, sales_id, follow_type,
                    content, next_action, next_follow_at, created_at
                ) VALUES (
                    :id, :tenant_id, :lead_id, :sales_id, :follow_type,
                    :content, :next_action, :next_follow_at, :now
                )
            """),
            {
                "id": follow_id,
                "tenant_id": self._tenant_id,
                "lead_id": lead_id,
                "sales_id": sales_id,
                "follow_type": follow_type,
                "content": content.strip(),
                "next_action": next_action,
                "next_follow_at": next_follow_at,
                "now": now,
            },
        )

        # 更新线索的下次跟进时间
        if next_follow_at:
            await self._db.execute(
                text("""
                    UPDATE banquet_leads
                    SET follow_up_at = :next_follow_at, updated_at = :now
                    WHERE id = :lead_id AND tenant_id = :tenant_id
                """),
                {
                    "lead_id": lead_id,
                    "tenant_id": self._tenant_id,
                    "next_follow_at": next_follow_at,
                    "now": now,
                },
            )

        await self._db.flush()

        logger.info(
            "banquet_follow_up_added",
            tenant_id=self._tenant_id,
            lead_id=lead_id,
            sales_id=sales_id,
            follow_type=follow_type,
        )

        return {
            "id": follow_id,
            "lead_id": lead_id,
            "sales_id": sales_id,
            "follow_type": follow_type,
            "content": content.strip(),
            "next_action": next_action,
            "next_follow_at": next_follow_at,
            "created_at": now.isoformat(),
        }

    # ── 客资转移 ──────────────────────────────────────────────────────────

    async def transfer_lead(
        self,
        lead_id: str,
        from_employee_id: str,
        to_employee_id: str,
        reason: str,
    ) -> dict:
        """客资转移：员工离职/调店时，将线索及全部跟进记录转移到新负责人。

        历史跟进记录完整保留，仅更新当前负责人。
        """
        if not reason or not reason.strip():
            raise ValueError("转移原因不能为空")
        if from_employee_id == to_employee_id:
            raise ValueError("转出和转入不能是同一人")

        row = await self._db.execute(
            text("""
                SELECT id, status, assigned_sales_id FROM banquet_leads
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
            """),
            {"id": lead_id, "tenant_id": self._tenant_id},
        )
        lead = row.mappings().first()
        if not lead:
            raise ValueError(f"线索不存在: {lead_id}")
        if lead["assigned_sales_id"] != from_employee_id:
            raise ValueError("转出人与当前负责人不匹配")

        transfer_id = str(uuid.uuid4())
        now = _now_utc()

        # 记录转移
        await self._db.execute(
            text("""
                INSERT INTO banquet_lead_transfers (
                    id, tenant_id, lead_id, from_employee_id, to_employee_id,
                    reason, transferred_at
                ) VALUES (
                    :id, :tenant_id, :lead_id, :from_employee_id, :to_employee_id,
                    :reason, :now
                )
            """),
            {
                "id": transfer_id,
                "tenant_id": self._tenant_id,
                "lead_id": lead_id,
                "from_employee_id": from_employee_id,
                "to_employee_id": to_employee_id,
                "reason": reason.strip(),
                "now": now,
            },
        )

        # 更新线索负责人
        await self._db.execute(
            text("""
                UPDATE banquet_leads
                SET assigned_sales_id = :to_employee_id, updated_at = :now
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {
                "id": lead_id,
                "tenant_id": self._tenant_id,
                "to_employee_id": to_employee_id,
                "now": now,
            },
        )
        await self._db.flush()

        logger.info(
            "banquet_lead_transferred",
            tenant_id=self._tenant_id,
            lead_id=lead_id,
            from_employee_id=from_employee_id,
            to_employee_id=to_employee_id,
            reason=reason,
        )

        return {
            "transfer_id": transfer_id,
            "lead_id": lead_id,
            "from_employee_id": from_employee_id,
            "to_employee_id": to_employee_id,
            "reason": reason.strip(),
            "transferred_at": now.isoformat(),
        }

    # ── 状态流转 ──────────────────────────────────────────────────────────

    async def update_status(
        self,
        lead_id: str,
        new_status: str,
        reason: Optional[str] = None,
    ) -> dict:
        """更新线索状态，校验合法流转。

        合法流转: new→following→quoted→contracted→won, 任意→lost
        """
        if new_status not in LEAD_STATUSES:
            raise ValueError(f"无效状态: {new_status}，可选: {LEAD_STATUSES}")

        row = await self._db.execute(
            text("""
                SELECT id, status FROM banquet_leads
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
            """),
            {"id": lead_id, "tenant_id": self._tenant_id},
        )
        lead = row.mappings().first()
        if not lead:
            raise ValueError(f"线索不存在: {lead_id}")

        current = lead["status"]
        if current in ("won", "lost"):
            raise ValueError(f"终态线索不可变更状态: {current}")

        valid_next = VALID_TRANSITIONS.get(current, set())
        if new_status not in valid_next:
            raise ValueError(f"状态流转非法: {current} → {new_status}，允许: {valid_next}")

        now = _now_utc()
        params: dict = {
            "id": lead_id,
            "tenant_id": self._tenant_id,
            "new_status": new_status,
            "now": now,
        }

        extra_set = ""
        if new_status == "won":
            extra_set = ", won_at = :now"
        elif new_status == "lost":
            extra_set = ", lost_at = :now, lost_reason = :reason"
            params["reason"] = reason

        await self._db.execute(
            text(f"""
                UPDATE banquet_leads
                SET status = :new_status, updated_at = :now{extra_set}
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            params,
        )
        await self._db.flush()

        logger.info(
            "banquet_lead_status_updated",
            tenant_id=self._tenant_id,
            lead_id=lead_id,
            from_status=current,
            to_status=new_status,
            reason=reason,
        )

        return await self.get_lead(lead_id)

    # ── 查询 ──────────────────────────────────────────────────────────────

    async def list_leads(
        self,
        store_id: Optional[str] = None,
        status: Optional[str] = None,
        event_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        assigned_sales_id: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询线索列表，支持多维度筛选。"""
        if page < 1:
            page = 1
        if size < 1 or size > 100:
            size = 20

        conditions = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
        params: dict = {"tenant_id": self._tenant_id}

        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if event_type:
            conditions.append("event_type = :event_type")
            params["event_type"] = event_type
        if date_from:
            conditions.append("event_date >= :date_from")
            params["date_from"] = date_from
        if date_to:
            conditions.append("event_date <= :date_to")
            params["date_to"] = date_to
        if assigned_sales_id:
            conditions.append("assigned_sales_id = :assigned_sales_id")
            params["assigned_sales_id"] = assigned_sales_id

        where = " AND ".join(conditions)

        # 总数
        count_row = await self._db.execute(
            text(f"SELECT COUNT(*) AS cnt FROM banquet_leads WHERE {where}"),
            params,
        )
        total = count_row.scalar() or 0

        # 分页数据
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        result = await self._db.execute(
            text(f"""
                SELECT id, lead_no, customer_name, phone, event_type,
                       event_date, guest_count_est, table_count_est,
                       budget_per_table_fen, source_channel, status,
                       assigned_sales_id, follow_up_at,
                       created_at, updated_at
                FROM banquet_leads
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.mappings().all()

        items = []
        for r in rows:
            items.append(
                {
                    "id": str(r["id"]),
                    "lead_no": r["lead_no"],
                    "customer_name": r["customer_name"],
                    "phone": r["phone"],
                    "event_type": r["event_type"],
                    "event_date": str(r["event_date"]) if r["event_date"] else None,
                    "guest_count_est": r["guest_count_est"],
                    "table_count_est": r["table_count_est"],
                    "budget_per_table_fen": r["budget_per_table_fen"],
                    "source_channel": r["source_channel"],
                    "status": r["status"],
                    "assigned_sales_id": str(r["assigned_sales_id"]) if r["assigned_sales_id"] else None,
                    "follow_up_at": r["follow_up_at"].isoformat() if r["follow_up_at"] else None,
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                }
            )

        return {"items": items, "total": total, "page": page, "size": size}

    async def get_lead(self, lead_id: str) -> dict:
        """获取单个线索详情，附带跟进次数。"""
        row = await self._db.execute(
            text("""
                SELECT l.*,
                       (SELECT COUNT(*) FROM banquet_lead_follow_ups f
                        WHERE f.lead_id = l.id AND f.tenant_id = l.tenant_id
                       ) AS follow_up_count
                FROM banquet_leads l
                WHERE l.id = :id AND l.tenant_id = :tenant_id AND l.is_deleted = FALSE
            """),
            {"id": lead_id, "tenant_id": self._tenant_id},
        )
        lead = row.mappings().first()
        if not lead:
            raise ValueError(f"线索不存在: {lead_id}")

        return {
            "id": str(lead["id"]),
            "lead_no": lead["lead_no"],
            "store_id": str(lead["store_id"]),
            "customer_name": lead["customer_name"],
            "phone": lead["phone"],
            "event_type": lead["event_type"],
            "event_date": str(lead["event_date"]) if lead["event_date"] else None,
            "guest_count_est": lead["guest_count_est"],
            "table_count_est": lead["table_count_est"],
            "budget_per_table_fen": lead["budget_per_table_fen"],
            "source_channel": lead["source_channel"],
            "notes": lead["notes"],
            "status": lead["status"],
            "assigned_sales_id": str(lead["assigned_sales_id"]) if lead["assigned_sales_id"] else None,
            "follow_up_at": lead["follow_up_at"].isoformat() if lead["follow_up_at"] else None,
            "won_at": lead["won_at"].isoformat() if lead.get("won_at") else None,
            "lost_at": lead["lost_at"].isoformat() if lead.get("lost_at") else None,
            "lost_reason": lead.get("lost_reason"),
            "follow_up_count": lead["follow_up_count"],
            "created_at": lead["created_at"].isoformat() if lead["created_at"] else None,
            "updated_at": lead["updated_at"].isoformat() if lead["updated_at"] else None,
        }

    async def get_follow_ups(
        self,
        lead_id: str,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询线索的跟进记录，最新在前。"""
        if page < 1:
            page = 1
        if size < 1 or size > 100:
            size = 20

        # 验证线索存在
        check = await self._db.execute(
            text("""
                SELECT id FROM banquet_leads
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
            """),
            {"id": lead_id, "tenant_id": self._tenant_id},
        )
        if not check.first():
            raise ValueError(f"线索不存在: {lead_id}")

        count_row = await self._db.execute(
            text("""
                SELECT COUNT(*) AS cnt FROM banquet_lead_follow_ups
                WHERE lead_id = :lead_id AND tenant_id = :tenant_id
            """),
            {"lead_id": lead_id, "tenant_id": self._tenant_id},
        )
        total = count_row.scalar() or 0

        offset = (page - 1) * size
        result = await self._db.execute(
            text("""
                SELECT id, lead_id, sales_id, follow_type, content,
                       next_action, next_follow_at, created_at
                FROM banquet_lead_follow_ups
                WHERE lead_id = :lead_id AND tenant_id = :tenant_id
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {
                "lead_id": lead_id,
                "tenant_id": self._tenant_id,
                "limit": size,
                "offset": offset,
            },
        )
        rows = result.mappings().all()

        items = []
        for r in rows:
            items.append(
                {
                    "id": str(r["id"]),
                    "lead_id": str(r["lead_id"]),
                    "sales_id": str(r["sales_id"]),
                    "follow_type": r["follow_type"],
                    "content": r["content"],
                    "next_action": r["next_action"],
                    "next_follow_at": r["next_follow_at"].isoformat() if r["next_follow_at"] else None,
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
            )

        return {"items": items, "total": total, "page": page, "size": size}

    # ── 分析 ──────────────────────────────────────────────────────────────

    async def conversion_funnel(
        self,
        store_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict:
        """销售漏斗分析：统计各状态线索数量及转化率。"""
        conditions = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
        params: dict = {"tenant_id": self._tenant_id}

        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id
        if date_from:
            conditions.append("created_at >= :date_from")
            params["date_from"] = date_from
        if date_to:
            conditions.append("created_at <= :date_to")
            params["date_to"] = date_to

        where = " AND ".join(conditions)

        result = await self._db.execute(
            text(f"""
                SELECT status, COUNT(*) AS cnt
                FROM banquet_leads
                WHERE {where}
                GROUP BY status
            """),
            params,
        )
        rows = result.mappings().all()

        counts: dict[str, int] = dict.fromkeys(LEAD_STATUSES, 0)
        for r in rows:
            counts[r["status"]] = r["cnt"]

        total = sum(counts.values())
        conversion_rate = (counts["won"] / total * 100) if total > 0 else 0.0

        return {
            "new": counts["new"],
            "following": counts["following"],
            "quoted": counts["quoted"],
            "contracted": counts["contracted"],
            "won": counts["won"],
            "lost": counts["lost"],
            "total": total,
            "conversion_rate": round(conversion_rate, 2),
        }

    async def leads_due_for_follow_up(
        self,
        store_id: Optional[str] = None,
    ) -> list:
        """获取需要跟进的线索（follow_up_at <= 当前时间 且未终结）。"""
        conditions = [
            "tenant_id = :tenant_id",
            "is_deleted = FALSE",
            "follow_up_at <= :now",
            "status NOT IN ('won', 'lost')",
        ]
        params: dict = {
            "tenant_id": self._tenant_id,
            "now": _now_utc(),
        }

        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id

        where = " AND ".join(conditions)

        result = await self._db.execute(
            text(f"""
                SELECT id, lead_no, customer_name, phone, event_type,
                       event_date, status, assigned_sales_id, follow_up_at
                FROM banquet_leads
                WHERE {where}
                ORDER BY follow_up_at ASC
                LIMIT 100
            """),
            params,
        )
        rows = result.mappings().all()

        items = []
        for r in rows:
            items.append(
                {
                    "id": str(r["id"]),
                    "lead_no": r["lead_no"],
                    "customer_name": r["customer_name"],
                    "phone": r["phone"],
                    "event_type": r["event_type"],
                    "event_date": str(r["event_date"]) if r["event_date"] else None,
                    "status": r["status"],
                    "assigned_sales_id": str(r["assigned_sales_id"]) if r["assigned_sales_id"] else None,
                    "follow_up_at": r["follow_up_at"].isoformat() if r["follow_up_at"] else None,
                }
            )

        logger.info(
            "banquet_leads_due_for_follow_up",
            tenant_id=self._tenant_id,
            count=len(items),
        )

        return items
