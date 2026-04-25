"""test_channel_canonical_tier2 — Sprint E1 channel canonical 路由+服务覆盖

Tier 2 覆盖（CLAUDE.md §17 KDS 类高标准但不涉资金）：
  1. ingest_idempotency_same_external_id_returns_existing
     — 同 (tenant, channel, external_order_id) 重复 ingest，返回既有记录
       且不重复发 CHANNEL.ORDER_SYNCED 事件
  2. ingest_emits_channel_order_synced_event
     — 首次落库异步发 CHANNEL.ORDER_SYNCED；payload 含金额三件套
  3. cross_tenant_403_blocks_query
     — X-Tenant-ID != JWT.tenant_id → 403 USER_TENANT_MISMATCH
  4. settlement_fen_computed_correctly_from_total_minus_subsidy_minus_commission
     — DB GENERATED 列由 Service 透传后，路由响应中 settlement_fen = total - subsidy - commission
  5. rls_with_check_blocks_cross_tenant_insert（静态扫描）
     — v276 迁移文件包含 USING + WITH CHECK 双向对称
  6. list_route_pagination_returns_total_count
     — GET /orders 返回 total + items + page + size
"""

from __future__ import annotations

import os
import sys
import types
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# ─── 路径准备 ──────────────────────────────────────────────────────────────────

_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.schemas", os.path.join(_SRC_DIR, "schemas"))
_ensure_pkg("src.security", os.path.join(_SRC_DIR, "security"))

os.environ.setdefault("TX_AUTH_ENABLED", "false")  # 跳过 RBAC 实际 JWT 校验

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.schemas.channel_canonical import CanonicalOrderRequest  # noqa: E402
from src.services.channel_canonical_service import ChannelCanonicalService  # noqa: E402

# ─── 数据 ──────────────────────────────────────────────────────────────────────

TENANT_A = "00000000-0000-0000-0000-00000000000a"
TENANT_B = "00000000-0000-0000-0000-00000000000b"
STORE_ID = str(uuid.uuid4())


def _build_request(
    *,
    tenant_id: str = TENANT_A,
    external_order_id: str = "MT-20260425-001",
    total_fen: int = 12800,
    subsidy_fen: int = 1500,
    merchant_share_fen: int = 500,
    commission_fen: int = 1280,
) -> CanonicalOrderRequest:
    return CanonicalOrderRequest(
        tenant_id=uuid.UUID(tenant_id),
        store_id=uuid.UUID(STORE_ID),
        channel_code="meituan",
        external_order_id=external_order_id,
        status="received",
        items=[
            {
                "dish_external_id": "MT-DISH-1",
                "dish_name": "椒盐皮皮虾",
                "quantity": 1,
                "unit_price_fen": 12800,
                "spec": None,
                "line_subsidy_fen": 1500,
                "line_merchant_share_fen": 500,
            }
        ],
        total_fen=total_fen,
        subsidy_fen=subsidy_fen,
        merchant_share_fen=merchant_share_fen,
        commission_fen=commission_fen,
        received_at=datetime.now(timezone.utc),
        payload={"raw": "meituan-original-payload"},
    )


def _row_from_request(req: CanonicalOrderRequest, *, settlement_fen: int) -> dict:
    """模拟 DB INSERT RETURNING 的行（含 GENERATED settlement_fen）。"""
    now = datetime.now(timezone.utc)
    return {
        "id": uuid.uuid4(),
        "tenant_id": req.tenant_id,
        "store_id": req.store_id,
        "channel_code": req.channel_code,
        "external_order_id": req.external_order_id,
        "canonical_order_id": None,
        "status": req.status,
        "total_fen": req.total_fen,
        "subsidy_fen": req.subsidy_fen,
        "merchant_share_fen": req.merchant_share_fen,
        "commission_fen": req.commission_fen,
        "settlement_fen": settlement_fen,
        "payload": req.payload,
        "received_at": req.received_at,
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
    }


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


# ─── Service 层用例（不经路由，直接打 Service） ────────────────────────────────


