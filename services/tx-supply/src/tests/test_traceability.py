"""原料追溯服务测试 -- 正向追溯 / 反向追溯 / 时间线 / 报告 / 关系图"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.traceability import (
    TraceDirection,
    TraceNodeType,
    _clear_store,
    build_ingredient_graph,
    full_trace_backward,
    full_trace_forward,
    generate_trace_report,
    get_trace_timeline,
    inject_batch,
    inject_batch_transaction,
    inject_bom_link,
    inject_ingredient_alternative,
    inject_ingredient_supplier,
    inject_order_customer,
    inject_order_dish,
)

TENANT = "tenant-trace-001"
BATCH_NO = "BATCH-2026-001"
INGREDIENT_ID = "ing-pork-001"
DISH_ID = "dish-hongshaorou"
ORDER_ID = "order-20260327-001"
CUSTOMER_ID = "cust-zhang-001"
STORE_ID = "store-changsha-001"


def _setup_full_chain():
    """注入完整追溯链数据：供应商 -> 入库 -> 领用 -> BOM -> 菜品 -> 订单 -> 客户"""
    inject_batch(BATCH_NO, TENANT, {
        "supplier_id": "sup-001",
        "supplier_name": "湖南优质猪肉供应商",
        "ingredient_id": INGREDIENT_ID,
        "ingredient_name": "五花肉",
        "quantity": 50.0,
        "unit": "kg",
        "received_at": "2026-03-25T08:00:00+08:00",
        "received_by": "验收员张三",
        "store_id": STORE_ID,
        "expiry_date": "2026-03-30",
    })
    inject_batch_transaction(BATCH_NO, TENANT, {
        "node_type": TraceNodeType.storage.value,
        "action": "入库冷藏 (2C)",
        "operator": "仓管李四",
        "location": "冷藏库A区",
        "quantity": 50.0,
        "timestamp": "2026-03-25T08:30:00+08:00",
    })
    inject_batch_transaction(BATCH_NO, TENANT, {
        "node_type": TraceNodeType.requisition.value,
        "action": "厨房领用 5kg",
        "operator": "厨师王五",
        "location": "热菜档口",
        "quantity": 5.0,
        "timestamp": "2026-03-26T10:00:00+08:00",
    })
    inject_bom_link(INGREDIENT_ID, TENANT, DISH_ID)
    inject_order_dish(ORDER_ID, TENANT, {
        "dish_id": DISH_ID,
        "dish_name": "红烧肉",
        "batch_nos": [BATCH_NO],
    })
    inject_order_customer(ORDER_ID, TENANT, {
        "customer_id": CUSTOMER_ID,
        "customer_name": "张先生",
        "phone": "138****1234",
    })


class TestFullTraceForward:
    def setup_method(self):
        _clear_store()
        _setup_full_chain()

    def test_forward_trace_complete_chain(self):
        result = full_trace_forward(BATCH_NO, TENANT)
        assert result["direction"] == TraceDirection.forward.value
        assert result["complete"] is True
        # 链条节点类型包含完整链路
        node_types = [n["node_type"] for n in result["chain"]]
        assert TraceNodeType.supplier.value in node_types
        assert TraceNodeType.receiving.value in node_types
        assert TraceNodeType.dish.value in node_types
        assert TraceNodeType.order.value in node_types
        assert TraceNodeType.customer.value in node_types

    def test_forward_trace_affected_entities(self):
        result = full_trace_forward(BATCH_NO, TENANT)
        assert DISH_ID in result["affected_dishes"]
        assert ORDER_ID in result["affected_orders"]
        assert CUSTOMER_ID in result["affected_customers"]

    def test_forward_trace_batch_not_found(self):
        result = full_trace_forward("NONEXISTENT", TENANT)
        assert result["complete"] is False
        assert result["chain"] == []

    def test_forward_trace_supplier_info(self):
        result = full_trace_forward(BATCH_NO, TENANT)
        supplier_node = next(
            n for n in result["chain"] if n["node_type"] == TraceNodeType.supplier.value
        )
        assert supplier_node["supplier_name"] == "湖南优质猪肉供应商"

    def test_tenant_isolation(self):
        result = full_trace_forward(BATCH_NO, "other-tenant")
        assert result["complete"] is False


class TestFullTraceBackward:
    def setup_method(self):
        _clear_store()
        _setup_full_chain()

    def test_backward_trace_complete(self):
        result = full_trace_backward(ORDER_ID, DISH_ID, TENANT)
        assert result["direction"] == TraceDirection.backward.value
        assert result["complete"] is True
        assert BATCH_NO in result["source_batches"]
        assert "sup-001" in result["source_suppliers"]

    def test_backward_trace_chain_nodes(self):
        result = full_trace_backward(ORDER_ID, DISH_ID, TENANT)
        node_types = [n["node_type"] for n in result["chain"]]
        assert TraceNodeType.customer.value in node_types
        assert TraceNodeType.order.value in node_types
        assert TraceNodeType.supplier.value in node_types

    def test_backward_trace_no_batch(self):
        inject_order_dish("order-empty", TENANT, {
            "dish_id": "dish-x",
            "dish_name": "测试菜",
            "batch_nos": [],
        })
        result = full_trace_backward("order-empty", "dish-x", TENANT)
        assert result["complete"] is False
        assert result["source_batches"] == []

    def test_backward_includes_customer(self):
        result = full_trace_backward(ORDER_ID, DISH_ID, TENANT)
        customer_nodes = [
            n for n in result["chain"] if n["node_type"] == TraceNodeType.customer.value
        ]
        assert len(customer_nodes) >= 1
        assert customer_nodes[0]["customer_id"] == CUSTOMER_ID

    def test_tenant_id_required(self):
        try:
            full_trace_backward(ORDER_ID, DISH_ID, "")
            assert False, "应该抛出 ValueError"
        except ValueError:
            pass


class TestGetTraceTimeline:
    def setup_method(self):
        _clear_store()
        _setup_full_chain()

    def test_timeline_ordered(self):
        result = get_trace_timeline(BATCH_NO, TENANT)
        assert result["total_nodes"] >= 3
        timestamps = [n["timestamp"] for n in result["timeline"] if n.get("timestamp")]
        assert timestamps == sorted(timestamps)

    def test_timeline_duration(self):
        result = get_trace_timeline(BATCH_NO, TENANT)
        assert result["duration_hours"] is not None
        assert result["duration_hours"] > 0

    def test_timeline_not_found(self):
        result = get_trace_timeline("NONEXISTENT", TENANT)
        assert result["total_nodes"] == 0
        assert result["duration_hours"] is None

    def test_timeline_operators(self):
        result = get_trace_timeline(BATCH_NO, TENANT)
        operators = [n.get("operator") for n in result["timeline"] if n.get("operator")]
        assert "验收员张三" in operators
        assert "仓管李四" in operators

    def test_timeline_locations(self):
        result = get_trace_timeline(BATCH_NO, TENANT)
        locations = [n.get("location") for n in result["timeline"] if n.get("location")]
        assert any("冷藏" in loc for loc in locations)


class TestGenerateTraceReport:
    def setup_method(self):
        _clear_store()
        _setup_full_chain()

    def test_report_structure(self):
        result = generate_trace_report(BATCH_NO, TENANT)
        assert "report_id" in result
        assert "batch_no" in result
        assert "generated_at" in result
        assert "forward_trace" in result
        assert "timeline" in result
        assert "risk_assessment" in result
        assert "recommendations" in result

    def test_report_risk_assessment(self):
        result = generate_trace_report(BATCH_NO, TENANT)
        risk = result["risk_assessment"]
        assert risk["affected_customers_count"] >= 1
        assert risk["risk_level"] in ("low", "medium", "high")
        assert risk["trace_complete"] is True

    def test_report_recommendations_not_empty(self):
        result = generate_trace_report(BATCH_NO, TENANT)
        assert len(result["recommendations"]) >= 2

    def test_report_for_missing_batch(self):
        result = generate_trace_report("MISSING", TENANT)
        assert result["risk_assessment"]["affected_customers_count"] == 0
        assert result["risk_assessment"]["risk_level"] == "low"

    def test_report_includes_timeline(self):
        result = generate_trace_report(BATCH_NO, TENANT)
        assert result["timeline"]["total_nodes"] >= 1


class TestBuildIngredientGraph:
    def setup_method(self):
        _clear_store()
        inject_bom_link(INGREDIENT_ID, TENANT, DISH_ID)
        inject_bom_link(INGREDIENT_ID, TENANT, "dish-meatball")
        inject_ingredient_supplier(INGREDIENT_ID, TENANT, {
            "supplier_id": "sup-001",
            "supplier_name": "供应商A",
            "contact": "138xxxx",
            "lead_time_days": 2,
        })
        inject_ingredient_alternative(INGREDIENT_ID, TENANT, "ing-alt-001")

    def test_graph_dishes(self):
        result = build_ingredient_graph(INGREDIENT_ID, TENANT)
        assert DISH_ID in result["bom_dishes"]
        assert "dish-meatball" in result["bom_dishes"]

    def test_graph_suppliers(self):
        result = build_ingredient_graph(INGREDIENT_ID, TENANT)
        assert len(result["suppliers"]) >= 1
        assert result["suppliers"][0]["supplier_name"] == "供应商A"

    def test_graph_alternatives(self):
        result = build_ingredient_graph(INGREDIENT_ID, TENANT)
        assert "ing-alt-001" in result["alternatives"]

    def test_graph_nodes_and_edges(self):
        result = build_ingredient_graph(INGREDIENT_ID, TENANT)
        node_types = [n["type"] for n in result["graph_nodes"]]
        assert "ingredient" in node_types
        assert "dish" in node_types
        assert "supplier" in node_types
        assert "alternative" in node_types
        assert len(result["graph_edges"]) >= 4

    def test_empty_graph(self):
        result = build_ingredient_graph("ing-unknown", TENANT)
        assert result["bom_dishes"] == []
        assert result["suppliers"] == []
        assert result["alternatives"] == []
