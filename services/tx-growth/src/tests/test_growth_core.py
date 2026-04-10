"""tx-growth 核心路由单元测试

覆盖范围：
  - journey_routes.py  (12 端点，测 5 个最关键场景)
  - growth_campaign_routes.py (9 端点，测 5 个最关键场景)

运行：
  cd services/tx-growth
  pytest src/tests/test_growth_core.py -v
"""

import sys
import types
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError

# ---------------------------------------------------------------------------
# ① 注入最小存根，解决相对导入和缺失依赖
# ---------------------------------------------------------------------------

# --- structlog stub ---
structlog_stub = types.ModuleType("structlog")
structlog_stub.get_logger = lambda *a, **kw: MagicMock()
sys.modules.setdefault("structlog", structlog_stub)

# --- shared.events stub ---
_events_pkg = types.ModuleType("shared.events")
_events_src = types.ModuleType("shared.events.src")
_emitter_mod = types.ModuleType("shared.events.src.emitter")
_emitter_mod.emit_event = AsyncMock(return_value=None)
_event_types_mod = types.ModuleType("shared.events.src.event_types")
_event_pub = types.ModuleType("shared.events.event_publisher")
_event_pub.MemberEventPublisher = MagicMock()
for _mod_name, _mod in [
    ("shared", types.ModuleType("shared")),
    ("shared.events", _events_pkg),
    ("shared.events.src", _events_src),
    ("shared.events.src.emitter", _emitter_mod),
    ("shared.events.src.event_types", _event_types_mod),
    ("shared.events.event_publisher", _event_pub),
]:
    sys.modules.setdefault(_mod_name, _mod)

# --- shared.ontology stub ---
_ontology_pkg = types.ModuleType("shared.ontology")
_ontology_src = types.ModuleType("shared.ontology.src")
_database_mod = types.ModuleType("shared.ontology.src.database")

# 真实 get_db 占位符 — 测试中会被 dependency_overrides 替换
async def _placeholder_get_db():
    yield MagicMock()

_database_mod.get_db = _placeholder_get_db
_database_mod.async_session_factory = MagicMock()
_database_mod.init_db = AsyncMock()
for _mod_name, _mod in [
    ("shared.ontology", _ontology_pkg),
    ("shared.ontology.src", _ontology_src),
    ("shared.ontology.src.database", _database_mod),
]:
    sys.modules.setdefault(_mod_name, _mod)

# --- engine / service stubs（journey_routes 需要）---
_engine_mod = types.ModuleType("engine")
_journey_engine_mod = types.ModuleType("engine.journey_engine")
_journey_engine_mod.JourneyEngine = MagicMock()
sys.modules.setdefault("engine", _engine_mod)
sys.modules.setdefault("engine.journey_engine", _journey_engine_mod)

_templates_mod = types.ModuleType("templates")
_journey_tmpl_mod = types.ModuleType("templates.journey_templates")
_journey_tmpl_mod.TEMPLATES = {
    "first_visit_welcome": {
        "name": "首次到访欢迎",
        "trigger_event": "first_visit",
        "steps": [{"step_id": "s1", "action_type": "send_sms", "action_config": {}, "wait_hours": 0, "next_steps": []}],
    }
}
sys.modules.setdefault("templates", _templates_mod)
sys.modules.setdefault("templates.journey_templates", _journey_tmpl_mod)

# --- services stubs（growth_campaign_routes 的相对导入）---
_services_mod = types.ModuleType("services")
_campaign_engine_mod = types.ModuleType("services.campaign_engine")
_campaign_engine_mod.CampaignEngine = MagicMock()
_campaign_repo_mod = types.ModuleType("services.campaign_repository")
_campaign_repo_mod.CampaignRepository = MagicMock()
sys.modules.setdefault("services", _services_mod)
sys.modules.setdefault("services.campaign_engine", _campaign_engine_mod)
sys.modules.setdefault("services.campaign_repository", _campaign_repo_mod)

# ---------------------------------------------------------------------------
# ② 导入路由模块（必须在 stub 注入之后）
# ---------------------------------------------------------------------------

