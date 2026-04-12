"""pgvector 向量存储测试

覆盖场景：
1. health_check 在 vector 扩展存在时返回 True
2. health_check 在异常时返回 False
3. upsert_chunks 写入正确的 SQL 含向量嵌入
4. upsert_chunks 成功时返回 {success: N, failed: 0}
5. upsert_chunks 失败时优雅降级 {success: 0, failed: N}
6. vector_search 查询前设置 RLS 租户上下文
7. vector_search 返回格式化结果
8. vector_search 异常时返回 []（优雅降级）
9. keyword_search 返回匹配 tsvector 查询的结果
10. keyword_search 空查询返回 []
11. delete_by_document 执行含正确 WHERE 子句的 DELETE
12. 租户隔离：所有查询包含 tenant_id 过滤
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_KS_DIR = os.path.dirname(_TESTS_DIR)
_SHARED_DIR = os.path.dirname(_KS_DIR)
_ROOT_DIR = os.path.dirname(_SHARED_DIR)
sys.path.insert(0, _ROOT_DIR)

from shared.knowledge_store.pg_vector_store import PgVectorStore


# ── 工具：生成假向量 ────────────────────────────────────────────

def _fake_embedding(val: float = 0.1, size: int = 1536) -> list[float]:
    return [val] * size


def _mock_db_session() -> AsyncMock:
    """创建模拟的 AsyncSession"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


# ── health_check 测试 ────────────────────────────────────────────

class TestHealthCheck:
    """健康检查测试"""

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_vector_extension_exists(self):
        """pgvector 扩展存在时返回 True"""
        db = _mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1  # 扩展存在
        db.execute.return_value = mock_result

        result = await PgVectorStore.health_check(db)
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_extension_missing(self):
        """pgvector 扩展不存在时返回 False"""
        db = _mock_db_session()
        mock_result = MagicMock()
        mock_result.scalar.return_value = None  # 扩展不存在
        db.execute.return_value = mock_result

        result = await PgVectorStore.health_check(db)
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_exception(self):
        """数据库异常时返回 False，不抛异常"""
        db = _mock_db_session()
        db.execute.side_effect = ConnectionRefusedError("db offline")

        result = await PgVectorStore.health_check(db)
        assert result is False


# ── upsert_chunks 测试 ──────────────────────────────────────────

class TestUpsertChunks:
    """知识块写入测试"""

    @pytest.mark.asyncio
    async def test_upsert_empty_chunks_returns_zero(self):
        """空列表不执行SQL，返回 {success:0, failed:0}"""
        db = _mock_db_session()
        result = await PgVectorStore.upsert_chunks([], "tenant_001", db)
        assert result == {"success": 0, "failed": 0}
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_upsert_chunks_success(self):
        """正常写入返回 {success: N, failed: 0}"""
        db = _mock_db_session()
        chunks = [
            {
                "text": "红烧肉做法",
                "embedding": _fake_embedding(0.1, 4),
                "metadata": {"category": "热菜"},
                "doc_id": "dish:001",
                "document_id": "00000000-0000-0000-0000-000000000001",
                "collection": "menu_knowledge",
                "chunk_index": 0,
                "token_count": 10,
            },
            {
                "text": "清蒸鱼做法",
                "embedding": _fake_embedding(0.2, 4),
                "metadata": {"category": "海鲜"},
                "doc_id": "dish:002",
                "document_id": "00000000-0000-0000-0000-000000000001",
                "collection": "menu_knowledge",
                "chunk_index": 1,
                "token_count": 8,
            },
        ]

        result = await PgVectorStore.upsert_chunks(chunks, "tenant_001", db)
        assert result == {"success": 2, "failed": 0}

    @pytest.mark.asyncio
    async def test_upsert_chunks_sets_rls_context(self):
        """写入前设置 RLS 租户上下文"""
        db = _mock_db_session()
        chunks = [{"text": "test", "embedding": [0.1], "metadata": {}, "doc_id": "d1"}]

        await PgVectorStore.upsert_chunks(chunks, "tenant_XYZ", db)

        # 检查第一次 execute 调用是设置 tenant_id
        first_call_args = db.execute.call_args_list[0]
        sql_arg = str(first_call_args[0][0])
        assert "set_config" in sql_arg
        assert first_call_args[0][1]["tid"] == "tenant_XYZ"

    @pytest.mark.asyncio
    async def test_upsert_chunks_handles_individual_failures(self):
        """单条写入失败时记录 failed 计数，不影响其他条目"""
        db = _mock_db_session()

        call_count = 0

        async def selective_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            sql_str = str(args[0]) if args else ""
            if "set_config" in sql_str:
                return MagicMock()
            # 第二次 INSERT 抛异常
            if call_count == 3:  # 1=set_config, 2=INSERT#1, 3=INSERT#2
                raise ValueError("simulated failure")
            return MagicMock()

        db.execute = AsyncMock(side_effect=selective_execute)

        chunks = [
            {"text": "chunk1", "embedding": [0.1], "metadata": {}, "doc_id": "d1"},
            {"text": "chunk2", "embedding": [0.2], "metadata": {}, "doc_id": "d2"},
        ]

        result = await PgVectorStore.upsert_chunks(chunks, "tenant_001", db)
        assert result["success"] == 1
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_upsert_chunks_batch_failure_returns_all_failed(self):
        """批次级别异常时所有条目标记为 failed"""
        db = _mock_db_session()
        db.execute.side_effect = ConnectionRefusedError("db down")

        chunks = [
            {"text": f"chunk{i}", "embedding": [0.1], "metadata": {}, "doc_id": f"d{i}"}
            for i in range(3)
        ]

        result = await PgVectorStore.upsert_chunks(chunks, "tenant_001", db)
        assert result["failed"] == 3
        assert result["success"] == 0

    @pytest.mark.asyncio
    async def test_upsert_commits_after_success(self):
        """成功写入后调用 commit"""
        db = _mock_db_session()
        chunks = [{"text": "test", "embedding": [0.1], "metadata": {}, "doc_id": "d1"}]

        await PgVectorStore.upsert_chunks(chunks, "tenant_001", db)
        db.commit.assert_called_once()


