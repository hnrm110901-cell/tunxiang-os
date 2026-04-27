"""租户配置 — 三家客户的真实品智POS API连接信息

数据来源：zhilian-os/apps/api-gateway/scripts/seed_real_merchants.py
敏感信息从环境变量读取，此处为开发默认值（品智API Token）。
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from pydantic import BaseModel


class PinzhiStoreConfig(BaseModel):
    """单个门店的品智配置"""

    store_name: str
    store_code: str
    city: str
    pinzhi_store_id: int
    pinzhi_store_token: str
    pinzhi_oms_id: int


class PinzhiTenantConfig(BaseModel):
    """单个租户的品智API配置"""

    tenant_id: uuid.UUID
    tenant_name: str
    brand_id: str
    base_url: str
    token: str  # 品智全局 API Token
    timeout: int = 30
    retry_times: int = 3
    store_ognids: list[str] = []  # 品智门店 ognid 列表
    stores: list[PinzhiStoreConfig] = []

    def to_adapter_config(self) -> dict[str, Any]:
        """转换为 PinzhiAdapter 所需的 config 字典"""
        return {
            "base_url": self.base_url,
            "token": self.token,
            "timeout": self.timeout,
            "retry_times": self.retry_times,
        }


# ══════════════════════════════════════════════════════════════════
# 三家商户真实配置（来自 zhilian-os seed_real_merchants.py）
# ══════════════════════════════════════════════════════════════════

REAL_TENANT_DEFAULTS = [
    # ── 尝在一起（品智 + 微生活 + 喰星云） ──
    {
        "tenant_id": "10000000-0000-0000-0000-000000000001",
        "tenant_name": "尝在一起",
        "brand_id": "BRD_CZYZ0001",
        "base_url": "https://czyq.pinzhikeji.net/pzcatering-gateway",
        "token": "3bbc9bed2b42c1e1b3cca26389fbb81c",
        "stores": [
            {
                "store_name": "文化城店",
                "store_code": "CZYZ-WH001",
                "city": "长沙",
                "pinzhi_store_id": 2461,
                "pinzhi_store_token": "752b4b16a863ce47def11cf33b1b521f",
                "pinzhi_oms_id": 2461,
            },
            {
                "store_name": "浏小鲜",
                "store_code": "CZYZ-LXX001",
                "city": "长沙",
                "pinzhi_store_id": 7269,
                "pinzhi_store_token": "f5cc1a27db6e215ae7bb5512b6b57981",
                "pinzhi_oms_id": 7269,
            },
            {
                "store_name": "永安店",
                "store_code": "CZYZ-YA001",
                "city": "长沙",
                "pinzhi_store_id": 19189,
                "pinzhi_store_token": "56cd51b69211297104a0608f6a696b80",
                "pinzhi_oms_id": 19189,
            },
        ],
    },
    # ── 最黔线（品智 + 微生活） ──
    {
        "tenant_id": "10000000-0000-0000-0000-000000000002",
        "tenant_name": "最黔线",
        "brand_id": "BRD_ZQX0001",
        "base_url": "https://ljcg.pinzhikeji.net/pzcatering-gateway",
        "token": "47a428538d350fac1640a51b6bbda68c",
        "stores": [
            {
                "store_name": "马家湾店",
                "store_code": "ZQX-MJW001",
                "city": "长沙",
                "pinzhi_store_id": 20529,
                "pinzhi_store_token": "29cdb6acac3615070bb853afcbb32f60",
                "pinzhi_oms_id": 20529,
            },
            {
                "store_name": "东欣万象店",
                "store_code": "ZQX-DXWX001",
                "city": "长沙",
                "pinzhi_store_id": 32109,
                "pinzhi_store_token": "ed2c948284d09cf9e096e9d965936aa3",
                "pinzhi_oms_id": 32109,
            },
            {
                "store_name": "合众路店",
                "store_code": "ZQX-HZL001",
                "city": "长沙",
                "pinzhi_store_id": 32304,
                "pinzhi_store_token": "43f0b54db12b0618ea612b2a0a4d2675",
                "pinzhi_oms_id": 32304,
            },
            {
                "store_name": "广州路店",
                "store_code": "ZQX-GZL001",
                "city": "长沙",
                "pinzhi_store_id": 32305,
                "pinzhi_store_token": "a8a4e4daf86875d4a4e0254b6eb7191e",
                "pinzhi_oms_id": 32305,
            },
            {
                "store_name": "昆明路店",
                "store_code": "ZQX-KML001",
                "city": "长沙",
                "pinzhi_store_id": 32306,
                "pinzhi_store_token": "d656668d285a100c851bbe149d4364f3",
                "pinzhi_oms_id": 32306,
            },
            {
                "store_name": "仁怀店",
                "store_code": "ZQX-RH001",
                "city": "仁怀",
                "pinzhi_store_id": 32309,
                "pinzhi_store_token": "36bf0644e5703adc8a4d1ddd7b8f0e95",
                "pinzhi_oms_id": 32309,
            },
        ],
    },
    # ── 尚宫厨（品智 + 微生活 + 微生活卡券中心） ──
    {
        "tenant_id": "10000000-0000-0000-0000-000000000003",
        "tenant_name": "尚宫厨",
        "brand_id": "BRD_SGC0001",
        "base_url": "https://xcsgc.pinzhikeji.net/pzcatering-gateway",
        "token": "8275cf74d1943d7a32531d2d4f889870",
        "stores": [
            {
                "store_name": "采霞街店",
                "store_code": "SGC-CXJ001",
                "city": "长沙",
                "pinzhi_store_id": 2463,
                "pinzhi_store_token": "852f1d34c75af0b8eb740ef47f133130",
                "pinzhi_oms_id": 2463,
            },
            {
                "store_name": "湘江水岸店",
                "store_code": "SGC-XJSA001",
                "city": "长沙",
                "pinzhi_store_id": 7896,
                "pinzhi_store_token": "27a36f2feea6d3a914438f6cb32108c3",
                "pinzhi_oms_id": 7896,
            },
            {
                "store_name": "乐城店",
                "store_code": "SGC-LC001",
                "city": "长沙",
                "pinzhi_store_id": 24777,
                "pinzhi_store_token": "5cbfb449112f698218e0b1be1a3bc7c6",
                "pinzhi_oms_id": 24777,
            },
            {
                "store_name": "啫匠亲城店",
                "store_code": "SGC-ZJQC001",
                "city": "长沙",
                "pinzhi_store_id": 36199,
                "pinzhi_store_token": "08f3791e15f48338405728a3a92fcd7f",
                "pinzhi_oms_id": 36199,
            },
            {
                "store_name": "酃湖雅院店",
                "store_code": "SGC-LHYY001",
                "city": "株洲",
                "pinzhi_store_id": 41405,
                "pinzhi_store_token": "bb7e89dcd0ac339b51631eca99e51c9b",
                "pinzhi_oms_id": 41405,
            },
        ],
    },
]


def load_tenant_configs() -> list[PinzhiTenantConfig]:
    """加载三个租户的品智API配置，优先使用环境变量覆盖。"""
    configs: list[PinzhiTenantConfig] = []
    for i, default in enumerate(REAL_TENANT_DEFAULTS, start=1):
        prefix = f"TENANT_{i}"
        tenant_id_str = os.getenv(f"{prefix}_ID", default["tenant_id"])
        base_url = os.getenv(f"{prefix}_PINZHI_URL", default["base_url"])
        token = os.getenv(f"{prefix}_PINZHI_TOKEN", default["token"])
        stores = [PinzhiStoreConfig(**s) for s in default["stores"]]
        store_ognids = [str(s.pinzhi_store_id) for s in stores]
        env_ognids = os.getenv(f"{prefix}_STORE_OGNIDS", "")
        if env_ognids.strip():
            store_ognids = [s.strip() for s in env_ognids.split(",") if s.strip()]
        configs.append(
            PinzhiTenantConfig(
                tenant_id=uuid.UUID(tenant_id_str),
                tenant_name=os.getenv(f"{prefix}_NAME", default["tenant_name"]),
                brand_id=os.getenv(f"{prefix}_BRAND_ID", default["brand_id"]),
                base_url=base_url,
                token=token,
                store_ognids=store_ognids,
                stores=stores,
            )
        )
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
