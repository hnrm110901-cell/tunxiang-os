"""支付路由引擎 — 多租户 × 多门店 × 多渠道路由

根据 (tenant_id, store_id, method, trade_type) 决定走哪个支付渠道实例。

路由优先级：
  1. 门店级配置（store_id 精确匹配）
  2. 品牌级配置（brand_id 匹配）
  3. 租户级配置（tenant_id 兜底）

配置存储在 payment_channel_configs 表：
  - 尝在一起 → 收钱吧（微信/支付宝/银联）
  - 最黔线   → 拉卡拉（微信/支付宝）+ 银联直连
  - 徐记海鲜 → 微信直连V3 + 支付宝直连
"""
from __future__ import annotations

from typing import Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.base import BasePaymentChannel, PayMethod, TradeType
from ..channels.registry import ChannelRegistry

logger = structlog.get_logger(__name__)


class ChannelConfig(BaseModel):
    """渠道配置记录"""
    id: Optional[str] = None
    tenant_id: str
    brand_id: Optional[str] = None
    store_id: Optional[str] = None
    method: PayMethod
    channel_name: str                       # 对应 ChannelRegistry 中的 channel_name
    priority: int = 0                       # 优先级，数字越大越优先
    is_active: bool = True
    config_data: dict = Field(default_factory=dict)  # 渠道特有配置（商户号/密钥路径等）


class PaymentRoutingEngine:
    """支付路由引擎

    职责：
      1. 根据租户/门店/支付方式解析应该使用哪个渠道
      2. 支持运行时热更新配置（管理后台修改后即时生效）
      3. 降级策略：指定渠道不可用时自动切换备选渠道
    """

    def __init__(self, registry: ChannelRegistry) -> None:
        self._registry = registry
        # 内存缓存：(tenant_id, store_id, method) → channel_name
        self._cache: dict[tuple[str, str, str], str] = {}

    async def resolve(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        method: PayMethod,
        trade_type: TradeType = TradeType.B2C,
    ) -> BasePaymentChannel:
        """解析支付渠道实例

        查找顺序：
          1. 内存缓存命中 → 直接返回
          2. DB 查询 → 按优先级（门店 > 品牌 > 租户）匹配
          3. ChannelRegistry 兜底 → 按 method 查找默认渠道

        Raises:
            ValueError: 找不到任何可用渠道
        """
        cache_key = (tenant_id, store_id, method.value)

        # 1. 缓存命中
        if cache_key in self._cache:
            channel_name = self._cache[cache_key]
            try:
                return self._registry.get(channel_name)
            except KeyError:
                # 缓存过期（渠道被注销），清除并继续查找
                del self._cache[cache_key]

        # 2. DB 查询（按 priority DESC，门店级 > 品牌级 > 租户级）
        channel_name = await self._query_config(db, tenant_id, store_id, method)

        if channel_name:
            self._cache[cache_key] = channel_name
            return self._registry.get(channel_name)

        # 3. 兜底：从 registry 按 method + trade_type 查找
        channel = self._registry.find(method, trade_type)
        if channel:
            self._cache[cache_key] = channel.channel_name
            return channel

        raise ValueError(
            f"找不到支付渠道: tenant={tenant_id}, store={store_id}, "
            f"method={method.value}, trade_type={trade_type.value}"
        )

    async def _query_config(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        method: PayMethod,
    ) -> Optional[str]:
        """从 DB 查询渠道配置

        优先级排序：
          - store_id 精确匹配的排最前
          - 其次 brand_id 匹配（暂简化：store_id IS NULL 的为品牌/租户级）
          - priority DESC
        """
        result = await db.execute(
            text("""
                SELECT channel_name
                FROM payment_channel_configs
                WHERE tenant_id = :tenant_id::UUID
                  AND method = :method
                  AND is_active = TRUE
                  AND (store_id = :store_id::UUID OR store_id IS NULL)
                ORDER BY
                  CASE WHEN store_id = :store_id::UUID THEN 0 ELSE 1 END,
                  priority DESC
                LIMIT 1
            """),
            {"tenant_id": tenant_id, "store_id": store_id, "method": method.value},
        )
        row = result.fetchone()
        return row[0] if row else None

    def invalidate_cache(
        self,
        tenant_id: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> int:
        """清除缓存（配置变更时调用）

        Args:
            tenant_id: 指定租户（None = 清除全部）
            store_id: 指定门店（None = 清除该租户全部）

        Returns:
            清除的缓存条目数
        """
        if tenant_id is None:
            count = len(self._cache)
            self._cache.clear()
            return count

        keys_to_remove = [
            k for k in self._cache
            if k[0] == tenant_id and (store_id is None or k[1] == store_id)
        ]
        for k in keys_to_remove:
            del self._cache[k]
        return len(keys_to_remove)
