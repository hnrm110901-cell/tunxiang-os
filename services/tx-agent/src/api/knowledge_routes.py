"""知识库管理 API

提供文档上传、分块管理、混合检索等知识库管理能力。
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any
from uuid import uuid4

import structlog
from fastapi import APIRouter, File, Form, Query, UploadFile

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


@router.post("/documents")
async def upload_document(
    title: str = Form(...),
    collection: str = Form("ops_procedures"),
    source_type: str = Form("manual"),
    tenant_id: str = Form(...),
    metadata: str = Form("{}"),  # JSON string
    file: UploadFile | None = File(None),
    raw_text: str | None = Form(None),
) -> dict[str, Any]:
    """上传文档并触发异步处理。

    支持：PDF/DOCX/XLSX/TXT 文件上传，或直接传入文本。
    """
    from shared.knowledge_store.document_processor import DocumentProcessor

    doc_id = str(uuid4())
    meta = json.loads(metadata) if metadata else {}
    file_path = None
    file_hash = None

    # 保存上传文件
    if file and file.filename:
        source_type = _detect_source_type(file.filename, source_type)
        suffix = os.path.splitext(file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            file_path = tmp.name
        file_hash = DocumentProcessor.compute_file_hash(file_path)

    # 创建文档记录
    # TODO: 接入实际 DB session（当前返回模拟结果）
    result = {
        "ok": True,
        "data": {
            "id": doc_id,
            "tenant_id": tenant_id,
            "title": title,
            "source_type": source_type,
            "collection": collection,
            "status": "processing",
            "file_hash": file_hash,
            "metadata": meta,
        },
    }

    logger.info(
        "document_upload_accepted",
        doc_id=doc_id,
        title=title,
        source_type=source_type,
        collection=collection,
    )

    # TODO: 触发异步文档处理任务
    # asyncio.create_task(process_document_task(doc_id, file_path, ...))

    return result


@router.get("/documents")
async def list_documents(
    tenant_id: str = Query(...),
    collection: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """查询文档列表"""
    # TODO: 接入实际 DB 查询
    return {
        "ok": True,
        "data": {"items": [], "total": 0, "page": page, "size": size},
    }


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """获取文档详情"""
    return {"ok": True, "data": None, "error": {"code": "NOT_FOUND", "message": "文档不存在"}}


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """删除文档及其所有知识块"""
    # TODO: 接入实际 DB + PgVectorStore.delete_by_document()
    return {"ok": True, "data": {"deleted": True}}


@router.post("/documents/{document_id}/reprocess")
async def reprocess_document(
    document_id: str,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """重新处理文档（重新分块 + 向量化）"""
    return {"ok": True, "data": {"status": "processing"}}


@router.get("/documents/{document_id}/chunks")
async def list_chunks(
    document_id: str,
    tenant_id: str = Query(...),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """获取文档的知识块列表"""
    return {
        "ok": True,
        "data": {"items": [], "total": 0, "page": page, "size": size},
    }


@router.post("/search")
async def search_knowledge(
    body: dict[str, Any],
) -> dict[str, Any]:
    """混合检索（向量 + 关键词 + RRF + Rerank）。

    body: {query, collection, tenant_id, top_k?, filters?, rerank?}
    """
    query = body.get("query", "")
    collection = body.get("collection", "ops_procedures")
    tenant_id = body.get("tenant_id", "")
    top_k = body.get("top_k", 5)

    if not query or not tenant_id:
        return {"ok": False, "error": {"code": "INVALID_PARAMS", "message": "query 和 tenant_id 必填"}}

    # 使用 KnowledgeRetrievalService（自动按 feature flag 路由）
    from ..services.knowledge_retrieval import KnowledgeRetrievalService

    results = await KnowledgeRetrievalService.search(
        collection=collection,
        query=query,
        tenant_id=tenant_id,
        top_k=top_k,
        filters=body.get("filters"),
    )

    return {
        "ok": True,
        "data": {
            "results": results,
            "total": len(results),
            "query": query,
            "collection": collection,
        },
    }


@router.post("/index")
async def index_text(
    body: dict[str, Any],
) -> dict[str, Any]:
    """索引文本（向后兼容，供现有服务调用）。

    body: {collection, doc_id, text, metadata?, tenant_id}
    """
    from ..services.knowledge_retrieval import KnowledgeRetrievalService

    collection = body.get("collection", "")
    doc_id = body.get("doc_id", "")
    text = body.get("text", "")
    tenant_id = body.get("tenant_id", "")
    metadata = body.get("metadata", {})

    if not all([collection, doc_id, text, tenant_id]):
        return {"ok": False, "error": {"code": "INVALID_PARAMS", "message": "collection, doc_id, text, tenant_id 必填"}}

    success = await KnowledgeRetrievalService.index_document(
        collection=collection,
        doc_id=doc_id,
        text=text,
        metadata=metadata,
        tenant_id=tenant_id,
    )

    return {"ok": success, "data": {"indexed": success, "doc_id": doc_id}}


def _detect_source_type(filename: str, default: str) -> str:
    """根据文件扩展名检测源类型"""
    ext = os.path.splitext(filename)[1].lower()
    mapping = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".csv": "csv", ".txt": "txt", ".md": "txt"}
    return mapping.get(ext, default)
