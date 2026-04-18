"""
意图识别器 —— 关键词规则优先，规则 miss 时 LLM 兜底

15 类意图：
  1  query_salary        查工资
  2  query_attendance    查考勤
  3  query_schedule      查排班
  4  query_leave_balance 查请假余额
  5  query_health_cert   查健康证
  6  query_contract      查合同到期
  7  query_training      查培训进度
  8  query_certificates  查证书
  9  query_okr           查 OKR
  10 query_points        查积分/排行
  11 submit_leave        申请请假
  12 swap_shift          发起换班
  13 register_course     报名课程
  14 payslip_email       请求工资条邮件
  15 contact_hr          联系人力/店长
  16 query_social_insurance 查社保（补充）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()


@dataclass
class IntentRule:
    intent: str
    keywords: List[str]     # 任一命中即可
    tool: str               # 对应工具名
    requires_slots: List[str] = None  # 需要从文本提取的槽位


# 关键词规则表 —— 每类至少 3 种说法（测试用）
INTENT_RULES: List[IntentRule] = [
    IntentRule(
        intent="query_salary",
        keywords=["工资", "薪资", "薪水", "发多少钱", "收入", "到手", "月薪"],
        tool="get_my_salary",
    ),
    IntentRule(
        intent="query_attendance",
        keywords=["考勤", "打卡", "出勤", "迟到", "早退", "缺勤"],
        tool="get_my_attendance",
    ),
    IntentRule(
        intent="query_schedule",
        keywords=["排班", "班表", "排几个班", "上班时间", "我的班", "下周班"],
        tool="get_my_schedule",
    ),
    IntentRule(
        intent="query_leave_balance",
        keywords=["请假额度", "请假余额", "年假", "剩多少天", "还能请几天"],
        tool="get_my_leave_balance",
    ),
    IntentRule(
        intent="query_health_cert",
        keywords=["健康证", "体检证", "健康证过期", "健康证到期"],
        tool="get_my_health_cert_status",
    ),
    IntentRule(
        intent="query_contract",
        keywords=["合同", "劳动合同", "合同到期", "合同什么时候"],
        tool="get_my_contract_status",
    ),
    IntentRule(
        intent="query_training",
        keywords=["培训", "培训进度", "学到哪了", "课程进度"],
        tool="get_my_training_progress",
    ),
    IntentRule(
        intent="query_certificates",
        keywords=["证书", "我拿了什么证", "我的证", "证书即将过期"],
        tool="get_my_certificates",
    ),
    IntentRule(
        intent="query_okr",
        keywords=["okr", "OKR", "目标", "我的目标进度"],
        tool="get_my_okr",
    ),
    IntentRule(
        intent="query_points",
        keywords=["积分", "我排第几", "排行榜", "排名"],
        tool="get_my_points_and_rank",
    ),
    IntentRule(
        intent="submit_leave",
        keywords=["我要请假", "申请请假", "提交请假", "帮我请假"],
        tool="submit_leave_request",
        requires_slots=["start", "end", "leave_type", "reason"],
    ),
    IntentRule(
        intent="swap_shift",
        keywords=["换班", "调班", "跟谁换班", "换个班"],
        tool="request_shift_swap",
        requires_slots=["target_employee", "my_shift", "their_shift"],
    ),
    IntentRule(
        intent="register_course",
        keywords=["报名", "报名课程", "我要报", "报这个课"],
        tool="register_for_course",
        requires_slots=["course_id"],
    ),
    IntentRule(
        intent="payslip_email",
        keywords=["工资条", "电子工资条", "工资单邮件", "发到邮箱"],
        tool="request_payslip_email",
    ),
    IntentRule(
        intent="contact_hr",
        keywords=["人力电话", "联系人力", "店长电话", "人事电话", "hr电话"],
        tool="get_hr_contact",
    ),
    IntentRule(
        intent="query_social_insurance",
        keywords=["社保", "五险", "公积金", "社保缴纳"],
        tool="get_my_social_insurance",
    ),
    IntentRule(
        intent="list_courses",
        keywords=["有什么课", "可以学", "能学什么", "推荐课程"],
        tool="list_available_courses",
    ),
]


def classify_intent(message: str) -> Optional[Tuple[str, str]]:
    """
    规则优先的意图分类
    返回 (intent, tool_name) 或 None（需走 LLM 兜底）
    """
    text = (message or "").lower()
    for rule in INTENT_RULES:
        if any(kw.lower() in text for kw in rule.keywords):
            return rule.intent, rule.tool
    return None


def extract_month_slot(text: str) -> Optional[str]:
    """从文本提取月份槽位，如'本月'/'上月'/'3月'"""
    import re
    if "本月" in text or "这个月" in text:
        return "this_month"
    if "上月" in text or "上个月" in text:
        return "last_month"
    m = re.search(r"(\d{4})[年\-](\d{1,2})月?", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{1,2})月", text)
    if m:
        from datetime import datetime
        return f"{datetime.utcnow().year}-{int(m.group(1)):02d}"
    return None


def extract_week_slot(text: str) -> Optional[str]:
    """从文本提取周槽位"""
    if "下周" in text or "下个星期" in text:
        return "next"
    if "本周" in text or "这周" in text or "这个星期" in text:
        return "current"
    return None
