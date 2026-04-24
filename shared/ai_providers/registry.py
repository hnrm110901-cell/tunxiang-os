"""全局模型注册表 -- 所有 Provider 的模型目录。

包含中国 Top 5 大模型 + Claude + Core ML 的完整定价和能力矩阵。
价格数据来源：各厂商 2025/2026 年公开定价页面。
"""

from .types import ModelInfo, ModelPricing, ModelTier, ProviderName

# 完整模型注册表
MODEL_REGISTRY: dict[str, ModelInfo] = {}


def _register(info: ModelInfo) -> None:
    MODEL_REGISTRY[info.model_id] = info


# -- Anthropic Claude -----------------------------------------------------
_register(
    ModelInfo(
        provider=ProviderName.ANTHROPIC,
        model_id="claude-haiku-4-5-20251001",
        display_name="Claude Haiku 4.5",
        tier=ModelTier.LITE,
        pricing=ModelPricing(input_rmb_per_million=5.6, output_rmb_per_million=28.0),
        max_context_tokens=200_000,
        max_output_tokens=8_192,
        supports_tools=True,
        supports_vision=True,
        data_region="overseas",
    )
)
_register(
    ModelInfo(
        provider=ProviderName.ANTHROPIC,
        model_id="claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6",
        tier=ModelTier.STANDARD,
        pricing=ModelPricing(input_rmb_per_million=21.0, output_rmb_per_million=105.0),
        max_context_tokens=200_000,
        max_output_tokens=16_384,
        supports_tools=True,
        supports_vision=True,
        data_region="overseas",
    )
)
_register(
    ModelInfo(
        provider=ProviderName.ANTHROPIC,
        model_id="claude-opus-4-6",
        display_name="Claude Opus 4.6",
        tier=ModelTier.PREMIUM,
        pricing=ModelPricing(input_rmb_per_million=105.0, output_rmb_per_million=525.0),
        max_context_tokens=200_000,
        max_output_tokens=32_768,
        supports_tools=True,
        supports_vision=True,
        data_region="overseas",
    )
)

# -- DeepSeek --------------------------------------------------------------
_register(
    ModelInfo(
        provider=ProviderName.DEEPSEEK,
        model_id="deepseek-chat",
        display_name="DeepSeek-V3",
        tier=ModelTier.STANDARD,
        pricing=ModelPricing(input_rmb_per_million=1.0, output_rmb_per_million=2.0),
        max_context_tokens=128_000,
        max_output_tokens=8_192,
        supports_tools=True,
        supports_vision=False,
        data_region="cn",
    )
)
_register(
    ModelInfo(
        provider=ProviderName.DEEPSEEK,
        model_id="deepseek-reasoner",
        display_name="DeepSeek-R1",
        tier=ModelTier.PREMIUM,
        pricing=ModelPricing(input_rmb_per_million=4.0, output_rmb_per_million=16.0),
        max_context_tokens=128_000,
        max_output_tokens=8_192,
        supports_tools=False,
        supports_vision=False,
        data_region="cn",
    )
)

# -- Qwen (阿里云百炼) ----------------------------------------------------
_register(
    ModelInfo(
        provider=ProviderName.QWEN,
        model_id="qwen-max",
        display_name="Qwen-Max",
        tier=ModelTier.STANDARD,
        pricing=ModelPricing(input_rmb_per_million=2.0, output_rmb_per_million=6.0),
        max_context_tokens=32_000,
        max_output_tokens=8_192,
        supports_tools=True,
        supports_vision=True,
        data_region="cn",
    )
)
_register(
    ModelInfo(
        provider=ProviderName.QWEN,
        model_id="qwen-plus",
        display_name="Qwen-Plus",
        tier=ModelTier.STANDARD,
        pricing=ModelPricing(input_rmb_per_million=0.8, output_rmb_per_million=2.0),
        max_context_tokens=131_072,
        max_output_tokens=8_192,
        supports_tools=True,
        supports_vision=True,
        data_region="cn",
    )
)
_register(
    ModelInfo(
        provider=ProviderName.QWEN,
        model_id="qwen-turbo",
        display_name="Qwen-Turbo",
        tier=ModelTier.LITE,
        pricing=ModelPricing(input_rmb_per_million=0.3, output_rmb_per_million=0.6),
        max_context_tokens=131_072,
        max_output_tokens=8_192,
        supports_tools=True,
        supports_vision=False,
        data_region="cn",
    )
)
_register(
    ModelInfo(
        provider=ProviderName.QWEN,
        model_id="qwen-long",
        display_name="Qwen-Long",
        tier=ModelTier.LONG_CTX,
        pricing=ModelPricing(input_rmb_per_million=0.5, output_rmb_per_million=2.0),
        max_context_tokens=1_000_000,
        max_output_tokens=8_192,
        supports_tools=False,
        supports_vision=False,
        data_region="cn",
    )
)

