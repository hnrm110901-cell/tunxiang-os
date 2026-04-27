"""桌台监控服务 — 前厅大屏数据聚合

提供桌台视角的实时状态汇总：
- 按桌台（table_number）聚合 kds_tasks
- 计算起菜时长、超时状态、催单次数
- 按区域（包厢/大厅）分组汇总

USAGE:
    from .services.table_monitor_service import TableMonitorService
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem

from ..models.kds_task import KDSTask

logger = structlog.get_logger()

# 默认超时阈值（分钟）
DEFAULT_STANDARD_MINUTES = 25


# ─── Pydantic 响应模型 ───


class PendingDish(BaseModel):
    name: str
    status: str  # pending / cooking
    dept: str


class TableStatus(BaseModel):
    table_id: str  # 等同于 table_number，前端唯一标识
    table_no: str
    zone: str  # "包厢" | "大厅"
    status: str  # idle | ordering | cooking | ready | rush | overtime
    dish_total: int
    dish_done: int
    elapsed_minutes: int
    standard_minutes: int
    is_overtime: bool
    rush_count: int
    pending_dishes: list[PendingDish]


class DishItem(BaseModel):
    task_id: str
    name: str
    qty: int
    status: str
    dept: str
    started_at: Optional[str]
    rush_count: int
    elapsed_minutes: int


class TableDetail(BaseModel):
    table_id: str
    table_no: str
    zone: str
    status: str
    dish_total: int
    dish_done: int
    elapsed_minutes: int
    standard_minutes: int
    is_overtime: bool
    rush_count: int
    dishes: list[DishItem]


class ZoneSummary(BaseModel):
    zone: str
    table_count: int
    overtime_count: int
    rush_count: int
    avg_elapsed: float


# ─── 区域推断 ───


def _infer_zone(table_no: str) -> str:
    """根据桌号推断区域：以 P/VIP/包 开头 → 包厢，否则 → 大厅"""
    upper = table_no.upper().strip()
    if upper.startswith(("P", "VIP", "包")):
        return "包厢"
    return "大厅"


def _infer_table_status(
    dish_total: int,
    dish_done: int,
    is_overtime: bool,
    rush_count: int,
    active_tasks: list,
) -> str:
    """推断桌台状态"""
    if dish_total == 0:
        return "idle"
    if is_overtime:
        return "overtime"
    if rush_count > 0:
        return "rush"
    if dish_done == dish_total:
        return "ready"
    has_cooking = any(getattr(t, "status", "") == "cooking" for t in active_tasks)
    if has_cooking:
        return "cooking"
    return "ordering"


def _ensure_utc(dt: datetime) -> datetime:
    """确保 datetime 为 UTC aware。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ─── TableMonitorService ───


