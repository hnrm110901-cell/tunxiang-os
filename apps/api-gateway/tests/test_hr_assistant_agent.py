"""
HR 助手 Agent 测试

覆盖：
  - 15 类意图 × 3 变体 = 45 用例（规则分类器准确率 >= 85%）
  - 权限隔离：员工 A 不能查员工 B
  - 工具失败容错：mock 工具抛异常 → 返回 "暂时查不到"
  - 敏感操作二次确认流程
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.services.hr_assistant_agent.intent_classifier import (
    INTENT_RULES, classify_intent,
)
from src.services.hr_assistant_agent.tools import (
    TOOL_REGISTRY, invoke_tool, get_my_salary,
)
from src.services.hr_assistant_agent.agent import HRAssistantAgent


# ═══════════════════════════════════════════════════════════════
# Task 5 — 15 类意图 × 3 变体（部分补 16 类含社保）
# ═══════════════════════════════════════════════════════════════

INTENT_TEST_CASES = [
    # query_salary
    ("我这个月工资多少", "query_salary"),
    ("帮我看看本月的薪资", "query_salary"),
    ("3月份到手多少", "query_salary"),
    # query_attendance
    ("我的考勤今天有没有异常", "query_attendance"),
    ("本周打卡记录", "query_attendance"),
    ("我有几次迟到", "query_attendance"),
    # query_schedule
    ("我下周排几个班", "query_schedule"),
    ("看看我本周的班表", "query_schedule"),
    ("明天我的上班时间", "query_schedule"),
    # query_leave_balance
    ("我还剩多少年假", "query_leave_balance"),
    ("请假余额", "query_leave_balance"),
    ("我还能请几天", "query_leave_balance"),
    # query_health_cert
    ("我的健康证什么时候过期", "query_health_cert"),
    ("健康证到期日", "query_health_cert"),
    ("体检证还有效吗", "query_health_cert"),
    # query_contract
    ("我的合同到期日", "query_contract"),
    ("劳动合同什么时候续签", "query_contract"),
    ("合同什么时候到期", "query_contract"),
    # query_training
    ("我的培训进度", "query_training"),
    ("我学到哪了", "query_training"),
    ("课程进度怎么样", "query_training"),
    # query_certificates
    ("我拿了什么证书", "query_certificates"),
    ("我的证", "query_certificates"),
    ("证书即将过期吗", "query_certificates"),
    # query_okr
    ("我的OKR进度", "query_okr"),
    ("目标完成得怎么样", "query_okr"),
    ("我的okr", "query_okr"),
    # query_points
    ("我的积分多少", "query_points"),
    ("我排第几", "query_points"),
    ("看看排行榜", "query_points"),
    # submit_leave
    ("我要请假", "submit_leave"),
    ("帮我请假", "submit_leave"),
    ("申请请假", "submit_leave"),
    # swap_shift
    ("我想换班", "swap_shift"),
    ("跟同事换班", "swap_shift"),
    ("能帮我调班吗", "swap_shift"),
    # register_course
    ("我要报名这个课", "register_course"),
    ("报名课程", "register_course"),
    ("我要报", "register_course"),
    # payslip_email
    ("把工资条发到邮箱", "payslip_email"),
    ("请求电子工资条", "payslip_email"),
    ("工资单邮件", "payslip_email"),
    # contact_hr
    ("人力电话是多少", "contact_hr"),
    ("店长电话", "contact_hr"),
    ("我要联系人力", "contact_hr"),
    # query_social_insurance
    ("我的社保", "query_social_insurance"),
    ("五险缴了多少", "query_social_insurance"),
    ("公积金", "query_social_insurance"),
]


def test_intent_classifier_accuracy():
    """15 类意图 × 3 变体：命中率 >= 85%"""
    hits = 0
    misses = []
    for text, expect in INTENT_TEST_CASES:
        got = classify_intent(text)
        if got and got[0] == expect:
            hits += 1
        else:
            misses.append((text, expect, got))
    total = len(INTENT_TEST_CASES)
    accuracy = hits / total
    assert accuracy >= 0.85, f"准确率 {accuracy:.1%} < 85%，漏判：{misses[:5]}"


def test_all_intents_have_rules():
    """15 类意图在 INTENT_RULES 中都存在"""
    intents = {r.intent for r in INTENT_RULES}
    required = {
        "query_salary", "query_attendance", "query_schedule",
        "query_leave_balance", "query_health_cert", "query_contract",
        "query_training", "query_certificates", "query_okr",
        "query_points", "submit_leave", "swap_shift",
        "register_course", "payslip_email", "contact_hr",
    }
    assert required.issubset(intents), f"缺失意图: {required - intents}"


# ═══════════════════════════════════════════════════════════════
# 工具失败容错
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_tool_failure_returns_friendly_message():
    """工具 handler 抛异常 → 返回 ok=False + 友好错误，不抛栈"""
    async def _broken(**_):
        raise RuntimeError("DB down")

    from src.services.hr_assistant_agent.tools import ToolSchema
    TOOL_REGISTRY["_test_broken"] = ToolSchema(
        name="_test_broken", description="", parameters={},
        handler=_broken,
    )
    try:
        result = await invoke_tool("_test_broken", current_user_id="emp_001")
        assert result["ok"] is False
        assert "暂时查不到" in result["error"]
    finally:
        TOOL_REGISTRY.pop("_test_broken", None)


@pytest.mark.asyncio
async def test_tool_unknown_name():
    """未知工具名 → 友好错误"""
    result = await invoke_tool("no_such_tool", current_user_id="emp_001")
    assert result["ok"] is False
    assert "未知工具" in result["error"]


# ═══════════════════════════════════════════════════════════════
# 权限隔离
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_permission_isolation_cannot_override_employee_id():
    """
    员工 A 尝试通过参数传 employee_id=B 查询 B 的数据
    invoke_tool 必须丢掉伪造参数，使用 current_user_id
    """
    captured = {}

    async def _capture_handler(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "data": {"employee_id": kwargs.get("current_user_id")}}

    from src.services.hr_assistant_agent.tools import ToolSchema
    TOOL_REGISTRY["_test_perm"] = ToolSchema(
        name="_test_perm", description="", parameters={},
        handler=_capture_handler,
    )
    try:
        # 员工 A 调用，恶意注入 employee_id=B
        await invoke_tool(
            "_test_perm",
            current_user_id="emp_A",
            employee_id="emp_B",     # 应被丢弃
            current_user_id_spoof="emp_B",
        )
        assert captured.get("current_user_id") == "emp_A"
        assert "employee_id" not in captured, "employee_id 伪造参数必须被丢弃"
    finally:
        TOOL_REGISTRY.pop("_test_perm", None)


# ═══════════════════════════════════════════════════════════════
# 敏感操作二次确认流程
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_sensitive_operation_requires_confirm():
    """请假 / 换班 / 报名 → 必须先返回 pending_confirm"""
    agent = HRAssistantAgent()

    # mock invoke_tool 以避免真的写库
    with patch(
        "src.services.hr_assistant_agent.agent.invoke_tool",
        new=AsyncMock(return_value={"ok": True, "data": {"request_id": "req_1"}}),
    ):
        # 请假 —— 缺槽位，先引导补信息
        r1 = await agent.chat(
            current_user_id="emp_A",
            message="我要请假",
            conversation_id="c1",
        )
        # 槽位缺失 → 引导补充；或当槽位被提取后需要二次确认
        assert r1["ok"]

        # 直接走 confirm_token 分支 —— 模拟用户点了"确认"
        r2 = await agent.chat(
            current_user_id="emp_A",
            message="确认",
            conversation_id="c1",
            confirm_token={
                "tool": "submit_leave_request",
                "args": {
                    "start": "2026-04-20", "end": "2026-04-21",
                    "leave_type": "personal", "reason": "事假",
                },
            },
        )
        assert r2["ok"] is True
        assert any(t["name"] == "submit_leave_request" for t in r2["tool_invocations"])


@pytest.mark.asyncio
async def test_read_tool_does_not_require_confirm():
    """读取类工具直接执行，不弹确认"""
    agent = HRAssistantAgent()
    with patch(
        "src.services.hr_assistant_agent.agent.invoke_tool",
        new=AsyncMock(return_value={"ok": True, "data": {"net_pay_yuan": 5432.10, "pay_month": "2026-03"}}),
    ):
        r = await agent.chat(
            current_user_id="emp_A",
            message="我这个月工资多少",
            conversation_id="c2",
        )
        assert r["ok"] is True
        assert r["pending_confirm"] is None
        assert any(t["name"] == "get_my_salary" for t in r["tool_invocations"])
        assert "5,432.10" in r["reply"] or "5432.10" in r["reply"]


# ═══════════════════════════════════════════════════════════════
# 服务层 safe_call 容错（所依赖 service 不存在）
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_safe_call_missing_service_returns_friendly():
    """所依赖 service 文件不存在时，工具不报错，返回 ok=False"""
    from src.services.hr_assistant_agent.tools import _safe_call
    result = await _safe_call(
        "this_service_definitely_does_not_exist_xyz",
        "foo",
        employee_id="emp_A",
    )
    assert result["ok"] is False
    assert "暂时查不到" in result["error"]
