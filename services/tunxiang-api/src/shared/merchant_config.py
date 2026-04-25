"""多商户配置加载器

从环境变量安全加载商户 POS/CRM 凭证。
不在代码中存储任何敏感值，全部通过 os.getenv 读取。
缺失凭证时记录 warning 但不崩溃，保证系统可用性。

用法:
    from shared.merchant_config import get_merchant_config, get_all_merchants

    # 获取单个商户
    czyz = get_merchant_config("czyz")
    if czyz and czyz.pinzhi:
        token = czyz.pinzhi["api_token"]

    # 获取所有已配置商户
    for m in get_all_merchants():
        print(m.code, m.brand_name)
"""

from __future__ import annotations

import os

import structlog

logger = structlog.get_logger(__name__)


# ── 商户注册表（code → 元数据） ──────────────────────────────
# 新增商户时只需在此处添加一行，环境变量命名遵循 {CODE}_PINZHI_* / {CODE}_AOQIWEI_* 规范
MERCHANT_REGISTRY: dict[str, dict] = {
    "czyz": {
        "brand_name": "尝在一起",
        "brand_id": "BRD_CZYZ0001",
        "pinzhi_store_ids": ["2461", "7269", "19189"],
        "aoqiwei_store_ids": ["2461", "7269", "19189"],
    },
    "zqx": {
        "brand_name": "最黔线",
        "brand_id": "BRD_ZQX0001",
        "pinzhi_store_ids": ["20529", "32109", "32304", "32305", "32306", "32309"],
        "aoqiwei_store_ids": ["20529", "32109", "32304", "32305", "32306", "32309"],
    },
    "sgc": {
        "brand_name": "尚宫厨",
        "brand_id": "BRD_SGC0001",
        "pinzhi_store_ids": ["2463", "7896", "24777", "36199", "41405"],
        "aoqiwei_store_ids": ["2463", "7896", "24777", "36199", "41405"],
    },
}


class PinzhiConfig:
    """品智收银 POS 凭证"""

    def __init__(self, api_token: str, base_url: str, store_tokens: dict[str, str]):
        self.api_token = api_token
        self.base_url = base_url
        self.store_tokens = store_tokens  # {store_id: token}

    def get_store_token(self, store_id: str) -> str | None:
        """获取指定门店的独立 Token"""
        return self.store_tokens.get(store_id)


class AoqiweiConfig:
    """奥琦玮微生活 CRM 凭证"""

    def __init__(
        self,
        app_id: str,
        app_key: str,
        merchant_id: str,
        base_url: str,
        store_ids: dict[str, str],
    ):
        self.app_id = app_id
        self.app_key = app_key
        self.merchant_id = merchant_id
        self.base_url = base_url
        self.store_ids = store_ids  # {pinzhi_store_id: aoqiwei_store_id}


class CouponConfig:
    """奥琦玮卡券中心凭证"""

    def __init__(
        self,
        base_url: str,
        app_id: str,
        app_key: str,
        platforms: list[str],
    ):
        self.base_url = base_url
        self.app_id = app_id
        self.app_key = app_key
        self.platforms = platforms


