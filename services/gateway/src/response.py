"""统一响应格式 — { "ok": bool, "data": {}, "error": {} }"""
from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": True, "data": data, "error": None},
    )


def err(message: str, code: str = "INTERNAL_ERROR", status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "data": None, "error": {"code": code, "message": message}},
    )


def paginated(items: list, total: int, page: int = 1, size: int = 20) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "data": {"items": items, "total": total, "page": page, "size": size},
            "error": None,
        },
    )
