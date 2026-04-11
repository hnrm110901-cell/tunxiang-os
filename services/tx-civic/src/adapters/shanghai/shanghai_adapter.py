"""上海城市适配器 — 对接沪食安、上海明厨亮灶等平台。"""

from typing import Any

import structlog

from ..base_city_adapter import BaseCityAdapter
from ..base_domain_adapter import BaseDomainAdapter
from ..registry import CityAdapterRegistry
from .shanghai_kitchen import ShanghaiKitchenAdapter
from .shushian_trace import ShushianTraceAdapter

logger = structlog.get_logger(__name__)


class ShanghaiEnvAdapter(BaseDomainAdapter):
    """上海环保监管适配器 — 占位实现。"""

    domain: str = "env"
    platform_name: str = "上海环保监管平台"

    async def normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        logger.info("shanghai_env_normalize", data_keys=list(data.keys()))
        return data

    async def submit(self, payload: dict[str, Any]) -> "SubmissionResult":  # noqa: F821
        from ..base_city_adapter import SubmissionResult

        logger.info(
            "shanghai_env_submit_mock",
            platform=self.platform_name,
            payload=payload,
        )
        return SubmissionResult(
            success=True,
            message="Mock模式: 上海环保数据已记录",
        )

    async def pull(self, **filters: Any) -> list[dict[str, Any]]:
        logger.info("shanghai_env_pull_mock", filters=filters)
        return []


@CityAdapterRegistry.register("310000")
class ShanghaiCityAdapter(BaseCityAdapter):
    """上海城市适配器。

    支持领域:
    - trace: 沪食安追溯平台
    - kitchen: 上海明厨亮灶智慧监管平台
    - env: 上海环保监管平台
    """

    city_name: str = "上海"
    supported_domains: list[str] = ["trace", "kitchen", "env"]

    def __init__(self, city_code: str, config: dict[str, Any]) -> None:
        super().__init__(city_code, config)
        self._domain_adapters: dict[str, BaseDomainAdapter] = {}
        logger.info("shanghai_adapter_init", city_code=city_code)

    def get_domain_adapter(self, domain: str) -> BaseDomainAdapter:
        """获取上海对应领域的适配器实例（懒加载+缓存）。"""
        if domain not in self._domain_adapters:
            adapter_map: dict[str, type[BaseDomainAdapter]] = {
                "trace": ShushianTraceAdapter,
                "kitchen": ShanghaiKitchenAdapter,
                "env": ShanghaiEnvAdapter,
            }
            adapter_cls = adapter_map.get(domain)
            if adapter_cls is None:
                raise ValueError(f"上海不支持领域: {domain}")
            self._domain_adapters[domain] = adapter_cls(config=self.config)

        return self._domain_adapters[domain]
