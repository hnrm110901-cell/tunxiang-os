"""PRD-09 分解型 BOM — Tier 1 邻接测试

场景：海鲜 10kg 整鱼分切 / 干货整箱拆零 / cashier consume 兼容 / 边界校验 / RLS 隔离

覆盖端点（bom_routes.py — 5 个分解型端点）：
  POST /api/v1/supply/boms/disassembly               — create_disassembly_bom
  GET  /api/v1/supply/boms/disassembly               — list_disassembly_boms
  GET  /api/v1/supply/boms/disassembly/{bom_id}      — get_disassembly_bom
  POST /api/v1/supply/boms/disassembly/{bom_id}/calculate — calculate_disassembly
  PUT  /api/v1/supply/boms/disassembly/{bom_id}      — update_disassembly_bom

覆盖 service（disassembly_service.py）：
  disassemble_ingredient()  — 纯计算，dry-run

测试用例：6 个
"""

from __future__ import annotations

import sys
import types
import uuid

# ─── Stub: shared.ontology.src.database ───────────────────────────────────────
_shared = types.ModuleType("shared")
_shared_ont = types.ModuleType("shared.ontology")
_shared_ont_src = types.ModuleType("shared.ontology.src")
_shared_db = types.ModuleType("shared.ontology.src.database")


async def _placeholder_get_db():
    yield None


_shared_db.get_db = _placeholder_get_db
sys.modules.setdefault("shared", _shared)
sys.modules.setdefault("shared.ontology", _shared_ont)
sys.modules.setdefault("shared.ontology.src", _shared_ont_src)
sys.modules.setdefault("shared.ontology.src.database", _shared_db)

# ─── Stub: shared.security.src.error_handler ──────────────────────────────────
_shared_sec = types.ModuleType("shared.security")
_shared_sec_src = types.ModuleType("shared.security.src")
_shared_sec_eh = types.ModuleType("shared.security.src.error_handler")


def _safe_http(status: int, msg: str, exc: Exception):
    from fastapi import HTTPException

    return HTTPException(status_code=status, detail=f"{msg}: {exc}")


_shared_sec_eh.safe_http_exception = _safe_http
sys.modules.setdefault("shared.security", _shared_sec)
sys.modules.setdefault("shared.security.src", _shared_sec_src)
sys.modules.setdefault("shared.security.src.error_handler", _shared_sec_eh)

# ─── Stub: structlog ──────────────────────────────────────────────────────────
_structlog = types.ModuleType("structlog")
_structlog.get_logger = lambda *a, **kw: types.SimpleNamespace(
    info=lambda *a, **kw: None,
    error=lambda *a, **kw: None,
    warning=lambda *a, **kw: None,
)
sys.modules.setdefault("structlog", _structlog)

import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from services.tx_supply.src.api.bom_routes import get_db, router

TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
BOM_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
HEADERS_A = {"X-Tenant-ID": TENANT_A}
HEADERS_B = {"X-Tenant-ID": TENANT_B}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_app(db_mock):
    app = FastAPI()
    app.include_router(router)

    async def _override():
        yield db_mock

    app.dependency_overrides[get_db] = _override
    return app


def _client(db_mock):
    return TestClient(_make_app(db_mock))


def _mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _scalar_result(value):
    r = MagicMock()
    r.scalar.return_value = value
    return r


class _DictRow(dict):
    """Dict-like row that also supports attribute access and dict() conversion.
    Mimics SQLAlchemy RowMapping for test purposes.
    """
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)


def _mapping_first(data: dict | None):
    if data is None:
        m = MagicMock()
        m.mappings.return_value.first.return_value = None
        return m
    row = _DictRow(data)
    m = MagicMock()
    m.mappings.return_value.first.return_value = row
    return m


def _mapping_all(rows: list):
    mock_rows = [_DictRow(data) for data in rows]
    m = MagicMock()
    m.mappings.return_value.all.return_value = mock_rows
    return m


def _fetchall_result(rows: list):
    m = MagicMock()
    m.fetchall.return_value = rows
    return m


