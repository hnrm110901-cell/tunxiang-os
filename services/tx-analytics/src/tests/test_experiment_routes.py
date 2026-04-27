"""Sprint G — 实验框架 HTTP 路由单测（Tier 3）。

通过 FastAPI dependency_overrides 注入 fake orchestrator/dashboard/breaker，
不连任何 DB / Redis。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ..api.experiment_routes import (
    get_circuit_breaker,
    get_dashboard,
    get_orchestrator,
    router,
)
from ..experiment.circuit_breaker import (
    CircuitBreakerStatus,
    VariantBreach,
)
from ..experiment.dashboard import (
    ExperimentSummary,
    PairwiseResult,
    VariantMetricCell,
)
from ..experiment.metrics import WelchResult
from ..experiment.orchestrator import OrchestratorBucketResult

# ── fakes ─────────────────────────────────────────────────────────────


class FakeOrchestrator:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def get_bucket(self, **kwargs: Any) -> OrchestratorBucketResult:
        self.calls.append(kwargs)
        return OrchestratorBucketResult(
            bucket="variant_a",
            bucket_position=4321,
            is_new_exposure=True,
            fallback_reason=None,
            experiment_enabled=True,
            circuit_breaker_tripped=False,
        )


class FakeDashboard:
    async def summarize(self, **kwargs: Any) -> ExperimentSummary:
        tw = kwargs["time_window"]
        return ExperimentSummary(
            experiment_key=kwargs["experiment_key"],
            time_window=tw,
            variant_subjects={"control": ["u1", "u2"], "variant_a": ["u3", "u4"]},
            cells=[
                VariantMetricCell(
                    variant="control", metric_key="payment_success_rate", n=2, mean=0.99
                ),
                VariantMetricCell(
                    variant="variant_a",
                    metric_key="payment_success_rate",
                    n=2,
                    mean=0.97,
                ),
            ],
            pairs=[
                PairwiseResult(
                    metric_key="payment_success_rate",
                    control_variant="control",
                    test_variant="variant_a",
                    welch=WelchResult(
                        t_statistic=-1.5,
                        df=18.0,
                        p_value=0.15,
                        effect_size_cohens_d=-0.3,
                        mean_a=0.99,
                        mean_b=0.97,
                        var_a=0.0001,
                        var_b=0.0002,
                        n_a=100,
                        n_b=100,
                        ci_95_low=-0.05,
                        ci_95_high=0.01,
                        is_significant_at_005=False,
                    ),
                    lift_pct=-2.02,
                )
            ],
        )


class FakeBreaker:
    def __init__(self, tripped: bool = False) -> None:
        self.tripped = tripped
        self.reset_calls: list[dict] = []

    async def evaluate(
        self, *, tenant_id: str, experiment_key: str, threshold_pct: float = -20.0
    ) -> CircuitBreakerStatus:
        breaches: list[VariantBreach] = []
        if self.tripped:
            breaches.append(
                VariantBreach(
                    variant="variant_a",
                    metric_key="payment_success_rate",
                    drop_pct=-25.0,
                    threshold_pct=threshold_pct,
                )
            )
        return CircuitBreakerStatus(
            experiment_key=experiment_key,
            tripped=self.tripped,
            threshold_pct=threshold_pct,
            breaches=breaches,
        )

    async def reset(self, *, tenant_id: str, experiment_key: str, actor: str) -> None:
        self.reset_calls.append(
            {"tenant_id": tenant_id, "experiment_key": experiment_key, "actor": actor}
        )


# ── 测试 fixture ──────────────────────────────────────────────────────


def _make_app(
    orch: Optional[FakeOrchestrator] = None,
    dash: Optional[FakeDashboard] = None,
    cb: Optional[FakeBreaker] = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    if orch is not None:
        app.dependency_overrides[get_orchestrator] = lambda: orch
    if dash is not None:
        app.dependency_overrides[get_dashboard] = lambda: dash
    if cb is not None:
        app.dependency_overrides[get_circuit_breaker] = lambda: cb
    return app


# ── 用例 ──────────────────────────────────────────────────────────────


def test_bucket_route_requires_tenant_header() -> None:
    app = _make_app(orch=FakeOrchestrator())
    client = TestClient(app)
    r = client.post(
        "/api/v1/experiments/checkout.v2/bucket",
        json={"subject_type": "user", "subject_id": "u1"},
    )
    assert r.status_code == 400


def test_bucket_route_authn_403_on_tenant_mismatch() -> None:
    """body.tenant_id 与 header 不一致 → 403。"""
    app = _make_app(orch=FakeOrchestrator())
    client = TestClient(app)
    r = client.post(
        "/api/v1/experiments/checkout.v2/bucket",
        json={"tenant_id": "tenant-B", "subject_type": "user", "subject_id": "u1"},
        headers={"X-Tenant-ID": "tenant-A"},
    )
    assert r.status_code == 403
    assert "tenant_id 三方一致性" in r.json()["detail"]


def test_bucket_route_returns_assignment() -> None:
    fake_orch = FakeOrchestrator()
    app = _make_app(orch=fake_orch)
    client = TestClient(app)
    r = client.post(
        "/api/v1/experiments/checkout.v2/bucket",
        json={"subject_type": "user", "subject_id": "u1"},
        headers={"X-Tenant-ID": "tenant-A"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["bucket"] == "variant_a"
    assert body["data"]["is_new_exposure"] is True
    assert len(fake_orch.calls) == 1


def test_dashboard_route_returns_correct_summary() -> None:
    app = _make_app(dash=FakeDashboard())
    client = TestClient(app)
    r = client.get(
        "/api/v1/experiments/checkout.v2/dashboard",
        params={"metric": ["payment_success_rate"]},
        headers={"X-Tenant-ID": "tenant-A"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["experiment_key"] == "checkout.v2"
    assert "control" in data["variant_subject_counts"]
    assert len(data["pairs"]) == 1
    pair = data["pairs"][0]
    assert pair["metric_key"] == "payment_success_rate"
    assert pair["is_significant_at_005"] is False


def test_circuit_breaker_status_route() -> None:
    app = _make_app(cb=FakeBreaker(tripped=True))
    client = TestClient(app)
    r = client.get(
        "/api/v1/experiments/checkout.v2/circuit-breaker",
        headers={"X-Tenant-ID": "tenant-A"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["tripped"] is True
    assert len(body["data"]["breaches"]) == 1


def test_circuit_breaker_reset_requires_admin() -> None:
    """无 X-Role-Code → 403。"""
    app = _make_app(cb=FakeBreaker())
    client = TestClient(app)
    r = client.post(
        "/api/v1/experiments/checkout.v2/circuit-breaker/reset",
        json={"actor": "founder@tx"},
        headers={"X-Tenant-ID": "tenant-A"},
    )
    assert r.status_code == 403


def test_circuit_breaker_reset_admin_ok() -> None:
    fake_cb = FakeBreaker()
    app = _make_app(cb=fake_cb)
    client = TestClient(app)
    r = client.post(
        "/api/v1/experiments/checkout.v2/circuit-breaker/reset",
        json={"actor": "founder@tx"},
        headers={"X-Tenant-ID": "tenant-A", "X-Role-Code": "ADMIN"},
    )
    assert r.status_code == 200
    assert len(fake_cb.reset_calls) == 1
    assert fake_cb.reset_calls[0]["actor"] == "founder@tx"
