"""ModelRouter — 所有 AI 模型调用的统一路由层

所有 Claude API 调用必须通过此模块，不直接调用 API。

模块职责：
  1. ModelSelectionStrategy  — 按任务类型 + 紧急程度选择最优模型
  2. CostTracker             — 精确计算并记录每次调用成本
  3. CircuitBreaker          — 防止 Claude API 故障级联
  4. ModelRouter             — 统一调用入口（重试 + 超时 + 熔断 + 成本追踪）

环境变量：
  ANTHROPIC_API_KEY   — Claude API 密钥（必须）
  REDIS_URL           — Redis 地址，默认 redis://localhost:6379
                        不可用时熔断器降级为内存状态

使用方式：
  router = ModelRouter()
  response = await router.complete(
      tenant_id="uuid",
      task_type="standard_analysis",
      messages=[{"role": "user", "content": "分析这份数据..."}],
      db=db_session,          # 可选，传入则记录成本
  )
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional

import structlog
from anthropic import AsyncAnthropic, APIConnectionError, APIStatusError, APITimeoutError

logger = structlog.get_logger()

# ─────────────────────────────────────────────────────────────────────────────
# 1. 模型选择策略
# ─────────────────────────────────────────────────────────────────────────────

class ModelSelectionStrategy:
    """根据任务类型和成本/速度权衡选择最优模型。

    urgency 参数影响模型选择：
      "fast"    — 降级到 haiku（低成本/高速度）
      "quality" — 升级到 opus（高质量/高成本）
      "normal"  — 使用 TASK_MODEL_MAP 默认映射
    """

    # 任务类型 → 默认模型映射
    TASK_MODEL_MAP: dict[str, str] = {
        "quick_classification": "claude-haiku-4-5-20251001",
        "standard_analysis":    "claude-sonnet-4-6",
        "complex_reasoning":    "claude-opus-4-6",
        "agent_decision":       "claude-sonnet-4-6",
        "supplier_scoring":     "claude-sonnet-4-6",
        "demand_forecast":      "claude-sonnet-4-6",
        "cost_analysis":        "claude-sonnet-4-6",
        "patrol_report":        "claude-haiku-4-5-20251001",
        "dashboard_brief":      "claude-sonnet-4-6",
        "default":              "claude-sonnet-4-6",
    }

    # 紧急程度升/降级规则
    _DOWNGRADE_MODEL = "claude-haiku-4-5-20251001"
    _UPGRADE_MODEL   = "claude-opus-4-6"

    def select_model(self, task_type: str, urgency: str = "normal") -> str:
        """选择模型。

        Args:
            task_type: 任务类型，见 TASK_MODEL_MAP
            urgency:   "fast" | "normal" | "quality"

        Returns:
            模型 ID 字符串
        """
        if urgency == "fast":
            return self._DOWNGRADE_MODEL

        if urgency == "quality":
            return self._UPGRADE_MODEL

        return self.TASK_MODEL_MAP.get(task_type, self.TASK_MODEL_MAP["default"])


# ─────────────────────────────────────────────────────────────────────────────
# 2. 成本追踪
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ModelCallRecord:
    """单次模型调用记录"""
    tenant_id:   str
    task_type:   str
    model:       str
    input_tokens:  int
    output_tokens: int
    cost_usd:    float
    duration_ms: int
    success:     bool
    error_type:  Optional[str]
    created_at:  datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    request_id:  Optional[str] = None


class CostTracker:
    """按官方价格精确计算并持久化调用成本。

    价格单位：USD per 1M tokens（2025 Claude API 官方定价）
    """

    # 2025 年 Claude API 定价（USD / 1M tokens）
    PRICING: dict[str, dict[str, float]] = {
        "claude-haiku-4-5-20251001": {"input": 0.80,  "output": 4.00},
        "claude-sonnet-4-6":         {"input": 3.00,  "output": 15.00},
        "claude-opus-4-6":           {"input": 15.00, "output": 75.00},
    }

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """计算调用成本（USD）。

        未知模型按 sonnet 价格计算，并记录 warning。
        """
        pricing = self.PRICING.get(model)
        if not pricing:
            logger.warning("unknown_model_pricing", model=model)
            pricing = self.PRICING["claude-sonnet-4-6"]

        cost = (
            input_tokens  / 1_000_000 * pricing["input"] +
            output_tokens / 1_000_000 * pricing["output"]
        )
        return round(cost, 6)

    async def record_call(self, record: ModelCallRecord, db: Any) -> None:
        """将调用记录写入 model_call_logs 表。

        Args:
            record: ModelCallRecord 数据
            db:     SQLAlchemy AsyncSession
        """
        from sqlalchemy import text

        sql = text("""
            INSERT INTO model_call_logs
                (id, tenant_id, task_type, model,
                 input_tokens, output_tokens, cost_usd,
                 duration_ms, success, error_type, request_id, created_at)
            VALUES
                (:id, :tenant_id, :task_type, :model,
                 :input_tokens, :output_tokens, :cost_usd,
                 :duration_ms, :success, :error_type, :request_id, :created_at)
            ON CONFLICT (request_id) DO NOTHING
        """)
        try:
            await db.execute(sql, {
                "id":            str(uuid.uuid4()),
                "tenant_id":     record.tenant_id,
                "task_type":     record.task_type,
                "model":         record.model,
                "input_tokens":  record.input_tokens,
                "output_tokens": record.output_tokens,
                "cost_usd":      record.cost_usd,
                "duration_ms":   record.duration_ms,
                "success":       record.success,
                "error_type":    record.error_type,
                "request_id":    record.request_id,
                "created_at":    record.created_at,
            })
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — 成本记录失败不阻塞主业务
            logger.warning("cost_record_failed", error=str(exc), tenant_id=record.tenant_id, exc_info=True)

    async def get_tenant_usage(
        self,
        tenant_id: str,
        start_date: date,
        end_date: date,
        db: Any,
    ) -> dict:
        """返回租户在时间段内的 token 使用量和成本聚合。

        Returns:
            {
              "tenant_id": str,
              "start_date": str,
              "end_date": str,
              "total_input_tokens": int,
              "total_output_tokens": int,
              "total_cost_usd": float,
              "call_count": int,
              "success_count": int,
              "by_model": [{"model": str, "call_count": int, "cost_usd": float}]
            }
        """
        from sqlalchemy import text

        aggregate_sql = text("""
            SELECT
                COUNT(*)                    AS call_count,
                SUM(CASE WHEN success THEN 1 ELSE 0 END) AS success_count,
                COALESCE(SUM(input_tokens), 0)  AS total_input_tokens,
                COALESCE(SUM(output_tokens), 0) AS total_output_tokens,
                COALESCE(SUM(cost_usd), 0)      AS total_cost_usd
            FROM model_call_logs
            WHERE tenant_id = :tenant_id
              AND created_at >= :start_dt
              AND created_at <  :end_dt
        """)

        by_model_sql = text("""
            SELECT
                model,
                COUNT(*)          AS call_count,
                SUM(cost_usd)     AS cost_usd
            FROM model_call_logs
            WHERE tenant_id = :tenant_id
              AND created_at >= :start_dt
              AND created_at <  :end_dt
            GROUP BY model
            ORDER BY cost_usd DESC
        """)

        params = {
            "tenant_id": tenant_id,
            "start_dt":  datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc),
            "end_dt":    datetime.combine(end_date,   datetime.min.time()).replace(tzinfo=timezone.utc),
        }

        try:
            agg_row   = (await db.execute(aggregate_sql, params)).mappings().one()
            model_rows = (await db.execute(by_model_sql, params)).mappings().all()
        except Exception as exc:  # noqa: BLE001 — DB查询失败降级返回空统计
            logger.error("get_tenant_usage_failed", error=str(exc), tenant_id=tenant_id, exc_info=True)
            return {
                "tenant_id": tenant_id,
                "start_date": str(start_date),
                "end_date":   str(end_date),
                "total_input_tokens":  0,
                "total_output_tokens": 0,
                "total_cost_usd":      0.0,
                "call_count":          0,
                "success_count":       0,
                "by_model":            [],
            }

        return {
            "tenant_id":             tenant_id,
            "start_date":            str(start_date),
            "end_date":              str(end_date),
            "total_input_tokens":    int(agg_row["total_input_tokens"]),
            "total_output_tokens":   int(agg_row["total_output_tokens"]),
            "total_cost_usd":        float(agg_row["total_cost_usd"]),
            "call_count":            int(agg_row["call_count"]),
            "success_count":         int(agg_row["success_count"]),
            "by_model": [
                {
                    "model":      row["model"],
                    "call_count": int(row["call_count"]),
                    "cost_usd":   float(row["cost_usd"]),
                }
                for row in model_rows
            ],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 3. 熔断器
# ─────────────────────────────────────────────────────────────────────────────

class CircuitState(str, Enum):
    CLOSED    = "closed"     # 正常
    OPEN      = "open"       # 熔断中
    HALF_OPEN = "half_open"  # 探测中


class CircuitOpenError(Exception):
    """熔断器处于 OPEN 状态时抛出，不再发起 API 调用。"""


class CircuitBreaker:
    """防止 Claude API 故障级联的熔断器。

    状态转换规则：
      CLOSED → OPEN       连续失败达到 failure_threshold（默认 5）次
      OPEN   → HALF_OPEN  经过 recovery_timeout_s（默认 30）秒
      HALF_OPEN → CLOSED  1 次成功
      HALF_OPEN → OPEN    1 次失败

    Redis 可用时跨进程共享状态；Redis 不可用时降级到内存状态。
    """

    _REDIS_KEY_PREFIX = "circuit_breaker:"

    def __init__(
        self,
        name: str = "claude_api",
        failure_threshold: int = 5,
        recovery_timeout_s: int = 30,
        redis_url: Optional[str] = None,
    ) -> None:
        self.name               = name
        self.failure_threshold  = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self._redis_url         = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")

        # 内存状态（Redis 不可用时使用）
        self._state:          CircuitState = CircuitState.CLOSED
        self._failure_count:  int          = 0
        self._opened_at:      Optional[float] = None

        # Redis 客户端（懒加载）
        self._redis: Any = None
        self._redis_available: bool = True  # 首次尝试前假设可用

    # ── Redis 状态操作 ──────────────────────────────────────────────────────

    async def _get_redis(self) -> Any:
        """懒加载 Redis 客户端，失败则标记不可用。"""
        if not self._redis_available:
            return None
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
                await self._redis.ping()
            except Exception as exc:  # noqa: BLE001 — Redis连接失败降级为内存状态
                logger.warning("circuit_breaker_redis_unavailable", reason=str(exc), exc_info=True)
                self._redis = None
                self._redis_available = False
        return self._redis

    def _redis_key(self, field: str) -> str:
        return f"{self._REDIS_KEY_PREFIX}{self.name}:{field}"

    async def _load_state(self) -> tuple[CircuitState, int, Optional[float]]:
        """从 Redis 加载状态；失败时返回内存状态。"""
        redis = await self._get_redis()
        if redis is None:
            return self._state, self._failure_count, self._opened_at

        try:
            pipe = redis.pipeline()
            pipe.get(self._redis_key("state"))
            pipe.get(self._redis_key("failure_count"))
            pipe.get(self._redis_key("opened_at"))
            results = await pipe.execute()

            state_val = results[0]
            failure_val = results[1]
            opened_val = results[2]

            state = CircuitState(state_val) if state_val else CircuitState.CLOSED
            failure_count = int(failure_val) if failure_val else 0
            opened_at = float(opened_val) if opened_val else None
            return state, failure_count, opened_at
        except Exception as exc:  # noqa: BLE001 — Redis读取失败降级为内存状态
            logger.warning("circuit_breaker_redis_read_failed", reason=str(exc), exc_info=True)
            return self._state, self._failure_count, self._opened_at

    async def _save_state(
        self,
        state: CircuitState,
        failure_count: int,
        opened_at: Optional[float],
    ) -> None:
        """持久化状态到 Redis；失败时仅更新内存。"""
        # 始终更新内存状态
        self._state = state
        self._failure_count = failure_count
        self._opened_at = opened_at

        redis = await self._get_redis()
        if redis is None:
            return

        try:
            pipe = redis.pipeline()
            pipe.set(self._redis_key("state"),         state.value)
            pipe.set(self._redis_key("failure_count"), str(failure_count))
            if opened_at is not None:
                pipe.set(self._redis_key("opened_at"), str(opened_at))
            else:
                pipe.delete(self._redis_key("opened_at"))
            await pipe.execute()
        except Exception as exc:  # noqa: BLE001 — Redis写入失败仅影响跨进程共享，内存状态已更新
            logger.warning("circuit_breaker_redis_write_failed", reason=str(exc), exc_info=True)

    # ── 核心状态机 ──────────────────────────────────────────────────────────

    async def get_state(self) -> CircuitState:
        """获取当前状态，自动处理 OPEN → HALF_OPEN 的时间转换。"""
        state, failure_count, opened_at = await self._load_state()

        if state == CircuitState.OPEN and opened_at is not None:
            elapsed = time.monotonic() - opened_at
            if elapsed >= self.recovery_timeout_s:
                # 超时，进入探测状态
                await self._save_state(CircuitState.HALF_OPEN, failure_count, opened_at)
                logger.info(
                    "circuit_breaker_half_open",
                    name=self.name,
                    elapsed_s=round(elapsed, 1),
                )
                return CircuitState.HALF_OPEN

        return state

    async def record_success(self) -> None:
        """记录成功：HALF_OPEN → CLOSED；CLOSED 时重置计数。"""
        state, _, opened_at = await self._load_state()

        if state in (CircuitState.HALF_OPEN, CircuitState.CLOSED):
            await self._save_state(CircuitState.CLOSED, 0, None)
            if state == CircuitState.HALF_OPEN:
                logger.info("circuit_breaker_closed", name=self.name)

    async def record_failure(self) -> None:
        """记录失败。CLOSED 时累加计数；达阈值则 OPEN；HALF_OPEN 直接 OPEN。"""
        state, failure_count, _ = await self._load_state()

        if state == CircuitState.HALF_OPEN:
            opened_at = time.monotonic()
            await self._save_state(CircuitState.OPEN, failure_count, opened_at)
            logger.warning("circuit_breaker_reopened", name=self.name)
            return

        new_count = failure_count + 1
        if new_count >= self.failure_threshold:
            opened_at = time.monotonic()
            await self._save_state(CircuitState.OPEN, new_count, opened_at)
            logger.error(
                "circuit_breaker_opened",
                name=self.name,
                failure_count=new_count,
                threshold=self.failure_threshold,
            )
        else:
            await self._save_state(CircuitState.CLOSED, new_count, None)

    async def call(self, coro: Any) -> Any:
        """通过熔断器执行协程。

        Args:
            coro: 待执行的协程

        Raises:
            CircuitOpenError: 熔断器处于 OPEN 状态
            任何来自 coro 的异常（同时记录失败）
        """
        current_state = await self.get_state()

        if current_state == CircuitState.OPEN:
            logger.warning("circuit_breaker_rejected", name=self.name)
            raise CircuitOpenError(f"Circuit breaker '{self.name}' is OPEN. Request rejected.")

        try:
            result = await coro
            await self.record_success()
            return result
        except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
            await self.record_failure()
            raise
        except CircuitOpenError:
            raise
        except Exception as exc:  # noqa: BLE001 — 其他异常不计入熔断计数，直接透传
            raise


# ─────────────────────────────────────────────────────────────────────────────
# 4. ModelRouter — 统一路由入口
# ─────────────────────────────────────────────────────────────────────────────

class ModelRouter:
    """所有 Claude API 调用的统一路由层。

    特性：
      - 自动重试（最多 3 次，指数退避 1s / 2s / 4s）
      - 超时控制（默认 30 秒）
      - 熔断器保护（5 次连续失败触发熔断）
      - 成本自动追踪（需传入 db session）
      - 结构化日志（structlog）

    使用示例：
        router = ModelRouter()
        text = await router.complete(
            tenant_id="...",
            task_type="standard_analysis",
            messages=[{"role": "user", "content": "分析这份报告..."}],
        )
    """

    MAX_RETRIES    = 3
    RETRY_DELAYS   = [1, 2, 4]   # 秒，指数退避
    DEFAULT_TIMEOUT_S = 30

    def __init__(
        self,
        api_key: Optional[str] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        cost_tracker: Optional[CostTracker] = None,
        model_strategy: Optional[ModelSelectionStrategy] = None,
    ) -> None:
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError("ANTHROPIC_API_KEY 环境变量未设置")

        self._client         = AsyncAnthropic(api_key=resolved_key)
        self._circuit        = circuit_breaker or CircuitBreaker()
        self._cost_tracker   = cost_tracker or CostTracker()
        self._strategy       = model_strategy or ModelSelectionStrategy()

    async def complete(
        self,
        tenant_id:     str,
        task_type:     str,
        messages:      list[dict[str, str]],
        system:        Optional[str] = None,
        urgency:       str = "normal",
        max_tokens:    int = 1024,
        timeout_s:     int = DEFAULT_TIMEOUT_S,
        request_id:    Optional[str] = None,
        db:            Any = None,
    ) -> str:
        """发起 Claude API 调用，返回模型生成的文本。

        Args:
            tenant_id:  租户 UUID（用于成本追踪）
            task_type:  任务类型，见 ModelSelectionStrategy.TASK_MODEL_MAP
            messages:   对话消息列表，格式同 Anthropic SDK
            system:     系统 prompt（可选）
            urgency:    "fast" | "normal" | "quality"
            max_tokens: 最大输出 token 数
            timeout_s:  请求超时秒数
            request_id: 幂等请求 ID（可选，用于去重）
            db:         AsyncSession，传入则记录成本到 model_call_logs

        Returns:
            模型生成的文本字符串

        Raises:
            CircuitOpenError:   熔断器 OPEN，请求被拒绝
            APIConnectionError: 连接失败（重试后仍失败）
            APITimeoutError:    超时（重试后仍超时）
            APIStatusError:     API 返回错误状态码
        """
        model = self._strategy.select_model(task_type, urgency)
        req_id = request_id or str(uuid.uuid4())

        logger.info(
            "model_router_call_start",
            tenant_id=tenant_id,
            task_type=task_type,
            model=model,
            urgency=urgency,
            request_id=req_id,
        )

        last_exc: Optional[Exception] = None
        start_ms = time.monotonic()

        for attempt in range(self.MAX_RETRIES):
            if attempt > 0:
                delay = self.RETRY_DELAYS[attempt - 1]
                logger.info(
                    "model_router_retry",
                    attempt=attempt + 1,
                    delay_s=delay,
                    model=model,
                    request_id=req_id,
                )
                await asyncio.sleep(delay)

            try:
                response = await self._circuit.call(
                    self._call_api(
                        model=model,
                        messages=messages,
                        system=system,
                        max_tokens=max_tokens,
                        timeout_s=timeout_s,
                    )
                )

                duration_ms = int((time.monotonic() - start_ms) * 1000)
                input_tokens  = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                cost_usd = self._cost_tracker.calculate_cost(model, input_tokens, output_tokens)

                logger.info(
                    "model_router_call_success",
                    tenant_id=tenant_id,
                    task_type=task_type,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    duration_ms=duration_ms,
                    request_id=req_id,
                )

                if db is not None:
                    record = ModelCallRecord(
                        tenant_id=tenant_id,
                        task_type=task_type,
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=cost_usd,
                        duration_ms=duration_ms,
                        success=True,
                        error_type=None,
                        request_id=req_id,
                    )
                    await self._cost_tracker.record_call(record, db)

                return response.content[0].text

            except CircuitOpenError:
                # 熔断器拒绝，不重试
                duration_ms = int((time.monotonic() - start_ms) * 1000)
                if db is not None:
                    record = ModelCallRecord(
                        tenant_id=tenant_id,
                        task_type=task_type,
                        model=model,
                        input_tokens=0,
                        output_tokens=0,
                        cost_usd=0.0,
                        duration_ms=duration_ms,
                        success=False,
                        error_type="CircuitOpenError",
                        request_id=req_id,
                    )
                    await self._cost_tracker.record_call(record, db)
                raise

            except APIStatusError as exc:
                last_exc = exc
                # 4xx 错误（非 429）不重试
                if exc.status_code < 500 and exc.status_code != 429:
                    logger.error(
                        "model_router_client_error",
                        status_code=exc.status_code,
                        model=model,
                        request_id=req_id,
                    )
                    break
                logger.warning(
                    "model_router_server_error",
                    attempt=attempt + 1,
                    status_code=exc.status_code,
                    model=model,
                    request_id=req_id,
                )

            except (APIConnectionError, APITimeoutError) as exc:
                last_exc = exc
                logger.warning(
                    "model_router_network_error",
                    attempt=attempt + 1,
                    error=type(exc).__name__,
                    model=model,
                    request_id=req_id,
                )

        # 所有重试耗尽，记录失败并重新抛出
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        error_type = type(last_exc).__name__ if last_exc else "UnknownError"

        logger.error(
            "model_router_call_failed",
            tenant_id=tenant_id,
            task_type=task_type,
            model=model,
            error_type=error_type,
            attempts=self.MAX_RETRIES,
            duration_ms=duration_ms,
            request_id=req_id,
        )

        if db is not None:
            record = ModelCallRecord(
                tenant_id=tenant_id,
                task_type=task_type,
                model=model,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                duration_ms=duration_ms,
                success=False,
                error_type=error_type,
                request_id=req_id,
            )
            await self._cost_tracker.record_call(record, db)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("model_router: all retries exhausted with unknown error")

    async def _call_api(
        self,
        model:      str,
        messages:   list[dict[str, str]],
        system:     Optional[str],
        max_tokens: int,
        timeout_s:  int,
    ) -> Any:
        """实际发起 Anthropic SDK 调用，带超时控制。"""
        kwargs: dict[str, Any] = {
            "model":      model,
            "max_tokens": max_tokens,
            "messages":   messages,
        }
        if system:
            kwargs["system"] = system

        return await asyncio.wait_for(
            self._client.messages.create(**kwargs),
            timeout=timeout_s,
        )
