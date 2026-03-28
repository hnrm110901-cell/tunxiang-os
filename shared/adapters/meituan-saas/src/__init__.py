"""美团SAAS API适配器"""
from .adapter import MeituanSaasAdapter, set_dish_id_map, get_internal_dish_id
from .client import MeituanClient, MeituanAPIError, MeituanAuthError

__all__ = [
    "MeituanSaasAdapter",
    "MeituanClient",
    "MeituanAPIError",
    "MeituanAuthError",
    "set_dish_id_map",
    "get_internal_dish_id",
]
