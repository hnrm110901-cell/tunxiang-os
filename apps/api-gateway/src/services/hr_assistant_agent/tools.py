"""
HR Assistant 工具集

每个工具都是一个异步可调用函数 —— 强制以 current_user.employee_id 过滤数据，
禁止跨员工查询。工具失败不抛 stack trace，返回 {"ok": False, "error": "暂时查不到..."}。

权限级别：
  - read:   只读自己数据
  - write:  会创建/修改数据（请假/换班/报名），需要二次确认
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════
# 工具 schema 定义
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToolSchema:
    """工具描述（用于 LLM tool calling）"""

    name: str
    description: str
    parameters: Dict[str, Any]
    permission: str = "read"          # read | write
    requires_confirm: bool = False    # 是否需要二次确认
    handler: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = field(
        default=None, repr=False
    )


# ═══════════════════════════════════════════════════════════════
# 工具 handler 实现（best-effort：依赖的 service 若不存在或失败，统一降级）
# ═══════════════════════════════════════════════════════════════

async def _safe_call(service_path: str, method: str, /, **kwargs) -> Dict[str, Any]:
    """
    通用安全调用器：动态导入 service，调用方法，捕获全部异常。
    若 service 不存在 → 返回"暂时查不到"而不是 stack trace。
    """
    try:
        module = __import__(f"src.services.{service_path}", fromlist=[method])
        fn = getattr(module, method, None)
        if fn is None:
            return {"ok": False, "error": f"暂时查不到（{method} 不可用）"}
        result = await fn(**kwargs)
        return {"ok": True, "data": result}
    except Exception as exc:
        logger.warning("hr_tool.call_failed", service=service_path, method=method, error=str(exc))
        return {"ok": False, "error": "暂时查不到，稍后再试"}


# ── 查询类工具 ──────────────────────────────────────────────────

async def get_my_salary(*, current_user_id: str, pay_month: Optional[str] = None, **_) -> Dict[str, Any]:
    """查我的工资（本月/指定月份）"""
    return await _safe_call(
        "personal_tax_service", "get_payslip",
        employee_id=current_user_id, pay_month=pay_month,
    )


async def get_my_attendance(*, current_user_id: str, date_range: Optional[str] = None, **_) -> Dict[str, Any]:
    """查考勤记录"""
    return await _safe_call(
        "attendance_punch_service", "query_employee_punches",
        employee_id=current_user_id, date_range=date_range or "this_week",
    )


async def get_my_schedule(*, current_user_id: str, week: Optional[str] = None, **_) -> Dict[str, Any]:
    """查排班"""
    return await _safe_call(
        "schedule_query_service", "get_employee_schedule",
        employee_id=current_user_id, week=week or "current",
    )


async def get_my_leave_balance(*, current_user_id: str, **_) -> Dict[str, Any]:
    """查请假余额"""
    return await _safe_call(
        "leave_service", "get_balance",
        employee_id=current_user_id,
    )


async def get_my_health_cert_status(*, current_user_id: str, **_) -> Dict[str, Any]:
    """查健康证状态"""
    return await _safe_call(
        "health_cert_scan_service", "get_employee_cert_status",
        employee_id=current_user_id,
    )


async def get_my_contract_status(*, current_user_id: str, **_) -> Dict[str, Any]:
    """查劳动合同状态"""
    return await _safe_call(
        "labor_contract_alert_service", "get_employee_contract",
        employee_id=current_user_id,
    )


async def get_my_training_progress(*, current_user_id: str, **_) -> Dict[str, Any]:
    """查培训进度"""
    return await _safe_call(
        "training_course_service", "get_employee_progress",
        employee_id=current_user_id,
    )


async def get_my_certificates(*, current_user_id: str, **_) -> Dict[str, Any]:
    """查我已获得的证书"""
    return await _safe_call(
        "exam_service", "list_employee_certificates",
        employee_id=current_user_id,
    )


async def get_my_okr(*, current_user_id: str, period: Optional[str] = None, **_) -> Dict[str, Any]:
    """查 OKR 进度"""
    return await _safe_call(
        "okr_service", "get_employee_okr",
        employee_id=current_user_id, period=period or "current",
    )


async def get_my_points_and_rank(*, current_user_id: str, **_) -> Dict[str, Any]:
    """查积分 + 排名"""
    return await _safe_call(
        "learning_points_service", "get_employee_points_and_rank",
        employee_id=current_user_id,
    )


async def list_available_courses(*, current_user_id: str, **_) -> Dict[str, Any]:
    """列出我可报名的课程"""
    return await _safe_call(
        "training_course_service", "list_available_courses",
        employee_id=current_user_id,
    )


async def get_my_social_insurance(*, current_user_id: str, pay_month: Optional[str] = None, **_) -> Dict[str, Any]:
    """查社保缴纳记录"""
    return await _safe_call(
        "social_insurance_service", "get_employee_records",
        employee_id=current_user_id, pay_month=pay_month,
    )


async def get_hr_contact(*, current_user_id: str, **_) -> Dict[str, Any]:
    """返回人力/店长联系方式"""
    return {
        "ok": True,
        "data": {
            "hr_hotline": "400-xxx-xxxx",
            "store_manager_wechat": "请查看门店公告栏",
            "tip": "紧急事务请直接联系店长",
        },
    }


# ── 写入类工具（需二次确认）─────────────────────────────────────

async def submit_leave_request(
    *, current_user_id: str, start: str, end: str, leave_type: str, reason: str, **_
) -> Dict[str, Any]:
    """提交请假申请"""
    return await _safe_call(
        "leave_service", "create_leave_request",
        employee_id=current_user_id, start=start, end=end,
        leave_type=leave_type, reason=reason,
    )


async def request_shift_swap(
    *, current_user_id: str, target_employee: str, my_shift: str, their_shift: str, **_
) -> Dict[str, Any]:
    """发起换班申请"""
    return await _safe_call(
        "shift_swap_service", "create_swap_request",
        from_employee_id=current_user_id,
        to_employee_id=target_employee,
        my_shift=my_shift, their_shift=their_shift,
    )


async def complete_pulse_survey(*, current_user_id: str, answers: Dict[str, Any], **_) -> Dict[str, Any]:
    """提交脉搏调研"""
    return await _safe_call(
        "pulse_survey_service", "submit_answers",
        employee_id=current_user_id, answers=answers,
    )


async def register_for_course(*, current_user_id: str, course_id: str, **_) -> Dict[str, Any]:
    """报名培训课程"""
    return await _safe_call(
        "training_course_service", "register_course",
        employee_id=current_user_id, course_id=course_id,
    )


async def request_payslip_email(*, current_user_id: str, pay_month: Optional[str] = None, **_) -> Dict[str, Any]:
    """请求发送电子工资条到邮箱"""
    return await _safe_call(
        "personal_tax_service", "send_payslip_email",
        employee_id=current_user_id, pay_month=pay_month,
    )


# ═══════════════════════════════════════════════════════════════
# 注册表
# ═══════════════════════════════════════════════════════════════

TOOL_REGISTRY: Dict[str, ToolSchema] = {
    "get_my_salary": ToolSchema(
        name="get_my_salary",
        description="查询本人工资（支持指定月份，如 '2026-03'）",
        parameters={"pay_month": {"type": "string", "required": False, "desc": "YYYY-MM"}},
        permission="read",
        handler=get_my_salary,
    ),
    "get_my_attendance": ToolSchema(
        name="get_my_attendance",
        description="查询本人考勤记录，支持 today/this_week/this_month",
        parameters={"date_range": {"type": "string", "required": False}},
        permission="read",
        handler=get_my_attendance,
    ),
    "get_my_schedule": ToolSchema(
        name="get_my_schedule",
        description="查询本周/下周排班",
        parameters={"week": {"type": "string", "required": False, "desc": "current/next"}},
        permission="read",
        handler=get_my_schedule,
    ),
    "get_my_leave_balance": ToolSchema(
        name="get_my_leave_balance",
        description="查询剩余请假额度（年假/事假/病假）",
        parameters={},
        permission="read",
        handler=get_my_leave_balance,
    ),
    "get_my_health_cert_status": ToolSchema(
        name="get_my_health_cert_status",
        description="查询健康证有效期",
        parameters={},
        permission="read",
        handler=get_my_health_cert_status,
    ),
    "get_my_contract_status": ToolSchema(
        name="get_my_contract_status",
        description="查询劳动合同到期日",
        parameters={},
        permission="read",
        handler=get_my_contract_status,
    ),
    "get_my_training_progress": ToolSchema(
        name="get_my_training_progress",
        description="查询本人培训进度",
        parameters={},
        permission="read",
        handler=get_my_training_progress,
    ),
    "get_my_certificates": ToolSchema(
        name="get_my_certificates",
        description="列出已获得证书 + 即将过期证书",
        parameters={},
        permission="read",
        handler=get_my_certificates,
    ),
    "get_my_okr": ToolSchema(
        name="get_my_okr",
        description="查询本人 OKR 进度",
        parameters={"period": {"type": "string", "required": False}},
        permission="read",
        handler=get_my_okr,
    ),
    "get_my_points_and_rank": ToolSchema(
        name="get_my_points_and_rank",
        description="查询积分和排行",
        parameters={},
        permission="read",
        handler=get_my_points_and_rank,
    ),
    "list_available_courses": ToolSchema(
        name="list_available_courses",
        description="列出本人可报名的课程",
        parameters={},
        permission="read",
        handler=list_available_courses,
    ),
    "get_my_social_insurance": ToolSchema(
        name="get_my_social_insurance",
        description="查询社保缴纳记录",
        parameters={"pay_month": {"type": "string", "required": False}},
        permission="read",
        handler=get_my_social_insurance,
    ),
    "get_hr_contact": ToolSchema(
        name="get_hr_contact",
        description="获取人力/店长联系方式",
        parameters={},
        permission="read",
        handler=get_hr_contact,
    ),
    # ── 写入类 ──
    "submit_leave_request": ToolSchema(
        name="submit_leave_request",
        description="提交请假申请（需二次确认）",
        parameters={
            "start": {"type": "string", "required": True},
            "end": {"type": "string", "required": True},
            "leave_type": {"type": "string", "required": True, "desc": "annual/sick/personal"},
            "reason": {"type": "string", "required": True},
        },
        permission="write",
        requires_confirm=True,
        handler=submit_leave_request,
    ),
    "request_shift_swap": ToolSchema(
        name="request_shift_swap",
        description="发起换班申请（需二次确认）",
        parameters={
            "target_employee": {"type": "string", "required": True},
            "my_shift": {"type": "string", "required": True},
            "their_shift": {"type": "string", "required": True},
        },
        permission="write",
        requires_confirm=True,
        handler=request_shift_swap,
    ),
    "complete_pulse_survey": ToolSchema(
        name="complete_pulse_survey",
        description="提交脉搏调研答案",
        parameters={"answers": {"type": "object", "required": True}},
        permission="write",
        requires_confirm=False,
        handler=complete_pulse_survey,
    ),
    "register_for_course": ToolSchema(
        name="register_for_course",
        description="报名培训课程（需二次确认）",
        parameters={"course_id": {"type": "string", "required": True}},
        permission="write",
        requires_confirm=True,
        handler=register_for_course,
    ),
    "request_payslip_email": ToolSchema(
        name="request_payslip_email",
        description="请求将电子工资条发送到我的邮箱",
        parameters={"pay_month": {"type": "string", "required": False}},
        permission="write",
        requires_confirm=False,
        handler=request_payslip_email,
    ),
}


def tool_schemas_for_llm() -> List[Dict[str, Any]]:
    """导出供 LLM tool calling 的 schema 列表"""
    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
            "permission": t.permission,
            "requires_confirm": t.requires_confirm,
        }
        for t in TOOL_REGISTRY.values()
    ]


async def invoke_tool(tool_name: str, *, current_user_id: str, **kwargs) -> Dict[str, Any]:
    """
    统一工具调用入口
    - 强制注入 current_user_id（不可覆盖）
    - 捕获所有异常 → 返回 {"ok": False, "error": "..."}
    """
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        return {"ok": False, "error": f"未知工具: {tool_name}"}

    # 权限隔离：current_user_id 强制注入，禁止参数伪造他人 id
    kwargs.pop("current_user_id", None)
    kwargs.pop("employee_id", None)
    try:
        if tool.handler is None:
            return {"ok": False, "error": f"工具 {tool_name} 未实现"}
        return await tool.handler(current_user_id=current_user_id, **kwargs)
    except Exception as exc:
        logger.exception("hr_tool.invoke_failed", tool=tool_name)
        return {"ok": False, "error": "暂时查不到，稍后再试"}