# 分解型 BOM 详情查询的标准 mock（供多个测试复用）
def _bom_detail_side_effect(bom_id: str, tenant_id: str):
    """返回 _fetch_disassembly_bom 的两次 execute mock：主表 + items。"""
    return [
        _mapping_first(
            {
                "id": bom_id,
                "tenant_id": tenant_id,
                "dish_id": DISH_ID,
                "version": 1,
                "total_cost_fen": 0,
                "yield_qty": "10.00",
                "yield_unit": "kg",
                "is_active": False,
                "notes": "整鱼分切",
                "assembly_type": "disassembly",
                "created_at": None,
                "updated_at": None,
                "is_deleted": False,
            }
        ),
        _mapping_all(
            [
                {"id": str(uuid.uuid4()), "bom_id": bom_id, "ingredient_name": "鱼柳",
                 "ingredient_code": "FISH-FILLET", "quantity": "5.000", "unit": "kg",
                 "sort_order": 0, "created_at": None, "updated_at": None},
                {"id": str(uuid.uuid4()), "bom_id": bom_id, "ingredient_name": "鱼骨",
                 "ingredient_code": "FISH-BONE", "quantity": "2.000", "unit": "kg",
                 "sort_order": 1, "created_at": None, "updated_at": None},
                {"id": str(uuid.uuid4()), "bom_id": bom_id, "ingredient_name": "内脏",
                 "ingredient_code": "FISH-GUT", "quantity": "3.000", "unit": "kg",
                 "sort_order": 2, "created_at": None, "updated_at": None},
            ]
        ),
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# 用例 1: 10kg 整鱼分解型 BOM 创建 — 核心海鲜分切场景
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateDisassemblyBom:
    def test_create_disassembly_bom_10kg_fish(self):
        """10kg 整鱼分解型 BOM 创建: 产出鱼柳5kg + 鱼骨2kg + 内脏3kg。
        断言: assembly_type='disassembly', is_active=False, items 3 行。
        """
        db = _mock_db()
        bom_id = str(uuid.uuid4())

        # INSERT dish_boms RETURNING id
        insert_result = MagicMock()
        insert_result.scalar.return_value = bom_id

        db.execute.side_effect = [
            MagicMock(),              # set_config
            insert_result,            # INSERT dish_boms RETURNING id
            MagicMock(),              # INSERT dish_bom_items row 1 (鱼柳)
            MagicMock(),              # INSERT dish_bom_items row 2 (鱼骨)
            MagicMock(),              # INSERT dish_bom_items row 3 (内脏)
            # _fetch_disassembly_bom: SELECT dish_boms + SELECT dish_bom_items
            *_bom_detail_side_effect(bom_id, TENANT_A),
        ]

        payload = {
            "dish_id": DISH_ID,
            "yield_qty": "10.0",
            "yield_unit": "kg",
            "notes": "整鱼分切标准 2026Q1",
            "items": [
                {"ingredient_name": "鱼柳", "ingredient_code": "FISH-FILLET",
                 "quantity": "5.000", "unit": "kg"},
                {"ingredient_name": "鱼骨", "ingredient_code": "FISH-BONE",
                 "quantity": "2.000", "unit": "kg"},
                {"ingredient_name": "内脏", "ingredient_code": "FISH-GUT",
                 "quantity": "3.000", "unit": "kg"},
            ],
        }
        resp = _client(db).post(
            "/api/v1/supply/boms/disassembly",
            json=payload,
            headers=HEADERS_A,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["assembly_type"] == "disassembly"
        assert data["is_active"] is False
        assert len(data["items"]) == 3
        names = [it["ingredient_name"] for it in data["items"]]
        assert "鱼柳" in names
        assert "鱼骨" in names
        assert "内脏" in names


# ═══════════════════════════════════════════════════════════════════════════════
# 用例 2: 按投入量 5kg 计算分解产出（比例）
# ═══════════════════════════════════════════════════════════════════════════════


class TestCalculateDisassembly:
    def test_calculate_disassembly_proportional(self):
        """按投入量 5kg 计算分解产出（比例）:
        鱼柳 5/10*5=2.5kg + 鱼骨 2/10*5=1.0kg + 内脏 3/10*5=1.5kg。
        dry-run，不写 DB。
        """
        db = _mock_db()

        # disassemble_ingredient 内部: SELECT dish_boms, SELECT dish_bom_items
        db.execute.side_effect = [
            MagicMock(),  # set_config
            _mapping_first(
                {
                    "id": BOM_ID,
                    "yield_qty": "10.0",
                    "assembly_type": "disassembly",
                }
            ),
            _mapping_all(
                [
                    {"ingredient_name": "鱼柳", "ingredient_code": "FISH-FILLET",
                     "quantity": "5.0", "unit": "kg"},
                    {"ingredient_name": "鱼骨", "ingredient_code": "FISH-BONE",
                     "quantity": "2.0", "unit": "kg"},
                    {"ingredient_name": "内脏", "ingredient_code": "FISH-GUT",
                     "quantity": "3.0", "unit": "kg"},
                ]
            ),
        ]

        resp = _client(db).post(
            f"/api/v1/supply/boms/disassembly/{BOM_ID}/calculate",
            json={"input_qty": 5.0},
            headers=HEADERS_A,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["bom_id"] == BOM_ID
        assert data["input_qty"] == 5.0

        outputs = {o["ingredient_name"]: o["output_qty"] for o in data["outputs"]}
        assert abs(outputs["鱼柳"] - 2.5) < 1e-9
        assert abs(outputs["鱼骨"] - 1.0) < 1e-9
        assert abs(outputs["内脏"] - 1.5) < 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# 用例 3: 产出总量超过整件量 — 校验拒绝 422
# ═══════════════════════════════════════════════════════════════════════════════


class TestDisassemblySumValidation:
    def test_disassembly_sum_exceeds_yield_rejected(self):
        """产出组件总量 12 > yield_qty 10 → 422（校验拒绝）。"""
        db = _mock_db()
        db.execute.side_effect = [
            MagicMock(),  # set_config
        ]

        payload = {
            "dish_id": DISH_ID,
            "yield_qty": "10.0",
            "yield_unit": "kg",
            "items": [
                {"ingredient_name": "鱼柳", "ingredient_code": None,
                 "quantity": "7.0", "unit": "kg"},
                {"ingredient_name": "鱼骨", "ingredient_code": None,
                 "quantity": "5.0", "unit": "kg"},  # sum=12 > 10
            ],
        }
        resp = _client(db).post(
            "/api/v1/supply/boms/disassembly",
            json=payload,
            headers=HEADERS_A,
        )
        assert resp.status_code == 422
        # 验证没有写 DB（rollback 而非 commit）
        db.commit.assert_not_called()
        db.rollback.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# 用例 4: 现有组装型 BOM（cashier 扣料路径）不受影响
# ═══════════════════════════════════════════════════════════════════════════════


class TestExistingAssemblyBomUnaffected:
    def test_existing_assembly_bom_unaffected(self):
        """现有 GET /boms 接口不因分解型端点受影响，assembly BOM 正常返回。"""
        db = _mock_db()
        asm_bom_id = str(uuid.uuid4())

        db.execute.side_effect = [
            MagicMock(),                    # set_config
            _scalar_result(1),              # COUNT
            _fetchall_result([(asm_bom_id,)]),  # ids
            # _fetch_bom_with_items: SELECT dish_boms + SELECT dish_bom_items
            _mapping_first(
                {
                    "id": asm_bom_id,
                    "tenant_id": TENANT_A,
                    "dish_id": DISH_ID,
                    "version": 1,
                    "total_cost_fen": 500,
                    "yield_qty": "1.00",
                    "yield_unit": "份",
                    "is_active": True,
                    "notes": None,
                    "created_at": None,
                    "updated_at": None,
                    "is_deleted": False,
                }
            ),
            _mapping_all([]),  # items 空
        ]

        resp = _client(db).get("/api/v1/supply/boms", headers=HEADERS_A)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 1
        # assembly BOM 正常返回，不被 disassembly 端点干扰


# ═══════════════════════════════════════════════════════════════════════════════
# 用例 5: 租户隔离 — tenant_B 的分解型 BOM 不被 tenant_A 看到
# ═══════════════════════════════════════════════════════════════════════════════


class TestRlsDisassemblyBomTenantIsolation:
    def test_rls_disassembly_bom_tenant_isolation(self):
        """GET /boms/disassembly/{bom_id}: tenant_A 查 tenant_B 的 BOM → 404。
        RLS set_config 已限制，mock 模拟 DB 返回 None（RLS 过滤结果）。
        """
        db = _mock_db()

        db.execute.side_effect = [
            MagicMock(),          # set_config (tenant_A 的 RLS)
            _mapping_first(None), # SELECT dish_boms → None（RLS 过滤 tenant_B 数据）
        ]

        # tenant_A 请求 tenant_B 的 BOM ID（RLS 应过滤掉，DB 返回 None → 404）
        resp = _client(db).get(
            f"/api/v1/supply/boms/disassembly/{BOM_ID}",
            headers=HEADERS_A,
        )
        assert resp.status_code == 404
        detail = resp.json().get("detail", "")
        assert "不存在" in detail or "not found" in detail.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 用例 6: 分解型 BOM 不应被 cashier consume-stock 用作扣料模板
# ═══════════════════════════════════════════════════════════════════════════════


class TestDisassemblyBomNotConsumedByCashier:
    def test_disassembly_bom_not_consumed_by_cashier(self):
        """分解型 BOM 默认 is_active=False，consume-stock 找不到有效 BOM → 400。
        cashier 路径：WHERE is_active=true，分解型不存在激活版本。
        """
        db = _mock_db()

        db.execute.side_effect = [
            MagicMock(),          # set_config
            _mapping_first(None), # SELECT dish_boms WHERE is_active=true → None（分解型未激活）
        ]

        payload = {
            "quantity": "1.0",
            "store_id": str(uuid.uuid4()),
        }
        resp = _client(db).post(
            f"/api/v1/supply/dishes/{DISH_ID}/consume-stock",
            json=payload,
            headers=HEADERS_A,
        )
        # cashier consume-stock 应返回 400（无有效 BOM）而非成功
        assert resp.status_code == 400
        detail = resp.json().get("detail", "")
        assert "BOM" in detail or "bom" in detail.lower()
