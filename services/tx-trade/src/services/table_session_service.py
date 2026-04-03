"""多人协同扫码点餐服务 — 桌台会话管理 + 共享购物车 + 呼叫服务员

同桌多人扫码 → 加入同一 table_session → 实时同步 cart_items → 提交厨房
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.kds_dispatch import dispatch_order_to_kds

logger = structlog.get_logger()

SESSION_TTL_HOURS = 2


# ─── Pydantic 数据模型 ───


class Participant(BaseModel):
    openid: str
    nickname: str
    joined_at: datetime
    item_count: int


class CartItem(BaseModel):
    dish_id: uuid.UUID
    dish_name: str
    quantity: int
    price_fen: int
    subtotal_fen: int
    added_by_openid: str
    added_at: datetime


class TableSession(BaseModel):
    id: uuid.UUID
    session_token: str
    table_id: uuid.UUID
    order_id: Optional[uuid.UUID]
    status: str
    participants: list[Participant]
    cart_items: list[CartItem]
    expires_at: datetime
    submitted_at: Optional[datetime]


class SubmitResult(BaseModel):
    session_id: uuid.UUID
    order_id: uuid.UUID
    total_items: int
    total_fen: int
    kds_sent: bool


class WaiterCall(BaseModel):
    id: uuid.UUID
    table_id: uuid.UUID
    call_type: str
    note: str
    status: str
    acknowledged_by: Optional[uuid.UUID]
    acknowledged_at: Optional[datetime]
    created_at: datetime


# ─── 内部工具 ───


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_session(row: dict) -> TableSession:
    """将数据库行转换为 TableSession 模型"""
    raw_participants = row["participants"] or []
    raw_cart = row["cart_items"] or []

    participants = [
        Participant(
            openid=p["openid"],
            nickname=p.get("nickname", ""),
            joined_at=datetime.fromisoformat(p["joined_at"]) if isinstance(p["joined_at"], str) else p["joined_at"],
            item_count=p.get("item_count", 0),
        )
        for p in raw_participants
    ]

    cart_items = [
        CartItem(
            dish_id=uuid.UUID(str(c["dish_id"])),
            dish_name=c["dish_name"],
            quantity=c["quantity"],
            price_fen=c["price_fen"],
            subtotal_fen=c["price_fen"] * c["quantity"],
            added_by_openid=c["added_by_openid"],
            added_at=datetime.fromisoformat(c["added_at"]) if isinstance(c["added_at"], str) else c["added_at"],
        )
        for c in raw_cart
    ]

    return TableSession(
        id=uuid.UUID(str(row["id"])),
        session_token=row["session_token"],
        table_id=uuid.UUID(str(row["table_id"])),
        order_id=uuid.UUID(str(row["order_id"])) if row.get("order_id") else None,
        status=row["status"],
        participants=participants,
        cart_items=cart_items,
        expires_at=row["expires_at"],
        submitted_at=row.get("submitted_at"),
    )


def _row_to_waiter_call(row: dict) -> WaiterCall:
    return WaiterCall(
        id=uuid.UUID(str(row["id"])),
        table_id=uuid.UUID(str(row["table_id"])),
        call_type=row["call_type"],
        note=row.get("note", ""),
        status=row["status"],
        acknowledged_by=uuid.UUID(str(row["acknowledged_by"])) if row.get("acknowledged_by") else None,
        acknowledged_at=row.get("acknowledged_at"),
        created_at=row["created_at"],
    )


def _count_items_for_openid(cart_items: list[dict], openid: str) -> int:
    return sum(c["quantity"] for c in cart_items if c.get("added_by_openid") == openid)


# ─── 主服务类 ───


class TableSessionService:
    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._db = db
        self._tenant_id = tenant_id

    async def create_session(
        self,
        store_id: uuid.UUID,
        table_id: uuid.UUID,
        openid: str,
    ) -> TableSession:
        """创建协同会话，生成 session_token，2小时过期"""
        token = secrets.token_urlsafe(32)
        now = _now_utc()
        expires_at = now + timedelta(hours=SESSION_TTL_HOURS)
        session_id = uuid.uuid4()

        initial_participants = [
            {
                "openid": openid,
                "nickname": "",
                "joined_at": now.isoformat(),
                "item_count": 0,
            }
        ]

        result = await self._db.execute(
            text("""
                INSERT INTO table_sessions
                    (id, tenant_id, store_id, table_id, session_token,
                     participants, cart_items, status, expires_at,
                     created_at, updated_at)
                VALUES
                    (:id, :tenant_id, :store_id, :table_id, :session_token,
                     :participants::jsonb, '[]'::jsonb, 'active', :expires_at,
                     :now, :now)
                RETURNING *
            """),
            {
                "id": session_id,
                "tenant_id": self._tenant_id,
                "store_id": store_id,
                "table_id": table_id,
                "session_token": token,
                "participants": __import__("json").dumps(initial_participants, ensure_ascii=False),
                "expires_at": expires_at,
                "now": now,
            },
        )
        row = result.mappings().one()

        logger.info(
            "table_session_created",
            session_id=str(session_id),
            table_id=str(table_id),
            openid=openid,
            tenant_id=str(self._tenant_id),
        )
        return _row_to_session(dict(row))

    async def join_session(
        self,
        session_token: str,
        openid: str,
        nickname: str = "",
    ) -> TableSession:
        """加入已有会话（第2-N个顾客扫码）"""
        import json

        row = await self._fetch_active_session(session_token)

        participants: list[dict] = list(row["participants"] or [])
        existing_openids = {p["openid"] for p in participants}

        if openid not in existing_openids:
            participants.append(
                {
                    "openid": openid,
                    "nickname": nickname,
                    "joined_at": _now_utc().isoformat(),
                    "item_count": 0,
                }
            )

        now = _now_utc()
        result = await self._db.execute(
            text("""
                UPDATE table_sessions
                SET participants = :participants::jsonb,
                    updated_at   = :now
                WHERE session_token = :token
                  AND tenant_id     = :tenant_id
                RETURNING *
            """),
            {
                "participants": json.dumps(participants, ensure_ascii=False),
                "now": now,
                "token": session_token,
                "tenant_id": self._tenant_id,
            },
        )
        updated = result.mappings().one()

        logger.info(
            "table_session_joined",
            session_token=session_token,
            openid=openid,
            participant_count=len(participants),
            tenant_id=str(self._tenant_id),
        )
        return _row_to_session(dict(updated))

    async def get_session(
        self,
        session_token: str,
    ) -> Optional[TableSession]:
        """获取会话（含实时 cart_items）"""
        result = await self._db.execute(
            text("""
                SELECT * FROM table_sessions
                WHERE session_token = :token
                  AND tenant_id     = :tenant_id
            """),
            {"token": session_token, "tenant_id": self._tenant_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return _row_to_session(dict(row))

    async def add_cart_item(
        self,
        session_token: str,
        openid: str,
        dish_id: uuid.UUID,
        dish_name: str,
        quantity: int,
        price_fen: int,
    ) -> TableSession:
        """向共享购物车加菜；同一菜品已存在则累加数量"""
        import json

        row = await self._fetch_active_session(session_token)

        cart: list[dict] = list(row["cart_items"] or [])
        now_iso = _now_utc().isoformat()
        dish_id_str = str(dish_id)

        # 查找已有相同 dish_id 的条目
        existing = next((c for c in cart if str(c["dish_id"]) == dish_id_str), None)
        if existing:
            existing["quantity"] += quantity
        else:
            cart.append(
                {
                    "dish_id": dish_id_str,
                    "dish_name": dish_name,
                    "quantity": quantity,
                    "price_fen": price_fen,
                    "added_by_openid": openid,
                    "added_at": now_iso,
                }
            )

        # 更新参与者的 item_count
        participants: list[dict] = list(row["participants"] or [])
        for p in participants:
            if p["openid"] == openid:
                p["item_count"] = _count_items_for_openid(cart, openid)

        now = _now_utc()
        result = await self._db.execute(
            text("""
                UPDATE table_sessions
                SET cart_items   = :cart::jsonb,
                    participants = :participants::jsonb,
                    updated_at   = :now
                WHERE session_token = :token
                  AND tenant_id     = :tenant_id
                RETURNING *
            """),
            {
                "cart": json.dumps(cart, ensure_ascii=False),
                "participants": json.dumps(participants, ensure_ascii=False),
                "now": now,
                "token": session_token,
                "tenant_id": self._tenant_id,
            },
        )
        updated = result.mappings().one()

        logger.info(
            "cart_item_added",
            session_token=session_token,
            dish_id=dish_id_str,
            quantity=quantity,
            openid=openid,
            tenant_id=str(self._tenant_id),
        )
        return _row_to_session(dict(updated))

    async def remove_cart_item(
        self,
        session_token: str,
        openid: str,
        dish_id: uuid.UUID,
    ) -> TableSession:
        """从购物车移除菜品（仅限自己加的）"""
        import json

        row = await self._fetch_active_session(session_token)

        cart: list[dict] = list(row["cart_items"] or [])
        dish_id_str = str(dish_id)

        # 只允许删除自己加的菜品
        new_cart = [
            c for c in cart
            if not (str(c["dish_id"]) == dish_id_str and c.get("added_by_openid") == openid)
        ]

        if len(new_cart) == len(cart):
            raise ValueError(f"菜品 {dish_id_str} 不存在或不属于当前用户")

        # 更新参与者的 item_count
        participants: list[dict] = list(row["participants"] or [])
        for p in participants:
            if p["openid"] == openid:
                p["item_count"] = _count_items_for_openid(new_cart, openid)

        now = _now_utc()
        result = await self._db.execute(
            text("""
                UPDATE table_sessions
                SET cart_items   = :cart::jsonb,
                    participants = :participants::jsonb,
                    updated_at   = :now
                WHERE session_token = :token
                  AND tenant_id     = :tenant_id
                RETURNING *
            """),
            {
                "cart": json.dumps(new_cart, ensure_ascii=False),
                "participants": json.dumps(participants, ensure_ascii=False),
                "now": now,
                "token": session_token,
                "tenant_id": self._tenant_id,
            },
        )
        updated = result.mappings().one()

        logger.info(
            "cart_item_removed",
            session_token=session_token,
            dish_id=dish_id_str,
            openid=openid,
            tenant_id=str(self._tenant_id),
        )
        return _row_to_session(dict(updated))

    async def submit_session(
        self,
        session_token: str,
    ) -> SubmitResult:
        """提交购物车到厨房 — 创建 Order + OrderItems，触发 KDS 分单"""

        row = await self._fetch_active_session(session_token)
        session_id = uuid.UUID(str(row["id"]))
        table_id = uuid.UUID(str(row["table_id"]))
        store_id = uuid.UUID(str(row["store_id"]))
        cart: list[dict] = list(row["cart_items"] or [])

        if not cart:
            raise ValueError("购物车为空，无法提交")

        # 计算总额
        total_fen = sum(c["price_fen"] * c["quantity"] for c in cart)
        total_items = sum(c["quantity"] for c in cart)

        # 生成订单号
        from ..services.order_service import _gen_order_no
        order_no = _gen_order_no()
        order_id = uuid.uuid4()
        now = _now_utc()

        # 插入 Order
        await self._db.execute(
            text("""
                INSERT INTO orders
                    (id, tenant_id, store_id, order_no, table_number,
                     sales_channel, total_amount_fen, discount_amount_fen,
                     final_amount_fen, status, created_at, updated_at,
                     is_deleted)
                VALUES
                    (:id, :tenant_id, :store_id, :order_no, :table_number,
                     'collab_scan_order', :total_fen, 0,
                     :total_fen, 'confirmed', :now, :now, FALSE)
            """),
            {
                "id": order_id,
                "tenant_id": self._tenant_id,
                "store_id": store_id,
                "order_no": order_no,
                "table_number": str(table_id),
                "total_fen": total_fen,
                "now": now,
            },
        )

        # 插入 OrderItems
        order_item_ids: list[str] = []
        kds_items: list[dict] = []
        for c in cart:
            item_id = uuid.uuid4()
            order_item_ids.append(str(item_id))
            await self._db.execute(
                text("""
                    INSERT INTO order_items
                        (id, tenant_id, order_id, dish_id, item_name,
                         quantity, unit_price_fen, subtotal_fen,
                         notes, sent_to_kds_flag, return_flag,
                         created_at, updated_at)
                    VALUES
                        (:id, :tenant_id, :order_id, :dish_id, :dish_name,
                         :quantity, :price_fen, :subtotal_fen,
                         '', FALSE, FALSE,
                         :now, :now)
                """),
                {
                    "id": item_id,
                    "tenant_id": self._tenant_id,
                    "order_id": order_id,
                    "dish_id": uuid.UUID(str(c["dish_id"])),
                    "dish_name": c["dish_name"],
                    "quantity": c["quantity"],
                    "price_fen": c["price_fen"],
                    "subtotal_fen": c["price_fen"] * c["quantity"],
                    "now": now,
                },
            )
            kds_items.append(
                {
                    "dish_id": str(c["dish_id"]),
                    "item_name": c["dish_name"],
                    "quantity": c["quantity"],
                    "order_item_id": str(item_id),
                    "notes": "",
                }
            )

        # 触发 KDS 分单
        kds_sent = False
        try:
            await dispatch_order_to_kds(
                order_id=str(order_id),
                order_items=kds_items,
                tenant_id=str(self._tenant_id),
                db=self._db,
                table_number=str(table_id),
                order_no=order_no,
                auto_print=True,
            )
            # 标记已发送 KDS
            await self._db.execute(
                text("""
                    UPDATE order_items
                    SET sent_to_kds_flag = TRUE
                    WHERE order_id   = :order_id
                      AND tenant_id  = :tenant_id
                """),
                {"order_id": order_id, "tenant_id": self._tenant_id},
            )
            kds_sent = True
        except (SQLAlchemyError, ValueError, RuntimeError) as exc:
            logger.warning(
                "collab_kds_dispatch_failed",
                order_id=str(order_id),
                tenant_id=str(self._tenant_id),
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )

        # 更新 session 状态
        await self._db.execute(
            text("""
                UPDATE table_sessions
                SET order_id     = :order_id,
                    status       = 'submitted',
                    submitted_at = :now,
                    updated_at   = :now
                WHERE session_token = :token
                  AND tenant_id     = :tenant_id
            """),
            {
                "order_id": order_id,
                "now": now,
                "token": session_token,
                "tenant_id": self._tenant_id,
            },
        )

        logger.info(
            "collab_session_submitted",
            session_id=str(session_id),
            order_id=str(order_id),
            total_items=total_items,
            total_fen=total_fen,
            kds_sent=kds_sent,
            tenant_id=str(self._tenant_id),
        )

        return SubmitResult(
            session_id=session_id,
            order_id=order_id,
            total_items=total_items,
            total_fen=total_fen,
            kds_sent=kds_sent,
        )

    async def call_waiter(
        self,
        session_token: str,
        store_id: uuid.UUID,
        table_id: uuid.UUID,
        call_type: str = "general",
        note: str = "",
    ) -> WaiterCall:
        """呼叫服务员，创建 waiter_calls 记录"""
        row = await self._fetch_session_row(session_token)
        session_id = uuid.UUID(str(row["id"]))

        call_id = uuid.uuid4()
        now = _now_utc()
        result = await self._db.execute(
            text("""
                INSERT INTO waiter_calls
                    (id, tenant_id, store_id, table_id, session_id,
                     call_type, note, status, created_at)
                VALUES
                    (:id, :tenant_id, :store_id, :table_id, :session_id,
                     :call_type, :note, 'pending', :now)
                RETURNING *
            """),
            {
                "id": call_id,
                "tenant_id": self._tenant_id,
                "store_id": store_id,
                "table_id": table_id,
                "session_id": session_id,
                "call_type": call_type,
                "note": note,
                "now": now,
            },
        )
        call_row = result.mappings().one()

        logger.info(
            "waiter_called",
            call_id=str(call_id),
            table_id=str(table_id),
            call_type=call_type,
            tenant_id=str(self._tenant_id),
        )
        return _row_to_waiter_call(dict(call_row))

    async def acknowledge_call(
        self,
        call_id: uuid.UUID,
        waiter_id: uuid.UUID,
    ) -> WaiterCall:
        """服务员确认响应"""
        now = _now_utc()
        result = await self._db.execute(
            text("""
                UPDATE waiter_calls
                SET status          = 'acknowledged',
                    acknowledged_by = :waiter_id,
                    acknowledged_at = :now
                WHERE id        = :call_id
                  AND tenant_id = :tenant_id
                  AND status    = 'pending'
                RETURNING *
            """),
            {
                "waiter_id": waiter_id,
                "now": now,
                "call_id": call_id,
                "tenant_id": self._tenant_id,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise ValueError(f"呼叫 {call_id} 不存在或已被响应")

        logger.info(
            "waiter_call_acknowledged",
            call_id=str(call_id),
            waiter_id=str(waiter_id),
            tenant_id=str(self._tenant_id),
        )
        return _row_to_waiter_call(dict(row))

    async def get_pending_calls(
        self,
        store_id: uuid.UUID,
    ) -> list[WaiterCall]:
        """获取门店当前未处理的呼叫（服务员端使用）"""
        result = await self._db.execute(
            text("""
                SELECT * FROM waiter_calls
                WHERE tenant_id = :tenant_id
                  AND store_id  = :store_id
                  AND status    = 'pending'
                ORDER BY created_at ASC
            """),
            {"tenant_id": self._tenant_id, "store_id": store_id},
        )
        rows = result.mappings().all()
        return [_row_to_waiter_call(dict(r)) for r in rows]

    # ─── 私有工具 ───

    async def _fetch_session_row(self, session_token: str) -> dict:
        """获取会话行（不校验状态）"""
        result = await self._db.execute(
            text("""
                SELECT * FROM table_sessions
                WHERE session_token = :token
                  AND tenant_id     = :tenant_id
            """),
            {"token": session_token, "tenant_id": self._tenant_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise ValueError(f"会话不存在: {session_token}")
        return dict(row)

    async def _fetch_active_session(self, session_token: str) -> dict:
        """获取会话并校验 active 状态及未过期"""
        row = await self._fetch_session_row(session_token)
        if row["status"] != "active":
            raise ValueError(f"会话已{row['status']}，无法操作")

        expires_at: datetime = row["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if _now_utc() > expires_at:
            raise ValueError("会话已过期")

        return row
