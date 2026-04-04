"""XSS 防护

纯 Python 实现，零外部依赖。提供：
1. HTML 实体转义
2. Script 标签检测
3. CSP Header 生成
"""

import re
from html import escape as _html_escape

# ---------------------------------------------------------------------------
# 内部常量
# ---------------------------------------------------------------------------

_SCRIPT_RE = re.compile(
    r"<\s*script[\s>]|<\s*/\s*script\s*>|javascript\s*:|on\w+\s*=",
    re.IGNORECASE,
)

# 事件处理器属性（onerror, onclick, onload ...）
_EVENT_HANDLER_RE = re.compile(r"\bon\w+\s*=", re.IGNORECASE)

# data: URI（可用于 XSS）
_DATA_URI_RE = re.compile(r"data\s*:\s*text/html", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def escape_html(value: str) -> str:
    """HTML 实体转义。

    将 ``<``, ``>``, ``&``, ``"``, ``'`` 转义为对应的 HTML 实体。
    这是最基本的 XSS 防护手段。
    """
    if not isinstance(value, str):
        raise ValueError("expected str")
    return _html_escape(value, quote=True)


def validate_no_script(value: str) -> str:
    """检测并拒绝包含 script 标签 / javascript 协议 / 事件处理器的输入。

    Raises:
        ValueError: 检测到潜在 XSS 攻击载荷。
    """
    if not isinstance(value, str):
        raise ValueError("expected str")
    if _SCRIPT_RE.search(value):
        raise ValueError("potential XSS detected: script/javascript pattern")
    if _EVENT_HANDLER_RE.search(value):
        raise ValueError("potential XSS detected: event handler attribute")
    if _DATA_URI_RE.search(value):
        raise ValueError("potential XSS detected: data URI")
    return value


def get_csp_header() -> str:
    """生成 Content-Security-Policy 头。

    策略说明：
    - default-src 'self'：默认只允许同源
    - script-src 'self'：脚本只允许同源（禁止 inline/eval）
    - style-src 'self' 'unsafe-inline'：样式允许 inline（Tailwind 需要）
    - img-src 'self' data: https:：图片允许同源、data URI、HTTPS
    - font-src 'self'：字体只允许同源
    - connect-src 'self'：XHR/Fetch 只允许同源
    - frame-ancestors 'none'：禁止被嵌入 iframe（防点击劫持）
    - base-uri 'self'：限制 <base> 标签
    - form-action 'self'：限制表单提交目标
    """
    directives = [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: https:",
        "font-src 'self'",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
    return "; ".join(directives)
