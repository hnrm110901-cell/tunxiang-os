"""宴会主单服务 — 贯穿全生命周期的核心状态机

状态流转: draft → confirmed → preparing → ready → in_progress → completed → settled
                                                                     ↘ cancelled (from any pre-completed state)
定金管理: 记录定金金额/支付状态/支付方式，对接卡券内核。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


# ─── 状态机 ─────────────────────────────────────────────────────────────────

BANQUET_STATUSES = (
    "draft",
    "confirmed",
    "preparing",
    "ready",
    "in_progress",
    "completed",
    "settled",
    "cancelled",
)

VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"confirmed", "cancelled"},
    "confirmed": {"preparing", "cancelled"},
    "preparing": {"ready", "cancelled"},
    "ready": {"in_progress", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": {"settled"},
    # settled / cancelled 为终态
}

CANCELLABLE_STATUSES = {"draft", "confirmed", "preparing", "ready", "in_progress"}


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _safe_json(val: object) -> str:
    if isinstance(val, str):
        return val
    return json.dumps(val, ensure_ascii=False, default=str)


def _parse_json(val: object) -> object:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        return json.loads(val)
    return val


# ─── Service ────────────────────────────────────────────────────────────────


class BanquetOrderService:
    """宴会主单全生命周期管理"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id

    # ── 创建宴会 ──────────────────────────────────────────────────────────

    async def create_banquet(
        self,
        lead_id: str,
        quote_id: str,
        store_id: str,
        venue_id: str,
        event_type: str,
        event_name: str,
        event_date: str,
        time_slot: str,
        host_name: str,
        host_phone: str,
        guest_count: int,
        table_count: int,
        menu_json: list[dict],
        deposit_amount_fen: int = 0,
        special_requests: Optional[str] = None,
        contact_name: Optional[str] = None,
        contact_phone: Optional[str] = None,
    ) -> dict:
        """创建宴会主单。

        从报价单确认后创建，关联线索、报价、厅房。
        总金额从报价单获取，余额 = 总额 - 定金。
        """
        if not event_name or not event_name.strip():
            raise ValueError("宴会名称不能为空")
        if not host_name or not host_name.strip():
            raise ValueError("宴主姓名不能为空")
        if guest_count <= 0:
            raise ValueError("宾客人数必须大于0")
        if table_count <= 0:
            raise ValueError("桌数必须大于0")
        if deposit_amount_fen < 0:
            raise ValueError("定金不能为负数")

        # 获取报价单总金额
        quote_row = await self._db.execute(
            text("""
                SELECT total_fen FROM banquet_quotes
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": quote_id, "tenant_id": self._tenant_id},
        )
        quote = quote_row.mappings().first()
        if not quote:
            raise ValueError(f"报价单不存在: {quote_id}")

        total_amount_fen = quote["total_fen"]
        balance_fen = total_amount_fen - deposit_amount_fen

        banquet_id = str(uuid.uuid4())
        banquet_no = _gen_id("BNQ")
        now = _now_utc()

        await self._db.execute(
            text("""
                INSERT INTO banquet_orders (
                    id, tenant_id, banquet_no, lead_id, quote_id, store_id,
                    venue_id, event_type, event_name, event_date, time_slot,
                    host_name, host_phone, contact_name, contact_phone,
                    guest_count, table_count, menu_json,
                    total_amount_fen, deposit_amount_fen, balance_fen,
                    special_requests, status,
                    created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :banquet_no, :lead_id, :quote_id, :store_id,
                    :venue_id, :event_type, :event_name, :event_date, :time_slot,
                    :host_name, :host_phone, :contact_name, :contact_phone,
                    :guest_count, :table_count, :menu_json,
                    :total_amount_fen, :deposit_amount_fen, :balance_fen,
                    :special_requests, 'draft',
                    :now, :now
                )
            """),
            {
                "id": banquet_id,
                "tenant_id": self._tenant_id,
                "banquet_no": banquet_no,
                "lead_id": lead_id,
                "quote_id": quote_id,
                "store_id": store_id,
                "venue_id": venue_id,
                "event_type": event_type,
                "event_name": event_name.strip(),
                "event_date": event_date,
                "time_slot": time_slot,
                "host_name": host_name.strip(),
                "host_phone": host_phone.strip(),
                "contact_name": contact_name,
                "contact_phone": contact_phone,
                "guest_count": guest_count,
                "table_count": table_count,
                "menu_json": _safe_json(menu_json),
                "total_amount_fen": total_amount_fen,
                "deposit_amount_fen": deposit_amount_fen,
                "balance_fen": balance_fen,
                "special_requests": special_requests,
                "now": now,
            },
        )

        # 插入初始状态日志
        await self._insert_status_log(
            banquet_id=banquet_id,
            status="draft",
            operator_id=None,
            reason="宴会主单创建",
            timestamp=now,
        )

        # 关联厅房预订
        await self._db.execute(
            text("""
                UPDATE banquet_venue_bookings
                SET banquet_id = :banquet_id, updated_at = :now
                WHERE venue_id = :venue_id
                  AND lead_id = :lead_id
                  AND booking_date = :event_date
                  AND tenant_id = :tenant_id
                  AND status IN ('held', 'confirmed')
            """),
            {
                "banquet_id": banquet_id,
                "venue_id": venue_id,
                "lead_id": lead_id,
                "event_date": event_date,
                "tenant_id": self._tenant_id,
                "now": now,
            },
        )

        await self._db.flush()

        logger.info(
            "banquet_order_created",
            tenant_id=self._tenant_id,
            banquet_id=banquet_id,
            banquet_no=banquet_no,
            store_id=store_id,
            event_type=event_type,
            event_date=event_date,
            total_amount_fen=total_amount_fen,
            deposit_amount_fen=deposit_amount_fen,
        )

        return {
            "id": banquet_id,
            "banquet_no": banquet_no,
            "lead_id": lead_id,
            "quote_id": quote_id,
            "store_id": store_id,
            "venue_id": venue_id,
            "event_type": event_type,
            "event_name": event_name.strip(),
            "event_date": event_date,
            "time_slot": time_slot,
            "host_name": host_name.strip(),
            "host_phone": host_phone.strip(),
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "guest_count": guest_count,
            "table_count": table_count,
            "total_amount_fen": total_amount_fen,
            "deposit_amount_fen": deposit_amount_fen,
            "balance_fen": balance_fen,
            "special_requests": special_requests,
            "status": "draft",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

    # ── 状态流转 ──────────────────────────────────────────────────────────

    async def update_status(
        self,
        banquet_id: str,
        new_status: str,
        operator_id: str,
        reason: Optional[str] = None,
    ) -> dict:
        """更新宴会状态，校验合法流转。"""
        if new_status not in BANQUET_STATUSES:
            raise ValueError(f"无效状态: {new_status}，可选: {BANQUET_STATUSES}")

        row = await self._db.execute(
            text("""
                SELECT id, status, banquet_no FROM banquet_orders
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": banquet_id, "tenant_id": self._tenant_id},
        )
        banquet = row.mappings().first()
        if not banquet:
            raise ValueError(f"宴会不存在: {banquet_id}")

        current = banquet["status"]
        if current in ("settled", "cancelled"):
            raise ValueError(f"终态宴会不可变更: {current}")

        valid_next = VALID_TRANSITIONS.get(current, set())
        if new_status not in valid_next:
            raise ValueError(f"状态流转非法: {current} → {new_status}，允许: {valid_next}")

        now = _now_utc()
        await self._db.execute(
            text("""
                UPDATE banquet_orders
                SET status = :new_status, updated_at = :now
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {
                "id": banquet_id,
                "tenant_id": self._tenant_id,
                "new_status": new_status,
                "now": now,
            },
        )

        await self._insert_status_log(
            banquet_id=banquet_id,
            status=new_status,
            operator_id=operator_id,
            reason=reason,
            timestamp=now,
        )

        await self._db.flush()

        # 发布事件（通过 Redis Stream，若可用）
        await self._publish_event(
            banquet_id=banquet_id,
            banquet_no=banquet["banquet_no"],
            new_status=new_status,
            operator_id=operator_id,
        )

        logger.info(
            "banquet_status_updated",
            tenant_id=self._tenant_id,
            banquet_id=banquet_id,
            banquet_no=banquet["banquet_no"],
            from_status=current,
            to_status=new_status,
            operator_id=operator_id,
        )

        return await self.get_banquet(banquet_id)

    async def _insert_status_log(
        self,
        banquet_id: str,
        status: str,
        operator_id: Optional[str],
        reason: Optional[str],
        timestamp: datetime,
    ) -> None:
        """插入状态变更日志。"""
        log_id = str(uuid.uuid4())
        await self._db.execute(
            text("""
                INSERT INTO banquet_status_logs (
                    id, tenant_id, banquet_id, status,
                    operator_id, reason, created_at
                ) VALUES (
                    :id, :tenant_id, :banquet_id, :status,
                    :operator_id, :reason, :now
                )
            """),
            {
                "id": log_id,
                "tenant_id": self._tenant_id,
                "banquet_id": banquet_id,
                "status": status,
                "operator_id": operator_id,
                "reason": reason,
                "now": timestamp,
            },
        )

    async def _publish_event(
        self,
        banquet_id: str,
        banquet_no: str,
        new_status: str,
        operator_id: str,
    ) -> None:
        """发布宴会状态变更事件（Redis Stream 旁路，失败不阻塞主流程）。"""
        try:
            # 尝试通过事件总线发布
            # 若 emit_event 不可用则静默跳过
            import asyncio

            from shared.events.src.emitter import emit_event

            asyncio.create_task(
                emit_event(
                    event_type=f"banquet.status.{new_status}",
                    tenant_id=self._tenant_id,
                    stream_id=banquet_id,
                    payload={
                        "banquet_id": banquet_id,
                        "banquet_no": banquet_no,
                        "status": new_status,
                        "operator_id": operator_id,
                    },
                    source_service="tx-trade",
                )
            )
        except ImportError:
            logger.debug("banquet_event_emit_skipped", reason="emit_event not available")
        except RuntimeError:
            logger.debug("banquet_event_emit_skipped", reason="no running event loop")

    # ── 定金管理 ──────────────────────────────────────────────────────────

    async def record_deposit(
        self,
        banquet_id: str,
        amount_fen: int,
        payment_method: str,
    ) -> dict:
        """记录定金支付。

        Args:
            banquet_id: 宴会ID
            amount_fen: 定金金额（分）
            payment_method: 支付方式 (wechat/alipay/cash/bank_transfer/pos)
        """
        if amount_fen <= 0:
            raise ValueError("定金金额必须大于0")

        row = await self._db.execute(
            text("""
                SELECT id, status, total_amount_fen, deposit_amount_fen,
                       deposit_paid_fen
                FROM banquet_orders
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": banquet_id, "tenant_id": self._tenant_id},
        )
        banquet = row.mappings().first()
        if not banquet:
            raise ValueError(f"宴会不存在: {banquet_id}")
        if banquet["status"] in ("completed", "settled", "cancelled"):
            raise ValueError(f"当前状态不可收定金: {banquet['status']}")

        already_paid = banquet["deposit_paid_fen"] or 0
        new_paid = already_paid + amount_fen
        deposit_required = banquet["deposit_amount_fen"] or 0

        if new_paid > deposit_required:
            raise ValueError(
                f"定金已付 {already_paid} + 本次 {amount_fen} = {new_paid} 超过应付定金 {deposit_required}"
            )

        balance_fen = banquet["total_amount_fen"] - new_paid
        now = _now_utc()

        await self._db.execute(
            text("""
                UPDATE banquet_orders
                SET deposit_paid_fen = :new_paid,
                    deposit_paid_at = :now,
                    deposit_payment_method = :payment_method,
                    balance_fen = :balance_fen,
                    updated_at = :now
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {
                "id": banquet_id,
                "tenant_id": self._tenant_id,
                "new_paid": new_paid,
                "payment_method": payment_method,
                "balance_fen": balance_fen,
                "now": now,
            },
        )
        await self._db.flush()

        logger.info(
            "banquet_deposit_recorded",
            tenant_id=self._tenant_id,
            banquet_id=banquet_id,
            amount_fen=amount_fen,
            total_paid_fen=new_paid,
            balance_fen=balance_fen,
            payment_method=payment_method,
        )

        return {
            "banquet_id": banquet_id,
            "deposit_amount_fen": deposit_required,
            "deposit_paid_fen": new_paid,
            "this_payment_fen": amount_fen,
            "payment_method": payment_method,
            "balance_fen": balance_fen,
            "deposit_paid_at": now.isoformat(),
            "fully_paid": new_paid >= deposit_required,
        }

    # ── 查询 ──────────────────────────────────────────────────────────────

    async def get_banquet(self, banquet_id: str) -> dict:
        """获取宴会详情，含厅房信息和状态日志数量。"""
        row = await self._db.execute(
            text("""
                SELECT o.*,
                       v.venue_name, v.venue_type, v.floor AS venue_floor,
                       (SELECT COUNT(*) FROM banquet_status_logs sl
                        WHERE sl.banquet_id = o.id AND sl.tenant_id = o.tenant_id
                       ) AS log_count
                FROM banquet_orders o
                LEFT JOIN banquet_venues v
                    ON v.id = o.venue_id AND v.tenant_id = o.tenant_id
                WHERE o.id = :id AND o.tenant_id = :tenant_id
            """),
            {"id": banquet_id, "tenant_id": self._tenant_id},
        )
        b = row.mappings().first()
        if not b:
            raise ValueError(f"宴会不存在: {banquet_id}")

        return {
            "id": str(b["id"]),
            "banquet_no": b["banquet_no"],
            "lead_id": str(b["lead_id"]) if b["lead_id"] else None,
            "quote_id": str(b["quote_id"]) if b["quote_id"] else None,
            "store_id": str(b["store_id"]),
            "venue_id": str(b["venue_id"]) if b["venue_id"] else None,
            "venue_name": b["venue_name"],
            "venue_type": b["venue_type"],
            "venue_floor": b["venue_floor"],
            "event_type": b["event_type"],
            "event_name": b["event_name"],
            "event_date": str(b["event_date"]) if b["event_date"] else None,
            "time_slot": b["time_slot"],
            "host_name": b["host_name"],
            "host_phone": b["host_phone"],
            "contact_name": b.get("contact_name"),
            "contact_phone": b.get("contact_phone"),
            "guest_count": b["guest_count"],
            "table_count": b["table_count"],
            "menu_json": _parse_json(b["menu_json"]),
            "total_amount_fen": b["total_amount_fen"],
            "deposit_amount_fen": b["deposit_amount_fen"],
            "deposit_paid_fen": b.get("deposit_paid_fen") or 0,
            "deposit_payment_method": b.get("deposit_payment_method"),
            "balance_fen": b["balance_fen"],
            "special_requests": b.get("special_requests"),
            "status": b["status"],
            "log_count": b["log_count"],
            "created_at": b["created_at"].isoformat() if b["created_at"] else None,
            "updated_at": b["updated_at"].isoformat() if b["updated_at"] else None,
        }

    async def list_banquets(
        self,
        store_id: Optional[str] = None,
        status: Optional[str] = None,
        event_date_from: Optional[str] = None,
        event_date_to: Optional[str] = None,
        event_type: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询宴会列表。"""
        if page < 1:
            page = 1
        if size < 1 or size > 100:
            size = 20

        conditions = ["o.tenant_id = :tenant_id"]
        params: dict = {"tenant_id": self._tenant_id}

        if store_id:
            conditions.append("o.store_id = :store_id")
            params["store_id"] = store_id
        if status:
            conditions.append("o.status = :status")
            params["status"] = status
        if event_date_from:
            conditions.append("o.event_date >= :event_date_from")
            params["event_date_from"] = event_date_from
        if event_date_to:
            conditions.append("o.event_date <= :event_date_to")
            params["event_date_to"] = event_date_to
        if event_type:
            conditions.append("o.event_type = :event_type")
            params["event_type"] = event_type

        where = " AND ".join(conditions)

        count_row = await self._db.execute(
            text(f"SELECT COUNT(*) AS cnt FROM banquet_orders o WHERE {where}"),
            params,
        )
        total = count_row.scalar() or 0

        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        result = await self._db.execute(
            text(f"""
                SELECT o.id, o.banquet_no, o.store_id, o.event_type,
                       o.event_name, o.event_date, o.time_slot,
                       o.host_name, o.guest_count, o.table_count,
                       o.total_amount_fen, o.deposit_amount_fen, o.balance_fen,
                       o.status, o.created_at,
                       v.venue_name
                FROM banquet_orders o
                LEFT JOIN banquet_venues v
                    ON v.id = o.venue_id AND v.tenant_id = o.tenant_id
                WHERE {where}
                ORDER BY o.event_date ASC, o.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.mappings().all()

        items = [
            {
                "id": str(r["id"]),
                "banquet_no": r["banquet_no"],
                "store_id": str(r["store_id"]),
                "event_type": r["event_type"],
                "event_name": r["event_name"],
                "event_date": str(r["event_date"]) if r["event_date"] else None,
                "time_slot": r["time_slot"],
                "host_name": r["host_name"],
                "guest_count": r["guest_count"],
                "table_count": r["table_count"],
                "total_amount_fen": r["total_amount_fen"],
                "deposit_amount_fen": r["deposit_amount_fen"],
                "balance_fen": r["balance_fen"],
                "venue_name": r["venue_name"],
                "status": r["status"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

        return {"items": items, "total": total, "page": page, "size": size}

    async def get_timeline(self, banquet_id: str) -> list:
        """获取宴会状态变更时间线。"""
        # 验证宴会存在
        check = await self._db.execute(
            text("""
                SELECT id FROM banquet_orders
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": banquet_id, "tenant_id": self._tenant_id},
        )
        if not check.first():
            raise ValueError(f"宴会不存在: {banquet_id}")

        result = await self._db.execute(
            text("""
                SELECT id, status, operator_id, reason, created_at
                FROM banquet_status_logs
                WHERE banquet_id = :banquet_id AND tenant_id = :tenant_id
                ORDER BY created_at ASC
            """),
            {"banquet_id": banquet_id, "tenant_id": self._tenant_id},
        )
        rows = result.mappings().all()

        return [
            {
                "id": str(r["id"]),
                "status": r["status"],
                "operator_id": str(r["operator_id"]) if r["operator_id"] else None,
                "reason": r["reason"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

    async def get_day_schedule(self, store_id: str, date: str) -> dict:
        """获取门店某日所有宴会排程。"""
        result = await self._db.execute(
            text("""
                SELECT o.id, o.banquet_no, o.event_type, o.event_name,
                       o.time_slot, o.host_name, o.guest_count, o.table_count,
                       o.status,
                       v.venue_id, v.venue_name, v.venue_type
                FROM banquet_orders o
                LEFT JOIN banquet_venues v
                    ON v.id = o.venue_id AND v.tenant_id = o.tenant_id
                WHERE o.store_id = :store_id
                  AND o.tenant_id = :tenant_id
                  AND o.event_date = :event_date
                  AND o.status NOT IN ('cancelled')
                ORDER BY
                    CASE o.time_slot
                        WHEN 'lunch' THEN 1
                        WHEN 'dinner' THEN 2
                        WHEN 'full_day' THEN 0
                    END,
                    v.venue_name
            """),
            {
                "store_id": store_id,
                "tenant_id": self._tenant_id,
                "event_date": date,
            },
        )
        rows = result.mappings().all()

        lunch = []
        dinner = []
        full_day = []

        for r in rows:
            item = {
                "banquet_id": str(r["id"]),
                "banquet_no": r["banquet_no"],
                "event_type": r["event_type"],
                "event_name": r["event_name"],
                "host_name": r["host_name"],
                "guest_count": r["guest_count"],
                "table_count": r["table_count"],
                "venue_name": r["venue_name"],
                "venue_type": r["venue_type"],
                "status": r["status"],
            }
            if r["time_slot"] == "lunch":
                lunch.append(item)
            elif r["time_slot"] == "dinner":
                dinner.append(item)
            else:
                full_day.append(item)

        return {
            "store_id": store_id,
            "date": date,
            "lunch": lunch,
            "dinner": dinner,
            "full_day": full_day,
            "total_banquets": len(rows),
            "total_tables": sum(r["table_count"] for r in rows),
            "total_guests": sum(r["guest_count"] for r in rows),
        }

    # ── 取消 ──────────────────────────────────────────────────────────────

    async def cancel_banquet(
        self,
        banquet_id: str,
        operator_id: str,
        reason: str,
    ) -> dict:
        """取消宴会，释放厅房预订。"""
        if not reason or not reason.strip():
            raise ValueError("取消原因不能为空")

        row = await self._db.execute(
            text("""
                SELECT id, status, venue_id, lead_id, event_date, banquet_no
                FROM banquet_orders
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": banquet_id, "tenant_id": self._tenant_id},
        )
        banquet = row.mappings().first()
        if not banquet:
            raise ValueError(f"宴会不存在: {banquet_id}")

        current = banquet["status"]
        if current not in CANCELLABLE_STATUSES:
            raise ValueError(f"当前状态不可取消: {current}")

        now = _now_utc()

        # 更新宴会状态
        await self._db.execute(
            text("""
                UPDATE banquet_orders
                SET status = 'cancelled',
                    cancelled_at = :now,
                    cancel_reason = :reason,
                    updated_at = :now
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {
                "id": banquet_id,
                "tenant_id": self._tenant_id,
                "reason": reason.strip(),
                "now": now,
            },
        )

        # 插入状态日志
        await self._insert_status_log(
            banquet_id=banquet_id,
            status="cancelled",
            operator_id=operator_id,
            reason=reason.strip(),
            timestamp=now,
        )

        # 释放厅房预订
        if banquet["venue_id"]:
            await self._db.execute(
                text("""
                    UPDATE banquet_venue_bookings
                    SET status = 'released',
                        release_reason = :reason,
                        updated_at = :now
                    WHERE banquet_id = :banquet_id
                      AND tenant_id = :tenant_id
                      AND status IN ('held', 'confirmed')
                """),
                {
                    "banquet_id": banquet_id,
                    "tenant_id": self._tenant_id,
                    "reason": f"宴会取消: {reason.strip()}",
                    "now": now,
                },
            )

        await self._db.flush()

        # 发布取消事件
        await self._publish_event(
            banquet_id=banquet_id,
            banquet_no=banquet["banquet_no"],
            new_status="cancelled",
            operator_id=operator_id,
        )

        logger.info(
            "banquet_cancelled",
            tenant_id=self._tenant_id,
            banquet_id=banquet_id,
            banquet_no=banquet["banquet_no"],
            from_status=current,
            operator_id=operator_id,
            reason=reason,
        )

        return await self.get_banquet(banquet_id)

    # ── 看板 ──────────────────────────────────────────────────────────────

    async def dashboard_summary(
        self,
        store_id: str,
        date_from: str,
        date_to: str,
    ) -> dict:
        """宴会经营看板汇总。"""
        params: dict = {
            "tenant_id": self._tenant_id,
            "store_id": store_id,
            "date_from": date_from,
            "date_to": date_to,
        }

        # 总数和营收
        summary_row = await self._db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_banquets,
                    COALESCE(SUM(CASE WHEN status NOT IN ('cancelled') THEN total_amount_fen ELSE 0 END), 0) AS total_revenue_fen,
                    COALESCE(SUM(CASE WHEN status NOT IN ('cancelled') THEN table_count ELSE 0 END), 0) AS total_tables,
                    COUNT(CASE WHEN status = 'completed' OR status = 'settled' THEN 1 END) AS completed_count,
                    COUNT(CASE WHEN status = 'cancelled' THEN 1 END) AS cancelled_count
                FROM banquet_orders
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND event_date >= :date_from
                  AND event_date <= :date_to
            """),
            params,
        )
        s = summary_row.mappings().first()

        total_banquets = s["total_banquets"] or 0
        total_revenue_fen = s["total_revenue_fen"] or 0
        total_tables = s["total_tables"] or 0
        avg_per_table_fen = (total_revenue_fen // total_tables) if total_tables > 0 else 0

        # 按宴会类型分布
        type_row = await self._db.execute(
            text("""
                SELECT event_type, COUNT(*) AS cnt,
                       COALESCE(SUM(total_amount_fen), 0) AS revenue_fen
                FROM banquet_orders
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND event_date >= :date_from
                  AND event_date <= :date_to
                  AND status NOT IN ('cancelled')
                GROUP BY event_type
                ORDER BY revenue_fen DESC
            """),
            params,
        )
        by_type = [
            {
                "event_type": r["event_type"],
                "count": r["cnt"],
                "revenue_fen": r["revenue_fen"],
            }
            for r in type_row.mappings().all()
        ]

        # 线索转化率（同期）
        lead_row = await self._db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_leads,
                    COUNT(CASE WHEN status = 'won' THEN 1 END) AS won_leads
                FROM banquet_leads
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND created_at >= :date_from
                  AND created_at <= :date_to
                  AND is_deleted = FALSE
            """),
            params,
        )
        lr = lead_row.mappings().first()
        total_leads = lr["total_leads"] or 0
        won_leads = lr["won_leads"] or 0
        lead_conversion = round(won_leads / total_leads * 100, 2) if total_leads > 0 else 0.0

        return {
            "store_id": store_id,
            "date_from": date_from,
            "date_to": date_to,
            "total_banquets": total_banquets,
            "completed_count": s["completed_count"] or 0,
            "cancelled_count": s["cancelled_count"] or 0,
            "total_revenue_fen": total_revenue_fen,
            "avg_per_table_fen": avg_per_table_fen,
            "total_tables": total_tables,
            "by_event_type": by_type,
            "total_leads": total_leads,
            "won_leads": won_leads,
            "lead_conversion_rate": lead_conversion,
        }
