"""四川城市适配器 — 对接四川省食品追溯及明厨亮灶平台。"""

import uuid
from typing import Any

import structlog

from ..base_city_adapter import BaseCityAdapter, SubmissionResult
from ..base_domain_adapter import BaseDomainAdapter
from ..registry import CityAdapterRegistry

logger = structlog.get_logger(__name__)


class SichuanTraceAdapter(BaseDomainAdapter):
    """四川食品追溯适配器 — Mock 模式。"""

    domain: str = "trace"
    platform_name: str = "四川省食品追溯平台"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.platform_api_base = config.get("sichuan_trace_api_base", "")
        logger.info(
            "sichuan_trace_init",
            api_base=self.platform_api_base or "(未配置)",
        )

    async def normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "sichuan_trace_normalize",
            data_keys=list(data.keys()),
            payload=data,
        )
        return data

    async def submit(self, payload: dict[str, Any]) -> SubmissionResult:
        mock_ref = f"SCTRACE-{uuid.uuid4().hex[:12].upper()}"

        logger.info(
            "sichuan_trace_submit_mock",
            platform=self.platform_name,
            mock_ref=mock_ref,
            payload=payload,
        )

        return SubmissionResult(
            success=True,
            platform_ref=mock_ref,
            message="Mock模式: 四川追溯数据已记录",
            raw_response={"mock": True, "ref": mock_ref},
        )

    async def pull(self, **filters: Any) -> list[dict[str, Any]]:
        logger.info("sichuan_trace_pull_mock", filters=filters)
        return []


class SichuanKitchenAdapter(BaseDomainAdapter):
    """四川明厨亮灶适配器 — Mock 模式。"""

    domain: str = "kitchen"
    platform_name: str = "四川省明厨亮灶平台"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.platform_api_base = config.get("sichuan_kitchen_api_base", "")
        logger.info(
            "sichuan_kitchen_init",
            api_base=self.platform_api_base or "(未配置)",
        )

    async def normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "sichuan_kitchen_normalize",
            data_keys=list(data.keys()),
            payload=data,
        )
        return data

    async def submit(self, payload: dict[str, Any]) -> SubmissionResult:
        mock_ref = f"SCKITCHEN-{uuid.uuid4().hex[:12].upper()}"

        logger.info(
            "sichuan_kitchen_submit_mock",
            platform=self.platform_name,
            mock_ref=mock_ref,
            payload=payload,
        )

        return SubmissionResult(
            success=True,
            platform_ref=mock_ref,
            message="Mock模式: 四川明厨亮灶数据已记录",
            raw_response={"mock": True, "ref": mock_ref},
        )

    async def pull(self, **filters: Any) -> list[dict[str, Any]]:
        logger.info("sichuan_kitchen_pull_mock", filters=filters)
        return []


@CityAdapterRegistry.register("510000")
class SichuanCityAdapter(BaseCityAdapter):
    """四川城市适配器。

    支持领域:
    - trace: 四川省食品追溯平台
    - kitchen: 四川省明厨亮灶平台
    """

    city_name: str = "四川"
    supported_domains: list[str] = ["trace", "kitchen"]

    def __init__(self, city_code: str, config: dict[str, Any]) -> None:
        super().__init__(city_code, config)
        self._domain_adapters: dict[str, BaseDomainAdapter] = {}
        logger.info("sichuan_adapter_init", city_code=city_code)

    def get_domain_adapter(self, domain: str) -> BaseDomainAdapter:
        """获取四川对应领域的适配器实例。"""
        if domain not in self._domain_adapters:
            adapter_map: dict[str, type[BaseDomainAdapter]] = {
                "trace": SichuanTraceAdapter,
                "kitchen": SichuanKitchenAdapter,
            }
            adapter_cls = adapter_map.get(domain)
            if adapter_cls is None:
                raise ValueError(f"四川不支持领域: {domain}")
            self._domain_adapters[domain] = adapter_cls(config=self.config)

        return self._domain_adapters[domain]
