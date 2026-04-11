"""通用兜底适配器 — 未对接城市的 Mock 模式实现。

所有领域均以日志记录方式运行，不实际调用任何外部平台。
方便新城市接入前的开发调试和数据格式验证。
"""

import uuid
from typing import Any

import structlog

from ..base_city_adapter import BaseCityAdapter, SubmissionResult
from ..base_domain_adapter import BaseDomainAdapter
from ..registry import CityAdapterRegistry

logger = structlog.get_logger(__name__)


class GenericDomainAdapter(BaseDomainAdapter):
    """通用领域适配器 — Mock 模式。

    所有操作仅记录日志，不调用真实平台 API。
    """

    def __init__(self, domain: str, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.domain = domain
        self.platform_name = f"通用Mock-{domain}"

    async def normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """直接返回原始数据，不做任何转换。"""
        logger.info(
            "generic_normalize",
            domain=self.domain,
            data_keys=list(data.keys()),
            payload=data,
        )
        return data

    async def submit(self, payload: dict[str, Any]) -> SubmissionResult:
        """Mock 模式 — 记录日志并返回模拟成功。"""
        mock_ref = f"MOCK-{uuid.uuid4().hex[:12].upper()}"

        logger.info(
            "generic_submit_mock",
            domain=self.domain,
            platform=self.platform_name,
            mock_ref=mock_ref,
            payload=payload,
        )

        return SubmissionResult(
            success=True,
            platform_ref=mock_ref,
            message="Mock模式: 数据已记录，未实际上报",
            raw_response={"mock": True, "ref": mock_ref},
        )

    async def pull(self, **filters: Any) -> list[dict[str, Any]]:
        """Mock 模式 — 返回空列表。"""
        logger.info(
            "generic_pull_mock",
            domain=self.domain,
            platform=self.platform_name,
            filters=filters,
        )
        return []

    async def health_check(self) -> bool:
        """Mock 模式始终返回健康。"""
        return True


@CityAdapterRegistry.register("000000")
class GenericCityAdapter(BaseCityAdapter):
    """通用兜底城市适配器。

    当请求的城市无专属适配器时，回退到此通用实现。
    所有领域均以 Mock 模式运行。
    """

    city_name: str = "通用"
    supported_domains: list[str] = ["trace", "kitchen", "env", "fire", "license"]

    def __init__(self, city_code: str, config: dict[str, Any]) -> None:
        super().__init__(city_code, config)
        logger.info(
            "generic_adapter_init",
            city_code=city_code,
            note="使用通用兜底适配器，所有领域为Mock模式",
        )

    def get_domain_adapter(self, domain: str) -> BaseDomainAdapter:
        """所有领域均返回 GenericDomainAdapter。"""
        return GenericDomainAdapter(domain=domain, config=self.config)
