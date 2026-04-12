"""Voyage Rerank-2 精排服务测试

覆盖场景：
1. 空文档列表返回 []
2. 文档数少于 top_k 时原样返回
3. 有 VOYAGE_API_KEY 时：mock API 响应，验证重排序
4. 无 API Key 时：降级为分数排序
5. API 异常时：降级为分数排序
6. 分数阈值过滤在降级模式下生效
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_KS_DIR = os.path.dirname(_TESTS_DIR)
_SHARED_DIR = os.path.dirname(_KS_DIR)
_ROOT_DIR = os.path.dirname(_SHARED_DIR)
sys.path.insert(0, _ROOT_DIR)

from shared.knowledge_store.reranker import RerankerService, _fallback_rerank


# ── 工具 ────────────────────────────────────────────────────────

def _make_doc(doc_id: str, text: str, score: float) -> dict:
    """生成模拟文档"""
    return {
        "chunk_id": doc_id,
        "doc_id": doc_id,
        "text": text,
        "score": score,
        "metadata": {},
        "chunk_index": 0,
    }


# ── 空文档 ──────────────────────────────────────────────────────

class TestEmptyDocuments:
    """空文档列表应返回空列表"""

    @pytest.mark.asyncio
    async def test_empty_documents_returns_empty(self):
        """空列表返回[]"""
        result = await RerankerService.rerank("红烧肉", [])
        assert result == []


# ── 文档数少于 top_k ────────────────────────────────────────────

class TestFewerThanTopK:
    """文档数 <= top_k 时原样返回"""

    @pytest.mark.asyncio
    async def test_single_document_returned_as_is(self):
        """单条文档直接返回"""
        docs = [_make_doc("d1", "红烧肉", 0.9)]
        result = await RerankerService.rerank("红烧肉", docs, top_k=5)
        assert len(result) == 1
        assert result[0]["doc_id"] == "d1"

    @pytest.mark.asyncio
    async def test_exact_top_k_returned_as_is(self):
        """文档数等于 top_k 时直接返回"""
        docs = [_make_doc(f"d{i}", f"菜品{i}", 0.9 - i * 0.1) for i in range(3)]
        result = await RerankerService.rerank("菜品", docs, top_k=3)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_fewer_than_top_k_preserves_order(self):
        """文档数 < top_k 时保持原始顺序"""
        docs = [
            _make_doc("d1", "红烧肉", 0.9),
            _make_doc("d2", "清蒸鱼", 0.8),
        ]
        result = await RerankerService.rerank("菜品", docs, top_k=10)
        assert result[0]["doc_id"] == "d1"
        assert result[1]["doc_id"] == "d2"


# ── API 精排成功 ────────────────────────────────────────────────

class TestAPIRerank:
    """有 VOYAGE_API_KEY 时通过 API 精排"""

    @pytest.mark.asyncio
    async def test_api_rerank_success(self):
        """API 返回成功时按 API 排序重建结果"""
        docs = [
            _make_doc("d1", "红烧肉做法", 0.9),
            _make_doc("d2", "清蒸鱼做法", 0.8),
            _make_doc("d3", "糖醋排骨做法", 0.7),
            _make_doc("d4", "宫保鸡丁做法", 0.6),
            _make_doc("d5", "回锅肉做法", 0.5),
            _make_doc("d6", "麻婆豆腐做法", 0.4),
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"index": 2, "relevance_score": 0.98},  # 糖醋排骨
                {"index": 0, "relevance_score": 0.95},  # 红烧肉
                {"index": 4, "relevance_score": 0.85},  # 回锅肉
            ]
        }

        with (
            patch("shared.knowledge_store.reranker._VOYAGE_API_KEY", "test-key-123"),
            patch("shared.knowledge_store.reranker.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await RerankerService.rerank("肉类菜品", docs, top_k=3)

        assert len(result) == 3
        # 按 API 返回的顺序排列
        assert result[0]["doc_id"] == "d3"  # 糖醋排骨（index=2）
        assert result[0]["score"] == 0.98
        assert result[1]["doc_id"] == "d1"  # 红烧肉（index=0）
        assert result[1]["score"] == 0.95

    @pytest.mark.asyncio
    async def test_api_rerank_sends_correct_request(self):
        """API 请求包含正确的 model、query、documents、top_k"""
        docs = [
            _make_doc("d1", "红烧肉", 0.9),
            _make_doc("d2", "清蒸鱼", 0.8),
            _make_doc("d3", "糖醋排骨", 0.7),
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"index": 0, "relevance_score": 0.9}]
        }

        with (
            patch("shared.knowledge_store.reranker._VOYAGE_API_KEY", "test-key"),
            patch("shared.knowledge_store.reranker.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            await RerankerService.rerank("肉类", docs, top_k=2, model="rerank-2")

            call_kwargs = mock_client.post.call_args
            body = call_kwargs[1]["json"]
            assert body["model"] == "rerank-2"
            assert body["query"] == "肉类"
            assert body["top_k"] == 2
            assert len(body["documents"]) == 3


# ── 无 API Key 降级 ─────────────────────────────────────────────

class TestNoAPIKeyFallback:
    """无 VOYAGE_API_KEY 时降级为分数排序"""

    @pytest.mark.asyncio
    async def test_fallback_when_no_api_key(self):
        """无 API Key 时降级排序"""
        docs = [
            _make_doc("d1", "红烧肉", 0.5),
            _make_doc("d2", "清蒸鱼", 0.9),
            _make_doc("d3", "糖醋排骨", 0.7),
            _make_doc("d4", "宫保鸡丁", 0.3),
            _make_doc("d5", "回锅肉", 0.8),
            _make_doc("d6", "麻婆豆腐", 0.6),
        ]

        with patch("shared.knowledge_store.reranker._VOYAGE_API_KEY", ""):
            result = await RerankerService.rerank("菜品", docs, top_k=3)

        assert len(result) == 3
        # 降级按原始分数排序
        assert result[0]["score"] >= result[1]["score"]
        assert result[1]["score"] >= result[2]["score"]

    @pytest.mark.asyncio
    async def test_fallback_highest_score_first(self):
        """降级排序：最高分在前"""
        docs = [
            _make_doc("d1", "低分", 0.1),
            _make_doc("d2", "高分", 0.95),
            _make_doc("d3", "中分", 0.5),
            _make_doc("d4", "次高", 0.8),
        ]

        with patch("shared.knowledge_store.reranker._VOYAGE_API_KEY", ""):
            result = await RerankerService.rerank("查询", docs, top_k=2)

        assert result[0]["doc_id"] == "d2"
        assert result[1]["doc_id"] == "d4"


# ── API 异常降级 ────────────────────────────────────────────────

class TestAPIErrorFallback:
    """API 异常时降级为分数排序"""

    @pytest.mark.asyncio
    async def test_api_error_status_fallback(self):
        """API 返回非200时降级"""
        docs = [
            _make_doc("d1", "红烧肉", 0.9),
            _make_doc("d2", "清蒸鱼", 0.8),
            _make_doc("d3", "糖醋排骨", 0.5),
        ]

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with (
            patch("shared.knowledge_store.reranker._VOYAGE_API_KEY", "test-key"),
            patch("shared.knowledge_store.reranker.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await RerankerService.rerank("肉类", docs, top_k=2)

        # 降级：按分数排序返回 top_k
        assert len(result) == 2
        assert result[0]["score"] >= result[1]["score"]

    @pytest.mark.asyncio
    async def test_api_connection_error_fallback(self):
        """API 连接异常时降级"""
        docs = [
            _make_doc("d1", "红烧肉", 0.9),
            _make_doc("d2", "清蒸鱼", 0.4),
            _make_doc("d3", "糖醋排骨", 0.7),
        ]

        with (
            patch("shared.knowledge_store.reranker._VOYAGE_API_KEY", "test-key"),
            patch("shared.knowledge_store.reranker.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=ConnectionRefusedError("offline"))
            mock_cls.return_value = mock_client

            result = await RerankerService.rerank("肉类", docs, top_k=2)

        assert len(result) == 2
        assert result[0]["score"] >= result[1]["score"]

    @pytest.mark.asyncio
    async def test_api_timeout_fallback(self):
        """API 超时时降级"""
        docs = [
            _make_doc("d1", "红烧肉", 0.9),
            _make_doc("d2", "清蒸鱼", 0.3),
            _make_doc("d3", "糖醋排骨", 0.7),
        ]

        with (
            patch("shared.knowledge_store.reranker._VOYAGE_API_KEY", "test-key"),
            patch("shared.knowledge_store.reranker.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=TimeoutError("timeout"))
            mock_cls.return_value = mock_client

            result = await RerankerService.rerank("肉类", docs, top_k=2)

        assert len(result) == 2


# ── 分数阈值过滤（降级模式） ────────────────────────────────────

class TestFallbackScoreThreshold:
    """降级模式下分数阈值过滤"""

    def test_fallback_filters_below_threshold(self):
        """低于阈值（0.3）的文档在降级时被过滤"""
        docs = [
            _make_doc("d1", "高分", 0.9),
            _make_doc("d2", "中分", 0.5),
            _make_doc("d3", "低分", 0.1),
            _make_doc("d4", "极低分", 0.05),
        ]

        result = _fallback_rerank(docs, top_k=10)

        # 0.1 和 0.05 低于阈值 0.3，应被过滤
        doc_ids = {r["doc_id"] for r in result}
        assert "d1" in doc_ids
        assert "d2" in doc_ids
        assert "d3" not in doc_ids
        assert "d4" not in doc_ids

    def test_fallback_all_below_threshold_returns_sorted(self):
        """所有文档低于阈值时仍返回排序后的结果"""
        docs = [
            _make_doc("d1", "低分1", 0.1),
            _make_doc("d2", "低分2", 0.2),
            _make_doc("d3", "低分3", 0.05),
        ]

        result = _fallback_rerank(docs, top_k=2)

        # 全部低于阈值，但仍返回排序后的 top_k
        assert len(result) == 2
        assert result[0]["score"] >= result[1]["score"]

    def test_fallback_top_k_limits_output(self):
        """降级模式 top_k 限制输出数量"""
        docs = [_make_doc(f"d{i}", f"菜品{i}", 0.9 - i * 0.05) for i in range(10)]

        result = _fallback_rerank(docs, top_k=3)
        assert len(result) == 3

    def test_fallback_sorted_descending(self):
        """降级模式结果按分数降序排列"""
        docs = [
            _make_doc("d1", "低分", 0.4),
            _make_doc("d2", "高分", 0.9),
            _make_doc("d3", "中分", 0.6),
        ]

        result = _fallback_rerank(docs, top_k=3)
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)
