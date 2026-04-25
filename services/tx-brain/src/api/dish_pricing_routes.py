"""D3c — Dish Dynamic Pricing HTTP route.

POST /api/v1/agents/dish-pricing/recommend
  - 强制 X-Tenant-ID header
  - 强制 Authorization Bearer（JWT 占位 — 真实 JWT 验签由 gateway 完成；
    此处只防裸调用，与现有 brain_routes 风格保持一致）
  - 校验 body.tenant_id == X-Tenant-ID（防跨租户）
  - 委托 DishPricingService.recommend
  - 返回 DishPricingResponse；floor_protected=True 时也是 200（不是错误）

CLAUDE.md §17 Tier 2 路径。
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException

from ..agents.dish_pricing import (
    DishPricingRequest,
    DishPricingResponse,
    DishPricingService,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/agents/dish-pricing", tags=["dish-pricing"])


# ─── 依赖 ────────────────────────────────────────────────────────────────


def _require_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    """强制 X-Tenant-ID header"""
    if not x_tenant_id or not x_tenant_id.strip():
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return x_tenant_id


def _require_jwt(authorization: str = Header(..., alias="Authorization")) -> str:
    """强制 Bearer JWT（与现有 brain_routes 保持一致：仅防裸调，签名验证在 gateway）"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization Bearer token required")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token empty")
    return token


# 单例 — 测试可通过 dependency_overrides 替换
_dish_pricing_service_singleton: DishPricingService | None = None


def get_dish_pricing_service() -> DishPricingService:
    """惰性单例（测试时可 monkey-patch）"""
    global _dish_pricing_service_singleton
    if _dish_pricing_service_singleton is None:
        _dish_pricing_service_singleton = DishPricingService()
    return _dish_pricing_service_singleton


# ─── 路由 ────────────────────────────────────────────────────────────────


@router.post("/recommend", response_model=DishPricingResponse)
async def recommend_price(
    req: DishPricingRequest,
    tenant_id: str = Depends(_require_tenant),
    _token: str = Depends(_require_jwt),
    service: DishPricingService = Depends(get_dish_pricing_service),
) -> DishPricingResponse:
    """生成菜品动态定价建议。

    floor_protected=True 表示毛利底线已兜底（不是错误）；前端若需要可高亮提示。
    """
    # 强一致：body.tenant_id 必须 == X-Tenant-ID（防跨租户写）
    if req.tenant_id != tenant_id:
        raise HTTPException(
            status_code=403,
            detail="body.tenant_id mismatch X-Tenant-ID",
        )

    try:
        return await service.recommend(req)
    except ValueError as exc:
        # 输入级问题（cost >= base 等）
        raise HTTPException(status_code=400, detail=str(exc)) from exc
