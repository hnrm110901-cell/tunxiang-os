"""知识库 Phase 2 数据模型 — Agentic RAG"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """引用定位"""

    chunk_id: str
    doc_id: str
    text_span: str
    start_offset: int = 0
    end_offset: int = 0


class QueryResult(BaseModel):
    """Agentic RAG 查询结果"""

    query: str
    complexity: str = "simple"  # simple/medium/complex
    results: list[dict[str, Any]] = Field(default_factory=list)
    sub_queries: list[str] | None = None
    rewrite_count: int = 0
    latency_ms: int = 0
    answer: str | None = None
    citations: list[Citation] | None = None
    model_used: str | None = None


class AnswerWithCitations(BaseModel):
    """带引用的回答"""

    answer: str
    citations: list[Citation] = Field(default_factory=list)
    model_used: str = ""
    token_usage: dict[str, int] = Field(default_factory=dict)


class QueryLogEntry(BaseModel):
    """检索质量日志"""

    tenant_id: str
    query: str
    collection: str | None = None
    query_complexity: str = "simple"
    retrieved_count: int = 0
    reranked_count: int = 0
    relevance_max: float | None = None
    latency_ms: int = 0
    rewrite_count: int = 0
    answer_source: str = "direct"  # direct/reranked/corrective/decomposed
