"""预订备餐联动服务 — 将预订菜品需求聚合并生成KDS预备单

Schema SQL（在数据库中手动执行）:
    CREATE TABLE IF NOT EXISTS booking_prep_tasks (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL,
      booking_id UUID NOT NULL,
      store_id UUID NOT NULL,
      dish_id UUID NOT NULL,
      dish_name TEXT NOT NULL,
      quantity INT NOT NULL DEFAULT 1,
      dept_id TEXT,
      prep_start_at TIMESTAMPTZ,
      status TEXT NOT NULL DEFAULT 'pending',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      UNIQUE(tenant_id, booking_id, dish_id)
    );
    ALTER TABLE booking_prep_tasks ENABLE ROW LEVEL SECURITY;
    CREATE POLICY booking_prep_tasks_tenant ON booking_prep_tasks
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);

路由注册（在 main.py 中添加）:
    from .api.booking_prep_routes import router as booking_prep_router
    app.include_router(booking_prep_router, prefix="/api/v1/booking-prep")
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ─── 档口映射：菜品类型关键词 → dept_id ───
# 生产环境中应从数据库的菜品档口配置表读取；此处为默认内置映射
_DEPT_KEYWORD_MAP: dict[str, str] = {
    "烤鸭": "roast",
    "烤": "roast",
    "烧": "roast",
    "炒": "wok",
    "爆炒": "wok",
    "小炒": "wok",
    "炖": "stew",
    "煨": "stew",
    "红烧": "stew",
    "蒸": "steam",
    "清蒸": "steam",
    "粉蒸": "steam",
    "凉拌": "cold",
    "冷": "cold",
    "卤": "cold",
    "汤": "soup",
    "火锅": "hotpot",
    "涮": "hotpot",
}

_DEFAULT_DEPT = "wok"  # 兜底档口


def _resolve_dept(dish_name: str) -> str:
    """根据菜品名称匹配出品档口，无匹配则使用默认档口。"""
    for keyword, dept in _DEPT_KEYWORD_MAP.items():
        if keyword in dish_name:
            return dept
    return _DEFAULT_DEPT


# ─── 数据模型 ───


@dataclass
class BookingPrepTask:
    id: str
    tenant_id: str
    booking_id: str
    store_id: str
    dish_id: str
    dish_name: str
    quantity: int
    dept_id: str
    prep_start_at: datetime | None
    status: str  # pending | started | done
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "booking_id": self.booking_id,
            "store_id": self.store_id,
            "dish_id": self.dish_id,
            "dish_name": self.dish_name,
            "quantity": self.quantity,
            "dept_id": self.dept_id,
            "prep_start_at": self.prep_start_at.isoformat() if self.prep_start_at else None,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class DishSummary:
    dish_name: str
    total_qty: int
    booking_count: int


@dataclass
class BookingSummary:
    today_count: int
    week_count: int
    top_dishes: list[DishSummary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "today_count": self.today_count,
            "week_count": self.week_count,
            "top_dishes": [
                {
                    "dish_name": d.dish_name,
                    "total_qty": d.total_qty,
                    "booking_count": d.booking_count,
                }
                for d in self.top_dishes
            ],
        }


# ─── 内存存储（单元测试用；生产中替换为 SQLAlchemy ORM 操作） ───
# key: (tenant_id, task_id)
_tasks: dict[tuple[str, str], BookingPrepTask] = {}


def _clear_store() -> None:
    """测试辅助：清空内存存储。"""
    _tasks.clear()


# ─── 模拟预订数据存储（生产中由 ReservationService / DB 提供） ───
# key: (tenant_id, booking_id) → dict with keys: store_id, date, dining_at, items
_bookings: dict[tuple[str, str], dict[str, Any]] = {}


def _register_booking(
    tenant_id: str,
    booking_id: str,
    store_id: str,
    dining_at: datetime,
    items: list[dict[str, Any]],
) -> None:
    """测试辅助：注册预订信息（items 格式: [{dish_id, dish_name, quantity}]）。"""
    _bookings[(tenant_id, booking_id)] = {
        "store_id": store_id,
        "dining_at": dining_at,
        "items": items,
    }


# ─── 服务类 ───


class BookingPrepService:
    """预订备餐联动服务。

    所有方法均为同步方法，使用内存存储以保持轻量可测试。
    生产部署时可通过注入 AsyncSession 替换存储层。
    """

    # ── 今日/本周汇总 ──

    @staticmethod
    def get_today_summary(
        store_id: str,
        tenant_id: str,
        db: Any = None,  # noqa: ARG004 — 预留 DB session 参数，测试时为 None
    ) -> BookingSummary:
        """计算今日/本周预订数与菜品需求 TOP10。

        参数:
            store_id: 门店 ID
            tenant_id: 租户 ID
            db: DB session（当前版本使用内存存储，未使用此参数）

        返回:
            BookingSummary 对象
        """
        now = datetime.now(timezone.utc)
        today = now.date()
        week_start = today - timedelta(days=today.weekday())
        week_end = today + timedelta(days=6 - today.weekday())

        # 统计预订数（按 booking_id 去重）
        today_booking_ids: set[str] = set()
        week_booking_ids: set[str] = set()

        for (tid, bid), info in _bookings.items():
            if tid != tenant_id:
                continue
            if info["store_id"] != store_id:
                continue
            dining_date: date = info["dining_at"].date() if hasattr(info["dining_at"], "date") else info["dining_at"]
            if dining_date == today:
                today_booking_ids.add(bid)
            if week_start <= dining_date <= week_end:
                week_booking_ids.add(bid)

        # 聚合菜品需求（本周范围内）
        dish_qty: dict[str, int] = {}
        dish_booking_count: dict[str, set[str]] = {}

        for (tid, bid), info in _bookings.items():
            if tid != tenant_id:
                continue
            if info["store_id"] != store_id:
                continue
            dining_date = info["dining_at"].date() if hasattr(info["dining_at"], "date") else info["dining_at"]
            if not (week_start <= dining_date <= week_end):
                continue
            for item in info.get("items", []):
                name = item["dish_name"]
                qty = item.get("quantity", 1)
                dish_qty[name] = dish_qty.get(name, 0) + qty
                dish_booking_count.setdefault(name, set()).add(bid)

        # 排序取 TOP10
        sorted_dishes = sorted(dish_qty.items(), key=lambda x: x[1], reverse=True)[:10]
        top_dishes = [
            DishSummary(
                dish_name=name,
                total_qty=qty,
                booking_count=len(dish_booking_count[name]),
            )
            for name, qty in sorted_dishes
        ]

        log = logger.bind(store_id=store_id, tenant_id=tenant_id)
        log.info(
            "booking_prep.today_summary",
            today_count=len(today_booking_ids),
            week_count=len(week_booking_ids),
            top_dish_count=len(top_dishes),
        )

        return BookingSummary(
            today_count=len(today_booking_ids),
            week_count=len(week_booking_ids),
            top_dishes=top_dishes,
        )

    # ── 生成备餐任务（幂等） ──

    @staticmethod
    def generate_prep_tasks(
        booking_id: str,
        tenant_id: str,
        db: Any = None,  # noqa: ARG004
    ) -> list[BookingPrepTask]:
        """根据预订中的 items 生成备餐任务，分配到对应档口。

        幂等：同一 booking 重复调用返回已存在任务，不会创建重复记录。

        参数:
            booking_id: 预订 ID
            tenant_id: 租户 ID
            db: DB session（当前版本使用内存存储）

        异常:
            ValueError: 预订不存在或无菜品

        返回:
            BookingPrepTask 列表
        """
        booking_info = _bookings.get((tenant_id, booking_id))
        if booking_info is None:
            raise ValueError(f"预订 {booking_id} 不存在（tenant={tenant_id}）")

        items = booking_info.get("items", [])
        if not items:
            raise ValueError(f"预订 {booking_id} 没有菜品信息，无法生成备餐任务")

        store_id = booking_info["store_id"]
        now = datetime.now(timezone.utc)

        # 检查是否已存在（幂等）
        existing = [t for t in _tasks.values() if t.tenant_id == tenant_id and t.booking_id == booking_id]
        if existing:
            logger.info(
                "booking_prep.generate_tasks.idempotent",
                booking_id=booking_id,
                tenant_id=tenant_id,
                task_count=len(existing),
            )
            return existing

        # 生成新任务
        created: list[BookingPrepTask] = []
        for item in items:
            dish_id = str(item.get("dish_id", uuid.uuid4()))
            dish_name = item["dish_name"]
            quantity = int(item.get("quantity", 1))
            dept_id = item.get("dept_id") or _resolve_dept(dish_name)

            task = BookingPrepTask(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                booking_id=booking_id,
                store_id=store_id,
                dish_id=dish_id,
                dish_name=dish_name,
                quantity=quantity,
                dept_id=dept_id,
                prep_start_at=None,
                status="pending",
                created_at=now,
            )
            _tasks[(tenant_id, task.id)] = task
            created.append(task)

        logger.info(
            "booking_prep.generate_tasks.created",
            booking_id=booking_id,
            tenant_id=tenant_id,
            task_count=len(created),
        )
        return created

    # ── 待备餐任务列表 ──

    @staticmethod
    def get_pending_prep_tasks(
        store_id: str,
        tenant_id: str,
        db: Any = None,  # noqa: ARG004
    ) -> list[BookingPrepTask]:
        """获取当前待备餐/进行中任务，按预计开餐时间排序（最近先显示）。

        参数:
            store_id: 门店 ID
            tenant_id: 租户 ID
            db: DB session

        返回:
            状态为 pending 或 started 的 BookingPrepTask 列表
        """
        result = [
            t
            for t in _tasks.values()
            if t.tenant_id == tenant_id and t.store_id == store_id and t.status in ("pending", "started")
        ]

        # 按预订的 dining_at 排序（最近开餐时间优先）
        def sort_key(task: BookingPrepTask) -> datetime:
            booking = _bookings.get((tenant_id, task.booking_id))
            if booking is None:
                return datetime.max.replace(tzinfo=timezone.utc)
            dining_at = booking["dining_at"]
            if dining_at.tzinfo is None:
                dining_at = dining_at.replace(tzinfo=timezone.utc)
            return dining_at

        result.sort(key=sort_key)
        return result

    # ── 状态流转 ──

    @staticmethod
    def mark_prep_started(
        task_id: str,
        tenant_id: str,
        db: Any = None,  # noqa: ARG004
    ) -> BookingPrepTask:
        """标记备餐开始（pending → started）。

        异常:
            ValueError: 任务不存在或状态不合法
        """
        task = _tasks.get((tenant_id, task_id))
        if task is None:
            raise ValueError(f"备餐任务 {task_id} 不存在（tenant={tenant_id}）")
        if task.status != "pending":
            raise ValueError(f"任务 {task_id} 当前状态为 '{task.status}'，只有 pending 状态可开始备餐")
        task.status = "started"
        task.prep_start_at = datetime.now(timezone.utc)
        logger.info("booking_prep.task_started", task_id=task_id, tenant_id=tenant_id)
        return task

    @staticmethod
    def mark_prep_done(
        task_id: str,
        tenant_id: str,
        db: Any = None,  # noqa: ARG004
    ) -> BookingPrepTask:
        """标记备餐完成（started → done）。

        异常:
            ValueError: 任务不存在或状态不合法
        """
        task = _tasks.get((tenant_id, task_id))
        if task is None:
            raise ValueError(f"备餐任务 {task_id} 不存在（tenant={tenant_id}）")
        if task.status != "started":
            raise ValueError(f"任务 {task_id} 当前状态为 '{task.status}'，只有 started 状态可完成备餐")
        task.status = "done"
        logger.info("booking_prep.task_done", task_id=task_id, tenant_id=tenant_id)
        return task
