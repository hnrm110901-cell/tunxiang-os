"""
i18n 种子文案 — 100 个常用 key × zh-CN/zh-TW/en-US 三核心语种
vi-VN/th-TH/id-ID 占位（留待 LLM/人工补齐）

运行:
  cd apps/api-gateway && python -m scripts.seed_i18n_texts
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from src.core.database import async_session_maker  # noqa: E402
from src.models.i18n import I18nTextKey, I18nTranslation, Locale  # noqa: E402


LOCALES = [
    ("zh-CN", "简体中文", "🇨🇳", True),
    ("zh-TW", "繁體中文", "🇭🇰", False),
    ("en-US", "English", "🇺🇸", False),
    ("vi-VN", "Tiếng Việt", "🇻🇳", False),
    ("th-TH", "ภาษาไทย", "🇹🇭", False),
    ("id-ID", "Bahasa Indonesia", "🇮🇩", False),
]


# 100 个文案：(namespace, key, zh-CN, zh-TW, en-US)
# vi/th/id 留空，由 auto_translate_missing 填充
TEXTS: list[tuple[str, str, str, str, str]] = [
    # common 40
    ("common", "save", "保存", "儲存", "Save"),
    ("common", "cancel", "取消", "取消", "Cancel"),
    ("common", "confirm", "确认", "確認", "Confirm"),
    ("common", "delete", "删除", "刪除", "Delete"),
    ("common", "edit", "编辑", "編輯", "Edit"),
    ("common", "create", "创建", "建立", "Create"),
    ("common", "search", "搜索", "搜尋", "Search"),
    ("common", "filter", "筛选", "篩選", "Filter"),
    ("common", "export", "导出", "匯出", "Export"),
    ("common", "import", "导入", "匯入", "Import"),
    ("common", "submit", "提交", "提交", "Submit"),
    ("common", "back", "返回", "返回", "Back"),
    ("common", "next", "下一步", "下一步", "Next"),
    ("common", "previous", "上一步", "上一步", "Previous"),
    ("common", "loading", "加载中...", "載入中...", "Loading..."),
    ("common", "empty", "暂无数据", "暫無資料", "No data"),
    ("common", "success", "操作成功", "操作成功", "Success"),
    ("common", "failed", "操作失败", "操作失敗", "Failed"),
    ("common", "yes", "是", "是", "Yes"),
    ("common", "no", "否", "否", "No"),
    ("common", "all", "全部", "全部", "All"),
    ("common", "today", "今天", "今天", "Today"),
    ("common", "yesterday", "昨天", "昨天", "Yesterday"),
    ("common", "week", "本周", "本週", "This week"),
    ("common", "month", "本月", "本月", "This month"),
    ("common", "year", "本年", "本年", "This year"),
    ("common", "settings", "设置", "設定", "Settings"),
    ("common", "profile", "个人信息", "個人資料", "Profile"),
    ("common", "logout", "退出登录", "登出", "Logout"),
    ("common", "login", "登录", "登入", "Login"),
    ("common", "username", "用户名", "使用者名稱", "Username"),
    ("common", "password", "密码", "密碼", "Password"),
    ("common", "remember_me", "记住我", "記住我", "Remember me"),
    ("common", "welcome", "欢迎，{name}", "歡迎，{name}", "Welcome, {name}"),
    ("common", "language", "语言", "語言", "Language"),
    ("common", "currency", "货币", "貨幣", "Currency"),
    ("common", "timezone", "时区", "時區", "Timezone"),
    ("common", "operation", "操作", "操作", "Action"),
    ("common", "status", "状态", "狀態", "Status"),
    ("common", "total", "合计", "合計", "Total"),
    # hr 25
    ("hr", "employee", "员工", "員工", "Employee"),
    ("hr", "employee_list", "员工列表", "員工列表", "Employee list"),
    ("hr", "position", "职位", "職位", "Position"),
    ("hr", "department", "部门", "部門", "Department"),
    ("hr", "hire_date", "入职日期", "到職日期", "Hire date"),
    ("hr", "leave_date", "离职日期", "離職日期", "Leave date"),
    ("hr", "schedule", "排班", "排班", "Schedule"),
    ("hr", "attendance", "考勤", "考勤", "Attendance"),
    ("hr", "punch_in", "上班打卡", "上班打卡", "Clock in"),
    ("hr", "punch_out", "下班打卡", "下班打卡", "Clock out"),
    ("hr", "late", "迟到", "遲到", "Late"),
    ("hr", "early_leave", "早退", "早退", "Early leave"),
    ("hr", "absent", "缺勤", "缺勤", "Absent"),
    ("hr", "overtime", "加班", "加班", "Overtime"),
    ("hr", "leave", "请假", "請假", "Leave"),
    ("hr", "annual_leave", "年假", "年假", "Annual leave"),
    ("hr", "sick_leave", "病假", "病假", "Sick leave"),
    ("hr", "personal_leave", "事假", "事假", "Personal leave"),
    ("hr", "contract", "劳动合同", "勞動契約", "Contract"),
    ("hr", "probation", "试用期", "試用期", "Probation"),
    ("hr", "regular", "正式", "正式", "Regular"),
    ("hr", "performance", "绩效", "績效", "Performance"),
    ("hr", "okr", "OKR", "OKR", "OKR"),
    ("hr", "training", "培训", "訓練", "Training"),
    ("hr", "exit_interview", "离职面谈", "離職面談", "Exit interview"),
    # finance 15
    ("finance", "amount", "金额", "金額", "Amount"),
    ("finance", "revenue", "收入", "收入", "Revenue"),
    ("finance", "cost", "成本", "成本", "Cost"),
    ("finance", "profit", "利润", "利潤", "Profit"),
    ("finance", "invoice", "发票", "發票", "Invoice"),
    ("finance", "receipt", "收据", "收據", "Receipt"),
    ("finance", "tax", "税", "稅", "Tax"),
    ("finance", "vat", "增值税", "加值稅", "VAT"),
    ("finance", "budget", "预算", "預算", "Budget"),
    ("finance", "expense", "费用", "費用", "Expense"),
    ("finance", "receivable", "应收", "應收", "Receivable"),
    ("finance", "payable", "应付", "應付", "Payable"),
    ("finance", "reconcile", "对账", "對帳", "Reconcile"),
    ("finance", "closing", "结账", "結帳", "Closing"),
    ("finance", "report", "财务报表", "財務報表", "Financial report"),
    # payroll 12
    ("payroll", "salary", "工资", "薪資", "Salary"),
    ("payroll", "gross_pay", "应发工资", "應發薪資", "Gross pay"),
    ("payroll", "net_pay", "实发工资", "實發薪資", "Net pay"),
    ("payroll", "payslip", "工资条", "薪資單", "Payslip"),
    ("payroll", "bonus", "奖金", "獎金", "Bonus"),
    ("payroll", "allowance", "津贴", "津貼", "Allowance"),
    ("payroll", "deduction", "扣款", "扣款", "Deduction"),
    ("payroll", "social_insurance", "社保", "社保", "Social insurance"),
    ("payroll", "housing_fund", "公积金", "公積金", "Housing fund"),
    ("payroll", "mpf", "强积金", "強積金", "MPF"),
    ("payroll", "cpf", "公积金(CPF)", "公積金(CPF)", "CPF"),
    ("payroll", "pay_month", "薪资月份", "薪資月份", "Pay month"),
    # gdpr 8
    ("gdpr", "consent", "数据处理同意", "資料處理同意", "Data consent"),
    ("gdpr", "revoke_consent", "撤回同意", "撤回同意", "Revoke consent"),
    ("gdpr", "data_export", "导出我的数据", "匯出我的資料", "Export my data"),
    ("gdpr", "data_delete", "删除我的数据", "刪除我的資料", "Delete my data"),
    ("gdpr", "access_request", "数据主体请求", "資料主體請求", "Data subject request"),
    ("gdpr", "legal_basis", "法律依据", "法律依據", "Legal basis"),
    ("gdpr", "marketing_consent", "营销推送同意", "行銷推送同意", "Marketing consent"),
    ("gdpr", "ai_training_consent", "AI 训练数据同意", "AI 訓練資料同意", "AI training consent"),
]


async def seed() -> None:
    async with async_session_maker() as session:
        # 1) locales
        for code, name, flag, is_default in LOCALES:
            exists = (await session.execute(select(Locale).where(Locale.code == code))).scalar_one_or_none()
            if exists:
                continue
            session.add(
                Locale(
                    id=uuid.uuid4(),
                    code=code,
                    name=name,
                    flag_emoji=flag,
                    is_active=True,
                    is_default=is_default,
                )
            )
        await session.flush()

        # 2) text keys + translations
        key_count = 0
        tr_count = 0
        for ns, key, zh_cn, zh_tw, en in TEXTS:
            existing_key = (
                await session.execute(
                    select(I18nTextKey).where(I18nTextKey.namespace == ns, I18nTextKey.key == key)
                )
            ).scalar_one_or_none()
            if existing_key:
                tk_id = existing_key.id
            else:
                tk = I18nTextKey(id=uuid.uuid4(), namespace=ns, key=key, default_value_zh=zh_cn)
                session.add(tk)
                await session.flush()
                tk_id = tk.id
                key_count += 1

            for loc, val in [("zh-CN", zh_cn), ("zh-TW", zh_tw), ("en-US", en)]:
                existing_tr = (
                    await session.execute(
                        select(I18nTranslation).where(
                            I18nTranslation.text_key_id == tk_id,
                            I18nTranslation.locale_code == loc,
                        )
                    )
                ).scalar_one_or_none()
                if existing_tr:
                    continue
                session.add(
                    I18nTranslation(
                        id=uuid.uuid4(),
                        text_key_id=tk_id,
                        locale_code=loc,
                        translated_value=val,
                        translator="human",
                        reviewed=True,
                    )
                )
                tr_count += 1

        await session.commit()
        print(f"种子完成: {key_count} 个新 key, {tr_count} 条新翻译, 覆盖 6 locales")


if __name__ == "__main__":
    asyncio.run(seed())