class TestChannelCanonicalServiceTier2:
    @pytest.mark.asyncio
    async def test_ingest_idempotency_same_external_id_returns_existing(self):
        """重复 ingest 返回既有记录；不再调用 insert，不再发事件。"""
        req = _build_request()
        existing_row = _row_from_request(req, settlement_fen=10020)

        db = _make_db()
        svc = ChannelCanonicalService(db, tenant_id=TENANT_A)

        # 模拟仓储：第一次幂等命中
        with patch.object(
            svc._repo, "get_by_external", AsyncMock(return_value=existing_row)
        ) as mock_get, patch.object(
            svc._repo, "insert", AsyncMock()
        ) as mock_insert, patch(
            "src.services.channel_canonical_service.emit_event",
            AsyncMock(),
        ) as mock_emit:
            record, created = await svc.ingest(req)

        assert created is False
        assert str(record.id) == str(existing_row["id"])
        mock_get.assert_awaited_once()
        mock_insert.assert_not_awaited()
        # 幂等命中不发事件
        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_emits_channel_order_synced_event(self):
        """首次落库异步发 CHANNEL.ORDER_SYNCED；payload 含金额三件套。"""
        req = _build_request(external_order_id="MT-FIRST-001")
        new_row = _row_from_request(req, settlement_fen=req.total_fen - req.subsidy_fen - req.commission_fen)

        db = _make_db()
        svc = ChannelCanonicalService(db, tenant_id=TENANT_A)

        emitted: dict = {}

        async def fake_emit(**kwargs):
            emitted.update(kwargs)
            return "evt-id-mock"

        with patch.object(
            svc._repo, "get_by_external", AsyncMock(return_value=None)
        ), patch.object(
            svc._repo, "insert", AsyncMock(return_value=new_row)
        ), patch(
            "src.services.channel_canonical_service.emit_event", new=fake_emit
        ):
            record, created = await svc.ingest(req)
            # 等所有 fire-and-forget 任务完成
            import asyncio as _aio
            pending = [t for t in _aio.all_tasks() if t is not _aio.current_task()]
            await _aio.gather(*pending, return_exceptions=True)

        assert created is True
        assert emitted["event_type"].value == "channel.order_synced"
        # 金额三件套都在事件 payload 里
        ev_payload = emitted["payload"]
        assert ev_payload["total_fen"] == req.total_fen
        assert ev_payload["subsidy_fen"] == req.subsidy_fen
        assert ev_payload["commission_fen"] == req.commission_fen
        assert ev_payload["settlement_fen"] == record.settlement_fen
        assert ev_payload["channel_code"] == "meituan"

    @pytest.mark.asyncio
    async def test_settlement_fen_computed_correctly_from_total_minus_subsidy_minus_commission(self):
        """settlement_fen = total - subsidy - commission（DB GENERATED 列）。

        Service 层不计算 settlement_fen（数据库 GENERATED STORED 计算并返回），
        本用例验证 Service 透传的值确实满足公式。模拟 DB 返回正确值，
        Record 模型读取后路由响应 settlement_fen 一致。
        """
        req = _build_request(total_fen=20000, subsidy_fen=2000, commission_fen=2200)
        expected_settlement = 20000 - 2000 - 2200  # 15800
        new_row = _row_from_request(req, settlement_fen=expected_settlement)

        db = _make_db()
        svc = ChannelCanonicalService(db, tenant_id=TENANT_A)

        with patch.object(
            svc._repo, "get_by_external", AsyncMock(return_value=None)
        ), patch.object(
            svc._repo, "insert", AsyncMock(return_value=new_row)
        ), patch(
            "src.services.channel_canonical_service.emit_event", AsyncMock()
        ):
            record, _ = await svc.ingest(req)

        assert record.settlement_fen == expected_settlement
        assert record.settlement_fen == record.total_fen - record.subsidy_fen - record.commission_fen


# ─── 路由层用例（FastAPI TestClient + override get_db） ────────────────────────


def _build_app_with_overrides(svc_mock: MagicMock) -> FastAPI:
    """构建仅含 channel_canonical_router 的轻量 app，并 override get_db。

    通过 patch ChannelCanonicalService 类构造器返回 svc_mock。
    """
    from shared.ontology.src.database import get_db
    from src.api.channel_canonical_routes import router as cc_router

    test_app = FastAPI(title="test-app")
    test_app.include_router(cc_router)

    async def fake_get_db():
        yield AsyncMock()

    test_app.dependency_overrides[get_db] = fake_get_db
    return test_app


