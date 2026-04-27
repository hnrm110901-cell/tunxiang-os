"""容错解析 Sonnet 输出 — 从 D4a/D4b/D4c 三份服务抽取的共用逻辑

Anthropic 输出结构：
    {
      "content": [{"type": "text", "text": "..."}, ...],
      "usage": {...}
    }

Sonnet 有时会在 JSON 外包 markdown 代码块（```json ... ```），偶尔会多一段说明
文本。本模块提供：

  · extract_text_from_content — 从 content blocks 拼出原始文本
  · parse_json_response — 容错解析成 dict（剥离 code fence + JSON 失败返回 {}）
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

# 支持：
#   ```json\n{...}\n```
#   ```\n{...}\n```
#   ```{...}```
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def extract_text_from_content(content: Any) -> str:
    """从 Anthropic response["content"] 字段拼出纯文本。

    content 可能是：
      · List[{"type": "text", "text": "..."}, ...]
      · str（旧版 API 或 fake 实现）
      · None（空响应）

    忽略 non-text block（如 tool_use / image），只拼接 type='text' 的文本。
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, Iterable):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, Mapping) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def parse_json_response(raw: str | None) -> dict[str, Any]:
    """容错解析 Sonnet 输出的 JSON 字符串。

    步骤：
      1. 去除首尾空白
      2. 若被 ```json ... ``` 或 ``` ... ``` 包裹，剥离
      3. json.loads，失败返回 {}（不抛异常，交由调用方决定是否降级）

    注：返回值永远是 dict，即便原 JSON 是 list，也会被丢弃。这是刻意设计——
    D4 三个服务都期望顶层是 dict（包含 predicted_items / variance_risks 等 key）。
    """
    if not raw or not raw.strip():
        return {}

    stripped = raw.strip()
    match = _CODE_FENCE_RE.match(stripped)
    if match:
        stripped = match.group(1).strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        logger.warning(
            "prompt_cache_json_parse_failed",
            extra={"error": str(exc), "raw_preview": raw[:200]},
        )
        return {}

    if not isinstance(parsed, dict):
        logger.warning(
            "prompt_cache_non_dict_response",
            extra={"type": type(parsed).__name__},
        )
        return {}

    return parsed


def parse_response(response: Mapping[str, Any]) -> dict[str, Any]:
    """便捷函数：直接从 Anthropic response 解析 JSON。

    等价于：
        text = extract_text_from_content(response["content"])
        return parse_json_response(text)
    """
    text = extract_text_from_content(response.get("content"))
    return parse_json_response(text)
