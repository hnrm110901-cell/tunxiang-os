"""Tier 1 邻接测试：cert CRUD endpoint + service 校验（PR-01C / PRD-01 食安合规）

为什么 *tier1* 后缀（触发 tier1-gate）:
  - 证件 CRUD 是 PRD-01 食安合规硬约束的 backbone。
    创建错证 / 漏删过期证 / 软删失败都会让 is_supplier_blocked 误判，
    直接威胁"过期证件不可收货"硬约束（CLAUDE.md §6 三条硬约束之一）。
  - 不依赖真 PG，全 mock + monkeypatch service helper（与 PR #608 sub-PR C /
    PR #602 minimal-app endpoint-level test 模式一致）。

测试范围:
  1-6. 4 endpoint 行为契约（status filter / 404 / 422 / 分页透传）
  7-8. service helper 单元层（list SQL / create warning_days 校验）

反模式禁止（feedback_pytest_stub_setdefault_pitfall.md）:
  - 禁用 sys.modules.setdefault("shared", ...) 注入 — 会污染同目录其他测试
  - monkeypatch 替换 cert_service 函数；用 dependency_overrides[_get_db] 跳真 DB
"""

from __future__ import annotations

import sys
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

# 本机 Python 3.9 跳过 — shared.ontology 用 PEP 604 `X | None` 需 3.10+.
# CI Python 3.11 真跑. 与 test_auto_deduction_row_lock_tier1.py 同模式
# 避开 PR #547 round-1 stub 污染陷阱 (feedback_pytest_stub_setdefault_pitfall.md).
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.ontology PEP 604 union)；CI Python 3.11 跑通",
        allow_module_level=True,
    )

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from services.tx_supply.src.api.cert_routes import router as cert_router  # noqa: E402
from services.tx_supply.src.services import cert_service  # noqa: E402
from shared.ontology.src.database import get_db  # noqa: E402

# ── 常量 ───────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
SUPPLIER_ID = str(uuid.uuid4())
CERT_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ── DB Mock + dependency override ──────────────────────────────────────────────


def _mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _override_get_db(mock_db=None):
    if mock_db is None:
        mock_db = _mock_db()

    async def _dep():
        yield mock_db

    return _dep


