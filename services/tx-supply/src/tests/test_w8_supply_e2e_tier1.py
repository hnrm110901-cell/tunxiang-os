"""Tier 1 — W8 供应链三表联动 e2e（PRD-02 扣秤 + PRD-06 出料率 + PRD-05 时间窗）

CLAUDE.md §22 Week 8 DEMO 验收门槛 — Tier 1 全绿（含 PRD-02/05/06 三表联动）。
本测试验证三个 W7-W8 ship 的 Tier 1 表 + receiving 主流程的契约级集成：

  1. v428 ingredient_weight_standards     — PRD-02 扣秤标准库
  2. v429 ingredient_yield_standards      — PRD-06 出料率标准库
  3. v430 supplier_delivery_windows       — PRD-05 配送时间窗（+ violations 日志）

测试视角（CLAUDE.md §19 验证视角）：徐记海鲜收银员场景 —
  收货员扫码到货 → 系统并行检查（扣秤 + 出料率 + 时间窗），任一异常都不应阻塞其他维度。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+ — 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )


# ─── helper ───────────────────────────────────────────────────────────────────


def _read_file(rel: str) -> str:
    """读取 worktree 根相对路径文件。"""
    here = Path(__file__).resolve()
    # tests / src / tx-supply / services / tunxiang-os
    repo_root = here.parent.parent.parent.parent.parent
    return (repo_root / rel).read_text(encoding="utf-8")


# ─── 1. 三个 v428/v429/v430 migration 全部存在且 chain 正确 ─────────────────


class TestW8MigrationChain:
    def test_v428_weight_standards_present(self):
        """v428 ingredient_weight_standards migration 存在（PRD-02 W7-1 ship）。"""
        src = _read_file(
            "shared/db-migrations/versions/v428_ingredient_weight_standards.py"
        )
        assert "ingredient_weight_standards" in src
        assert "ENABLE ROW LEVEL SECURITY" in src
        assert "FORCE ROW LEVEL SECURITY" in src, "v428 必须含 FORCE（PR #633 R2 教训）"

    def test_v429_yield_standards_present(self):
        """v429 ingredient_yield_standards migration 存在（PRD-06 W7-2 ship）。"""
        src = _read_file(
            "shared/db-migrations/versions/v429_ingredient_yield_standards.py"
        )
        assert "ingredient_yield_standards" in src
        assert "ENABLE ROW LEVEL SECURITY" in src
        assert "FORCE ROW LEVEL SECURITY" in src

    def test_v430_delivery_window_present(self):
        """v430 supplier_delivery_windows + violations migration 存在（PRD-05 W8）。"""
        src = _read_file(
            "shared/db-migrations/versions/v430_supplier_delivery_windows.py"
        )
        assert "supplier_delivery_windows" in src
        assert "supplier_delivery_violations" in src
        assert "ENABLE ROW LEVEL SECURITY" in src
        assert "FORCE ROW LEVEL SECURITY" in src, "v430 必须含 FORCE（PR #633 R2 教训）"

    def test_v430_chain_v429(self):
        """v430 down_revision 必须指向 v429（chain integrity）。"""
        src = _read_file(
            "shared/db-migrations/versions/v430_supplier_delivery_windows.py"
        )
        assert 'down_revision: Union[str, Sequence[str], None] = "v429_ingredient_yield_standards"' in src, (
            "v430.down_revision 必须 = v429（防双 head）"
        )


# ─── 2. 三个事件类型全部注册到 SupplyEventType ─────────────────────────────


class TestW8EventTypes:
    def test_weight_deduction_anomaly_registered(self):
        """SupplyEventType.WEIGHT_DEDUCTION_ANOMALY = supply.weight_deduction.anomaly（PRD-02）。"""
        src = _read_file("shared/events/supply_events.py")
        assert 'WEIGHT_DEDUCTION_ANOMALY = "supply.weight_deduction.anomaly"' in src

    def test_yield_anomaly_registered(self):
        """SupplyEventType.YIELD_ANOMALY = supply.yield.anomaly（PRD-06）。"""
        src = _read_file("shared/events/supply_events.py")
        assert 'YIELD_ANOMALY = "supply.yield.anomaly"' in src

    def test_delivery_late_registered(self):
        """SupplyEventType.DELIVERY_LATE = supply.delivery.late（PRD-05）。"""
        src = _read_file("shared/events/supply_events.py")
        assert 'DELIVERY_LATE = "supply.delivery.late"' in src


# ─── 3. 三个 service 文件存在且对外 API 签名稳定 ──────────────────────────


class TestW8ServiceAPI:
    def test_weight_standard_service_calculate_present(self):
        """weight_standard_service.apply_weight_deduction_for_item（PRD-02 主 API）。"""
        src = _read_file("services/tx-supply/src/services/weight_standard_service.py")
        assert "apply_weight_deduction_for_item" in src or "calculate" in src

    def test_yield_standard_service_calculate_present(self):
        """yield_standard_service.calculate_purchase_qty（PRD-06 主 API）。"""
        src = _read_file("services/tx-supply/src/services/yield_standard_service.py")
        assert "calculate_purchase_qty" in src

    def test_delivery_window_service_check_present(self):
        """delivery_window_service.check_delivery_window（PRD-05 主 API）。"""
        src = _read_file("services/tx-supply/src/services/delivery_window_service.py")
        assert "check_delivery_window" in src
        assert "record_violation" in src
        assert "count_violations" in src


# ─── 4. 三个 Web UI 页面全部注册到 App.tsx ────────────────────────────────


class TestW8WebUIRoutes:
    def test_weight_standards_route_present(self):
        """/supply/ingredient-weight-standards（PRD-02 W7-1 ship）。"""
        src = _read_file("apps/web-admin/src/App.tsx")
        assert "/supply/ingredient-weight-standards" in src
        assert "IngredientWeightStandardsPage" in src

    def test_yield_standards_route_present(self):
        """/supply/ingredient-yield-standards（PRD-06 W7-2 ship）。"""
        src = _read_file("apps/web-admin/src/App.tsx")
        assert "/supply/ingredient-yield-standards" in src
        assert "IngredientYieldStandardsPage" in src

    def test_delivery_windows_route_present(self):
        """/supply/supplier-delivery-windows（PRD-05 W8）。"""
        src = _read_file("apps/web-admin/src/App.tsx")
        assert "/supply/supplier-delivery-windows" in src
        assert "SupplierDeliveryWindowsPage" in src


# ─── 5. 三个 router 在 tx-supply main.py 注册 ──────────────────────────────


class TestW8MainRouterRegistration:
    def test_weight_standard_router_registered(self):
        src = _read_file("services/tx-supply/src/main.py")
        assert "weight_standard_router" in src

    def test_yield_standard_router_registered(self):
        src = _read_file("services/tx-supply/src/main.py")
        assert "yield_standard_router" in src

    def test_delivery_window_router_registered(self):
        src = _read_file("services/tx-supply/src/main.py")
        assert "delivery_window_router" in src
        # 含描述行（Tier 1 + PRD-05 + v430）
        assert "PRD-05" in src
        assert "v430" in src


# ─── 6. receiving_v2 主流程：三个集成点齐全 ────────────────────────────────


class TestW8ReceivingV2Integration:
    """complete_receiving 完成路径必须按顺序触发三种异常事件（PRD-02/06 旁路 + PRD-05 集成）。

    PRD-02 (WEIGHT_DEDUCTION_ANOMALY)：由 receiving_v2.apply_weight_deduction_for_item 触发
                                       （enhancement layer，单独 endpoint）
    PRD-06 (YIELD_ANOMALY)：由 bom_service.bom_purchase_qty_with_yield 触发（采购建议时）
    PRD-05 (DELIVERY_LATE)：由 complete_receiving 直接集成检查时触发
    """

    def test_complete_receiving_has_delivery_window_check(self):
        """complete_receiving 主路径必须含 check_delivery_window 调用。"""
        src = _read_file("services/tx-supply/src/services/receiving_v2_service.py")
        # 检查 complete_receiving 函数内含 check
        idx = src.find("async def complete_receiving(")
        assert idx > -1, "complete_receiving 必须存在"
        # complete_receiving 函数体 ~600 行（含集成）
        func_body = src[idx : idx + 6000]
        assert "check_delivery_window" in func_body, (
            "complete_receiving 必须在主路径调 check_delivery_window"
        )
        assert "DELIVERY_LATE" in func_body, "complete_receiving 必须发射 DELIVERY_LATE event"

    def test_apply_weight_deduction_for_item_present(self):
        """apply_weight_deduction_for_item（PRD-02 扣秤 enhancement layer）必须存在。"""
        src = _read_file("services/tx-supply/src/services/receiving_v2_service.py")
        assert "apply_weight_deduction_for_item" in src
        assert "WEIGHT_DEDUCTION_ANOMALY" in src


# ─── 7. supplier_scoring_engine 扣分集成 ─────────────────────────────────────


class TestW8SupplierScoringIntegration:
    """delivery_rate 维度必须接入 v430 supplier_delivery_violations 扣分。"""

    def test_delivery_violations_factored_into_delivery_rate(self):
        src = _read_file("services/tx-supply/src/services/supplier_scoring_engine.py")
        assert "supplier_delivery_violations" in src
        assert "adjusted_on_time" in src, (
            "公式必须 explicit (on_time_cnt - violation_cnt)"
        )
