"""测试 proxy.py UPSTREAM_NON_JSON 路径 (PR #616 §19 P2 follow-up — issue #606)

PR #616 修法：`resp.json()` 抛 `httpx.DecodingError` / `ValueError` /
`UnicodeDecodeError` 时，保留下游 status code + 返回结构化 UPSTREAM_NON_JSON
错误体（不再强制 502）+ log warning 含 body preview + upstream URL。

本测覆盖 issue #606 验收清单：
  T1. text/plain 502 nginx body → 502 + UPSTREAM_NON_JSON, status 透传
  T2. application/octet-stream binary (KDS ESC/POS) → status 透传 + 结构化错误
  T3. 异常字符编码（UnicodeDecodeError）→ UPSTREAM_NON_JSON
  T4. 控制组：合法 JSON 直通透传，不进入 fallback

回归防护 — 防止后续误改 except 子句缩窄到只捕 ValueError 时漏 httpx.DecodingError
（PR #621 §19 reviewer 指出的 MRO 不继承陷阱 — DecodingError 不是 ValueError 子类）。
"""

from __future__ import annotations

import json
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

# gateway 测试模式：sys.path 加 src/..，直接 import 模块（参考 test_brand_management.py）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import proxy  # noqa: E402


@pytest.fixture
def patched_pool(monkeypatch):
    """Mock _http_pool.request 为可控 AsyncMock。"""
    mock_pool = MagicMock()
    mock_pool.request = AsyncMock()
    monkeypatch.setattr(proxy, "_http_pool", mock_pool)

    # 防御：若 PYTHONPATH 含仓库根（pytest collect 时偶然），避免 mint_internal_jwt
    # 真实调用引发 jwt secret missing 等 RuntimeError。注入一个 no-op fake module。
    fake_jwt = types.ModuleType("shared.security.src.internal_jwt")
    fake_jwt.mint_internal_jwt = lambda **_: ""
    monkeypatch.setitem(sys.modules, "shared.security.src.internal_jwt", fake_jwt)

    return mock_pool


def _make_request(method: str = "GET", path: str = "/api/test"):
    """构造最小 FastAPI Request stand-in（仅含 _proxy 用到的属性）。"""
    request = MagicMock()
    request.method = method
    request.url = MagicMock()
    request.url.path = path
    # headers.items() 必须返回 iterable of (name, value) tuple
    request.headers = MagicMock()
    request.headers.items = lambda: [("user-agent", "pytest")]
    request.query_params = {}
    # state attrs 全空 → JWT 头不构造，路径走 fallback ImportError
    request.state = MagicMock()
    request.state.tenant_id = ""
    request.state.user_id = ""
    request.state.role = ""

    async def _body() -> bytes:
        return b""

    request.body = _body
    return request


def _make_response(status_code: int, content: bytes, json_side_effect):
    """构造 httpx.Response stand-in；json_side_effect 是 .json() 要抛的异常。"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.json = MagicMock(side_effect=json_side_effect)
    return resp


def _decode_response_body(response) -> dict:
    """JSONResponse.body 是 bytes，解析回 dict。"""
    return json.loads(response.body)


# ─── T1: text/plain 502 nginx → UPSTREAM_NON_JSON ────────────


@pytest.mark.asyncio
async def test_text_plain_502_returns_upstream_non_json_with_status_preserved(patched_pool):
    """nginx 502 plain-text body → 保留 502 + UPSTREAM_NON_JSON 结构化错误。

    场景：上游 nginx 返回 502 Bad Gateway，body 是 HTML。`resp.json()` 抛
    `ValueError("Expecting value")`（json 模块原生）。proxy 必须保留下游 502
    （不强制改 502 — 本来就是 502，保留语义）+ 错误体含 upstream_status=502。
    """
    upstream_resp = _make_response(
        status_code=502,
        content=b"<html><body><h1>502 Bad Gateway</h1></body></html>",
        json_side_effect=ValueError("Expecting value"),
    )
    patched_pool.request.return_value = upstream_resp

    response = await proxy._proxy(_make_request(), "http://upstream:8001/api/test")

    assert response.status_code == 502, "下游 502 必须透传，不能强制改成别的"
    body = _decode_response_body(response)
    assert body["ok"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "UPSTREAM_NON_JSON"
    assert body["error"]["upstream_status"] == 502
    assert body["error"]["message"] == "Upstream returned non-JSON response"


# ─── T2: octet-stream binary (KDS ESC/POS) → UPSTREAM_NON_JSON ──


@pytest.mark.asyncio
async def test_octet_stream_binary_returns_upstream_non_json(patched_pool):
    """KDS ESC/POS 二进制 body → UPSTREAM_NON_JSON; status 200 透传。

    场景：tx-trade 打印队列接口返回 application/octet-stream 打印指令二进制。
    `httpx.DecodingError` （注意 MRO 不继承 ValueError，必须显式 catch — 见
    PR #621 §19 reviewer P1 防回归点）。
    """
    upstream_resp = _make_response(
        status_code=200,
        content=b"\x1b[40;1m\x00\x01\x02ESC/POS print job binary",
        json_side_effect=httpx.DecodingError("not json"),
    )
    patched_pool.request.return_value = upstream_resp

    response = await proxy._proxy(_make_request(path="/print/queue"), "http://upstream:8001/print/queue")

    assert response.status_code == 200, "下游 200 必须透传（即使 body 非 JSON）"
    body = _decode_response_body(response)
    assert body["error"]["code"] == "UPSTREAM_NON_JSON"
    assert body["error"]["upstream_status"] == 200


# ─── T3: bad utf-8 (UnicodeDecodeError) → UPSTREAM_NON_JSON ──


@pytest.mark.asyncio
async def test_bad_utf8_returns_upstream_non_json(patched_pool):
    """异常字符编码（GBK 字节 / UTF-8 解码失败）→ UPSTREAM_NON_JSON。

    场景：旧系统返回 GBK 编码中文字节，JSON 解析期 UnicodeDecodeError。
    `decode("utf-8", errors="replace")` 在 body_preview 构造时会容错，确保
    log 不抛二次异常（PR #616 实现细节）。
    """
    upstream_resp = _make_response(
        status_code=500,
        content=b"\xc4\xe3\xba\xc3 GBK chinese body",
        json_side_effect=UnicodeDecodeError("utf-8", b"\xc4\xe3", 0, 1, "invalid start byte"),
    )
    patched_pool.request.return_value = upstream_resp

    response = await proxy._proxy(_make_request(), "http://upstream:8011/api/legacy")

    assert response.status_code == 500
    body = _decode_response_body(response)
    assert body["error"]["code"] == "UPSTREAM_NON_JSON"
    assert body["error"]["upstream_status"] == 500


# ─── T4: 控制组 — valid JSON 直通透传 ────────────────────────


@pytest.mark.asyncio
async def test_valid_json_passes_through_unchanged(patched_pool):
    """控制组：合法 JSON 必须原样透传，不进入 UPSTREAM_NON_JSON fallback 路径。"""
    upstream_resp = MagicMock()
    upstream_resp.status_code = 200
    upstream_resp.content = b'{"data": [1, 2, 3]}'
    upstream_resp.json = MagicMock(return_value={"data": [1, 2, 3]})
    patched_pool.request.return_value = upstream_resp

    response = await proxy._proxy(_make_request(), "http://upstream:8001/api/items")

    assert response.status_code == 200
    body = _decode_response_body(response)
    assert body == {"data": [1, 2, 3]}, "合法 JSON 必须透传，不应被 wrapped"
    assert "error" not in body, "控制组不应进入 UPSTREAM_NON_JSON 分支"
