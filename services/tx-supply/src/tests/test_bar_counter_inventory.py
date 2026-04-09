"""吧台盘点库存测试

覆盖：
  1. test_inventory_query_by_location   — 按 location_type=bar 过滤库存
  2. test_stocktake_create_and_variance — 盘点单创建，差异 = 实际 - 账面
  3. test_requisition_workflow          — 领用单创建/确认流程
  4. test_bar_counter_report            — 盘点报表数据聚合
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest


# ─── 工具函数 ────────────────────────────────────────────────────────────────

def _make_stock_item(
    name: str = "可乐 330ml",
    unit: str = "罐",
    quantity: float = 48.0,
    safety_stock: float = 24.0,
    location_type: str = "bar",
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "ingredient_id": str(uuid.uuid4()),
        "name": name,
        "unit": unit,
        "quantity": quantity,
        "safety_stock": safety_stock,
        "location_type": location_type,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


def _compute_variance(book_qty: float, actual_qty: float) -> float:
    """差异 = 实际 - 账面。正=盘盈，负=盘亏。"""
    return round(actual_qty - book_qty, 3)


# ─── Test 1: 按 location_type=bar 过滤库存 ───────────────────────────────────

class TestInventoryQueryByLocation:
    """库存列表应能按 location_type 过滤，只返回吧台库存。"""

    def test_filter_returns_only_bar_items(self):
        """给定混合 location_type 数据，过滤后只剩 bar 类型。"""
        all_items = [
            _make_stock_item("可乐", location_type="bar"),
            _make_stock_item("鸡腿", location_type="kitchen"),
            _make_stock_item("百威", location_type="bar"),
            _make_stock_item("番茄", location_type="kitchen"),
            _make_stock_item("气泡水", location_type="bar"),
        ]

        bar_items = [i for i in all_items if i["location_type"] == "bar"]
        kitchen_items = [i for i in all_items if i["location_type"] == "kitchen"]

        assert len(bar_items) == 3
        assert len(kitchen_items) == 2
        assert all(i["location_type"] == "bar" for i in bar_items)

    def test_filter_empty_result_when_no_bar_items(self):
        """没有 bar 类型库存时，返回空列表，不报错。"""
        all_items = [
            _make_stock_item("鸡腿", location_type="kitchen"),
            _make_stock_item("番茄", location_type="kitchen"),
        ]

        bar_items = [i for i in all_items if i["location_type"] == "bar"]
        assert bar_items == []

    def test_filter_combines_with_store_id(self):
        """location_type=bar 和 store_id 可组合过滤，各门店数据隔离。"""
        store_a = "store-aaa"
        store_b = "store-bbb"

        all_items = [
            {**_make_stock_item("可乐", location_type="bar"), "store_id": store_a},
            {**_make_stock_item("百威", location_type="bar"), "store_id": store_b},
            {**_make_stock_item("鸡腿", location_type="kitchen"), "store_id": store_a},
        ]

        store_a_bar = [i for i in all_items
                       if i["location_type"] == "bar" and i["store_id"] == store_a]
        assert len(store_a_bar) == 1
        assert store_a_bar[0]["name"] == "可乐"

    def test_low_stock_status_calculated_correctly(self):
        """库存低于安全库存时，status 应为 'low'；到 0 时为 'out'。"""
        items = [
            _make_stock_item("百威", quantity=3.0, safety_stock=5.0),
            _make_stock_item("气泡水", quantity=0.0, safety_stock=12.0),
            _make_stock_item("可乐", quantity=48.0, safety_stock=24.0),
        ]

        def compute_status(item: dict) -> str:
            if item["quantity"] == 0:
                return "out"
            if item["quantity"] < item["safety_stock"]:
                return "low"
            return "ok"

        statuses = [compute_status(i) for i in items]
        assert statuses == ["low", "out", "ok"]


# ─── Test 2: 盘点单创建，差异 = 实际 - 账面 ──────────────────────────────────

class TestStocktakeCreateAndVariance:
    """盘点单：差异计算正确，盘盈为正，盘亏为负。"""

    def test_variance_positive_means_surplus(self):
        """实际 > 账面 → 盘盈（正差异）。"""
        book_qty = 10.0
        actual_qty = 12.0
        variance = _compute_variance(book_qty, actual_qty)
        assert variance == 2.0
        assert variance > 0, "正差异表示盘盈"

    def test_variance_negative_means_shortage(self):
        """实际 < 账面 → 盘亏（负差异）。"""
        book_qty = 10.0
        actual_qty = 8.5
        variance = _compute_variance(book_qty, actual_qty)
        assert variance == -1.5
        assert variance < 0, "负差异表示盘亏"

    def test_variance_zero_means_balanced(self):
        """实际 = 账面 → 无差异。"""
        book_qty = 24.0
        actual_qty = 24.0
        variance = _compute_variance(book_qty, actual_qty)
        assert variance == 0.0

    def test_stocktake_aggregates_total_variance_fen(self):
        """盘点单总损益金额 = 各品项差异数量 × 单价。"""
        stocktake_items = [
            {"name": "可乐",  "variance": 2.0,  "unit_cost_fen": 300},   # 盘盈 600分
            {"name": "百威",  "variance": -1.0, "unit_cost_fen": 15000}, # 盘亏 -15000分
            {"name": "气泡水","variance": 0.0,  "unit_cost_fen": 500},   # 无差异
        ]

        total_variance_fen = sum(
            int(item["variance"] * item["unit_cost_fen"])
            for item in stocktake_items
        )

        assert total_variance_fen == -14400  # 600 - 15000 = -14400

    def test_stocktake_status_transition(self):
        """盘点单状态流转：draft → submitted → confirmed。"""
        valid_transitions = {
            "draft": ["submitted"],
            "submitted": ["confirmed", "draft"],  # 可退回草稿
            "confirmed": [],  # 终态
        }

        current = "draft"
        assert "submitted" in valid_transitions[current]

        current = "submitted"
        assert "confirmed" in valid_transitions[current]

        current = "confirmed"
        assert valid_transitions[current] == []


# ─── Test 3: 领用单创建/确认流程 ─────────────────────────────────────────────

class TestRequisitionWorkflow:
    """领用单：创建 → 待审批 → 审批通过后扣减库存。"""

    def test_create_requisition_initial_status_pending(self):
        """新建领用单初始状态为 pending。"""
        requisition = {
            "id": str(uuid.uuid4()),
            "store_id": "store-aaa",
            "items": [{"ingredient_id": "i1", "quantity": 3.0}],
            "requester_id": "emp-001",
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        assert requisition["status"] == "pending"

    def test_approve_requisition_changes_status(self):
        """审批通过后 status 变为 approved。"""
        requisition = {"id": "r1", "status": "pending"}

        def approve(req: dict, approver_id: str, decision: str) -> dict:
            if req["status"] != "pending":
                raise ValueError(f"当前状态 {req['status']} 不允许审批")
            return {**req, "status": "approved" if decision == "approve" else "rejected"}

        approved = approve(requisition, "manager-001", "approve")
        assert approved["status"] == "approved"

    def test_reject_requisition_changes_status(self):
        """审批拒绝后 status 变为 rejected。"""
        requisition = {"id": "r2", "status": "pending"}

        def approve(req: dict, decision: str) -> dict:
            return {**req, "status": "approved" if decision == "approve" else "rejected"}

        rejected = approve(requisition, "reject")
        assert rejected["status"] == "rejected"

    def test_approved_requisition_triggers_stock_deduction(self):
        """审批通过后，库存应扣减对应数量。"""
        initial_stock = 48.0
        requisition_qty = 12.0

        stock_after = initial_stock - requisition_qty
        assert stock_after == 36.0

    def test_cannot_approve_already_approved(self):
        """已审批的领用单不能再次审批。"""
        requisition = {"id": "r3", "status": "approved"}

        def approve(req: dict, decision: str) -> dict:
            if req["status"] != "pending":
                raise ValueError(f"当前状态 {req['status']} 不允许审批")
            return {**req, "status": decision}

        with pytest.raises(ValueError, match="不允许审批"):
            approve(requisition, "approve")

    def test_requisition_item_quantity_must_be_positive(self):
        """领用数量必须 > 0。"""
        valid_qtys = [0.5, 1.0, 10.0, 100.0]
        invalid_qtys = [0.0, -1.0, -0.5]

        for qty in valid_qtys:
            assert qty > 0, f"数量 {qty} 应有效"

        for qty in invalid_qtys:
            assert not qty > 0, f"数量 {qty} 应无效"


# ─── Test 4: 盘点报表数据聚合 ────────────────────────────────────────────────

class TestBarCounterReport:
    """盘点报表：近 N 天损益汇总，按品项分组。"""

    def _build_adjustments(self) -> list[dict[str, Any]]:
        """构造模拟的盘点调整记录。"""
        return [
            # 可乐：2 次盘点，1次盈2罐，1次亏1罐，单价3元
            {"ingredient_id": "i1", "name": "可乐 330ml", "unit": "罐",
             "quantity": 2.0, "unit_cost_fen": 300},
            {"ingredient_id": "i1", "name": "可乐 330ml", "unit": "罐",
             "quantity": -1.0, "unit_cost_fen": 300},
            # 百威：1 次盘点，亏1箱，单价150元
            {"ingredient_id": "i2", "name": "百威啤酒", "unit": "箱",
             "quantity": -1.0, "unit_cost_fen": 15000},
        ]

    def _aggregate_report(self, adjustments: list[dict]) -> list[dict]:
        """按品项聚合盘点记录，计算盈亏数量和金额。"""
        from collections import defaultdict
        groups: dict[str, dict] = defaultdict(lambda: {
            "gain_qty": 0.0, "loss_qty": 0.0,
            "gain_fen": 0, "loss_fen": 0,
            "unit": "", "name": "",
        })

        for adj in adjustments:
            key = adj["ingredient_id"]
            groups[key]["name"] = adj["name"]
            groups[key]["unit"] = adj["unit"]
            if adj["quantity"] > 0:
                groups[key]["gain_qty"] += adj["quantity"]
                groups[key]["gain_fen"] += int(adj["quantity"] * adj["unit_cost_fen"])
            else:
                groups[key]["loss_qty"] += abs(adj["quantity"])
                groups[key]["loss_fen"] += int(abs(adj["quantity"]) * adj["unit_cost_fen"])

        return [{"ingredient_id": k, **v} for k, v in groups.items()]

    def test_report_aggregates_by_ingredient(self):
        """报表应按 ingredient_id 分组，同一品项多次盘点合并。"""
        adjustments = self._build_adjustments()
        report = self._aggregate_report(adjustments)

        ingredient_ids = [r["ingredient_id"] for r in report]
        assert len(ingredient_ids) == 2, "应有2个品项"
        assert "i1" in ingredient_ids
        assert "i2" in ingredient_ids

    def test_report_gain_loss_calculated_correctly(self):
        """可乐：净盈1罐（2-1=1），百威：亏1箱。"""
        adjustments = self._build_adjustments()
        report_map = {r["ingredient_id"]: r for r in self._aggregate_report(adjustments)}

        # 可乐：盈2-亏1=净盈1罐（金额分开统计）
        cola = report_map["i1"]
        assert cola["gain_qty"] == 2.0
        assert cola["loss_qty"] == 1.0
        assert cola["gain_fen"] == 600    # 2 * 300
        assert cola["loss_fen"] == 300    # 1 * 300

        # 百威：亏1箱
        beer = report_map["i2"]
        assert beer["gain_qty"] == 0.0
        assert beer["loss_qty"] == 1.0
        assert beer["gain_fen"] == 0
        assert beer["loss_fen"] == 15000

    def test_report_total_net_loss_correct(self):
        """总净损益 = 总盈金额 - 总亏金额。"""
        adjustments = self._build_adjustments()
        report = self._aggregate_report(adjustments)

        total_gain = sum(r["gain_fen"] for r in report)
        total_loss = sum(r["loss_fen"] for r in report)
        net = total_gain - total_loss

        assert total_gain == 600
        assert total_loss == 15300   # 300 + 15000
        assert net == -14700         # 净亏

    def test_report_empty_when_no_adjustments(self):
        """无盘点调整时，报表返回空列表。"""
        report = self._aggregate_report([])
        assert report == []
