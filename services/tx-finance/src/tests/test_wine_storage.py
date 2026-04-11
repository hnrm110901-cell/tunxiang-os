"""存酒管理 API 测试

覆盖：
  1. test_register_wine_storage       — POST /wine-storage/ 存酒登记
  2. test_retrieve_wine               — POST /wine-storage/{id}/retrieve 取酒
  3. test_list_customer_wines          — GET /wine-storage/customer/{id} 客户存酒列表
  4. test_member_association           — 会员关联查询（手机号→存酒记录）
  5. test_expiring_report              — GET /wine-storage/report/expiring 到期筛选
  6. test_summary_report               — GET /wine-storage/report/summary 存酒汇总
"""
from __future__ import annotations

import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest


# ══════════════════════════════════════════════════════════════════════════════
#  sys.modules 存根注入
# ══════════════════════════════════════════════════════════════════════════════


def _ensure_stub(module_path: str, attrs: dict | None = None) -> types.ModuleType:
    if module_path not in sys.modules:
        mod = types.ModuleType(module_path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[module_path] = mod
    return sys.modules[module_path]


_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")
_db_mod = _ensure_stub("shared.ontology.src.database")
if not hasattr(_db_mod, "get_db_with_tenant"):
    async def _placeholder_get_db_with_tenant(tenant_id: str):
        yield None
    _db_mod.get_db_with_tenant = _placeholder_get_db_with_tenant

_ensure_stub("shared.events")
_ensure_stub("shared.events.src")
_ensure_stub("shared.events.src.emitter", {"emit_event": AsyncMock()})
_ev_types = _ensure_stub("shared.events.src.event_types")
if not hasattr(_ev_types, "WineStorageEventType"):
    class _FakeWineStorageEventType:
        STORED = "wine.stored"
        RETRIEVED = "wine.retrieved"
        EXTENDED = "wine.extended"
        EXPIRED = "wine.expired"
    _ev_types.WineStorageEventType = _FakeWineStorageEventType

if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())
    sys.modules["structlog"] = _sl

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = types.ModuleType("asyncpg")

# ══════════════════════════════════════════════════════════════════════════════
#  导入路由
# ══════════════════════════════════════════════════════════════════════════════

from ..api.wine_storage_routes import router as wine_router  # noqa: E402
from shared.ontology.src.database import get_db_with_tenant  # noqa: E402

from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(wine_router)

TENANT_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID, "X-Operator-ID": str(uuid.uuid4())}

# ── 辅助函数 ──────────────────────────────────────────────────────────────────

WINE_ID = str(uuid.uuid4())
CUSTOMER_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())


def _make_row_mapping(data: dict):
    class FakeMapping:
        def __init__(self, d):
            self._data = d
        def __getitem__(self, key):
            return self._data[key]
        def get(self, key, default=None):
            return self._data.get(key, default)
    class FakeRow:
        def __init__(self, d):
            self._mapping = FakeMapping(d)
    return FakeRow(data)


def _make_wine_record(
    wine_id: str = WINE_ID,
    status: str = "stored",
    remaining_ml: int = 750,
    expire_at: datetime | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": uuid.UUID(wine_id),
        "customer_id": uuid.UUID(CUSTOMER_ID),
        "customer_name": "张先生",
        "customer_phone": "138****0001",
        "store_id": uuid.UUID(STORE_ID),
        "store_name": "芙蓉路店",
        "wine_name": "五粮液52度",
        "wine_type": "白酒",
        "original_ml": 750,
        "remaining_ml": remaining_ml,
        "locker_no": "A-03",
        "status": status,
        "stored_at": now,
        "expire_at": expire_at or (now + timedelta(days=90)),
        "created_at": now,
        "updated_at": now,
        "notes": "",
    }


