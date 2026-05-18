"""Tier 1 — omni_channel_routes 4 处 fail-OPEN 改 fail-closed (F#10)

漏洞背景:
  services/tx-trade/src/api/omni_channel_routes.py 4 处 fail-OPEN：
  - line 60 `_verify_meituan_signature`: secret 空 `return True` (注释明示"无secret时放行")
  - line 69 `_verify_eleme_signature`: secret 空 `return True`
  - line 78 `_verify_douyin_signature`: secret 空 `return True`
  - line 106 `_verify_platform_signature`: signature 缺 + secret 空 `return not secret` (即 True)

  比 F#7 (booking webhook) silent skip 更严重 — 这里是**明确放行**（fail-OPEN vs fail-closed）。

  来源: gateway-pay-callback-whitelist PR 第 2 轮 reviewer agent F#10 verdict（P1，建议独立 PR）。

  风险评估:
  - 当前 omni_channel webhook 路径 `/api/v1/omni/webhook/{platform}` **不在** gateway
    AUTH_EXEMPT_PREFIXES 范围内（gateway 白名单收窄到 `/api/v1/webhook` + `/api/v1/booking/webhook`），
    所以 attack vector 需 JWT 突破 = 内部权限提升问题，非公网攻击面
  - 但若未来 gateway 把 omni webhook 加入白名单 / 内部凭证泄露 → 任意公网/内部请求可灌单到 omni_channel_service.handle_incoming
  - 设计上 fail-OPEN 是错误防御范式（应"配置错误 → 拒绝服务"而非"配置错误 → 放行所有"）

衍生 bug 同 PR 修:
  - `_PLATFORM_SECRETS` 是 module-level dict 在 import 时一次性读 env （line 42-46），
    导致 (1) prod 改 env 需重启服务 (2) 测试无法 patch env。
    本 PR 改为函数 `_get_platform_secret(platform)` lazy lookup。

修复要求 (本 PR):
  - 删 3 个 verifier 内 `if not secret: return True` (line 58-60 / 67-69 / 76-78)
  - 删 `_verify_platform_signature` 内 `return not secret` (line 106 第 4 处 fail-open)
  - 加 `_verify_platform_signature` 内 `if not secret: raise HTTPException(503, error.code={PLATFORM}_WEBHOOK_SECRET_NOT_CONFIGURED)` + Retry-After: 300
  - 删 module-level `_PLATFORM_SECRETS` dict，改 `_get_platform_secret(platform)` lazy lookup
  - structlog ERROR 级别（不是 warning）

测试策略 (与 F#7 同模式):
  - 单元 (3): 3 platform 各空 secret → _verify_platform_signature raise 503
  - 单元 (1): error code 契约 + Retry-After 契约
  - 集成 (1): POST /api/v1/omni/webhook/meituan 空 secret → 503
  - 不回归 (1): secret 有值 + 缺签名 → 既有 401 路径不变

运行方法:
  cd services/tx-trade
  PYTHONPATH=src python3 -m pytest src/tests/test_omni_channel_fail_closed_tier1.py -v
"""

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 路径准备（沿用 src/tests pattern）────────────────────────────────────────
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

# Stub tenacity (transitively pulled by shared/adapters/base via omni_channel_service)
# — not installed in local Python 3.11; only used by service-layer retry decorator
# which isn't on our fail-closed code path.
if "tenacity" not in sys.modules:
    _tenacity_stub = types.ModuleType("tenacity")
    _tenacity_stub.retry = lambda *a, **kw: (lambda f: f)  # type: ignore[attr-defined]
    _tenacity_stub.stop_after_attempt = lambda *a, **kw: None  # type: ignore[attr-defined]
    _tenacity_stub.wait_exponential = lambda *a, **kw: None  # type: ignore[attr-defined]
    sys.modules["tenacity"] = _tenacity_stub

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from shared.ontology.src.database import get_db  # noqa: E402

from src.api.omni_channel_routes import (  # type: ignore[import]  # noqa: E402
    _verify_platform_signature,
    router,
)

# ─── 测试工具 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())

_HEADERS = {"X-Tenant-ID": TENANT_ID, "X-Store-ID": STORE_ID}


def _make_app():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def _override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_db
    return app


def _env_with_only(keep: dict) -> dict:
    """返回 env dict，排除所有 *_WEBHOOK_SECRET keys 后注入 keep"""
    base = {
        k: v
        for k, v in os.environ.items()
        if not k.endswith("_WEBHOOK_SECRET")
    }
    base.update(keep)
    return base


# ─── Unit Tests: _verify_platform_signature 直接调用 ────────────────────────


@pytest.mark.parametrize(
    "platform,env_key",
    [
        ("meituan", "MEITUAN_WEBHOOK_SECRET"),
        ("eleme", "ELEME_WEBHOOK_SECRET"),
        ("douyin", "DOUYIN_WEBHOOK_SECRET"),
    ],
)
def test_empty_secret_raises_503(platform, env_key):
    """3 platform 各自空 {PLATFORM}_WEBHOOK_SECRET 时 _verify_platform_signature 必须 raise 503"""
    request = MagicMock(spec=Request)
    request.headers = {}

    with patch.dict(os.environ, _env_with_only({}), clear=True):
        with pytest.raises(HTTPException) as exc_info:
            _verify_platform_signature(platform, b"{}", request)

    assert exc_info.value.status_code == 503, (
        f"platform={platform} 空 secret 应 raise 503 (fail-closed F#10)，"
        f"实际 {exc_info.value.status_code}"
    )


