"""Tests for shared.security.src.error_handler

Verifies the core contract of the central secure error handler:
1. External responses NEVER contain raw exception text.
2. Same internal exception produces different correlation_ids each call.
3. safe_http_exception returns the correct HTTP status code.
4. log_and_raise always raises HTTPException.
5. Stack-trace information is NOT leaked into the response detail.
6. generic_message returns a safe fallback string.
"""

import re

import pytest
from fastapi import HTTPException

from shared.security.src.error_handler import (
    generic_message,
    log_and_raise,
    safe_http_exception,
)

# ──────────────────────────────────────────────────────────────────────────────
# 1. Response never contains raw exception text
# ──────────────────────────────────────────────────────────────────────────────


def test_response_does_not_contain_exception_message():
    """detail must not expose the raw exception string to callers."""
    internal = ValueError("column 'tenant_id' of relation 'orders' does not exist")
    exc = safe_http_exception(400, "请求参数无效", internal)

    detail_str = str(exc.detail)
    assert "tenant_id" not in detail_str
    assert "orders" not in detail_str
    assert "does not exist" not in detail_str


def test_response_contains_safe_public_message():
    """detail['error'] must equal the public_msg argument exactly."""
    exc = safe_http_exception(404, "资源不存在")
    assert exc.detail["error"] == "资源不存在"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Each call produces a unique correlation_id
# ──────────────────────────────────────────────────────────────────────────────


def test_correlation_ids_are_unique_across_calls():
    """Two calls with the same exception must produce different correlation_ids."""
    internal = ValueError("same error")
    exc1 = safe_http_exception(400, "请求参数无效", internal)
    exc2 = safe_http_exception(400, "请求参数无效", internal)

    cid1 = exc1.detail["correlation_id"]
    cid2 = exc2.detail["correlation_id"]
    assert cid1 != cid2, "correlation_id must be unique per call, got same value"


def test_correlation_id_format():
    """correlation_id must be a 12-character hex string."""
    exc = safe_http_exception(500, "服务器内部错误")
    cid = exc.detail["correlation_id"]
    assert re.fullmatch(r"[0-9a-f]{12}", cid), f"Unexpected correlation_id format: {cid!r}"


# ──────────────────────────────────────────────────────────────────────────────
# 3. HTTP status code is set correctly
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 409, 500, 502, 503])
def test_status_code_propagated(status_code: int):
    exc = safe_http_exception(status_code, "操作失败")
    assert exc.status_code == status_code


# ──────────────────────────────────────────────────────────────────────────────
# 4. log_and_raise always raises HTTPException
# ──────────────────────────────────────────────────────────────────────────────


def test_log_and_raise_raises_http_exception():
    with pytest.raises(HTTPException) as exc_info:
        log_and_raise(400, "请求参数无效", ValueError("internal detail"))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "请求参数无效"


def test_log_and_raise_without_exception():
    """log_and_raise must work even when no internal exception is provided."""
    with pytest.raises(HTTPException) as exc_info:
        log_and_raise(403, "权限不足")
    assert exc_info.value.status_code == 403


# ──────────────────────────────────────────────────────────────────────────────
# 5. Stack trace information is NOT in the response
# ──────────────────────────────────────────────────────────────────────────────


def test_no_traceback_in_response():
    """Even a nested exception must not produce traceback text in detail."""
    try:
        raise RuntimeError("internal: db connection pool exhausted at host=db.internal")
    except RuntimeError as e:
        exc = safe_http_exception(500, "服务器内部错误", e)

    detail_str = str(exc.detail)
    assert "Traceback" not in detail_str
    assert "RuntimeError" not in detail_str
    assert "db.internal" not in detail_str
    assert "pool exhausted" not in detail_str


# ──────────────────────────────────────────────────────────────────────────────
# 6. generic_message returns safe fallback
# ──────────────────────────────────────────────────────────────────────────────


def test_generic_message_known_codes():
    assert generic_message(400) == "请求参数无效"
    assert generic_message(404) == "资源不存在"
    assert generic_message(500) == "服务器内部错误"


def test_generic_message_unknown_code():
    msg = generic_message(418)
    assert isinstance(msg, str) and len(msg) > 0


# ──────────────────────────────────────────────────────────────────────────────
# 7. extra fields are NOT leaked to response
# ──────────────────────────────────────────────────────────────────────────────


def test_extra_fields_not_in_response():
    """Internal extra fields like tenant_id must not appear in the response body."""
    exc = safe_http_exception(
        400,
        "请求参数无效",
        ValueError("internal"),
        extra={"tenant_id": "secret-uuid-here", "table": "orders"},
    )
    detail_str = str(exc.detail)
    assert "secret-uuid-here" not in detail_str
    assert "orders" not in detail_str
