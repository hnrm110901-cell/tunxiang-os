"""配送商适配器基类 — 定义统一接口和数据契约

所有 provider（达达 / 顺丰同城 / 自有骑手）必须实现此接口。
路由层只与本基类交互，永远不直接 import 子类。
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class ProviderConfigSnapshot:
    """从 DB 读出的配置快照（adapter 不直接依赖 ORM 对象，便于测试）"""

    provider: str
    tenant_id: str
    store_id: str
    app_key: Optional[str] = None
    app_secret: Optional[str] = None
    merchant_id: Optional[str] = None
    shop_no: Optional[str] = None
    callback_url: Optional[str] = None
    extra_config: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DispatchOrderInput:
    """下单输入（与 DB 解耦，纯领域对象）"""

    dispatch_id: str
    order_id: str
    store_id: str
    delivery_address: str
    delivery_lat: Optional[float]
    delivery_lng: Optional[float]
    distance_meters: int
    delivery_fee_fen: int
    tip_fen: int
    estimated_minutes: int
    customer_phone: Optional[str] = None


@dataclass(frozen=True)
class DispatchResult:
    """下单结果（统一格式，路由层只关心这些字段）"""

    success: bool
    provider_order_id: Optional[str]
    estimated_minutes: int
    raw: dict = field(default_factory=dict)
    error_code: Optional[str] = None
    error_message: Optional[str] = None


@dataclass(frozen=True)
class RiderLocation:
    """骑手位置查询结果"""

    rider_lat: Optional[float]
    rider_lng: Optional[float]
    rider_name: Optional[str]
    rider_phone: Optional[str]
    updated_at: datetime
    raw: dict = field(default_factory=dict)


class DeliveryDispatchError(Exception):
    """所有 adapter 业务异常的基类"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class BaseDeliveryDispatchAdapter(ABC):
    """配送商适配器基类

    设计原则：
      1. 路由层只 await adapter.dispatch / cancel / query_location
      2. 子类内部封装 HTTP 调用、签名、错误码映射
      3. 当前阶段所有子类返回 mock 数据，便于联调；接入真实 API 时仅替换 _call_api
    """

    provider: str = ""  # 子类覆盖

    def __init__(self, store_config: ProviderConfigSnapshot) -> None:
        if store_config.provider != self.provider:
            raise ValueError(
                f"adapter {self.__class__.__name__} expects provider={self.provider!r}, got {store_config.provider!r}"
            )
        self.config = store_config

    # ─── 必须实现的抽象方法 ───────────────────────────────────────────

    @abstractmethod
    async def dispatch(self, order: DispatchOrderInput) -> DispatchResult:
        """下发配送单到三方平台 / 自有骑手池。

        实现要点：
          - 不可抛裸 Exception；业务失败必须返回 DispatchResult(success=False, ...)
          - 网络/签名异常允许向上抛 DeliveryDispatchError
        """
        ...

    @abstractmethod
    async def cancel(self, provider_order_id: str, reason: str) -> bool:
        """取消三方平台已下发的配送单"""
        ...

    @abstractmethod
    async def query_location(self, provider_order_id: str) -> RiderLocation:
        """查询骑手实时位置"""
        ...

    @abstractmethod
    async def notify_pickup_ready(
        self,
        provider_order_id: str,
        dispatch_id: str,
    ) -> bool:
        """通知骑手"出餐完成可取货"。
        三方平台一般无此接口（骑手到店扫码即可），自有骑手通过 WebSocket/推送实现。
        """
        ...


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def gen_mock_provider_order_id(provider: str) -> str:
    return f"{provider.upper()}-{uuid.uuid4().hex[:10].upper()}"
