"""城市适配器抽象基类 — 每个城市/省份一个实现。

每个城市适配器负责:
1. 声明该城市支持的监管领域(trace/kitchen/env/fire/license)
2. 将请求路由到对应领域的具体适配器
3. 提供统一的上报/拉取/健康检查接口
"""

from abc import ABC, abstractmethod
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class CivicPlatformError(Exception):
    """监管平台错误基类。"""

    def __init__(self, platform: str, code: int, message: str) -> None:
        self.platform = platform
        self.code = code
        self.message = message
        super().__init__(f"[{platform}] {code}: {message}")


class CivicPlatformTimeoutError(CivicPlatformError):
    """监管平台超时错误。"""

    pass


class CivicPlatformAuthError(CivicPlatformError):
    """监管平台认证错误。"""

    pass


class SubmissionResult:
    """上报结果。"""

    def __init__(
        self,
        success: bool,
        platform_ref: str = "",
        message: str = "",
        raw_response: dict[str, Any] | None = None,
    ) -> None:
        self.success = success
        self.platform_ref = platform_ref  # 平台返回的回执编号
        self.message = message
        self.raw_response = raw_response or {}

    def __repr__(self) -> str:
        return f"SubmissionResult(success={self.success}, platform_ref={self.platform_ref!r}, message={self.message!r})"


class BaseCityAdapter(ABC):
    """城市适配器基类。

    子类必须设置 city_code / city_name / supported_domains 并实现
    get_domain_adapter 方法。
    """

    city_code: str
    city_name: str
    supported_domains: list[str]  # trace / kitchen / env / fire / license

    def __init__(self, city_code: str, config: dict[str, Any]) -> None:
        self.city_code = city_code
        self.config = config

    # ------------------------------------------------------------------
    # 抽象方法
    # ------------------------------------------------------------------

    @abstractmethod
    def get_domain_adapter(self, domain: str) -> "BaseDomainAdapter":  # noqa: F821
        """获取某监管领域的具体适配器。"""
        ...

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def supports_domain(self, domain: str) -> bool:
        """判断该城市是否支持指定监管领域。"""
        return domain in self.supported_domains

    async def submit(self, domain: str, data: dict[str, Any]) -> SubmissionResult:
        """统一上报入口。"""
        if not self.supports_domain(domain):
            return SubmissionResult(
                success=False,
                message=f"城市{self.city_name}不支持{domain}领域对接",
            )

        adapter = self.get_domain_adapter(domain)
        try:
            normalized = await adapter.normalize(data)
            return await adapter.submit(normalized)
        except CivicPlatformError as e:
            logger.error(
                "civic_submit_failed",
                city=self.city_name,
                domain=domain,
                error=str(e),
            )
            return SubmissionResult(success=False, message=str(e))

    async def pull_updates(self, domain: str, **filters: Any) -> list[dict[str, Any]]:
        """从平台拉取更新（检查结果/通知等）。"""
        if not self.supports_domain(domain):
            return []

        adapter = self.get_domain_adapter(domain)
        return await adapter.pull(**filters)

    async def health_check(self) -> dict[str, bool]:
        """检查该城市所有平台的连通性。"""
        results: dict[str, bool] = {}
        for domain in self.supported_domains:
            try:
                adapter = self.get_domain_adapter(domain)
                results[domain] = await adapter.health_check()
            except (CivicPlatformError, ConnectionError, TimeoutError, OSError):
                results[domain] = False
        return results

    async def close(self) -> None:  # noqa: B027 - intentional default hook for optional override
        """释放资源，子类可覆盖。"""
        pass

    # ------------------------------------------------------------------
    # 异步上下文管理器
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "BaseCityAdapter":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
