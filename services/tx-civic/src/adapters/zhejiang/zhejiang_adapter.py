"""浙江城市适配器 — 对接浙食链等平台。"""

from typing import Any

import structlog

from ..base_city_adapter import BaseCityAdapter
from ..base_domain_adapter import BaseDomainAdapter
from ..registry import CityAdapterRegistry
from .zheshilian_trace import ZheshilianTraceAdapter

logger = structlog.get_logger(__name__)


@CityAdapterRegistry.register("330000")
class ZhejiangCityAdapter(BaseCityAdapter):
    """浙江城市适配器。

    支持领域:
    - trace: 浙食链追溯平台
    """

    city_name: str = "浙江"
    supported_domains: list[str] = ["trace"]

    def __init__(self, city_code: str, config: dict[str, Any]) -> None:
        super().__init__(city_code, config)
        self._domain_adapters: dict[str, BaseDomainAdapter] = {}
        logger.info("zhejiang_adapter_init", city_code=city_code)

    def get_domain_adapter(self, domain: str) -> BaseDomainAdapter:
        """获取浙江对应领域的适配器实例。"""
        if domain not in self._domain_adapters:
            adapter_map: dict[str, type[BaseDomainAdapter]] = {
                "trace": ZheshilianTraceAdapter,
            }
            adapter_cls = adapter_map.get(domain)
            if adapter_cls is None:
                raise ValueError(f"浙江不支持领域: {domain}")
            self._domain_adapters[domain] = adapter_cls(config=self.config)

        return self._domain_adapters[domain]