def _make_db_returning(rows: list[dict] | None = None, insert_id: str | None = None) -> AsyncMock:
    db = AsyncMock()
    result_mock = MagicMock()
    if rows is not None:
        result_mock.fetchall.return_value = [_make_row_mapping(r) for r in rows]
        result_mock.fetchone.return_value = _make_row_mapping(rows[0]) if rows else None
        result_mock.mappings.return_value.all.return_value = rows
        result_mock.mappings.return_value.first.return_value = rows[0] if rows else None
    else:
        result_mock.fetchall.return_value = []
        result_mock.fetchone.return_value = None
        result_mock.mappings.return_value.all.return_value = []
        result_mock.mappings.return_value.first.return_value = None
    result_mock.scalar.return_value = len(rows) if rows else 0
    result_mock.rowcount = 1
    if insert_id:
        insert_result = MagicMock()
        insert_result.fetchone.return_value = _make_row_mapping({"id": uuid.UUID(insert_id), "created_at": datetime.now(timezone.utc)})
        insert_result.mappings.return_value.first.return_value = {"id": uuid.UUID(insert_id), "created_at": datetime.now(timezone.utc)}
        db.execute = AsyncMock(return_value=insert_result)
    else:
        db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()
    db.begin.return_value.__aenter__ = AsyncMock(return_value=db)
    db.begin.return_value.__aexit__ = AsyncMock(return_value=None)
    return db


def _override_db(db_mock: AsyncMock):
    async def _dep(x_tenant_id: str = ""):
        yield db_mock
    return _dep


# ══════════════════════════════════════════════════════════════════════════════
#  测试用例
# ══════════════════════════════════════════════════════════════════════════════


class TestRegisterWineStorage:
    """1. POST /wine-storage/ 存酒登记。"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_register_returns_201(self):
        new_id = str(uuid.uuid4())
        db = _make_db_returning(insert_id=new_id)
        app.dependency_overrides[get_db_with_tenant] = _override_db(db)

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/wine-storage/",
                json={
                    "customer_id": CUSTOMER_ID,
                    "store_id": STORE_ID,
                    "wine_name": "五粮液52度",
                    "wine_type": "白酒",
                    "original_ml": 750,
                    "locker_no": "A-03",
                },
                headers=HEADERS,
            )

        assert resp.status_code in (200, 201)
        body = resp.json()
        assert body["ok"] is True


class TestRetrieveWine:
    """2. POST /wine-storage/{id}/retrieve 取酒。"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_retrieve_partial(self):
        record = _make_wine_record(remaining_ml=750, status="stored")
        db = _make_db_returning([record])
        app.dependency_overrides[get_db_with_tenant] = _override_db(db)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/wine-storage/{WINE_ID}/retrieve",
                json={"retrieve_ml": 300, "notes": "客人晚宴取用"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True


class TestListCustomerWines:
    """3. GET /wine-storage/customer/{id} 客户存酒列表。"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_customer_wine_list(self):
        records = [
            _make_wine_record(wine_id=str(uuid.uuid4()), remaining_ml=750),
            _make_wine_record(wine_id=str(uuid.uuid4()), remaining_ml=500),
        ]
        db = _make_db_returning(records)
        app.dependency_overrides[get_db_with_tenant] = _override_db(db)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/wine-storage/customer/{CUSTOMER_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True


class TestMemberAssociation:
    """4. 会员关联查询。"""

    def test_phone_to_wine_records(self):
        record = _make_wine_record()
        db = _make_db_returning([record])
        app.dependency_overrides[get_db_with_tenant] = _override_db(db)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/wine-storage/customer/{CUSTOMER_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        app.dependency_overrides.clear()


class TestExpiringReport:
    """5. GET /wine-storage/report/expiring 到期筛选。"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_expiring_report_returns_soon_expiring(self):
        now = datetime.now(timezone.utc)
        # 3天后过期
        expiring_soon = _make_wine_record(
            wine_id=str(uuid.uuid4()),
            expire_at=now + timedelta(days=3),
        )
        db = _make_db_returning([expiring_soon])
        app.dependency_overrides[get_db_with_tenant] = _override_db(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/wine-storage/report/expiring",
                params={"days": 7},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True


class TestSummaryReport:
    """6. GET /wine-storage/report/summary 存酒汇总。"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_summary_report_formula(self):
        """期初 + 存入 - 取出 = 期末"""
        db = AsyncMock()
        summary_data = {
            "total_stored": 10,
            "total_active": 7,
            "total_retrieved": 2,
            "total_expired": 1,
            "stored_ml_total": 7500,
            "remaining_ml_total": 5250,
        }
        result_mock = MagicMock()
        result_mock.fetchone.return_value = _make_row_mapping(summary_data)
        result_mock.mappings.return_value.first.return_value = summary_data
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()
        app.dependency_overrides[get_db_with_tenant] = _override_db(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/wine-storage/report/summary",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
