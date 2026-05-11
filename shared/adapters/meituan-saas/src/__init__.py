"""美团SAAS API适配器。

CH-02.7a a3 起：MeituanClient / MeituanAPIError / MeituanAuthError 唯一 SoT
位于 shared/adapters/meituan_delivery_adapter.py，本包不再 re-export
（grep 全仓零外部依赖；历史 saas/src/client.py 已在 a3 删除）。

外部如需 client/Error，应直接 import 顶层：
    from shared.adapters.meituan_delivery_adapter import (
        MeituanClient, MeituanAPIError, MeituanAuthError,
    )
"""

from .adapter import MeituanSaasAdapter, get_internal_dish_id, set_dish_id_map

__all__ = [
    "MeituanSaasAdapter",
    "set_dish_id_map",
    "get_internal_dish_id",
]
