"""Sprint G — G2 ExperimentOrchestrator 单测（Tier 3）。"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from ..experiment.assignment import Variant
from ..experiment.orchestrator import (
    CONTROL_BUCKET,
    ExperimentDefinition,
    ExperimentOrchestrator,
    ExperimentSubject,
)

# ── 测试 fakes ─────────────────────────────────────────────────────────


class FakeDefRepo:
    def __init__(self, definition: Optional[ExperimentDefinition]) -> None:
        self.definition = definition
        self.calls = 0

    async def get_definition(self, tenant_id: str, experiment_key: str):
        self.calls += 1
        return self.definition


class FakeExposureRepo:
    def __init__(self) -> None:
        self.store: dict[tuple, str] = {}
        self.insert_calls: int = 0

    async def get_existing(
        self,
        tenant_id: str,
        experiment_key: str,
        subject_type: str,
        subject_id: str,
    ) -> Optional[str]:
        return self.store.get((tenant_id, experiment_key, subject_type, subject_id))

    async def insert_if_absent(
        self,
        *,
        tenant_id: str,
        store_id: Optional[str],
        experiment_key: str,
        subject_type: str,
        subject_id: str,
        bucket: str,
        bucket_hash_seed: str,
        context: dict[str, Any],
    ) -> bool:
        self.insert_calls += 1
        key = (tenant_id, experiment_key, subject_type, subject_id)
        if key in self.store:
            return False
        self.store[key] = bucket
        return True


class FakeCircuitBreaker:
    def __init__(self, tripped: bool = False) -> None:
        self.tripped = tripped

    async def is_tripped(self, tenant_id: str, experiment_key: str) -> bool:
        return self.tripped


class FakeEmitter:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, **kwargs: Any) -> str:
        self.events.append(kwargs)
        return "fake-event-id"


def _make_def(*, enabled: bool = True) -> ExperimentDefinition:
    return ExperimentDefinition(
        experiment_key="checkout.v2",
        tenant_id="tenant-A",
        variants=[
            Variant(name="control", weight=5000),
            Variant(name="variant_a", weight=5000),
        ],
        bucket_hash_seed="seed-1",
        enabled=enabled,
        circuit_breaker_threshold_pct=-20.0,
        guardrail_metrics=["payment_success_rate"],
    )


# ── 用例 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotent_repeated_get_bucket_returns_same_value() -> None:
    """同 subject 重复请求返回相同 bucket，且只插入一次。"""
    def_repo = FakeDefRepo(_make_def())
    exp_repo = FakeExposureRepo()
    cb = FakeCircuitBreaker()
    emit = FakeEmitter()

    orch = ExperimentOrchestrator(
        definition_repo=def_repo,
        exposure_repo=exp_repo,
        circuit_breaker_state=cb,
        emit_func=emit,
    )

    sub = ExperimentSubject(subject_type="user", subject_id="user_42")

    r1 = await orch.get_bucket(
        tenant_id="tenant-A", experiment_key="checkout.v2", subject=sub
    )
    r2 = await orch.get_bucket(
        tenant_id="tenant-A", experiment_key="checkout.v2", subject=sub
    )

    assert r1.bucket == r2.bucket
    assert r1.is_new_exposure is True
    assert r2.is_new_exposure is False
    assert exp_repo.insert_calls == 2  # 都尝试，第二次返回 False
    assert len(exp_repo.store) == 1


@pytest.mark.asyncio
async def test_emits_exposed_event_only_on_first_exposure() -> None:
    """重复请求不重复发射 EXPERIMENT.EXPOSED 事件。"""
    def_repo = FakeDefRepo(_make_def())
    exp_repo = FakeExposureRepo()
    cb = FakeCircuitBreaker()
    emit = FakeEmitter()

    orch = ExperimentOrchestrator(
        definition_repo=def_repo,
        exposure_repo=exp_repo,
        circuit_breaker_state=cb,
        emit_func=emit,
    )

    sub = ExperimentSubject(subject_type="user", subject_id="user_42")
    await orch.get_bucket(
        tenant_id="tenant-A", experiment_key="checkout.v2", subject=sub
    )
    await orch.get_bucket(
        tenant_id="tenant-A", experiment_key="checkout.v2", subject=sub
    )

    assert len(emit.events) == 1
    assert emit.events[0]["event_type"].value == "experiment.exposed"


@pytest.mark.asyncio
async def test_when_circuit_tripped_forces_control() -> None:
    """熔断时强制 control，且 fallback_reason 标记。"""
    def_repo = FakeDefRepo(_make_def())
    exp_repo = FakeExposureRepo()
    cb = FakeCircuitBreaker(tripped=True)
    emit = FakeEmitter()

    orch = ExperimentOrchestrator(
        definition_repo=def_repo,
        exposure_repo=exp_repo,
        circuit_breaker_state=cb,
        emit_func=emit,
    )

    result = await orch.get_bucket(
        tenant_id="tenant-A",
        experiment_key="checkout.v2",
        subject=ExperimentSubject(subject_type="user", subject_id="user_99"),
    )

    assert result.bucket == CONTROL_BUCKET
    assert result.circuit_breaker_tripped is True
    assert result.fallback_reason == "circuit_breaker_tripped"


@pytest.mark.asyncio
async def test_disabled_experiment_returns_control_no_exposure() -> None:
    """实验 disabled → control，且不写暴露记录。"""
    def_repo = FakeDefRepo(_make_def(enabled=False))
    exp_repo = FakeExposureRepo()
    cb = FakeCircuitBreaker()
    emit = FakeEmitter()

    orch = ExperimentOrchestrator(
        definition_repo=def_repo,
        exposure_repo=exp_repo,
        circuit_breaker_state=cb,
        emit_func=emit,
    )

    result = await orch.get_bucket(
        tenant_id="tenant-A",
        experiment_key="checkout.v2",
        subject=ExperimentSubject(subject_type="user", subject_id="u"),
    )

    assert result.bucket == CONTROL_BUCKET
    assert result.experiment_enabled is False
    assert result.is_new_exposure is False
    assert exp_repo.insert_calls == 0
    assert emit.events == []


@pytest.mark.asyncio
async def test_unknown_experiment_returns_control() -> None:
    """实验不存在 → control + reason='experiment_not_found'。"""
    def_repo = FakeDefRepo(None)
    exp_repo = FakeExposureRepo()
    cb = FakeCircuitBreaker()

    orch = ExperimentOrchestrator(
        definition_repo=def_repo,
        exposure_repo=exp_repo,
        circuit_breaker_state=cb,
        emit_func=None,
    )

    result = await orch.get_bucket(
        tenant_id="tenant-A",
        experiment_key="nonexistent",
        subject=ExperimentSubject(subject_type="user", subject_id="u"),
    )
    assert result.bucket == CONTROL_BUCKET
    assert result.fallback_reason == "experiment_not_found"


@pytest.mark.asyncio
async def test_definition_cache_hits_within_ttl() -> None:
    """5 分钟缓存：第二次调用不再查 def_repo。"""
    def_repo = FakeDefRepo(_make_def())
    exp_repo = FakeExposureRepo()
    cb = FakeCircuitBreaker()

    orch = ExperimentOrchestrator(
        definition_repo=def_repo,
        exposure_repo=exp_repo,
        circuit_breaker_state=cb,
        emit_func=None,
    )
    sub = ExperimentSubject(subject_type="user", subject_id="u")

    await orch.get_bucket(
        tenant_id="tenant-A", experiment_key="checkout.v2", subject=sub
    )
    await orch.get_bucket(
        tenant_id="tenant-A",
        experiment_key="checkout.v2",
        subject=ExperimentSubject(subject_type="user", subject_id="u2"),
    )
    assert def_repo.calls == 1


@pytest.mark.asyncio
async def test_invalidate_clears_cache() -> None:
    def_repo = FakeDefRepo(_make_def())
    exp_repo = FakeExposureRepo()
    cb = FakeCircuitBreaker()
    orch = ExperimentOrchestrator(
        definition_repo=def_repo,
        exposure_repo=exp_repo,
        circuit_breaker_state=cb,
        emit_func=None,
    )

    await orch.get_bucket(
        tenant_id="tenant-A",
        experiment_key="checkout.v2",
        subject=ExperimentSubject(subject_type="user", subject_id="u"),
    )
    orch.invalidate("tenant-A", "checkout.v2")
    await orch.get_bucket(
        tenant_id="tenant-A",
        experiment_key="checkout.v2",
        subject=ExperimentSubject(subject_type="user", subject_id="u2"),
    )
    assert def_repo.calls == 2
