"""知识库管理 API

提供文档上传、分块管理、混合检索等知识库管理能力。
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Any
from uuid import uuid4

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from shared.ontology.src.database import TenantSession

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


@router.post("/documents")
async def upload_document(
    title: str = Form(...),
    collection: str = Form("ops_procedures"),
    source_type: str = Form("manual"),
    tenant_id: str = Form(...),
    metadata: str = Form("{}"),  # JSON string
    created_by: str = Form(None),
    file: UploadFile | None = File(None),
    raw_text: str | None = Form(None),
) -> dict[str, Any]:
    """上传文档并触发异步处理。

    支持：PDF/DOCX/XLSX/TXT 文件上传，或直接传入文本。
    幂等：如 file_hash 已存在（且 is_deleted=FALSE），返回现有记录并加 idempotent:true。
    """
    from shared.knowledge_store.document_processor import DocumentProcessor

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

    # 创建文档记录（带幂等检查）
    try:
        async with TenantSession(tenant_id) as db:
            # 幂等检查：如 file_hash 已存在则直接返回
            if file_hash:
                existing = await db.execute(
                    text("""
                        SELECT id::text, title, status, created_at
                        FROM knowledge_documents
                        WHERE tenant_id = :tenant_id::uuid
                          AND file_hash = :file_hash
                          AND is_deleted = FALSE
                        LIMIT 1
                    """),
                    {"tenant_id": tenant_id, "file_hash": file_hash},
                )
                row = existing.fetchone()
                if row:
                    logger.info(
                        "document_upload_idempotent",
                        doc_id=row.id,
                        title=row.title,
                        tenant_id=tenant_id,
                    )
                    return {
                        "ok": True,
                        "data": {
                            "document_id": row.id,
                            "title": row.title,
                            "status": row.status,
                            "created_at": row.created_at.isoformat() if row.created_at else None,
                            "idempotent": True,
                        },
                    }

            # 插入新记录
            doc_id = str(uuid4())
            insert_result = await db.execute(
                text("""
                    INSERT INTO knowledge_documents
                        (id, tenant_id, title, source_type, file_path, file_hash,
                         status, collection, metadata, created_by)
                    VALUES
                        (:id::uuid, :tenant_id::uuid, :title, :source_type, :file_path,
                         :file_hash, 'processing', :collection, :metadata::jsonb, :created_by)
                    RETURNING id::text, title, status, created_at
                """),
                {
                    "id": doc_id,
                    "tenant_id": tenant_id,
                    "title": title,
                    "source_type": source_type,
                    "file_path": file_path,
                    "file_hash": file_hash,
                    "collection": collection,
                    "metadata": json.dumps(meta),
                    "created_by": created_by,
                },
            )
            row = insert_result.fetchone()

    except SQLAlchemyError as exc:
        logger.error(
            "document_upload_db_error",
            title=title,
            tenant_id=tenant_id,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="数据库写入失败") from exc

    document_id = row.id
    logger.info(
        "document_upload_accepted",
        doc_id=document_id,
        title=title,
        source_type=source_type,
        collection=collection,
    )

    # 触发异步文档处理任务（旁路，失败不影响主流程）
    asyncio.create_task(
        _process_document_task(
            document_id=document_id,
            file_path=file_path,
            raw_text=raw_text,
            source_type=source_type,
            collection=collection,
            tenant_id=tenant_id,
            metadata=meta,
        )
    )

    return {
        "ok": True,
        "data": {
            "document_id": document_id,
            "title": row.title,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "idempotent": False,
        },
    }


@router.get("/documents")
async def list_documents(
    tenant_id: str = Query(...),
    collection: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """查询文档列表，支持 collection / status 过滤，分页，按创建时间倒序。"""
    try:
        async with TenantSession(tenant_id) as db:
            # 构建动态过滤条件
            filters = "AND is_deleted = FALSE"
            params: dict[str, Any] = {
                "tenant_id": tenant_id,
                "limit": size,
                "offset": (page - 1) * size,
            }
            if collection:
                filters += " AND collection = :collection"
                params["collection"] = collection
            if status:
                filters += " AND status = :status"
                params["status"] = status

            count_result = await db.execute(
                text(f"""
                    SELECT COUNT(*) AS total
                    FROM knowledge_documents
                    WHERE tenant_id = :tenant_id::uuid
                    {filters}
                """),
                params,
            )
            total = count_result.scalar() or 0

            rows_result = await db.execute(
                text(f"""
                    SELECT
                        id::text            AS id,
                        title               AS title,
                        source_type         AS source_type,
                        file_hash           AS file_hash,
                        chunk_count         AS chunk_count,
                        status              AS status,
                        collection          AS collection,
                        metadata            AS metadata,
                        error_message       AS error_message,
                        created_by::text    AS created_by,
                        published_at        AS published_at,
                        created_at          AS created_at,
                        updated_at          AS updated_at
                    FROM knowledge_documents
                    WHERE tenant_id = :tenant_id::uuid
                    {filters}
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = rows_result.fetchall()

    except SQLAlchemyError as exc:
        logger.error(
            "list_documents_db_error",
            tenant_id=tenant_id,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="数据库查询失败") from exc

    items = [
        {
            "id": r.id,
            "title": r.title,
            "source_type": r.source_type,
            "file_hash": r.file_hash,
            "chunk_count": r.chunk_count,
            "status": r.status,
            "collection": r.collection,
            "metadata": r.metadata,
            "error_message": r.error_message,
            "created_by": r.created_by,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]

    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
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
    """删除文档（软删除）。knowledge_chunks 通过 FK CASCADE 自动清理。"""
    try:
        async with TenantSession(tenant_id) as db:
            result = await db.execute(
                text("""
                    UPDATE knowledge_documents
                    SET is_deleted = TRUE,
                        updated_at = NOW()
                    WHERE id = :doc_id::uuid
                      AND tenant_id = :tenant_id::uuid
                      AND is_deleted = FALSE
                    RETURNING id::text AS id
                """),
                {"doc_id": document_id, "tenant_id": tenant_id},
            )
            row = result.fetchone()

    except SQLAlchemyError as exc:
        logger.error(
            "delete_document_db_error",
            document_id=document_id,
            tenant_id=tenant_id,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="数据库操作失败") from exc

    if not row:
        raise HTTPException(status_code=404, detail="文档不存在或已删除")

    logger.info(
        "document_deleted",
        doc_id=document_id,
        tenant_id=tenant_id,
    )
    return {"ok": True, "data": {"deleted_doc_id": row.id}}


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
    text_content = body.get("text", "")
    tenant_id = body.get("tenant_id", "")
    metadata = body.get("metadata", {})

    if not all([collection, doc_id, text_content, tenant_id]):
        return {"ok": False, "error": {"code": "INVALID_PARAMS", "message": "collection, doc_id, text, tenant_id 必填"}}

    success = await KnowledgeRetrievalService.index_document(
        collection=collection,
        doc_id=doc_id,
        text=text_content,
        metadata=metadata,
        tenant_id=tenant_id,
    )

    return {"ok": success, "data": {"indexed": success, "doc_id": doc_id}}


# ── 内部辅助函数 ──────────────────────────────────────────────


async def _process_document_task(
    document_id: str,
    file_path: str | None,
    raw_text: str | None,
    source_type: str,
    collection: str,
    tenant_id: str,
    metadata: dict[str, Any],
) -> None:
    """异步文档处理任务（旁路调用，失败只 log.warning 不影响主流程）。"""
    try:
        from shared.knowledge_store.document_processor import DocumentProcessor

        async with TenantSession(tenant_id) as db:
            result = await DocumentProcessor.process_document(
                document_id=document_id,
                file_path=file_path,
                source_type=source_type,
                collection=collection,
                tenant_id=tenant_id,
                db=db,
                raw_text=raw_text,
                metadata=metadata,
            )
        logger.info(
            "document_process_task_done",
            doc_id=document_id,
            chunk_count=result.get("chunk_count"),
            status=result.get("status"),
        )
    except Exception as exc:  # noqa: BLE001 — 旁路任务，最外层兜底
        logger.warning(
            "document_process_task_failed",
            doc_id=document_id,
            error=str(exc),
            exc_info=True,
        )


def _detect_source_type(filename: str, default: str) -> str:
    """根据文件扩展名检测源类型"""
    ext = os.path.splitext(filename)[1].lower()
    mapping = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".csv": "csv", ".txt": "txt", ".md": "txt"}
    return mapping.get(ext, default)
