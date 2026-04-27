"""tx-finance 预算管理路由测试 — test_finance_more.py

覆盖 budget_routes.py（8 端点，尚无测试）的核心场景：

  [1] POST   /api/v1/finance/budgets              — 正常创建预算计划 → 201
  [2] POST   /api/v1/finance/budgets              — period_type 非法 → 422
  [3] GET    /api/v1/finance/budgets              — 列表查询正常返回
  [4] POST   /api/v1/finance/budgets/{id}/approve — BudgetService 抛 ValueError → 400
  [5] GET    /api/v1/finance/budgets/{id}/progress — 进度查询，计划不存在 → 404

运行方式：
    cd /Users/lichun/tunxiang-os
    pytest services/tx-finance/src/tests/test_finance_more.py -v
"""

from __future__ import annotations

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

# ──────────────────────────────────────────────────────────────────────────────
# 路径注入：让 `src.*` 包可从 tx-finance/ 目录解析
# ──────────────────────────────────────────────────────────────────────────────
_TX_FINANCE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
sys.path.insert(0, os.path.abspath(_TX_FINANCE + "/services/tx-finance"))

# ──────────────────────────────────────────────────────────────────────────────
# 存根工具
# ──────────────────────────────────────────────────────────────────────────────


def _make_stub(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# ── structlog 存根 ─────────────────────────────────────────────────────────────
if "structlog" not in sys.modules:
    _log_mock = MagicMock()
    _log_mock.get_logger.return_value = MagicMock(info=MagicMock(), error=MagicMock(), warning=MagicMock())
    sys.modules["structlog"] = _log_mock

# ── sqlalchemy 系列存根 ────────────────────────────────────────────────────────
if "sqlalchemy" not in sys.modules:
    sa_stub = _make_stub("sqlalchemy", text=lambda s: s)
    sa_ext_stub = _make_stub("sqlalchemy.ext")
    sa_ext_async = _make_stub("sqlalchemy.ext.asyncio", AsyncSession=MagicMock())
    sys.modules["sqlalchemy"] = sa_stub
    sys.modules["sqlalchemy.ext"] = sa_ext_stub
    sys.modules["sqlalchemy.ext.asyncio"] = sa_ext_async

# ── shared.ontology.src.database 存根 ─────────────────────────────────────────
_db_stub = _make_stub(
    "shared.ontology.src.database",
    get_db=AsyncMock(),
    get_db_with_tenant=AsyncMock(),
)
sys.modules.setdefault("shared", _make_stub("shared"))
sys.modules.setdefault("shared.ontology", _make_stub("shared.ontology"))
sys.modules.setdefault("shared.ontology.src", _make_stub("shared.ontology.src"))
sys.modules["shared.ontology.src.database"] = _db_stub

# ── src.services.budget_service 存根 ──────────────────────────────────────────
# budget_routes.py 使用相对导入 from ..services.budget_service import ...
# 从 src.api 包相对解析 → src.services.budget_service
_VALID_CATEGORIES = (
    "revenue",
    "ingredient_cost",
    "labor_cost",
    "fixed_cost",
    "marketing_cost",
    "total",
)
_VALID_PERIOD_TYPES = ("monthly", "quarterly", "yearly")
_VALID_STATUSES = ("draft", "approved", "locked")

_BudgetServiceMock = MagicMock()
_budget_svc_stub = _make_stub(
    "src.services.budget_service",
    BudgetService=_BudgetServiceMock,
    VALID_CATEGORIES=_VALID_CATEGORIES,
    VALID_PERIOD_TYPES=_VALID_PERIOD_TYPES,
    VALID_STATUSES=_VALID_STATUSES,
)
# 只注册 service 存根，不覆盖真实 src 包（避免与其他测试的 sys.modules 冲突）
sys.modules["src.services.budget_service"] = _budget_svc_stub

# ── 加载被测路由 ───────────────────────────────────────────────────────────────
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import budget_routes  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# 公共常量
# ──────────────────────────────────────────────────────────────────────────────
TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
PLAN_ID = str(uuid.uuid4())
TENANT_HDR = {"X-Tenant-ID": TENANT_ID}


# ──────────────────────────────────────────────────────────────────────────────
# 辅助：构建 FastAPI app，注入 mock DB session
# ──────────────────────────────────────────────────────────────────────────────


def _build_app(db_session: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(budget_routes.router)
    app.dependency_overrides[budget_routes._get_tenant_db] = lambda: db_session
    return app


def _budget_svc_instance(
    upsert_val=None,
    list_val=None,
    get_val=None,
    approve_val=None,
    progress_val=None,
    raise_on: str | None = None,
    raise_exc: Exception | None = None,
) -> AsyncMock:
    """构建 BudgetService 实例 mock，按需配置各方法返回值或异常。"""
    svc = AsyncMock()
    svc.upsert_plan = AsyncMock(return_value=upsert_val or {"id": PLAN_ID, "status": "draft"})
    svc.list_plans = AsyncMock(return_value=list_val if list_val is not None else [])
    svc.get_plan = AsyncMock(return_value=get_val)
    svc.approve_plan = AsyncMock(return_value=approve_val or {"id": PLAN_ID, "status": "approved"})
    svc.record_execution = AsyncMock(return_value={"id": PLAN_ID})
    svc.get_execution_progress = AsyncMock(
        return_value=progress_val
        or {
            "plan_id": PLAN_ID,
            "budget_fen": 100000,
            "actual_fen": 60000,
            "variance_fen": -40000,
            "completion_rate": 0.6,
        }
    )
    svc.get_store_budget_summary = AsyncMock(return_value={"items": [], "total": 0})

    if raise_on and raise_exc:
        getattr(svc, raise_on).side_effect = raise_exc

    return svc


# ════════════════════════════════════════════════════════════════════════════
# 测试用例（5 个）
# ════════════════════════════════════════════════════════════════════════════


class TestBudgetRoutes:
    """budget_routes.py 的 5 个核心测试"""

    # ── 1. POST /budgets — 正常创建预算计划 → 201 ────────────────────────

    def test_upsert_budget_success(self):
        """合法请求应以 201 返回预算计划 id 和 status=draft。"""
        plan_data = {
            "id": PLAN_ID,
            "store_id": STORE_ID,
            "period_type": "monthly",
            "period": "2026-04",
            "category": "revenue",
            "budget_fen": 5_000_000,
            "status": "draft",
        }
        mock_svc = _budget_svc_instance(upsert_val=plan_data)
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        app = _build_app(mock_db)

        with patch.object(budget_routes, "BudgetService", return_value=mock_svc):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/finance/budgets",
                    json={
                        "store_id": STORE_ID,
                        "period_type": "monthly",
                        "period": "2026-04",
                        "category": "revenue",
                        "budget_fen": 5_000_000,
                    },
                    headers=TENANT_HDR,
                )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["id"] == PLAN_ID
        assert body["data"]["status"] == "draft"

    # ── 2. POST /budgets — period_type 非法 → 422（Pydantic 校验）───────

    def test_upsert_budget_invalid_period_type(self):
        """period_type 不在枚举内时，Pydantic 校验应拦截并返回 422。"""
        mock_db = AsyncMock()
        app = _build_app(mock_db)

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/finance/budgets",
                json={
                    "store_id": STORE_ID,
                    "period_type": "weekly",  # 非法值
                    "period": "2026-W15",
                    "category": "revenue",
                    "budget_fen": 1_000_000,
                },
                headers=TENANT_HDR,
            )

        assert resp.status_code == 422

    # ── 3. GET /budgets — 列表查询，正常返回 ────────────────────────────

    def test_list_budgets_success(self):
        """不带过滤条件的列表查询，应返回 ok=True，data.items 为列表。"""
        items = [
            {"id": PLAN_ID, "period": "2026-04", "category": "revenue", "status": "draft"},
        ]
        mock_svc = _budget_svc_instance(list_val=items)
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        app = _build_app(mock_db)

        with patch.object(budget_routes, "BudgetService", return_value=mock_svc):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/finance/budgets",
                    headers=TENANT_HDR,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["id"] == PLAN_ID

    # ── 4. POST /budgets/{id}/approve — ValueError → 400 ─────────────────

    def test_approve_budget_value_error(self):
        """预算计划状态不允许审批时（如已是 approved），应返回 400。"""
        mock_svc = _budget_svc_instance(
            raise_on="approve_plan",
            raise_exc=ValueError("预算计划当前状态 approved 不允许审批"),
        )
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        app = _build_app(mock_db)

        with patch.object(budget_routes, "BudgetService", return_value=mock_svc):
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/v1/finance/budgets/{PLAN_ID}/approve",
                    json={"approved_by": "mgr-001"},
                    headers=TENANT_HDR,
                )

        assert resp.status_code == 400
        assert "不允许审批" in resp.json()["detail"]

    # ── 5. GET /budgets/{id}/progress — 计划不存在 → 404 ─────────────────

    def test_get_execution_progress_not_found(self):
        """progress 端点在 BudgetService 抛 ValueError 时，应返回 404。"""
        mock_svc = _budget_svc_instance(
            raise_on="get_execution_progress",
            raise_exc=ValueError(f"预算计划不存在: {PLAN_ID}"),
        )
        mock_db = AsyncMock()

        app = _build_app(mock_db)

        with patch.object(budget_routes, "BudgetService", return_value=mock_svc):
            with TestClient(app) as client:
                resp = client.get(
                    f"/api/v1/finance/budgets/{PLAN_ID}/progress",
                    headers=TENANT_HDR,
                )

        assert resp.status_code == 404
        assert PLAN_ID in resp.json()["detail"]
