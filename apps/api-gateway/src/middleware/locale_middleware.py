"""
Locale 中间件

从 Accept-Language header 或用户 profile 识别 locale，注入到 request.state.locale
"""

from __future__ import annotations

from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

SUPPORTED_LOCALES = {
    "zh-CN",
    "zh-TW",
    "en-US",
    "vi-VN",
    "th-TH",
    "id-ID",
}
DEFAULT_LOCALE = "zh-CN"


def _parse_accept_language(header_value: str) -> Iterable[str]:
    """解析 Accept-Language: zh-CN,zh;q=0.9,en;q=0.8"""
    for part in header_value.split(","):
        lang = part.split(";", 1)[0].strip()
        if lang:
            yield lang


def _normalize(lang: str) -> str:
    """zh → zh-CN；en → en-US；zh-HK → zh-TW"""
    low = lang.lower()
    if low.startswith("zh-hk") or low.startswith("zh-tw"):
        return "zh-TW"
    if low == "zh" or low.startswith("zh-cn") or low.startswith("zh-"):
        return "zh-CN"
    if low == "en" or low.startswith("en-"):
        return "en-US"
    if low.startswith("vi"):
        return "vi-VN"
    if low.startswith("th"):
        return "th-TH"
    if low.startswith("id"):
        return "id-ID"
    return DEFAULT_LOCALE


class LocaleMiddleware(BaseHTTPMiddleware):
    """识别请求 locale 并注入 request.state.locale"""

    async def dispatch(self, request: Request, call_next):
        locale = DEFAULT_LOCALE

        # 1) 显式 query param 优先（方便调试）
        qp = request.query_params.get("locale")
        if qp and qp in SUPPORTED_LOCALES:
            locale = qp
        else:
            # 2) Accept-Language header
            header = request.headers.get("accept-language", "")
            for lang in _parse_accept_language(header):
                norm = _normalize(lang)
                if norm in SUPPORTED_LOCALES:
                    locale = norm
                    break

        request.state.locale = locale
        response = await call_next(request)
        response.headers["Content-Language"] = locale
        return response
