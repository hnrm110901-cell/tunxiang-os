"""Qdrant向量数据库客户端

URL通过环境变量 QDRANT_URL 配置（默认 http://localhost:6333）
API KEY通过 QDRANT_API_KEY 配置

所有方法在Qdrant不可用时优雅降级，不抛出异常。
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger()

_QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
_QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "")
_TIMEOUT = 5.0  # seconds


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if _QDRANT_API_KEY:
        h["api-key"] = _QDRANT_API_KEY
    return h


class QdrantClient:
    """Qdrant向量数据库客户端（无状态，方法均为async）"""

    # ── 健康检查 ─────────────────────────────────────────────

    @staticmethod
    async def health_check() -> bool:
        """检查Qdrant是否在线，不可用时返回False"""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(f"{_QDRANT_URL}/healthz", headers=_headers())
                return resp.status_code == 200
        except Exception as exc:
            logger.warning("qdrant_health_check_failed", error=str(exc))
            return False

    # ── Collection管理 ───────────────────────────────────────

    @staticmethod
    async def create_collection_if_not_exists(
        collection: str,
        vector_size: int = 1536,
    ) -> bool:
        """幂等创建collection。返回True表示成功（含已存在），False表示失败"""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                # 先检查是否已存在
                check = await client.get(
                    f"{_QDRANT_URL}/collections/{collection}",
                    headers=_headers(),
                )
                if check.status_code == 200:
                    return True

                # 不存在则创建
                payload = {
                    "vectors": {
                        "size": vector_size,
                        "distance": "Cosine",
                    }
                }
                resp = await client.put(
                    f"{_QDRANT_URL}/collections/{collection}",
                    json=payload,
                    headers=_headers(),
                )
                ok = resp.status_code in (200, 201)
                if not ok:
                    logger.error(
                        "qdrant_create_collection_failed",
                        collection=collection,
                        status=resp.status_code,
                        body=resp.text,
                    )
                return ok
        except Exception as exc:
            logger.warning(
                "qdrant_create_collection_error",
                collection=collection,
                error=str(exc),
            )
            return False

    # ── 写入 ─────────────────────────────────────────────────

    @staticmethod
    async def upsert(
        collection: str,
        points: list[dict[str, Any]],
    ) -> bool:
        """批量写入向量点。points格式：[{id, vector, payload}]

        返回True表示成功，False表示Qdrant不可用或写入失败。
        """
        if not points:
            return True
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.put(
                    f"{_QDRANT_URL}/collections/{collection}/points",
                    json={"points": points},
                    headers=_headers(),
                )
                ok = resp.status_code in (200, 201)
                if not ok:
                    logger.error(
                        "qdrant_upsert_failed",
                        collection=collection,
                        status=resp.status_code,
                        body=resp.text,
                    )
                return ok
        except Exception as exc:
            logger.warning(
                "qdrant_upsert_error",
                collection=collection,
                count=len(points),
                error=str(exc),
            )
            return False

    # ── 检索 ─────────────────────────────────────────────────

    @staticmethod
    async def search(
        collection: str,
        query_vector: list[float],
        filter: Optional[dict[str, Any]] = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """向量相似度检索。

        返回命中列表，每项含 {id, score, payload}。
        Qdrant不可用时返回空列表。
        """
        try:
            body: dict[str, Any] = {
                "vector": query_vector,
                "limit": limit,
                "with_payload": True,
                "with_vector": False,
            }
            if filter:
                body["filter"] = filter

            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{_QDRANT_URL}/collections/{collection}/points/search",
                    json=body,
                    headers=_headers(),
                )
                if resp.status_code != 200:
                    logger.warning(
                        "qdrant_search_failed",
                        collection=collection,
                        status=resp.status_code,
                    )
                    return []
                data = resp.json()
                return data.get("result", [])
        except Exception as exc:
            logger.warning(
                "qdrant_search_error",
                collection=collection,
                error=str(exc),
            )
            return []

    # ── 删除 ─────────────────────────────────────────────────

    @staticmethod
    async def delete(
        collection: str,
        ids: list[str | int],
    ) -> bool:
        """删除指定ID的向量点。返回True表示成功，False表示失败。"""
        if not ids:
            return True
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{_QDRANT_URL}/collections/{collection}/points/delete",
                    json={"points": ids},
                    headers=_headers(),
                )
                ok = resp.status_code in (200, 201)
                if not ok:
                    logger.error(
                        "qdrant_delete_failed",
                        collection=collection,
                        status=resp.status_code,
                    )
                return ok
        except Exception as exc:
            logger.warning(
                "qdrant_delete_error",
                collection=collection,
                count=len(ids),
                error=str(exc),
            )
            return False
