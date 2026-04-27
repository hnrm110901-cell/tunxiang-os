"""知识库 Pydantic V2 数据模型"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeSearchRequest(BaseModel):
    """知识检索请求"""

    query: str
    collection: str
    tenant_id: str
    top_k: int = Field(default=5, le=50, ge=1)
    filters: dict[str, Any] | None = None
    rerank: bool = True


class KnowledgeSearchResult(BaseModel):
    """单条检索结果"""

    doc_id: str
    chunk_id: str | None = None
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class IndexTextRequest(BaseModel):
    """文本索引请求（向后兼容）"""

    collection: str
    doc_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str


class DocumentUploadRequest(BaseModel):
    """文档上传请求"""

    title: str
    collection: str = "ops_procedures"
    source_type: str = "manual"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkPreview(BaseModel):
    """分块预览"""

    chunk_index: int
    text: str
    token_count: int
    start_char: int = 0
    end_char: int = 0


class DocumentResponse(BaseModel):
    """文档响应"""

    id: str
    tenant_id: str
    title: str
    source_type: str
    file_path: str | None = None
    file_hash: str | None = None
    chunk_count: int = 0
    status: str = "draft"
    collection: str = "ops_procedures"
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_by: str | None = None
    reviewed_by: str | None = None
    published_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ChunkResponse(BaseModel):
    """知识块响应"""

    id: str
    document_id: str
    collection: str
    doc_id: str
    chunk_index: int
    text: str
    token_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
