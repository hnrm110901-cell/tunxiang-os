"""租户配置 — 三家客户的品智API连接信息

敏感信息从环境变量读取，提供开发默认值。
"""
from __future__ import annotations

import os
import uuid
from typing import Any

from pydantic import BaseModel


class PinzhiTenantConfig(BaseModel):
    """单个租户的品智API配置"""

    tenant_id: uuid.UUID
    tenant_name: str
    brand_id: str
    base_url: str
    token: str
    timeout: int = 30
    retry_times: int = 3
    store_ognids: list[str] = []

    def to_adapter_config(self) -> dict[str, Any]:
        """转换为 PinzhiAdapter 所需的 config 字典"""
        return {
            "base_url": self.base_url,
            "token": self.token,
            "timeout": self.timeout,
            "retry_times": self.retry_times,
        }


def load_tenant_configs() -> list[PinzhiTenantConfig]:
    """从环境变量加载三个租户的品智API配置"""
    configs: list[PinzhiTenantConfig] = []
    defaults = [
        {"tenant_id": "a1000000-0000-0000-0000-000000000001", "tenant_name": "尝在一起", "brand_id": "brand_changzaiyiqi", "base_url": "https://openapi.pinzhi.cn", "token": "dev_token_czyz", "store_ognids": ""},
        {"tenant_id": "a2000000-0000-0000-0000-000000000002", "tenant_name": "最黔线", "brand_id": "brand_zuiqianxian", "base_url": "https://openapi.pinzhi.cn", "token": "dev_token_zqx", "store_ognids": ""},
        {"tenant_id": "a3000000-0000-0000-0000-000000000003", "tenant_name": "尚宫厨", "brand_id": "brand_shanggongchu", "base_url": "https://openapi.pinzhi.cn", "token": "dev_token_sgc", "store_ognids": ""},
    ]
    for i, default in enumerate(defaults, start=1):
        prefix = f"TENANT_{i}"
        tenant_id_str = os.getenv(f"{prefix}_ID", default["tenant_id"])
        store_ognids_str = os.getenv(f"{prefix}_STORE_OGNIDS", default["store_ognids"])
        store_ognids = [s.strip() for s in store_ognids_str.split(",") if s.strip()]
        configs.append(PinzhiTenantConfig(
            tenant_id=uuid.UUID(tenant_id_str),
            tenant_name=os.getenv(f"{prefix}_NAME", default["tenant_name"]),
            brand_id=os.getenv(f"{prefix}_BRAND_ID", default["brand_id"]),
            base_url=os.getenv(f"{prefix}_PINZHI_URL", default["base_url"]),
            token=os.getenv(f"{prefix}_PINZHI_TOKEN", default["token"]),
            store_ognids=store_ognids,
        ))
    return configs


def get_tenant_config_by_id(tenant_id: str) -> PinzhiTenantConfig | None:
    target = uuid.UUID(tenant_id)
    for cfg in load_tenant_configs():
        if cfg.tenant_id == target:
            return cfg
    return None


TENANT_REGISTRY: dict[str, PinzhiTenantConfig] = {}


def init_tenant_registry() -> None:
    global TENANT_REGISTRY
    for cfg in load_tenant_configs():
        TENANT_REGISTRY[str(cfg.tenant_id)] = cfg
