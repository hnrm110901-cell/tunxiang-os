"""Sprint G — G4 CircuitBreakerEvaluator 单测（Tier 3）。"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Optional

import pytest

from ..experiment.circuit_breaker import (
    CircuitBreakerEvaluator,
    MetricSnapshot,
)

# ── fakes ───────────────────────────────────────────────────────────────


class FakeMetricsProvider:
    def __init__(self, snapshots: list[MetricSnapshot]) -> None:
        self.snapshots = snapshots

    async def snapshot_last_hour(
        self, tenant_id: str, experiment_key: str
    ) -> list[MetricSnapshot]:
        return self.snapshots


class FakeWriter:
    def __init__(self) -> None:
        self.disabled: list[tuple] = []

    async def disable_experiment(
        self, tenant_id: str, experiment_key: str, reason: str
    ) -> bool:
        self.disabled.append((tenant_id, experiment_key, reason))
        return True


class FakeEmitter:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, **kwargs: Any) -> Optional[str]:
        self.events.append(kwargs)
        return "fake"


# ── 用例 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_variant_drops_22pct_trips_breaker() -> None:
    """variant_a 比 control 跌 22%（payment_success_rate）→ tripped=True。"""
    snapshots = [
        MetricSnapshot(
            metric_key="payment_success_rate",
            by_variant={"control": 0.99, "variant_a": 0.99 * 0.78},  # ~ -22%
        )
    ]
    metrics = FakeMetricsProvider(snapshots)
    writer = FakeWriter()
    emit = FakeEmitter()

    with tempfile.TemporaryDirectory() as td:
        breaker = CircuitBreakerEvaluator(
            metrics_provider=metrics,
            definition_writer=writer,
            emit_func=emit,
            flag_dir=td,
        )
        status = await breaker.evaluate(
            tenant_id="tenant-A", experiment_key="checkout.v2", threshold_pct=-20.0
        )
        assert status.tripped is True
        assert len(status.breaches) == 1
        assert status.breaches[0].variant == "variant_a"
        assert status.breaches[0].drop_pct < -20.0


@pytest.mark.asyncio
async def test_variant_drops_15pct_does_not_trip() -> None:
    """跌幅 15% < 20% 阈值 → 不熔断。"""
    snapshots = [
        MetricSnapshot(
            metric_key="payment_success_rate",
            by_variant={"control": 1.0, "variant_a": 0.85},  # -15%
        )
    ]
    breaker = CircuitBreakerEvaluator(
        metrics_provider=FakeMetricsProvider(snapshots),
        definition_writer=FakeWriter(),
        emit_func=None,
    )
    status = await breaker.evaluate(
        tenant_id="t", experiment_key="ex", threshold_pct=-20.0
    )
    assert status.tripped is False
    assert status.breaches == []


@pytest.mark.asyncio
async def test_per_experiment_threshold_override() -> None:
    """更严的阈值 -10% → 跌 15% 也熔断。"""
    snapshots = [
        MetricSnapshot(
            metric_key="payment_success_rate",
            by_variant={"control": 1.0, "variant_a": 0.85},
        )
    ]
    breaker = CircuitBreakerEvaluator(
        metrics_provider=FakeMetricsProvider(snapshots),
        definition_writer=FakeWriter(),
        emit_func=None,
    )
    status = await breaker.evaluate(
        tenant_id="t", experiment_key="ex", threshold_pct=-10.0
    )
    assert status.tripped is True


@pytest.mark.asyncio
async def test_trip_writes_flag_file_and_disables_definition() -> None:
    """trip 动作：disable_experiment 被调 + flag 文件落盘 + 事件发出。"""
    snapshots = [
        MetricSnapshot(
            metric_key="payment_success_rate",
            by_variant={"control": 1.0, "variant_a": 0.5},  # -50%
        )
    ]
    writer = FakeWriter()
    emit = FakeEmitter()

    with tempfile.TemporaryDirectory() as td:
        breaker = CircuitBreakerEvaluator(
            metrics_provider=FakeMetricsProvider(snapshots),
            definition_writer=writer,
            emit_func=emit,
            flag_dir=td,
        )
        status = await breaker.evaluate(
            tenant_id="tenant-A", experiment_key="checkout.v2"
        )
        assert status.tripped is True

        await breaker.trip(
            tenant_id="tenant-A", experiment_key="checkout.v2", status=status
        )

        # writer 关 enabled
        assert len(writer.disabled) == 1
        assert writer.disabled[0][0] == "tenant-A"
        assert writer.disabled[0][1] == "checkout.v2"

        # flag 文件存在
        files = os.listdir(td)
        assert any(f.endswith(".disabled.yaml") for f in files)

        # 事件发出
        assert any(
            e["event_type"].value == "experiment.circuit_breaker_tripped"
            for e in emit.events
        )


@pytest.mark.asyncio
async def test_tripped_state_persists_until_reset() -> None:
    """trip 后 flag 文件存在；reset 后被清除。"""
    snapshots = [
        MetricSnapshot(
            metric_key="payment_success_rate",
            by_variant={"control": 1.0, "variant_a": 0.5},
        )
    ]
    writer = FakeWriter()
    emit = FakeEmitter()

    with tempfile.TemporaryDirectory() as td:
        breaker = CircuitBreakerEvaluator(
            metrics_provider=FakeMetricsProvider(snapshots),
            definition_writer=writer,
            emit_func=emit,
            flag_dir=td,
        )
        status = await breaker.evaluate(
            tenant_id="tenant-A", experiment_key="checkout.v2"
        )
        await breaker.trip(
            tenant_id="tenant-A", experiment_key="checkout.v2", status=status
        )
        assert len(os.listdir(td)) == 1

        await breaker.reset(
            tenant_id="tenant-A", experiment_key="checkout.v2", actor="founder@tx"
        )
        assert os.listdir(td) == []
        assert any(
            e["event_type"].value == "experiment.circuit_breaker_reset"
            for e in emit.events
        )


@pytest.mark.asyncio
async def test_no_control_baseline_skipped() -> None:
    """快照中无 control → 跳过该指标，不熔断。"""
    snapshots = [
        MetricSnapshot(
            metric_key="payment_success_rate",
            by_variant={"variant_a": 0.5},
        )
    ]
    breaker = CircuitBreakerEvaluator(
        metrics_provider=FakeMetricsProvider(snapshots),
        definition_writer=FakeWriter(),
        emit_func=None,
    )
    status = await breaker.evaluate(tenant_id="t", experiment_key="ex")
    assert status.tripped is False


@pytest.mark.asyncio
async def test_metrics_failure_does_not_trip() -> None:
    """指标拉取失败 → 不熔断（防止误杀）。"""

    class BrokenProvider:
        async def snapshot_last_hour(self, tenant_id: str, experiment_key: str):
            raise ConnectionError("DB 临时失败")

    breaker = CircuitBreakerEvaluator(
        metrics_provider=BrokenProvider(),
        definition_writer=FakeWriter(),
        emit_func=None,
    )
    status = await breaker.evaluate(tenant_id="t", experiment_key="ex")
    assert status.tripped is False
