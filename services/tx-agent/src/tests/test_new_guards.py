"""测试3个守门员 Skill Agent — cashier_audit / stockout_alert / audit_trail

覆盖：
1. 收银稽核 — 单笔稽核、退款异常检测
2. 沽清预警 — 单菜品预测、批量扫描
3. 审计留痕 — 记录决策、查询日志、汇总统计
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from agents.skills.audit_trail import AuditTrailAgent
from agents.skills.cashier_audit import CashierAuditAgent
from agents.skills.stockout_alert import StockoutAlertAgent

TENANT = "test-tenant-001"
STORE = "store-001"


# ══════════════════════════════════════════════
# 收银稽核 Agent
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cashier_audit_detects_unapproved_discount():
    """大额折扣无审批应标记为高风险"""
    agent = CashierAuditAgent(tenant_id=TENANT, store_id=STORE)
    result = await agent.run(
        "audit_transaction",
        {
            "transaction": {
                "txn_id": "TXN-001",
                "cashier_id": "C01",
                "total_amount_fen": 20000,
                "discount_amount_fen": 8000,
                "refund_amount_fen": 0,
                "pending_amount_fen": 0,
                "discount_approved": False,
                "payment_method": "wechat",
                "cost_fen": 6000,
            },
        },
    )
    assert result.success is True
    assert result.data["risk_level"] == "high"
    anomaly_types = [a["type"] for a in result.data["anomalies"]]
    assert "unapproved_large_discount" in anomaly_types
    assert result.confidence > 0
    assert result.reasoning


@pytest.mark.asyncio
async def test_cashier_audit_normal_transaction():
    """正常交易应标记为低风险"""
    agent = CashierAuditAgent(tenant_id=TENANT, store_id=STORE)
    result = await agent.run(
        "audit_transaction",
        {
            "transaction": {
                "txn_id": "TXN-002",
                "cashier_id": "C01",
                "total_amount_fen": 15000,
                "discount_amount_fen": 1000,
                "refund_amount_fen": 0,
                "pending_amount_fen": 0,
                "discount_approved": True,
                "payment_method": "wechat",
                "cost_fen": 5000,
            },
        },
    )
    assert result.success is True
    assert result.data["risk_level"] == "low"
    assert len(result.data["anomalies"]) == 0


@pytest.mark.asyncio
async def test_cashier_refund_anomaly_detection():
    """同一收银员频繁退款应检测为异常"""
    agent = CashierAuditAgent(tenant_id=TENANT, store_id=STORE)
    result = await agent.run(
        "detect_refund_anomaly",
        {
            "cashier_id": "C05",
            "refund_records": [
                {"amount_fen": 3000},
                {"amount_fen": 2500},
                {"amount_fen": 4000},
                {"amount_fen": 1800},
            ],
            "refund_count_threshold": 3,
            "window_minutes": 60,
        },
    )
    assert result.success is True
    assert result.data["risk_level"] in ("medium", "high")
    assert result.data["refund_count"] == 4
    assert len(result.data["anomalies"]) > 0
    assert result.confidence > 0
    assert result.reasoning


# ══════════════════════════════════════════════
# 沽清预警 Agent
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_stockout_predict_critical():
    """库存极低的菜品应标记为 critical"""
    agent = StockoutAlertAgent(tenant_id=TENANT, store_id=STORE)
    result = await agent.run(
        "predict_stockout",
        {
            "dish_name": "剁椒鱼头",
            "current_portions": 1,
            "hourly_sales": [3, 4, 5],
            "alternatives": ["清蒸鲈鱼", "蒜蓉蒸鱼"],
        },
    )
    assert result.success is True
    dishes = result.data["at_risk_dishes"]
    assert len(dishes) == 1
    assert dishes[0]["risk_level"] == "critical"
    assert dishes[0]["remaining_portions"] == 1
    assert result.confidence > 0
    assert result.reasoning


@pytest.mark.asyncio
async def test_stockout_batch_scan():
    """批量扫描应返回所有沽清风险菜品"""
    agent = StockoutAlertAgent(tenant_id=TENANT, store_id=STORE)
    result = await agent.run(
        "batch_scan",
        {
            "dishes": [
                {"name": "剁椒鱼头", "remaining_portions": 2, "hourly_sales": [3, 4, 5]},
                {"name": "宫保鸡丁", "remaining_portions": 50, "hourly_sales": [2, 1, 1]},
                {"name": "麻婆豆腐", "remaining_portions": 4, "hourly_sales": [5, 6, 7]},
            ],
        },
    )
    assert result.success is True
    assert result.data["total_scanned"] == 3
    assert result.data["at_risk_count"] >= 1
    # 剁椒鱼头(2份) 和 麻婆豆腐(4份) 应有风险
    at_risk_names = [d["dish"] for d in result.data["at_risk_dishes"]]
    assert "剁椒鱼头" in at_risk_names
    assert result.confidence > 0


# ══════════════════════════════════════════════
# 审计留痕 Agent
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_audit_log_decision():
    """记录决策应成功并包含完整日志条目"""
    agent = AuditTrailAgent(tenant_id=TENANT, store_id=STORE)
    result = await agent.run(
        "log_decision",
        {
            "agent_id": "discount_guard",
            "decision_type": "detect_discount_anomaly",
            "operator_id": "system",
            "input_context": {"order_id": "ORD-001"},
            "output_action": {"blocked": True},
            "reasoning": "折扣率 75% 超阈值",
            "confidence": 0.95,
            "constraints_check": {"passed": True},
        },
    )
    assert result.success is True
    assert result.data["logged"] is True
    log_entry = result.data["log_entry"]
    assert log_entry["agent_id"] == "discount_guard"
    assert log_entry["tenant_id"] == TENANT
    assert result.confidence > 0
    assert result.reasoning


@pytest.mark.asyncio
async def test_audit_query_logs():
    """按条件查询审计日志应正确过滤"""
    agent = AuditTrailAgent(tenant_id=TENANT, store_id=STORE)
    mock_logs = [
        {
            "agent_id": "discount_guard",
            "decision_type": "detect",
            "operator_id": "sys",
            "created_at": "2026-03-27T10:00:00",
        },
        {
            "agent_id": "cashier_audit",
            "decision_type": "audit",
            "operator_id": "mgr",
            "created_at": "2026-03-27T11:00:00",
        },
        {
            "agent_id": "discount_guard",
            "decision_type": "block",
            "operator_id": "sys",
            "created_at": "2026-03-27T12:00:00",
        },
    ]
    result = await agent.run(
        "query_logs",
        {
            "agent_id": "discount_guard",
            "logs": mock_logs,
        },
    )
    assert result.success is True
    assert result.data["total"] == 2
    assert len(result.data["items"]) == 2
    assert result.confidence > 0


@pytest.mark.asyncio
async def test_audit_summarize():
    """审计汇总应统计各维度数据"""
    agent = AuditTrailAgent(tenant_id=TENANT, store_id=STORE)
    mock_logs = [
        {
            "agent_id": "discount_guard",
            "decision_type": "detect",
            "confidence": 0.9,
            "constraints_check": {"passed": True},
        },
        {
            "agent_id": "cashier_audit",
            "decision_type": "audit",
            "confidence": 0.8,
            "constraints_check": {"passed": False},
        },
        {
            "agent_id": "discount_guard",
            "decision_type": "detect",
            "confidence": 0.95,
            "constraints_check": {"passed": True},
        },
    ]
    result = await agent.run(
        "summarize_audit",
        {
            "logs": mock_logs,
            "period": "2026-03-27",
        },
    )
    assert result.success is True
    data = result.data
    assert data["total_decisions"] == 3
    assert data["by_agent"]["discount_guard"] == 2
    assert data["by_agent"]["cashier_audit"] == 1
    assert data["constraint_violations"] == 1
    assert data["avg_confidence"] > 0
    assert result.confidence > 0
    assert result.reasoning
