from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import alerts_webhook


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(alerts_webhook.router)
    return TestClient(app)


def test_alert_webhook_accepts_alertmanager_payload_and_forwards(monkeypatch):
    alerts_webhook._DEDUP_CACHE.clear()
    monkeypatch.setenv("ALERT_DEDUPE_ENABLED", "false")
    monkeypatch.setenv("ALERT_RECIPIENTS", "ops_a,ops_b")
    monkeypatch.delenv("ALERT_WEBHOOK_TOKEN", raising=False)

    mock_send = AsyncMock(return_value={"success": True, "sent_count": 2})
    mock_persist = AsyncMock(return_value=2)
    monkeypatch.setattr(alerts_webhook.wechat_alert_service, "send_system_alert", mock_send)
    monkeypatch.setattr(alerts_webhook, "_persist_ops_events", mock_persist)

    payload = {
        "status": "firing",
        "alerts": [
            {
                "labels": {"alertname": "APIServiceDown", "severity": "critical", "instance": "api-1"},
                "annotations": {"summary": "API down"},
            },
            {
                "labels": {"alertname": "HighErrorRate", "severity": "warning", "instance": "api-2"},
                "annotations": {"summary": "error rate high"},
            },
        ],
    }

    resp = _client().post("/api/v1/alerts/webhook", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["received"] == 2
    assert data["deduped"] == 2
    assert data["suppressed"] == 0
    assert data["forwarded"] is True
    assert data["severity"] == "critical"
    mock_send.assert_awaited_once()
    mock_persist.assert_awaited_once()


def test_alert_webhook_requires_token_when_configured(monkeypatch):
    alerts_webhook._DEDUP_CACHE.clear()
    monkeypatch.setenv("ALERT_DEDUPE_ENABLED", "false")
    monkeypatch.setenv("ALERT_WEBHOOK_TOKEN", "token-123")
    monkeypatch.setenv("ALERT_RECIPIENTS", "ops_a")

    mock_send = AsyncMock(return_value={"success": True})
    mock_persist = AsyncMock(return_value=1)
    monkeypatch.setattr(alerts_webhook.wechat_alert_service, "send_system_alert", mock_send)
    monkeypatch.setattr(alerts_webhook, "_persist_ops_events", mock_persist)

    payload = {"status": "firing", "alerts": [{"labels": {"alertname": "x", "severity": "warning"}}]}

    # Missing token
    resp = _client().post("/api/v1/alerts/webhook", json=payload)
    assert resp.status_code == 401

    # Invalid token
    resp = _client().post("/api/v1/alerts/webhook", json=payload, headers={"X-Alert-Token": "bad"})
    assert resp.status_code == 401

    # Valid token
    resp = _client().post("/api/v1/alerts/webhook", json=payload, headers={"X-Alert-Token": "token-123"})
    assert resp.status_code == 200
    mock_send.assert_awaited_once()


def test_alert_webhook_skips_forward_when_no_recipients(monkeypatch):
    alerts_webhook._DEDUP_CACHE.clear()
    monkeypatch.setenv("ALERT_DEDUPE_ENABLED", "false")
    monkeypatch.delenv("ALERT_RECIPIENTS", raising=False)
    monkeypatch.delenv("WECHAT_DEFAULT_RECIPIENT", raising=False)
    monkeypatch.delenv("ALERT_WEBHOOK_TOKEN", raising=False)

    mock_send = AsyncMock(return_value={"success": True})
    mock_persist = AsyncMock(return_value=1)
    monkeypatch.setattr(alerts_webhook.wechat_alert_service, "send_system_alert", mock_send)
    monkeypatch.setattr(alerts_webhook, "_persist_ops_events", mock_persist)

    payload = {
        "status": "firing",
        "alerts": [{"labels": {"alertname": "HighCPUUsage", "severity": "warning"}}],
    }
    resp = _client().post("/api/v1/alerts/warning", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["forwarded"] is False
    assert data["send_result"]["reason"] == "no_recipients"
    assert mock_send.await_count == 0
    mock_persist.assert_awaited_once()


def test_alert_webhook_supports_list_payload(monkeypatch):
    alerts_webhook._DEDUP_CACHE.clear()
    monkeypatch.setenv("ALERT_DEDUPE_ENABLED", "false")
    monkeypatch.setenv("ALERT_RECIPIENTS", "ops_a")
    monkeypatch.delenv("ALERT_WEBHOOK_TOKEN", raising=False)
    mock_send = AsyncMock(return_value={"success": True, "sent_count": 1})
    mock_persist = AsyncMock(return_value=2)
    monkeypatch.setattr(alerts_webhook.wechat_alert_service, "send_system_alert", mock_send)
    monkeypatch.setattr(alerts_webhook, "_persist_ops_events", mock_persist)

    payload = [
        {"labels": {"alertname": "A", "severity": "warning"}},
        {"labels": {"alertname": "B", "severity": "critical"}},
    ]
    resp = _client().post("/api/v1/alerts/critical", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["received"] == 2
    assert data["severity"] == "critical"
    mock_send.assert_awaited_once()
    mock_persist.assert_awaited_once()


def test_alert_webhook_deduplicates_repeated_alerts(monkeypatch):
    alerts_webhook._DEDUP_CACHE.clear()
    monkeypatch.setenv("ALERT_DEDUPE_ENABLED", "true")
    monkeypatch.setenv("ALERT_DEDUPE_TTL_SECONDS", "600")
    monkeypatch.setenv("ALERT_RECIPIENTS", "ops_a")
    monkeypatch.delenv("ALERT_WEBHOOK_TOKEN", raising=False)

    mock_send = AsyncMock(return_value={"success": True, "sent_count": 1})
    mock_persist = AsyncMock(return_value=1)
    monkeypatch.setattr(alerts_webhook.wechat_alert_service, "send_system_alert", mock_send)
    monkeypatch.setattr(alerts_webhook, "_persist_ops_events", mock_persist)

    payload = {
        "status": "firing",
        "alerts": [{"labels": {"alertname": "A", "severity": "warning", "instance": "x"}}],
    }
    client = _client()

    first = client.post("/api/v1/alerts/webhook", json=payload)
    assert first.status_code == 200
    assert first.json()["deduped"] == 1
    assert first.json()["suppressed"] == 0

    second = client.post("/api/v1/alerts/webhook", json=payload)
    assert second.status_code == 200
    assert second.json()["deduped"] == 0
    assert second.json()["suppressed"] == 1

    # only first one forwarded
    assert mock_send.await_count == 1
