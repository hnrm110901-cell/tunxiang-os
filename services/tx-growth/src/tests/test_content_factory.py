"""智能内容工厂测试 — content_factory / poster_generator / content_publisher / routes

覆盖场景：
  TestContentFactory:
    1.  auto_generate 正常（mock Claude）→ 返回内容+model+ai_prompt_context
    2.  auto_generate 渠道格式验证：moments<=120字, wecom_chat<=80字, sms<=70字
    3.  generate_for_dish 菜品内容生成（多渠道）
    4.  generate_for_dish 菜品不存在 → 空列表
    5.  generate_for_holiday 全渠道节日内容
    6.  generate_weekly_plan 覆盖7天
    7.  schedule_content 设置排期 → status=scheduled
    8.  approve_content 审批 → approved_by + approved_at

  TestPosterGenerator:
    9.  get_poster_templates → 5个模板
    10. generate_poster_data 有菜品 → 返回完整结构
    11. generate_poster_data 无菜品有活动 → 标题含活动名

  TestContentPublisher:
    12. tick 查找到期内容并发布
    13. publish_single 成功 → status=published
    14. publish_single 内容不存在 → failed

  TestContentCalendarRoutes:
    15. GET / → 200 + items列表
    16. POST / → 200 + 创建成功
    17. PUT /{id} → 200 + 更新成功
    18. DELETE /{id} → 200 + 软删除
    19. POST /auto-generate (auto) → 200
    20. POST /auto-generate (weekly_plan) → 200
    21. POST /{id}/schedule → 200
    22. POST /{id}/publish → 200
    23. GET /calendar-view → 200 + 按日期分组
"""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Stub heavy dependencies before importing modules
# ---------------------------------------------------------------------------
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Stub structlog
_structlog_mod = types.ModuleType("structlog")
_structlog_mod.get_logger = MagicMock(return_value=MagicMock())
sys.modules.setdefault("structlog", _structlog_mod)

# Stub sqlalchemy
_sqla_mod = types.ModuleType("sqlalchemy")


def _fake_text(sql: str):
    return sql


_sqla_mod.text = _fake_text
sys.modules.setdefault("sqlalchemy", _sqla_mod)

_sqla_ext = types.ModuleType("sqlalchemy.ext")
_sqla_ext_asyncio = types.ModuleType("sqlalchemy.ext.asyncio")
_sqla_ext_asyncio.AsyncSession = MagicMock()
sys.modules.setdefault("sqlalchemy.ext", _sqla_ext)
sys.modules.setdefault("sqlalchemy.ext.asyncio", _sqla_ext_asyncio)

_sqla_exc = types.ModuleType("sqlalchemy.exc")
_sqla_exc.SQLAlchemyError = type("SQLAlchemyError", (Exception,), {})
sys.modules.setdefault("sqlalchemy.exc", _sqla_exc)

# Stub httpx
_httpx_mod = types.ModuleType("httpx")
_httpx_mod.AsyncClient = MagicMock()
_httpx_mod.TimeoutException = type("TimeoutException", (Exception,), {})
_httpx_mod.HTTPStatusError = type(
    "HTTPStatusError",
    (Exception,),
    {
        "__init__": lambda self, *a, **kw: None,
        "response": MagicMock(status_code=500),
    },
)
sys.modules.setdefault("httpx", _httpx_mod)

# Stub shared.ontology.src.database
_shared = types.ModuleType("shared")
_shared_ontology = types.ModuleType("shared.ontology")
_shared_ontology_src = types.ModuleType("shared.ontology.src")
_shared_ontology_src_database = types.ModuleType("shared.ontology.src.database")
_shared_ontology_src_database.get_db = MagicMock()
sys.modules.setdefault("shared", _shared)
sys.modules.setdefault("shared.ontology", _shared_ontology)
sys.modules.setdefault("shared.ontology.src", _shared_ontology_src)
sys.modules.setdefault("shared.ontology.src.database", _shared_ontology_src_database)

# Stub redis
_redis_mod = types.ModuleType("redis")
_redis_asyncio = types.ModuleType("redis.asyncio")
sys.modules.setdefault("redis", _redis_mod)
sys.modules.setdefault("redis.asyncio", _redis_asyncio)

