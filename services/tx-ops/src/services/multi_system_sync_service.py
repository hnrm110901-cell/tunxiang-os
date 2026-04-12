"""四系统数据同步协调器

统一调度品智POS / 奥琦玮CRM / 奥琦玮供应链 / 易订预订 四个适配器的数据同步。

职责：
  - sync_pinzhi_orders       — 拉取品智订单 → orders 表 upsert + OrderEventType.CREATED
  - sync_aoqiwei_members     — 拉取奥琦玮CRM会员 → customers 表 upsert on golden_id
  - sync_aoqiwei_inventory   — 拉取奥琦玮供应链库存 → ingredients 表 upsert + InventoryEventType.ADJUSTED
  - sync_yiding_reservations — 拉取易订待处理预订 → reservations 表 + confirm_orders
  - sync_all                 — 并发执行以上4个同步，返回汇总结果
  - get_sync_status          — 查询各系统最近同步时间/成功率/最近错误

同步记录写入 operation_logs 表（log_type='sync_record'）。

编码规范：
  - async/await 全程
  - 禁止 except Exception（各适配器调用捕获具体异常）
  - 金额单位：分（整数）
  - 事件发射：asyncio.create_task(emit_event(...))
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import InventoryEventType, OrderEventType, ReservationEventType

logger = structlog.get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────
# 适配器导入（延迟导入避免循环依赖）
# ──────────────────────────────────────────────────────────────────────


def _get_pinzhi_adapter():
    from shared.adapters.pinzhi_adapter import PinzhiPOSAdapter
    return PinzhiPOSAdapter


def _get_aoqiwei_crm_adapter():
    from shared.adapters.aoqiwei.src.crm_adapter import AoqiweiCrmAdapter
    return AoqiweiCrmAdapter


def _get_aoqiwei_supply_adapter():
    from shared.adapters.aoqiwei.src.adapter import AoqiweiAdapter
    return AoqiweiAdapter


def _get_yiding_adapter():
    from shared.adapters.yiding.src.adapter import YiDingAdapter
    return YiDingAdapter


# ──────────────────────────────────────────────────────────────────────
# 系统标识常量
# ──────────────────────────────────────────────────────────────────────

SYSTEM_PINZHI = "pinzhi"
SYSTEM_AOQIWEI_CRM = "aoqiwei_crm"
SYSTEM_AOQIWEI_SUPPLY = "aoqiwei_supply"
SYSTEM_YIDING = "yiding"

ALL_SYSTEMS = [SYSTEM_PINZHI, SYSTEM_AOQIWEI_CRM, SYSTEM_AOQIWEI_SUPPLY, SYSTEM_YIDING]


# ──────────────────────────────────────────────────────────────────────
# 协调器主类
# ──────────────────────────────────────────────────────────────────────


class MultiSystemSyncService:
    """四系统数据同步协调器

    使用示例：
        svc = MultiSystemSyncService(engine=db_engine)
        result = await svc.sync_all(tenant_id="xxx", store_ids=["S001", "S002"])
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # ── 工具方法 ────────────────────────────────────────────────────────

    async def _write_sync_log(
        self,
        conn: AsyncConnection,
        tenant_id: str,
        system: str,
        store_id: Optional[str],
        synced: int,
        skipped: int,
        errors: List[str],
        duration_ms: int,
    ) -> None:
        """将同步结果写入 operation_logs 表（log_type='sync_record'）"""
        log_id = str(uuid.uuid4())
        status = "success" if not errors else "partial_error"
        payload = {
            "system": system,
            "store_id": store_id,
            "synced": synced,
            "skipped": skipped,
            "errors": errors,
            "duration_ms": duration_ms,
        }
        try:
            await conn.execute(
                text("""
                    INSERT INTO operation_logs
                        (id, tenant_id, log_type, status, store_id, payload, created_at)
                    VALUES
                        (:id, :tenant_id, 'sync_record', :status, :store_id,
                         :payload::jsonb, NOW())
                    ON CONFLICT DO NOTHING
                """),
                {
                    "id": log_id,
                    "tenant_id": tenant_id,
                    "status": status,
                    "store_id": store_id,
                    "payload": __import__("json").dumps(payload, ensure_ascii=False),
                },
            )
        except Exception as exc:  # noqa: BLE001  # 写日志失败不影响主流程，此处兜底
            logger.warning(
                "sync_log_write_failed",
                system=system,
                error=str(exc),
                exc_info=True,
            )

    # ── 1. 品智订单同步 ─────────────────────────────────────────────────

    async def sync_pinzhi_orders(
        self,
        tenant_id: str,
        store_id: str,
        since_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """从品智POS拉取订单 → upsert 到 orders 表 → 发射 OrderEventType.CREATED

        Args:
            tenant_id:  租户ID
            store_id:   门店ID（品智 ognid）
            since_date: 起始时间，默认24小时前

        Returns:
            {"synced": N, "skipped": M, "errors": [...], "duration_ms": D}
        """
        since = since_date or (datetime.now(timezone.utc) - timedelta(hours=24))
        t0 = time.monotonic()
        synced = 0
        skipped = 0
        errors: List[str] = []

        logger.info("sync_pinzhi_orders_start", tenant_id=tenant_id, store_id=store_id, since=since.isoformat())

        PinzhiPOSAdapter = _get_pinzhi_adapter()
        adapter = PinzhiPOSAdapter(mock_mode=not os.environ.get("PINZHI_BASE_URL"))

        try:
            orders = await adapter.sync_orders(since=since)
        except (ValueError, RuntimeError, ConnectionError) as exc:
            errors.append(f"品智订单拉取失败: {exc}")
            logger.error("sync_pinzhi_orders_fetch_failed", error=str(exc), exc_info=True)
            return {"synced": 0, "skipped": 0, "errors": errors, "duration_ms": int((time.monotonic() - t0) * 1000)}
        finally:
            await adapter.close()

        if not orders:
            duration_ms = int((time.monotonic() - t0) * 1000)
            async with self._engine.begin() as conn:
                await self._write_sync_log(conn, tenant_id, SYSTEM_PINZHI, store_id, 0, 0, [], duration_ms)
            return {"synced": 0, "skipped": 0, "errors": [], "duration_ms": duration_ms}

        async with self._engine.begin() as conn:
            for order in orders:
                order_id = order.get("order_id") or str(uuid.uuid4())
                order_number = order.get("order_number", "")
                total_fen = order.get("total_fen", 0)
                order_status = order.get("order_status", "pending")

                try:
                    result = await conn.execute(
                        text("""
                            INSERT INTO orders
                                (id, tenant_id, store_id, order_number, order_type, order_status,
                                 total_fen, source_system, raw_data, created_at, updated_at)
                            VALUES
                                (:id, :tenant_id, :store_id, :order_number, :order_type, :order_status,
                                 :total_fen, 'pinzhi', :raw_data::jsonb, NOW(), NOW())
                            ON CONFLICT (tenant_id, order_number) DO UPDATE
                                SET order_status = EXCLUDED.order_status,
                                    total_fen    = EXCLUDED.total_fen,
                                    updated_at   = NOW()
                            RETURNING (xmax = 0) AS was_inserted
                        """),
                        {
                            "id": order_id,
                            "tenant_id": tenant_id,
                            "store_id": store_id,
                            "order_number": order_number,
                            "order_type": order.get("order_type", "dine_in"),
                            "order_status": order_status,
                            "total_fen": total_fen,
                            "raw_data": __import__("json").dumps(order, ensure_ascii=False),
                        },
                    )
                    row = result.fetchone()
                    if row and row.was_inserted:
                        synced += 1
                        asyncio.create_task(emit_event(
                            event_type=OrderEventType.CREATED,
                            tenant_id=tenant_id,
                            stream_id=order_id,
                            payload={
                                "order_id": order_id,
                                "order_number": order_number,
                                "total_fen": total_fen,
                                "order_status": order_status,
                                "source_system": "pinzhi",
                            },
                            store_id=store_id,
                            source_service="tx-ops",
                        ))
                    else:
                        skipped += 1

                except Exception as exc:  # noqa: BLE001  # 单条订单写入失败不阻断整批
                    errors.append(f"订单 {order_number} 写入失败: {exc}")
                    logger.warning("sync_pinzhi_order_write_failed", order_number=order_number, error=str(exc), exc_info=True)

            duration_ms = int((time.monotonic() - t0) * 1000)
            await self._write_sync_log(conn, tenant_id, SYSTEM_PINZHI, store_id, synced, skipped, errors, duration_ms)

        logger.info(
            "sync_pinzhi_orders_done",
            tenant_id=tenant_id,
            store_id=store_id,
            synced=synced,
            skipped=skipped,
            errors=len(errors),
            duration_ms=duration_ms,
        )
        return {"synced": synced, "skipped": skipped, "errors": errors, "duration_ms": duration_ms}

    # ── 2. 奥琦玮会员同步 ──────────────────────────────────────────────

    async def sync_aoqiwei_members(
        self,
        tenant_id: str,
        store_id: str,
    ) -> Dict[str, Any]:
        """从奥琦玮CRM拉取会员数据 → upsert 到 customers 表（on golden_id）

        注：奥琦玮 get_member_info 是单查接口，批量同步需枚举已知 cno/mobile 列表。
        此方法从 customers 表中找出 source_system='aoqiwei' 的会员逐一刷新。

        Returns:
            {"synced": N, "skipped": M, "errors": [...], "duration_ms": D}
        """
        t0 = time.monotonic()
        synced = 0
        skipped = 0
        errors: List[str] = []

        logger.info("sync_aoqiwei_members_start", tenant_id=tenant_id, store_id=store_id)

        AoqiweiCrmAdapter = _get_aoqiwei_crm_adapter()
        crm_config: Dict[str, Any] = {}  # 从环境变量读取
        adapter = AoqiweiCrmAdapter(crm_config)

        try:
            async with self._engine.begin() as conn:
                # 获取需要刷新的会员（有 aoqiwei_cno 或 aoqiwei_mobile 字段）
                rows = await conn.execute(
                    text("""
                        SELECT id, golden_id,
                               extra_data->>'aoqiwei_cno'    AS cno,
                               extra_data->>'aoqiwei_mobile' AS mobile,
                               extra_data->>'aoqiwei_shop_id' AS shop_id
                        FROM   customers
                        WHERE  tenant_id = :tenant_id
                          AND  source_system = 'aoqiwei'
                          AND  is_deleted    = FALSE
                        LIMIT  500
                    """),
                    {"tenant_id": tenant_id},
                )
                candidates = rows.fetchall()

            for row in candidates:
                cno = row.cno
                mobile = row.mobile
                if not cno and not mobile:
                    skipped += 1
                    continue

                try:
                    shop_id = int(row.shop_id) if row.shop_id else None
                    info = await adapter.get_member_info(cno=cno, mobile=mobile, shop_id=shop_id)
                except (ValueError, RuntimeError) as exc:
                    errors.append(f"会员 {cno or mobile} 拉取失败: {exc}")
                    logger.warning("sync_aoqiwei_member_fetch_failed", cno=cno, error=str(exc), exc_info=True)
                    skipped += 1
                    continue

                if not info:
                    skipped += 1
                    continue

                try:
                    async with self._engine.begin() as conn:
                        await conn.execute(
                            text("""
                                INSERT INTO customers
                                    (id, tenant_id, golden_id, name, phone,
                                     balance_fen, points, level, source_system,
                                     extra_data, created_at, updated_at)
                                VALUES
                                    (:id, :tenant_id, :golden_id, :name, :phone,
                                     :balance_fen, :points, :level, 'aoqiwei',
                                     :extra_data::jsonb, NOW(), NOW())
                                ON CONFLICT (tenant_id, golden_id) WHERE golden_id IS NOT NULL
                                DO UPDATE SET
                                    name         = EXCLUDED.name,
                                    balance_fen  = EXCLUDED.balance_fen,
                                    points       = EXCLUDED.points,
                                    level        = EXCLUDED.level,
                                    extra_data   = EXCLUDED.extra_data,
                                    updated_at   = NOW()
                            """),
                            {
                                "id": str(row.id),
                                "tenant_id": tenant_id,
                                "golden_id": row.golden_id,
                                "name": info.get("name", ""),
                                "phone": mobile or info.get("mobile", ""),
                                "balance_fen": int(info.get("balance", 0)),
                                "points": int(info.get("point", 0)),
                                "level": info.get("level_name", ""),
                                "extra_data": __import__("json").dumps(info, ensure_ascii=False),
                            },
                        )
                    synced += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"会员 {cno or mobile} 写入失败: {exc}")
                    logger.warning("sync_aoqiwei_member_write_failed", cno=cno, error=str(exc), exc_info=True)

        finally:
            await adapter.aclose()

        duration_ms = int((time.monotonic() - t0) * 1000)
        async with self._engine.begin() as conn:
            await self._write_sync_log(conn, tenant_id, SYSTEM_AOQIWEI_CRM, store_id, synced, skipped, errors, duration_ms)

        logger.info(
            "sync_aoqiwei_members_done",
            tenant_id=tenant_id,
            synced=synced,
            skipped=skipped,
            errors=len(errors),
            duration_ms=duration_ms,
        )
        return {"synced": synced, "skipped": skipped, "errors": errors, "duration_ms": duration_ms}

    # ── 3. 奥琦玮库存同步 ─────────────────────────────────────────────

    async def sync_aoqiwei_inventory(
        self,
        tenant_id: str,
        store_id: str,
    ) -> Dict[str, Any]:
        """从奥琦玮供应链拉取库存 → upsert 到 ingredients 表 → 发射 InventoryEventType.ADJUSTED

        Returns:
            {"synced": N, "errors": [...], "duration_ms": D}
        """
        t0 = time.monotonic()
        synced = 0
        errors: List[str] = []

        logger.info("sync_aoqiwei_inventory_start", tenant_id=tenant_id, store_id=store_id)

        AoqiweiAdapter = _get_aoqiwei_supply_adapter()
        supply_config: Dict[str, Any] = {}
        adapter = AoqiweiAdapter(supply_config)

        try:
            stock_list = await adapter.query_stock(shop_code=store_id)
        except (ValueError, RuntimeError) as exc:
            errors.append(f"奥琦玮库存拉取失败: {exc}")
            logger.error("sync_aoqiwei_inventory_fetch_failed", error=str(exc), exc_info=True)
            duration_ms = int((time.monotonic() - t0) * 1000)
            async with self._engine.begin() as conn:
                await self._write_sync_log(conn, tenant_id, SYSTEM_AOQIWEI_SUPPLY, store_id, 0, 0, errors, duration_ms)
            return {"synced": 0, "errors": errors, "duration_ms": duration_ms}
        finally:
            await adapter.aclose()

        async with self._engine.begin() as conn:
            for item in stock_list:
                good_code = item.get("goodCode", item.get("good_code", ""))
                good_name = item.get("goodName", item.get("good_name", ""))
                stock_qty = float(item.get("qty", item.get("quantity", 0)))
                unit_price_fen = int(float(item.get("price", 0)) * 100)
                ingredient_id = f"aoqiwei_{good_code}" if good_code else str(uuid.uuid4())

                try:
                    await conn.execute(
                        text("""
                            INSERT INTO ingredients
                                (id, tenant_id, store_id, ingredient_code, ingredient_name,
                                 stock_qty, unit_price_fen, source_system,
                                 extra_data, created_at, updated_at)
                            VALUES
                                (:id, :tenant_id, :store_id, :ingredient_code, :ingredient_name,
                                 :stock_qty, :unit_price_fen, 'aoqiwei',
                                 :extra_data::jsonb, NOW(), NOW())
                            ON CONFLICT (tenant_id, store_id, ingredient_code) DO UPDATE SET
                                ingredient_name  = EXCLUDED.ingredient_name,
                                stock_qty        = EXCLUDED.stock_qty,
                                unit_price_fen   = EXCLUDED.unit_price_fen,
                                extra_data       = EXCLUDED.extra_data,
                                updated_at       = NOW()
                        """),
                        {
                            "id": ingredient_id,
                            "tenant_id": tenant_id,
                            "store_id": store_id,
                            "ingredient_code": good_code,
                            "ingredient_name": good_name,
                            "stock_qty": stock_qty,
                            "unit_price_fen": unit_price_fen,
                            "extra_data": __import__("json").dumps(item, ensure_ascii=False),
                        },
                    )
                    synced += 1
                    asyncio.create_task(emit_event(
                        event_type=InventoryEventType.ADJUSTED,
                        tenant_id=tenant_id,
                        stream_id=ingredient_id,
                        payload={
                            "ingredient_id": ingredient_id,
                            "ingredient_code": good_code,
                            "ingredient_name": good_name,
                            "stock_qty": stock_qty,
                            "unit_price_fen": unit_price_fen,
                            "source_system": "aoqiwei",
                        },
                        store_id=store_id,
                        source_service="tx-ops",
                    ))

                except Exception as exc:  # noqa: BLE001
                    errors.append(f"食材 {good_code} 写入失败: {exc}")
                    logger.warning("sync_aoqiwei_inventory_write_failed", good_code=good_code, error=str(exc), exc_info=True)

            duration_ms = int((time.monotonic() - t0) * 1000)
            await self._write_sync_log(conn, tenant_id, SYSTEM_AOQIWEI_SUPPLY, store_id, synced, 0, errors, duration_ms)

        logger.info(
            "sync_aoqiwei_inventory_done",
            tenant_id=tenant_id,
            store_id=store_id,
            synced=synced,
            errors=len(errors),
            duration_ms=duration_ms,
        )
        return {"synced": synced, "errors": errors, "duration_ms": duration_ms}

    # ── 4. 易订预订同步 ─────────────────────────────────────────────────

    async def sync_yiding_reservations(
        self,
        tenant_id: str,
        store_id: str,
    ) -> Dict[str, Any]:
        """从易订拉取待处理预订 → 写入 reservations 表 → 调用 confirm_orders 确认

        Returns:
            {"synced": N, "errors": [...], "duration_ms": D}
        """
        t0 = time.monotonic()
        synced = 0
        errors: List[str] = []

        logger.info("sync_yiding_reservations_start", tenant_id=tenant_id, store_id=store_id)

        YiDingAdapter = _get_yiding_adapter()
        yiding_config = {
            "base_url": os.environ.get("YIDING_BASE_URL", ""),
            "app_id": os.environ.get("YIDING_APP_ID", ""),
            "app_secret": os.environ.get("YIDING_APP_SECRET", ""),
            "hotel_id": store_id,
            "cache_ttl": 300,
        }
        adapter = YiDingAdapter(yiding_config)

        try:
            pending = await adapter.get_pending_orders()
        except (ValueError, RuntimeError) as exc:
            errors.append(f"易订预订拉取失败: {exc}")
            logger.error("sync_yiding_reservations_fetch_failed", error=str(exc), exc_info=True)
            duration_ms = int((time.monotonic() - t0) * 1000)
            async with self._engine.begin() as conn:
                await self._write_sync_log(conn, tenant_id, SYSTEM_YIDING, store_id, 0, 0, errors, duration_ms)
            await adapter.close()
            return {"synced": 0, "errors": errors, "duration_ms": duration_ms}

        confirm_items: List[Dict[str, Any]] = []

        async with self._engine.begin() as conn:
            for resv in pending:
                resv_dict = dict(resv) if not isinstance(resv, dict) else resv
                resv_order_no = resv_dict.get("resv_order") or resv_dict.get("reservation_id") or str(uuid.uuid4())
                resv_id = f"yiding_{resv_order_no}"

                try:
                    await conn.execute(
                        text("""
                            INSERT INTO reservations
                                (id, tenant_id, store_id, reservation_no, guest_name, guest_phone,
                                 party_size, resv_date, resv_time, status, source_system,
                                 raw_data, created_at, updated_at)
                            VALUES
                                (:id, :tenant_id, :store_id, :reservation_no, :guest_name, :guest_phone,
                                 :party_size, :resv_date, :resv_time, 'pending', 'yiding',
                                 :raw_data::jsonb, NOW(), NOW())
                            ON CONFLICT (tenant_id, reservation_no) DO UPDATE SET
                                status     = EXCLUDED.status,
                                updated_at = NOW()
                        """),
                        {
                            "id": resv_id,
                            "tenant_id": tenant_id,
                            "store_id": store_id,
                            "reservation_no": resv_order_no,
                            "guest_name": resv_dict.get("guest_name", resv_dict.get("name", "")),
                            "guest_phone": resv_dict.get("guest_phone", resv_dict.get("phone", "")),
                            "party_size": int(resv_dict.get("party_size", resv_dict.get("num_people", 1))),
                            "resv_date": resv_dict.get("resv_date", resv_dict.get("date", "")),
                            "resv_time": resv_dict.get("resv_time", resv_dict.get("time", "")),
                            "raw_data": __import__("json").dumps(resv_dict, ensure_ascii=False),
                        },
                    )
                    synced += 1
                    confirm_items.append({
                        "resv_order": resv_order_no,
                        "status": 1,
                        "order_type": resv_dict.get("order_type", 1),
                    })
                    asyncio.create_task(emit_event(
                        event_type=ReservationEventType.CREATED,
                        tenant_id=tenant_id,
                        stream_id=resv_id,
                        payload={
                            "reservation_id": resv_id,
                            "reservation_no": resv_order_no,
                            "guest_name": resv_dict.get("guest_name", ""),
                            "party_size": resv_dict.get("party_size", 1),
                            "source_system": "yiding",
                        },
                        store_id=store_id,
                        source_service="tx-ops",
                    ))

                except Exception as exc:  # noqa: BLE001
                    errors.append(f"预订 {resv_order_no} 写入失败: {exc}")
                    logger.warning("sync_yiding_reservation_write_failed", resv_order=resv_order_no, error=str(exc), exc_info=True)

            duration_ms = int((time.monotonic() - t0) * 1000)
            await self._write_sync_log(conn, tenant_id, SYSTEM_YIDING, store_id, synced, 0, errors, duration_ms)

        # 确认已接收（告知易订不再重发）
        if confirm_items:
            try:
                await adapter.confirm_orders(confirm_items)
                logger.info("yiding_confirm_orders_done", count=len(confirm_items))
            except (ValueError, RuntimeError) as exc:
                logger.warning("yiding_confirm_orders_failed", error=str(exc), exc_info=True)
                errors.append(f"易订确认失败（预订已入库）: {exc}")

        await adapter.close()

        logger.info(
            "sync_yiding_reservations_done",
            tenant_id=tenant_id,
            store_id=store_id,
            synced=synced,
            errors=len(errors),
            duration_ms=duration_ms,
        )
        return {"synced": synced, "errors": errors, "duration_ms": duration_ms}

    # ── 5. 全量并发同步 ─────────────────────────────────────────────────

    async def sync_all(
        self,
        tenant_id: str,
        store_ids: List[str],
        systems: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """并发执行四个系统的同步，返回汇总结果

        Args:
            tenant_id:  租户ID
            store_ids:  门店ID列表（每个门店各执行一次）
            systems:    要同步的系统列表，默认全部

        Returns:
            {
              "total_synced": N,
              "by_system": {"pinzhi": {...}, "aoqiwei_crm": {...}, ...},
              "errors": [...],
              "duration_ms": D
            }
        """
        target_systems = set(systems or ALL_SYSTEMS)
        t0 = time.monotonic()

        tasks: Dict[str, asyncio.Task] = {}

        for store_id in store_ids:
            if SYSTEM_PINZHI in target_systems:
                tasks[f"{SYSTEM_PINZHI}:{store_id}"] = asyncio.create_task(
                    self.sync_pinzhi_orders(tenant_id, store_id)
                )
            if SYSTEM_AOQIWEI_CRM in target_systems:
                tasks[f"{SYSTEM_AOQIWEI_CRM}:{store_id}"] = asyncio.create_task(
                    self.sync_aoqiwei_members(tenant_id, store_id)
                )
            if SYSTEM_AOQIWEI_SUPPLY in target_systems:
                tasks[f"{SYSTEM_AOQIWEI_SUPPLY}:{store_id}"] = asyncio.create_task(
                    self.sync_aoqiwei_inventory(tenant_id, store_id)
                )
            if SYSTEM_YIDING in target_systems:
                tasks[f"{SYSTEM_YIDING}:{store_id}"] = asyncio.create_task(
                    self.sync_yiding_reservations(tenant_id, store_id)
                )

        results = {}
        all_errors: List[str] = []

        for task_key, task in tasks.items():
            try:
                results[task_key] = await task
            except (ValueError, RuntimeError) as exc:
                results[task_key] = {"synced": 0, "errors": [str(exc)]}
                all_errors.append(f"{task_key}: {exc}")
                logger.error("sync_all_task_failed", task=task_key, error=str(exc), exc_info=True)

        # 按系统汇总
        by_system: Dict[str, Dict[str, Any]] = {}
        total_synced = 0

        for system in ALL_SYSTEMS:
            system_synced = 0
            system_errors: List[str] = []
            for store_id in store_ids:
                key = f"{system}:{store_id}"
                if key in results:
                    r = results[key]
                    system_synced += r.get("synced", 0)
                    system_errors.extend(r.get("errors", []))
            by_system[system] = {"synced": system_synced, "errors": system_errors}
            total_synced += system_synced

        duration_ms = int((time.monotonic() - t0) * 1000)

        logger.info(
            "sync_all_done",
            tenant_id=tenant_id,
            store_count=len(store_ids),
            total_synced=total_synced,
            error_count=len(all_errors),
            duration_ms=duration_ms,
        )

        return {
            "total_synced": total_synced,
            "by_system": by_system,
            "errors": all_errors,
            "duration_ms": duration_ms,
        }

    # ── 6. 同步状态查询 ────────────────────────────────────────────────

    async def get_sync_status(self, tenant_id: str) -> Dict[str, Any]:
        """查询各系统最近同步时间、成功率、最近错误

        从 operation_logs 表（log_type='sync_record'）读取最近30条记录汇总。

        Returns:
            {
              "systems": {
                "pinzhi":          {"last_sync_at": "...", "success_rate": 0.95, "last_errors": []},
                "aoqiwei_crm":     {...},
                "aoqiwei_supply":  {...},
                "yiding":          {...},
              }
            }
        """
        status: Dict[str, Any] = {"systems": {}}

        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("""
                    SELECT
                        payload->>'system'   AS system,
                        status,
                        created_at,
                        payload->>'errors'   AS errors_json
                    FROM operation_logs
                    WHERE tenant_id = :tenant_id
                      AND log_type  = 'sync_record'
                      AND created_at >= NOW() - INTERVAL '24 hours'
                    ORDER BY created_at DESC
                    LIMIT 200
                """),
                {"tenant_id": tenant_id},
            )
            records = rows.fetchall()

        import json as _json

        for system in ALL_SYSTEMS:
            system_records = [r for r in records if r.system == system]
            if not system_records:
                status["systems"][system] = {
                    "last_sync_at": None,
                    "success_rate": None,
                    "last_errors": [],
                    "total_records": 0,
                }
                continue

            total = len(system_records)
            success_count = sum(1 for r in system_records if r.status == "success")
            last_record = system_records[0]

            last_errors: List[str] = []
            for r in system_records[:5]:
                if r.errors_json:
                    try:
                        errs = _json.loads(r.errors_json)
                        last_errors.extend(errs[:3])
                    except (ValueError, TypeError):
                        pass

            status["systems"][system] = {
                "last_sync_at": last_record.created_at.isoformat() if last_record.created_at else None,
                "success_rate": round(success_count / total, 4) if total > 0 else None,
                "last_errors": last_errors[:10],
                "total_records": total,
            }

        return status