# 把 src 加入 path，使相对导入能定位到正确包
import os
_src_dir = os.path.join(os.path.dirname(__file__), "..")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# journey_routes 使用 async_session_factory（上下文管理器），不走 get_db
# 我们需要 patch async_session_factory；在此先导入以备用
from api import journey_routes  # noqa: E402
from api import growth_campaign_routes  # noqa: E402
from shared.ontology.src.database import get_db  # noqa: E402


# ---------------------------------------------------------------------------
# ③ 构建 FastAPI 测试应用
# ---------------------------------------------------------------------------

app = FastAPI()
app.include_router(journey_routes.router)
app.include_router(growth_campaign_routes.router)

TENANT_ID = str(uuid.uuid4())
DEF_ID = str(uuid.uuid4())
CAMPAIGN_ID = str(uuid.uuid4())
CUSTOMER_ID = str(uuid.uuid4())

HEADERS = {"X-Tenant-ID": TENANT_ID}


# ---------------------------------------------------------------------------
# ④ Helpers
# ---------------------------------------------------------------------------

def _make_mock_db():
    """返回一个完整 mock AsyncSession，支持 async with / execute / commit。"""
    db = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _scalar_result(value):
    r = MagicMock()
    r.scalar = MagicMock(return_value=value)
    r.fetchall = MagicMock(return_value=[])
    r.fetchone = MagicMock(return_value=None)
    return r


def _fetchone_result(row):
    r = MagicMock()
    r.fetchone = MagicMock(return_value=row)
    return r


def _fetchall_result(rows):
    r = MagicMock()
    r.fetchall = MagicMock(return_value=rows)
    return r


# ---------------------------------------------------------------------------
# ⑤ 测试：journey_routes.py（5 个）
# ---------------------------------------------------------------------------