class MerchantConfig:
    """单个商户的完整配置（POS + CRM + 卡券）"""

    def __init__(self, code: str, brand_name: str, brand_id: str):
        self.code = code
        self.brand_name = brand_name
        self.brand_id = brand_id
        self._meta = MERCHANT_REGISTRY.get(code, {})
        self.pinzhi: PinzhiConfig | None = self._load_pinzhi()
        self.aoqiwei: AoqiweiConfig | None = self._load_aoqiwei()
        self.coupon: CouponConfig | None = self._load_coupon()

    # ── 品智收银加载 ──

    def _load_pinzhi(self) -> PinzhiConfig | None:
        prefix = self.code.upper()
        api_token = os.getenv(f"{prefix}_PINZHI_API_TOKEN")
        if not api_token:
            logger.warning(
                "pinzhi_token_not_configured",
                merchant=self.code,
                hint=f"请设置环境变量 {prefix}_PINZHI_API_TOKEN",
            )
            return None

        base_url = os.getenv(
            f"{prefix}_PINZHI_BASE_URL",
            "http://czyq.pinzhikeji.net:8899/pzcatering-gateway",
        )

        # 收集所有门店 Token
        store_ids = self._meta.get("pinzhi_store_ids", [])
        store_tokens: dict[str, str] = {}
        for sid in store_ids:
            token = os.getenv(f"{prefix}_PINZHI_STORE_{sid}_TOKEN")
            if token:
                store_tokens[sid] = token
            else:
                logger.warning(
                    "pinzhi_store_token_missing",
                    merchant=self.code,
                    store_id=sid,
                    hint=f"请设置环境变量 {prefix}_PINZHI_STORE_{sid}_TOKEN",
                )

        return PinzhiConfig(
            api_token=api_token,
            base_url=base_url,
            store_tokens=store_tokens,
        )

    # ── 奥琦玮 CRM 加载 ──

    def _load_aoqiwei(self) -> AoqiweiConfig | None:
        prefix = self.code.upper()
        app_id = os.getenv(f"{prefix}_AOQIWEI_APP_ID")
        app_key = os.getenv(f"{prefix}_AOQIWEI_APP_KEY")
        if not app_id or not app_key:
            logger.warning(
                "aoqiwei_credentials_not_configured",
                merchant=self.code,
                hint=f"请设置环境变量 {prefix}_AOQIWEI_APP_ID 和 {prefix}_AOQIWEI_APP_KEY",
            )
            return None

        base_url = os.getenv(f"{prefix}_AOQIWEI_BASE_URL", "https://api.acewill.net")
        merchant_id = os.getenv(f"{prefix}_AOQIWEI_MERCHANT_ID", "")

        # 收集门店映射
        store_ids: dict[str, str] = {}
        for sid in self._meta.get("aoqiwei_store_ids", []):
            aoqiwei_id = os.getenv(f"{prefix}_AOQIWEI_STORE_{sid}_ID", sid)
            store_ids[sid] = aoqiwei_id

        return AoqiweiConfig(
            app_id=app_id,
            app_key=app_key,
            merchant_id=merchant_id,
            base_url=base_url,
            store_ids=store_ids,
        )

    # ── 卡券中心加载（仅部分商户启用） ──

    def _load_coupon(self) -> CouponConfig | None:
        prefix = self.code.upper()
        app_id = os.getenv(f"{prefix}_COUPON_APP_ID")
        app_key = os.getenv(f"{prefix}_COUPON_APP_KEY")
        if not app_id or not app_key:
            # 卡券中心非必须，静默跳过
            return None

        base_url = os.getenv(f"{prefix}_COUPON_BASE_URL", "https://apigateway.acewill.net")
        platforms_raw = os.getenv(f"{prefix}_COUPON_PLATFORMS", "")
        platforms = [p.strip() for p in platforms_raw.split(",") if p.strip()]

        return CouponConfig(
            base_url=base_url,
            app_id=app_id,
            app_key=app_key,
            platforms=platforms,
        )

    def __repr__(self) -> str:
        pos = "OK" if self.pinzhi else "MISSING"
        crm = "OK" if self.aoqiwei else "MISSING"
        coupon = "OK" if self.coupon else "N/A"
        return f"MerchantConfig({self.code!r}, brand={self.brand_name!r}, pos={pos}, crm={crm}, coupon={coupon})"


# ── 模块级缓存（进程内单例） ──────────────────────────────────
_cache: dict[str, MerchantConfig] = {}


def get_merchant_config(merchant_code: str) -> MerchantConfig | None:
    """获取指定商户配置，不存在则返回 None

    Args:
        merchant_code: 商户代码，如 "czyz"、"zqx"、"sgc"

    Returns:
        MerchantConfig 实例，或 None（未注册的商户代码）
    """
    code = merchant_code.lower()
    if code in _cache:
        return _cache[code]

    meta = MERCHANT_REGISTRY.get(code)
    if meta is None:
        logger.warning("unknown_merchant_code", code=code)
        return None

    config = MerchantConfig(
        code=code,
        brand_name=meta["brand_name"],
        brand_id=meta["brand_id"],
    )
    _cache[code] = config
    return config


def get_all_merchants() -> list[MerchantConfig]:
    """获取所有已注册商户的配置列表

    Returns:
        所有商户的 MerchantConfig 列表（按注册顺序）
    """
    result: list[MerchantConfig] = []
    for code in MERCHANT_REGISTRY:
        config = get_merchant_config(code)
        if config is not None:
            result.append(config)
    return result


def get_store_pinzhi_token(merchant_code: str, store_id: str) -> str | None:
    """快捷方法：直接获取某商户某门店的品智 Token

    Args:
        merchant_code: 商户代码
        store_id: 品智门店 ID

    Returns:
        门店 Token 字符串，或 None
    """
    config = get_merchant_config(merchant_code)
    if config is None or config.pinzhi is None:
        return None
    return config.pinzhi.get_store_token(store_id)


def clear_cache() -> None:
    """清除缓存（用于测试或配置热更新）"""
    _cache.clear()
