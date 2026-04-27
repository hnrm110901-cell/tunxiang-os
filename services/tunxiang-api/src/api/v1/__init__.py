"""V1 API — 所有路由模块"""

from . import auth_routes, brain_routes, hub_routes, ops_routes, pos_sync_routes, trade_routes

__all__ = ["auth_routes", "hub_routes", "trade_routes", "ops_routes", "brain_routes", "pos_sync_routes"]
