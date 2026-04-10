"""供应链扩展路由单元测试

覆盖文件：api/procurement_recommend_routes.py（4 个端点，尚无测试中端点最多）
测试 5 个场景：

  1. GET  /api/v1/procurement/recommend/{store_id}          — 正常返回采购建议列表
  2. POST /api/v1/procurement/recommend/{store_id}/apply    — 空 recommendation_ids → 400
  3. POST /api/v1/procurement/recommend/{store_id}/apply    — 正常应用建议返回结果
  4. GET  /api/v1/procurement/suppliers/{ingredient_id}/scores — DB 查询正常，无供应商 → 空列表
  5. GET  /api/v1/procurement/alerts/{store_id}             — 正常返回紧急预警（urgent_count）

技术说明：
  - shared.ontology.src.database.get_db 通过 sys.modules 注入存根
  - AutoProcurementService 通过 unittest.mock.patch 替换
  - DB 依赖通过 app.dependency_overrides[_get_db] 注入 mock AsyncSession
  - mock execute 使用 MagicMock 模拟 fetchall 返回空列表（无供应商场景）
"""
from __future__ import annotations

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── 路径设置 ──────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ─── shared.* / structlog 存根注入（必须在导入路由模块前完成）──────────────────


def _make_supply_stubs():
    """注入 shared.* 外部依赖存根，避免循环导入和真实 DB 连接。"""

    # structlog
    sl = types.ModuleType("structlog")
    sl.get_logger = MagicMock(return_value=MagicMock(
        info=MagicMock(), warning=MagicMock(), error=MagicMock(),
    ))
    sys.modules.setdefault("structlog", sl)

    # shared
    shared = types.ModuleType("shared")
    sys.modules.setdefault("shared", shared)

    # shared.ontology
    ont = types.ModuleType("shared.ontology")
    sys.modules.setdefault("shared.ontology", ont)

    # shared.ontology.src
    ont_src = types.ModuleType("shared.ontology.src")
    sys.modules.setdefault("shared.ontology.src", ont_src)

    # shared.ontology.src.database — 暴露 get_db 占位（测试中通过 dependency_overrides 覆盖）
    db_mod = types.ModuleType("shared.ontology.src.database")
    db_mod.get_db = lambda: None  # type: ignore[attr-defined]
    sys.modules.setdefault("shared.ontology.src.database", db_mod)

    # shared.events
    ev = types.ModuleType("shared.events")
    sys.modules.setdefault("shared.events", ev)
    ev_src = types.ModuleType("shared.events.src")
    sys.modules.setdefault("shared.events.src", ev_src)
    emitter = types.ModuleType("shared.events.src.emitter")
    emitter.emit_event = AsyncMock(return_value=None)  # type: ignore[attr-defined]
    sys.modules.setdefault("shared.events.src.emitter", emitter)

    # services 包存根（procurement_recommend_routes 内部通过相对 lazy import 引入 AutoProcurementService
    # 当 sys.path 包含 src/ 且模块名为 api.xxx 时，相对 ..services 解析为 services）
    svc_pkg = types.ModuleType("services")
    sys.modules.setdefault("services", svc_pkg)

    # services.auto_procurement — 预先注入 AutoProcurementService 存根；
    # 各测试用例会通过 patch 替换此类
    auto_proc_mod = types.ModuleType("services.auto_procurement")
    auto_proc_mod.AutoProcurementService = MagicMock()  # type: ignore[attr-defined]
    sys.modules.setdefault("services.auto_procurement", auto_proc_mod)


_make_supply_stubs()

# ─── 导入路由模块 ──────────────────────────────────────────────────────────────

from api.procurement_recommend_routes import router  # noqa: E402
from api.procurement_recommend_routes import _get_db  # noqa: E402

# ─── 公共常量 ──────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
INGREDIENT_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── Mock DB 工厂 ──────────────────────────────────────────────────────────────