def test_error_code_string_contract():
    """error code 必须为 {PLATFORM}_WEBHOOK_SECRET_NOT_CONFIGURED（告警规则依赖）"""
    request = MagicMock(spec=Request)
    request.headers = {}

    with patch.dict(os.environ, _env_with_only({}), clear=True):
        with pytest.raises(HTTPException) as exc_info:
            _verify_platform_signature("meituan", b"{}", request)

    code = exc_info.value.detail["error"]["code"]
    assert code == "MEITUAN_WEBHOOK_SECRET_NOT_CONFIGURED", (
        f"error code 必须为 MEITUAN_WEBHOOK_SECRET_NOT_CONFIGURED，实际 {code}"
    )


def test_retry_after_header_contract():
    """503 必须附 Retry-After: 300 (与 F#7 booking webhook fail-closed 一致防 storm)"""
    request = MagicMock(spec=Request)
    request.headers = {}

    with patch.dict(os.environ, _env_with_only({}), clear=True):
        with pytest.raises(HTTPException) as exc_info:
            _verify_platform_signature("douyin", b"{}", request)

    headers = exc_info.value.headers
    assert headers is not None and headers.get("Retry-After") == "300", (
        f"503 必须附 Retry-After=300 (防第三方 storm)，实际 headers={headers}"
    )


# ─── Integration Test: endpoint POST 空 secret → 503 ───────────────────────


def test_endpoint_empty_secret_returns_503_via_meituan_webhook():
    """POST /api/v1/omni/webhook/meituan + 空 secret → 503 (端到端验 fail-closed)

    防御场景: 未来若 gateway 把 /api/v1/omni/webhook 加入 AUTH_EXEMPT_PREFIXES 或
    内部凭证泄露后, prod 漏配 MEITUAN_WEBHOOK_SECRET 不得让 omni_channel_service 被灌单。
    """
    app = _make_app()
    client = TestClient(app)

    with patch.dict(os.environ, _env_with_only({}), clear=True):
        resp = client.post(
            "/api/v1/omni/webhook/meituan",
            headers=_HEADERS,
            content=b'{"order_id": "test_order"}',
        )

    assert resp.status_code == 503, (
        f"空 MEITUAN_WEBHOOK_SECRET 应返 503 (fail-closed)，实际 {resp.status_code} body={resp.text}"
    )
    assert resp.headers.get("Retry-After") == "300", (
        f"503 必须附 Retry-After=300，实际 headers={dict(resp.headers)}"
    )


# ─── 不回归: secret 有值 + 缺签名 → 既有 401 路径不变 ──────────────────────


def test_endpoint_valid_secret_missing_signature_returns_401_dict_format():
    """MEITUAN_WEBHOOK_SECRET 有值 + 缺 X-Meituan-Signature → 401 + detail dict format (F#12)

    F#12 reviewer follow-up: 401 detail 从 str "签名验证失败" 改为 dict
    {"ok": False, "data": None, "error": {"code": "INVALID_SIGNATURE"}} —
    与 503 fail-closed dict format 统一, API 消费者无需 type-check 4xx/5xx 错误体。
    """
    app = _make_app()
    client = TestClient(app)

    with patch.dict(
        os.environ, _env_with_only({"MEITUAN_WEBHOOK_SECRET": "test_meituan_secret"}), clear=True
    ):
        resp = client.post(
            "/api/v1/omni/webhook/meituan",
            headers=_HEADERS,  # 故意不带 X-Meituan-Signature
            content=b'{"order_id": "test_order"}',
        )

    assert resp.status_code == 401, (
        f"secret 有值 + 缺签名应 401 (既有签名验证失败路径)，实际 {resp.status_code} body={resp.text}"
    )
    # F#12 契约: detail 必须是 dict 含 error.code
    body = resp.json()
    detail = body.get("detail")
    assert isinstance(detail, dict), (
        f"401 detail 必须是 dict (与 503 fail-closed 一致), 实际 type={type(detail)} value={detail}"
    )
    assert detail.get("error", {}).get("code") == "INVALID_SIGNATURE", (
        f"401 error code 必须为 INVALID_SIGNATURE, 实际 detail={detail}"
    )


# ─── F#11: PLATFORMS / _SIGNATURE_VERIFIERS 同步性 startup check ───────────


def test_platforms_and_verifiers_in_sync():
    """F#11 reviewer follow-up: PLATFORMS 与 _SIGNATURE_VERIFIERS 必须严格同步

    防御场景: 未来加新 platform 时若忘记注册 verifier, _verify_platform_signature
    走 `return False` 静默回 401, secret check 已通过 = 验签被悄然绕过。
    Module-level startup check (omni_channel_routes.py) 强制不一致时 RuntimeError。
    """
    from src.api.omni_channel_routes import _SIGNATURE_VERIFIERS
    from src.services.omni_channel_service import OmniChannelService

    assert set(OmniChannelService.PLATFORMS) == set(_SIGNATURE_VERIFIERS.keys()), (
        f"PLATFORMS {sorted(OmniChannelService.PLATFORMS)} 与 _SIGNATURE_VERIFIERS keys "
        f"{sorted(_SIGNATURE_VERIFIERS.keys())} 不同步 — 加新 platform 时必须同时注册 verifier"
    )
