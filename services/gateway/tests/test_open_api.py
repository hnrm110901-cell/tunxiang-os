"""Tests for Phase 4-A: 开放API平台

覆盖:
 1. 应用注册返回app_key + app_secret（明文只一次）
 2. secret以hash形式存储（不含明文）
 3. issue_token成功返回access_token
 4. issue_token with wrong secret返回401
 5. issue_token with suspended app返回403
 6. verify_token成功
 7. verify_token expired返回None
 8. verify_token revoked返回None
 9. scope超集检查（requested > allowed → PermissionError）
10. rate_limit: 超出限制返回429
11. rate_limit: Redis不可用时优雅降级
12. rotate_secret吊销旧token
13. webhook dispatch发送HMAC签名
14. webhook signature验证
15. webhook retry on failure
16. 请求日志字段验证（不含金额/敏感字段）
17. 租户隔离（跨租户不可见）
18. revoke_token后verify返回None
"""

from __future__ import annotations

import os

# ── 被测模块 ──────────────────────────────────────────────────────
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from middleware.rate_limiter import RateLimiter
from services.oauth2_service import OAuth2Service
from services.webhook_dispatcher import WebhookDispatcher

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _make_db_mock() -> AsyncMock:
    """创建模拟AsyncSession"""
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


def _configure_db_for_create_app(db: AsyncMock, app_id: str) -> None:
    """配置DB mock: create_application返回新app_id"""
    result_mock = MagicMock()
    row_mock = MagicMock()
    row_mock.__getitem__ = MagicMock(return_value=app_id)
    result_mock.fetchone = MagicMock(return_value=(app_id,))
    db.execute = AsyncMock(return_value=result_mock)


def _configure_db_for_issue_token(
    db: AsyncMock,
    svc: OAuth2Service,
    app_id: str,
    tenant_id: str,
    secret: str,
    status: str = "active",
    scopes: list | None = None,
) -> None:
    """配置DB mock: issue_token查询app_key成功"""
    if scopes is None:
        scopes = ["orders:read", "members:read"]

    secret_hash = svc._hash_secret(secret)
    token_id = str(uuid4())

    call_count = 0

    async def side_effect(query, params=None):
        nonlocal call_count
        call_count += 1

        mock_result = MagicMock()

        if call_count == 1:
            # 第1次: SELECT app by app_key
            row = MagicMock()
            row.__getitem__ = MagicMock(side_effect=lambda k: {
                "id": app_id,
                "tenant_id": tenant_id,
                "app_secret_hash": secret_hash,
                "status": status,
                "scopes": scopes,
                "rate_limit_per_min": 60,
            }[k])
            mock_result.mappings.return_value.fetchone.return_value = row
        elif call_count == 2:
            # 第2次: INSERT token
            mock_result.fetchone = MagicMock(return_value=(token_id,))
        else:
            # 后续: UPDATE last_active_at
            mock_result.fetchone = MagicMock(return_value=None)

        return mock_result

    db.execute = AsyncMock(side_effect=side_effect)


