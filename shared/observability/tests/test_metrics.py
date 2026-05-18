"""shared/observability/metrics.py 单测 (Phase C.3 #820)。

测试目标:
  1. setup_metrics 成功挂入 /metrics endpoint
  2. service_name 必传 (空串 → ValueError)
  3. /metrics 返回 prometheus text format (200)
  4. /metrics 自身不计入 fastapi_requests_total (excluded_handlers)
"""

from __future__ import annotations

import pytest


def _has_instrumentator() -> bool:
    try:
        import fastapi  # noqa: F401
        import prometheus_fastapi_instrumentator  # noqa: F401
    except ImportError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _has_instrumentator(),
    reason="prometheus_fastapi_instrumentator / fastapi 未安装 (本地 dev env), CI 装齐再跑",
)


def test_service_name_required() -> None:
    """空 service_name → ValueError."""
    from fastapi import FastAPI

    from shared.observability.metrics import setup_metrics

    app = FastAPI()
    with pytest.raises(ValueError, match="service_name"):
        setup_metrics(app, service_name="")


def test_metrics_endpoint_exposed() -> None:
    """挂入后 GET /metrics 返回 200 + prometheus text format."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from shared.observability.metrics import setup_metrics

    app = FastAPI()
    setup_metrics(app, service_name="test-service")

    client = TestClient(app)
    resp = client.get("/metrics")

    assert resp.status_code == 200
    # Prometheus text exposition format starts with `# HELP` or `# TYPE`
    body = resp.text
    assert "# HELP" in body or "# TYPE" in body


def test_metrics_endpoint_excluded_from_self_counter() -> None:
    """/metrics 自身不计入 fastapi_requests_total (避免 scrape 自爆)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from shared.observability.metrics import setup_metrics

    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    setup_metrics(app, service_name="test-service-2")

    client = TestClient(app)
    # 触发一次业务路由
    client.get("/ping")
    # 触发 /metrics scrape 多次
    for _ in range(3):
        client.get("/metrics")

    final = client.get("/metrics").text
    # /ping 应在 metric 输出里
    assert "/ping" in final or "ping" in final
    # /metrics 自身路径不应作为 handler 标签出现 (excluded_handlers 生效)
    # 检查 handler 标签 — 不允许 handler="/metrics"
    assert 'handler="/metrics"' not in final
