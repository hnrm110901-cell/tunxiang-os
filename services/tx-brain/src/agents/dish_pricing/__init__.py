"""D3c — Dish Dynamic Pricing Agent (Sprint D Wave 3)

边缘 Core ML（v0 规则）+ 云端 ModelRouter fallback。
绝不突破毛利底线（margin >= 15%）— 三条硬约束之首。

Public API:
    from .schemas import DishPricingRequest, DishPricingResponse, PricingSignal
    from .service import DishPricingService, GROSS_MARGIN_FLOOR
    from .edge_client import DishPricingEdgeClient, EdgeUnavailableError
    from .cloud_fallback import DishPricingCloudFallback
"""

from .cloud_fallback import DishPricingCloudFallback
from .edge_client import DishPricingEdgeClient, EdgeUnavailableError
from .schemas import DishPricingRequest, DishPricingResponse, PricingSignal
from .service import GROSS_MARGIN_FLOOR, DishPricingService

__all__ = [
    "DishPricingRequest",
    "DishPricingResponse",
    "PricingSignal",
    "DishPricingService",
    "GROSS_MARGIN_FLOOR",
    "DishPricingEdgeClient",
    "EdgeUnavailableError",
    "DishPricingCloudFallback",
]