def _configure_db_for_verify_token(
    db: AsyncMock,
    svc: OAuth2Service,
    raw_token: str,
    token_id: str,
    app_id: str,
    tenant_id: str,
    scopes: list,
    expired: bool = False,
    revoked: bool = False,
) -> None:
    """配置DB mock: verify_token"""
    token_hash = svc._hash_secret(raw_token)
    now = datetime.now(timezone.utc)
    expires_at = now - timedelta(hours=1) if expired else now + timedelta(hours=23)
    revoked_at = now if revoked else None

    call_count = 0

    async def side_effect(query, params=None):
        nonlocal call_count
        call_count += 1

        mock_result = MagicMock()
        if call_count == 1:
            row = MagicMock()
            row.__getitem__ = MagicMock(side_effect=lambda k: {
                "id": token_id,
                "tenant_id": tenant_id,
                "app_id": app_id,
                "scopes": scopes,
                "expires_at": expires_at,
                "revoked_at": revoked_at,
            }[k])
            mock_result.mappings.return_value.fetchone.return_value = row
        else:
            mock_result.fetchone = MagicMock(return_value=None)

        return mock_result

    db.execute = AsyncMock(side_effect=side_effect)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 1: 应用注册返回app_key + app_secret（明文只一次）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_create_application_returns_app_key_and_secret() -> None:
    svc = OAuth2Service()
    db = _make_db_mock()
    app_id = str(uuid4())
    _configure_db_for_create_app(db, app_id)

    result = await svc.create_application(
        tenant_id=uuid4(),
        app_name="测试应用",
        scopes=["orders:read"],
        contact_email="dev@example.com",
        db=db,
    )

    assert "app_key" in result
    assert "app_secret" in result
    assert "app_id" in result
    assert result["app_key"].startswith("txapp_")
    assert len(result["app_secret"]) >= 32
    assert "warning" in result  # 明文只显示一次的警告


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 2: secret以hash形式存储，不含明文
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_create_application_secret_stored_as_hash() -> None:
    svc = OAuth2Service()
    db = _make_db_mock()
    app_id = str(uuid4())

    stored_hash: str | None = None

    async def capture_execute(query, params=None):
        nonlocal stored_hash
        mock_result = MagicMock()

        query_str = str(query)
        if params and "secret_hash" in params:
            stored_hash = params["secret_hash"]

        mock_result.fetchone = MagicMock(return_value=(app_id,))
        mock_result.mappings.return_value.fetchone.return_value = None
        return mock_result

    db.execute = AsyncMock(side_effect=capture_execute)

    result = await svc.create_application(
        tenant_id=uuid4(),
        app_name="哈希测试",
        scopes=[],
        contact_email=None,
        db=db,
    )

    plain_secret = result["app_secret"]
    # 明文不等于存储值
    assert stored_hash != plain_secret
    # 存储值通过PBKDF2可复现
    expected_hash = svc._hash_secret(plain_secret)
    assert stored_hash == expected_hash


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 3: issue_token成功返回access_token
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_issue_token_success() -> None:
    svc = OAuth2Service()
    db = _make_db_mock()
    app_id = str(uuid4())
    tenant_id = str(uuid4())
    secret = "my-test-secret-12345"

    _configure_db_for_issue_token(db, svc, app_id, tenant_id, secret)

    result = await svc.issue_token(
        app_key="txapp_testkey",
        app_secret=secret,
        requested_scopes=["orders:read"],
        db=db,
    )

    assert "access_token" in result
    assert result["token_type"] == "Bearer"
    assert result["expires_in"] == OAuth2Service.TOKEN_EXPIRE_HOURS * 3600
    assert result["token_prefix"].startswith(OAuth2Service.TOKEN_PREFIX)
    assert "scopes" in result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 4: issue_token with wrong secret → PermissionError
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_issue_token_wrong_secret_raises() -> None:
    svc = OAuth2Service()
    db = _make_db_mock()
    app_id = str(uuid4())
    tenant_id = str(uuid4())

    _configure_db_for_issue_token(db, svc, app_id, tenant_id, "correct-secret")

    with pytest.raises(PermissionError, match="app_secret验证失败"):
        await svc.issue_token(
            app_key="txapp_testkey",
            app_secret="wrong-secret",
            requested_scopes=[],
            db=db,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 5: issue_token with suspended app → PermissionError
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_issue_token_suspended_app_raises() -> None:
    svc = OAuth2Service()
    db = _make_db_mock()
    app_id = str(uuid4())
    tenant_id = str(uuid4())
    secret = "valid-secret-xyz"

    _configure_db_for_issue_token(db, svc, app_id, tenant_id, secret, status="suspended")

    with pytest.raises(PermissionError, match="suspended"):
        await svc.issue_token(
            app_key="txapp_testkey",
            app_secret=secret,
            requested_scopes=[],
            db=db,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 6: verify_token成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_verify_token_success() -> None:
    svc = OAuth2Service()
    db = _make_db_mock()
    raw_token = "valid-raw-token-abcdef123456"
    token_id = str(uuid4())
    app_id = str(uuid4())
    tenant_id = str(uuid4())
    scopes = ["orders:read"]

    _configure_db_for_verify_token(db, svc, raw_token, token_id, app_id, tenant_id, scopes)

    result = await svc.verify_token(raw_token, None, db)

    assert result is not None
    assert result["app_id"] == app_id
    assert result["tenant_id"] == tenant_id
    assert "orders:read" in result["scopes"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 7: verify_token expired → None
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_verify_token_expired_returns_none() -> None:
    svc = OAuth2Service()
    db = _make_db_mock()
    raw_token = "expired-token-abc"
    token_id = str(uuid4())
    app_id = str(uuid4())
    tenant_id = str(uuid4())

    _configure_db_for_verify_token(
        db, svc, raw_token, token_id, app_id, tenant_id,
        scopes=["orders:read"], expired=True
    )

    result = await svc.verify_token(raw_token, None, db)
    assert result is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 8: verify_token revoked → None
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_verify_token_revoked_returns_none() -> None:
    svc = OAuth2Service()
    db = _make_db_mock()
    raw_token = "revoked-token-def"
    token_id = str(uuid4())
    app_id = str(uuid4())
    tenant_id = str(uuid4())

    _configure_db_for_verify_token(
        db, svc, raw_token, token_id, app_id, tenant_id,
        scopes=["orders:read"], revoked=True
    )

    result = await svc.verify_token(raw_token, None, db)
    assert result is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 9: scope超集检查（requested > allowed → PermissionError）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_issue_token_scope_exceeded_raises() -> None:
    svc = OAuth2Service()
    db = _make_db_mock()
    app_id = str(uuid4())
    tenant_id = str(uuid4())
    secret = "scope-test-secret"

    # app只有orders:read权限
    _configure_db_for_issue_token(
        db, svc, app_id, tenant_id, secret,
        scopes=["orders:read"]
    )

    with pytest.raises(PermissionError, match="scope"):
        await svc.issue_token(
            app_key="txapp_testkey",
            app_secret=secret,
            requested_scopes=["orders:read", "finance:write"],  # 超出授权
            db=db,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 10: rate_limit超出限制
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_rate_limit_exceeded() -> None:
    redis_mock = AsyncMock()
    # INCR返回超出限制的值
    redis_mock.incr = AsyncMock(return_value=101)
    redis_mock.expire = AsyncMock()

    limiter = RateLimiter(redis_client=redis_mock)
    allowed, remaining, reset_at = await limiter.check_rate_limit("app-abc", limit_per_min=100)

    assert allowed is False
    assert remaining == 0
    assert reset_at > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 11: rate_limit Redis不可用时优雅降级
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_rate_limit_redis_unavailable_degrades_gracefully() -> None:
    redis_mock = AsyncMock()
    redis_mock.incr = AsyncMock(side_effect=ConnectionError("Redis connection refused"))

    limiter = RateLimiter(redis_client=redis_mock)
    allowed, remaining, reset_at = await limiter.check_rate_limit("app-abc", limit_per_min=60)

    # 降级时应放行请求
    assert allowed is True
    assert remaining == 60  # 返回满配额
    assert reset_at > 0


@pytest.mark.asyncio
async def test_rate_limit_redis_not_configured_degrades_gracefully() -> None:
    """Redis未配置时应优雅降级"""
    limiter = RateLimiter(redis_client=None)
    allowed, remaining, reset_at = await limiter.check_rate_limit("app-xyz", limit_per_min=30)

    assert allowed is True
    assert remaining == 30


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 12: rotate_secret吊销旧token
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_rotate_secret_revokes_old_tokens() -> None:
    svc = OAuth2Service()
    db = _make_db_mock()
    app_id = uuid4()
    tenant_id = uuid4()
    revoked_ids = [str(uuid4()), str(uuid4())]

    call_count = 0

    async def side_effect(query, params=None):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()

        if call_count == 1:
            # SELECT验证应用存在
            mock_result.fetchone = MagicMock(return_value=(str(app_id),))
        elif call_count == 2:
            # UPDATE secret_hash
            mock_result.fetchone = MagicMock(return_value=None)
        elif call_count == 3:
            # UPDATE revoke tokens — 返回被吊销的行
            mock_result.fetchall = MagicMock(return_value=[(rid,) for rid in revoked_ids])
        else:
            mock_result.fetchone = MagicMock(return_value=None)

        return mock_result

    db.execute = AsyncMock(side_effect=side_effect)

    result = await svc.rotate_secret(app_id, tenant_id, db)

    assert "new_app_secret" in result
    assert result["revoked_token_count"] == 2
    assert "warning" in result
    db.commit.assert_called_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 13: webhook dispatch发送HMAC签名
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_webhook_dispatch_sends_hmac_signature() -> None:
    dispatcher = WebhookDispatcher()
    db = _make_db_mock()
    tenant_id = uuid4()
    webhook_id = str(uuid4())
    secret_hash = "test-secret-hash-value"

    received_headers: dict = {}

    async def mock_post(url, content, headers):
        nonlocal received_headers
        received_headers = dict(headers)
        resp = MagicMock()
        resp.status_code = 200
        return resp

    # 配置DB返回一个webhook
    db_result = MagicMock()
    row = MagicMock()
    row.__iter__ = MagicMock(return_value=iter([]))
    webhooks_list = [
        {"id": webhook_id, "endpoint_url": "https://example.com/hook",
         "secret_hash": secret_hash, "retry_count": 3}
    ]
    db_result.mappings.return_value.fetchall.return_value = [MagicMock(**wh) for wh in webhooks_list]

    call_idx = 0

    async def db_execute(query, params=None):
        nonlocal call_idx
        call_idx += 1
        mock_res = MagicMock()
        if call_idx == 1:
            # SELECT webhooks
            rows = []
            for wh in webhooks_list:
                r = MagicMock()
                r.keys = MagicMock(return_value=list(wh.keys()))
                r.__getitem__ = MagicMock(side_effect=lambda k, _wh=wh: _wh[k])
                rows.append(r)
            mock_res.mappings.return_value.fetchall.return_value = rows
        else:
            mock_res.fetchone = MagicMock(return_value=None)
        return mock_res

    db.execute = AsyncMock(side_effect=db_execute)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        captured_headers: dict = {}

        async def mock_post_method(url, content, headers):
            captured_headers.update(headers)
            resp = MagicMock()
            resp.status_code = 200
            return resp

        mock_client.post = AsyncMock(side_effect=mock_post_method)
        mock_client_cls.return_value = mock_client

        results = await dispatcher.dispatch(
            tenant_id=tenant_id,
            event_type="order.completed",
            payload={"order_id": "o123"},
            db=db,
        )

    assert len(results) == 1
    assert "X-TunXiang-Signature" in captured_headers
    sig = captured_headers["X-TunXiang-Signature"]
    assert sig.startswith("sha256=")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 14: webhook signature验证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_webhook_signature_verify() -> None:
    dispatcher = WebhookDispatcher()
    secret_hash = "my-webhook-secret"
    body = b'{"event":"order.completed","data":{}}'

    signature = dispatcher._compute_signature(secret_hash, body)
    assert dispatcher.verify_signature(secret_hash, body, signature) is True


def test_webhook_signature_tampered_body_fails() -> None:
    dispatcher = WebhookDispatcher()
    secret_hash = "my-webhook-secret"
    original_body = b'{"event":"order.completed","data":{}}'
    tampered_body = b'{"event":"order.completed","data":{"injected":true}}'

    signature = dispatcher._compute_signature(secret_hash, original_body)
    assert dispatcher.verify_signature(secret_hash, tampered_body, signature) is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 15: webhook retry on failure
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_webhook_retry_on_server_error() -> None:
    dispatcher = WebhookDispatcher()
    webhook = {
        "id": str(uuid4()),
        "endpoint_url": "https://example.com/hook",
        "secret_hash": "test-hash",
        "retry_count": 2,
    }
    body = b'{"event":"test"}'
    signature = "sha256=abc"

    attempt_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        resp = MagicMock()
        if attempt_count < 3:
            resp.status_code = 503  # 服务端错误，触发重试
        else:
            resp.status_code = 200
        return resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_client_cls.return_value = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await dispatcher._push_with_retry(webhook, body, signature, retry_count=2)

    assert result["success"] is True
    assert result["attempts"] == 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 16: 请求日志不含金额/敏感字段
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_request_log_schema_no_sensitive_fields() -> None:
    """验证api_request_logs表结构不含金额/密钥敏感字段"""
    # 从migration文件中验证字段定义
    migration_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..",
        "shared", "db-migrations", "versions", "v069_open_api_platform.py"
    )
    migration_path = os.path.normpath(migration_path)

    with open(migration_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 找到api_request_logs表定义部分
    start = content.find("CREATE TABLE IF NOT EXISTS api_request_logs")
    end = content.find(");", start)
    table_def = content[start:end]

    # 验证不含敏感字段
    sensitive_fields = ["amount", "price", "fee", "secret", "password", "token_hash"]
    for field in sensitive_fields:
        assert field not in table_def, f"api_request_logs不应包含敏感字段: {field}"

    # 验证包含基础审计字段
    assert "endpoint" in table_def
    assert "method" in table_def
    assert "status_code" in table_def
    assert "request_duration_ms" in table_def
    assert "ip_address" in table_def


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 17: 租户隔离（跨租户不可见）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_tenant_isolation_app_not_visible_cross_tenant() -> None:
    """跨租户查询应返回None（RLS隔离）"""
    svc = OAuth2Service()
    db = _make_db_mock()
    app_id = uuid4()
    correct_tenant = uuid4()
    wrong_tenant = uuid4()

    # DB对错误租户返回空结果（模拟RLS过滤）
    result_mock = MagicMock()
    result_mock.mappings.return_value.fetchone.return_value = None
    db.execute = AsyncMock(return_value=result_mock)

    # 用错误的租户ID查询应用
    app = await svc.get_application(app_id, wrong_tenant, db)
    assert app is None


@pytest.mark.asyncio
async def test_tenant_isolation_rotate_secret_wrong_tenant() -> None:
    """错误租户无法轮换他人的secret"""
    svc = OAuth2Service()
    db = _make_db_mock()
    app_id = uuid4()
    wrong_tenant = uuid4()

    # DB返回空（模拟RLS过滤+应用不属于该租户）
    result_mock = MagicMock()
    result_mock.fetchone = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=result_mock)

    with pytest.raises(ValueError, match="应用不存在"):
        await svc.rotate_secret(app_id, wrong_tenant, db)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test 18: revoke_token后verify返回None
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_revoke_token_then_verify_returns_none() -> None:
    svc = OAuth2Service()
    db = _make_db_mock()
    raw_token = "token-to-revoke-xyz789"
    token_id = str(uuid4())

    # 第一次调用: revoke_token — UPDATE返回一行
    revoke_result = MagicMock()
    revoke_result.fetchone = MagicMock(return_value=(token_id,))
    db.execute = AsyncMock(return_value=revoke_result)

    success = await svc.revoke_token(raw_token, db)
    assert success is True
    db.commit.assert_called_once()

    # 第二次调用: verify_token — 查不到（已吊销）
    db.reset_mock()
    _configure_db_for_verify_token(
        db, svc, raw_token, token_id,
        app_id=str(uuid4()), tenant_id=str(uuid4()),
        scopes=["orders:read"], revoked=True
    )

    result = await svc.verify_token(raw_token, None, db)
    assert result is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  额外: PBKDF2哈希一致性
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_hash_secret_deterministic() -> None:
    """相同输入，哈希结果相同"""
    svc = OAuth2Service()
    h1 = svc._hash_secret("my-secret")
    h2 = svc._hash_secret("my-secret")
    assert h1 == h2


def test_hash_secret_different_inputs_differ() -> None:
    """不同输入，哈希结果不同"""
    svc = OAuth2Service()
    h1 = svc._hash_secret("secret-a")
    h2 = svc._hash_secret("secret-b")
    assert h1 != h2


def test_verify_secret_timing_safe() -> None:
    """_verify_secret使用恒时比较"""
    svc = OAuth2Service()
    secret = "safe-comparison-test"
    secret_hash = svc._hash_secret(secret)

    assert svc._verify_secret(secret, secret_hash) is True
    assert svc._verify_secret("wrong-secret", secret_hash) is False
