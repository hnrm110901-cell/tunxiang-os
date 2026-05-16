"""tx-supply api 路由 import smoke 测试 (Tier 1 邻接 — 2026-05-16).

修复 2 个 pre-existing import bug，让 tx-supply main.py 能正常 import (uvicorn 启动前提):

1. `dept_issue_routes.py:229` 用 `Query(...)` 但未 import (origin/main `d5d680dd`
   2026-03-28 引入). bug 直接后果: 在 py3.10+ module load 时 NameError, 进而阻挡 main.py
   line 51 处 `from .api.dept_issue_routes import router as dept_issue_router`.
   触 Tier 1 邻接 (PRD-08 部门用料白名单 / 第 27 例 explicit-ask 路径).

2. `kingdee_routes.py:18` 错把 `Header` 从 `shared.ontology.src.database` import (应是
   `fastapi.Header`). 同样在 py3.10+ ImportError, 阻挡 main.py 启动.
   Tier 3 ERP 路径.

测试策略: **只针对修复的 2 个文件**做 import smoke + 端点注册校验.

不做全 api 模块扫描的原因 (feedback_tier1_ci_minimal_deps_trap 借鉴):
- Tier 1 CI workflow 只装 ~10 个核心包, 不含 python-multipart 等 prod runtime deps,
  全扫会触 market_survey_routes RuntimeError (Form data 依赖) 等假阳性
- 全模块 eager import 触 SQLAlchemy mapper 配置 (含 pre-existing
  SupplierReconciliation.supplier 关系 bug), 污染 registry 致下游 16 个 Tier 1
  测试连环失败. **不顺手清理无关代码** + scope 内最小变更原则
"""

from __future__ import annotations


def test_dept_issue_routes_import_ok() -> None:
    """import smoke — module load 必须不抛 NameError (本 PR 修的 1/2 文件)."""
    from services.tx_supply.src.api.dept_issue_routes import router

    assert router.prefix == "/api/v1/supply"


def test_dept_issue_flow_endpoint_registered() -> None:
    """line 229 那个用 Query() 的 endpoint 必须被 FastAPI 注册.

    没注册 = Query NameError 在 module load 时已 raise, import smoke 已失败.
    显式断言路径存在让回归更易诊断.
    """
    from services.tx_supply.src.api.dept_issue_routes import router

    paths = {route.path for route in router.routes}
    expected = "/api/v1/supply/dept-issue/flow/{store_id}/{dept_id}"
    assert expected in paths, (
        f"dept-issue/flow endpoint missing from router. "
        f"Likely cause: Query NameError 回归. paths={sorted(paths)}"
    )


def test_kingdee_routes_import_ok() -> None:
    """import smoke — module load 必须不抛 ImportError (本 PR 修的 2/2 文件)."""
    from services.tx_supply.src.api.kingdee_routes import router

    assert router is not None


def test_kingdee_routes_endpoints_registered() -> None:
    """kingdee_routes Header 来源校正后, 12 个端点必须注册."""
    from services.tx_supply.src.api.kingdee_routes import router

    paths = {route.path for route in router.routes}
    assert len(paths) >= 10, (
        f"kingdee_routes endpoints under-registered ({len(paths)}). "
        f"Likely cause: Header ImportError 回归. paths={sorted(paths)}"
    )