class TestJourneyRoutes:

    # ------------------------------------------------------------------
    # J-1 GET /definitions — 正常返回空列表
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_list_definitions_returns_empty(self):
        mock_db = _make_mock_db()

        def _side_effect(stmt, params=None):
            # 第1次：SET LOCAL；第2次：COUNT；第3次：SELECT rows
            call_count = mock_db.execute.call_count
            if call_count == 1:
                return MagicMock()
            elif call_count == 2:
                return _scalar_result(0)
            else:
                return _fetchall_result([])

        mock_db.execute.side_effect = _side_effect

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(journey_routes, "async_session_factory", return_value=ctx):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/api/v1/journey/definitions", headers=HEADERS
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0

    # ------------------------------------------------------------------
    # J-2 POST /definitions — 正常创建旅程
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_create_definition_success(self):
        mock_db = _make_mock_db()
        mock_db.execute.return_value = MagicMock()

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)

        payload = {
            "name": "新客欢迎旅程",
            "trigger_event": "first_visit",
            "steps": [
                {
                    "step_id": "s1",
                    "action_type": "send_sms",
                    "action_config": {},
                    "wait_hours": 0,
                    "next_steps": [],
                }
            ],
        }

        with patch.object(journey_routes, "async_session_factory", return_value=ctx):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/journey/definitions", json=payload, headers=HEADERS
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["name"] == "新客欢迎旅程"
        assert body["data"]["is_active"] is False
        # 应返回合法 UUID
        uuid.UUID(body["data"]["id"])

    # ------------------------------------------------------------------
    # J-3 POST /definitions — steps 为空时返回 422
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_create_definition_empty_steps_422(self):
        payload = {
            "name": "空步骤旅程",
            "trigger_event": "first_visit",
            "steps": [],
        }

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/journey/definitions", json=payload, headers=HEADERS
            )

        assert resp.status_code == 422

    # ------------------------------------------------------------------
    # J-4 GET /definitions/{id} — 资源不存在返回 404
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_get_definition_not_found_404(self):
        mock_db = _make_mock_db()
        mock_db.execute.return_value = _fetchone_result(None)

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(journey_routes, "async_session_factory", return_value=ctx):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v1/journey/definitions/{DEF_ID}", headers=HEADERS
                )

        assert resp.status_code == 404

    # ------------------------------------------------------------------
    # J-5 DELETE /definitions/{id} — 资源存在时正常软删除
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_delete_definition_success(self):
        deleted_row = MagicMock()  # fetchone 返回非空行代表找到
        mock_db = _make_mock_db()

        call_count = 0

        async def _execute_side(stmt, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # SET LOCAL
                return MagicMock()
            else:
                # UPDATE … RETURNING id
                return _fetchone_result(deleted_row)

        mock_db.execute = AsyncMock(side_effect=_execute_side)

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(journey_routes, "async_session_factory", return_value=ctx):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.delete(
                    f"/api/v1/journey/definitions/{DEF_ID}", headers=HEADERS
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["deleted"] is True


# ---------------------------------------------------------------------------
# ⑥ 测试：growth_campaign_routes.py（5 个）
# ---------------------------------------------------------------------------

class TestGrowthCampaignRoutes:
    """growth_campaign_routes 使用 Depends(get_db)，通过 app.dependency_overrides 注入 mock。"""

    def _override_db(self, mock_db):
        """返回一个可注册为依赖覆盖的异步生成器函数。"""
        async def _get_mock_db():
            yield mock_db
        app.dependency_overrides[get_db] = _get_mock_db

    def teardown_method(self):
        app.dependency_overrides.clear()

    # ------------------------------------------------------------------
    # C-1 GET /growth/campaigns — 正常返回活动列表
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_list_campaigns_ok(self):
        mock_db = _make_mock_db()

        call_count = 0

        async def _execute_side(stmt, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MagicMock()          # set_config
            elif call_count == 2:
                return _scalar_result(0)    # COUNT
            else:
                return _fetchall_result([]) # SELECT rows

        mock_db.execute = AsyncMock(side_effect=_execute_side)
        self._override_db(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/growth/campaigns", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0

    # ------------------------------------------------------------------
    # C-2 POST /growth/campaigns — 正常创建活动
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_create_campaign_success(self):
        cid = str(uuid.uuid4())
        mock_engine = MagicMock()
        mock_engine.create_campaign = AsyncMock(
            return_value={"campaign_id": cid, "status": "draft"}
        )

        mock_db = _make_mock_db()
        self._override_db(mock_db)

        with patch.object(growth_campaign_routes, "_engine", mock_engine):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/growth/campaigns",
                    json={
                        "name": "双十一优惠券",
                        "type": "coupon_giveaway",
                        "budget_fen": 100000,
                        "rules": {"max_claim": 500},
                    },
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["campaign_id"] == cid
        assert body["data"]["status"] == "draft"

    # ------------------------------------------------------------------
    # C-3 POST /growth/campaigns — type 非法时返回 error
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_create_campaign_invalid_type(self):
        mock_db = _make_mock_db()
        self._override_db(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/growth/campaigns",
                json={"name": "测试", "type": "not_a_valid_type"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "INVALID_TYPE"

    # ------------------------------------------------------------------
    # C-4 GET /growth/campaigns/{id}/stats — 活动不存在返回 NOT_FOUND error
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_get_campaign_stats_not_found(self):
        mock_repo = MagicMock()
        mock_repo.get_analytics = AsyncMock(return_value=None)

        mock_db = _make_mock_db()
        mock_db.execute.return_value = MagicMock()
        self._override_db(mock_db)

        with patch.object(
            growth_campaign_routes, "CampaignRepository", return_value=mock_repo
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v1/growth/campaigns/{CAMPAIGN_ID}/stats",
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "NOT_FOUND"

    # ------------------------------------------------------------------
    # C-5 GET /growth/campaigns — DB 错误时返回 DB_ERROR（非表缺失异常）
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_list_campaigns_db_error(self):
        mock_db = _make_mock_db()

        call_count = 0

        async def _execute_side(stmt, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MagicMock()      # set_config
            # 第2次 COUNT 抛出非 table-missing 的 SQLAlchemy 错误
            raise SQLAlchemyError("connection refused")

        mock_db.execute = AsyncMock(side_effect=_execute_side)
        self._override_db(mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/growth/campaigns", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "DB_ERROR"
