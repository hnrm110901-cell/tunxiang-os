"""MultiProviderRouter -- 多模型统一路由层。

屯象OS 所有 AI 模型调用的核心路由。整合：
  1. 任务→Provider 路由策略（故障转移链）
  2. 多 Provider 独立熔断器
  3. DataSecurityGateway 数据安全集成
  4. 统一成本追踪（RMB 计价）
  5. ModelRouterCompat 向后兼容层

所有模型调用必须通过此模块，不直接调用 Provider API。

环境变量：
  REDIS_URL -- Redis 地址，熔断器状态共享（可选，降级为内存）

使用示例::

    router = MultiProviderRouter(adapters={...})
    resp = await router.complete(
        tenant_id="uuid",
        task_type="standard_analysis",
        messages=[{"role": "user", "content": "分析..."}],
    )
    print(resp.text, resp.cost_rmb)
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncGenerator, Optional

import structlog

from .registry import MODEL_REGISTRY, get_model_info
from .security import DataSecurityGateway, MaskContext
from .types import (
    DataSensitivity,
    LLMResponse,
    ModelTier,
    ProviderAdapter,
    ProviderHealth,
    ProviderName,
)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Route target type alias
# ---------------------------------------------------------------------------

RouteTarget = tuple[str, str]
"""(provider_name, model_id) -- 路由链中的一个目标。"""


# ---------------------------------------------------------------------------
# 1. 任务路由策略
# ---------------------------------------------------------------------------

# 每个任务类型定义一条有序故障转移链。
# 链中第一个可用且有权限的 Provider 被选中。
TASK_ROUTING: dict[str, list[RouteTarget]] = {
    "quick_classification": [
        ("deepseek", "deepseek-chat"),
        ("qwen", "qwen-turbo"),
        ("anthropic", "claude-haiku-4-5-20251001"),
    ],
    "standard_analysis": [
        ("qwen", "qwen-max"),
        ("deepseek", "deepseek-chat"),
        ("anthropic", "claude-sonnet-4-6"),
    ],
    "complex_reasoning": [
        ("deepseek", "deepseek-reasoner"),
        ("anthropic", "claude-opus-4-6"),
        ("qwen", "qwen-max"),
    ],
    "agent_decision": [
        ("anthropic", "claude-sonnet-4-6"),
        ("qwen", "qwen-max"),
        ("deepseek", "deepseek-chat"),
    ],
    "marketing_content": [
        ("qwen", "qwen-max"),
        ("deepseek", "deepseek-chat"),
        ("anthropic", "claude-sonnet-4-6"),
    ],
    "document_analysis": [
        ("qwen", "qwen-long"),
        ("kimi", "moonshot-v1-128k"),
        ("anthropic", "claude-sonnet-4-6"),
    ],
    "patrol_report": [
        ("deepseek", "deepseek-chat"),
        ("qwen", "qwen-turbo"),
        ("anthropic", "claude-haiku-4-5-20251001"),
    ],
    "dashboard_brief": [
        ("deepseek", "deepseek-chat"),
        ("qwen", "qwen-plus"),
        ("anthropic", "claude-sonnet-4-6"),
    ],
    "supplier_scoring": [
        ("qwen", "qwen-max"),
        ("deepseek", "deepseek-chat"),
        ("anthropic", "claude-sonnet-4-6"),
    ],
    "demand_forecast": [
        ("deepseek", "deepseek-chat"),
        ("qwen", "qwen-plus"),
        ("anthropic", "claude-sonnet-4-6"),
    ],
    "cost_analysis": [
        ("deepseek", "deepseek-chat"),
        ("qwen", "qwen-max"),
        ("anthropic", "claude-sonnet-4-6"),
    ],
    "default": [
        ("deepseek", "deepseek-chat"),
        ("qwen", "qwen-plus"),
        ("anthropic", "claude-sonnet-4-6"),
    ],
}

# urgency 覆盖规则
_FAST_MODELS: set[str] = {
    "qwen-turbo", "glm-4-flash", "ernie-speed-128k", "deepseek-chat",
    "claude-haiku-4-5-20251001",
}
_QUALITY_MODELS: set[str] = {"deepseek-reasoner", "claude-opus-4-6"}


class TaskRoutingStrategy:
    """根据任务类型 + urgency 解析故障转移链。"""

    def resolve_chain(
        self,
        task_type: str,
        urgency: str = "normal",
    ) -> list[RouteTarget]:
        """返回当前请求应尝试的 (provider, model) 有序列表。

        Args:
            task_type: 任务类型键，来自 TASK_ROUTING。
            urgency:   ``"fast"`` / ``"normal"`` / ``"quality"``。

        Returns:
            有序 RouteTarget 列表。第一个可用的将被选中。
        """
        chain = TASK_ROUTING.get(task_type, TASK_ROUTING["default"])

        if urgency == "fast":
            # 把链中 tier=LITE 的便宜模型排到最前面
            lite_first: list[RouteTarget] = []
            rest: list[RouteTarget] = []
            for provider_name, model_id in chain:
                info = MODEL_REGISTRY.get(model_id)
                if info and info.tier == ModelTier.LITE:
                    lite_first.append((provider_name, model_id))
                else:
                    rest.append((provider_name, model_id))
            # 如果路由链里没有 LITE，从全局找最便宜的
            if not lite_first:
                for mid, minfo in MODEL_REGISTRY.items():
                    if mid in _FAST_MODELS:
                        lite_first.append((minfo.provider.value, mid))
                        break
            return lite_first + rest

        if urgency == "quality":
            quality_first: list[RouteTarget] = []
            others: list[RouteTarget] = []
            for provider_name, model_id in chain:
                if model_id in _QUALITY_MODELS:
                    quality_first.append((provider_name, model_id))
                else:
                    others.append((provider_name, model_id))
            if not quality_first:
                quality_first.append(("deepseek", "deepseek-reasoner"))
            return quality_first + others

        return list(chain)


# ---------------------------------------------------------------------------
# 2. 多 Provider 熔断器
# ---------------------------------------------------------------------------

class CircuitState(str, Enum):
    """熔断器状态。"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """熔断器处于 OPEN 状态，请求被拒绝。"""


class ProviderCircuitBreaker:
    """单个 Provider 的熔断器（内存版，轻量级）。

    状态转换：
      CLOSED -> OPEN:       连续失败达到 failure_threshold
      OPEN -> HALF_OPEN:    经过 recovery_timeout_s 秒
      HALF_OPEN -> CLOSED:  一次成功
      HALF_OPEN -> OPEN:    一次失败
    """

    def __init__(
        self,
        provider_name: str,
        failure_threshold: int = 5,
        recovery_timeout_s: int = 30,
    ) -> None:
        self.provider_name = provider_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        """当前状态（纯读取，无副作用）。"""
        return self._state

    def tick(self) -> CircuitState:
        """检查超时并更新状态。"""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self.recovery_timeout_s:
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "circuit_half_open",
                    provider=self.provider_name,
                )
        return self._state

    @property
    def is_available(self) -> bool:
        """熔断器是否允许请求通过。"""
        return self.tick() != CircuitState.OPEN

    def record_success(self) -> None:
        """记录调用成功。"""
        if self._state == CircuitState.HALF_OPEN:
            logger.info("circuit_closed", provider=self.provider_name)
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = None

    def record_failure(self) -> None:
        """记录调用失败。"""
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.warning("circuit_reopened", provider=self.provider_name)
            return

        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.error(
                "circuit_opened",
                provider=self.provider_name,
                failure_count=self._failure_count,
            )


class CircuitBreakerRegistry:
    """管理所有 Provider 的熔断器实例。"""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_s: int = 30,
    ) -> None:
        self._breakers: dict[str, ProviderCircuitBreaker] = {}
        self._failure_threshold = failure_threshold
        self._recovery_timeout_s = recovery_timeout_s

    def get(self, provider_name: str) -> ProviderCircuitBreaker:
        """获取或创建指定 Provider 的熔断器。"""
        if provider_name not in self._breakers:
            self._breakers[provider_name] = ProviderCircuitBreaker(
                provider_name=provider_name,
                failure_threshold=self._failure_threshold,
                recovery_timeout_s=self._recovery_timeout_s,
            )
        return self._breakers[provider_name]

    def all_states(self) -> dict[str, CircuitState]:
        """返回所有已注册熔断器的状态。"""
        return {name: cb.state for name, cb in self._breakers.items()}


# ---------------------------------------------------------------------------
# 3. 成本计算工具
# ---------------------------------------------------------------------------

def _calculate_cost_rmb(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """计算单次调用成本（人民币元）。

    Args:
        model_id:      注册表中的模型 ID。
        input_tokens:  输入 token 数。
        output_tokens: 输出 token 数。

    Returns:
        成本（元），保留6位小数。
    """
    try:
        info = get_model_info(model_id)
    except KeyError:
        logger.warning("cost_unknown_model", model_id=model_id)
        return 0.0

    cost = (
        input_tokens / 1_000_000 * info.pricing.input_rmb_per_million
        + output_tokens / 1_000_000 * info.pricing.output_rmb_per_million
    )
    return round(cost, 6)


# ---------------------------------------------------------------------------
# 4. MultiProviderRouter
# ---------------------------------------------------------------------------

class AllProvidersExhaustedError(Exception):
    """故障转移链中所有 Provider 均不可用。"""


class MultiProviderRouter:
    """多模型统一路由层。

    整合任务路由、熔断器、数据安全网关和成本追踪。
    每个请求按故障转移链依次尝试，直到某个 Provider 成功。

    Args:
        adapters:           已初始化的 Provider 适配器映射。
        security_gateway:   DataSecurityGateway 实例（可选，None 则跳过安全检查）。
        routing_strategy:   TaskRoutingStrategy 实例（可选）。
        circuit_registry:   CircuitBreakerRegistry 实例（可选）。
        max_retries:        单 Provider 内部重试次数。
        retry_delays:       重试退避秒数列表。
    """

    DEFAULT_MAX_RETRIES = 2
    DEFAULT_RETRY_DELAYS = [1, 2]

    def __init__(
        self,
        adapters: dict[str, ProviderAdapter],
        *,
        security_gateway: DataSecurityGateway | None = None,
        routing_strategy: TaskRoutingStrategy | None = None,
        circuit_registry: CircuitBreakerRegistry | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delays: list[int] | None = None,
    ) -> None:
        self._adapters = adapters
        self._security = security_gateway
        self._strategy = routing_strategy or TaskRoutingStrategy()
        self._circuits = circuit_registry or CircuitBreakerRegistry()
        self._max_retries = max_retries
        self._retry_delays = retry_delays or self.DEFAULT_RETRY_DELAYS

    # ── 主入口：同步完成 ────────────────────────────────────────────────────

    async def complete(
        self,
        tenant_id: str,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        system: str | None = None,
        urgency: str = "normal",
        max_tokens: int = 1024,
        timeout_s: int = 30,
        request_id: str | None = None,
        db: Any = None,
        data_sensitivity: DataSensitivity | None = None,
    ) -> LLMResponse:
        """发起模型调用，沿故障转移链自动切换 Provider。

        Args:
            tenant_id:        租户 UUID。
            task_type:        任务类型，对应 TASK_ROUTING 键。
            messages:         消息列表 ``[{"role": "...", "content": "..."}]``。
            system:           系统 prompt（可选）。
            urgency:          ``"fast"`` / ``"normal"`` / ``"quality"``。
            max_tokens:       最大输出 token。
            timeout_s:        请求超时秒数。
            request_id:       幂等请求 ID（可选）。
            db:               AsyncSession，传入则写入 model_call_logs。
            data_sensitivity: 手动指定敏感级别（可选，不传则自动检测）。

        Returns:
            LLMResponse 包含文本、token 计数、成本等信息。

        Raises:
            AllProvidersExhaustedError: 链中所有 Provider 均失败。
        """
        req_id = request_id or str(uuid.uuid4())
        chain = self._strategy.resolve_chain(task_type, urgency)

        # -- 数据安全：脱敏 + 权限检测 --
        mask_ctx: MaskContext | None = None
        work_messages = messages
        if self._security is not None:
            work_messages, mask_ctx = self._security.mask_messages(messages, tenant_id)

        # 调用方手动指定敏感级别时，覆盖自动检测结果
        if data_sensitivity is not None and mask_ctx is not None:
            mask_ctx.sensitivity_level = data_sensitivity

        logger.info(
            "multi_router_start",
            tenant_id=tenant_id,
            task_type=task_type,
            urgency=urgency,
            request_id=req_id,
            chain=[(p, m) for p, m in chain],
            sensitivity=mask_ctx.sensitivity_level.value if mask_ctx else "unknown",
        )

        last_exc: Exception | None = None
        start_all = time.monotonic()

        for provider_name, model_id in chain:
            # 检查 adapter 是否存在
            adapter = self._adapters.get(provider_name)
            if adapter is None:
                logger.debug("provider_not_registered", provider=provider_name)
                continue

            # 检查熔断器
            breaker = self._circuits.get(provider_name)
            if not breaker.is_available:
                logger.info("provider_circuit_open", provider=provider_name)
                continue

            # 数据安全权限校验
            if self._security is not None and mask_ctx is not None:
                try:
                    self._security.check_provider_clearance(provider_name, mask_ctx)
                except PermissionError:
                    logger.info(
                        "provider_data_clearance_denied",
                        provider=provider_name,
                        sensitivity=mask_ctx.sensitivity_level.value,
                    )
                    continue

            # 尝试调用（含重试）
            try:
                response = await self._call_with_retry(
                    adapter=adapter,
                    model_id=model_id,
                    messages=work_messages,
                    system=system,
                    max_tokens=max_tokens,
                    timeout_s=timeout_s,
                    breaker=breaker,
                    req_id=req_id,
                )
            except (OSError, RuntimeError, TimeoutError) as exc:
                last_exc = exc
                logger.warning(
                    "provider_exhausted",
                    provider=provider_name,
                    model=model_id,
                    error=str(exc),
                    request_id=req_id,
                )
                continue

            # 成功 -- 后处理
            duration_ms = int((time.monotonic() - start_all) * 1000)
            cost_rmb = _calculate_cost_rmb(model_id, response.input_tokens, response.output_tokens)

            # 还原脱敏
            final_text = response.text
            if self._security is not None and mask_ctx is not None:
                final_text = self._security.unmask_text(response.text, mask_ctx)
                self._security.record_audit(mask_ctx, tenant_id, provider_name)

            result = LLMResponse(
                text=final_text,
                provider=ProviderName(provider_name),
                model_id=model_id,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_rmb=cost_rmb,
                duration_ms=duration_ms,
                request_id=req_id,
                finish_reason=response.finish_reason,
            )

            logger.info(
                "multi_router_success",
                tenant_id=tenant_id,
                provider=provider_name,
                model=model_id,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_rmb=cost_rmb,
                duration_ms=duration_ms,
                request_id=req_id,
            )

            # 异步写成本日志
            if db is not None:
                asyncio.create_task(
                    self._record_cost(
                        db=db,
                        tenant_id=tenant_id,
                        task_type=task_type,
                        provider=provider_name,
                        model=model_id,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        cost_rmb=cost_rmb,
                        duration_ms=duration_ms,
                        success=True,
                        error_type=None,
                        request_id=req_id,
                    )
                )

            return result

        # 所有 Provider 耗尽
        total_ms = int((time.monotonic() - start_all) * 1000)
        logger.error(
            "multi_router_all_exhausted",
            tenant_id=tenant_id,
            task_type=task_type,
            duration_ms=total_ms,
            request_id=req_id,
        )

        if db is not None:
            asyncio.create_task(
                self._record_cost(
                    db=db,
                    tenant_id=tenant_id,
                    task_type=task_type,
                    provider="none",
                    model="none",
                    input_tokens=0,
                    output_tokens=0,
                    cost_rmb=0.0,
                    duration_ms=total_ms,
                    success=False,
                    error_type="AllProvidersExhaustedError",
                    request_id=req_id,
                )
            )

        raise AllProvidersExhaustedError(
            f"故障转移链全部耗尽: task_type={task_type}, request_id={req_id}. "
            f"最后错误: {last_exc}"
        )

    # ── 流式完成 ────────────────────────────────────────────────────────────

    async def stream_complete(
        self,
        tenant_id: str,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        system: str | None = None,
        urgency: str = "normal",
        max_tokens: int = 1024,
        timeout_s: int = 30,
        request_id: str | None = None,
        data_sensitivity: DataSensitivity | None = None,
    ) -> AsyncGenerator[str, None]:
        """流式模型调用，沿故障转移链自动切换。

        与 ``complete`` 相同的路由和安全逻辑，但以流式方式输出文本。

        Yields:
            文本片段。
        """
        req_id = request_id or str(uuid.uuid4())
        chain = self._strategy.resolve_chain(task_type, urgency)

        mask_ctx: MaskContext | None = None
        work_messages = messages
        if self._security is not None:
            work_messages, mask_ctx = self._security.mask_messages(messages, tenant_id)

        last_exc: Exception | None = None

        for provider_name, model_id in chain:
            adapter = self._adapters.get(provider_name)
            if adapter is None:
                continue

            breaker = self._circuits.get(provider_name)
            if not breaker.is_available:
                continue

            if self._security is not None and mask_ctx is not None:
                try:
                    self._security.check_provider_clearance(provider_name, mask_ctx)
                except PermissionError:
                    continue

            try:
                gen = adapter.stream(
                    messages=work_messages,
                    model=model_id,
                    system=system,
                    max_tokens=max_tokens,
                )
                async for chunk in gen:
                    # 流式输出不做 unmask（令牌碎片无法还原）
                    yield chunk
                breaker.record_success()
                return
            except (OSError, RuntimeError, TimeoutError) as exc:
                breaker.record_failure()
                last_exc = exc
                logger.warning(
                    "stream_provider_failed",
                    provider=provider_name,
                    model=model_id,
                    error=str(exc),
                    request_id=req_id,
                )
                continue

        logger.error(
            "multi_router_stream_all_failed",
            tenant_id=tenant_id,
            task_type=task_type,
            request_id=req_id,
        )
        # 注意：AsyncGenerator 不能 raise，只能 return 结束迭代

    # ── 健康检查 ────────────────────────────────────────────────────────────

    async def health_check_all(self) -> dict[str, ProviderHealth]:
        """并行检查所有已注册 Provider 的健康状态。

        Returns:
            ``{provider_name: ProviderHealth}`` 映射。
        """
        tasks = {}
        for name, adapter in self._adapters.items():
            tasks[name] = asyncio.create_task(self._safe_health_check(name, adapter))

        results: dict[str, ProviderHealth] = {}
        for name, task in tasks.items():
            results[name] = await task
        return results

    # ── 内部方法 ────────────────────────────────────────────────────────────

    async def _call_with_retry(
        self,
        adapter: ProviderAdapter,
        model_id: str,
        messages: list[dict[str, str]],
        system: str | None,
        max_tokens: int,
        timeout_s: int,
        breaker: ProviderCircuitBreaker,
        req_id: str,
    ) -> LLMResponse:
        """带重试和熔断器的单 Provider 调用。

        Raises:
            最后一次调用的异常。
        """
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                delay = self._retry_delays[min(attempt - 1, len(self._retry_delays) - 1)]
                await asyncio.sleep(delay)

            try:
                response = await asyncio.wait_for(
                    adapter.complete(
                        messages=messages,
                        model=model_id,
                        system=system,
                        max_tokens=max_tokens,
                        timeout_s=timeout_s,
                    ),
                    timeout=timeout_s,
                )
                breaker.record_success()
                return response
            except asyncio.TimeoutError as exc:
                breaker.record_failure()
                last_exc = exc
                logger.warning(
                    "provider_timeout",
                    provider=adapter.name.value if hasattr(adapter.name, "value") else str(adapter.name),
                    model=model_id,
                    attempt=attempt + 1,
                    request_id=req_id,
                )
            except (OSError, RuntimeError, TimeoutError) as exc:
                breaker.record_failure()
                last_exc = exc
                logger.warning(
                    "provider_call_error",
                    provider=adapter.name.value if hasattr(adapter.name, "value") else str(adapter.name),
                    model=model_id,
                    attempt=attempt + 1,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    request_id=req_id,
                )

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Retry loop exited without exception or result")

    async def _safe_health_check(
        self, name: str, adapter: ProviderAdapter,
    ) -> ProviderHealth:
        """安全封装单个 Provider 的健康检查。"""
        try:
            return await adapter.health_check()
        except (OSError, RuntimeError, ValueError) as exc:
            return ProviderHealth(
                provider=ProviderName(name),
                is_available=False,
                last_error=str(exc),
            )

    async def _record_cost(
        self,
        db: Any,
        tenant_id: str,
        task_type: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_rmb: float,
        duration_ms: int,
        success: bool,
        error_type: str | None,
        request_id: str,
    ) -> None:
        """写入 model_call_logs 表。兼容旧表结构，新增 provider 字段。

        注意：成本记录失败不阻塞主业务。
        """
        from sqlalchemy import text

        # cost_usd 保留向后兼容（粗略转换，1 USD ~ 7.2 RMB）
        cost_usd = round(cost_rmb / 7.2, 6) if cost_rmb > 0 else 0.0

        sql = text("""
            INSERT INTO model_call_logs
                (id, tenant_id, task_type, model, provider,
                 input_tokens, output_tokens, cost_usd, cost_rmb,
                 duration_ms, success, error_type, request_id, created_at)
            VALUES
                (:id, :tenant_id, :task_type, :model, :provider,
                 :input_tokens, :output_tokens, :cost_usd, :cost_rmb,
                 :duration_ms, :success, :error_type, :request_id, :created_at)
            ON CONFLICT (request_id) DO NOTHING
        """)
        try:
            await db.execute(sql, {
                "id":            str(uuid.uuid4()),
                "tenant_id":     tenant_id,
                "task_type":     task_type,
                "model":         model,
                "provider":      provider,
                "input_tokens":  input_tokens,
                "output_tokens": output_tokens,
                "cost_usd":      cost_usd,
                "cost_rmb":      cost_rmb,
                "duration_ms":   duration_ms,
                "success":       success,
                "error_type":    error_type,
                "request_id":    request_id,
                "created_at":    datetime.now(timezone.utc),
            })
            await db.commit()
        except Exception as exc:  # noqa: BLE001 -- 成本记录失败不阻塞主业务
            logger.warning(
                "cost_record_failed",
                error=str(exc),
                tenant_id=tenant_id,
                request_id=request_id,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# 5. ModelRouterCompat -- 向后兼容旧 ModelRouter.complete() 签名
# ---------------------------------------------------------------------------

class ModelRouterCompat:
    """向后兼容层。

    签名与旧 ``ModelRouter.complete()`` 完全一致，返回 ``str``。
    内部委托给 ``MultiProviderRouter``，所有现有调用方无需修改。

    使用示例::

        # 替换旧代码 ``router = ModelRouter()``
        compat = ModelRouterCompat(multi_router)
        text = await compat.complete(tenant_id=..., task_type=..., messages=...)
    """

    def __init__(self, multi_router: MultiProviderRouter) -> None:
        self._router = multi_router

    async def complete(
        self,
        tenant_id: str,
        task_type: str,
        messages: list[dict[str, str]],
        system: str | None = None,
        urgency: str = "normal",
        max_tokens: int = 1024,
        timeout_s: int = 30,
        request_id: str | None = None,
        db: Any = None,
    ) -> str:
        """兼容旧接口，返回纯文本字符串。

        Args:
            参数列表与旧 ``ModelRouter.complete()`` 完全一致。

        Returns:
            模型生成的文本字符串。
        """
        response = await self._router.complete(
            tenant_id=tenant_id,
            task_type=task_type,
            messages=messages,
            system=system,
            urgency=urgency,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            request_id=request_id,
            db=db,
        )
        return response.text

    async def stream_complete(
        self,
        tenant_id: str,
        task_type: str,
        messages: list[dict[str, str]],
        system: str | None = None,
        urgency: str = "normal",
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        """兼容旧流式接口。

        Yields:
            文本片段。
        """
        async for chunk in self._router.stream_complete(
            tenant_id=tenant_id,
            task_type=task_type,
            messages=messages,
            system=system,
            urgency=urgency,
            max_tokens=max_tokens,
        ):
            yield chunk