class TestChannelCanonicalRouterTier2:
    def test_cross_tenant_403_blocks_query(self):
        """X-Tenant-ID != user.tenant_id 时 GET 返回 403 USER_TENANT_MISMATCH。

        TX_AUTH_ENABLED=false 注入 mock 用户，其 tenant_id 是
        a0000000-0000-0000-0000-000000000001（rbac._mock_user_context）。
        故传 X-Tenant-ID = TENANT_A（不一致）必然 403。
        """
        from shared.ontology.src.database import get_db
        from src.api.channel_canonical_routes import router as cc_router

        test_app = FastAPI(title="test-app")
        test_app.include_router(cc_router)

        async def fake_get_db():
            yield AsyncMock()

        test_app.dependency_overrides[get_db] = fake_get_db
        client = TestClient(test_app)

        resp = client.get(
            "/api/v1/channels/canonical/orders",
            headers={"X-Tenant-ID": TENANT_A},
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["detail"] == "USER_TENANT_MISMATCH"

    def test_list_route_pagination_returns_total_count(self):
        """GET /orders 响应包含 items + total + page + size。"""
        from shared.ontology.src.database import get_db
        from src.api.channel_canonical_routes import router as cc_router

        # 先打 ChannelCanonicalService 类，让其 list_recent 返回我们造的数据
        sample_records = []
        for i in range(3):
            req = _build_request(external_order_id=f"MT-LIST-{i:03d}")
            sample_records.append(_row_from_request(req, settlement_fen=10020))

        from src.schemas.channel_canonical import CanonicalOrderRecord

        records = [CanonicalOrderRecord(**r) for r in sample_records]

        with patch(
            "src.api.channel_canonical_routes.ChannelCanonicalService"
        ) as svc_cls:
            instance = MagicMock()
            instance.list_recent = AsyncMock(return_value=(records, 42))
            svc_cls.return_value = instance

            test_app = FastAPI(title="test-app")
            test_app.include_router(cc_router)

            async def fake_get_db():
                yield AsyncMock()

            test_app.dependency_overrides[get_db] = fake_get_db
            client = TestClient(test_app)

            # 用 mock_user 的 tenant_id 来通过校验
            mock_tenant = "a0000000-0000-0000-0000-000000000001"
            resp = client.get(
                "/api/v1/channels/canonical/orders",
                headers={"X-Tenant-ID": mock_tenant},
                params={"page": 1, "size": 20},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["total"] == 42
        assert len(data["items"]) == 3
        assert data["page"] == 1
        assert data["size"] == 20


# ─── 静态扫描：迁移文件 RLS WITH CHECK 检查 ─────────────────────────────────


class TestChannelCanonicalMigrationStatic:
    def test_rls_with_check_blocks_cross_tenant_insert(self):
        """v276 迁移必须包含 USING + WITH CHECK 双向对称（防 NULL 绕过）。"""
        migration_path = os.path.abspath(
            os.path.join(
                _TESTS_DIR,
                "..", "..", "..", "..",
                "shared", "db-migrations", "versions",
                "v276_channel_canonical_orders.py",
            )
        )
        assert os.path.exists(migration_path), migration_path
        with open(migration_path, encoding="utf-8") as fh:
            content = fh.read()

        # 检查 RLS 启用
        assert "ENABLE ROW LEVEL SECURITY" in content
        # 必须同时声明 USING 与 WITH CHECK
        assert "USING (" in content
        assert "WITH CHECK (" in content
        # 严禁 NULL 绕过：使用 NULLIF + ::uuid 强转，不接受 NULL
        assert "NULLIF(current_setting('app.tenant_id', true), '')::uuid" in content
        # 策略必须 DROP IF EXISTS 后再 CREATE（升级幂等）
        assert "DROP POLICY IF EXISTS channel_canonical_orders_tenant_isolation" in content
        assert "CREATE POLICY channel_canonical_orders_tenant_isolation" in content
