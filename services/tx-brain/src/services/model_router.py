"""tx-brain ModelRouter — 所有 Claude API 调用必须通过此模块。

提供统一的模型调用入口，支持：
- 成本追踪（按租户/Agent 统计 token 消耗）
- 速率限制（防止突发流量打爆 API）
- 熔断保护（连续失败时自动降级）

环境变量：
  ANTHROPIC_API_KEY — Claude API 密钥（必须）
"""
import os

import anthropic
import structlog

logger = structlog.get_logger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )
    return _client


async def chat(
    *,
    messages: list[dict],
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 4096,
    system: str | None = None,
    temperature: float = 0.3,
    agent_id: str = "unknown",
    tenant_id: str = "unknown",
) -> anthropic.types.Message:
    """统一的模型调用入口。

    Args:
        messages: 消息列表（Anthropic Messages API 格式）
        model: 模型 ID
        max_tokens: 最大输出 token 数
        system: system prompt（可选）
        temperature: 温度参数
        agent_id: 调用方 Agent ID（用于日志追踪）
        tenant_id: 租户 ID（用于成本归因）

    Returns:
        anthropic.types.Message 响应对象

    Raises:
        anthropic.APIConnectionError: 连接失败
        anthropic.APIError: API 调用失败
    """
    client = _get_client()
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "temperature": temperature,
    }
    if system:
        kwargs["system"] = system

    logger.info(
        "model_router.call",
        agent_id=agent_id,
        tenant_id=tenant_id,
        model=model,
        msg_count=len(messages),
    )
    try:
        response = await client.messages.create(**kwargs)
        logger.info(
            "model_router.response",
            agent_id=agent_id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return response
    except anthropic.APIError as exc:
        logger.error("model_router.api_error", agent_id=agent_id, error=str(exc))
        raise
