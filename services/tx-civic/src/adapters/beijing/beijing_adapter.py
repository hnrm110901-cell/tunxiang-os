"""北京城市适配器 — 对接阳光餐饮等平台。"""

from typing import Any

import structlog

from ..base_city_adapter import BaseCityAdapter
from ..base_domain_adapter import BaseDomainAdapter
from ..registry import CityAdapterRegistry
from .yangguang_kitchen import YangguangKitchenAdapter

logger = structlog.get_logger(__name__)


class BeijingTraceAdapter(BaseDomainAdapter):
    """北京食品追溯适配器 — 占位实现。"""

    domain: str = "trace"
    platform_name: str = "北京食品追溯平台"

    async def normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        logger.info("beijing_trace_normalize", data_keys=list(data.keys()))
        return data

    async def submit(self, payload: dict[str, Any]) -> "SubmissionResult":  # noqa: F821
        from ..base_city_adapter import SubmissionResult

        import uuid

        mock_ref = f"BJTRACE-{uuid.uuid4().hex[:12].upper()}"
        logger.info(
            "beijing_trace_submit_mock",
            platform=self.platform_name,
            mock_ref=mock_ref,
            payload=payload,
        )
        return SubmissionResult(
            success=True,
            platform_ref=mock_ref,
            message="Mock模式: 北京追溯数据已记录",
        )

    async def pull(self, **filters: Any) -> list[dict[str, Any]]:
        logger.info("beijing_trace_pull_mock", filters=filters)
        return []


@CityAdapterRegistry.register("110000")
class BeijingCityAdapter(BaseCityAdapter):
    """北京城市适配器。

    支持领域:
    - trace: 北京食品追溯平台
    - kitchen: 阳光餐饮平台
    """

    city_name: str = "北京"
    supported_domains: list[str] = ["trace", "kitchen"]

    def __init__(self, city_code: str, config: dict[str, Any]) -> None:
        super().__init__(city_code, config)
        self._domain_adapters: dict[str, BaseDomainAdapter] = {}
        logger.info("beijing_adapter_init", city_code=city_code)

    def get_domain_adapter(self, domain: str) -> BaseDomainAdapter:
        """获取北京对应领域的适配器实例。"""
        if domain not in self._domain_adapters:
            adapter_map: dict[str, type[BaseDomainAdapter]] = {
                "trace": BeijingTraceAdapter,
                "kitchen": YangguangKitchenAdapter,
            }
            adapter_cls = adapter_map.get(domain)
            if adapter_cls is None:
                raise ValueError(f"北京不支持领域: {domain}")
            self._domain_adapters[domain] = adapter_cls(config=self.config)

        return self._domain_adapters[domain]
