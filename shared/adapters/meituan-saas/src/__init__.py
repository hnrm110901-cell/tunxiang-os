"""美团SAAS API适配器"""

from .adapter import MeituanSaasAdapter, get_internal_dish_id, set_dish_id_map
from .client import MeituanAPIError, MeituanAuthError, MeituanClient

__all__ = [
    "MeituanSaasAdapter",
    "MeituanClient",
    "MeituanAPIError",
    "MeituanAuthError",
    "set_dish_id_map",
    "get_internal_dish_id",
]
