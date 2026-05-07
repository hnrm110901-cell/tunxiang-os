"""品智适配器工厂

根据商户代码和门店ID创建已配置好的 PinzhiAdapter 实例。
所有 token 通过环境变量加载，不硬编码。
"""

import os
from typing import Optional

import structlog

from .adapter import PinzhiAdapter
from .merchants import MERCHANT_CONFIG

logger = structlog.get_logger()


class PinzhiAdapterFactory:
    """品智适配器工厂，按商户/门店创建适配器实例"""

    @staticmethod
    def create_for_merchant(
        merchant_code: str,
        timeout: int = 30,
        retry_times: int = 3,
    ) -> PinzhiAdapter:
        """
        根据商户代码创建适配器（使用商户级 API token）

        Args:
            merchant_code: 商户代码（czyz / zqx / sgc）
            timeout: 请求超时秒数
            retry_times: 重试次数

        Returns:
            已配置的 PinzhiAdapter 实例

        Raises:
            ValueError: 商户代码不存在或 token 未配置
        """
        merchant = MERCHANT_CONFIG.get(merchant_code)
        if not merchant:
            valid_codes = ", ".join(MERCHANT_CONFIG.keys())
            raise ValueError(f"未知商户代码: {merchant_code}，可选值: {valid_codes}")

        token_env = merchant["api_token_env"]
        token = os.getenv(token_env)
        if not token:
            raise ValueError(f"商户 {merchant['brand_name']}({merchant_code}) 的 API token 环境变量 {token_env} 未设置")

        config = {
            "base_url": merchant["pinzhi_base_url"],
            "token": token,
            "timeout": timeout,
            "retry_times": retry_times,
        }

        logger.info(
            "创建商户级品智适配器",
            merchant_code=merchant_code,
            brand_name=merchant["brand_name"],
            base_url=merchant["pinzhi_base_url"],
        )
        return PinzhiAdapter(config)

    @staticmethod
    def create_for_store(
        merchant_code: str,
        store_id: str,
        timeout: int = 30,
        retry_times: int = 3,
    ) -> PinzhiAdapter:
        """
        根据商户代码和门店ID创建适配器（使用门店级 token）

        如果门店级 token 未配置，回退到商户级 API token。

        Args:
            merchant_code: 商户代码（czyz / zqx / sgc）
            store_id: 品智门店ID（如 "2461"）
            timeout: 请求超时秒数
            retry_times: 重试次数

        Returns:
            已配置的 PinzhiAdapter 实例

        Raises:
            ValueError: 商户代码/门店ID不存在或 token 未配置
        """
        merchant = MERCHANT_CONFIG.get(merchant_code)
        if not merchant:
            valid_codes = ", ".join(MERCHANT_CONFIG.keys())
            raise ValueError(f"未知商户代码: {merchant_code}，可选值: {valid_codes}")

        store = merchant["stores"].get(store_id)
        if not store:
            valid_stores = ", ".join(merchant["stores"].keys())
            raise ValueError(f"商户 {merchant['brand_name']} 下不存在门店 {store_id}，可选值: {valid_stores}")

        # 优先使用门店级 token，回退到商户级 token
        token = os.getenv(store["token_env"])
        token_source = f"门店级({store['token_env']})"
        if not token:
            token = os.getenv(merchant["api_token_env"])
            token_source = f"商户级({merchant['api_token_env']})"
        if not token:
            raise ValueError(
                f"门店 {store['name']}({store_id}) 的 token 未配置，"
                f"已尝试: {store['token_env']} 和 {merchant['api_token_env']}"
            )

        config = {
            "base_url": merchant["pinzhi_base_url"],
            "token": token,
            "timeout": timeout,
            "retry_times": retry_times,
        }

        logger.info(
            "创建门店级品智适配器",
            merchant_code=merchant_code,
            store_id=store_id,
            store_name=store["name"],
            token_source=token_source,
        )
        return PinzhiAdapter(config)

    @staticmethod
    def get_store_info(merchant_code: str, store_id: str) -> Optional[dict]:
        """
        获取门店的静态配置信息（不创建适配器，不需要 token）

        Args:
            merchant_code: 商户代码
            store_id: 门店ID

        Returns:
            门店配置字典（含 name, token_env, brand_name, base_url），
            不存在则返回 None
        """
        merchant = MERCHANT_CONFIG.get(merchant_code)
        if not merchant:
            return None

        store = merchant["stores"].get(store_id)
        if not store:
            return None

        return {
            "merchant_code": merchant_code,
            "brand_name": merchant["brand_name"],
            "base_url": merchant["pinzhi_base_url"],
            "store_id": store_id,
            "store_name": store["name"],
            "token_env": store["token_env"],
            "api_token_env": merchant["api_token_env"],
        }

    @staticmethod
    def list_merchants() -> list:
        """列出所有商户及其门店概要"""
        result = []
        for code, merchant in MERCHANT_CONFIG.items():
            result.append(
                {
                    "merchant_code": code,
                    "brand_name": merchant["brand_name"],
                    "base_url": merchant["pinzhi_base_url"],
                    "store_count": len(merchant["stores"]),
                    "store_ids": list(merchant["stores"].keys()),
                }
            )
        return result
