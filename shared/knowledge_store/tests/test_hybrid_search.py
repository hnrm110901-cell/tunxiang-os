"""混合检索引擎测试

覆盖场景：
1. 空查询返回 []
2. search 同时调用 vector_search 和 keyword_search
3. RRF 融合正确合并两路结果
4. 重复 chunk_id 跨两路时分数相加
5. 结果按融合分数降序排序
6. top_k 限制输出数量
7. 一路为空时另一路结果仍然出现
8. vector_weight 和 keyword_weight 影响最终分数
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

from shared.knowledge_store.hybrid_search import HybridSearchEngine, _rrf_fuse


# ── 工具 ────────────────────────────────────────────────────────

def _fake_embedding(val: float = 0.1, size: int = 1536) -> list[float]:
    return [val] * size


def _make_result(chunk_id: str, doc_id: str, text: str, score: float) -> dict:
    """生成模拟检索结果"""
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "text": text,
        "score": score,
        "metadata": {},
        "chunk_index": 0,
        "document_id": "doc-uuid-1",
    }


def _mock_db_session() -> AsyncMock:
    return AsyncMock()


# ── 空查询 ──────────────────────────────────────────────────────

class TestEmptyQuery:
    """空查询应返回空列表"""

    @pytest.mark.asyncio
    async def test_empty_string_returns_empty(self):
        """空字符串查询返回[]"""
        db = _mock_db_session()
        results = await HybridSearchEngine.search("", "menu_knowledge", "tenant_001", db)
        assert results == []

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_empty(self):
        """纯空白查询返回[]"""
        db = _mock_db_session()
        results = await HybridSearchEngine.search("   ", "menu_knowledge", "tenant_001", db)
        assert results == []


# ── search 调用双路检索 ─────────────────────────────────────────

class TestDualRetrieval:
    """search 应同时调用 vector_search 和 keyword_search"""

    @pytest.mark.asyncio
    async def test_search_calls_both_vector_and_keyword(self):
        """检索同时调用向量检索和关键词检索"""
        with (
            patch("shared.knowledge_store.hybrid_search.EmbeddingService") as mock_embed,
            patch("shared.knowledge_store.hybrid_search.PgVectorStore") as mock_store,
        ):
            mock_embed.embed_text = AsyncMock(return_value=_fake_embedding())
            mock_store.vector_search = AsyncMock(return_value=[])
            mock_store.keyword_search = AsyncMock(return_value=[])

            db = _mock_db_session()
            await HybridSearchEngine.search("红烧肉", "menu_knowledge", "tenant_001", db)

            mock_store.vector_search.assert_called_once()
            mock_store.keyword_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_passes_correct_params_to_vector_search(self):
        """向量检索收到正确的参数"""
        embedding = _fake_embedding(0.5)
        with (
            patch("shared.knowledge_store.hybrid_search.EmbeddingService") as mock_embed,
            patch("shared.knowledge_store.hybrid_search.PgVectorStore") as mock_store,
        ):
            mock_embed.embed_text = AsyncMock(return_value=embedding)
            mock_store.vector_search = AsyncMock(return_value=[])
            mock_store.keyword_search = AsyncMock(return_value=[])

            db = _mock_db_session()
            await HybridSearchEngine.search(
                "红烧肉", "menu_knowledge", "tenant_001", db,
                top_k=5, retrieval_k=20,
            )

            call_kwargs = mock_store.vector_search.call_args[1]
            assert call_kwargs["collection"] == "menu_knowledge"
            assert call_kwargs["tenant_id"] == "tenant_001"
            assert call_kwargs["top_k"] == 20


# ── RRF 融合 ────────────────────────────────────────────────────

class TestRRFFusion:
    """RRF 融合测试"""

    def test_rrf_fuse_merges_results(self):
        """RRF 融合能合并两路结果"""
        vector_results = [
            _make_result("c1", "d1", "红烧肉", 0.95),
            _make_result("c2", "d2", "东坡肉", 0.88),
        ]
        keyword_results = [
            _make_result("c3", "d3", "梅菜扣肉", 0.70),
        ]

        fused = _rrf_fuse(vector_results, keyword_results)
        assert len(fused) == 3  # c1, c2, c3 各出现一次

    def test_rrf_fuse_duplicate_chunk_scores_added(self):
        """同一 chunk_id 在两路中出现时分数相加"""
        vector_results = [
            _make_result("c1", "d1", "红烧肉", 0.95),
        ]
        keyword_results = [
            _make_result("c1", "d1", "红烧肉", 0.70),
        ]

        fused = _rrf_fuse(vector_results, keyword_results)
        assert len(fused) == 1  # 只有 c1

        # 分数应是两路 RRF 分数之和
        # vector: 0.7 * (1/61) + keyword: 0.3 * (1/61)
        expected_score = 0.7 * (1.0 / 61) + 0.3 * (1.0 / 61)
        assert abs(fused[0]["score"] - expected_score) < 1e-9

    def test_rrf_fuse_results_sorted_by_score(self):
        """融合结果按分数降序排列（由 search 方法排序）"""
        vector_results = [
            _make_result("c1", "d1", "第一名", 0.9),
            _make_result("c2", "d2", "第二名", 0.8),
        ]
        keyword_results = [
            _make_result("c2", "d2", "第二名", 0.9),  # c2 在关键词中排第一
            _make_result("c3", "d3", "第三名", 0.5),
        ]

        fused = _rrf_fuse(vector_results, keyword_results)
        fused.sort(key=lambda x: x["score"], reverse=True)

        # c2 在两路都出现，分数应最高
        assert fused[0]["chunk_id"] == "c2"

    def test_rrf_fuse_empty_vector_results(self):
        """向量检索为空时仍返回关键词结果"""
        keyword_results = [
            _make_result("c1", "d1", "红烧肉", 0.8),
        ]

        fused = _rrf_fuse([], keyword_results)
        assert len(fused) == 1
        assert fused[0]["chunk_id"] == "c1"

    def test_rrf_fuse_empty_keyword_results(self):
        """关键词检索为空时仍返回向量结果"""
        vector_results = [
            _make_result("c1", "d1", "红烧肉", 0.95),
        ]

        fused = _rrf_fuse(vector_results, [])
        assert len(fused) == 1
        assert fused[0]["chunk_id"] == "c1"

    def test_rrf_fuse_both_empty(self):
        """两路都为空时返回空列表"""
        fused = _rrf_fuse([], [])
        assert fused == []


# ── top_k 限制 ──────────────────────────────────────────────────

class TestTopKLimit:
    """top_k 应限制输出数量"""

    @pytest.mark.asyncio
    async def test_top_k_limits_output(self):
        """返回结果数不超过 top_k"""
        vector_results = [_make_result(f"v{i}", f"dv{i}", f"向量{i}", 0.9 - i * 0.05) for i in range(10)]
        keyword_results = [_make_result(f"k{i}", f"dk{i}", f"关键词{i}", 0.8 - i * 0.05) for i in range(10)]

        with (
            patch("shared.knowledge_store.hybrid_search.EmbeddingService") as mock_embed,
            patch("shared.knowledge_store.hybrid_search.PgVectorStore") as mock_store,
        ):
            mock_embed.embed_text = AsyncMock(return_value=_fake_embedding())
            mock_store.vector_search = AsyncMock(return_value=vector_results)
            mock_store.keyword_search = AsyncMock(return_value=keyword_results)

            db = _mock_db_session()
            results = await HybridSearchEngine.search(
                "测试", "menu_knowledge", "tenant_001", db, top_k=3,
            )

            assert len(results) == 3

    @pytest.mark.asyncio
    async def test_fewer_results_than_top_k(self):
        """候选数少于 top_k 时返回全部"""
        vector_results = [_make_result("c1", "d1", "唯一结果", 0.95)]

        with (
            patch("shared.knowledge_store.hybrid_search.EmbeddingService") as mock_embed,
            patch("shared.knowledge_store.hybrid_search.PgVectorStore") as mock_store,
        ):
            mock_embed.embed_text = AsyncMock(return_value=_fake_embedding())
            mock_store.vector_search = AsyncMock(return_value=vector_results)
            mock_store.keyword_search = AsyncMock(return_value=[])

            db = _mock_db_session()
            results = await HybridSearchEngine.search(
                "测试", "menu_knowledge", "tenant_001", db, top_k=10,
            )

            assert len(results) == 1


# ── 权重影响 ────────────────────────────────────────────────────

class TestWeightEffect:
    """vector_weight 和 keyword_weight 应影响最终分数"""

    def test_higher_vector_weight_boosts_vector_results(self):
        """增大 vector_weight 使向量结果得分更高"""
        vector_results = [_make_result("cv", "dv", "向量命中", 0.9)]
        keyword_results = [_make_result("ck", "dk", "关键词命中", 0.9)]

        # 高向量权重
        fused_high_v = _rrf_fuse(vector_results, keyword_results, vector_weight=0.9, keyword_weight=0.1)
        # 高关键词权重
        fused_high_k = _rrf_fuse(vector_results, keyword_results, vector_weight=0.1, keyword_weight=0.9)

        score_cv_high_v = next(r["score"] for r in fused_high_v if r["chunk_id"] == "cv")
        score_cv_high_k = next(r["score"] for r in fused_high_k if r["chunk_id"] == "cv")

        # 向量权重高时向量结果得分应更高
        assert score_cv_high_v > score_cv_high_k

    def test_equal_weights_produce_equal_rrf_scores(self):
        """权重相等时，同排名的结果 RRF 分数相等"""
        vector_results = [_make_result("cv", "dv", "向量", 0.9)]
        keyword_results = [_make_result("ck", "dk", "关键词", 0.9)]

        fused = _rrf_fuse(vector_results, keyword_results, vector_weight=0.5, keyword_weight=0.5)

        score_cv = next(r["score"] for r in fused if r["chunk_id"] == "cv")
        score_ck = next(r["score"] for r in fused if r["chunk_id"] == "ck")

        # 同排名（都是 rank 0）+ 同权重 → 分数相等
        assert abs(score_cv - score_ck) < 1e-9


# ── 单路为空时的行为 ────────────────────────────────────────────

class TestSingleLegEmpty:
    """一路检索为空时另一路结果仍然出现"""

    @pytest.mark.asyncio
    async def test_vector_empty_keyword_has_results(self):
        """向量检索为空时关键词结果仍然返回"""
        keyword_results = [
            _make_result("k1", "dk1", "关键词命中1", 0.8),
            _make_result("k2", "dk2", "关键词命中2", 0.7),
        ]

        with (
            patch("shared.knowledge_store.hybrid_search.EmbeddingService") as mock_embed,
            patch("shared.knowledge_store.hybrid_search.PgVectorStore") as mock_store,
        ):
            mock_embed.embed_text = AsyncMock(return_value=_fake_embedding())
            mock_store.vector_search = AsyncMock(return_value=[])
            mock_store.keyword_search = AsyncMock(return_value=keyword_results)

            db = _mock_db_session()
            results = await HybridSearchEngine.search(
                "红烧", "menu_knowledge", "tenant_001", db, top_k=5,
            )

            assert len(results) == 2
            chunk_ids = {r["chunk_id"] for r in results}
            assert "k1" in chunk_ids
            assert "k2" in chunk_ids

    @pytest.mark.asyncio
    async def test_keyword_empty_vector_has_results(self):
        """关键词检索为空时向量结果仍然返回"""
        vector_results = [
            _make_result("v1", "dv1", "向量命中", 0.95),
        ]

        with (
            patch("shared.knowledge_store.hybrid_search.EmbeddingService") as mock_embed,
            patch("shared.knowledge_store.hybrid_search.PgVectorStore") as mock_store,
        ):
            mock_embed.embed_text = AsyncMock(return_value=_fake_embedding())
            mock_store.vector_search = AsyncMock(return_value=vector_results)
            mock_store.keyword_search = AsyncMock(return_value=[])

            db = _mock_db_session()
            results = await HybridSearchEngine.search(
                "红烧", "menu_knowledge", "tenant_001", db, top_k=5,
            )

            assert len(results) == 1
            assert results[0]["chunk_id"] == "v1"
