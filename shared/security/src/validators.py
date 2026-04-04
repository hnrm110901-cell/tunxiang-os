"""统一输入验证工具 -- OWASP Top 10 防护

纯 Python 实现，零外部依赖。覆盖：
- SQL 注入：参数格式校验 + UUID/手机号/邮箱白名单
- XSS：HTML 标签清理
- 路径遍历：文件名清理
- SSRF：URL 白名单
"""

import re
import uuid as _uuid
from datetime import date, timedelta
from typing import Optional
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# 内部常量
# ---------------------------------------------------------------------------

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9\u4e00-\u9fff._\-]")
# 基本格式标签白名单（sanitize_html 保留这些）
_ALLOWED_TAGS = {"b", "i", "u", "em", "strong", "br", "p", "ul", "ol", "li"}
_TAG_RE = re.compile(r"<(/?)(\w+)([^>]*)>", re.IGNORECASE)
_DATE_FMT = "%Y-%m-%d"


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def sanitize_string(value: str, max_length: int = 500) -> str:
    """清理字符串输入：去除控制字符、限制长度。

    Raises:
        ValueError: 如果 value 不是字符串。
    """
    if not isinstance(value, str):
        raise ValueError("expected str")
    cleaned = _CONTROL_CHAR_RE.sub("", value)
    return cleaned[:max_length]


def validate_uuid(value: str) -> str:
    """验证 UUID 格式，防止注入。

    Raises:
        ValueError: 格式不合法。
    """
    try:
        return str(_uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"invalid UUID: {value!r}") from exc


def validate_phone(value: str) -> str:
    """验证手机号格式（中国 11 位）。

    Raises:
        ValueError: 格式不合法。
    """
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _PHONE_RE.match(cleaned):
        raise ValueError(f"invalid phone: {value!r}")
    return cleaned


def validate_email(value: str) -> str:
    """验证邮箱格式。

    Raises:
        ValueError: 格式不合法。
    """
    cleaned = value.strip().lower()
    if len(cleaned) > 254 or not _EMAIL_RE.match(cleaned):
        raise ValueError(f"invalid email: {value!r}")
    return cleaned


def sanitize_filename(value: str) -> str:
    """清理文件名：防止路径遍历（../）。

    - 移除所有路径分隔符和 ``..``
    - 仅保留中英文、数字、点、下划线、连字符
    - 空文件名会抛异常

    Raises:
        ValueError: 清理后文件名为空。
    """
    # 先去掉路径部分
    name = value.replace("\\", "/").split("/")[-1]
    # 去掉 .. 片段
    name = name.replace("..", "")
    # 替换不安全字符
    name = _SAFE_FILENAME_RE.sub("_", name)
    # 去掉前导点（隐藏文件）
    name = name.lstrip(".")
    if not name:
        raise ValueError("filename is empty after sanitization")
    return name


def validate_url(
    value: str, allowed_hosts: Optional[list[str]] = None
) -> str:
    """验证 URL：防止 SSRF（只允许白名单域名）。

    Raises:
        ValueError: scheme 非 http(s)、域名不在白名单、或格式错误。
    """
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"invalid URL scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise ValueError("URL missing hostname")
    # 阻止内网地址
    hostname = parsed.hostname.lower()
    _reject_internal_host(hostname)
    if allowed_hosts is not None:
        if hostname not in [h.lower() for h in allowed_hosts]:
            raise ValueError(
                f"host {hostname!r} not in allowed list"
            )
    return value


def sanitize_html(value: str) -> str:
    """清理 HTML 标签，防止 XSS（保留基本格式标签）。

    保留白名单标签（b/i/u/em/strong/br/p/ul/ol/li），
    移除其余所有标签及其属性。
    """

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        slash, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if tag in _ALLOWED_TAGS:
            # 保留标签但去掉所有属性（防止 on* 事件注入）
            return f"<{slash}{tag}>"
        return ""

    return _TAG_RE.sub(_replace, value)


def validate_amount_fen(value: int) -> int:
    """验证金额（分）：必须非负，上限 1 亿元（10_000_000_00 分）。

    Raises:
        ValueError: 不合法金额。
    """
    if not isinstance(value, int):
        raise ValueError("amount must be int")
    if value < 0:
        raise ValueError("amount must be non-negative")
    if value > 10_000_000_00:
        raise ValueError("amount exceeds 1亿元 limit")
    return value


def validate_page_params(page: int, size: int) -> tuple[int, int]:
    """验证分页参数：page >= 1, 1 <= size <= 100。

    Raises:
        ValueError: 参数越界。
    """
    if not isinstance(page, int) or page < 1:
        raise ValueError("page must be >= 1")
    if not isinstance(size, int) or size < 1 or size > 100:
        raise ValueError("size must be between 1 and 100")
    return page, size


def validate_date_range(start: str, end: str) -> tuple[str, str]:
    """验证日期范围：start <= end，跨度不超过 1 年。

    日期格式：YYYY-MM-DD

    Raises:
        ValueError: 格式错误、start > end、或跨度超过 365 天。
    """
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid date format, expected YYYY-MM-DD") from exc
    if start_date > end_date:
        raise ValueError("start date must be <= end date")
    if (end_date - start_date) > timedelta(days=365):
        raise ValueError("date range exceeds 1 year")
    return start, end


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _reject_internal_host(hostname: str) -> None:
    """拒绝内网 / 回环 / 元数据地址，防止 SSRF。"""
    import ipaddress

    # 常见内网 / 云元数据域名
    blocked_hosts = {
        "localhost",
        "metadata.google.internal",
        "169.254.169.254",
    }
    if hostname in blocked_hosts:
        raise ValueError(f"internal host blocked: {hostname!r}")

    # 尝试解析为 IP 判断是否内网
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise ValueError(f"internal IP blocked: {hostname!r}")
    except ValueError:
        # 不是 IP 地址，是正常域名，放行
        if hostname.endswith(".internal") or hostname.endswith(".local"):
            raise ValueError(f"internal host blocked: {hostname!r}")
