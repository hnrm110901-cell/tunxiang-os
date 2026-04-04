"""public_opinion_routes.py FastAPI 路由单元测试

测试范围（8端点，Round 72新增）：
  - GET  /api/v1/ops/public-opinion/mentions          — 列表查询（正常+DB异常降级）
  - POST /api/v1/ops/public-opinion/mentions          — 新增舆情（正常+DB异常fallback）
  - GET  /api/v1/ops/public-opinion/mentions/{id}     — 单条详情（正常+未找到）
  - PATCH /api/v1/ops/public-opinion/mentions/{id}/resolve — 标记处理（正常+DB异常）
  - GET  /api/v1/ops/public-opinion/stats             — 平台统计（正常+异常降级）
  - GET  /api/v1/ops/public-opinion/trends            — 趋势查询（正常+异常降级）
  - GET  /api/v1/ops/public-opinion/top-complaints    — 高频投诉词（正常+异常降级）
  - POST /api/v1/ops/public-opinion/batch-capture     — 批量导入（正常+commit失败）

技术约束：
  - FastAPI TestClient + unittest.mock 覆盖 get_db 依赖
  - 不连接真实 PostgreSQL
  - emit_event 通过 patch 拦截，不实际发送
  - asyncio.create_task 通过 patch 拦截，验证旁路调用
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from ..api.public_opinion_routes import router as opinion_router
from shared.ontology.src.database import get_db

# ── 应用组装 ──────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(opinion_router)

# ── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
MENTION_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ── Mock DB 工厂 ──────────────────────────────────────────────────────────────


def _make_mock_db(
    scalar_return=0,
    mappings_rows=None,
    raise_on_execute: bool = False,
) -> AsyncMock:
    """构造 mock AsyncSession。

    raise_on_execute=True 时：第1次 execute（set_config RLS）正常，后续抛出 SQLAlchemyError。
    """
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    if raise_on_execute:
        call_count = {"n": 0}

        async def _execute_side(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                ok = MagicMock()
                ok.scalar.return_value = 0
                return ok
            raise SQLAlchemyError("DB error")

        db.execute = AsyncMock(side_effect=_execute_side)
    else:
        mock_result = MagicMock()
        mock_result.scalar.return_value = scalar_return
        # mappings().first()
        mapping_mock = MagicMock()
        mapping_mock.first.return_value = mappings_rows[0] if mappings_rows else None
        mock_result.mappings.return_value = mapping_mock
        # 直接迭代（列表查询用 [dict(r._mapping) for r in rows]）
        rows = mappings_rows or []
        row_objects = []
        for m in rows:
            r = MagicMock()
            r._mapping = m
            row_objects.append(r)
        mock_result.__iter__ = MagicMock(return_value=iter(row_objects))
        db.execute = AsyncMock(return_value=mock_result)

    return db


def _override_get_db(mock_db: AsyncMock):
    async def _dep():
        yield mock_db

    return _dep


# ══════════════════════════════════════════════════════════════════════════════
#  GET /mentions — 舆情列表
# ══════════════════════════════════════════════════════════════════════════════


class TestListMentions:
    """GET /api/v1/ops/public-opinion/mentions"""

    def test_returns_empty_list_when_no_data(self):
        """无数据时返回空列表，ok=True。"""
        mock_db = _make_mock_db(scalar_return=0, mappings_rows=[])
        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/public-opinion/mentions",
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["mentions"] == []
        assert data["data"]["total"] == 0
        assert data["data"]["page"] == 1

    def test_db_error_returns_graceful_fallback(self):
        """DB 异常时降级返回空列表，ok=True（不抛 500）。"""
        mock_db = _make_mock_db(raise_on_execute=True)
        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/public-opinion/mentions",
                params={"platform": "meituan"},
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["mentions"] == []


# ══════════════════════════════════════════════════════════════════════════════
#  POST /mentions — 新增舆情
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateMention:
    """POST /api/v1/ops/public-opinion/mentions"""

    def test_creates_mention_and_emits_event(self):
        """正常新增舆情，返回 mention_id，旁路发射事件。"""
        mock_db = _make_mock_db()

        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with patch("asyncio.create_task") as mock_task:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/public-opinion/mentions",
                    json={
                        "store_id": STORE_ID,
                        "platform": "dianping",
                        "content": "菜品不错，环境一般",
                        "sentiment": "positive",
                        "sentiment_score": 0.85,
                        "rating": 4.5,
                        "tags": ["菜品", "环境"],
                    },
                    headers=HEADERS,
                )
            assert mock_task.called  # emit_event 被旁路调用
        app.dependency_overrides.clear()

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert "mention_id" in data["data"]
        assert data["data"]["platform"] == "dianping"
        assert data["data"]["sentiment"] == "positive"

    def test_db_error_returns_fallback_with_mention_id(self):
        """DB 写入失败时，仍返回 mention_id（fallback），ok=True。"""
        mock_db = _make_mock_db(raise_on_execute=True)
        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with patch("asyncio.create_task"):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/public-opinion/mentions",
                    json={
                        "store_id": STORE_ID,
                        "platform": "weibo",
                        "content": "服务太差了",
                        "sentiment": "negative",
                    },
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert "mention_id" in data["data"]


# ══════════════════════════════════════════════════════════════════════════════
#  GET /mentions/{id} — 单条详情
# ══════════════════════════════════════════════════════════════════════════════


class TestGetMention:
    """GET /api/v1/ops/public-opinion/mentions/{mention_id}"""

    def test_returns_mention_when_found(self):
        """找到记录时返回 mention 数据。"""
        mock_record = {
            "id": MENTION_ID,
            "tenant_id": TENANT_ID,
            "store_id": STORE_ID,
            "platform": "meituan",
            "content": "外卖速度快",
            "sentiment": "positive",
            "sentiment_score": 0.9,
            "rating": 5.0,
            "author_name": "张三",
            "author_id": None,
            "published_at": None,
            "source_url": None,
            "tags": ["速度"],
            "is_resolved": False,
            "resolution_note": None,
            "resolved_at": None,
            "resolver_id": None,
            "created_at": None,
            "updated_at": None,
        }
        mock_db = _make_mock_db(mappings_rows=[mock_record])
        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/ops/public-opinion/mentions/{MENTION_ID}",
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["mention"]["platform"] == "meituan"

    def test_returns_not_found_when_missing(self):
        """记录不存在时返回 ok=False，code=NOT_FOUND。"""
        mock_db = _make_mock_db(mappings_rows=[])  # first() 返回 None
        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/public-opinion/mentions/nonexistent-id",
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════════════
#  PATCH /mentions/{id}/resolve — 标记已处理
# ══════════════════════════════════════════════════════════════════════════════


class TestResolveMention:
    """PATCH /api/v1/ops/public-opinion/mentions/{mention_id}/resolve"""

    def test_resolves_mention_and_emits_event(self):
        """正常处理舆情，返回 is_resolved=True，旁路发射 opinion.resolved 事件。"""
        # 先 SELECT（获取 store_id），再 UPDATE
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        call_count = {"n": 0}

        async def _execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            if call_count["n"] == 1:
                # set_config RLS
                return result
            if call_count["n"] == 2:
                # SELECT store_id, is_resolved
                m = MagicMock()
                m.first.return_value = {"store_id": STORE_ID, "is_resolved": False}
                result.mappings.return_value = m
                return result
            # UPDATE
            result.rowcount = 1
            return result

        mock_db.execute = AsyncMock(side_effect=_execute)

        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with patch("asyncio.create_task") as mock_task:
            with TestClient(app) as client:
                resp = client.patch(
                    f"/api/v1/ops/public-opinion/mentions/{MENTION_ID}/resolve",
                    json={"resolution_note": "已联系客户致歉", "resolver_id": "mgr_001"},
                    headers=HEADERS,
                )
            assert mock_task.called
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["is_resolved"] is True
        assert data["data"]["mention_id"] == MENTION_ID

    def test_resolve_db_error_returns_fallback(self):
        """DB 异常时降级返回 ok=True（不阻塞业务）。"""
        mock_db = _make_mock_db(raise_on_execute=True)
        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with patch("asyncio.create_task"):
            with TestClient(app) as client:
                resp = client.patch(
                    f"/api/v1/ops/public-opinion/mentions/{MENTION_ID}/resolve",
                    json={"resolution_note": "处理中"},
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True


# ══════════════════════════════════════════════════════════════════════════════
#  GET /stats — 平台/周汇总统计
# ══════════════════════════════════════════════════════════════════════════════


class TestGetStats:
    """GET /api/v1/ops/public-opinion/stats"""

    def test_returns_stats_from_mv(self):
        """正常返回物化视图数据，source=mv_public_opinion。"""
        mock_db = _make_mock_db(mappings_rows=[])
        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/public-opinion/stats",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "stats" in data["data"]

    def test_db_error_returns_empty_stats(self):
        """DB 双重失败时返回空 stats，source=error。"""
        mock_db = _make_mock_db(raise_on_execute=True)
        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/public-opinion/stats",
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["stats"] == []


# ══════════════════════════════════════════════════════════════════════════════
#  GET /trends — 最近8周趋势
# ══════════════════════════════════════════════════════════════════════════════


class TestGetTrends:
    """GET /api/v1/ops/public-opinion/trends"""

    def test_returns_trend_data(self):
        """正常返回趋势数组（可为空）。"""
        mock_db = _make_mock_db(mappings_rows=[])
        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/public-opinion/trends",
                params={"platform": "dianping"},
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert isinstance(data["data"]["trends"], list)

    def test_db_error_returns_empty_trends(self):
        """DB 异常时降级返回空 trends。"""
        mock_db = _make_mock_db(raise_on_execute=True)
        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/public-opinion/trends",
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["trends"] == []


# ══════════════════════════════════════════════════════════════════════════════
#  GET /top-complaints — 高频投诉关键词
# ══════════════════════════════════════════════════════════════════════════════


class TestTopComplaints:
    """GET /api/v1/ops/public-opinion/top-complaints"""

    def test_returns_keywords_list(self):
        """正常返回 keywords 列表（可为空）。"""
        mock_db = _make_mock_db(mappings_rows=[])
        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/public-opinion/top-complaints",
                params={"limit": 10},
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert isinstance(data["data"]["keywords"], list)

    def test_db_error_returns_empty_keywords(self):
        """DB 异常时降级返回空 keywords。"""
        mock_db = _make_mock_db(raise_on_execute=True)
        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/public-opinion/top-complaints",
                headers=HEADERS,
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["keywords"] == []


# ══════════════════════════════════════════════════════════════════════════════
#  POST /batch-capture — 批量导入
# ══════════════════════════════════════════════════════════════════════════════


class TestBatchCapture:
    """POST /api/v1/ops/public-opinion/batch-capture"""

    _sample_mentions = [
        {
            "store_id": STORE_ID,
            "platform": "dianping",
            "content": "好吃",
            "sentiment": "positive",
        },
        {
            "store_id": STORE_ID,
            "platform": "meituan",
            "content": "一般",
            "sentiment": "neutral",
        },
    ]

    def test_batch_insert_success(self):
        """正常批量导入，返回 inserted 数量与 mention_ids。"""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with patch("asyncio.create_task"):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/public-opinion/batch-capture",
                    json={"mentions": self._sample_mentions},
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["inserted"] == 2
        assert len(data["data"]["mention_ids"]) == 2
        assert data["data"]["failed_indices"] == []

    def test_batch_commit_failure_returns_zero_inserted(self):
        """commit 失败时，返回 inserted=0，ok=True（降级）。"""
        mock_db = _make_mock_db()
        mock_db.commit = AsyncMock(side_effect=SQLAlchemyError("commit fail"))
        app.dependency_overrides[get_db] = _override_get_db(mock_db)
        with patch("asyncio.create_task"):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/public-opinion/batch-capture",
                    json={"mentions": self._sample_mentions},
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["inserted"] == 0
