"""G2 — ExperimentOrchestrator：判桶 + idempotent expose + 熔断守卫

调用链：
    HTTP 路由 → orchestrator.get_bucket(...)
        ├─ 1. 取实验定义（5 分钟 in-process 缓存）
        ├─ 2. 检查熔断：tripped → 强制 control + return
        ├─ 3. 调 assign_bucket 纯函数
        ├─ 4. UPSERT experiment_exposures（unique 约束保 idempotent）
        ├─ 5. 旁路 emit_event(EXPOSED)（仅首次写入时；重复请求不重发）
        └─ 6. 返回 AssignmentResult + 已暴露事实

依赖注入约定：
  - definition_repo: 必须实现 get_definition(tenant_id, experiment_key)
  - exposure_repo:   必须实现 get_existing / insert_if_absent
  - circuit_breaker_state_provider: 实现 is_tripped(tenant_id, experiment_key)
  - emit_func: 默认为 shared.events.src.emitter.emit_event；测试可注入 mock

设计准则：
  - 任何依赖（DB / event bus / cache）失败 → 兜底返回 control，并写 warning 日志
    （决不能因 orchestrator 抛异常导致主业务链路挂掉）
  - 缓存 TTL 5 分钟：实验配置变更后最多 5 分钟生效（admin 端按下"立即推平"按钮可
    远程清缓存——本模块只暴露 .invalidate(tenant, key)）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Protocol

import structlog

from .assignment import (
    CONTROL_BUCKET,
    AssignmentResult,
    Variant,
    assign_bucket,
)

logger = structlog.get_logger(__name__)

_CACHE_TTL_SECONDS = 300


@dataclass(frozen=True)
class ExperimentSubject:
    """实验主体（被分桶的对象）。"""

    subject_type: str  # "user" / "device" / "store" / "table"
    subject_id: str


@dataclass(frozen=True)
class ExperimentDefinition:
    """实验定义视图（缓存内的不可变快照）。"""

    experiment_key: str
    tenant_id: str
    variants: list[Variant]
    bucket_hash_seed: str
    enabled: bool
    circuit_breaker_threshold_pct: float
    guardrail_metrics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OrchestratorBucketResult:
    """orchestrator 输出。"""

    bucket: str
    bucket_position: int
    is_new_exposure: bool
    fallback_reason: Optional[str]
    experiment_enabled: bool
    circuit_breaker_tripped: bool


class DefinitionRepo(Protocol):
    async def get_definition(
        self, tenant_id: str, experiment_key: str
    ) -> Optional[ExperimentDefinition]: ...


class ExposureRepo(Protocol):
    async def get_existing(
        self,
        tenant_id: str,
        experiment_key: str,
        subject_type: str,
        subject_id: str,
    ) -> Optional[str]:
        """返回历史 bucket（如果存在），否则 None。"""

    async def insert_if_absent(
        self,
        tenant_id: str,
        store_id: Optional[str],
        experiment_key: str,
        subject_type: str,
        subject_id: str,
        bucket: str,
        bucket_hash_seed: str,
        context: dict[str, Any],
    ) -> bool:
        """返回 True=本次插入, False=已存在（其它请求并发先到）。"""


class CircuitBreakerStateProvider(Protocol):
    async def is_tripped(self, tenant_id: str, experiment_key: str) -> bool: ...


EmitFunc = Callable[..., Awaitable[Optional[str]]]


class ExperimentOrchestrator:
    """实验编排器（线程不安全 — 仅在 asyncio 单事件循环内使用；缓存为 in-process）。"""

    def __init__(
        self,
        *,
        definition_repo: DefinitionRepo,
        exposure_repo: ExposureRepo,
        circuit_breaker_state: CircuitBreakerStateProvider,
        emit_func: Optional[EmitFunc] = None,
        cache_ttl_seconds: int = _CACHE_TTL_SECONDS,
    ) -> None:
        self._def_repo = definition_repo
        self._exp_repo = exposure_repo
        self._cb = circuit_breaker_state
        self._emit = emit_func
        self._cache: dict[tuple[str, str], tuple[float, ExperimentDefinition]] = {}
        self._ttl = cache_ttl_seconds

    # ── public ────────────────────────────────────────────────────────────

    async def get_bucket(
        self,
        *,
        tenant_id: str,
        experiment_key: str,
        subject: ExperimentSubject,
        context: Optional[dict[str, Any]] = None,
        store_id: Optional[str] = None,
    ) -> OrchestratorBucketResult:
        """主入口。永不抛异常。"""
        context = context or {}

        definition = await self._load_definition_safe(tenant_id, experiment_key)
        if definition is None or not definition.enabled:
            # 配置不存在或被关闭 → control（不触发暴露事件，因为没有实验）
            return OrchestratorBucketResult(
                bucket=CONTROL_BUCKET,
                bucket_position=0,
                is_new_exposure=False,
                fallback_reason="experiment_disabled" if definition else "experiment_not_found",
                experiment_enabled=False,
                circuit_breaker_tripped=False,
            )

        # 熔断检查
        tripped = False
        try:
            tripped = await self._cb.is_tripped(tenant_id, experiment_key)
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.warning(
                "circuit_breaker_check_failed",
                tenant_id=tenant_id,
                experiment_key=experiment_key,
                error=str(e),
            )

        if tripped:
            # 熔断时仍记录 expose（让仪表板看到熔断后的强制 control）
            assignment = AssignmentResult(
                bucket=CONTROL_BUCKET,
                bucket_position=0,
                fallback_reason="circuit_breaker_tripped",
            )
        else:
            assignment = assign_bucket(
                experiment_key=experiment_key,
                subject_id=subject.subject_id,
                variants=definition.variants,
                seed=definition.bucket_hash_seed,
            )

        # idempotent expose
        is_new = await self._idempotent_expose(
            tenant_id=tenant_id,
            store_id=store_id,
            experiment_key=experiment_key,
            subject=subject,
            bucket=assignment.bucket,
            bucket_hash_seed=definition.bucket_hash_seed,
            context=context,
        )

        if is_new and self._emit is not None:
            await self._emit_exposed(
                tenant_id=tenant_id,
                store_id=store_id,
                experiment_key=experiment_key,
                subject=subject,
                bucket=assignment.bucket,
                context=context,
            )

        return OrchestratorBucketResult(
            bucket=assignment.bucket,
            bucket_position=assignment.bucket_position,
            is_new_exposure=is_new,
            fallback_reason=assignment.fallback_reason,
            experiment_enabled=True,
            circuit_breaker_tripped=tripped,
        )

    def invalidate(self, tenant_id: str, experiment_key: str) -> None:
        """从缓存中清除某实验定义（admin 端推平用）。"""
        self._cache.pop((tenant_id, experiment_key), None)

    # ── private ───────────────────────────────────────────────────────────

    async def _load_definition_safe(
        self, tenant_id: str, experiment_key: str
    ) -> Optional[ExperimentDefinition]:
        cache_key = (tenant_id, experiment_key)
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached is not None:
            ts, definition = cached
            if now - ts < self._ttl:
                return definition

        try:
            definition = await self._def_repo.get_definition(tenant_id, experiment_key)
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.warning(
                "experiment_definition_load_failed",
                tenant_id=tenant_id,
                experiment_key=experiment_key,
                error=str(e),
            )
            return None

        if definition is not None:
            self._cache[cache_key] = (now, definition)
        return definition

    async def _idempotent_expose(
        self,
        *,
        tenant_id: str,
        store_id: Optional[str],
        experiment_key: str,
        subject: ExperimentSubject,
        bucket: str,
        bucket_hash_seed: str,
        context: dict[str, Any],
    ) -> bool:
        try:
            inserted = await self._exp_repo.insert_if_absent(
                tenant_id=tenant_id,
                store_id=store_id,
                experiment_key=experiment_key,
                subject_type=subject.subject_type,
                subject_id=subject.subject_id,
                bucket=bucket,
                bucket_hash_seed=bucket_hash_seed,
                context=context,
            )
            return inserted
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.warning(
                "experiment_expose_failed",
                tenant_id=tenant_id,
                experiment_key=experiment_key,
                subject_type=subject.subject_type,
                subject_id=subject.subject_id,
                error=str(e),
            )
            return False

    async def _emit_exposed(
        self,
        *,
        tenant_id: str,
        store_id: Optional[str],
        experiment_key: str,
        subject: ExperimentSubject,
        bucket: str,
        context: dict[str, Any],
    ) -> None:
        if self._emit is None:
            return
        # 解析事件类型枚举：优先使用 shared.events 的 ExperimentEventType；
        # 在 shared 不可用的环境（如 isolated unit test）降级为字符串字面量，
        # fake emitter 看到的 event_type.value 一致，仍能断言。
        event_type: object
        try:
            from shared.events.src.event_types import ExperimentEventType

            event_type = ExperimentEventType.EXPOSED
        except ImportError:
            class _ExposedFallback:
                value = "experiment.exposed"

            event_type = _ExposedFallback()

        try:
            await self._emit(
                event_type=event_type,
                tenant_id=tenant_id,
                stream_id=f"{experiment_key}:{subject.subject_type}:{subject.subject_id}",
                payload={
                    "experiment_key": experiment_key,
                    "subject_type": subject.subject_type,
                    "subject_id": subject.subject_id,
                    "bucket": bucket,
                    "exposed_at": datetime.now(timezone.utc).isoformat(),
                    "context": context,
                },
                store_id=store_id,
                source_service="tx-analytics",
            )
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.warning(
                "experiment_emit_exposed_failed",
                experiment_key=experiment_key,
                error=str(e),
            )
