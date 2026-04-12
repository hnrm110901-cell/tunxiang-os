"""屯象OS 多模型 Provider 抽象层。

支持 7 个模型提供商的统一接入：
- Anthropic Claude (Haiku/Sonnet/Opus)
- DeepSeek (V3/R1)
- 阿里云百炼 Qwen (Max/Plus/Turbo/Long)
- 智谱AI GLM (4-Plus/Flash)
- 百度千帆 ERNIE (4.5/Speed)
- 月之暗面 Kimi (k2)
- Core ML (门店边缘推理)
"""

from .config import ProviderConfig, get_enabled_providers, load_provider_configs
from .domain_enhance import (
    AGENT_PROMPTS,
    CATERING_GLOSSARY,
    FEW_SHOT_EXAMPLES,
    HARD_CONSTRAINTS_BLOCK,
    DomainEnhancer,
    FewShotExample,
)
from .registry import (
    MODEL_REGISTRY,
    get_cheapest_model,
    get_model_info,
    get_models_by_provider,
    get_models_by_tier,
)
from .router import (
    AllProvidersExhaustedError,
    CircuitBreakerRegistry,
    CircuitOpenError,
    ModelRouterCompat,
    MultiProviderRouter,
    TaskRoutingStrategy,
)
from .types import (
    DataSensitivity,
    LLMResponse,
    ModelInfo,
    ModelPricing,
    ModelTier,
    ProviderAdapter,
    ProviderHealth,
    ProviderName,
)

__all__ = [
    # types
    "ProviderName",
    "ModelTier",
    "DataSensitivity",
    "ModelPricing",
    "ModelInfo",
    "LLMResponse",
    "ProviderHealth",
    "ProviderAdapter",
    # registry
    "MODEL_REGISTRY",
    "get_model_info",
    "get_models_by_provider",
    "get_models_by_tier",
    "get_cheapest_model",
    # config
    "ProviderConfig",
    "load_provider_configs",
    "get_enabled_providers",
    # router
    "MultiProviderRouter",
    "ModelRouterCompat",
    "TaskRoutingStrategy",
    "CircuitBreakerRegistry",
    "CircuitOpenError",
    "AllProvidersExhaustedError",
    # domain_enhance
    "CATERING_GLOSSARY",
    "AGENT_PROMPTS",
    "FEW_SHOT_EXAMPLES",
    "HARD_CONSTRAINTS_BLOCK",
    "DomainEnhancer",
    "FewShotExample",
]
