"""领域适配器抽象基类 — 某城市某监管领域的具体对接。

每个领域适配器负责:
1. 将屯象统一数据模型转换(normalize)为目标平台格式
2. 提交(submit)数据到目标平台
3. 从平台拉取(pull)检查结果/通知等
"""

from abc import ABC, abstractmethod
from typing import Any

import structlog

from .base_city_adapter import SubmissionResult

logger = structlog.get_logger(__name__)


class BaseDomainAdapter(ABC):
    """领域适配器抽象基类。

    子类必须设置 domain / platform_name 并实现
    normalize / submit / pull 三个核心方法。
    """

    domain: str  # trace / kitchen / env / fire / license
    platform_name: str  # 目标平台名称
    platform_api_base: str = ""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # 抽象方法
    # ------------------------------------------------------------------

    @abstractmethod
    async def normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """将屯象统一模型转换为该平台的数据格式。"""
        ...

    @abstractmethod
    async def submit(self, payload: dict[str, Any]) -> SubmissionResult:
        """提交数据到平台。"""
        ...

    @abstractmethod
    async def pull(self, **filters: Any) -> list[dict[str, Any]]:
        """从平台拉取数据。"""
        ...

    # ------------------------------------------------------------------
    # 可选覆盖
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """平台可用性检查，子类可覆盖。"""
        return True

    async def validate_credentials(self) -> bool:
        """校验平台凭证有效性，子类可覆盖。"""
        return True
