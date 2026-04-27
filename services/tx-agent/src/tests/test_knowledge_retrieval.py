"""知识检索服务测试

覆盖场景：
1. 向量化文本并存入Qdrant
2. 相似度检索：返回最相关的K个结果
3. 混合检索：向量相似度 + 关键词过滤
4. 命名空间隔离：tenant_A的知识不被tenant_B检索到
5. Qdrant不可用时graceful降级（返回空结果，不报错）
6. 批量索引（大量文档一次性写入）
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 路径设置：从 src/tests/ 向上找到 src/，再找到项目根
# test文件位于 tunxiang-os/services/tx-agent/src/tests/
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../tx-agent/src
_TX_AGENT_DIR = os.path.dirname(_SRC_DIR)  # .../tx-agent
_SERVICES_DIR = os.path.dirname(_TX_AGENT_DIR)  # .../services
_ROOT_DIR = os.path.dirname(_SERVICES_DIR)  # tunxiang-os/
sys.path.insert(0, _SRC_DIR)
sys.path.insert(0, _ROOT_DIR)

# knowledge_retrieval位于 src/services/ 下，_SRC_DIR已加入sys.path
from services.knowledge_retrieval import KnowledgeRetrievalService

from shared.vector_store.client import QdrantClient
from shared.vector_store.embeddings import EmbeddingService
from shared.vector_store.indexes import COLLECTIONS, get_vector_size, list_collections

# ── 工具：生成固定长度的假向量 ────────────────────────────────


def _fake_vector(val: float = 0.1, size: int = 1536) -> list[float]:
    return [val] * size


# ── Qdrant客户端测试 ──────────────────────────────────────────


class TestQdrantClientHealthCheck:
    """测试健康检查"""

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_online(self):
        """Qdrant在线时返回True"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("shared.vector_store.client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            result = await QdrantClient.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_offline(self):
        """Qdrant离线时返回False，不抛异常"""
        with patch("shared.vector_store.client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=ConnectionRefusedError("offline"))
            mock_cls.return_value = mock_client

            result = await QdrantClient.health_check()
            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_non_200(self):
        """Qdrant返回非200时返回False"""
        mock_resp = MagicMock()
        mock_resp.status_code = 503

        with patch("shared.vector_store.client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            result = await QdrantClient.health_check()
            assert result is False


class TestQdrantClientUpsert:
    """测试向量写入"""

    @pytest.mark.asyncio
    async def test_upsert_returns_true_on_success(self):
        """正常写入返回True"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("shared.vector_store.client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.put = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            points = [{"id": 1, "vector": _fake_vector(), "payload": {"tenant_id": "t1"}}]
            result = await QdrantClient.upsert("test_collection", points)
            assert result is True

    @pytest.mark.asyncio
    async def test_upsert_returns_true_for_empty_points(self):
        """空列表不调用API，直接返回True"""
        result = await QdrantClient.upsert("test_collection", [])
        assert result is True

    @pytest.mark.asyncio
    async def test_upsert_returns_false_when_qdrant_unavailable(self):
        """Qdrant不可用时返回False，不抛异常"""
        with patch("shared.vector_store.client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.put = AsyncMock(side_effect=OSError("connection refused"))
            mock_cls.return_value = mock_client

            points = [{"id": 1, "vector": _fake_vector(), "payload": {}}]
            result = await QdrantClient.upsert("test_collection", points)
            assert result is False


class TestQdrantClientSearch:
    """测试向量检索"""

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        """正常检索返回命中列表"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "result": [
                {"id": 1, "score": 0.95, "payload": {"tenant_id": "t1", "doc_id": "d1", "text": "红烧肉"}},
                {"id": 2, "score": 0.87, "payload": {"tenant_id": "t1", "doc_id": "d2", "text": "东坡肉"}},
            ]
        }

        with patch("shared.vector_store.client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            results = await QdrantClient.search("menu_knowledge", _fake_vector(), limit=5)
            assert len(results) == 2
            assert results[0]["score"] == 0.95

    @pytest.mark.asyncio
    async def test_search_returns_empty_when_qdrant_unavailable(self):
        """Qdrant不可用时返回空列表，不抛异常"""
        with patch("shared.vector_store.client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=TimeoutError("timeout"))
            mock_cls.return_value = mock_client

            results = await QdrantClient.search("menu_knowledge", _fake_vector())
            assert results == []

    @pytest.mark.asyncio
    async def test_search_passes_filter_to_qdrant(self):
        """检索时filter参数正确传递到请求body"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": []}

        with patch("shared.vector_store.client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            filt = {"must": [{"key": "tenant_id", "match": {"value": "t1"}}]}
            await QdrantClient.search("menu_knowledge", _fake_vector(), filter=filt)

            call_kwargs = mock_client.post.call_args
            body = call_kwargs[1]["json"]
            assert "filter" in body
            assert body["filter"] == filt


# ── EmbeddingService测试 ──────────────────────────────────────


class TestEmbeddingServiceFallback:
    """测试TF-IDF fallback向量化"""

    def test_tfidf_embed_returns_correct_size(self):
        """TF-IDF向量维度为1536"""
        vec = EmbeddingService._tfidf_embed("红烧肉 东坡肉 猪肉")
        assert len(vec) == 1536

    def test_tfidf_embed_empty_text_returns_zeros(self):
        """空文本返回全零向量"""
        vec = EmbeddingService._tfidf_embed("")
        assert len(vec) == 1536
        assert all(v == 0.0 for v in vec)

    def test_tfidf_embed_different_texts_produce_different_vectors(self):
        """不同文本产生不同向量"""
        vec1 = EmbeddingService._tfidf_embed("红烧肉")
        vec2 = EmbeddingService._tfidf_embed("清蒸鱼")
        assert vec1 != vec2

    def test_tfidf_embed_same_text_is_deterministic(self):
        """相同文本始终产生相同向量"""
        text = "招牌菜 特色菜"
        vec1 = EmbeddingService._tfidf_embed(text)
        vec2 = EmbeddingService._tfidf_embed(text)
        assert vec1 == vec2

    @pytest.mark.asyncio
    async def test_embed_text_uses_fallback_when_no_api_key(self):
        """没有API Key时使用TF-IDF fallback"""
        with patch("shared.vector_store.embeddings._ANTHROPIC_API_KEY", ""):
            vec = await EmbeddingService.embed_text("测试文本")
            assert len(vec) == 1536
            assert isinstance(vec[0], float)

    @pytest.mark.asyncio
    async def test_embed_batch_returns_correct_count(self):
        """批量向量化返回与输入等长的列表"""
        texts = ["菜品一", "菜品二", "菜品三"]
        with patch("shared.vector_store.embeddings._ANTHROPIC_API_KEY", ""):
            vecs = await EmbeddingService.embed_batch(texts)
            assert len(vecs) == 3
            for v in vecs:
                assert len(v) == 1536

    @pytest.mark.asyncio
    async def test_embed_batch_empty_returns_empty(self):
        """空列表输入返回空列表"""
        vecs = await EmbeddingService.embed_batch([])
        assert vecs == []


# ── 索引配置测试 ───────────────────────────────────────────────


class TestCollectionIndexes:
    """测试预定义collection配置"""

    def test_all_required_collections_exist(self):
        """四个预定义collection均已配置"""
        required = {"menu_knowledge", "ops_procedures", "customer_insights", "decision_history"}
        assert required.issubset(set(COLLECTIONS.keys()))

    def test_all_collections_have_correct_vector_size(self):
        """所有collection向量维度为1536"""
        for name, cfg in COLLECTIONS.items():
            assert cfg["vector_size"] == 1536, f"{name} vector_size should be 1536"

    def test_get_vector_size_known_collection(self):
        """已知collection返回正确维度"""
        assert get_vector_size("menu_knowledge") == 1536

    def test_get_vector_size_unknown_collection(self):
        """未知collection返回默认1536"""
        assert get_vector_size("nonexistent_collection") == 1536

    def test_list_collections_returns_all(self):
        """list_collections返回所有预定义名称"""
        names = list_collections()
        assert "menu_knowledge" in names
        assert "decision_history" in names
        assert len(names) >= 4


# ── KnowledgeRetrievalService测试 ────────────────────────────


class TestIndexDocument:
    """测试1：向量化文本并存入Qdrant"""

    @pytest.mark.asyncio
    async def test_index_document_success(self):
        """正常索引文档返回True"""
        with (
            patch.object(QdrantClient, "create_collection_if_not_exists", return_value=True),
            patch.object(EmbeddingService, "embed_text", return_value=_fake_vector()),
            patch.object(QdrantClient, "upsert", return_value=True),
        ):
            result = await KnowledgeRetrievalService.index_document(
                collection="menu_knowledge",
                doc_id="dish:001",
                text="红烧肉，选用五花肉，入口即化",
                metadata={"brand_id": "brand_1", "category": "热菜"},
                tenant_id="tenant_001",
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_index_document_empty_text_returns_false(self):
        """空文本不调用Qdrant，直接返回False"""
        result = await KnowledgeRetrievalService.index_document(
            collection="menu_knowledge",
            doc_id="dish:001",
            text="",
            metadata={},
            tenant_id="tenant_001",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_index_document_collection_unavailable_returns_false(self):
        """collection创建失败时返回False"""
        with patch.object(QdrantClient, "create_collection_if_not_exists", return_value=False):
            result = await KnowledgeRetrievalService.index_document(
                collection="menu_knowledge",
                doc_id="dish:001",
                text="红烧肉",
                metadata={},
                tenant_id="tenant_001",
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_index_document_payload_contains_tenant_id(self):
        """upsert时payload必须包含tenant_id"""
        captured_points = []

        async def fake_upsert(collection, points):
            captured_points.extend(points)
            return True

        with (
            patch.object(QdrantClient, "create_collection_if_not_exists", return_value=True),
            patch.object(EmbeddingService, "embed_text", return_value=_fake_vector()),
            patch.object(QdrantClient, "upsert", side_effect=fake_upsert),
        ):
            await KnowledgeRetrievalService.index_document(
                collection="menu_knowledge",
                doc_id="dish:002",
                text="清蒸鱼",
                metadata={"category": "海鲜"},
                tenant_id="tenant_XYZ",
            )

        assert len(captured_points) == 1
        assert captured_points[0]["payload"]["tenant_id"] == "tenant_XYZ"


class TestSearchWithSimilarity:
    """测试2：相似度检索返回最相关的K个结果"""

    @pytest.mark.asyncio
    async def test_search_returns_top_k_results(self):
        """检索返回top_k个结果，按score排序"""
        qdrant_results = [
            {"id": 1, "score": 0.95, "payload": {"tenant_id": "t1", "doc_id": "d1", "text": "红烧肉"}},
            {"id": 2, "score": 0.88, "payload": {"tenant_id": "t1", "doc_id": "d2", "text": "东坡肉"}},
            {"id": 3, "score": 0.72, "payload": {"tenant_id": "t1", "doc_id": "d3", "text": "梅菜扣肉"}},
        ]
        with (
            patch.object(EmbeddingService, "embed_text", return_value=_fake_vector()),
            patch.object(QdrantClient, "search", return_value=qdrant_results),
        ):
            results = await KnowledgeRetrievalService.search(
                collection="menu_knowledge",
                query="猪肉类菜品",
                tenant_id="tenant_001",
                top_k=3,
            )
            assert len(results) == 3
            assert results[0]["score"] == 0.95
            assert results[0]["doc_id"] == "d1"

    @pytest.mark.asyncio
    async def test_search_empty_query_returns_empty(self):
        """空查询直接返回空列表"""
        results = await KnowledgeRetrievalService.search(
            collection="menu_knowledge",
            query="",
            tenant_id="tenant_001",
        )
        assert results == []


class TestHybridSearch:
    """测试3：混合检索 — 向量相似度 + 关键词过滤"""

    @pytest.mark.asyncio
    async def test_search_with_keyword_filter(self):
        """带keyword过滤时，filter参数传递给Qdrant"""
        captured_filter = {}

        async def fake_search(collection, query_vector, filter=None, limit=5):
            captured_filter.update(filter or {})
            return []

        with (
            patch.object(EmbeddingService, "embed_text", return_value=_fake_vector()),
            patch.object(QdrantClient, "search", side_effect=fake_search),
        ):
            await KnowledgeRetrievalService.search(
                collection="menu_knowledge",
                query="红烧系列",
                tenant_id="tenant_001",
                filters={"category": "热菜"},
            )

        # filter应包含tenant_id + category两个条件
        must_conditions = captured_filter.get("must", [])
        keys = [c["key"] for c in must_conditions]
        assert "tenant_id" in keys
        assert "category" in keys

    @pytest.mark.asyncio
    async def test_search_filter_includes_category_value(self):
        """过滤条件的value正确设置"""
        captured_filter = {}

        async def fake_search(collection, query_vector, filter=None, limit=5):
            captured_filter.update(filter or {})
            return []

        with (
            patch.object(EmbeddingService, "embed_text", return_value=_fake_vector()),
            patch.object(QdrantClient, "search", side_effect=fake_search),
        ):
            await KnowledgeRetrievalService.search(
                collection="menu_knowledge",
                query="海鲜推荐",
                tenant_id="tenant_001",
                filters={"category": "海鲜"},
            )

        must_conditions = captured_filter.get("must", [])
        category_cond = next((c for c in must_conditions if c["key"] == "category"), None)
        assert category_cond is not None
        assert category_cond["match"]["value"] == "海鲜"


class TestTenantIsolation:
    """测试4：tenant隔离 — tenant_A的知识不被tenant_B检索到"""

    @pytest.mark.asyncio
    async def test_search_always_adds_tenant_id_filter(self):
        """每次检索都强制添加tenant_id过滤"""
        captured_filter = {}

        async def fake_search(collection, query_vector, filter=None, limit=5):
            captured_filter.update(filter or {})
            return []

        with (
            patch.object(EmbeddingService, "embed_text", return_value=_fake_vector()),
            patch.object(QdrantClient, "search", side_effect=fake_search),
        ):
            await KnowledgeRetrievalService.search(
                collection="menu_knowledge",
                query="菜品推荐",
                tenant_id="tenant_A",
            )

        must_conds = captured_filter.get("must", [])
        tenant_cond = next((c for c in must_conds if c["key"] == "tenant_id"), None)
        assert tenant_cond is not None
        assert tenant_cond["match"]["value"] == "tenant_A"

    @pytest.mark.asyncio
    async def test_different_tenants_use_different_filter_values(self):
        """不同tenant的检索使用各自的tenant_id过滤，互不影响"""
        filters_by_call: list[dict] = []

        async def fake_search(collection, query_vector, filter=None, limit=5):
            filters_by_call.append(filter or {})
            return []

        with (
            patch.object(EmbeddingService, "embed_text", return_value=_fake_vector()),
            patch.object(QdrantClient, "search", side_effect=fake_search),
        ):
            await KnowledgeRetrievalService.search("menu_knowledge", "查询", "tenant_A")
            await KnowledgeRetrievalService.search("menu_knowledge", "查询", "tenant_B")

        assert len(filters_by_call) == 2

        def get_tenant(filt):
            for c in filt.get("must", []):
                if c["key"] == "tenant_id":
                    return c["match"]["value"]
            return None

        assert get_tenant(filters_by_call[0]) == "tenant_A"
        assert get_tenant(filters_by_call[1]) == "tenant_B"

    @pytest.mark.asyncio
    async def test_index_document_stores_tenant_id_in_payload(self):
        """索引文档时tenant_id写入payload，防止跨租户查询"""
        stored_payloads: list[dict] = []

        async def fake_upsert(collection, points):
            for p in points:
                stored_payloads.append(p.get("payload", {}))
            return True

        with (
            patch.object(QdrantClient, "create_collection_if_not_exists", return_value=True),
            patch.object(EmbeddingService, "embed_text", return_value=_fake_vector()),
            patch.object(QdrantClient, "upsert", side_effect=fake_upsert),
        ):
            await KnowledgeRetrievalService.index_document("menu_knowledge", "doc:001", "招牌菜", {}, "tenant_A")
            await KnowledgeRetrievalService.index_document("menu_knowledge", "doc:002", "特色菜", {}, "tenant_B")

        assert stored_payloads[0]["tenant_id"] == "tenant_A"
        assert stored_payloads[1]["tenant_id"] == "tenant_B"


class TestGracefulDegradation:
    """测试5：Qdrant不可用时graceful降级"""

    @pytest.mark.asyncio
    async def test_search_returns_empty_when_qdrant_down(self):
        """Qdrant宕机时search返回空列表，不抛异常"""
        with (
            patch.object(EmbeddingService, "embed_text", return_value=_fake_vector()),
            patch.object(QdrantClient, "search", side_effect=ConnectionRefusedError("down")),
        ):
            # QdrantClient内部已捕获异常，返回[]
            results = await KnowledgeRetrievalService.search(
                collection="menu_knowledge",
                query="菜品推荐",
                tenant_id="tenant_001",
            )
            assert results == []

    @pytest.mark.asyncio
    async def test_index_document_returns_false_when_qdrant_down(self):
        """Qdrant宕机时index_document返回False，不抛异常"""
        with (
            patch.object(QdrantClient, "create_collection_if_not_exists", return_value=False),
        ):
            result = await KnowledgeRetrievalService.index_document(
                collection="menu_knowledge",
                doc_id="doc:001",
                text="测试菜品",
                metadata={},
                tenant_id="tenant_001",
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_false_when_qdrant_down(self):
        """Qdrant宕机时is_available返回False"""
        with patch.object(QdrantClient, "health_check", return_value=False):
            available = await KnowledgeRetrievalService.is_available()
            assert available is False

    @pytest.mark.asyncio
    async def test_batch_index_returns_all_failed_when_collection_unavailable(self):
        """collection不可用时批量索引返回全部失败计数"""
        with patch.object(QdrantClient, "create_collection_if_not_exists", return_value=False):
            docs = [{"doc_id": f"d{i}", "text": f"文档{i}", "metadata": {}} for i in range(5)]
            result = await KnowledgeRetrievalService.index_documents_batch("menu_knowledge", docs, "tenant_001")
            assert result["success"] == 0
            assert result["failed"] == 5


class TestBatchIndex:
    """测试6：批量索引（大量文档一次性写入）"""

    @pytest.mark.asyncio
    async def test_batch_index_processes_all_documents(self):
        """批量索引正确处理所有文档"""
        upsert_calls: list[int] = []

        async def fake_upsert(collection, points):
            upsert_calls.append(len(points))
            return True

        with (
            patch.object(QdrantClient, "create_collection_if_not_exists", return_value=True),
            patch.object(EmbeddingService, "embed_batch", side_effect=lambda texts: [_fake_vector() for _ in texts]),
            patch.object(QdrantClient, "upsert", side_effect=fake_upsert),
        ):
            docs = [{"doc_id": f"d{i}", "text": f"菜品{i}描述", "metadata": {"idx": i}} for i in range(10)]
            result = await KnowledgeRetrievalService.index_documents_batch(
                collection="menu_knowledge",
                documents=docs,
                tenant_id="tenant_001",
                batch_size=5,
            )

        assert result["success"] == 10
        assert result["failed"] == 0
        # 10条文档按batch_size=5分两批
        assert len(upsert_calls) == 2
        assert all(n == 5 for n in upsert_calls)

    @pytest.mark.asyncio
    async def test_batch_index_empty_docs_returns_zero(self):
        """空文档列表返回0/0"""
        result = await KnowledgeRetrievalService.index_documents_batch("menu_knowledge", [], "tenant_001")
        assert result == {"success": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_batch_index_handles_upsert_failure(self):
        """upsert失败时记录failed计数"""
        with (
            patch.object(QdrantClient, "create_collection_if_not_exists", return_value=True),
            patch.object(EmbeddingService, "embed_batch", side_effect=lambda texts: [_fake_vector() for _ in texts]),
            patch.object(QdrantClient, "upsert", return_value=False),
        ):
            docs = [{"doc_id": f"d{i}", "text": f"菜品{i}", "metadata": {}} for i in range(3)]
            result = await KnowledgeRetrievalService.index_documents_batch("menu_knowledge", docs, "tenant_001")

        assert result["success"] == 0
        assert result["failed"] == 3

    @pytest.mark.asyncio
    async def test_batch_index_sets_tenant_id_in_all_payloads(self):
        """批量索引时每个文档的payload都包含tenant_id"""
        all_points: list[dict] = []

        async def fake_upsert(collection, points):
            all_points.extend(points)
            return True

        with (
            patch.object(QdrantClient, "create_collection_if_not_exists", return_value=True),
            patch.object(EmbeddingService, "embed_batch", side_effect=lambda texts: [_fake_vector() for _ in texts]),
            patch.object(QdrantClient, "upsert", side_effect=fake_upsert),
        ):
            docs = [{"doc_id": f"d{i}", "text": f"菜品{i}", "metadata": {}} for i in range(4)]
            await KnowledgeRetrievalService.index_documents_batch("menu_knowledge", docs, "tenant_BATCH")

        assert len(all_points) == 4
        for point in all_points:
            assert point["payload"]["tenant_id"] == "tenant_BATCH"


class TestIndexDecisionHistory:
    """测试决策历史索引"""

    @pytest.mark.asyncio
    async def test_index_decision_history_success(self):
        """正常索引决策日志返回True"""
        with (
            patch.object(KnowledgeRetrievalService, "index_document", return_value=True),
        ):
            result = await KnowledgeRetrievalService.index_decision_history(
                agent_id="discount_guard",
                decision_log={
                    "decision_id": "dec_001",
                    "action": "block_discount",
                    "reasoning": "折扣超过毛利底线，拒绝执行",
                    "outcome": "rejected",
                    "confidence": 0.95,
                    "created_at": "2026-03-30T10:00:00Z",
                },
                tenant_id="tenant_001",
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_index_decision_history_empty_reasoning_returns_false(self):
        """空reasoning返回False"""
        result = await KnowledgeRetrievalService.index_decision_history(
            agent_id="discount_guard",
            decision_log={"action": "", "reasoning": ""},
            tenant_id="tenant_001",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_index_decision_doc_id_format(self):
        """决策历史的doc_id格式正确"""
        captured_doc_ids: list[str] = []

        async def fake_index(collection, doc_id, text, metadata, tenant_id):
            captured_doc_ids.append(doc_id)
            return True

        with patch.object(KnowledgeRetrievalService, "index_document", side_effect=fake_index):
            await KnowledgeRetrievalService.index_decision_history(
                agent_id="smart_menu",
                decision_log={
                    "decision_id": "dec_999",
                    "action": "adjust_price",
                    "reasoning": "根据销量调整定价",
                    "outcome": "accepted",
                },
                tenant_id="tenant_001",
            )

        assert len(captured_doc_ids) == 1
        assert captured_doc_ids[0].startswith("decision:smart_menu:")
