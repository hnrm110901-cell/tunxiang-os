"""品智POS数据同步服务

功能：
1. 按日期范围从品智API拉取订单数据
2. 转换为标准Order模型写入数据库（UPSERT语义）
3. 支持增量同步（只拉新数据）和全量回填
4. 多门店并行拉取

凭证优先级（高 → 低）：
  1. store.config["pinzhi_base_url"] / ["pinzhi_token"]  ← 门店级覆盖
  2. 环境变量 PINZHI_BASE_URL / PINZHI_TOKEN             ← 全局兜底
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ....shared.core.exceptions import PinzhiAPIError, POSAdapterError
from .pos_mapper import pinzhi_order_to_db, pinzhi_order_items_to_db
from .pos_sync_schemas import StoreSyncSummary, SyncResult, SyncStatusResponse

logger = structlog.get_logger(__name__)

# 品智适配器延迟加载（shared/adapters/pinzhi/）
_ADAPTER_CLS = None


def _get_pinzhi_adapter_class():
    """延迟加载品智适配器，避免启动时依赖问题"""
    global _ADAPTER_CLS
    if _ADAPTER_CLS is not None:
        return _ADAPTER_CLS

    import importlib.util
    import sys
    import types

    pkg_key = "_txos_pinzhi_pkg"
    if pkg_key not in sys.modules:
        adapter_src = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..", "..", "..", "..", "..", "..",  # tunxiang-os/
                "shared", "adapters", "pinzhi", "src",
            )
        )
        if not os.path.isdir(adapter_src):
            raise FileNotFoundError(
                f"品智适配器源码目录未找到: {adapter_src}"
            )

        pkg = types.ModuleType(pkg_key)
        pkg.__path__ = [adapter_src]
        pkg.__package__ = pkg_key
        pkg.__file__ = os.path.join(adapter_src, "__init__.py")
        sys.modules[pkg_key] = pkg

        for mod_name in ("signature", "adapter"):
            mod_key = f"{pkg_key}.{mod_name}"
            spec = importlib.util.spec_from_file_location(
                mod_key, os.path.join(adapter_src, f"{mod_name}.py")
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                mod.__package__ = pkg_key
                sys.modules[mod_key] = mod
                spec.loader.exec_module(mod)

    _ADAPTER_CLS = sys.modules[f"{pkg_key}.adapter"].PinzhiAdapter
    return _ADAPTER_CLS


# ── 商户配置映射 ─────────────────────────────────────────────────────────────

MERCHANT_ENV_PREFIX: dict[str, str] = {
    "czyz": "CZYZ",   # 尝在一起
    "zqx": "ZQX",     # 最黔线
    "sgc": "SGC",     # 尚宫厨
}


def _get_merchant_env(merchant_code: str, key: str, default: str = "") -> str:
    """读取商户级环境变量，回退到全局品智变量

    例: CZYZ_PINZHI_BASE_URL → PINZHI_BASE_URL
    """
    prefix = MERCHANT_ENV_PREFIX.get(merchant_code, merchant_code.upper())
    val = os.getenv(f"{prefix}_PINZHI_{key}", "")
    if val:
        return val
    return os.getenv(f"PINZHI_{key}", default)


# ── 同步服务 ─────────────────────────────────────────────────────────────────


class POSSyncService:
    """品智POS数据同步核心服务"""

    async def sync_daily_orders(
        self,
        merchant_code: str,
        store_id: str,
        sync_date: date,
        tenant_id: UUID,
        db: AsyncSession,
    ) -> StoreSyncSummary:
        """拉取指定门店指定日期的订单并写入数据库

        Args:
            merchant_code: 商户编码(czyz/zqx/sgc)
            store_id: 门店ID（UUID字符串）
            sync_date: 同步日期
            tenant_id: 租户ID
            db: 数据库会话

        Returns:
            StoreSyncSummary 单门店同步结果
        """
        store_name = await self._get_store_name(store_id, db)

        # 1) 获取凭证
        base_url, token, ognid = await self._resolve_credentials(
            merchant_code, store_id, db
        )
        if not base_url or not token:
            return StoreSyncSummary(
                store_id=store_id,
                store_name=store_name,
                error="品智凭证未配置（PINZHI_BASE_URL/TOKEN 或 store.config）",
            )

        # 2) 创建适配器
        PinzhiAdapter = _get_pinzhi_adapter_class()
        adapter = PinzhiAdapter({
            "base_url": base_url,
            "token": token,
            "timeout": int(os.getenv("PINZHI_TIMEOUT", "30")),
            "retry_times": int(os.getenv("PINZHI_RETRY_TIMES", "3")),
        })

        # 3) 分页拉取订单
        date_str = sync_date.isoformat()
        orders_synced = 0
        orders_skipped = 0
        revenue_fen = 0

        try:
            page = 1
            while True:
                raw_orders = await adapter.query_orders(
                    ognid=ognid,
                    begin_date=date_str,
                    end_date=date_str,
                    page_index=page,
                    page_size=100,
                )
                if not raw_orders:
                    break

                for raw in raw_orders:
                    order_dict = pinzhi_order_to_db(raw, tenant_id, UUID(store_id))
                    was_new = await self._upsert_order(order_dict, db)

                    if was_new:
                        orders_synced += 1
                    else:
                        orders_skipped += 1

                    revenue_fen += order_dict["final_amount_fen"]

                    # 写入订单明细
                    items = pinzhi_order_items_to_db(raw, order_dict["id"], tenant_id)
                    for item in items:
                        await self._upsert_order_item(item, db)

                if len(raw_orders) < 100:
                    break
                page += 1

            await db.flush()
            logger.info(
                "pos_sync.store_done",
                merchant=merchant_code,
                store_id=store_id,
                date=date_str,
                synced=orders_synced,
                skipped=orders_skipped,
                revenue_fen=revenue_fen,
            )

        except PinzhiAPIError as e:
            logger.error(
                "pos_sync.pinzhi_api_error",
                store_id=store_id,
                error=str(e),
            )
            return StoreSyncSummary(
                store_id=store_id,
                store_name=store_name,
                orders_synced=orders_synced,
                revenue_fen=revenue_fen,
                error=f"品智API错误: {e.message}",
            )
        except (ConnectionError, TimeoutError) as e:
            logger.error(
                "pos_sync.connection_error",
                store_id=store_id,
                error=str(e),
            )
            return StoreSyncSummary(
                store_id=store_id,
                store_name=store_name,
                orders_synced=orders_synced,
                revenue_fen=revenue_fen,
                error=f"连接错误: {e}",
            )

        return StoreSyncSummary(
            store_id=store_id,
            store_name=store_name,
            orders_synced=orders_synced,
            orders_skipped=orders_skipped,
            revenue_fen=revenue_fen,
        )

    async def backfill(
        self,
        merchant_code: str,
        start_date: date,
        end_date: date,
        tenant_id: UUID,
        db: AsyncSession,
        store_ids: list[str] | None = None,
    ) -> SyncResult:
        """回填指定日期范围的数据

        逐日、逐店同步，失败的门店不阻塞其他门店。

        Args:
            merchant_code: 商户编码
            start_date: 开始日期
            end_date: 结束日期
            tenant_id: 租户ID
            db: 数据库会话
            store_ids: 指定门店ID列表（None=全部活跃门店）

        Returns:
            SyncResult 整体同步结果
        """
        days = (end_date - start_date).days + 1
        if days > 90:
            raise POSAdapterError(
                "回填日期范围不能超过90天",
                context={"start_date": str(start_date), "end_date": str(end_date)},
            )

        # 获取门店列表
        active_store_ids = await self._get_active_store_ids(
            merchant_code, store_ids, db
        )
        if not active_store_ids:
            return SyncResult(
                success=False,
                merchant_code=merchant_code,
                sync_date=f"{start_date} ~ {end_date}",
                triggered_at=datetime.now().isoformat(),
                stores=[],
                totals={"error": "未找到活跃门店"},
            )

        all_summaries: list[StoreSyncSummary] = []
        current = start_date

        while current <= end_date:
            logger.info(
                "pos_sync.backfill_day",
                merchant=merchant_code,
                date=str(current),
                stores=len(active_store_ids),
            )
            for sid in active_store_ids:
                summary = await self.sync_daily_orders(
                    merchant_code=merchant_code,
                    store_id=sid,
                    sync_date=current,
                    tenant_id=tenant_id,
                    db=db,
                )
                all_summaries.append(summary)
            current += timedelta(days=1)

        await db.commit()

        total_synced = sum(s.orders_synced for s in all_summaries)
        total_revenue = sum(s.revenue_fen for s in all_summaries)
        errors = [s for s in all_summaries if s.error]

        return SyncResult(
            success=len(errors) == 0,
            merchant_code=merchant_code,
            sync_date=f"{start_date} ~ {end_date}",
            triggered_at=datetime.now().isoformat(),
            stores=all_summaries,
            totals={
                "days": days,
                "stores_processed": len(active_store_ids),
                "total_orders_synced": total_synced,
                "total_revenue_fen": total_revenue,
                "total_revenue_yuan": round(total_revenue / 100, 2),
                "errors": len(errors),
            },
        )

    async def sync_menu(
        self,
        merchant_code: str,
        store_id: str,
        tenant_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """同步菜品数据（从品智拉取菜单并写入dishes表）

        Args:
            merchant_code: 商户编码
            store_id: 门店ID
            tenant_id: 租户ID
            db: 数据库会话

        Returns:
            同步结果摘要
        """
        base_url, token, ognid = await self._resolve_credentials(
            merchant_code, store_id, db
        )
        if not base_url or not token:
            return {"success": False, "error": "品智凭证未配置"}

        PinzhiAdapter = _get_pinzhi_adapter_class()
        adapter = PinzhiAdapter({
            "base_url": base_url,
            "token": token,
            "timeout": int(os.getenv("PINZHI_TIMEOUT", "30")),
            "retry_times": int(os.getenv("PINZHI_RETRY_TIMES", "3")),
        })

        try:
            dishes = await adapter.query_dishes(ognid=ognid)
        except (PinzhiAPIError, ConnectionError, TimeoutError) as e:
            logger.error("pos_sync.menu_error", store_id=store_id, error=str(e))
            return {"success": False, "error": str(e), "dishes_count": 0}

        synced = 0
        for dish in (dishes or []):
            dish_name = dish.get("dishName", "")
            pinzhi_dish_id = str(dish.get("dishId", ""))
            price_fen = _safe_int_from_mapper(dish.get("dishPrice", 0))

            await db.execute(
                text("""
                    INSERT INTO dishes (id, tenant_id, store_id, name, price_fen,
                                        sales_channel_id, external_id, is_active)
                    VALUES (gen_random_uuid(), :tenant_id, :store_id, :name, :price_fen,
                            'pinzhi', :external_id, true)
                    ON CONFLICT (tenant_id, store_id, external_id)
                    WHERE sales_channel_id = 'pinzhi'
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        price_fen = EXCLUDED.price_fen,
                        updated_at = NOW()
                """),
                {
                    "tenant_id": str(tenant_id),
                    "store_id": store_id,
                    "name": dish_name,
                    "price_fen": price_fen,
                    "external_id": pinzhi_dish_id,
                },
            )
            synced += 1

        await db.flush()
        logger.info("pos_sync.menu_done", store_id=store_id, dishes_synced=synced)
        return {"success": True, "dishes_synced": synced}

    async def get_sync_status(
        self,
        merchant_code: str,
        db: AsyncSession,
    ) -> SyncStatusResponse:
        """查询商户的同步状态"""
        today_str = date.today().isoformat()

        # 统计今日已同步订单数
        result = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM orders
                WHERE sales_channel_id = 'pinzhi'
                  AND DATE(order_time) = :today
            """),
            {"today": today_str},
        )
        row = result.fetchone()
        total_today = int(row[0]) if row else 0

        # 最近一条品智订单时间
        result2 = await db.execute(
            text("""
                SELECT MAX(updated_at) AS last_sync
                FROM orders
                WHERE sales_channel_id = 'pinzhi'
            """),
        )
        row2 = result2.fetchone()
        last_sync = str(row2[0]) if row2 and row2[0] else None

        return SyncStatusResponse(
            merchant_code=merchant_code,
            last_sync_at=last_sync,
            last_sync_date=today_str,
            total_orders_today=total_today,
            status="idle",
        )

    # ── 私有方法 ──────────────────────────────────────────────────────────────

    async def _resolve_credentials(
        self,
        merchant_code: str,
        store_id: str,
        db: AsyncSession,
    ) -> tuple[str, str, str]:
        """解析品智凭证：store.config > 环境变量

        Returns:
            (base_url, token, ognid)
        """
        # 尝试从数据库 store 记录读取
        try:
            result = await db.execute(
                text("SELECT config, code FROM stores WHERE id = :sid"),
                {"sid": store_id},
            )
            row = result.fetchone()
            if row:
                cfg = row[0] if isinstance(row[0], dict) else {}
                store_code = row[1] or store_id

                base_url = cfg.get("pinzhi_base_url") or _get_merchant_env(
                    merchant_code, "BASE_URL"
                )
                token = cfg.get("pinzhi_token") or _get_merchant_env(
                    merchant_code, "TOKEN"
                )
                ognid = (
                    cfg.get("pinzhi_ognid")
                    or cfg.get("pinzhi_store_id")
                    or _get_merchant_env(merchant_code, "OGNID")
                    or store_code
                )
                return base_url, token, str(ognid)
        except (KeyError, ValueError, OSError) as e:
            logger.warning(
                "pos_sync.credential_lookup_failed",
                store_id=store_id,
                error=str(e),
            )

        # 回退到纯环境变量
        base_url = _get_merchant_env(merchant_code, "BASE_URL")
        token = _get_merchant_env(merchant_code, "TOKEN")
        ognid = _get_merchant_env(merchant_code, "OGNID") or store_id
        return base_url, token, ognid

    async def _get_store_name(self, store_id: str, db: AsyncSession) -> str:
        """获取门店名称"""
        try:
            result = await db.execute(
                text("SELECT name FROM stores WHERE id = :sid"),
                {"sid": store_id},
            )
            row = result.fetchone()
            return str(row[0]) if row and row[0] else store_id
        except (OSError, ValueError, RuntimeError):
            return store_id

    async def _get_active_store_ids(
        self,
        merchant_code: str,
        store_ids: list[str] | None,
        db: AsyncSession,
    ) -> list[str]:
        """获取活跃门店ID列表"""
        if store_ids:
            return store_ids

        try:
            result = await db.execute(
                text("""
                    SELECT id::text FROM stores
                    WHERE is_active = true
                    ORDER BY created_at
                """),
            )
            return [str(row[0]) for row in result.fetchall()]
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("pos_sync.store_list_error", error=str(e))
            return []

    async def _upsert_order(self, order_dict: dict[str, Any], db: AsyncSession) -> bool:
        """UPSERT单条订单，返回是否为新插入"""
        result = await db.execute(
            text("""
                INSERT INTO orders
                    (id, tenant_id, store_id, order_no, order_type,
                     sales_channel_id, table_number, waiter_id,
                     customer_phone, customer_name,
                     total_amount_fen, discount_amount_fen, final_amount_fen,
                     status, order_time, completed_at, notes, order_metadata)
                VALUES
                    (:id, :tenant_id, :store_id, :order_no, :order_type,
                     :sales_channel_id, :table_number, :waiter_id,
                     :customer_phone, :customer_name,
                     :total_amount_fen, :discount_amount_fen, :final_amount_fen,
                     :status, :order_time, :completed_at, :notes,
                     :order_metadata::jsonb)
                ON CONFLICT (order_no) DO UPDATE SET
                    status              = EXCLUDED.status,
                    total_amount_fen    = EXCLUDED.total_amount_fen,
                    discount_amount_fen = EXCLUDED.discount_amount_fen,
                    final_amount_fen    = EXCLUDED.final_amount_fen,
                    customer_phone      = COALESCE(NULLIF(EXCLUDED.customer_phone, ''), orders.customer_phone),
                    customer_name       = COALESCE(NULLIF(EXCLUDED.customer_name, ''), orders.customer_name),
                    completed_at        = COALESCE(EXCLUDED.completed_at, orders.completed_at),
                    order_metadata      = EXCLUDED.order_metadata::jsonb,
                    updated_at          = NOW()
                RETURNING (xmax = 0) AS is_insert
            """),
            {
                **order_dict,
                "order_metadata": __import__("json").dumps(
                    order_dict.get("order_metadata") or {}, ensure_ascii=False
                ),
            },
        )
        row = result.fetchone()
        return bool(row and row[0]) if row else True

    async def _upsert_order_item(
        self, item_dict: dict[str, Any], db: AsyncSession
    ) -> None:
        """UPSERT单条订单明细"""
        await db.execute(
            text("""
                INSERT INTO order_items
                    (id, tenant_id, order_id, item_name, quantity,
                     unit_price_fen, subtotal_fen, notes, customizations)
                VALUES
                    (:id, :tenant_id, :order_id, :item_name, :quantity,
                     :unit_price_fen, :subtotal_fen, :notes,
                     :customizations::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    quantity       = EXCLUDED.quantity,
                    unit_price_fen = EXCLUDED.unit_price_fen,
                    subtotal_fen   = EXCLUDED.subtotal_fen,
                    updated_at     = NOW()
            """),
            {
                **item_dict,
                "customizations": __import__("json").dumps(
                    item_dict.get("customizations") or {}, ensure_ascii=False
                ),
            },
        )


def _safe_int_from_mapper(val: Any, default: int = 0) -> int:
    """安全转整数（复用 pos_mapper 的逻辑）"""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default
