"""Central secure error handler — prevents internal exception detail leakage.

Design contract:
  - Public-facing API responses NEVER contain raw exception messages, SQL
    error strings, internal paths, or stack frames.
  - Every raised HTTPException is accompanied by a structured internal log
    (via structlog) that includes exc_info so stack traces appear in logs.
  - Each error response includes a unique correlation_id so callers can
    reference it with support without exposing internals.

Usage in route handlers::

    from shared.security.src.error_handler import safe_http_exception, log_and_raise

    # Replace:  raise HTTPException(status_code=400, detail=str(e))
    # With:     raise safe_http_exception(400, "请求参数无效", e)

    # Or use the one-liner helper that logs + raises in one call:
    except ValueError as e:
        log_and_raise(400, "请求参数无效", e)
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import HTTPException

_logger = structlog.get_logger("security.error_handler")

# Map HTTP status codes to safe generic messages (Chinese, matching project convention)
_GENERIC_MESSAGES: dict[int, str] = {
    400: "请求参数无效",
    401: "认证失败",
    403: "权限不足",
    404: "资源不存在",
    409: "操作冲突",
    422: "请求格式错误",
    429: "请求过于频繁",
    500: "服务器内部错误",
    502: "上游服务不可用",
    503: "服务暂时不可用",
    504: "上游服务超时",
}


def _new_correlation_id() -> str:
    """Generate a short correlation id for cross-referencing logs and responses."""
    return uuid.uuid4().hex[:12]


def safe_http_exception(
    status_code: int,
    public_msg: str,
    internal_exc: BaseException | None = None,
    *,
    extra: dict[str, Any] | None = None,
) -> HTTPException:
    """Build an HTTPException that is safe to return to API callers.

    The *internal_exc* (if provided) is logged with full exc_info so the
    complete traceback appears in structured logs, but NEVER in the response.
    The response body only contains *public_msg* and a *correlation_id*.

    Args:
        status_code: HTTP status code to use.
        public_msg: Human-readable message safe to show the caller.  It must
            NOT contain raw exception text, DB column names, internal paths,
            or user-supplied input that could be reflected back.
        internal_exc: The original exception — logged but never serialised
            into the response.
        extra: Optional extra structured fields to attach to the log entry
            (e.g. tenant_id, resource_id).  These are NOT in the response.

    Returns:
        An HTTPException ready to be raised.  The ``detail`` field contains
        only ``{"error": public_msg, "correlation_id": "<hex>"}`` — no raw
        exception data.
    """
    correlation_id = _new_correlation_id()

    log = _logger.bind(
        status_code=status_code,
        correlation_id=correlation_id,
        **(extra or {}),
    )

    if internal_exc is not None:
        log.warning(
            "safe_http_exception",
            public_msg=public_msg,
            exc_type=type(internal_exc).__name__,
            exc_info=True,
        )
    else:
        log.warning("safe_http_exception", public_msg=public_msg)

    return HTTPException(
        status_code=status_code,
        detail={"error": public_msg, "correlation_id": correlation_id},
    )


def log_and_raise(
    status_code: int,
    public_msg: str,
    internal_exc: BaseException | None = None,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    """Convenience wrapper: log internally, raise safe HTTPException.

    This is the one-liner equivalent of::

        raise safe_http_exception(status_code, public_msg, e)

    Typical usage::

        except ValueError as e:
            log_and_raise(400, "请求参数无效", e)

    Never returns; always raises.
    """
    raise safe_http_exception(status_code, public_msg, internal_exc, extra=extra)


def generic_message(status_code: int) -> str:
    """Return the canonical generic message for a given HTTP status code.

    Falls back to "操作失败" for unmapped codes.
    """
    return _GENERIC_MESSAGES.get(status_code, "操作失败")
