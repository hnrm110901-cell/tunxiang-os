"""Claude Citations 引擎 — 生成带引用定位的回答

集成 Anthropic Claude API 的 Citations 功能：
- 将检索到的知识块作为 source documents 传入
- Claude 回答时自动标注引用来源
- 返回答案 + 引用列表（定位到具体知识块 + 文本片段）
"""
from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

from .models import AnswerWithCitations, Citation

logger = structlog.get_logger()

_ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_API_URL = "https://api.anthropic.com/v1/messages"
_DEFAULT_MODEL = "claude-sonnet-4-6-20250514"
_TIMEOUT = 30.0


class CitationEngine:
    """Claude Citations 引用引擎"""

    @staticmethod
    async def answer_with_citations(
        query: str,
        source_chunks: list[dict[str, Any]],
        tenant_id: str,
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> AnswerWithCitations:
        """生成带引用的回答。

        Args:
            query: 用户查询
            source_chunks: 检索到的知识块列表 [{chunk_id, doc_id, text, metadata}]
            tenant_id: 租户ID
            model: Claude 模型（默认 sonnet）
            system_prompt: 系统提示词（可选）

        Returns:
            AnswerWithCitations 包含答案和引用列表
        """
        if not source_chunks:
            return AnswerWithCitations(
                answer="未找到相关知识，无法回答此问题。",
                citations=[],
                model_used="none",
            )

        if not _ANTHROPIC_API_KEY:
            # API key 不可用时，返回拼接结果
            return _fallback_answer(query, source_chunks)

        try:
            return await _call_claude_with_citations(
                query=query,
                source_chunks=source_chunks,
                model=model or _DEFAULT_MODEL,
                system_prompt=system_prompt,
            )
        except Exception as exc:
            logger.warning("citation_engine_error", error=str(exc), exc_info=True)
            return _fallback_answer(query, source_chunks)


async def _call_claude_with_citations(
    query: str,
    source_chunks: list[dict[str, Any]],
    model: str,
    system_prompt: str | None,
) -> AnswerWithCitations:
    """调用 Claude API（带 Citations）"""

    # 构建 source content blocks
    content_blocks: list[dict[str, Any]] = []

    for i, chunk in enumerate(source_chunks):
        # Document source block
        content_blocks.append({
            "type": "document",
            "source": {
                "type": "text",
                "media_type": "text/plain",
                "data": chunk.get("text", ""),
            },
            "title": f"知识块 {i + 1} (ID: {chunk.get('chunk_id', chunk.get('doc_id', ''))})",
            "citations": {"enabled": True},
        })

    # 添加用户问题
    content_blocks.append({
        "type": "text",
        "text": query,
    })

    # 构建请求
    messages = [{"role": "user", "content": content_blocks}]

    body: dict[str, Any] = {
        "model": model,
        "max_tokens": 2048,
        "messages": messages,
    }

    if system_prompt:
        body["system"] = system_prompt
    else:
        body["system"] = (
            "你是屯象OS的餐饮行业知识助手。基于提供的知识文档回答问题。"
            "回答时务必引用具体的知识来源。如果知识文档中没有相关信息，请明确说明。"
            "回答要简洁、准确、实用。"
        )

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            _API_URL,
            json=body,
            headers={
                "x-api-key": _ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )

        if resp.status_code != 200:
            logger.warning("claude_api_error", status=resp.status_code, body=resp.text[:200])
            return _fallback_answer(query, source_chunks)

        data = resp.json()

    # 解析回答和引用
    answer_text = ""
    citations: list[Citation] = []

    for block in data.get("content", []):
        if block.get("type") == "text":
            answer_text += block.get("text", "")

            # 提取 citations
            for cite in block.get("citations", []):
                if cite.get("type") == "document":
                    doc_index = cite.get("document_index", 0)
                    if 0 <= doc_index < len(source_chunks):
                        chunk = source_chunks[doc_index]
                        citations.append(Citation(
                            chunk_id=chunk.get("chunk_id", ""),
                            doc_id=chunk.get("doc_id", ""),
                            text_span=cite.get("cited_text", ""),
                            start_offset=cite.get("start_char_offset", 0),
                            end_offset=cite.get("end_char_offset", 0),
                        ))

    # Token 使用统计
    usage = data.get("usage", {})
    token_usage = {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
    }

    logger.info(
        "citation_engine_ok",
        model=model,
        citations_count=len(citations),
        input_tokens=token_usage["input_tokens"],
        output_tokens=token_usage["output_tokens"],
    )

    return AnswerWithCitations(
        answer=answer_text,
        citations=citations,
        model_used=model,
        token_usage=token_usage,
    )


def _fallback_answer(
    query: str,
    source_chunks: list[dict[str, Any]],
) -> AnswerWithCitations:
    """降级回答：直接拼接知识块内容"""
    texts = []
    citations = []

    for i, chunk in enumerate(source_chunks[:3]):  # 最多取前3个
        text = chunk.get("text", "")
        texts.append(f"[{i + 1}] {text[:200]}")
        citations.append(Citation(
            chunk_id=chunk.get("chunk_id", ""),
            doc_id=chunk.get("doc_id", ""),
            text_span=text[:100],
        ))

    answer = f"以下是与「{query}」相关的知识内容：\n\n" + "\n\n".join(texts)

    return AnswerWithCitations(
        answer=answer,
        citations=citations,
        model_used="fallback",
    )
