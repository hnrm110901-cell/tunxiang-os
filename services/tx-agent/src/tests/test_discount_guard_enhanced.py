"""
P3-01 折扣守护Agent增强 — 测试用例
覆盖：
  1. test_member_frequency_detection       — 高频会员查询（列表非空、含风险等级、high在前）
  2. test_realtime_member_check_suspicious — 实时检查第5次折扣 → is_suspicious=True
  3. test_realtime_member_check_normal     — 首次折扣 → is_suspicious=False, risk_level=low
  4. test_table_pattern_anomaly            — A8桌连续5天 → anomaly_score>0.7，员工列表非空
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from api.discount_guard_enhanced_routes import router

# ─── 测试 App 独立实例（不依赖完整 tx-agent main.py）────────────────────────

_test_app = FastAPI()
_test_app.include_router(router)

client = TestClient(_test_app, raise_server_exceptions=True)

TENANT_ID = "test-tenant-001"
BASE_HEADERS = {"X-Tenant-ID": TENANT_ID}


# ══════════════════════════════════════════════════════════════════
# 1. 高频会员查询
# ══════════════════════════════════════════════════════════════════

def test_member_frequency_detection():
    """
    GET /member-frequency 应返回：
    - ok=True
    - high_frequency_members 非空列表
    - 每条记录含 risk_level 字段
    - high 风险记录排在 medium/low 之前
    - summary 包含 total_suspicious 和 total_amount_saved_fen
    """
    resp = client.get(
        "/api/v1/agent/discount-guard/member-frequency",
        params={"tenant_id": TENANT_ID, "days": 30, "threshold": 3},
        headers=BASE_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["ok"] is True
    data = body["data"]

    members = data["high_frequency_members"]
    assert isinstance(members, list), "high_frequency_members 应为列表"
    assert len(members) > 0, "高频会员列表不应为空"

    # 每条记录含 risk_level
    for m in members:
        assert "risk_level" in m, f"记录缺少 risk_level: {m}"
        assert m["risk_level"] in ("low", "medium", "high")
        assert "member_id" in m
        assert "discount_count" in m
        assert "total_saved_fen" in m

    # high 风险在 medium/low 前面
    _ORDER = {"high": 0, "medium": 1, "low": 2}
    levels = [_ORDER[m["risk_level"]] for m in members]
    assert levels == sorted(levels), "风险等级应按 high > medium > low 排序"

    # 汇总字段
    summary = data["summary"]
    assert "total_suspicious" in summary
    assert "total_amount_saved_fen" in summary
    assert summary["total_suspicious"] == len(members)
    assert summary["total_amount_saved_fen"] >= 0


# ══════════════════════════════════════════════════════════════════
# 2. 实时检查：可疑（第5次折扣）
# ══════════════════════════════════════════════════════════════════

def test_realtime_member_check_suspicious():
    """
    POST /member-frequency/check — 已知高频会员(mem-vip-001，历史7次)
    阈值=3，第8次时应：
      - is_suspicious=True
      - risk_level=high
      - recommendation 包含"审批"或"拒绝"
      - reason 包含"超出品牌阈值"
    """
    payload = {
        "member_id": "mem-vip-001",
        "order_id": "ORD-TEST-999",
        "discount_type": "vip_discount",
        "discount_amount_fen": 8000,
    }
    resp = client.post(
        "/api/v1/agent/discount-guard/member-frequency/check",
        json=payload,
        params={"tenant_id": TENANT_ID, "days": 30, "threshold": 3},
        headers=BASE_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["ok"] is True
    data = body["data"]

    assert data["is_suspicious"] is True, "高频VIP会员应被标记为可疑"
    assert data["risk_level"] == "high", f"期望 high，实际 {data['risk_level']}"

    # recommendation 包含"审批"或"拒绝"（二选一均可）
    recommendation: str = data["recommendation"]
    assert "审批" in recommendation or "拒绝" in recommendation, (
        f"recommendation 应包含'审批'或'拒绝'，实际：{recommendation}"
    )

    # reason 说明超出阈值
    reason: str = data["reason"]
    assert "超出品牌阈值" in reason, f"reason 应包含'超出品牌阈值'，实际：{reason}"

    # 业务字段完整性
    assert "frequency_in_window" in data
    assert "decision_id" in data
    assert "checked_at" in data


# ══════════════════════════════════════════════════════════════════
# 3. 实时检查：首次折扣（正常）
# ══════════════════════════════════════════════════════════════════

def test_realtime_member_check_normal():
    """
    POST /member-frequency/check — 全新会员（历史无记录）
    首次折扣应：
      - is_suspicious=False
      - risk_level=low
      - frequency_in_window=1
      - recommendation="正常放行"
    """
    payload = {
        "member_id": "mem-brand-new-xyz",   # 在 Mock 数据中不存在
        "order_id": "ORD-FIRST-001",
        "discount_type": "birthday_discount",
        "discount_amount_fen": 3000,
    }
    resp = client.post(
        "/api/v1/agent/discount-guard/member-frequency/check",
        json=payload,
        params={"tenant_id": TENANT_ID, "days": 30, "threshold": 3},
        headers=BASE_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["ok"] is True
    data = body["data"]

    assert data["is_suspicious"] is False, "首次折扣不应被标记为可疑"
    assert data["risk_level"] == "low", f"首次折扣应为 low，实际 {data['risk_level']}"
    assert data["frequency_in_window"] == 1, "首次折扣频率应为1"
    assert data["recommendation"] == "正常放行", (
        f"首次折扣应建议正常放行，实际：{data['recommendation']}"
    )


# ══════════════════════════════════════════════════════════════════
# 4. 桌台异常模式分析：A8桌
# ══════════════════════════════════════════════════════════════════

def test_table_pattern_anomaly():
    """
    POST /table-pattern/analyze — A8桌（连续5天折扣，赵服务员操作6次）
    应：
      - is_pattern_match=True
      - consecutive_discount_days >= 3
      - anomaly_score > 0.7
      - related_employees 非空
      - alert_level in (warning, critical)
      - alert_message 非空
    """
    payload = {
        "table_id": "table-A8",
        "order_id": "ORD-A8-TODAY",
        "employee_id": "emp-011",        # 赵服务员
        "discount_amount_fen": 15000,
    }
    resp = client.post(
        "/api/v1/agent/discount-guard/table-pattern/analyze",
        json=payload,
        params={"tenant_id": TENANT_ID},
        headers=BASE_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["ok"] is True
    data = body["data"]

    assert data["is_pattern_match"] is True, "A8桌连续5天折扣应匹配异常模式"
    assert data["consecutive_discount_days"] >= 3, (
        f"连续折扣天数应 >= 3，实际 {data['consecutive_discount_days']}"
    )
    assert data["anomaly_score"] > 0.7, (
        f"A8桌异常评分应 > 0.7，实际 {data['anomaly_score']}"
    )

    employees = data["related_employees"]
    assert isinstance(employees, list), "related_employees 应为列表"
    assert len(employees) > 0, "应有关联员工记录"

    # 员工记录格式检查
    for emp in employees:
        assert "employee_id" in emp
        assert "discount_count" in emp

    assert data["alert_level"] in ("warning", "critical"), (
        f"alert_level 应为 warning 或 critical，实际 {data['alert_level']}"
    )
    assert data["alert_message"], "alert_message 不应为空"

    # 业务字段完整性
    assert "decision_id" in data
    assert "analyzed_at" in data


# ══════════════════════════════════════════════════════════════════
# 5. 补充：GET /table-pattern 基础验证
# ══════════════════════════════════════════════════════════════════

def test_table_pattern_list():
    """
    GET /table-pattern 应返回 ok=True，suspicious_tables 非空，
    按 anomaly_score 降序，包含 pattern_analysis 字段。
    """
    resp = client.get(
        "/api/v1/agent/discount-guard/table-pattern",
        params={"tenant_id": TENANT_ID, "days": 7, "min_consecutive": 2},
        headers=BASE_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True

    data = body["data"]
    tables = data["suspicious_tables"]
    assert len(tables) > 0

    # 按 anomaly_score 降序
    scores = [t["anomaly_score"] for t in tables]
    assert scores == sorted(scores, reverse=True), "桌台应按异常评分降序"

    assert "pattern_analysis" in data
    assert "suspicious_rate" in data["pattern_analysis"]


# ══════════════════════════════════════════════════════════════════
# 6. 补充：GET /summary 基础验证
# ══════════════════════════════════════════════════════════════════

def test_summary_endpoint():
    """
    GET /summary 应返回 ok=True，包含 today/this_week/this_month 三个周期，
    以及 top3 员工和桌台。
    """
    resp = client.get(
        "/api/v1/agent/discount-guard/summary",
        params={"tenant_id": TENANT_ID},
        headers=BASE_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True

    data = body["data"]
    for period in ("today", "this_week", "this_month"):
        assert period in data, f"summary 应包含 {period} 字段"
        assert "checks" in data[period]
        assert "alerts" in data[period]

    assert "top3_risky_employees" in data
    assert "top3_risky_tables" in data
    assert isinstance(data["top3_risky_employees"], list)
    assert isinstance(data["top3_risky_tables"], list)
