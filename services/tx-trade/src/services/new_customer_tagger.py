"""新顾客标签服务 — 外卖平台新客识别

识别外卖平台上的新顾客，并标注到订单的 is_new_customer 字段。

设计：
  - 基于 platform_user_id 查询该客户在该平台的历史订单数
  - 结果缓存：同一 customer+platform 当天内缓存（内存 LRU，最多10000条）
  - 缓存 key 格式：{tenant_id}:{platform}:{customer_id}:{date}

SCHEMA SQL（需手动执行，禁止创建迁移文件）：
  ALTER TABLE delivery_orders
    ADD COLUMN IF NOT EXISTS is_new_customer BOOLEAN NOT NULL DEFAULT false;

  -- platform_user_id 存储在 items_json 中，示例：
  -- items_json->>'meituan_user_id'  美团用户ID
  -- items_json->>'eleme_user_id'    饿了么用户ID
  -- items_json->>'douyin_user_id'   抖音用户ID
  -- items_json->>'platform_user_id' 通用平台用户ID
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import date
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

_CACHE_MAX_SIZE = 10_000


class _LRUCache:
    """线程安全的内存 LRU 缓存，不引入 Redis 依赖"""

    def __init__(self, max_size: int = _CACHE_MAX_SIZE) -> None:
        self._max_size = max_size
        self._store: OrderedDict[str, bool] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[bool]:
        with self._lock:
            if key not in self._store:
                return None
            self._store.move_to_end(key)
            return self._store[key]

    def set(self, key: str, value: bool) -> None:
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = value
            if len(self._store) > self._max_size:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


class NewCustomerTagger:
    """外卖新顾客标签服务

    使用场景：
    1. 外卖订单接入时，调用 tag_order() 自动判断并写入 is_new_customer
    2. KDS / 接单面板通过 delivery_orders.is_new_customer 展示标签
    """

    # 类级别缓存（跨请求复用，进程内共享）
    _cache: _LRUCache = _LRUCache(max_size=_CACHE_MAX_SIZE)

    @classmethod
    def _cache_key(
        cls,
        customer_id: str,
        platform: str,
        tenant_id: str,
        cache_date: Optional[date] = None,
    ) -> str:
        """构造缓存 key，含日期确保跨天自动失效"""
        d = (cache_date or date.today()).isoformat()
        return f"{tenant_id}:{platform}:{customer_id}:{d}"

    @classmethod
    async def is_new_customer(
        cls,
        customer_id: str,
        platform: str,
        tenant_id: str,
        db: AsyncSession,
        _today: Optional[date] = None,  # 仅供测试注入
    ) -> bool:
        """判断外卖平台用户是否为新顾客

        Args:
            customer_id: 平台侧用户ID（platform_user_id）
            platform: 平台标识 meituan/eleme/douyin
            tenant_id: 租户ID
            db: 数据库会话
            _today: 可注入日期（测试用）

        Returns:
            True 表示新客（历史无完成订单）
        """
        if not customer_id or not platform:
            return False

        cache_key = cls._cache_key(customer_id, platform, tenant_id, _today)
        cached = cls._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # 查询该平台用户的历史完成订单数（不含当前进行中订单）
            result = await db.execute(
                text(
                    """
                    SELECT COUNT(id) AS order_count
                    FROM delivery_orders
                    WHERE tenant_id = :tenant_id
                      AND platform   = :platform
                      AND (
                            (platform = 'meituan' AND items_json->>'meituan_user_id' = :customer_id)
                         OR (platform = 'eleme'   AND items_json->>'eleme_user_id'   = :customer_id)
                         OR (platform = 'douyin'  AND items_json->>'douyin_user_id'  = :customer_id)
                         OR items_json->>'platform_user_id' = :customer_id
                      )
                      AND status IN ('completed')
                      AND is_deleted = false
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "platform": platform,
                    "customer_id": customer_id,
                },
            )
            row = result.fetchone()
            order_count = row.order_count if row else 0
            is_new = order_count == 0

            cls._cache.set(cache_key, is_new)
            logger.debug(
                "new_customer_tagger.is_new_customer",
                customer_id=customer_id,
                platform=platform,
                order_count=order_count,
                is_new=is_new,
            )
            return is_new

        except SQLAlchemyError as exc:  # MLPS3-P0: 异常收窄
            logger.error(
                "new_customer_tagger.is_new_customer_failed",
                customer_id=customer_id,
                platform=platform,
                error=str(exc),
            )
            raise RuntimeError(f"Failed to check new customer: {exc}") from exc

    @classmethod
    async def tag_order(
        cls,
        order_id: str,
        tenant_id: str,
        db: AsyncSession,
        _today: Optional[date] = None,  # 仅供测试注入
    ) -> bool:
        """判断并写入订单的 is_new_customer 标签

        流程：
        1. 查询 delivery_orders 获取 platform + platform_user_id
        2. 调用 is_new_customer() 判断
        3. UPDATE delivery_orders SET is_new_customer = ?

        Args:
            order_id: delivery_orders.id（UUID 字符串）
            tenant_id: 租户ID
            db: 数据库会话
            _today: 可注入日期（测试用）

        Returns:
            is_new_customer 值（True=新客）

        Raises:
            ValueError: 订单不存在
            RuntimeError: 数据库操作失败
        """
        try:
            # 获取订单基本信息
            result = await db.execute(
                text(
                    """
                    SELECT id, platform, items_json
                    FROM delivery_orders
                    WHERE id         = :order_id
                      AND tenant_id  = :tenant_id
                      AND is_deleted = false
                    LIMIT 1
                    """
                ),
                {"order_id": order_id, "tenant_id": tenant_id},
            )
            row = result.fetchone()
            if row is None:
                raise ValueError(f"DeliveryOrder not found: {order_id}")

            platform = row.platform
            items_json = row.items_json or {}

            # 从 items_json 或其他字段提取 platform_user_id
            customer_id = (
                items_json.get("meituan_user_id")
                or items_json.get("eleme_user_id")
                or items_json.get("douyin_user_id")
                or items_json.get("platform_user_id")
                or ""
            )

            if not customer_id:
                logger.warning(
                    "new_customer_tagger.tag_order.no_customer_id",
                    order_id=order_id,
                    platform=platform,
                )
                return False

            is_new = await cls.is_new_customer(
                customer_id=customer_id,
                platform=platform,
                tenant_id=tenant_id,
                db=db,
                _today=_today,
            )

            # 写回订单
            await db.execute(
                text(
                    """
                    UPDATE delivery_orders
                    SET is_new_customer = :is_new,
                        updated_at      = NOW()
                    WHERE id         = :order_id
                      AND tenant_id  = :tenant_id
                    """
                ),
                {
                    "is_new": is_new,
                    "order_id": order_id,
                    "tenant_id": tenant_id,
                },
            )
            await db.commit()

            logger.info(
                "new_customer_tagger.tag_order",
                order_id=order_id,
                platform=platform,
                is_new_customer=is_new,
            )
            return is_new

        except ValueError:
            raise
        except SQLAlchemyError as exc:  # MLPS3-P0: 异常收窄
            await db.rollback()
            logger.error(
                "new_customer_tagger.tag_order_failed",
                order_id=order_id,
                error=str(exc),
            )
            raise RuntimeError(f"Failed to tag order: {exc}") from exc
