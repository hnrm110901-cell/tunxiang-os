"""Tier 1 — booking_webhook_routes._verify_webhook_signature 空 WEBHOOK_SECRET 必须 fail-closed

漏洞背景:
  services/tx-trade/src/api/booking_webhook_routes.py:76 `_verify_webhook_signature`
  在 WEBHOOK_SECRET 环境变量为空（或未设置）时直接 `return`（仅 log warning），
  跳过签名验证与防重放检查。

  风险窗口:
  - PR fix/gateway-pay-callback-whitelist 加 /api/v1/booking/webhook 到
    gateway AUTH_EXEMPT_PREFIXES，第三方预订 webhook 跳过 JWT 鉴权
  - 生产部署时若 WEBHOOK_SECRET 漏配 → gateway bypass + 下游 skip 验签
    = 任意公网请求可写 customer_bookings / 触发 reservations 创建

  来源: gateway-pay-callback-whitelist PR 第 2 轮 code-reviewer agent F#3 verdict。

修复要求 (本 PR):
  - 空 secret 时改为 raise HTTPException(503, error.code=WEBHOOK_SECRET_NOT_CONFIGURED)
  - 503 而非 403: 区分"配置缺失"(运维问题, 监控告警) vs "签名错"(请求问题, 第三方问题)
  - structlog ERROR 级别（不是 warning）便于触发告警

测试策略:
  - 单元: _verify_webhook_signature 直接调 → 空 secret raise 503 (4 个用例覆盖 3 platform + error code 契约)
  - 集成: 1 endpoint POST 合法 payload + 空 secret → 503（端到端验 helper 在 endpoint 体内真触发）
  - 不回归: 1 endpoint 合法 payload + 有 secret + 缺签名 → 既有 403 INVALID_SIGNATURE 路径不变

运行方法:
  cd services/tx-trade
  PYTHONPATH=src python3 -m pytest src/tests/test_booking_webhook_secret_fail_closed_tier1.py -v
"""

import os
import sys
import time
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 路径准备（复用 test_booking_webhook_routes.py 模式）──────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.join(_TESTS_DIR, "..")
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))
for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.models", os.path.join(_SRC_DIR, "models"))
_ensure_pkg("src.repositories", os.path.join(_SRC_DIR, "repositories"))

# Stub ReservationService（避免 ORM 全量初始化，与 test_booking_webhook_routes.py 一致）
_stub_svc_mod = types.ModuleType("src.services.reservation_service")
_stub_svc_mod.ReservationService = MagicMock
sys.modules["src.services.reservation_service"] = _stub_svc_mod

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.booking_webhook_routes import (  # type: ignore[import]  # noqa: E402
    _get_db_session,
    _verify_webhook_signature,
    router,
)

# ─── 测试工具 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())

_HEADERS = {"X-Tenant-ID": TENANT_ID, "X-Store-ID": STORE_ID}


def _meituan_payload(**kwargs) -> dict:
    """合法美团预订 payload（沿用 test_booking_webhook_routes.py 既有 sample）"""
    base = {
        "order_id": f"MT{uuid.uuid4().hex[:12]}",
        "shop_id": "shop_001",
        "customer_name": "张三",
        "customer_phone": "13800138000",
        "party_size": 4,
        "arrive_time": "2026-06-15T18:30:00",
        "table_type": "大厅",
        "special_request": "",
        "status": "confirmed",
        "created_at": "2026-06-15T10:00:00",
    }
    base.update(kwargs)
    return base


def _make_db():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=AsyncMock(fetchone=MagicMock(return_value=None)))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_app(db):
    app = FastAPI()
    app.include_router(router)

    async def _dep():
        yield db

    app.dependency_overrides[_get_db_session] = _dep
    return app


def _env_without_secret() -> dict:
    """返回不含 WEBHOOK_SECRET 的 env dict（patch.dict clear=True 后 restore）"""
    return {k: v for k, v in os.environ.items() if k != "WEBHOOK_SECRET"}


# ─── Unit Tests: _verify_webhook_signature 直接调用 ─────────────────────────


@pytest.mark.asyncio
async def test_empty_secret_string_raises_503():
    """WEBHOOK_SECRET="" 空字符串时 _verify_webhook_signature 必须 raise 503 (fail-closed)"""
    request = MagicMock(spec=Request)
    request.headers = {}
    request.body = AsyncMock(return_value=b"{}")

    with patch.dict(os.environ, {"WEBHOOK_SECRET": ""}, clear=False):
        with pytest.raises(HTTPException) as exc_info:
            await _verify_webhook_signature(
                request, platform="meituan", signature_header="X-Meituan-Signature"
            )

    assert exc_info.value.status_code == 503, (
        f"空 WEBHOOK_SECRET 应 raise 503 (fail-closed)，实际 {exc_info.value.status_code}"
    )
    detail = exc_info.value.detail
    assert isinstance(detail, dict), f"detail 应为 dict，实际 {type(detail)}"
    assert (
        detail.get("error", {}).get("code") == "WEBHOOK_SECRET_NOT_CONFIGURED"
    ), f"error code 应为 WEBHOOK_SECRET_NOT_CONFIGURED，实际 detail={detail}"