# Stub pydantic
_pydantic = types.ModuleType("pydantic")
_pydantic.BaseModel = type("BaseModel", (), {"__init_subclass__": classmethod(lambda cls, **kw: None)})
sys.modules.setdefault("pydantic", _pydantic)

# Stub fastapi
_fastapi = types.ModuleType("fastapi")
_fastapi.APIRouter = MagicMock()
_fastapi.Depends = MagicMock(side_effect=lambda x: None)
_fastapi.Header = MagicMock(side_effect=lambda *a, **kw: None)
_fastapi.Query = MagicMock(side_effect=lambda *a, **kw: None)
sys.modules.setdefault("fastapi", _fastapi)

# Import after stubs
from services.content_factory import CHANNEL_REQUIREMENTS, ContentFactory
from services.poster_generator import PosterGenerator

# ChannelEngine stub for publisher
_channel_engine_mock = MagicMock()
_channel_engine_mock.send_message = AsyncMock(return_value={"message_id": "msg_001"})

TID = str(uuid.uuid4())
CONTENT_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helper: mock db
# ---------------------------------------------------------------------------


def _make_db():
    """Create a mock AsyncSession"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


def _make_row(data: dict):
    """Wrap dict as a DB row result"""
    result = MagicMock()
    mapping = MagicMock()
    mapping.__getitem__ = lambda self, k: data[k]
    mapping.get = lambda k, default=None: data.get(k, default)
    result.mappings.return_value.first.return_value = mapping
    return result


def _make_rows(items: list[dict]):
    """Wrap list of dicts as DB rows"""
    result = MagicMock()
    mappings = []
    for d in items:
        m = MagicMock()
        m.__getitem__ = lambda self, k, _d=d: _d[k]
        m.get = lambda k, default=None, _d=d: _d.get(k, default)
        mappings.append(m)
    result.mappings.return_value.all.return_value = mappings
    return result


# ===========================================================================
# TestContentFactory
# ===========================================================================


class TestContentFactory:
    """内容工厂核心测试"""

    @pytest.mark.asyncio
    async def test_auto_generate_returns_content(self):
        """1. auto_generate 正常生成 → 返回内容+model+ai_prompt_context"""
        factory = ContentFactory()
        db = _make_db()

        # Mock brand info
        brand_row = _make_row(
            {
                "brand_name": "徐记海鲜",
                "brand_voice": "高端温暖",
                "tone_keywords": "鲜美,品质",
            }
        )
        db.execute.side_effect = [
            AsyncMock(return_value=None)(),  # set_tenant
            brand_row,  # brand query
        ]

        with patch.object(factory, "_call_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = {
                "content": "周末和家人来一顿鲜美海鲜吧！",
                "model": "claude-haiku",
                "success": True,
            }
            result = await factory.auto_generate(
                TID,
                db,
                {
                    "target_channel": "moments",
                    "event_name": "周末特惠",
                },
            )

        assert result["success"] is True
        assert len(result["content"]) > 0
        assert result["model"] == "claude-haiku"
        assert result["ai_prompt_context"]["target_channel"] == "moments"

    @pytest.mark.asyncio
    async def test_channel_format_limits(self):
        """2. 渠道字符限制定义正确"""
        assert CHANNEL_REQUIREMENTS["moments"]["max_chars"] == 120
        assert CHANNEL_REQUIREMENTS["wecom_chat"]["max_chars"] == 80
        assert CHANNEL_REQUIREMENTS["sms"]["max_chars"] == 70
        assert CHANNEL_REQUIREMENTS["dish_story"]["max_chars"] == 150

    @pytest.mark.asyncio
    async def test_generate_for_dish_multi_channel(self):
        """3. generate_for_dish 多渠道菜品生成"""
        factory = ContentFactory()
        db = _make_db()

        dish_row = _make_row(
            {
                "name": "清蒸石斑鱼",
                "description": "新鲜活鱼现杀现蒸",
                "price_fen": 18800,
                "category": "海鲜",
            }
        )
        brand_row = _make_row(
            {
                "brand_name": "徐记海鲜",
                "brand_voice": "高端温暖",
                "tone_keywords": "鲜美",
            }
        )

        db.execute.side_effect = [
            AsyncMock(return_value=None)(),  # set_tenant
            dish_row,  # dish query
            brand_row,  # brand query (1st channel)
            brand_row,  # brand query (2nd channel)
        ]

        with patch.object(factory, "_call_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = {
                "content": "鲜活石斑鱼",
                "model": "claude-haiku",
                "success": True,
            }
            results = await factory.generate_for_dish(TID, DISH_ID, db, channels=["moments", "sms"])

        assert len(results) == 2
        assert results[0]["channel"] == "moments"
        assert results[1]["channel"] == "sms"
        assert results[0]["dish_name"] == "清蒸石斑鱼"

    @pytest.mark.asyncio
    async def test_generate_for_dish_not_found(self):
        """4. generate_for_dish 菜品不存在 → 空列表"""
        factory = ContentFactory()
        db = _make_db()

        empty_result = MagicMock()
        empty_result.mappings.return_value.first.return_value = None

        db.execute.side_effect = [
            AsyncMock(return_value=None)(),  # set_tenant
            empty_result,  # dish not found
        ]

        results = await factory.generate_for_dish(TID, "nonexistent", db)
        assert results == []

    @pytest.mark.asyncio
    async def test_generate_for_holiday_all_channels(self):
        """5. generate_for_holiday 全渠道节日内容"""
        factory = ContentFactory()
        db = _make_db()

        brand_row = _make_row(
            {
                "brand_name": "徐记海鲜",
                "brand_voice": "高端温暖",
                "tone_keywords": "鲜美",
            }
        )
        db.execute.side_effect = [
            brand_row,  # brand query for each channel call
            brand_row,
            brand_row,
            brand_row,
        ]

        with patch.object(factory, "_call_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = {
                "content": "春节快乐！",
                "model": "claude-haiku",
                "success": True,
            }
            results = await factory.generate_for_holiday(TID, "春节", db)

        assert len(results) == 4  # moments, wecom_chat, sms, poster
        channels = [r["channel"] for r in results]
        assert "moments" in channels
        assert "sms" in channels

    @pytest.mark.asyncio
    async def test_generate_weekly_plan_7_days(self):
        """6. generate_weekly_plan 覆盖Mon-Sun 7天"""
        factory = ContentFactory()
        db = _make_db()

        brand_row = _make_row(
            {
                "brand_name": "徐记海鲜",
                "brand_voice": "高端温暖",
                "tone_keywords": "鲜美",
            }
        )
        # 7 brand queries for 7 days
        db.execute.side_effect = [brand_row] * 7

        with patch.object(factory, "_call_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = {
                "content": "每日内容",
                "model": "claude-haiku",
                "success": True,
            }
            results = await factory.generate_weekly_plan(TID, db)

        assert len(results) == 7
        days = [r["day"] for r in results]
        assert days == ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        # 每天都有 scheduled_at
        for r in results:
            assert r["scheduled_at"] is not None

    @pytest.mark.asyncio
    async def test_schedule_content(self):
        """7. schedule_content → status=scheduled"""
        factory = ContentFactory()
        db = _make_db()

        update_row = _make_row(
            {
                "id": uuid.UUID(CONTENT_ID),
                "status": "scheduled",
                "scheduled_at": datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
            }
        )
        db.execute.side_effect = [
            AsyncMock(return_value=None)(),  # set_tenant
            update_row,
        ]

        result = await factory.schedule_content(TID, CONTENT_ID, "2026-05-01T10:00:00Z", db)
        assert result["status"] == "scheduled"

    @pytest.mark.asyncio
    async def test_approve_content(self):
        """8. approve_content → approved_by + approved_at"""
        factory = ContentFactory()
        db = _make_db()
        approver_id = str(uuid.uuid4())

        approve_row = _make_row(
            {
                "id": uuid.UUID(CONTENT_ID),
                "approved_by": uuid.UUID(approver_id),
                "approved_at": datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc),
            }
        )
        db.execute.side_effect = [
            AsyncMock(return_value=None)(),  # set_tenant
            approve_row,
        ]

        result = await factory.approve_content(TID, CONTENT_ID, approver_id, db)
        assert result["approved_by"] == approver_id


# ===========================================================================
# TestPosterGenerator
# ===========================================================================


class TestPosterGenerator:
    """海报生成器测试"""

    def test_get_poster_templates_returns_5(self):
        """9. get_poster_templates → 5个模板"""
        gen = PosterGenerator()
        templates = gen.get_poster_templates()
        assert len(templates) == 5
        names = [t["template_id"] for t in templates]
        assert "new_dish" in names
        assert "seasonal" in names
        assert "holiday" in names
        assert "member_day" in names
        assert "flash_sale" in names

    @pytest.mark.asyncio
    async def test_generate_poster_data_with_dish(self):
        """10. generate_poster_data 有菜品 → 返回完整结构"""
        gen = PosterGenerator()
        db = _make_db()

        brand_row = _make_row(
            {
                "brand_name": "徐记海鲜",
                "logo_url": "https://cdn.example.com/logo.png",
            }
        )
        dish_row = _make_row(
            {
                "name": "清蒸石斑鱼",
                "description": "新鲜活鱼",
                "price_fen": 18800,
                "image_url": "https://cdn.example.com/dish.jpg",
            }
        )
        db.execute.side_effect = [
            AsyncMock(return_value=None)(),  # set_tenant
            brand_row,
            dish_row,
        ]

        result = await gen.generate_poster_data(TID, db, dish_id=DISH_ID, template="new_dish")
        assert "title" in result
        assert "subtitle" in result
        assert "cta_text" in result
        assert result["background_color"] == "#FF6B35"
        assert result["brand_name"] == "徐记海鲜"

    @pytest.mark.asyncio
    async def test_generate_poster_data_event_only(self):
        """11. generate_poster_data 无菜品有活动 → 标题含活动名"""
        gen = PosterGenerator()
        db = _make_db()

        brand_row = _make_row({"brand_name": "徐记海鲜", "logo_url": ""})
        db.execute.side_effect = [
            AsyncMock(return_value=None)(),  # set_tenant
            brand_row,
        ]

        result = await gen.generate_poster_data(TID, db, event_name="周年庆", template="holiday")
        assert "周年庆" in result["title"]


# ===========================================================================
# TestContentPublisher
# ===========================================================================


class TestContentPublisher:
    """内容发布工作器测试"""

    @pytest.mark.asyncio
    async def test_tick_finds_due_items(self):
        """12. tick 查找到期内容并逐个发布"""
        # Import with channel_engine stubbed
        with patch.dict(sys.modules, {}):
            from workers.content_publisher import ContentPublisher

        publisher = ContentPublisher()
        db = _make_db()

        cid1 = str(uuid.uuid4())
        due_rows = _make_rows(
            [
                {"id": uuid.UUID(cid1), "tenant_id": uuid.UUID(TID)},
            ]
        )
        db.execute.return_value = due_rows

        with patch.object(publisher, "publish_single", new_callable=AsyncMock) as mock_pub:
            mock_pub.return_value = {"status": "published"}
            result = await publisher.tick(db)

        assert result["due"] == 1
        assert result["published"] == 1

    @pytest.mark.asyncio
    async def test_publish_single_success(self):
        """13. publish_single 成功 → status=published"""
        from workers.content_publisher import ContentPublisher

        publisher = ContentPublisher()
        db = _make_db()

        content_row = _make_row(
            {
                "id": uuid.UUID(CONTENT_ID),
                "content_body": "测试内容",
                "content_type": "moments",
                "target_channels": [{"channel": "wecom"}],
                "media_urls": [],
            }
        )
        db.execute.side_effect = [
            AsyncMock(return_value=None)(),  # set_tenant
            AsyncMock(return_value=None)(),  # update to publishing
            content_row,  # read content
            AsyncMock(return_value=None)(),  # update published
        ]

        with patch("workers.content_publisher._channel_engine") as mock_ce:
            mock_ce.send_message = AsyncMock(return_value={"message_id": "m1"})
            result = await publisher.publish_single(TID, CONTENT_ID, db)

        assert result["status"] == "published"

    @pytest.mark.asyncio
    async def test_publish_single_not_found(self):
        """14. publish_single 内容不存在 → failed"""
        from workers.content_publisher import ContentPublisher

        publisher = ContentPublisher()
        db = _make_db()

        empty_result = MagicMock()
        empty_result.mappings.return_value.first.return_value = None

        db.execute.side_effect = [
            AsyncMock(return_value=None)(),  # set_tenant
            AsyncMock(return_value=None)(),  # update to publishing
            empty_result,  # content not found
        ]

        result = await publisher.publish_single(TID, "nonexistent", db)
        assert result["status"] == "failed"


# ===========================================================================
# TestContentCalendarRoutes
# ===========================================================================


class TestContentCalendarRoutes:
    """内容日历路由端点测试"""

    @pytest.mark.asyncio
    async def test_list_content(self):
        """15. GET / → 200 + items列表"""
        from api.content_calendar_routes import list_content

        db = _make_db()
        count_result = MagicMock()
        count_result.scalar.return_value = 1

        now = datetime(2026, 4, 25, tzinfo=timezone.utc)
        items_result = _make_rows(
            [
                {
                    "id": uuid.UUID(CONTENT_ID),
                    "store_id": None,
                    "title": "测试内容",
                    "content_type": "moments",
                    "content_body": "测试",
                    "media_urls": [],
                    "target_channels": [],
                    "tags": [],
                    "ai_generated": False,
                    "ai_model": None,
                    "status": "draft",
                    "scheduled_at": None,
                    "published_at": None,
                    "created_by": None,
                    "approved_by": None,
                    "approved_at": None,
                    "view_count": 0,
                    "click_count": 0,
                    "share_count": 0,
                    "created_at": now,
                    "updated_at": now,
                }
            ]
        )

        db.execute.side_effect = [
            AsyncMock(return_value=None)(),  # set_tenant
            count_result,
            items_result,
        ]

        result = await list_content(
            status=None,
            content_type=None,
            date_from=None,
            date_to=None,
            page=1,
            size=20,
            x_tenant_id=TID,
            db=db,
        )
        assert result["ok"] is True
        assert result["data"]["total"] == 1
        assert len(result["data"]["items"]) == 1

    @pytest.mark.asyncio
    async def test_create_content(self):
        """16. POST / → 200 + 创建成功"""
        from api.content_calendar_routes import CreateContentRequest, create_content

        db = _make_db()
        now = datetime(2026, 4, 25, tzinfo=timezone.utc)
        insert_row = _make_row(
            {
                "id": uuid.UUID(CONTENT_ID),
                "status": "draft",
                "created_at": now,
            }
        )
        db.execute.side_effect = [
            AsyncMock(return_value=None)(),  # set_tenant
            insert_row,
        ]

        req = CreateContentRequest(
            title="五一活动推广",
            content_type="moments",
            content_body="五一快乐，来徐记海鲜吧！",
        )
        result = await create_content(req=req, x_tenant_id=TID, db=db)
        assert result["ok"] is True
        assert result["data"]["status"] == "draft"

    @pytest.mark.asyncio
    async def test_update_content(self):
        """17. PUT /{id} → 200 + 更新成功"""
        from api.content_calendar_routes import UpdateContentRequest, update_content

        db = _make_db()
        now = datetime(2026, 4, 25, tzinfo=timezone.utc)
        update_row = _make_row(
            {
                "id": uuid.UUID(CONTENT_ID),
                "title": "更新后的标题",
                "status": "draft",
                "updated_at": now,
            }
        )
        db.execute.side_effect = [
            AsyncMock(return_value=None)(),  # set_tenant
            update_row,
        ]

        req = UpdateContentRequest(title="更新后的标题")
        result = await update_content(content_id=CONTENT_ID, req=req, x_tenant_id=TID, db=db)
        assert result["ok"] is True
        assert result["data"]["title"] == "更新后的标题"

    @pytest.mark.asyncio
    async def test_delete_content(self):
        """18. DELETE /{id} → 200 + 软删除"""
        from api.content_calendar_routes import delete_content

        db = _make_db()
        delete_row = _make_row({"id": uuid.UUID(CONTENT_ID)})
        db.execute.side_effect = [
            AsyncMock(return_value=None)(),  # set_tenant
            delete_row,
        ]

        result = await delete_content(content_id=CONTENT_ID, x_tenant_id=TID, db=db)
        assert result["ok"] is True
        assert result["data"]["deleted"] is True

    @pytest.mark.asyncio
    async def test_auto_generate_auto_mode(self):
        """19. POST /auto-generate (auto) → 200"""
        from api.content_calendar_routes import AutoGenerateRequest, auto_generate_content

        db = _make_db()

        with patch("api.content_calendar_routes._factory") as mock_factory:
            mock_factory.auto_generate = AsyncMock(
                return_value={
                    "content": "AI生成的文案",
                    "model": "claude-haiku",
                    "success": True,
                    "suggested_media": [],
                    "ai_prompt_context": {},
                }
            )
            req = AutoGenerateRequest(
                mode="auto",
                target_channel="moments",
                event_name="周末特惠",
            )
            result = await auto_generate_content(req=req, x_tenant_id=TID, db=db)

        assert result["ok"] is True
        assert result["data"]["mode"] == "auto"

    @pytest.mark.asyncio
    async def test_auto_generate_weekly_plan(self):
        """20. POST /auto-generate (weekly_plan) → 200"""
        from api.content_calendar_routes import AutoGenerateRequest, auto_generate_content

        db = _make_db()

        with patch("api.content_calendar_routes._factory") as mock_factory:
            mock_factory.generate_weekly_plan = AsyncMock(
                return_value=[{"day": f"周{d}", "content": "内容"} for d in "一二三四五六日"]
            )
            req = AutoGenerateRequest(mode="weekly_plan")
            result = await auto_generate_content(req=req, x_tenant_id=TID, db=db)

        assert result["ok"] is True
        assert result["data"]["mode"] == "weekly_plan"
        assert len(result["data"]["results"]) == 7

    @pytest.mark.asyncio
    async def test_schedule_content_route(self):
        """21. POST /{id}/schedule → 200"""
        from api.content_calendar_routes import ScheduleRequest, schedule_content

        db = _make_db()

        with patch("api.content_calendar_routes._factory") as mock_factory:
            mock_factory.schedule_content = AsyncMock(
                return_value={
                    "id": CONTENT_ID,
                    "status": "scheduled",
                    "scheduled_at": "2026-05-01T10:00:00+00:00",
                }
            )
            req = ScheduleRequest(scheduled_at="2026-05-01T10:00:00Z")
            result = await schedule_content(content_id=CONTENT_ID, req=req, x_tenant_id=TID, db=db)

        assert result["ok"] is True
        assert result["data"]["status"] == "scheduled"

    @pytest.mark.asyncio
    async def test_publish_content_route(self):
        """22. POST /{id}/publish → 200"""
        from api.content_calendar_routes import publish_content

        db = _make_db()

        with patch("api.content_calendar_routes._publisher") as mock_pub:
            mock_pub.publish_single = AsyncMock(
                return_value={
                    "id": CONTENT_ID,
                    "status": "published",
                    "publish_result": {"channel_results": []},
                }
            )
            result = await publish_content(content_id=CONTENT_ID, x_tenant_id=TID, db=db)

        assert result["ok"] is True
        assert result["data"]["status"] == "published"

    @pytest.mark.asyncio
    async def test_calendar_view(self):
        """23. GET /calendar-view → 200 + 按日期分组"""
        from api.content_calendar_routes import calendar_view

        db = _make_db()
        now = datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)
        rows = _make_rows(
            [
                {
                    "id": uuid.UUID(CONTENT_ID),
                    "title": "测试",
                    "content_type": "moments",
                    "status": "scheduled",
                    "display_date": now,
                    "ai_generated": True,
                    "store_id": None,
                }
            ]
        )

        db.execute.side_effect = [
            AsyncMock(return_value=None)(),  # set_tenant
            rows,
        ]

        result = await calendar_view(
            year=2026,
            month=4,
            store_id=None,
            x_tenant_id=TID,
            db=db,
        )
        assert result["ok"] is True
        assert "2026-04-25" in result["data"]["dates"]