# ── vector_search 测试 ──────────────────────────────────────────

class TestVectorSearch:
    """向量相似度检索测试"""

    @pytest.mark.asyncio
    async def test_vector_search_sets_rls_context(self):
        """检索前设置 RLS 租户上下文"""
        db = _mock_db_session()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        db.execute.return_value = mock_result

        await PgVectorStore.vector_search(
            query_embedding=_fake_embedding(0.1, 4),
            collection="menu_knowledge",
            tenant_id="tenant_ABC",
            db=db,
        )

        first_call_args = db.execute.call_args_list[0]
        sql_arg = str(first_call_args[0][0])
        assert "set_config" in sql_arg
        assert first_call_args[0][1]["tid"] == "tenant_ABC"

    @pytest.mark.asyncio
    async def test_vector_search_returns_formatted_results(self):
        """检索返回格式化的结果列表"""
        db = _mock_db_session()
        # set_config 调用
        db.execute.side_effect = [
            MagicMock(),  # set_config
            MagicMock(fetchall=MagicMock(return_value=[
                ("chunk-id-1", "doc:001", "红烧肉做法", 0.95, {"cat": "热菜"}, 0, "doc-uuid-1"),
                ("chunk-id-2", "doc:002", "清蒸鱼做法", 0.87, {"cat": "海鲜"}, 1, "doc-uuid-1"),
            ])),
        ]

        results = await PgVectorStore.vector_search(
            query_embedding=_fake_embedding(0.1, 4),
            collection="menu_knowledge",
            tenant_id="tenant_001",
            db=db,
        )

        assert len(results) == 2
        assert results[0]["chunk_id"] == "chunk-id-1"
        assert results[0]["doc_id"] == "doc:001"
        assert results[0]["text"] == "红烧肉做法"
        assert results[0]["score"] == 0.95
        assert results[0]["chunk_index"] == 0
        assert results[0]["document_id"] == "doc-uuid-1"

    @pytest.mark.asyncio
    async def test_vector_search_returns_empty_on_exception(self):
        """数据库异常时返回[]，不抛异常"""
        db = _mock_db_session()
        db.execute.side_effect = ConnectionRefusedError("db offline")

        results = await PgVectorStore.vector_search(
            query_embedding=_fake_embedding(0.1, 4),
            collection="menu_knowledge",
            tenant_id="tenant_001",
            db=db,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_vector_search_includes_tenant_id_in_query(self):
        """检索 SQL 包含 tenant_id 过滤条件"""
        db = _mock_db_session()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        db.execute.side_effect = [MagicMock(), mock_result]

        await PgVectorStore.vector_search(
            query_embedding=_fake_embedding(0.1, 4),
            collection="menu_knowledge",
            tenant_id="tenant_001",
            db=db,
        )

        # 第二次调用是实际查询
        query_call = db.execute.call_args_list[1]
        sql_str = str(query_call[0][0])
        assert "tenant_id" in sql_str

    @pytest.mark.asyncio
    async def test_vector_search_passes_filters_to_query(self):
        """额外的 metadata 过滤条件传递到 SQL"""
        db = _mock_db_session()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        db.execute.side_effect = [MagicMock(), mock_result]

        await PgVectorStore.vector_search(
            query_embedding=_fake_embedding(0.1, 4),
            collection="menu_knowledge",
            tenant_id="tenant_001",
            db=db,
            filters={"category": "热菜"},
        )

        query_call = db.execute.call_args_list[1]
        params = query_call[0][1]
        assert params["fk0"] == "category"
        assert params["fv0"] == "热菜"


# ── keyword_search 测试 ─────────────────────────────────────────

class TestKeywordSearch:
    """关键词全文检索测试"""

    @pytest.mark.asyncio
    async def test_keyword_search_empty_query_returns_empty(self):
        """空查询直接返回[]"""
        db = _mock_db_session()
        result = await PgVectorStore.keyword_search("", "menu_knowledge", "tenant_001", db)
        assert result == []

    @pytest.mark.asyncio
    async def test_keyword_search_whitespace_query_returns_empty(self):
        """纯空白查询返回[]"""
        db = _mock_db_session()
        result = await PgVectorStore.keyword_search("   ", "menu_knowledge", "tenant_001", db)
        assert result == []

    @pytest.mark.asyncio
    async def test_keyword_search_returns_results(self):
        """关键词检索返回格式化结果"""
        db = _mock_db_session()
        db.execute.side_effect = [
            MagicMock(),  # set_config
            MagicMock(fetchall=MagicMock(return_value=[
                ("chunk-kw-1", "doc:010", "红烧肉的制作步骤", 0.65, {"cat": "热菜"}, 0, "doc-uuid-2"),
            ])),
        ]

        results = await PgVectorStore.keyword_search(
            query="红烧肉",
            collection="menu_knowledge",
            tenant_id="tenant_001",
            db=db,
        )

        assert len(results) == 1
        assert results[0]["chunk_id"] == "chunk-kw-1"
        assert results[0]["text"] == "红烧肉的制作步骤"
        assert results[0]["score"] == 0.65

    @pytest.mark.asyncio
    async def test_keyword_search_sets_rls_context(self):
        """关键词检索前设置 RLS 租户上下文"""
        db = _mock_db_session()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        db.execute.side_effect = [MagicMock(), mock_result]

        await PgVectorStore.keyword_search("测试", "menu_knowledge", "tenant_XYZ", db)

        first_call = db.execute.call_args_list[0]
        assert first_call[0][1]["tid"] == "tenant_XYZ"

    @pytest.mark.asyncio
    async def test_keyword_search_returns_empty_on_exception(self):
        """数据库异常时返回[]"""
        db = _mock_db_session()
        db.execute.side_effect = ConnectionRefusedError("db offline")

        results = await PgVectorStore.keyword_search("红烧肉", "menu_knowledge", "tenant_001", db)
        assert results == []


# ── delete_by_document 测试 ─────────────────────────────────────

class TestDeleteByDocument:
    """文档删除测试"""

    @pytest.mark.asyncio
    async def test_delete_by_document_executes_delete(self):
        """删除操作执行带 document_id 和 tenant_id 的 DELETE"""
        db = _mock_db_session()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        db.execute.side_effect = [MagicMock(), mock_result]  # set_config, DELETE

        count = await PgVectorStore.delete_by_document(
            document_id="00000000-0000-0000-0000-000000000001",
            tenant_id="tenant_001",
            db=db,
        )
        assert count == 5

    @pytest.mark.asyncio
    async def test_delete_by_document_includes_tenant_id(self):
        """DELETE SQL 包含 tenant_id 过滤"""
        db = _mock_db_session()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        db.execute.side_effect = [MagicMock(), mock_result]

        await PgVectorStore.delete_by_document(
            document_id="doc-uuid",
            tenant_id="tenant_001",
            db=db,
        )

        # 第二次调用是 DELETE
        delete_call = db.execute.call_args_list[1]
        sql_str = str(delete_call[0][0])
        assert "tenant_id" in sql_str
        assert "document_id" in sql_str

    @pytest.mark.asyncio
    async def test_delete_by_document_commits(self):
        """删除后调用 commit"""
        db = _mock_db_session()
        mock_result = MagicMock()
        mock_result.rowcount = 2
        db.execute.side_effect = [MagicMock(), mock_result]

        await PgVectorStore.delete_by_document("doc-uuid", "tenant_001", db)
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_by_document_returns_zero_on_exception(self):
        """异常时返回 0，不抛异常"""
        db = _mock_db_session()
        db.execute.side_effect = ConnectionRefusedError("db down")

        count = await PgVectorStore.delete_by_document("doc-uuid", "tenant_001", db)
        assert count == 0


# ── 租户隔离综合验证 ────────────────────────────────────────────

class TestTenantIsolation:
    """租户隔离：所有操作包含 tenant_id"""

    @pytest.mark.asyncio
    async def test_upsert_includes_tenant_id_in_params(self):
        """upsert 的 SQL 参数包含 tenant_id"""
        db = _mock_db_session()
        chunks = [{"text": "test", "embedding": [0.1], "metadata": {}, "doc_id": "d1"}]

        await PgVectorStore.upsert_chunks(chunks, "tenant_ISOLATION", db)

        # 检查 INSERT 调用中的参数
        for call_args in db.execute.call_args_list:
            params = call_args[0][1] if len(call_args[0]) > 1 else {}
            if "tenant_id" in params:
                assert params["tenant_id"] == "tenant_ISOLATION"

    @pytest.mark.asyncio
    async def test_vector_search_query_includes_tenant_id_param(self):
        """vector_search 的 SQL 参数包含 tenant_id"""
        db = _mock_db_session()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        db.execute.side_effect = [MagicMock(), mock_result]

        await PgVectorStore.vector_search(
            query_embedding=[0.1, 0.2],
            collection="test_col",
            tenant_id="tenant_ISO",
            db=db,
        )

        query_call = db.execute.call_args_list[1]
        params = query_call[0][1]
        assert params["tenant_id"] == "tenant_ISO"
