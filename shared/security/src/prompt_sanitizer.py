"""LLM Prompt Injection 防护 — sanitize 用户可控字段

防御策略：strip silently（不 raise） — 在用户字段被拼进 LLM system prompt 前
剥离已知 prompt-injection pattern，保留正常品牌内容。

四类 attack vector：
1. 中文 prompt-injection 关键词（忽略上述/系统/指令）
2. 英文 prompt-injection 关键词（IGNORE PREVIOUS/SYSTEM PROMPT/disregard）
3. XML 隔离绕过（</tenant_brand_data> / <system_authority> 等）
4. Unicode 隐藏字符（ZWSP/RLO/BOM 等）

加上：
- 控制字符（保留 \\n \\t \\r）
- 单字段长度 cap

起源：CSO 2026-05-11 finding F#5（brand_strategy prompt injection），
docs/audit/brand-strategy-prompt-injection-2026-05-11.md
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# 攻击 pattern 编译（class-private — 不暴露给外部，避免 fingerprinting）
# ---------------------------------------------------------------------------

# 控制字符：保留 \t (0x09) \n (0x0a) \r (0x0d)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Unicode 隐藏字符（zero-width / direction-override / BOM）
# - U+200B-U+200F: zero-width chars
# - U+202A-U+202E: bidirectional override
# - U+2060-U+2064: word joiner / invisible operators
# - U+FEFF: BOM / zero-width no-break space
_HIDDEN_UNICODE_RE = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")

# 中文 prompt-injection 关键词
_ZH_INJECTION_PATTERNS = [
    r"忽略上述[^\n]*",
    r"忽略以上[^\n]*",
    r"忽略所有[^\n]*",
    r"忽略先前[^\n]*",
    r"忽略之前[^\n]*",
    r"请忽略[^\n]*",
    r"#\s*系统[：:][^\n]*",
    r"#\s*指令[：:][^\n]*",
    r"#\s*新指令[：:][^\n]*",
    r"#\s*重要[：:][^\n]*",
    r"以下是新的\s*system\s*prompt[^\n]*",
    r"new\s*system\s*prompt[^\n]*",
]
_ZH_INJECTION_RE = re.compile("|".join(_ZH_INJECTION_PATTERNS), re.IGNORECASE)

# 英文 prompt-injection 关键词
_EN_INJECTION_PATTERNS = [
    r"ignore\s+previous[^\n]*",
    r"ignore\s+above[^\n]*",
    r"ignore\s+all[^\n]*",
    r"ignore\s+prior[^\n]*",
    r"disregard[^\n]*",
    r"#\s*system\s*:[^\n]*",
    r"#\s*assistant\s*:[^\n]*",
    r"#\s*important\s*:[^\n]*",
    r"system\s+prompt\s*:[^\n]*",
    r"new\s+instructions?\s*:[^\n]*",
    r"override\s+(previous|all|above)[^\n]*",
]
_EN_INJECTION_RE = re.compile("|".join(_EN_INJECTION_PATTERNS), re.IGNORECASE)

# XML 隔离 tag（开/闭合都剥离 — 用户内容不应该含这些）
_XML_ISOLATION_PATTERNS = [
    r"</?tenant_brand_data\s*/?>",
    r"</?user_brand_data\s*/?>",
    r"</?system_authority\s*/?>",
    r"</?system\s*/?>",
    r"</?assistant\s*/?>",
    r"</?instructions\s*/?>",
]
_XML_ISOLATION_RE = re.compile("|".join(_XML_ISOLATION_PATTERNS), re.IGNORECASE)


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def sanitize_for_prompt(value: Any, max_chars: int = 500) -> Any:
    """剥离 prompt-injection pattern 后返回安全值，递归处理 list / dict。

    Args:
        value:     用户可控值。可为 str / list / dict / None / int / float / bool。
        max_chars: 单字段最大字符数（仅作用于 str / list / dict 的 str 元素）。
                   默认 500，调用方按字段类型传入更紧的 cap（如 brand_slogan=200）。

    Returns:
        同类型清理结果。str 被过滤+截断；list/dict 递归；其他类型原样返回。

    Behavior:
        - strip silently：不 raise，安全 fallback 为正常字符串
        - dict 的 keys 不 sanitize（schema 定义，非用户可控）
        - 中英文混合可同时过滤
        - 过滤后再 truncate（避免 cap 让 attack pattern 漏过）
    """
    if value is None:
        return None
    if isinstance(value, str):
        return _sanitize_str(value, max_chars)
    if isinstance(value, list):
        return [sanitize_for_prompt(item, max_chars) for item in value]
    if isinstance(value, dict):
        return {k: sanitize_for_prompt(v, max_chars) for k, v in value.items()}
    # int / float / bool — 不可能携带 prompt injection，原样返回
    return value


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _sanitize_str(value: str, max_chars: int) -> str:
    """str 字段清理顺序：
    1. 剥离 Unicode 隐藏字符（避免后续 regex 被绕过）
    2. 剥离控制字符（保留 \\n \\t \\r）
    3. 剥离中英文 prompt-injection 关键词整行
    4. 剥离 XML 隔离 tag
    5. 截断到 max_chars
    """
    if max_chars <= 0:
        return ""
    cleaned = _HIDDEN_UNICODE_RE.sub("", value)
    cleaned = _CONTROL_CHAR_RE.sub("", cleaned)
    cleaned = _ZH_INJECTION_RE.sub("", cleaned)
    cleaned = _EN_INJECTION_RE.sub("", cleaned)
    cleaned = _XML_ISOLATION_RE.sub("", cleaned)
    return cleaned[:max_chars]
