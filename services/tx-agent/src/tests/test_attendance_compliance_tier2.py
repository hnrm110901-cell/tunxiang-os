"""Tier 2 测试 — attendance_compliance Agent 6 异常类型

按 #258 / S2-06 issue 验收标准：
  考勤异常 6 大类型（迟到 / 早退 / 旷工 / 超时 / 未休 / 连续无休）

涵盖：
  1. 迟到 late                — 实际打卡 > 排班开始时间
  2. 早退 early_leave         — 实际下班 < 排班结束时间
  3. 旷工 absent              — 排班但无打卡
  4. 超时加班 overtime        — 单日工时 > 法定 + 排班
  5. 未休 missing_holiday_rest — 法定节假日仍排班且未补休
  6. 连续无休 continuous_work  — 连续 > 6 天工作

运行：
  python3.11 -m pytest services/tx-agent/src/tests/test_attendance_compliance_tier2.py -v
"""

from __future__ import annotations

import os
import sys
from datetime import date

import pytest

_SRC_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _SRC_DIR)

from agents.skills.attendance_compliance_agent import AttendanceComplianceAgent  # noqa: E402

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def agent() -> AttendanceComplianceAgent:
    return AttendanceComplianceAgent(tenant_id=TENANT_ID, store_id=STORE_ID)


# ─── 场景 1：迟到 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_late_anomaly(agent):
    """场景 1：员工 09:15 打卡，排班 09:00 → late warning（>10min）"""
    result = await agent.run("analyze_attendance_anomalies", {
        "scan_date": "2026-05-07",
        "records": [
            {"employee_id": "e001", "name": "张伟", "scheduled_start": "09:00",
             "scheduled_end": "18:00", "clock_in": "09:15", "clock_out": "18:00"},
        ],
        "rules": {"late_threshold_min": 10},
    })
    assert result.success
    anomalies = result.data["anomalies"]
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a["type"] == "late"
    assert a["employee_id"] == "e001"
    assert a["severity"] in ("warning", "critical")
    assert a["delay_min"] == 15
    assert "remedy" in a


# ─── 场景 2：早退 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_early_leave_anomaly(agent):
    """场景 2：17:30 打卡下班，排班 18:00 → early_leave warning"""
    result = await agent.run("analyze_attendance_anomalies", {
        "scan_date": "2026-05-07",
        "records": [
            {"employee_id": "e002", "name": "李娜", "scheduled_start": "09:00",
             "scheduled_end": "18:00", "clock_in": "09:00", "clock_out": "17:30"},
        ],
        "rules": {"early_leave_threshold_min": 10},
    })
    assert result.success
    anomalies = result.data["anomalies"]
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a["type"] == "early_leave"
    assert a["short_min"] == 30


# ─── 场景 3：旷工 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_absent_anomaly(agent):
    """场景 3：排班 09-18 但无打卡 → absent critical"""
    result = await agent.run("analyze_attendance_anomalies", {
        "scan_date": "2026-05-07",
        "records": [
            {"employee_id": "e003", "name": "王强", "scheduled_start": "09:00",
             "scheduled_end": "18:00", "clock_in": None, "clock_out": None},
        ],
    })
    assert result.success
    anomalies = result.data["anomalies"]
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a["type"] == "absent"
    assert a["severity"] == "critical"
    assert "HR" in a.get("remedy", "")


# ─── 场景 4：超时加班 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_overtime_anomaly(agent):
    """场景 4：09-23（实际工时 14h）> 排班 9h + 法定加班 3h = 12h 上限"""
    result = await agent.run("analyze_attendance_anomalies", {
        "scan_date": "2026-05-07",
        "records": [
            {"employee_id": "e004", "name": "赵敏", "scheduled_start": "09:00",
             "scheduled_end": "18:00", "clock_in": "09:00", "clock_out": "23:00"},
        ],
        "rules": {"max_overtime_min": 180},
    })
    assert result.success
    anomalies = result.data["anomalies"]
    assert any(a["type"] == "overtime" for a in anomalies)
    overtime = next(a for a in anomalies if a["type"] == "overtime")
    assert overtime["overtime_min"] == 300  # 实际加班 5h - 法定 3h = 2h 超限，但报告值是 5h


# ─── 场景 5：未休法定节假日 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_holiday_rest(agent):
    """场景 5：劳动节 2026-05-01 仍排班 → missing_holiday_rest warning"""
    result = await agent.run("analyze_attendance_anomalies", {
        "scan_date": "2026-05-01",
        "records": [
            {"employee_id": "e005", "name": "陈刚", "scheduled_start": "09:00",
             "scheduled_end": "18:00", "clock_in": "09:00", "clock_out": "18:00"},
        ],
        "holiday_dates": ["2026-05-01", "2026-05-02", "2026-05-03"],
    })
    assert result.success
    anomalies = result.data["anomalies"]
    assert any(a["type"] == "missing_holiday_rest" for a in anomalies)
    h = next(a for a in anomalies if a["type"] == "missing_holiday_rest")
    assert h["holiday_date"] == "2026-05-01"


# ─── 场景 6：连续无休 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_continuous_work_anomaly(agent):
    """场景 6：连续 7 天工作（无休）→ continuous_work critical"""
    # 7 天连续记录
    records = []
    for d in range(1, 8):
        records.append({
            "employee_id": "e006", "name": "刘洋",
            "date": f"2026-05-{d:02d}",
            "scheduled_start": "09:00", "scheduled_end": "18:00",
            "clock_in": "09:00", "clock_out": "18:00",
        })

    result = await agent.run("analyze_attendance_anomalies", {
        "scan_date": "2026-05-07",
        "records": records,
        "rules": {"max_continuous_days": 6},
    })
    assert result.success
    anomalies = result.data["anomalies"]
    assert any(a["type"] == "continuous_work" for a in anomalies)
    cw = next(a for a in anomalies if a["type"] == "continuous_work")
    assert cw["consecutive_days"] >= 7
    assert cw["severity"] == "critical"


# ─── 场景 7：综合 + 决策留痕 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_summary_and_decision_log(agent):
    """场景 7：含多种异常的混合记录，验证 summary + 决策留痕字段完整"""
    result = await agent.run("analyze_attendance_anomalies", {
        "scan_date": "2026-05-07",
        "records": [
            {"employee_id": "e001", "name": "张伟", "scheduled_start": "09:00",
             "scheduled_end": "18:00", "clock_in": "09:30", "clock_out": "18:00"},  # late
            {"employee_id": "e002", "name": "李娜", "scheduled_start": "09:00",
             "scheduled_end": "18:00", "clock_in": None, "clock_out": None},  # absent
        ],
    })
    assert result.success
    summary = result.data["summary"]
    assert summary["total"] == 2
    assert summary["by_severity"]["warning"] >= 1
    assert summary["by_severity"]["critical"] >= 1

    # 决策留痕字段
    assert result.reasoning
    assert isinstance(result.constraints_passed, bool)
    assert 0 <= result.confidence <= 1.0
    assert result.execution_ms >= 0
    assert result.inference_layer in ("edge", "cloud", "edge+cloud")

    # JSON 序列化
    import json
    json.dumps(result.data, ensure_ascii=False, default=str)
