"""多 Provider 运行时配置。

从环境变量加载各 Provider 的 API 密钥和端点配置。
遵循屯象OS安全规范：禁止硬编码密钥。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .types import ProviderName


@dataclass(frozen=True)
class ProviderConfig:
    """单个 Provider 的配置。"""

    provider: ProviderName
    api_key: Optional[str]
    base_url: Optional[str] = None
    enabled: bool = True
    priority: int = 0  # 数字越小优先级越高
    timeout_s: int = 30
    max_retries: int = 3


def load_provider_configs() -> dict[ProviderName, ProviderConfig]:
    """从环境变量加载所有 Provider 配置。

    环境变量命名规范：
      {PROVIDER}_API_KEY     -- API 密钥
      {PROVIDER}_BASE_URL    -- 自定义端点（可选）
      {PROVIDER}_ENABLED     -- "true"/"false"，默认 true（有 key 时）
      {PROVIDER}_PRIORITY    -- 优先级数字，默认 0
    """
    configs: dict[ProviderName, ProviderConfig] = {}

    provider_env_map = {
        ProviderName.ANTHROPIC: "ANTHROPIC",
        ProviderName.DEEPSEEK: "DEEPSEEK",
        ProviderName.QWEN: "DASHSCOPE",  # 阿里云百炼 SDK 用 DASHSCOPE_API_KEY
        ProviderName.GLM: "ZHIPUAI",  # 智谱 SDK 用 ZHIPUAI_API_KEY
        ProviderName.ERNIE: "QIANFAN",  # 百度千帆 SDK 用 QIANFAN_API_KEY
        ProviderName.KIMI: "MOONSHOT",  # 月之暗面 SDK 用 MOONSHOT_API_KEY
        ProviderName.COREML: "COREML",
    }

    for provider, env_prefix in provider_env_map.items():
        api_key = os.environ.get(f"{env_prefix}_API_KEY")
        base_url = os.environ.get(f"{env_prefix}_BASE_URL")
        enabled_str = os.environ.get(f"{env_prefix}_ENABLED", "true" if api_key else "false")
        priority_str = os.environ.get(f"{env_prefix}_PRIORITY", "0")

        # Core ML 特殊处理：本地服务不需要 API Key
        if provider == ProviderName.COREML:
            base_url = base_url or "http://localhost:8100"
            enabled_str = os.environ.get("COREML_ENABLED", "true")

        configs[provider] = ProviderConfig(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            enabled=enabled_str.lower() == "true",
            priority=int(priority_str),
            timeout_s=int(os.environ.get(f"{env_prefix}_TIMEOUT_S", "30")),
            max_retries=int(os.environ.get(f"{env_prefix}_MAX_RETRIES", "3")),
        )

    return configs


def get_enabled_providers(
    configs: Optional[dict[ProviderName, ProviderConfig]] = None,
) -> list[ProviderConfig]:
    """获取所有已启用的 Provider，按 priority 升序排列。"""
    if configs is None:
        configs = load_provider_configs()
    enabled = [c for c in configs.values() if c.enabled]
    return sorted(enabled, key=lambda c: c.priority)
