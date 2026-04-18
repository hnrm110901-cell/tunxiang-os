"""依赖注入 — 全局单例管理

所有路由通过本模块获取服务实例，避免循环导入。
生命周期由 main.py 的 lifespan 管理。
"""
from __future__ import annotations

from typing import Optional

from .channels.registry import ChannelRegistry
from .routing.engine import PaymentRoutingEngine
from .payment_service import PaymentNexusService

# 全局单例（由 lifespan 初始化）
_registry: Optional[ChannelRegistry] = None
_routing_engine: Optional[PaymentRoutingEngine] = None


def init_globals(
    registry: ChannelRegistry,
    routing_engine: PaymentRoutingEngine,
) -> None:
    """初始化全局单例（main.py lifespan 调用）"""
    global _registry, _routing_engine
    _registry = registry
    _routing_engine = routing_engine


async def get_channel_registry() -> ChannelRegistry:
    if _registry is None:
        raise RuntimeError("ChannelRegistry 未初始化，请检查 lifespan")
    return _registry


async def get_routing_engine() -> PaymentRoutingEngine:
    if _routing_engine is None:
        raise RuntimeError("RoutingEngine 未初始化，请检查 lifespan")
    return _routing_engine


async def get_db():
    """获取数据库会话（延迟导入避免循环依赖）"""
    from shared.ontology.src.database import get_async_session
    async for session in get_async_session():
        return session


async def get_payment_service() -> PaymentNexusService:
    """构造 PaymentNexusService 实例"""
    db = await get_db()
    engine = await get_routing_engine()
    return PaymentNexusService(db=db, routing=engine)