class TableMonitorService:
    @staticmethod
    async def get_store_overview(
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[TableStatus]:
        """聚合全店所有桌台的实时状态。

        只查询 status IN ('pending', 'cooking') 的活跃 kds_tasks。
        按 table_number 聚合。
        """
        try:
            tid = uuid.UUID(tenant_id)
            sid = uuid.UUID(store_id)
        except ValueError as exc:
            raise ValueError(f"无效的 UUID: {exc}") from exc

        now = datetime.now(timezone.utc)

        # 联表：kds_tasks → order_items → orders，过滤当前门店 + 活跃任务
        stmt = (
            select(
                KDSTask,
                OrderItem.item_name,
                OrderItem.quantity,
                Order.table_number,
                Order.created_at.label("order_created_at"),
            )
            .join(OrderItem, KDSTask.order_item_id == OrderItem.id)
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                and_(
                    KDSTask.tenant_id == tid,
                    KDSTask.is_deleted.is_(False),
                    KDSTask.status.in_(["pending", "cooking"]),
                    Order.store_id == sid,
                    Order.is_deleted.is_(False),
                )
            )
        )

        rows = (await db.execute(stmt)).all()

        # 按 table_number 聚合
        # key: table_number (str), value: aggregation dict
        table_map: dict[str, dict] = {}
        for row in rows:
            task: KDSTask = row[0]
            item_name: str = row[1] or ""
            qty: int = row[2] or 1
            table_no: str = row[3] or ""
            order_created_at: datetime = row[4]

            if not table_no:
                continue  # 无桌号（外卖/零售）跳过

            if table_no not in table_map:
                table_map[table_no] = {
                    "table_no": table_no,
                    "order_created_at": order_created_at,
                    "tasks": [],
                    "task_row_pairs": [],
                    "dish_total": 0,
                    "dish_done": 0,
                    "rush_count": 0,
                }

            entry = table_map[table_no]
            entry["tasks"].append(task)
            entry["task_row_pairs"].append((task, item_name, qty))
            entry["dish_total"] += qty
            entry["rush_count"] = max(entry["rush_count"], task.rush_count)

            # 保留最早的 order_created_at 作为起菜参考时间
            if _ensure_utc(order_created_at) < _ensure_utc(entry["order_created_at"]):
                entry["order_created_at"] = order_created_at

        # 查询已完成（done）的菜品数量
        if table_map:
            table_nos = list(table_map.keys())
            done_stmt = (
                select(
                    Order.table_number,
                    func.sum(OrderItem.quantity).label("done_qty"),
                )
                .join(OrderItem, KDSTask.order_item_id == OrderItem.id)
                .join(Order, OrderItem.order_id == Order.id)
                .where(
                    and_(
                        KDSTask.tenant_id == tid,
                        KDSTask.is_deleted.is_(False),
                        KDSTask.status == "done",
                        Order.store_id == sid,
                        Order.table_number.in_(table_nos),
                        Order.is_deleted.is_(False),
                    )
                )
                .group_by(Order.table_number)
            )
            done_rows = (await db.execute(done_stmt)).all()
            for dr in done_rows:
                t_no: str = dr[0] or ""
                if t_no in table_map:
                    table_map[t_no]["dish_done"] = int(dr[1] or 0)

        result: list[TableStatus] = []
        for entry in table_map.values():
            elapsed = int((now - _ensure_utc(entry["order_created_at"])).total_seconds() // 60)
            is_overtime = elapsed > DEFAULT_STANDARD_MINUTES
            tasks: list[KDSTask] = entry["tasks"]
            table_status = _infer_table_status(
                entry["dish_total"],
                entry["dish_done"],
                is_overtime,
                entry["rush_count"],
                tasks,
            )

            # 构建 pending_dishes（未出品菜品摘要）
            pending_dishes: list[PendingDish] = [
                PendingDish(
                    name=item_name,
                    status=task.status,
                    dept=str(task.dept_id) if task.dept_id else "未知档口",
                )
                for task, item_name, _ in entry["task_row_pairs"]
                if task.status in ("pending", "cooking")
            ]

            tno = entry["table_no"]
            result.append(
                TableStatus(
                    table_id=tno,  # 用 table_number 作为唯一标识
                    table_no=tno,
                    zone=_infer_zone(tno),
                    status=table_status,
                    dish_total=entry["dish_total"],
                    dish_done=entry["dish_done"],
                    elapsed_minutes=elapsed,
                    standard_minutes=DEFAULT_STANDARD_MINUTES,
                    is_overtime=is_overtime,
                    rush_count=entry["rush_count"],
                    pending_dishes=pending_dishes,
                )
            )

        logger.info("table_monitor.overview", store_id=store_id, table_count=len(result))
        return result

    @staticmethod
    async def get_table_detail(
        table_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> Optional[TableDetail]:
        """获取单桌菜品级别详情（含已完成菜品）。

        Args:
            table_id: 即 table_number（桌号字符串），与 overview 中的 table_id 一致。
        """
        try:
            tid = uuid.UUID(tenant_id)
        except ValueError as exc:
            raise ValueError(f"无效的 UUID: {exc}") from exc

        now = datetime.now(timezone.utc)

        stmt = (
            select(
                KDSTask,
                OrderItem.item_name,
                OrderItem.quantity,
                Order.table_number,
                Order.created_at.label("order_created_at"),
            )
            .join(OrderItem, KDSTask.order_item_id == OrderItem.id)
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                and_(
                    KDSTask.tenant_id == tid,
                    KDSTask.is_deleted.is_(False),
                    KDSTask.status.in_(["pending", "cooking", "done"]),
                    Order.table_number == table_id,
                    Order.is_deleted.is_(False),
                )
            )
            .order_by(KDSTask.created_at.asc())
        )

        rows = (await db.execute(stmt)).all()
        if not rows:
            return None

        table_no: str = rows[0][3] or table_id
        order_created_at: datetime = rows[0][4]
        for row in rows:
            if _ensure_utc(row[4]) < _ensure_utc(order_created_at):
                order_created_at = row[4]

        elapsed = int((now - _ensure_utc(order_created_at)).total_seconds() // 60)
        is_overtime = elapsed > DEFAULT_STANDARD_MINUTES

        dishes: list[DishItem] = []
        total_rush = 0
        dish_total = 0
        dish_done = 0
        active_tasks: list[KDSTask] = []

        for row in rows:
            task: KDSTask = row[0]
            item_name: str = row[1] or ""
            qty: int = row[2] or 1

            dish_total += qty
            if task.status == "done":
                dish_done += qty
            else:
                active_tasks.append(task)

            total_rush = max(total_rush, task.rush_count)

            task_elapsed = 0
            if task.started_at:
                task_elapsed = int((now - _ensure_utc(task.started_at)).total_seconds() // 60)

            dishes.append(
                DishItem(
                    task_id=str(task.id),
                    name=item_name,
                    qty=qty,
                    status=task.status,
                    dept=str(task.dept_id) if task.dept_id else "未知档口",
                    started_at=task.started_at.isoformat() if task.started_at else None,
                    rush_count=task.rush_count,
                    elapsed_minutes=task_elapsed,
                )
            )

        table_status = _infer_table_status(dish_total, dish_done, is_overtime, total_rush, active_tasks)

        return TableDetail(
            table_id=table_id,
            table_no=table_no,
            zone=_infer_zone(table_no),
            status=table_status,
            dish_total=dish_total,
            dish_done=dish_done,
            elapsed_minutes=elapsed,
            standard_minutes=DEFAULT_STANDARD_MINUTES,
            is_overtime=is_overtime,
            rush_count=total_rush,
            dishes=dishes,
        )

    @staticmethod
    async def get_zone_summary(
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, ZoneSummary]:
        """按区域聚合全店桌台状态。

        Returns:
            {"包厢": ZoneSummary, "大厅": ZoneSummary}
        """
        tables = await TableMonitorService.get_store_overview(store_id, tenant_id, db)

        zones: dict[str, dict] = {}
        for t in tables:
            zone = t.zone
            if zone not in zones:
                zones[zone] = {
                    "table_count": 0,
                    "overtime_count": 0,
                    "rush_count": 0,
                    "total_elapsed": 0,
                }
            z = zones[zone]
            z["table_count"] += 1
            if t.is_overtime:
                z["overtime_count"] += 1
            if t.rush_count > 0:
                z["rush_count"] += t.rush_count
            z["total_elapsed"] += t.elapsed_minutes

        result: dict[str, ZoneSummary] = {}
        for zone, z in zones.items():
            avg_elapsed = round(z["total_elapsed"] / z["table_count"], 1) if z["table_count"] > 0 else 0.0
            result[zone] = ZoneSummary(
                zone=zone,
                table_count=z["table_count"],
                overtime_count=z["overtime_count"],
                rush_count=z["rush_count"],
                avg_elapsed=avg_elapsed,
            )

        return result

    @staticmethod
    async def get_alerts(
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[TableStatus]:
        """返回当前超时或有催单的桌台列表。"""
        tables = await TableMonitorService.get_store_overview(store_id, tenant_id, db)
        return [t for t in tables if t.is_overtime or t.rush_count > 0]
