"""多模型 Provider 核心类型定义。

屯象OS 支持 7 个模型提供商，所有调用通过统一 Protocol 抽象。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional, Protocol, runtime_checkable


class ProviderName(str, enum.Enum):
    """支持的模型提供商。"""
    ANTHROPIC = "anthropic"      # Claude (Haiku/Sonnet/Opus)
    DEEPSEEK  = "deepseek"       # DeepSeek-V3 / R1
    QWEN      = "qwen"           # 阿里云百炼 Qwen-Max/Plus/Turbo/Long
    GLM       = "glm"            # 智谱AI GLM-4-Plus/Flash
    ERNIE     = "ernie"          # 百度千帆 ERNIE-4.5/Speed
    KIMI      = "kimi"           # 月之暗面 Kimi-k2
    COREML    = "coreml"         # 门店边缘 Core ML


class ModelTier(str, enum.Enum):
    """模型性能档位，用于任务路由。"""
    LITE     = "lite"       # 最低成本：快速分类、意图识别
    STANDARD = "standard"   # 标准：分析、报表、常规Agent
    PREMIUM  = "premium"    # 高级：复杂推理、多步决策
    LONG_CTX = "long_ctx"   # 长上下文：文档分析、合同审查


class DataSensitivity(str, enum.Enum):
    """数据敏感级别，决定哪些 Provider 可以处理。"""
    PUBLIC     = "public"       # 公开信息，任何 Provider 可处理
    INTERNAL   = "internal"     # 内部数据，仅境内 Provider
    SENSITIVE  = "sensitive"    # 敏感数据（PII等），境内 + 脱敏后
    RESTRICTED = "restricted"   # 受限数据，仅本地 Core ML


@dataclass
class ModelPricing:
    """模型定价信息（每百万 token）。"""
    input_rmb_per_million: float    # 输入价格（¥/百万token）
    output_rmb_per_million: float   # 输出价格（¥/百万token）
    currency: str = "CNY"


@dataclass
class ModelInfo:
    """模型元信息。"""
    provider: ProviderName
    model_id: str                   # API 调用用的模型标识符
    display_name: str               # 显示名称
    tier: ModelTier
    pricing: ModelPricing
    max_context_tokens: int         # 最大上下文长度
    max_output_tokens: int          # 最大输出长度
    supports_tools: bool = False    # 是否支持 function calling
    supports_vision: bool = False   # 是否支持图片输入
    supports_streaming: bool = True
    data_region: str = "cn"         # "cn" = 境内, "overseas" = 境外


@dataclass
class LLMResponse:
    """统一的模型响应格式。"""
    text: str
    provider: ProviderName
    model_id: str
    input_tokens: int
    output_tokens: int
    cost_rmb: float               # 本次调用成本（¥）
    duration_ms: int
    request_id: str
    raw_response: Optional[Any] = None  # 原始 SDK 响应（调试用）
    finish_reason: str = "stop"


@dataclass
class ProviderHealth:
    """Provider 健康状态。"""
    provider: ProviderName
    is_available: bool
    latency_ms: Optional[int] = None
    error_rate: float = 0.0         # 最近 N 次调用的错误率
    last_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_error: Optional[str] = None


@runtime_checkable
class ProviderAdapter(Protocol):
    """模型提供商适配器 Protocol。

    所有 Provider（Anthropic/DeepSeek/Qwen/GLM 等）必须实现此接口。
    """

    @property
    def name(self) -> ProviderName:
        """提供商标识。"""
        ...

    @property
    def available_models(self) -> list[ModelInfo]:
        """该 Provider 支持的所有模型。"""
        ...

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout_s: int = 30,
        tools: Optional[list[dict]] = None,
    ) -> LLMResponse:
        """同步调用模型，返回完整响应。"""
        ...

    async def stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        tools: Optional[list[dict]] = None,
    ) -> AsyncGenerator[str, None]:
        """流式调用模型，逐 chunk 返回。"""
        ...

    async def health_check(self) -> ProviderHealth:
        """检查 Provider 连通性。"""
        ...

    def get_pricing(self, model: str) -> ModelPricing:
        """获取指定模型的定价。"""
        ...
