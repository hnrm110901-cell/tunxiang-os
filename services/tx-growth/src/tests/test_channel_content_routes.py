"""渠道触达 + 内容模板 API 路由测试
覆盖文件：
  api/channel_routes.py  (5个端点)
  api/content_routes.py  (6个端点，含 validate)

覆盖场景（15个）：
=== channel_routes ===
1.  POST /api/v1/channels/send             — 正常发送，返回 log_id + status=sent
2.  POST /api/v1/channels/send             — 无效 channel 返回 422
3.  POST /api/v1/channels/send             — 今日已超限返回 blocked
4.  GET  /api/v1/channels/{ch}/frequency/{uid} — 返回 allowed + remaining
5.  GET  /api/v1/channels/{ch}/frequency/{uid} — 无效 channel 返回 INVALID_CHANNEL
6.  GET  /api/v1/channels/{ch}/stats       — 正常统计返回 stats 字典
7.  GET  /api/v1/channels/{ch}/stats       — 无效 channel 返回 INVALID_CHANNEL
8.  POST /api/v1/channels/configure        — 正常配置渠道返回 settings_updated=True
9.  GET  /api/v1/channels/send-log         — 正常分页查询返回 items/total
=== content_routes ===
10. POST /api/v1/content/templates         — 正常创建返回 template_id
11. POST /api/v1/content/templates         — 无效 content_type 返回 422
12. GET  /api/v1/content/templates         — 正常列表返回 items
13. POST /api/v1/content/generate          — 指定 template_id 生成内容
14. GET  /api/v1/content/{tid}/performance — 模板不存在返回 NOT_FOUND
15. POST /api/v1/content/validate          — 含禁用词返回 valid=False + errors
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import types
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

# ── 注入假依赖模块（若尚未注入） ─────────────────────────────────────────────

def _ensure_module(path: str):
    parts = path.split(".")
    for i in range(1, len(parts) + 1):
        key = ".".join(parts[:i])
        if key not in sys.modules:
            sys.modules[key] = types.ModuleType(key)

_ensure_module("shared.ontology.src.database")
_ensure_module("shared.events.src.emitter")

# get_db stub（若还未写入）
if not hasattr(sys.modules["shared.ontology.src.database"], "get_db"):
    async def _fake_get_db():
        yield None
    sys.modules["shared.ontology.src.database"].get_db = _fake_get_db

if not hasattr(sys.modules["shared.events.src.emitter"], "emit_event"):
    sys.modules["shared.events.src.emitter"].emit_event = AsyncMock()

# ── 加载路由 ──────────────────────────────────────────────────────────────────

from api.channel_routes import router as channel_router, get_db as channel_get_db
from api.content_routes import router as content_router, get_db as content_get_db

channel_app = FastAPI()
channel_app.include_router(channel_router)
channel_client = TestClient(channel_app, raise_server_exceptions=False)

content_app = FastAPI()
content_app.include_router(content_router)
content_client = TestClient(content_app, raise_server_exceptions=False)

# ── 常量 ──────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": TENANT_ID}
_NOW = datetime(2026, 4, 4, 10, 0, tzinfo=timezone.utc)


# ── 辅助工具 ──────────────────────────────────────────────────────────────────

class _FakeRow:
    """模拟 SQLAlchemy named-column row"""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def __getattr__(self, name):
        return None


def _make_db(*execute_side_effects):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(execute_side_effects))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# === channel_routes 测试 ===
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 场景 1: POST /send — 正常发送
def test_send_message_ok():
    """正常发送消息，返回 log_id 和 status=sent"""
    set_cfg = MagicMock()
    # channel_configs 查询
    cfg_result = MagicMock()
    cfg_result.fetchone = MagicMock(return_value=None)
    # 今日发送次数
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=0)
    # INSERT log
    insert_result = MagicMock()

    mock_db = _make_db(set_cfg, cfg_result, count_result, insert_result)

    channel_app.dependency_overrides[channel_get_db] = lambda: mock_db
    resp = channel_client.post(
        "/api/v1/channels/send",
        json={
            "channel": "sms",
            "user_id": "13812345678",
            "content": "您有新优惠券，点击领取",
        },
        headers=_HEADERS,
    )
    channel_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "log_id" in body["data"]
    assert body["data"]["status"] == "sent"


# 场景 2: POST /send — 无效 channel
def test_send_message_invalid_channel():
    """无效 channel 返回 422 Pydantic 验证错误"""
    mock_db = _make_db()
    channel_app.dependency_overrides[channel_get_db] = lambda: mock_db
    resp = channel_client.post(
        "/api/v1/channels/send",
        json={
            "channel": "BOGUS_CHANNEL",
            "user_id": "user123",
            "content": "test",
        },
        headers=_HEADERS,
    )
    channel_app.dependency_overrides.clear()

    assert resp.status_code == 422


# 场景 3: POST /send — 今日超限
def test_send_message_blocked_by_frequency():
    """今日发送次数超限时返回 status=blocked"""
    set_cfg = MagicMock()
    cfg_result = MagicMock()
    cfg_result.fetchone = MagicMock(return_value=None)
    # 返回已发送 2 次（sms 默认上限 2）
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=2)

    mock_db = _make_db(set_cfg, cfg_result, count_result)

    channel_app.dependency_overrides[channel_get_db] = lambda: mock_db
    resp = channel_client.post(
        "/api/v1/channels/send",
        json={
            "channel": "sms",
            "user_id": "13812345678",
            "content": "超限测试",
        },
        headers=_HEADERS,
    )
    channel_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "blocked"


# 场景 4: GET /{channel}/frequency/{uid} — 正常频率查询
def test_check_frequency_ok():
    """返回 allowed=True 和 remaining 剩余次数"""
    set_cfg = MagicMock()
    cfg_result = MagicMock()
    cfg_result.fetchone = MagicMock(return_value=None)
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=1)

    mock_db = _make_db(set_cfg, cfg_result, count_result)

    channel_app.dependency_overrides[channel_get_db] = lambda: mock_db
    resp = channel_client.get(
        "/api/v1/channels/wecom/frequency/user_001",
        headers=_HEADERS,
    )
    channel_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "allowed" in body["data"]
    assert "remaining" in body["data"]
    assert body["data"]["channel"] == "wecom"


# 场景 5: GET /{channel}/frequency/{uid} — 无效 channel
def test_check_frequency_invalid_channel():
    """无效 channel 返回 INVALID_CHANNEL 错误"""
    mock_db = _make_db()
    channel_app.dependency_overrides[channel_get_db] = lambda: mock_db
    resp = channel_client.get(
        "/api/v1/channels/INVALID/frequency/user_001",
        headers=_HEADERS,
    )
    channel_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INVALID_CHANNEL"


# 场景 6: GET /{channel}/stats — 正常统计
def test_get_channel_stats_ok():
    """正常统计返回 stats 字典含 total/sent_count 等"""
    set_cfg = MagicMock()
    stats_row = _FakeRow(
        total=50,
        sent_count=45,
        failed_count=2,
        blocked_count=3,
        unique_users=30,
    )
    stats_result = MagicMock()
    stats_result.fetchone = MagicMock(return_value=stats_row)

    mock_db = _make_db(set_cfg, stats_result)

    channel_app.dependency_overrides[channel_get_db] = lambda: mock_db
    resp = channel_client.get(
        "/api/v1/channels/sms/stats",
        headers=_HEADERS,
    )
    channel_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "stats" in body["data"]
    assert body["data"]["stats"]["total"] == 50
    assert body["data"]["stats"]["sent_count"] == 45


# 场景 7: GET /{channel}/stats — 无效 channel
def test_get_channel_stats_invalid_channel():
    """无效 channel 返回 INVALID_CHANNEL"""
    mock_db = _make_db()
    channel_app.dependency_overrides[channel_get_db] = lambda: mock_db
    resp = channel_client.get(
        "/api/v1/channels/UNKNOWN/stats",
        headers=_HEADERS,
    )
    channel_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INVALID_CHANNEL"


# 场景 8: POST /configure — 正常渠道配置
def test_configure_channel_ok():
    """正常配置渠道参数，返回 settings_updated=True"""
    set_cfg = MagicMock()
    upsert_result = MagicMock()

    mock_db = _make_db(set_cfg, upsert_result)

    channel_app.dependency_overrides[channel_get_db] = lambda: mock_db
    resp = channel_client.post(
        "/api/v1/channels/configure",
        json={
            "channel": "wecom",
            "settings": {"corpid": "wx123", "corpsecret": "secret456"},
            "max_daily_per_user": 5,
        },
        headers=_HEADERS,
    )
    channel_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["settings_updated"] is True
    assert body["data"]["channel"] == "wecom"
    assert body["data"]["max_daily_per_user"] == 5


# 场景 9: GET /send-log — 正常分页查询
def test_get_send_log_ok():
    """正常查询发送日志，返回 items/total"""
    set_cfg = MagicMock()
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=3)
    log_row = _FakeRow(
        id=uuid.uuid4(),
        channel="sms",
        customer_id=uuid.uuid4(),
        external_user_id="13800000000",
        content_summary="新品优惠",
        offer_id=None,
        campaign_id=None,
        status="sent",
        error_reason=None,
        sent_at=_NOW,
    )
    rows_result = MagicMock()
    rows_result.fetchall = MagicMock(return_value=[log_row])

    mock_db = _make_db(set_cfg, count_result, rows_result)

    channel_app.dependency_overrides[channel_get_db] = lambda: mock_db
    resp = channel_client.get(
        "/api/v1/channels/send-log",
        headers=_HEADERS,
    )
    channel_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "items" in body["data"]
    assert body["data"]["total"] == 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# === content_routes 测试 ===
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 场景 10: POST /templates — 正常创建
def test_create_template_ok():
    """正常创建自定义模板，返回 template_id"""
    set_cfg = MagicMock()
    insert_result = MagicMock()

    mock_db = _make_db(set_cfg, insert_result)

    content_app.dependency_overrides[content_get_db] = lambda: mock_db
    resp = content_client.post(
        "/api/v1/content/templates",
        json={
            "name": "自定义活动推文",
            "content_type": "sms",
            "body_template": "【{brand_name}】{customer_name}，您好！{offer_text}",
            "variables": ["brand_name", "customer_name", "offer_text"],
        },
        headers=_HEADERS,
    )
    content_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "template_id" in body["data"]
    assert body["data"]["is_builtin"] is False


# 场景 11: POST /templates — 无效 content_type
def test_create_template_invalid_type():
    """无效 content_type 返回 422 Pydantic 验证错误"""
    mock_db = _make_db()
    content_app.dependency_overrides[content_get_db] = lambda: mock_db
    resp = content_client.post(
        "/api/v1/content/templates",
        json={
            "name": "测试",
            "content_type": "UNKNOWN_TYPE",
            "body_template": "Hello {name}",
            "variables": ["name"],
        },
        headers=_HEADERS,
    )
    content_app.dependency_overrides.clear()

    assert resp.status_code == 422


# 场景 12: GET /templates — 正常列表
def test_list_templates_ok():
    """正常列表请求返回 items 和 total"""
    set_cfg = MagicMock()
    # _ensure_builtin_templates 会执行多次 INSERT（8个内置模板），全部用 MagicMock
    builtin_inserts = [MagicMock() for _ in range(8)]
    commit_after_builtins = MagicMock()
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=2)
    template_row = _FakeRow(
        id=uuid.uuid4(),
        template_key="sms_reactivation",
        name="短信召回",
        content_type="sms",
        body_template="【{brand_name}】{customer_name}，好久没见！{offer_text}",
        variables=["brand_name", "customer_name", "offer_text"],
        is_builtin=True,
        usage_count=5,
        created_at=_NOW,
        updated_at=_NOW,
    )
    rows_result = MagicMock()
    rows_result.fetchall = MagicMock(return_value=[template_row])

    mock_db = _make_db(set_cfg, *builtin_inserts, count_result, rows_result)

    content_app.dependency_overrides[content_get_db] = lambda: mock_db
    resp = content_client.get(
        "/api/v1/content/templates",
        headers=_HEADERS,
    )
    content_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "items" in body["data"]


# 场景 13: POST /generate — 指定 template_id 生成内容
def test_generate_content_ok():
    """指定 template_id，变量填充成功返回 generated_text"""
    template_id = str(uuid.uuid4())
    set_cfg = MagicMock()
    tpl_row = _FakeRow(
        id=uuid.UUID(template_id),
        name="短信召回",
        content_type="sms",
        body_template="【{brand_name}】{customer_name}，好久没见！{offer_text}。退订回T",
        variables=["brand_name", "customer_name", "offer_text"],
    )
    select_result = MagicMock()
    select_result.fetchone = MagicMock(return_value=tpl_row)
    update_result = MagicMock()

    mock_db = _make_db(set_cfg, select_result, update_result)

    content_app.dependency_overrides[content_get_db] = lambda: mock_db
    resp = content_client.post(
        "/api/v1/content/generate",
        json={
            "content_type": "sms",
            "template_id": template_id,
            "variables": {
                "brand_name": "屯象餐厅",
                "customer_name": "张三",
                "offer_text": "9折优惠",
            },
        },
        headers=_HEADERS,
    )
    content_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "generated_text" in body["data"]
    assert "屯象餐厅" in body["data"]["generated_text"]
    assert body["data"]["missing_variables"] == []


# 场景 14: GET /{template_id}/performance — 模板不存在
def test_get_template_performance_not_found():
    """不存在的 template_id 返回 NOT_FOUND"""
    template_id = str(uuid.uuid4())
    set_cfg = MagicMock()
    not_found_result = MagicMock()
    not_found_result.fetchone = MagicMock(return_value=None)

    mock_db = _make_db(set_cfg, not_found_result)

    content_app.dependency_overrides[content_get_db] = lambda: mock_db
    resp = content_client.get(
        f"/api/v1/content/{template_id}/performance",
        headers=_HEADERS,
    )
    content_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"


# 场景 15: POST /validate — 含广告法禁用词
def test_validate_content_forbidden_words():
    """包含广告法禁用词时返回 valid=False 且 errors 非空"""
    resp = content_client.post(
        "/api/v1/content/validate",
        json={
            "brand_id": str(uuid.uuid4()),
            "content_text": "我们是全网最低价，100%保证品质！",
        },
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True          # HTTP 响应本身 ok
    assert body["data"]["valid"] is False
    assert len(body["data"]["errors"]) > 0


# 额外场景: POST /validate — 合规内容
def test_validate_content_ok():
    """合规内容返回 valid=True"""
    resp = content_client.post(
        "/api/v1/content/validate",
        json={
            "brand_id": str(uuid.uuid4()),
            "content_text": "尊敬的张三，我们的新品已上线，欢迎品尝！",
        },
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["valid"] is True
    assert body["data"]["errors"] == []
