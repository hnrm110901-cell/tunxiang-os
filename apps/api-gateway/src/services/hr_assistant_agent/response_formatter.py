"""
把工具返回结果格式化成自然语言回答
—— 金额保留 2 位小数 + 元单位；大额数字加提醒
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# 大额阈值（元），超过则额外提醒
LARGE_AMOUNT_YUAN = 10000


def _format_yuan(value: Any) -> str:
    """格式化为 'X,XXX.XX 元'"""
    try:
        v = float(value)
        return f"{v:,.2f} 元"
    except Exception:
        return str(value)


def format_salary(data: Dict[str, Any]) -> str:
    """工资"""
    net = data.get("net_pay_yuan") or data.get("net_pay") or 0
    month = data.get("pay_month", "本月")
    line = f"您 {month} 的实发工资：{_format_yuan(net)}"
    if float(net or 0) >= LARGE_AMOUNT_YUAN:
        line += "（大额金额，请留意）"
    return line


def format_attendance(data: Dict[str, Any]) -> str:
    """考勤"""
    total = data.get("total_days", "-")
    abnormal = data.get("abnormal_count", 0)
    late = data.get("late_count", 0)
    return f"考勤周期内共 {total} 天，异常 {abnormal} 次（迟到 {late} 次）"


def format_schedule(data: Dict[str, Any]) -> str:
    """排班"""
    shifts = data.get("shifts", []) or []
    if not shifts:
        return "该周暂无排班记录"
    lines = [f"- {s.get('date')} {s.get('shift_name', '')}" for s in shifts[:10]]
    return "排班如下：\n" + "\n".join(lines)


def format_leave_balance(data: Dict[str, Any]) -> str:
    annual = data.get("annual", 0)
    sick = data.get("sick", 0)
    personal = data.get("personal", 0)
    return f"剩余年假 {annual} 天 / 病假 {sick} 天 / 事假 {personal} 天"


def format_health_cert(data: Dict[str, Any]) -> str:
    expire = data.get("expires_on") or data.get("expire_date") or "未知"
    days_left = data.get("days_left")
    line = f"健康证到期日：{expire}"
    if days_left is not None:
        line += f"（剩余 {days_left} 天）"
    return line


def format_contract(data: Dict[str, Any]) -> str:
    expire = data.get("expires_on") or data.get("end_date") or "未知"
    return f"劳动合同到期日：{expire}"


def format_training(data: Dict[str, Any]) -> str:
    completed = data.get("completed_count", 0)
    total = data.get("total_count", 0)
    return f"培训进度：{completed}/{total} 门已完成"


def format_certificates(data: Dict[str, Any]) -> str:
    owned = data.get("owned", [])
    expiring = data.get("expiring_soon", [])
    lines = [f"已获得 {len(owned)} 个证书"]
    if expiring:
        lines.append(f"即将过期：{', '.join(e.get('name', '') for e in expiring[:3])}")
    return "\n".join(lines)


def format_okr(data: Dict[str, Any]) -> str:
    progress = data.get("overall_progress", 0)
    return f"当前 OKR 完成度：{progress}%"


def format_points(data: Dict[str, Any]) -> str:
    points = data.get("points", 0)
    rank = data.get("rank", "-")
    return f"您当前 {points} 积分，排名第 {rank}"


def format_courses(data: Dict[str, Any]) -> str:
    courses = data.get("courses", []) or []
    if not courses:
        return "暂无可报名课程"
    lines = [f"- {c.get('title')}（{c.get('duration', '')}）" for c in courses[:5]]
    return "可报名课程：\n" + "\n".join(lines)


def format_social_insurance(data: Dict[str, Any]) -> str:
    personal = data.get("personal_contribution_yuan", 0)
    company = data.get("company_contribution_yuan", 0)
    month = data.get("pay_month", "本月")
    return f"{month} 社保：个人缴 {_format_yuan(personal)}，公司缴 {_format_yuan(company)}"


def format_contact(data: Dict[str, Any]) -> str:
    return (
        f"人力服务专线：{data.get('hr_hotline', '-')}\n"
        f"店长：{data.get('store_manager_wechat', '-')}\n"
        f"{data.get('tip', '')}"
    )


FORMATTERS = {
    "get_my_salary": format_salary,
    "get_my_attendance": format_attendance,
    "get_my_schedule": format_schedule,
    "get_my_leave_balance": format_leave_balance,
    "get_my_health_cert_status": format_health_cert,
    "get_my_contract_status": format_contract,
    "get_my_training_progress": format_training,
    "get_my_certificates": format_certificates,
    "get_my_okr": format_okr,
    "get_my_points_and_rank": format_points,
    "list_available_courses": format_courses,
    "get_my_social_insurance": format_social_insurance,
    "get_hr_contact": format_contact,
}


def format_tool_result(tool_name: str, result: Dict[str, Any]) -> str:
    """统一工具结果格式化入口"""
    if not result.get("ok"):
        return result.get("error") or "暂时查不到，稍后再试"

    data = result.get("data") or {}
    if not isinstance(data, dict):
        return str(data)

    fn = FORMATTERS.get(tool_name)
    if fn is None:
        # 写入类工具 / 未定义 → 通用提示
        if data.get("success") or data.get("request_id"):
            return "操作已提交，稍后可在系统内查看进度。"
        return "已处理"
    try:
        return fn(data)
    except Exception:
        return "数据已取到，但展示时出了点小问题，请稍后重试"


def confirm_prompt(tool_name: str, args: Dict[str, Any]) -> str:
    """为需二次确认的写入类操作生成确认提示"""
    if tool_name == "submit_leave_request":
        return (
            f"请确认请假申请：\n"
            f"- 类型：{args.get('leave_type')}\n"
            f"- 时间：{args.get('start')} 至 {args.get('end')}\n"
            f"- 事由：{args.get('reason')}\n"
            "点击「确认」提交。"
        )
    if tool_name == "request_shift_swap":
        return (
            f"请确认换班：您的 {args.get('my_shift')} ↔ "
            f"{args.get('target_employee')} 的 {args.get('their_shift')}"
        )
    if tool_name == "register_for_course":
        return f"请确认报名课程 {args.get('course_id')}？"
    return "请二次确认后执行"
