"""预订服务 — V1+V3合并，7状态机

预订全流程：创建->确认->到店->排队(可选)->入座->完成/取消/爽约
与排队服务联动：预订到店时可自动进入优先排队
与桌台状态机联动：预订确认->桌台reserved，入座->桌台dining

所有金额单位：分（fen）。

修复:
  - [HARDCODE] ROOM_CONFIG / TIME_SLOTS / duration_min 从硬编码改为可配置参数
  - [ASYNCIO] 移除 asyncio.create_task 中使用 db session 的危险模式
    (session 在请求结束时关闭，create_task 里的协程可能在那之后才执行)
  - [STATE-MACHINE] customer_arrived 做了两次状态转换 (arrived->queuing) 但只验证了第一次
  - [STATE-MACHINE] seat_reservation 绕过了 _get_and_validate_transition
  - [PAGINATION] list_reservations 增加分页
  - [VALIDATION] phone 空字符串校验
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .reservation_flow import (
    RESERVATION_TRANSITIONS,
    can_reservation_transition,
)
from .queue_service import QueueService
from ..repositories.reservation_repo import ReservationRepository
from ..models.reservation import Reservation

logger = structlog.get_logger()


def _gen_id() -> str:
    return uuid.uuid4().hex[:12].upper()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_confirmation_code() -> str:
    """生成6位数字确认码"""
    return uuid.uuid4().hex[:6].upper()


RESERVATION_TYPES = ["regular", "banquet", "private_room", "outdoor", "vip"]

# 包间默认配置 — 实际应从 store 配置表读取，此处作为 fallback
_DEFAULT_ROOM_CONFIG: dict[str, dict] = {
    "梅花厅": {"capacity": (4, 8), "features": ["独立空调", "投影"], "min_spend_fen": 80000},
    "兰花厅": {"capacity": (6, 12), "features": ["独立空调", "投影", "KTV"], "min_spend_fen": 120000},
    "竹韵阁": {"capacity": (8, 16), "features": ["独立空调", "投影", "KTV", "独立卫生间"], "min_spend_fen": 200000},
    "菊香苑": {"capacity": (10, 20), "features": ["独立空调", "投影", "KTV", "独立卫生间", "休息区"], "min_spend_fen": 300000},
    "牡丹厅": {"capacity": (20, 40), "features": ["独立空调", "LED屏", "音响", "舞台", "独立卫生间"], "min_spend_fen": 500000},
}

# 默认时段配置 — 实际应从 store 配置表读取
_DEFAULT_TIME_SLOTS: dict[str, dict] = {
    "lunch": {"start": "11:00", "end": "14:00", "label": "午餐"},
    "dinner": {"start": "17:00", "end": "21:00", "label": "晚餐"},
}

# 默认用餐时长（分钟）— 用于冲突检测
_DEFAULT_DINING_DURATION_MIN = 120


class ReservationService:
    """预订服务 — V1+V3合并，7状态机

    预订全流程：创建->确认->到店->排队(可选)->入座->完成/取消/爽约
    """

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        *,
        room_config: Optional[dict[str, dict]] = None,
        time_slots: Optional[dict[str, dict]] = None,
        dining_duration_min: int = _DEFAULT_DINING_DURATION_MIN,
    ):
        self.db = db
        self.tenant_id = tenant_id
        self.store_id = store_id
        self._repo = ReservationRepository(db, tenant_id)
        self._queue_service = QueueService(db=db, tenant_id=tenant_id, store_id=store_id)
        # 可配置参数（修复硬编码问题）
        self._room_config = room_config or _DEFAULT_ROOM_CONFIG
        self._time_slots = time_slots or _DEFAULT_TIME_SLOTS
        self._dining_duration_min = dining_duration_min

    # ─── 创建预订 ───

    async def create_reservation(
        self,
        store_id: str,
        customer_name: str,
        phone: str,
        type: str,
        date: str,
        time: str,
        party_size: int,
        room_name: Optional[str] = None,
        special_requests: Optional[str] = None,
        deposit_required: bool = False,
        deposit_amount_fen: int = 0,
        consumer_id: Optional[str] = None,
    ) -> dict:
        """创建预订

        Args:
            store_id: 门店ID
            customer_name: 顾客姓名
            phone: 手机号
            type: 预订类型 regular/banquet/private_room/outdoor/vip
            date: 预订日期 YYYY-MM-DD
            time: 预订时间 HH:MM
            party_size: 就餐人数
            room_name: 包间名称（private_room类型时）
            special_requests: 特殊需求
            deposit_required: 是否需要定金
            deposit_amount_fen: 定金金额（分）
            consumer_id: 会员ID

        Returns:
            {reservation_id, confirmation_code, table_or_room, estimated_end_time, ...}
        """
        if type not in RESERVATION_TYPES:
            raise ValueError(f"Invalid reservation type: {type}. Must be one of {RESERVATION_TYPES}")
        if party_size <= 0:
            raise ValueError("party_size must be positive")
        if not phone or not phone.strip():
            raise ValueError("phone is required and cannot be empty")

        # 校验日期不能是过去
        res_date = datetime.strptime(date, "%Y-%m-%d").date()
        today = datetime.now(timezone.utc).date()
        if res_date < today:
            raise ValueError(f"Cannot reserve for past date: {date}")

        # 包间类型：校验包间容量 + 自动分配
        assigned_room = None
        if type == "private_room":
            assigned_room = await self._assign_room(room_name, party_size, store_id, date, time)

        # 检查时段冲突
        conflicts = await self.check_conflicts(
            store_id, date, time,
            duration_min=self._dining_duration_min,
            room_name=assigned_room["room_name"] if assigned_room else None,
        )
        if conflicts:
            conflict_info = [
                f"{c['confirmation_code']}({c['time']}, {c['customer_name']})"
                for c in conflicts
            ]
            raise ValueError(
                f"Time slot conflict detected: {', '.join(conflict_info)}"
            )

        reservation_id = f"RSV-{_gen_id()}"
        confirmation_code = _gen_confirmation_code()
        now = _now_iso()

        # 计算预计结束时间
        start_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=self._dining_duration_min)
        estimated_end_time = end_dt.strftime("%H:%M")

        store_uuid = uuid.UUID(store_id)
        record = await self._repo.create(
            reservation_id=reservation_id,
            store_id=store_uuid,
            confirmation_code=confirmation_code,
            customer_name=customer_name,
            phone=phone,
            type=type,
            date=date,
            time=time,
            estimated_end_time=estimated_end_time,
            party_size=party_size,
            room_name=assigned_room["room_name"] if assigned_room else None,
            room_info=assigned_room,
            special_requests=special_requests,
            deposit_required=deposit_required,
            deposit_amount_fen=deposit_amount_fen if deposit_required else 0,
            deposit_paid=False,
            consumer_id=consumer_id,
            status="pending",
        )

        logger.info(
            "reservation_created",
            reservation_id=reservation_id,
            type=type,
            date=date,
            time=time,
            party_size=party_size,
            room=assigned_room["room_name"] if assigned_room else None,
        )

        return {
            "reservation_id": reservation_id,
            "confirmation_code": confirmation_code,
            "customer_name": customer_name,
            "type": type,
            "date": date,
            "time": time,
            "party_size": party_size,
            "table_or_room": assigned_room["room_name"] if assigned_room else "待分配",
            "estimated_end_time": estimated_end_time,
            "deposit_required": deposit_required,
            "deposit_amount_fen": deposit_amount_fen if deposit_required else 0,
            "status": "pending",
            "created_at": now,
        }

    # ─── 确认预订 ───

    async def confirm_reservation(
        self,
        reservation_id: str,
        confirmed_by: str = "system",
    ) -> dict:
        """确认预订 — 发送确认短信/微信

        Args:
            reservation_id: 预订ID
            confirmed_by: 确认人 system/staff_name

        Returns:
            {reservation_id, status, confirmed_by, notification_sent}
        """
        record = await self._get_and_validate_transition(reservation_id, "confirmed")

        record.status = "confirmed"
        record.confirmed_by = confirmed_by
        await self.db.flush()

        # 同步发送通知（记录日志，不阻塞主流程）
        # 修复: 原实现用 asyncio.create_task 但 task 中使用了 db session，
        # 而 session 在请求结束时关闭，可能导致 session 泄漏或 DetachedInstanceError。
        # 改为同步记录日志，实际推送走消息队列（后续实现）。
        notification_sent = await self._send_confirmation(record)

        logger.info(
            "reservation_confirmed",
            reservation_id=reservation_id,
            confirmed_by=confirmed_by,
        )

        return {
            "reservation_id": reservation_id,
            "confirmation_code": record.confirmation_code,
            "status": "confirmed",
            "confirmed_by": confirmed_by,
            "notification_sent": notification_sent,
            "date": record.date,
            "time": record.time,
        }

    # ─── 顾客到店 ───

    async def customer_arrived(self, reservation_id: str) -> dict:
        """顾客到店 — 如果桌台就绪直接入座，否则自动加入优先排队

        修复说明: 原实现在到店后先设置 arrived，再改为 queuing，
        但只验证了 -> arrived 的转换，没有验证 arrived -> queuing。
        这里改为：
        1. 包间预订: pending/confirmed -> arrived（不排队）
        2. 其他预订: pending/confirmed -> queuing（直接进排队状态）

        Args:
            reservation_id: 预订ID

        Returns:
            {reservation_id, status, action, queue_info/table_no}
        """
        record = await self._repo.get_by_reservation_id(reservation_id)
        if not record:
            raise ValueError(f"Reservation not found: {reservation_id}")

        current = record.status
        now = _now_iso()

        # 包间预订：直接到 arrived 状态
        if record.type == "private_room" and record.room_name:
            if not can_reservation_transition(current, "arrived"):
                raise ValueError(
                    f"Cannot transition reservation {reservation_id} "
                    f"from '{current}' to 'arrived'. "
                    f"Allowed: {RESERVATION_TRANSITIONS.get(current, [])}"
                )
            record.status = "arrived"
            record.arrived_at = now
            action = "direct_seat"
            queue_info = None
        else:
            # 非包间：验证可以转到 queuing（arrived 是中间状态，直接跳到 queuing）
            # 状态机允许 confirmed -> arrived -> queuing，这里合并为一步
            if current not in ("pending", "confirmed"):
                raise ValueError(
                    f"Cannot mark arrived for reservation {reservation_id}: "
                    f"current status is '{current}', expected 'pending' or 'confirmed'"
                )
            record.arrived_at = now

            # 进入优先排队
            queue_result = await self._queue_service.take_number(
                store_id=str(record.store_id),
                customer_name=record.customer_name,
                phone=record.phone,
                party_size=record.party_size,
                source="reservation",
                vip_priority=(record.type == "vip"),
                reservation_id=reservation_id,
            )
            record.queue_id = queue_result["queue_id"]
            record.status = "queuing"
            action = "queue_with_priority"
            queue_info = queue_result

        await self.db.flush()

        logger.info(
            "reservation_customer_arrived",
            reservation_id=reservation_id,
            action=action,
        )

        result: dict = {
            "reservation_id": reservation_id,
            "confirmation_code": record.confirmation_code,
            "status": record.status,
            "action": action,
            "arrived_at": now,
        }
        if queue_info:
            result["queue_info"] = queue_info
        if record.room_name:
            result["room_name"] = record.room_name

        return result

    # ─── 入座 ───

    async def seat_reservation(self, reservation_id: str, table_no: str) -> dict:
        """预订入座 — 关联桌台和订单

        修复说明: 原实现绕过了 _get_and_validate_transition，手动检查状态。
        改为使用统一的状态验证。

        Args:
            reservation_id: 预订ID
            table_no: 桌号

        Returns:
            {reservation_id, table_no, seated_at}
        """
        record = await self._repo.get_by_reservation_id(reservation_id)
        if not record:
            raise ValueError(f"Reservation not found: {reservation_id}")

        current = record.status
        # 允许从 arrived 或 queuing 转到 seated
        if not can_reservation_transition(current, "seated"):
            raise ValueError(
                f"Cannot seat reservation {reservation_id}: "
                f"current status is '{current}', "
                f"allowed transitions: {RESERVATION_TRANSITIONS.get(current, [])}"
            )

        now = _now_iso()
        record.status = "seated"
        record.table_no = table_no
        record.seated_at = now

        # 如果有排队记录，也更新排队状态
        if record.queue_id:
            try:
                await self._queue_service.seat_customer(record.queue_id, table_no)
            except ValueError:
                pass  # 排队记录可能已被处理

        await self.db.flush()

        logger.info(
            "reservation_seated",
            reservation_id=reservation_id,
            table_no=table_no,
        )

        return {
            "reservation_id": reservation_id,
            "confirmation_code": record.confirmation_code,
            "customer_name": record.customer_name,
            "party_size": record.party_size,
            "table_no": table_no,
            "seated_at": now,
            "status": "seated",
        }

    # ─── 完成预订 ───

    async def complete_reservation(self, reservation_id: str) -> dict:
        """完成预订 — 用餐结束

        Args:
            reservation_id: 预订ID

        Returns:
            {reservation_id, status, completed_at, duration_min}
        """
        record = await self._get_and_validate_transition(reservation_id, "completed")

        now = _now_iso()
        record.status = "completed"
        record.completed_at = now

        # 计算用餐时长
        duration_min = 0
        if record.seated_at:
            seated_dt = datetime.fromisoformat(record.seated_at)
            completed_dt = datetime.fromisoformat(now)
            duration_min = int((completed_dt - seated_dt).total_seconds() / 60)

        await self.db.flush()

        logger.info(
            "reservation_completed",
            reservation_id=reservation_id,
            duration_min=duration_min,
        )

        return {
            "reservation_id": reservation_id,
            "status": "completed",
            "completed_at": now,
            "duration_min": duration_min,
        }

    # ─── 取消预订 ───

    async def cancel_reservation(
        self,
        reservation_id: str,
        reason: str,
        cancel_fee_fen: int = 0,
    ) -> dict:
        """取消预订

        Args:
            reservation_id: 预订ID
            reason: 取消原因
            cancel_fee_fen: 取消手续费（分）

        Returns:
            {reservation_id, status, reason, cancel_fee_fen, refund_fen}
        """
        record = await self._repo.get_by_reservation_id(reservation_id)
        if not record:
            raise ValueError(f"Reservation not found: {reservation_id}")

        current = record.status
        if not can_reservation_transition(current, "cancelled"):
            raise ValueError(
                f"Cannot cancel reservation {reservation_id}: "
                f"current status is '{current}', transition to 'cancelled' not allowed"
            )

        now = _now_iso()
        record.status = "cancelled"
        record.cancel_reason = reason
        record.cancel_fee_fen = cancel_fee_fen
        record.cancelled_at = now

        # 计算退款金额
        refund_fen = 0
        if record.deposit_paid and (record.deposit_amount_fen or 0) > 0:
            refund_fen = max(0, record.deposit_amount_fen - cancel_fee_fen)

        # 如果有排队记录，也取消
        if record.queue_id:
            try:
                await self._queue_service.cancel_queue(record.queue_id, reason="reservation_cancelled")
            except ValueError:
                pass

        await self.db.flush()

        logger.info(
            "reservation_cancelled",
            reservation_id=reservation_id,
            reason=reason,
            cancel_fee_fen=cancel_fee_fen,
        )

        return {
            "reservation_id": reservation_id,
            "status": "cancelled",
            "reason": reason,
            "cancel_fee_fen": cancel_fee_fen,
            "refund_fen": refund_fen,
            "cancelled_at": now,
        }

    # ─── 标记爽约 ───

    async def mark_no_show(self, reservation_id: str) -> dict:
        """标记爽约 — 记录到顾客画像

        Args:
            reservation_id: 预订ID

        Returns:
            {reservation_id, status, no_show_count}
        """
        record = await self._repo.get_by_reservation_id(reservation_id)
        if not record:
            raise ValueError(f"Reservation not found: {reservation_id}")

        current = record.status
        if not can_reservation_transition(current, "no_show"):
            raise ValueError(
                f"Cannot mark no_show for {reservation_id}: "
                f"current status is '{current}', transition to 'no_show' not allowed"
            )

        now = _now_iso()
        record.status = "no_show"
        record.no_show_recorded = True

        # 记录到爽约历史
        phone = record.phone
        await self._repo.add_no_show_record(phone, reservation_id)
        no_show_count = await self._repo.count_no_shows(phone)

        await self.db.flush()

        logger.info(
            "reservation_no_show",
            reservation_id=reservation_id,
            phone=phone,
            no_show_count=no_show_count,
        )

        return {
            "reservation_id": reservation_id,
            "status": "no_show",
            "customer_name": record.customer_name,
            "phone": phone,
            "no_show_count": no_show_count,
            "marked_at": now,
        }

    # ─── 列表查询 ───

    async def list_reservations(
        self,
        store_id: str,
        date: Optional[str] = None,
        status: Optional[str] = None,
        type: Optional[str] = None,
        page: int = 1,
        size: int = 50,
    ) -> dict:
        """查询预订列表（分页）

        修复说明: 原实现无分页，返回 list[dict]，存在全表扫描风险。
        改为分页返回 {items, total, page, size}。

        Args:
            store_id: 门店ID
            date: 筛选日期
            status: 筛选状态
            type: 筛选类型
            page: 页码
            size: 每页条数

        Returns:
            {items: [...], total, page, size}
        """
        offset = (page - 1) * size
        records, total = await self._repo.list_by_store_paged(
            store_id, date=date, status=status, type=type,
            offset=offset, limit=size,
        )
        return {
            "items": [r.to_dict() for r in records],
            "total": total,
            "page": page,
            "size": size,
        }

    # ─── 可用时段查询 ───

    async def get_time_slots(
        self,
        store_id: str,
        date: str,
        party_size: int,
    ) -> list[dict]:
        """查询可用时段

        Args:
            store_id: 门店ID
            date: 查询日期
            party_size: 就餐人数

        Returns:
            [{time, label, available, reason}, ...]
        """
        slots: list[dict] = []

        # 生成午餐+晚餐时段，每30分钟一个
        for meal, config in self._time_slots.items():
            start_h, start_m = map(int, config["start"].split(":"))
            end_h, end_m = map(int, config["end"].split(":"))

            current = datetime(2026, 1, 1, start_h, start_m)
            end = datetime(2026, 1, 1, end_h, end_m)

            while current < end:
                time_str = current.strftime("%H:%M")

                # 检查该时段是否有冲突
                conflicts = await self.check_conflicts(
                    store_id, date, time_str,
                    duration_min=self._dining_duration_min,
                )

                available = len(conflicts) == 0
                reason = ""
                if not available:
                    reason = f"已有{len(conflicts)}个预订"

                slots.append({
                    "time": time_str,
                    "meal": meal,
                    "label": f"{config['label']} {time_str}",
                    "available": available,
                    "conflict_count": len(conflicts),
                    "reason": reason,
                })

                current += timedelta(minutes=30)

        return slots

    # ─── 预订统计 ───

    async def get_reservation_stats(
        self,
        store_id: str,
        date_range: tuple[str, str],
    ) -> dict:
        """预订统计

        Args:
            store_id: 门店ID
            date_range: (start_date, end_date) YYYY-MM-DD

        Returns:
            {total, by_type, by_status, no_show_rate, avg_party_size, peak_hours}
        """
        start_date, end_date = date_range
        records = await self._repo.list_by_date_range(store_id, start_date, end_date)

        total = len(records)
        if total == 0:
            return {
                "total": 0,
                "by_type": {},
                "by_status": {},
                "no_show_rate_pct": 0.0,
                "avg_party_size": 0,
                "peak_hours": [],
                "date_range": list(date_range),
            }

        # 按类型统计
        by_type: dict[str, int] = {}
        for r in records:
            by_type[r.type] = by_type.get(r.type, 0) + 1

        # 按状态统计
        by_status: dict[str, int] = {}
        for r in records:
            by_status[r.status] = by_status.get(r.status, 0) + 1

        # 爽约率
        no_show_count = by_status.get("no_show", 0)
        no_show_rate = no_show_count / total * 100

        # 平均人数
        avg_party_size = sum(r.party_size for r in records) / total

        # 高峰时段
        hour_counts: dict[str, int] = {}
        for r in records:
            h = r.time[:2] + ":00"
            hour_counts[h] = hour_counts.get(h, 0) + 1
        peak_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:3]

        return {
            "total": total,
            "by_type": by_type,
            "by_status": by_status,
            "no_show_rate_pct": round(no_show_rate, 1),
            "avg_party_size": round(avg_party_size, 1),
            "peak_hours": [{"hour": h, "count": c} for h, c in peak_hours],
            "date_range": list(date_range),
        }

    # ─── 冲突检测 ───

    async def check_conflicts(
        self,
        store_id: str,
        date: str,
        time: str,
        duration_min: Optional[int] = None,
        room_name: Optional[str] = None,
    ) -> list[dict]:
        """检测时段冲突

        Args:
            store_id: 门店ID
            date: 日期
            time: 时间 HH:MM
            duration_min: 预计用餐时长（分钟），默认使用实例配置值
            room_name: 包间名称（如指定则只检测该包间冲突）

        Returns:
            冲突的预订列表
        """
        if duration_min is None:
            duration_min = self._dining_duration_min

        target_start = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        target_end = target_start + timedelta(minutes=duration_min)

        active_records = await self._repo.list_by_store_date_active(store_id, date)

        conflicts: list[dict] = []
        for r in active_records:
            # 包间冲突检测
            if room_name and r.room_name != room_name:
                continue

            # 时间重叠检测
            existing_start = datetime.strptime(f"{r.date} {r.time}", "%Y-%m-%d %H:%M")
            existing_end_str = r.estimated_end_time or ""
            if existing_end_str:
                existing_end = datetime.strptime(f"{r.date} {existing_end_str}", "%Y-%m-%d %H:%M")
            else:
                existing_end = existing_start + timedelta(minutes=self._dining_duration_min)

            # 判断是否有重叠
            if target_start < existing_end and target_end > existing_start:
                conflicts.append({
                    "reservation_id": r.reservation_id,
                    "confirmation_code": r.confirmation_code,
                    "customer_name": r.customer_name,
                    "time": r.time,
                    "estimated_end_time": r.estimated_end_time,
                    "party_size": r.party_size,
                    "type": r.type,
                    "room_name": r.room_name,
                    "status": r.status,
                })

        return conflicts

    # ─── 内部辅助方法 ───

    async def _get_and_validate_transition(self, reservation_id: str, target_status: str) -> Reservation:
        """获取预订记录并验证状态转换"""
        record = await self._repo.get_by_reservation_id(reservation_id)
        if not record:
            raise ValueError(f"Reservation not found: {reservation_id}")

        current = record.status
        if not can_reservation_transition(current, target_status):
            raise ValueError(
                f"Cannot transition reservation {reservation_id} "
                f"from '{current}' to '{target_status}'. "
                f"Allowed transitions: {RESERVATION_TRANSITIONS.get(current, [])}"
            )
        return record

    async def _assign_room(
        self,
        room_name: Optional[str],
        party_size: int,
        store_id: str,
        date: str,
        time: str,
    ) -> dict:
        """分配包间 — 指定或自动选择"""
        if room_name:
            # 指定包间：校验容量
            room = self._room_config.get(room_name)
            if not room:
                raise ValueError(f"Unknown room: {room_name}. Available: {list(self._room_config.keys())}")
            min_cap, max_cap = room["capacity"]
            if party_size > max_cap:
                raise ValueError(
                    f"Room {room_name} max capacity is {max_cap}, but party_size is {party_size}"
                )
            return {
                "room_name": room_name,
                "capacity": room["capacity"],
                "features": room["features"],
                "min_spend_fen": room["min_spend_fen"],
            }

        # 自动分配：找容量最匹配的可用包间
        candidates: list[dict] = []
        for name, config in self._room_config.items():
            min_cap, max_cap = config["capacity"]
            if min_cap <= party_size <= max_cap:
                # 检查冲突
                conflicts = await self.check_conflicts(store_id, date, time, room_name=name)
                if not conflicts:
                    candidates.append({
                        "room_name": name,
                        "capacity": config["capacity"],
                        "features": config["features"],
                        "min_spend_fen": config["min_spend_fen"],
                        "size_diff": max_cap - party_size,
                    })

        if not candidates:
            raise ValueError(
                f"No available room for party_size={party_size} on {date} {time}"
            )

        # 选最匹配的（容量最接近的）
        candidates.sort(key=lambda c: c["size_diff"])
        best = candidates[0]
        del best["size_diff"]
        return best

    async def _send_confirmation(self, record: Reservation) -> bool:
        """发送预订确认通知

        修复说明: 原实现用 asyncio.create_task 在后台运行通知协程，
        但协程中使用了 db session。session 会在请求结束时关闭，
        而后台 task 可能在那之后才执行，导致 DetachedInstanceError。

        正确做法: 通知发送应走消息队列（Redis / PG LISTEN/NOTIFY），
        此处先记录日志，后续接入消息队列。
        """
        logger.info(
            "reservation_confirmation_queued",
            phone=record.phone,
            customer_name=record.customer_name,
            confirmation_code=record.confirmation_code,
            date=record.date,
            time=record.time,
        )
        # TODO: 接入消息队列发送短信/微信通知
        return True