# ── App fixture ────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    """构造 minimal FastAPI app 只挂 cert_router.

    避免 main.py 拖全 tx-supply 依赖；与 doc_number_admin tests 同模式。
    """
    app = FastAPI()
    app.include_router(cert_router)
    app.dependency_overrides[get_db] = _override_get_db()
    yield TestClient(app)
    app.dependency_overrides.clear()


# ══════════════════════════════════════════════════════════════════════════════
#  1. GET /suppliers/{supplier_id}/certificates — 列表 + status 过滤
# ══════════════════════════════════════════════════════════════════════════════


def test_list_supplier_certificates_returns_filtered_by_status(client):
    """list endpoint 透传 status=expiring_30d，返回 items 结构正确."""
    mock_items = [
        {
            "id": CERT_ID,
            "supplier_id": SUPPLIER_ID,
            "supplier_name": "屯象食品有限公司",
            "cert_type": "food_permit",
            "cert_number": "FP-2026-001",
            "expire_date": date.today() + timedelta(days=15),
            "auto_block_on_expire": True,
        }
    ]
    with patch(
        "services.tx_supply.src.api.cert_routes.list_certificates",
        new=AsyncMock(return_value=mock_items),
    ) as m:
        resp = client.get(
            f"/api/v1/supply/suppliers/{SUPPLIER_ID}/certificates?status=expiring_30d",
            headers=HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["items"]) == 1
    assert body["data"]["items"][0]["cert_number"] == "FP-2026-001"
    # 验证透传：status 参数 + supplier_id
    _, kwargs = m.call_args
    assert kwargs["status"] == "expiring_30d"
    assert kwargs["supplier_id"] == SUPPLIER_ID
    assert kwargs["tenant_id"] == TENANT_ID


def test_list_certificates_pagination_params_passthrough(client):
    """page=2&size=50 透传到 service 为 limit=50/offset=50."""
    with patch(
        "services.tx_supply.src.api.cert_routes.list_certificates",
        new=AsyncMock(return_value=[]),
    ) as m:
        resp = client.get(
            f"/api/v1/supply/suppliers/{SUPPLIER_ID}/certificates?page=2&size=50",
            headers=HEADERS,
        )
    assert resp.status_code == 200
    _, kwargs = m.call_args
    assert kwargs["limit"] == 50
    assert kwargs["offset"] == 50


# ══════════════════════════════════════════════════════════════════════════════
#  2. GET /certificates/{cert_id} — 单条
# ══════════════════════════════════════════════════════════════════════════════


def test_get_certificate_returns_404_when_not_found(client):
    """get_certificate_by_id 返 None → 404 + code=CERT_NOT_FOUND."""
    with patch(
        "services.tx_supply.src.api.cert_routes.get_certificate_by_id",
        new=AsyncMock(return_value=None),
    ):
        resp = client.get(
            f"/api/v1/supply/certificates/{CERT_ID}",
            headers=HEADERS,
        )
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"]["code"] == "CERT_NOT_FOUND"


def test_get_certificate_returns_data_when_found(client):
    """get_certificate_by_id 返 dict → 200 + data."""
    mock_item = {
        "id": CERT_ID,
        "supplier_id": SUPPLIER_ID,
        "supplier_name": "屯象食品",
        "cert_type": "business_license",
        "cert_number": "BL-001",
        "expire_date": date.today() + timedelta(days=180),
    }
    with patch(
        "services.tx_supply.src.api.cert_routes.get_certificate_by_id",
        new=AsyncMock(return_value=mock_item),
    ):
        resp = client.get(
            f"/api/v1/supply/certificates/{CERT_ID}",
            headers=HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["cert_number"] == "BL-001"


# ══════════════════════════════════════════════════════════════════════════════
#  3. POST /suppliers/{supplier_id}/certificates — 创建
# ══════════════════════════════════════════════════════════════════════════════


def test_create_supplier_certificate_validates_required_fields(client):
    """缺 cert_type / cert_number / expire_date 各返 422."""
    # 缺 cert_type
    resp = client.post(
        f"/api/v1/supply/suppliers/{SUPPLIER_ID}/certificates",
        headers=HEADERS,
        json={"cert_number": "X", "expire_date": "2027-01-01"},
    )
    assert resp.status_code == 422

    # 缺 cert_number
    resp = client.post(
        f"/api/v1/supply/suppliers/{SUPPLIER_ID}/certificates",
        headers=HEADERS,
        json={"cert_type": "food_permit", "expire_date": "2027-01-01"},
    )
    assert resp.status_code == 422

    # 缺 expire_date
    resp = client.post(
        f"/api/v1/supply/suppliers/{SUPPLIER_ID}/certificates",
        headers=HEADERS,
        json={"cert_type": "food_permit", "cert_number": "X"},
    )
    assert resp.status_code == 422


def test_create_supplier_certificate_success(client):
    """完整 body → 200 + 透传 service."""
    mock_created = {
        "id": CERT_ID,
        "supplier_id": SUPPLIER_ID,
        "cert_type": "food_permit",
        "cert_number": "FP-NEW-001",
        "expire_date": date(2027, 6, 30),
        "auto_block_on_expire": True,
    }
    with patch(
        "services.tx_supply.src.api.cert_routes.create_certificate",
        new=AsyncMock(return_value=mock_created),
    ) as m:
        resp = client.post(
            f"/api/v1/supply/suppliers/{SUPPLIER_ID}/certificates",
            headers=HEADERS,
            json={
                "cert_type": "food_permit",
                "cert_number": "FP-NEW-001",
                "expire_date": "2027-06-30",
                "issuer": "长沙市市场监督管理局",
                "warning_days": [30, 15, 7],
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["cert_number"] == "FP-NEW-001"
    _, kwargs = m.call_args
    assert kwargs["supplier_id"] == SUPPLIER_ID
    assert kwargs["cert_type"] == "food_permit"
    assert kwargs["warning_days"] == [30, 15, 7]


def test_create_supplier_certificate_propagates_value_error_as_422(client):
    """service raise ValueError → 422 + code=CERT_VALIDATION."""
    with patch(
        "services.tx_supply.src.api.cert_routes.create_certificate",
        new=AsyncMock(side_effect=ValueError("warning_days 必须 1..365")),
    ):
        resp = client.post(
            f"/api/v1/supply/suppliers/{SUPPLIER_ID}/certificates",
            headers=HEADERS,
            json={
                "cert_type": "food_permit",
                "cert_number": "FP-001",
                "expire_date": "2027-01-01",
                "warning_days": [400],
            },
        )
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"]["code"] == "CERT_VALIDATION"
    assert "warning_days" in body["detail"]["message"]


# ══════════════════════════════════════════════════════════════════════════════
#  4. DELETE /certificates/{cert_id} — 软删
# ══════════════════════════════════════════════════════════════════════════════


def test_delete_certificate_success(client):
    """soft_delete_certificate 返 True → 200 + cert_id."""
    with patch(
        "services.tx_supply.src.api.cert_routes.soft_delete_certificate",
        new=AsyncMock(return_value=True),
    ):
        resp = client.delete(
            f"/api/v1/supply/certificates/{CERT_ID}",
            headers=HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["is_deleted"] is True
    assert body["data"]["cert_id"] == CERT_ID


def test_delete_certificate_returns_404_when_already_deleted(client):
    """soft_delete_certificate 返 False（不存在 / 已删 / 跨租户）→ 404."""
    with patch(
        "services.tx_supply.src.api.cert_routes.soft_delete_certificate",
        new=AsyncMock(return_value=False),
    ):
        resp = client.delete(
            f"/api/v1/supply/certificates/{CERT_ID}",
            headers=HEADERS,
        )
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"]["code"] == "CERT_NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════════════
#  5. service-level：list SQL 形态 + create warning_days 校验
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_certificates_sql_contains_left_join_and_order():
    """list_certificates SQL 含 LEFT JOIN supplier_accounts + ORDER BY expire_date ASC."""
    captured = []

    async def fake_execute(stmt, params=None):
        captured.append(str(stmt))
        result = AsyncMock()
        result.mappings = lambda: _MappingsAll([])
        return result

    db = AsyncMock()
    db.execute = fake_execute

    rows = await cert_service.list_certificates(
        db=db,
        tenant_id=TENANT_ID,
        supplier_id=SUPPLIER_ID,
        status="all",
    )
    assert rows == []
    # captured[0] 是 _set_tenant 的 SELECT set_config，跳过
    # 后续应有一条主查询含 LEFT JOIN + ORDER BY expire_date
    sql_blob = "\n".join(captured).upper()
    assert "LEFT JOIN SUPPLIER_ACCOUNTS" in sql_blob
    assert "ORDER BY" in sql_blob and "EXPIRE_DATE" in sql_blob


@pytest.mark.asyncio
async def test_create_certificate_rejects_invalid_warning_days():
    """warning_days 非法值 raise ValueError；合法值放行（实际不连 DB，但校验先于 _set_tenant）."""
    db = AsyncMock()

    # 400 > 365
    with pytest.raises(ValueError, match="warning_days"):
        await cert_service.create_certificate(
            db=db,
            tenant_id=TENANT_ID,
            supplier_id=SUPPLIER_ID,
            cert_type="food_permit",
            cert_number="X",
            expire_date=date(2027, 1, 1),
            warning_days=[400],
        )

    # 0 < 1
    with pytest.raises(ValueError, match="warning_days"):
        await cert_service.create_certificate(
            db=db,
            tenant_id=TENANT_ID,
            supplier_id=SUPPLIER_ID,
            cert_type="food_permit",
            cert_number="X",
            expire_date=date(2027, 1, 1),
            warning_days=[0],
        )

    # 类型错（非 int）
    with pytest.raises(ValueError, match="warning_days"):
        await cert_service.create_certificate(
            db=db,
            tenant_id=TENANT_ID,
            supplier_id=SUPPLIER_ID,
            cert_type="food_permit",
            cert_number="X",
            expire_date=date(2027, 1, 1),
            warning_days=["30"],  # type: ignore[list-item]
        )


# ── 辅助：模拟 SQLAlchemy MappingResult.all() ─────────────────────────────────


class _MappingsAll:
    """模拟 result.mappings() 返回对象."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)