def _mock_db():
    """返回可注入的 mock AsyncSession。"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ─── FastAPI 应用工厂（注入 mock DB）──────────────────────────────────────────


def _make_app(db) -> TestClient:
    """每个测试用例独立 FastAPI 实例，通过 dependency_overrides 注入 mock DB。"""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/procurement")

    async def override_get_db():
        yield db

    app.dependency_overrides[_get_db] = override_get_db
    return TestClient(app, raise_server_exceptions=False)


# ─── 采购建议存根工厂 ──────────────────────────────────────────────────────────


def _make_recommendation(ingredient_name: str, is_urgent: bool = False):
    rec = MagicMock()
    rec.recommendation_id = str(uuid.uuid4())
    rec.ingredient_id = str(uuid.uuid4())
    rec.ingredient_name = ingredient_name
    rec.current_qty = 2.5
    rec.unit = "kg"
    rec.daily_consumption = 1.2
    rec.days_remaining = 2.0 if is_urgent else 10.0
    rec.recommended_qty = 8.0
    rec.estimated_cost_fen = 4800
    rec.supplier_name = "食材供应商A"
    rec.is_urgent = is_urgent
    rec.model_dump = MagicMock(return_value={
        "recommendation_id": rec.recommendation_id,
        "ingredient_id": rec.ingredient_id,
        "ingredient_name": ingredient_name,
        "is_urgent": is_urgent,
    })
    return rec


# ══════════════════════════════════════════════════════════════════════════════
# 一、获取采购建议列表 — GET /recommend/{store_id}（正常返回）
# ══════════════════════════════════════════════════════════════════════════════


def test_get_recommendations_ok():
    """正常场景：AutoProcurementService 返回 2 条建议（1 紧急），响应 ok=True。"""
    recs = [
        _make_recommendation("鲈鱼", is_urgent=True),
        _make_recommendation("猪里脊", is_urgent=False),
    ]

    db = _mock_db()
    client = _make_app(db)

    with patch(
        "services.auto_procurement.AutoProcurementService",
        autospec=False,
    ) as MockSvc:
        mock_svc_instance = MagicMock()
        mock_svc_instance.generate_recommendations = AsyncMock(return_value=recs)
        MockSvc.return_value = mock_svc_instance

        resp = client.get(
            f"/api/v1/procurement/recommend/{STORE_ID}",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["store_id"] == STORE_ID
    assert data["total"] == 2
    assert data["urgent_count"] == 1
    assert len(data["recommendations"]) == 2


# ══════════════════════════════════════════════════════════════════════════════
# 二、应用建议 — POST /recommend/{store_id}/apply（空 recommendation_ids → 400）
# ══════════════════════════════════════════════════════════════════════════════


def test_apply_recommendations_empty_ids_400():
    """recommendation_ids 为空列表时，路由应直接返回 400 并包含错误描述。"""
    db = _mock_db()
    client = _make_app(db)

    resp = client.post(
        f"/api/v1/procurement/recommend/{STORE_ID}/apply",
        json={"recommendation_ids": [], "requester_id": "user-001"},
        headers=HEADERS,
    )

    assert resp.status_code == 400
    detail = resp.json().get("detail", "")
    assert "recommendation_ids" in detail or "不可为空" in detail


# ══════════════════════════════════════════════════════════════════════════════
# 三、应用建议 — POST /recommend/{store_id}/apply（正常采纳建议）
# ══════════════════════════════════════════════════════════════════════════════


def test_apply_recommendations_ok():
    """正常场景：匹配建议存在时应返回申购单创建结果。"""
    rec = _make_recommendation("花甲", is_urgent=True)
    selected_id = rec.recommendation_id

    db = _mock_db()
    client = _make_app(db)

    with patch(
        "services.auto_procurement.AutoProcurementService",
        autospec=False,
    ) as MockSvc:
        mock_svc_instance = MagicMock()
        mock_svc_instance.generate_recommendations = AsyncMock(return_value=[rec])
        mock_svc_instance.create_requisition_from_recommendations = AsyncMock(
            return_value={
                "requisition_id": str(uuid.uuid4()),
                "item_count": 1,
                "status": "draft",
            }
        )
        MockSvc.return_value = mock_svc_instance

        resp = client.post(
            f"/api/v1/procurement/recommend/{STORE_ID}/apply",
            json={
                "recommendation_ids": [selected_id],
                "requester_id": "user-001",
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["item_count"] == 1
    assert data["status"] == "draft"
    assert "requisition_id" in data


# ══════════════════════════════════════════════════════════════════════════════
# 四、供应商评分 — GET /suppliers/{ingredient_id}/scores（无历史供应商 → 空列表）
# ══════════════════════════════════════════════════════════════════════════════


def test_get_supplier_scores_no_suppliers():
    """DB 查询 receiving_records 返回空行时，scores 应为空列表。"""
    db = _mock_db()
    # fetchall() 返回空（无历史供应商记录）
    empty_result = MagicMock()
    empty_result.fetchall = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=empty_result)

    client = _make_app(db)

    with patch(
        "services.auto_procurement.AutoProcurementService",
        autospec=False,
    ) as MockSvc:
        mock_svc_instance = MagicMock()
        MockSvc.return_value = mock_svc_instance

        resp = client.get(
            f"/api/v1/procurement/suppliers/{INGREDIENT_ID}/scores",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["ingredient_id"] == INGREDIENT_ID
    assert data["supplier_count"] == 0
    assert data["scores"] == []


# ══════════════════════════════════════════════════════════════════════════════
# 五、紧急采购预警 — GET /alerts/{store_id}（正常返回 urgent 预警）
# ══════════════════════════════════════════════════════════════════════════════


def test_get_procurement_alerts_urgent():
    """generate_recommendations 含 is_urgent=True 的建议时，alerts 列表非空。"""
    urgent_rec = _make_recommendation("海虾", is_urgent=True)
    normal_rec = _make_recommendation("豆腐", is_urgent=False)

    db = _mock_db()
    client = _make_app(db)

    with patch(
        "services.auto_procurement.AutoProcurementService",
        autospec=False,
    ) as MockSvc:
        mock_svc_instance = MagicMock()
        mock_svc_instance.generate_recommendations = AsyncMock(
            return_value=[urgent_rec, normal_rec]
        )
        MockSvc.return_value = mock_svc_instance

        resp = client.get(
            f"/api/v1/procurement/alerts/{STORE_ID}",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["store_id"] == STORE_ID
    assert data["urgent_count"] == 1
    assert len(data["alerts"]) == 1
    alert = data["alerts"][0]
    assert alert["ingredient_name"] == "海虾"
    assert alert["days_remaining"] == pytest.approx(2.0)
