"""table_production_plan.py — 同桌同出协调引擎（TableFire Coordinator）

原理：
  1. 分单完成后，为该桌创建 TableProductionPlan
  2. 计算各档口预计完成时间，T_max = 最慢档口
  3. 较快的档口设置延迟开始时间 = T_max - 自身预计时间 - 30s缓冲
  4. 档口完成时调用 notify_dept_ready，全部就绪后推送 WebSocket "table_ready"

约束：
  - tenant_id 在每个查询/创建中显式传入
  - 不硬编码密钥
  - 异常用 structlog 记录，不静默吞没
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from pydantic import BaseModel
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import UniversalPublisher

from ..models.table_production_plan import TableProductionPlan

logger = structlog.get_logger()

# ─── 常量 ───

COORD_BUFFER_SECONDS = 30  # 协调缓冲时间：给较慢档口30秒余量
URGENT_TIME_FACTOR = 0.75  # 催菜时预计时间乘以此系数（缩短25%）


# ─── 内存计划（供测试和跨请求协调使用）───


@dataclass
class TableProductionPlanInMemory:
    """内存中的协调计划（用于单次请求内的协调计算）"""

    id: uuid.UUID
    order_id: uuid.UUID
    table_no: str
    store_id: uuid.UUID
    tenant_id: uuid.UUID
    target_completion: datetime
    status: str
    dept_readiness: dict  # {dept_id: bool}
    dept_delays: dict  # {dept_id: seconds}


# ─── ExpoTicket：传菜督导视图票据 ───


class ExpoTicket(BaseModel):
    """ExpoStation 传菜督导视图中一张桌的进度票据"""

    plan_id: str
    order_id: str
    table_no: str
    store_id: str
    tenant_id: str
    status: str  # coordinating / all_ready / served
    total_depts: int
    ready_depts: int
    target_completion: str  # ISO 8601
    dept_progress: list[dict]  # [{"dept_id":..,"dept_name":..,"ready":bool}]


# ─── WebSocket 推送（可被测试 mock 替换）───


async def push_table_ready_ws(
    store_id: str,
    tenant_id: str,
    event: str,
    data: dict,
) -> None:
    """推送 WebSocket 事件到 ExpoStation。

    实际项目中通过 Redis Pub/Sub 或 FastAPI WebSocket 广播实现。
    此处提供接口定义，供测试 mock 和生产实现替换。
    """
    log = logger.bind(store_id=store_id, tenant_id=tenant_id, event=event)
    log.info("table_fire.ws_push", table_no=data.get("table_no"), event=event)
    # 通过 Redis Pub/Sub 向 mac-station 广播，mac-station 转发 WebSocket 至 ExpoStation
    try:
        r = await UniversalPublisher.get_redis()
        payload = json.dumps(
            {"event": event, "store_id": store_id, **data},
            ensure_ascii=False,
            default=str,
        )
        await r.publish(f"table_fire:{tenant_id}:{store_id}", payload)
    except (OSError, RuntimeError) as exc:
        log.warning("table_fire.ws_push_failed", error=str(exc))


# ─── TableFireCoordinator ───


class TableFireCoordinator:
    """同桌同出协调引擎

    负责：
    - create_plan：计算各档口延迟开始时间，持久化到 DB
    - notify_dept_ready：档口完成时更新状态，全部就绪推送信号
    - get_expo_view：传菜督导实时视图
    """

    async def create_plan(
        self,
        order_id: str,
        table_no: str,
        store_id: str,
        tenant_id: str,
        items_by_dept: dict,
        db: AsyncSession,
    ) -> Optional[TableProductionPlanInMemory]:
        """为一张桌的订单创建同出协调计划。

        Args:
            order_id: 订单ID
            table_no: 桌号
            store_id: 门店ID
            tenant_id: 租户ID（强制隔离）
            items_by_dept: {
                dept_id: {
                    "dept_name": str,
                    "estimated_seconds": int,
                    "items": [{"task_id": str, "dish_name": str, "urgent": bool}, ...]
                }
            }
            db: 数据库会话

        Returns:
            TableProductionPlanInMemory 或 None（空档口列表）
        """
        log = logger.bind(order_id=order_id, table_no=table_no, tenant_id=tenant_id)

        if not items_by_dept:
            log.info("table_fire.create_plan.empty_depts")
            return None

        # ── 1. 计算每个档口的有效预计时间（考虑催菜）──
        dept_estimates: dict[str, int] = {}
        for dept_id, dept_info in items_by_dept.items():
            base_seconds = dept_info.get("estimated_seconds", 300)
            items = dept_info.get("items", [])
            # 任意菜品催菜 → 整个档口预计时间乘以 URGENT_TIME_FACTOR
            has_urgent = any(item.get("urgent") for item in items)
            effective_seconds = int(base_seconds * URGENT_TIME_FACTOR) if has_urgent else base_seconds
            dept_estimates[dept_id] = effective_seconds

        # ── 2. 找到最慢档口（bottleneck）──
        bottleneck_seconds = max(dept_estimates.values())
        now = datetime.now(timezone.utc)
        target_completion = now + timedelta(seconds=bottleneck_seconds)

        # ── 3. 为每个较快档口计算延迟开始时间 ──
        dept_delays: dict[str, int] = {}
        dept_readiness: dict[str, bool] = {}

        for dept_id, est_seconds in dept_estimates.items():
            if est_seconds < bottleneck_seconds:
                delay = bottleneck_seconds - est_seconds - COORD_BUFFER_SECONDS
                dept_delays[dept_id] = max(delay, 0)  # 延迟不能为负
            else:
                dept_delays[dept_id] = 0
            dept_readiness[dept_id] = False

        # ── 4. 持久化到数据库 ──
        plan_id = uuid.uuid4()
        db_plan = TableProductionPlan(
            id=plan_id,
            order_id=uuid.UUID(order_id),
            table_no=table_no,
            store_id=uuid.UUID(store_id),
            tenant_id=uuid.UUID(tenant_id),
            target_completion=target_completion,
            status="coordinating",
            dept_readiness=dept_readiness,
            dept_delays=dept_delays,
        )

        try:
            db.add(db_plan)
            await db.flush()
        except Exception as exc:  # noqa: BLE001 — MLPS3-P0: DB flush异常类型多变，记录后上抛
            log.error(
                "table_fire.create_plan.db_error",
                error=str(exc),
                exc_info=True,
            )
            raise

        log.info(
            "table_fire.create_plan.done",
            plan_id=str(plan_id),
            bottleneck_seconds=bottleneck_seconds,
            dept_count=len(items_by_dept),
            delayed_depts=sum(1 for d in dept_delays.values() if d > 0),
        )

        # 返回内存计划（测试友好，避免 DB session 依赖）
        return TableProductionPlanInMemory(
            id=plan_id,
            order_id=uuid.UUID(order_id),
            table_no=table_no,
            store_id=uuid.UUID(store_id),
            tenant_id=uuid.UUID(tenant_id),
            target_completion=target_completion,
            status="coordinating",
            dept_readiness=dept_readiness,
            dept_delays=dept_delays,
        )

    async def notify_dept_ready(
        self,
        plan: TableProductionPlanInMemory,
        dept_id: str,
        db: AsyncSession,
    ) -> dict:
        """档口完成出品时调用，更新就绪状态。

        全部档口就绪时自动推送 WebSocket "table_ready" 到 ExpoStation。

        Args:
            plan: 内存中的协调计划（含 dept_readiness）
            dept_id: 完成出品的档口ID
            db: 数据库会话

        Returns:
            {"all_ready": bool, "ready_depts": int, "total_depts": int}
        """
        log = logger.bind(plan_id=str(plan.id), dept_id=dept_id)

        # ── 1. 更新内存状态 ──
        if dept_id not in plan.dept_readiness:
            log.warning("table_fire.notify_dept_ready.unknown_dept", dept_id=dept_id)
        plan.dept_readiness[dept_id] = True

        ready_count = sum(1 for v in plan.dept_readiness.values() if v)
        total_count = len(plan.dept_readiness)
        all_ready = ready_count >= total_count

        # ── 2. 持久化到 DB ──
        try:
            stmt = (
                update(TableProductionPlan)
                .where(
                    and_(
                        TableProductionPlan.id == plan.id,
                        TableProductionPlan.tenant_id == plan.tenant_id,
                    )
                )
                .values(
                    dept_readiness=plan.dept_readiness,
                    status="all_ready" if all_ready else "coordinating",
                )
            )
            await db.execute(stmt)
            await db.flush()
        except Exception as exc:  # noqa: BLE001 — MLPS3-P0: DB execute异常类型多变，记录后上抛
            log.error(
                "table_fire.notify_dept_ready.db_error",
                error=str(exc),
                exc_info=True,
            )
            raise

        log.info(
            "table_fire.notify_dept_ready",
            dept_id=dept_id,
            ready_count=ready_count,
            total_count=total_count,
            all_ready=all_ready,
        )

        # ── 3. 全部就绪 → 推送 WebSocket ──
        if all_ready:
            plan.status = "all_ready"
            try:
                await push_table_ready_ws(
                    store_id=str(plan.store_id),
                    tenant_id=str(plan.tenant_id),
                    event="table_ready",
                    data={
                        "plan_id": str(plan.id),
                        "order_id": str(plan.order_id),
                        "table_no": plan.table_no,
                        "store_id": str(plan.store_id),
                        "tenant_id": str(plan.tenant_id),
                        "ready_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception as exc:  # noqa: BLE001 — MLPS3-P0: WS推送失败不阻断业务，最外层兜底
                # WebSocket 推送失败不阻断业务流程，记录日志
                log.error(
                    "table_fire.notify_dept_ready.ws_push_failed",
                    error=str(exc),
                    exc_info=True,
                )

        return {
            "all_ready": all_ready,
            "ready_depts": ready_count,
            "total_depts": total_count,
        }

    async def get_expo_view(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[dict]:
        """获取传菜督导视图：该门店所有活跃桌的出品进度。

        只返回 coordinating 和 all_ready 状态的计划（已 served 的过滤掉）。

        Args:
            store_id: 门店ID
            tenant_id: 租户ID（显式隔离）
            db: 数据库会话

        Returns:
            [ExpoTicket 的 dict 形式, ...]
        """
        log = logger.bind(store_id=store_id, tenant_id=tenant_id)

        try:
            stmt = (
                select(TableProductionPlan)
                .where(
                    and_(
                        TableProductionPlan.store_id == uuid.UUID(store_id),
                        TableProductionPlan.tenant_id == uuid.UUID(tenant_id),
                        TableProductionPlan.status.in_(["coordinating", "all_ready"]),
                        TableProductionPlan.is_deleted == False,  # noqa: E712
                    )
                )
                .order_by(TableProductionPlan.target_completion.asc())
            )

            result = await db.execute(stmt)
            plans = result.scalars().all()
        except (ValueError, AttributeError) as exc:
            log.error(
                "table_fire.get_expo_view.query_failed",
                error=str(exc),
                exc_info=True,
            )
            raise

        tickets = []
        for plan in plans:
            readiness = plan.dept_readiness or {}
            total = len(readiness)
            ready = sum(1 for v in readiness.values() if v)

            dept_progress = [{"dept_id": dept_id, "ready": is_ready} for dept_id, is_ready in readiness.items()]

            tickets.append(
                {
                    "plan_id": str(plan.id),
                    "order_id": str(plan.order_id),
                    "table_no": plan.table_no,
                    "store_id": str(plan.store_id),
                    "tenant_id": str(plan.tenant_id),
                    "status": plan.status,
                    "total_depts": total,
                    "ready_depts": ready,
                    "target_completion": (plan.target_completion.isoformat() if plan.target_completion else None),
                    "dept_progress": dept_progress,
                }
            )

        log.info("table_fire.get_expo_view.done", ticket_count=len(tickets))
        return tickets

    async def mark_served(
        self,
        plan_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> bool:
        """确认传菜完成，将计划状态更新为 served。

        Args:
            plan_id: 计划ID
            tenant_id: 租户ID（显式隔离，防止跨租户操作）
            db: 数据库会话

        Returns:
            True 表示更新成功，False 表示计划不存在
        """
        log = logger.bind(plan_id=plan_id, tenant_id=tenant_id)

        try:
            stmt = (
                update(TableProductionPlan)
                .where(
                    and_(
                        TableProductionPlan.id == uuid.UUID(plan_id),
                        TableProductionPlan.tenant_id == uuid.UUID(tenant_id),
                        TableProductionPlan.is_deleted == False,  # noqa: E712
                    )
                )
                .values(status="served")
            )
            result = await db.execute(stmt)
            await db.flush()
        except (ValueError, AttributeError) as exc:
            log.error(
                "table_fire.mark_served.error",
                error=str(exc),
                exc_info=True,
            )
            raise

        updated = result.rowcount > 0
        if updated:
            log.info("table_fire.mark_served.done", plan_id=plan_id)
        else:
            log.warning("table_fire.mark_served.not_found", plan_id=plan_id)

        return updated