# -- GLM (智谱AI) ----------------------------------------------------------
_register(
    ModelInfo(
        provider=ProviderName.GLM,
        model_id="glm-4-plus",
        display_name="GLM-4-Plus",
        tier=ModelTier.STANDARD,
        pricing=ModelPricing(input_rmb_per_million=50.0, output_rmb_per_million=50.0),
        max_context_tokens=128_000,
        max_output_tokens=4_096,
        supports_tools=True,
        supports_vision=False,
        data_region="cn",
    )
)
_register(
    ModelInfo(
        provider=ProviderName.GLM,
        model_id="glm-4-flash",
        display_name="GLM-4-Flash",
        tier=ModelTier.LITE,
        pricing=ModelPricing(input_rmb_per_million=0.1, output_rmb_per_million=0.1),
        max_context_tokens=128_000,
        max_output_tokens=4_096,
        supports_tools=True,
        supports_vision=False,
        data_region="cn",
    )
)

# -- ERNIE (百度千帆) ------------------------------------------------------
_register(
    ModelInfo(
        provider=ProviderName.ERNIE,
        model_id="ernie-4.5-turbo-128k",
        display_name="ERNIE 4.5 Turbo",
        tier=ModelTier.STANDARD,
        pricing=ModelPricing(input_rmb_per_million=4.0, output_rmb_per_million=8.0),
        max_context_tokens=128_000,
        max_output_tokens=4_096,
        supports_tools=True,
        supports_vision=True,
        data_region="cn",
    )
)
_register(
    ModelInfo(
        provider=ProviderName.ERNIE,
        model_id="ernie-speed-128k",
        display_name="ERNIE Speed",
        tier=ModelTier.LITE,
        pricing=ModelPricing(input_rmb_per_million=0.0, output_rmb_per_million=0.0),  # 免费
        max_context_tokens=128_000,
        max_output_tokens=4_096,
        supports_tools=True,
        supports_vision=False,
        data_region="cn",
    )
)

# -- Kimi (月之暗面) -------------------------------------------------------
_register(
    ModelInfo(
        provider=ProviderName.KIMI,
        model_id="moonshot-v1-128k",
        display_name="Kimi k2 128K",
        tier=ModelTier.LONG_CTX,
        pricing=ModelPricing(input_rmb_per_million=60.0, output_rmb_per_million=60.0),
        max_context_tokens=128_000,
        max_output_tokens=8_192,
        supports_tools=True,
        supports_vision=False,
        data_region="cn",
    )
)
_register(
    ModelInfo(
        provider=ProviderName.KIMI,
        model_id="moonshot-v1-32k",
        display_name="Kimi k2 32K",
        tier=ModelTier.STANDARD,
        pricing=ModelPricing(input_rmb_per_million=24.0, output_rmb_per_million=24.0),
        max_context_tokens=32_000,
        max_output_tokens=8_192,
        supports_tools=True,
        supports_vision=False,
        data_region="cn",
    )
)

# -- Core ML (边缘) --------------------------------------------------------
_register(
    ModelInfo(
        provider=ProviderName.COREML,
        model_id="coreml-dish-time",
        display_name="出餐时间预测 (边缘)",
        tier=ModelTier.LITE,
        pricing=ModelPricing(input_rmb_per_million=0.0, output_rmb_per_million=0.0),
        max_context_tokens=4_096,
        max_output_tokens=512,
        supports_tools=False,
        supports_vision=False,
        data_region="cn",
    )
)
_register(
    ModelInfo(
        provider=ProviderName.COREML,
        model_id="coreml-discount-risk",
        display_name="折扣异常检测 (边缘)",
        tier=ModelTier.LITE,
        pricing=ModelPricing(input_rmb_per_million=0.0, output_rmb_per_million=0.0),
        max_context_tokens=4_096,
        max_output_tokens=512,
        supports_tools=False,
        supports_vision=False,
        data_region="cn",
    )
)


def get_model_info(model_id: str) -> ModelInfo:
    """按 model_id 查询模型信息。找不到时 raise KeyError。"""
    if model_id not in MODEL_REGISTRY:
        raise KeyError(f"未注册的模型: {model_id}. 可用模型: {list(MODEL_REGISTRY.keys())}")
    return MODEL_REGISTRY[model_id]


def get_models_by_provider(provider: ProviderName) -> list[ModelInfo]:
    """获取指定 Provider 的所有模型。"""
    return [m for m in MODEL_REGISTRY.values() if m.provider == provider]


def get_models_by_tier(tier: ModelTier) -> list[ModelInfo]:
    """获取指定档位的所有模型，按输入价格升序。"""
    models = [m for m in MODEL_REGISTRY.values() if m.tier == tier]
    return sorted(models, key=lambda m: m.pricing.input_rmb_per_million)


def get_cheapest_model(tier: ModelTier, require_tools: bool = False) -> ModelInfo:
    """获取指定档位中最便宜的模型。"""
    candidates = get_models_by_tier(tier)
    if require_tools:
        candidates = [m for m in candidates if m.supports_tools]
    if not candidates:
        raise KeyError(f"没有满足条件的模型: tier={tier}, require_tools={require_tools}")
    return candidates[0]  # 已按价格升序排列