@pytest.mark.asyncio
async def test_missing_secret_env_var_raises_503():
    """WEBHOOK_SECRET 完全未设置（env 中无 key）同样 fail-closed 503"""
    request = MagicMock(spec=Request)
    request.headers = {}
    request.body = AsyncMock(return_value=b"{}")

    with patch.dict(os.environ, _env_without_secret(), clear=True):
        with pytest.raises(HTTPException) as exc_info:
            await _verify_webhook_signature(
                request, platform="dianping", signature_header="X-Meituan-Signature"
            )

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_empty_secret_blocks_all_three_platforms():
    """三个 platform (meituan/dianping/wechat) 在空 secret 时均 fail-closed"""
    for platform, sig_header in [
        ("meituan", "X-Meituan-Signature"),
        ("dianping", "X-Meituan-Signature"),  # 大众点评共享美团签名体系
        ("wechat", "X-Wechat-Signature"),
    ]:
        request = MagicMock(spec=Request)
        request.headers = {}
        request.body = AsyncMock(return_value=b"{}")

        with patch.dict(os.environ, {"WEBHOOK_SECRET": ""}, clear=False):
            with pytest.raises(HTTPException) as exc_info:
                await _verify_webhook_signature(
                    request, platform=platform, signature_header=sig_header
                )

        assert exc_info.value.status_code == 503, (
            f"platform={platform} 空 secret 应 503，实际 {exc_info.value.status_code}"
        )


@pytest.mark.asyncio
async def test_error_code_string_contract():
    """空 secret 时 error.code 必须是 WEBHOOK_SECRET_NOT_CONFIGURED 字符串（防告警规则失效）"""
    request = MagicMock(spec=Request)
    request.headers = {}
    request.body = AsyncMock(return_value=b"{}")

    with patch.dict(os.environ, {"WEBHOOK_SECRET": ""}, clear=False):
        with pytest.raises(HTTPException) as exc_info:
            await _verify_webhook_signature(
                request, platform="wechat", signature_header="X-Wechat-Signature"
            )

    code = exc_info.value.detail["error"]["code"]
    assert code == "WEBHOOK_SECRET_NOT_CONFIGURED", (
        f"error code 必须为 WEBHOOK_SECRET_NOT_CONFIGURED (告警规则依赖)，实际 {code}"
    )


# ─── Integration Tests: endpoint POST 合法 payload + 空 secret → 503 ──────


def test_endpoint_empty_secret_returns_503_via_meituan_webhook():
    """POST /api/v1/booking/webhook/meituan 合法 payload + 空 WEBHOOK_SECRET → 503

    端到端验：endpoint 函数体内调 _verify_webhook_signature 在 body validation 之后真触发，
    防御场景: gateway prefix bypass 后 prod 漏配 secret 时此 endpoint 拒绝任意公网写入。
    """
    db = _make_db()
    mock_svc = AsyncMock()
    mock_svc.find_by_platform_order_id = AsyncMock(return_value=None)
    mock_svc.create_reservation = AsyncMock(return_value={"id": str(uuid.uuid4())})

    with patch("src.api.booking_webhook_routes.ReservationService", return_value=mock_svc):
        with patch.dict(os.environ, {"WEBHOOK_SECRET": ""}, clear=False):
            app = _make_app(db)
            client = TestClient(app)
            resp = client.post(
                "/api/v1/booking/webhook/meituan",
                json=_meituan_payload(),
                headers=_HEADERS,
            )

    assert resp.status_code == 503, (
        f"空 secret 应返 503 (fail-closed)，实际 {resp.status_code} body={resp.text}"
    )
    body = resp.json()
    assert body.get("detail", {}).get("error", {}).get("code") == "WEBHOOK_SECRET_NOT_CONFIGURED", (
        f"error code 应为 WEBHOOK_SECRET_NOT_CONFIGURED，实际 {body}"
    )

    # 关键：DB 不得被写入（fail-closed 在 DB 之前）
    mock_svc.create_reservation.assert_not_awaited()


# ─── 不回归: secret 有值 + 缺签名 → 既有 403 路径不变 ──────────────────────


def test_endpoint_valid_secret_invalid_signature_still_returns_403():
    """secret 有值 + 缺 X-Meituan-Signature header → 既有 403 INVALID_SIGNATURE 路径不回归"""
    db = _make_db()
    mock_svc = AsyncMock()

    with patch("src.api.booking_webhook_routes.ReservationService", return_value=mock_svc):
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "test_secret_value"}, clear=False):
            app = _make_app(db)
            client = TestClient(app)
            resp = client.post(
                "/api/v1/booking/webhook/meituan",
                json=_meituan_payload(),
                headers={
                    **_HEADERS,
                    "X-Timestamp": str(int(time.time())),
                    # 故意不带 X-Meituan-Signature header
                },
            )

    assert resp.status_code == 403, (
        f"secret 有值 + 缺签名应 403 (既有 INVALID_SIGNATURE 路径), 实际 {resp.status_code}"
    )
    # DB 不被写入（既有行为）
    mock_svc.create_reservation.assert_not_awaited()
