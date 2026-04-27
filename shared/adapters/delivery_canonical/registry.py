"""transformer 注册表 — 支持动态注册与查找"""
from __future__ import annotations

import logging
from typing import Any

from .base import (
    ALLOWED_PLATFORMS,
    CanonicalDeliveryOrder,
    CanonicalTransformer,
    TransformationError,
)

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, CanonicalTransformer] = {}


def register_transformer(transformer: CanonicalTransformer) -> None:
    """注册 transformer。重名覆盖旧注册（允许测试环境 monkey patch）。"""
    if transformer.platform not in ALLOWED_PLATFORMS:
        raise ValueError(
            f"transformer.platform {transformer.platform!r} 不在 ALLOWED_PLATFORMS "
            f"中，请先更新 v285 迁移 CHECK 约束"
        )
    if transformer.platform in _REGISTRY:
        logger.warning(
            "canonical_transformer_override",
            extra={"platform": transformer.platform},
        )
    _REGISTRY[transformer.platform] = transformer


def get_transformer(platform: str) -> CanonicalTransformer:
    """查找 transformer，找不到抛 TransformationError"""
    transformer = _REGISTRY.get(platform)
    if transformer is None:
        raise TransformationError(
            f"找不到 platform={platform!r} 的 transformer。已注册："
            f"{sorted(_REGISTRY.keys())}"
        )
    return transformer


def list_supported_platforms() -> list[str]:
    return sorted(_REGISTRY.keys())


def transform(
    platform: str, raw: dict[str, Any], tenant_id: str
) -> CanonicalDeliveryOrder:
    """便捷函数：按 platform 调对应 transformer"""
    transformer = get_transformer(platform)
    return transformer.transform(raw, tenant_id)
