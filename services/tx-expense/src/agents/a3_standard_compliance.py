"""
A3 差标合规 Agent
=================
职责：费用申请提交时同步实时检查差标合规性

触发时机：
  - 同步调用：expense_application_service.submit_application() 中调用
  - 申请人提交前预检：/expense/standards/check-compliance 端点

处理流程：
  1. 读取申请人职级（从 tx-org 获取，P1已集成）
  2. 读取目的地城市（从申请单 metadata 或 expense_items）
  3. 逐行检查每个 expense_item 的金额
  4. 返回合规报告，包含每行的状态和建议

四档处理规则（Agent铁律）：
  超标 < 20%    → compliant_with_warning（允许提交，审批单高亮提示）
  超标 20%-50%  → over_limit_minor（必须填写超标说明才能提交）
  超标 > 50%    → over_limit_major（超出部分系统截断，走特殊申请通道）
  连续超标≥3次  → escalate_to_supervisor（通知申请人主管）

Agent铁律：
  < 50% 超标由审批人最终决定，Agent不自动驳回
  > 50% 超出部分截断是系统层面约束
  合规建议提供替代方案（如"建议住宿300元以内的酒店"）
  统计申请人历史合规率，连续超标通知主管

量化目标：
  差标违规报销率 12%→<2%，财务复核退单工作量 -60%
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import select, text as sa_text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.expense_application import ExpenseApplication, ExpenseItem
from ..models.expense_enums import (
    AgentType,
    NotificationEventType,
    StaffLevel,
)
from ..services import expense_standard_service as std_svc
from ..services import notification_service

log = structlog.get_logger(__name__)

# 超标分级阈值（与 expense_standard_service.check_compliance 保持一致）
_WARN_THRESHOLD = 0.20    # <20% → compliant_with_warning（允许提交，高亮）
_MINOR_THRESHOLD = 0.50   # 20%-50% → over_limit_minor（需说明）
# >50% → over_limit_major（截断）

# 连续超标触发主管通知的次数
_ESCALATE_CONSECUTIVE = 3

# 历史合规率查询回溯天数
_LOOKBACK_DAYS = 90

# 城市关键词：用于从 description 中提取目的地
_KNOWN_CITIES = [
    "北京", "上海", "广州", "深圳",           # 一线
    "成都", "杭州", "武汉", "西安", "南京",    # 新一线
    "重庆", "天津", "苏州", "长沙", "郑州",
    "青岛", "宁波", "无锡", "东莞", "福州",
    "合肥", "昆明", "沈阳", "哈尔滨", "济南",
    "长春", "贵阳", "太原", "南宁", "石家庄",
    "厦门", "乌鲁木齐", "南昌",
]

# 差标费用类型关键词映射（description → expense_type）
_EXPENSE_TYPE_KEYWORDS: dict[str, str] = {
    "住宿": "accommodation",
    "酒店": "accommodation",
    "宾馆": "accommodation",
    "客房": "accommodation",
    "餐饮": "meal",
    "餐费": "meal",
    "用餐": "meal",
    "饭费": "meal",
    "交通": "transport",
    "机票": "transport",
    "高铁": "transport",
    "火车": "transport",
    "出租车": "transport",
    "网约车": "transport",
    "打车": "transport",
    "地铁": "transport",
    "汽车票": "transport",
}


# =============================================================================
# 内部工具：Agent 任务日志
# =============================================================================

async def _log_agent_job(
    db: AsyncSession,
    tenant_id: UUID,
    job_type: str,
    trigger_source: str,
    application_id: Optional[UUID] = None,
    result: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    """写入结构化日志（暂用 structlog 代替 expense_agent_events 表，P1补建）。"""
    log.info(
        "agent_job_executed",
        agent=AgentType.STANDARD_COMPLIANCE,
        job_type=job_type,
        trigger_source=trigger_source,
        tenant_id=str(tenant_id),
        application_id=str(application_id) if application_id else None,
        result=result,
        error=error,
    )


# =============================================================================
# 1. 申请人职级获取
# =============================================================================

async def _get_applicant_level(
    db: AsyncSession,
    tenant_id: UUID,
    applicant_id: UUID,
) -> str:
    """
    获取申请人职级。

    优先从 tx-org 集成服务获取真实职级（org_integration_service.get_employee_info）。
    若集成服务不可用，从 expense_applications 历史记录推断（fallback）。
    返回 StaffLevel 枚举值，默认 'store_staff'（最保守）。

    tx-org 集成说明：
      当前 P1 阶段 tx-org 服务通过内部 HTTP 调用（localhost:8012）获取员工信息。
      响应结构示例：{"staff_level": "store_manager", "supervisor_id": "<uuid>"}
      若服务不可用（网络超时/服务宕机），自动降级到 fallback 逻辑。
    """
    import os
    import httpx

    # 尝试通过 tx-org 服务获取
    tx_org_base = os.environ.get("TX_ORG_INTERNAL_URL", "http://localhost:8012")
    try:
        async with httpx.AsyncClient(timeout=0.5) as client:
            resp = await client.get(
                f"{tx_org_base}/internal/employees/{applicant_id}",
                headers={"X-Tenant-ID": str(tenant_id)},
            )
            if resp.status_code == 200:
                data = resp.json()
                level = data.get("staff_level") or data.get("level")
                if level and level in {e.value for e in StaffLevel}:
                    return level
    except (httpx.TimeoutException, httpx.RequestError, Exception) as exc:
        log.warning(
            "a3_tx_org_unavailable_fallback",
            tenant_id=str(tenant_id),
            applicant_id=str(applicant_id),
            error=f"{type(exc).__name__}: {exc}",
        )

    # Fallback：从历史申请推断职级（查 metadata.staff_level 字段）
    try:
        stmt = (
            sa_text(
                "SELECT metadata->>'staff_level' AS staff_level "
                "FROM expense_applications "
                "WHERE tenant_id = :tenant_id "
                "  AND applicant_id = :applicant_id "
                "  AND metadata->>'staff_level' IS NOT NULL "
                "  AND is_deleted = FALSE "
                "ORDER BY created_at DESC "
                "LIMIT 1"
            )
        )
        result = await db.execute(
            stmt,
            {"tenant_id": tenant_id, "applicant_id": applicant_id},
        )
        row = result.fetchone()
        if row and row[0]:
            level = row[0]
            if level in {e.value for e in StaffLevel}:
                return level
    except (OperationalError, SQLAlchemyError) as exc:
        log.warning(
            "a3_fallback_level_query_failed",
            tenant_id=str(tenant_id),
            applicant_id=str(applicant_id),
            error=f"{type(exc).__name__}: {exc}",
        )

    # 最终默认：门店员工（最保守，宁可多查不漏）
    return StaffLevel.STORE_STAFF.value


# =============================================================================
# 2. 目的地城市提取
# =============================================================================

def _extract_destination_city(
    application_metadata: dict,
    items: list,
) -> Optional[str]:
    """
    从申请单中提取目的地城市。

    查找顺序：
    1. application.metadata['destination_city']
    2. application.metadata['trip_destination']
    3. expense_items 中 description 字段包含城市名的关键词提取
    返回城市名字符串，无法确定时返回 None
    """
    # 1. 精确字段
    meta = application_metadata or {}
    city = meta.get("destination_city") or meta.get("trip_destination")
    if city and isinstance(city, str) and city.strip():
        return city.strip()

    # 2. 从 expense_items 的 description 中模糊提取
    for item in items:
        desc = ""
        if isinstance(item, dict):
            desc = item.get("description", "") or ""
        elif hasattr(item, "description"):
            desc = item.description or ""

        for city_name in _KNOWN_CITIES:
            if city_name in desc:
                return city_name

    return None


# =============================================================================
# 3. 单项合规检查（核心）
# =============================================================================

async def check_item_compliance(
    db: AsyncSession,
    tenant_id: UUID,
    brand_id: UUID,
    applicant_id: UUID,
    item_description: str,
    item_amount_fen: int,
    expense_type: str,
    destination_city: Optional[str] = None,
    is_daily_limit: bool = False,
) -> dict:
    """
    检查单个费用项的差标合规性。

    Args:
        item_amount_fen:  申请金额（分）
        expense_type:     TravelExpenseType 值（accommodation/meal/transport/other_travel）
        destination_city: 目的地城市名，None 时降级使用 tier3
        is_daily_limit:   True=按日限额，False=按单笔限额

    Returns:
        {
          "status": "compliant"|"compliant_with_warning"|"over_limit_minor"|"over_limit_major"|"no_rule",
          "compliant": bool,           # True=可提交，False=需处理后才能提交
          "item_amount_fen": int,      # 申请金额（分）
          "limit_fen": int | None,     # 适用限额（分）
          "over_rate": float | None,   # 超标比例，如 0.35=35%
          "allowed_amount_fen": int,   # 本项允许的最大金额（分）
          "truncated_amount_fen": int, # >50%时截断后的金额（分），等于 limit_fen
          "city_tier": str | None,
          "staff_level": str,
          "standard_name": str | None,
          "compliance_action": str,    # "none"/"add_explanation"/"truncate"/"special_channel"
          "suggestion": str | None,    # 合规替代建议
          "message": str,              # 中文说明
        }

    性能约束：<200ms（使用差标服务内置缓存）
    """
    staff_level = await _get_applicant_level(db, tenant_id, applicant_id)

    # 无目的地城市时，使用 tier3（保守默认，宁可宽松不误拦）
    city = destination_city or "其他"

    # 调用差标匹配引擎（含城市→级别映射 + 三维度差标查询）
    compliance = await std_svc.check_compliance(
        db=db,
        tenant_id=tenant_id,
        brand_id=brand_id,
        staff_level=staff_level,
        destination_city=city,
        expense_type=expense_type,
        amount=item_amount_fen,
        is_daily=is_daily_limit,
    )

    city_tier = compliance.get("city_tier")
    limit_fen = compliance.get("limit")
    over_rate = compliance.get("over_rate", 0.0)
    standard_name = compliance.get("standard_name") or None

    # ── 无差标配置：自动通过 ──────────────────────────────────────────────────
    if compliance["status"] == "no_rule":
        return {
            "status": "no_rule",
            "compliant": True,
            "item_amount_fen": item_amount_fen,
            "limit_fen": None,
            "over_rate": None,
            "allowed_amount_fen": item_amount_fen,
            "truncated_amount_fen": item_amount_fen,
            "city_tier": city_tier,
            "staff_level": staff_level,
            "standard_name": None,
            "compliance_action": "none",
            "suggestion": None,
            "message": "未配置差标规则，自动通过",
        }

    # ── 未超标：合规 ──────────────────────────────────────────────────────────
    if compliance["status"] == "compliant" and over_rate == 0.0:
        return {
            "status": "compliant",
            "compliant": True,
            "item_amount_fen": item_amount_fen,
            "limit_fen": limit_fen,
            "over_rate": 0.0,
            "allowed_amount_fen": item_amount_fen,
            "truncated_amount_fen": item_amount_fen,
            "city_tier": city_tier,
            "staff_level": staff_level,
            "standard_name": standard_name,
            "compliance_action": "none",
            "suggestion": None,
            "message": compliance["message"],
        }

    # ── 超标分级处理 ─────────────────────────────────────────────────────────
    limit_yuan = (limit_fen or 0) / 100
    over_pct_str = f"{over_rate * 100:.1f}%"

    if over_rate < _WARN_THRESHOLD:
        # 超标 <20%：允许提交，审批单高亮
        return {
            "status": "compliant_with_warning",
            "compliant": True,
            "item_amount_fen": item_amount_fen,
            "limit_fen": limit_fen,
            "over_rate": over_rate,
            "allowed_amount_fen": item_amount_fen,
            "truncated_amount_fen": item_amount_fen,
            "city_tier": city_tier,
            "staff_level": staff_level,
            "standard_name": standard_name,
            "compliance_action": "none",
            "suggestion": _build_suggestion(expense_type, limit_fen),
            "message": (
                f"金额超出差标 {over_pct_str}（限额 {limit_yuan:.0f} 元），"
                "轻微超标，审批单将高亮显示，由审批人决定"
            ),
        }

    elif over_rate <= _MINOR_THRESHOLD:
        # 超标 20%-50%：必须填写超标说明才能提交
        return {
            "status": "over_limit_minor",
            "compliant": False,
            "item_amount_fen": item_amount_fen,
            "limit_fen": limit_fen,
            "over_rate": over_rate,
            "allowed_amount_fen": item_amount_fen,
            "truncated_amount_fen": item_amount_fen,
            "city_tier": city_tier,
            "staff_level": staff_level,
            "standard_name": standard_name,
            "compliance_action": "add_explanation",
            "suggestion": _build_suggestion(expense_type, limit_fen),
            "message": (
                f"金额超出差标 {over_pct_str}（限额 {limit_yuan:.0f} 元），"
                "须在备注中填写超标说明后方可提交，最终由审批人决定"
            ),
        }

    else:
        # 超标 >50%：超出部分系统截断，走特殊申请通道
        truncated = limit_fen  # 截断到限额
        return {
            "status": "over_limit_major",
            "compliant": False,
            "item_amount_fen": item_amount_fen,
            "limit_fen": limit_fen,
            "over_rate": over_rate,
            "allowed_amount_fen": truncated,
            "truncated_amount_fen": truncated,
            "city_tier": city_tier,
            "staff_level": staff_level,
            "standard_name": standard_name,
            "compliance_action": "special_channel",
            "suggestion": _build_suggestion(expense_type, limit_fen),
            "message": (
                f"金额严重超出差标 {over_pct_str}（限额 {limit_yuan:.0f} 元），"
                f"系统已截断至 {limit_yuan:.0f} 元，"
                f"超出部分 {(item_amount_fen - (truncated or 0)) / 100:.0f} 元须走特殊申请通道"
            ),
        }


def _build_suggestion(expense_type: str, limit_fen: Optional[int]) -> Optional[str]:
    """根据费用类型和限额生成合规替代建议。"""
    if limit_fen is None:
        return None
    limit_yuan = limit_fen / 100
    suggestions = {
        "accommodation": f"建议选择 {limit_yuan:.0f} 元以内的酒店（可通过差旅平台预订合规房源）",
        "meal": f"建议餐饮控制在 {limit_yuan:.0f} 元以内",
        "transport": f"建议选择 {limit_yuan:.0f} 元以内的交通方式（如高铁/经济舱/普通出租车）",
        "other_travel": f"建议该项费用控制在 {limit_yuan:.0f} 元以内",
    }
    return suggestions.get(expense_type, f"建议该项费用控制在 {limit_yuan:.0f} 元以内")


# =============================================================================
# 4. 申请级完整检查
# =============================================================================

async def check_application_compliance(
    db: AsyncSession,
    tenant_id: UUID,
    application_id: UUID,
) -> dict:
    """
    对整个费用申请进行完整差标合规检查。

    1. 读取申请及所有 expense_items
    2. 获取申请人职级
    3. 提取目的地城市
    4. 逐项调用 check_item_compliance
    5. 汇总结果，判断整体合规状态
    6. 检查申请人历史合规率（_check_historical_compliance_rate）
    7. 若历史连续超标≥3次，标记 escalate_to_supervisor=True

    Returns:
        {
          "application_id": str,
          "overall_status": "compliant"|"needs_explanation"|"needs_truncation"|"needs_special_channel",
          "can_submit": bool,          # False时必须处理后才能提交
          "items": list[dict],         # 每个 item 的合规检查结果
          "total_allowed_amount_fen": int,   # 所有项目允许金额之和（截断后）
          "total_over_amount_fen": int,      # 超标总金额（分）
          "escalate_to_supervisor": bool,
          "supervisor_id": UUID | None,
          "required_explanation_items": list[int],  # 需要填写说明的item索引
          "summary_message": str,
        }
    """
    summary: dict = {
        "application_id": str(application_id),
        # status: 标准格式（compliant/compliant_with_warning/over_limit_minor/over_limit_major）
        "status": "compliant",
        # overall_status: 内部扩展格式（兼容旧调用方）
        "overall_status": "compliant",
        "can_submit": True,
        "items": [],
        "max_over_rate": 0.0,
        "total_allowed_amount_fen": 0,
        "total_over_amount_fen": 0,
        "escalate_to_supervisor": False,
        "supervisor_id": None,
        "required_explanation_items": [],
        "summary_message": "",
        "error": None,
    }

    try:
        # 步骤1：读取申请主表
        stmt = select(ExpenseApplication).where(
            ExpenseApplication.tenant_id == tenant_id,
            ExpenseApplication.id == application_id,
            ExpenseApplication.is_deleted.is_(False),
        )
        result = await db.execute(stmt)
        application = result.scalar_one_or_none()

        if application is None:
            summary["error"] = f"申请单不存在: {application_id}"
            summary["summary_message"] = "申请单不存在，无法进行合规检查"
            return summary

        # 读取 expense_items
        items_stmt = select(ExpenseItem).where(
            ExpenseItem.application_id == application_id,
            ExpenseItem.is_deleted.is_(False),
        )
        items_result = await db.execute(items_stmt)
        expense_items = list(items_result.scalars().all())

        if not expense_items:
            summary["summary_message"] = "申请单无明细行，跳过差标合规检查"
            return summary

        # 步骤2：获取申请人职级
        staff_level = await _get_applicant_level(
            db, tenant_id, application.applicant_id
        )

        # 步骤3：提取目的地城市
        destination_city = _extract_destination_city(
            application.metadata or {},
            expense_items,
        )

        # 步骤4：逐项检查
        item_results = []
        total_allowed = 0
        total_over = 0
        required_explanation_idxs = []
        has_major = False
        has_minor = False
        has_warning = False
        max_over_rate = 0.0

        for idx, item in enumerate(expense_items):
            # 推断费用类型
            expense_type = _infer_expense_type(item.description or "")

            item_result = await check_item_compliance(
                db=db,
                tenant_id=tenant_id,
                brand_id=application.brand_id,
                applicant_id=application.applicant_id,
                item_description=item.description or "",
                item_amount_fen=item.amount,
                expense_type=expense_type,
                destination_city=destination_city,
                is_daily_limit=False,
            )

            item_result["item_id"] = str(item.id)
            item_result["item_index"] = idx
            # original_amount_fen：标准字段别名，与 item_amount_fen 保持一致
            item_result["original_amount_fen"] = item.amount
            item_results.append(item_result)

            # 跟踪最大超标率
            item_over_rate = item_result.get("over_rate") or 0.0
            if item_over_rate and item_over_rate > max_over_rate:
                max_over_rate = item_over_rate

            # 累加允许金额（截断后）
            total_allowed += item_result["allowed_amount_fen"]

            # 计算超标金额
            if item_result["limit_fen"] is not None and item.amount > item_result["limit_fen"]:
                total_over += item.amount - item_result["limit_fen"]

            # 标记各级状态
            status = item_result["status"]
            if status == "over_limit_major":
                has_major = True
            elif status == "over_limit_minor":
                has_minor = True
                required_explanation_idxs.append(idx)
            elif status == "compliant_with_warning":
                has_warning = True

        # 步骤5：汇总整体状态
        if has_major:
            overall_status = "needs_special_channel"
            # 标准状态：>50% 超标 → over_limit_major
            std_status = "over_limit_major"
            can_submit = False
        elif has_minor:
            overall_status = "needs_explanation"
            # 标准状态：20%-50% 超标 → over_limit_minor
            std_status = "over_limit_minor"
            can_submit = False
        elif has_warning:
            overall_status = "compliant"    # 允许提交，审批单高亮
            # 标准状态：<20% 超标 → compliant_with_warning
            std_status = "compliant_with_warning"
            can_submit = True
        else:
            overall_status = "compliant"
            std_status = "compliant"
            can_submit = True

        summary["items"] = item_results
        summary["status"] = std_status
        summary["overall_status"] = overall_status
        summary["can_submit"] = can_submit
        summary["max_over_rate"] = max_over_rate
        summary["total_allowed_amount_fen"] = total_allowed
        summary["total_over_amount_fen"] = total_over
        summary["required_explanation_items"] = required_explanation_idxs

        # 步骤6：检查历史合规率
        history = await _check_historical_compliance_rate(
            db=db,
            tenant_id=tenant_id,
            applicant_id=application.applicant_id,
        )

        # 步骤7：连续超标≥3次，通知主管
        if history["consecutive_over_limit"] >= _ESCALATE_CONSECUTIVE:
            summary["escalate_to_supervisor"] = True
            supervisor_id = await _get_supervisor_id(
                db, tenant_id, application.applicant_id
            )
            summary["supervisor_id"] = supervisor_id

        # 生成汇总说明
        summary["summary_message"] = _build_summary_message(
            overall_status=overall_status,
            can_submit=can_submit,
            total_over_amount_fen=total_over,
            required_count=len(required_explanation_idxs),
            has_major=has_major,
            escalate=summary["escalate_to_supervisor"],
            consecutive_count=history["consecutive_over_limit"],
        )

        await _log_agent_job(
            db=db,
            tenant_id=tenant_id,
            job_type="application_compliance_check",
            trigger_source="application_submit",
            application_id=application_id,
            result={
                "overall_status": overall_status,
                "can_submit": can_submit,
                "item_count": len(expense_items),
                "escalate": summary["escalate_to_supervisor"],
            },
        )
        return summary

    except (OSError, RuntimeError, ValueError, SQLAlchemyError) as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        summary["error"] = error_msg
        summary["status"] = "compliant"           # 异常时放行，不阻断主流程
        summary["overall_status"] = "compliant"
        summary["can_submit"] = True
        summary["max_over_rate"] = 0.0
        summary["summary_message"] = "差标合规检查异常，已放行（请人工复核）"
        log.error(
            "a3_check_application_compliance_error",
            tenant_id=str(tenant_id),
            application_id=str(application_id),
            error=error_msg,
            exc_info=True,
        )
        await _log_agent_job(
            db=db,
            tenant_id=tenant_id,
            job_type="application_compliance_check",
            trigger_source="application_submit",
            application_id=application_id,
            error=error_msg,
        )
        return summary


def _infer_expense_type(description: str) -> str:
    """从 item.description 关键词推断 TravelExpenseType。"""
    for keyword, expense_type in _EXPENSE_TYPE_KEYWORDS.items():
        if keyword in description:
            return expense_type
    return "other_travel"


def _build_summary_message(
    overall_status: str,
    can_submit: bool,
    total_over_amount_fen: int,
    required_count: int,
    has_major: bool,
    escalate: bool,
    consecutive_count: int,
) -> str:
    """生成给申请人的整体合规说明。"""
    if overall_status == "compliant" and total_over_amount_fen == 0:
        return "所有费用项符合差标要求，可直接提交"

    parts = []

    if has_major:
        parts.append(
            f"有费用项超标超过50%，超出部分已截断至差标限额，"
            f"请确认后通过特殊申请通道补充提交"
        )
    elif required_count > 0:
        parts.append(
            f"有 {required_count} 项费用超标20%-50%，"
            "请在对应明细的备注中填写超标说明后重新提交"
        )

    if total_over_amount_fen > 0:
        parts.append(f"超标金额合计：{total_over_amount_fen / 100:.2f} 元")

    if escalate:
        parts.append(
            f"您近期已连续超标 {consecutive_count} 次，"
            "系统将自动通知您的直属上级"
        )

    return "；".join(parts) if parts else "请检查费用明细后重新提交"


# =============================================================================
# 5. 历史合规率检查
# =============================================================================

async def _check_historical_compliance_rate(
    db: AsyncSession,
    tenant_id: UUID,
    applicant_id: UUID,
    lookback_days: int = _LOOKBACK_DAYS,
) -> dict:
    """
    查询申请人近90天的差标合规历史。

    从 expense_applications 中查询该申请人的历史申请。
    利用 metadata.compliance_status 字段（由 A3 写回）统计超标情况。

    统计：
    - total_applications: 总申请数
    - over_limit_count: 超标次数
    - compliance_rate: 合规率（0.0-1.0）
    - consecutive_over_limit: 连续超标次数（最近N次）

    Returns:
        {"compliance_rate": float, "consecutive_over_limit": int, "total_count": int}
    """
    try:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)

        # 查询近期申请的合规状态（从 metadata 中读取 A3 写回的合规结果）
        history_stmt = sa_text(
            "SELECT "
            "  metadata->>'a3_overall_status' AS compliance_status, "
            "  submitted_at "
            "FROM expense_applications "
            "WHERE tenant_id = :tenant_id "
            "  AND applicant_id = :applicant_id "
            "  AND submitted_at >= :cutoff "
            "  AND status NOT IN ('draft', 'cancelled') "
            "  AND is_deleted = FALSE "
            "ORDER BY submitted_at DESC "
            "LIMIT 50"
        )
        result = await db.execute(
            history_stmt,
            {
                "tenant_id": tenant_id,
                "applicant_id": applicant_id,
                "cutoff": cutoff,
            },
        )
        rows = result.fetchall()

        if not rows:
            return {"compliance_rate": 1.0, "consecutive_over_limit": 0, "total_count": 0}

        total = len(rows)
        # 有超标状态（needs_explanation / needs_special_channel）算超标
        over_statuses = {"needs_explanation", "needs_special_channel"}
        over_count = sum(
            1 for row in rows
            if row[0] in over_statuses
        )

        # 计算连续超标次数（从最近一次开始向前数）
        consecutive = 0
        for row in rows:
            if row[0] in over_statuses:
                consecutive += 1
            else:
                break

        compliance_rate = round(1.0 - over_count / total, 4) if total > 0 else 1.0

        return {
            "compliance_rate": compliance_rate,
            "consecutive_over_limit": consecutive,
            "total_count": total,
        }

    except (OperationalError, SQLAlchemyError) as exc:
        log.warning(
            "a3_check_historical_compliance_rate_error",
            tenant_id=str(tenant_id),
            applicant_id=str(applicant_id),
            error=f"{type(exc).__name__}: {exc}",
        )
        return {"compliance_rate": 1.0, "consecutive_over_limit": 0, "total_count": 0}


async def _get_supervisor_id(
    db: AsyncSession,
    tenant_id: UUID,
    applicant_id: UUID,
) -> Optional[UUID]:
    """
    从 tx-org 获取申请人直属上级 ID。
    不可用时返回 None。
    """
    import os
    import httpx

    tx_org_base = os.environ.get("TX_ORG_INTERNAL_URL", "http://localhost:8012")
    try:
        async with httpx.AsyncClient(timeout=0.5) as client:
            resp = await client.get(
                f"{tx_org_base}/internal/employees/{applicant_id}",
                headers={"X-Tenant-ID": str(tenant_id)},
            )
            if resp.status_code == 200:
                data = resp.json()
                supervisor_id_str = data.get("supervisor_id")
                if supervisor_id_str:
                    return uuid.UUID(supervisor_id_str)
    except (httpx.TimeoutException, httpx.RequestError, ValueError, Exception) as exc:
        log.warning(
            "a3_get_supervisor_id_failed",
            tenant_id=str(tenant_id),
            applicant_id=str(applicant_id),
            error=f"{type(exc).__name__}: {exc}",
        )
    return None


# =============================================================================
# 6. 超标通知主管
# =============================================================================

async def notify_supervisor_of_repeated_violations(
    db: AsyncSession,
    tenant_id: UUID,
    brand_id: UUID,
    applicant_id: UUID,
    application_id: UUID,
    consecutive_count: int,
) -> None:
    """
    连续超标≥3次时通知申请人直属上级。

    主管信息通过 tx-org 内部 HTTP 获取（P1已集成）。
    调用 notification_service 推送通知。
    注意：只通知，不阻断申请流程。
    """
    try:
        supervisor_id = await _get_supervisor_id(db, tenant_id, applicant_id)
        if supervisor_id is None:
            log.warning(
                "a3_notify_supervisor_no_supervisor_found",
                tenant_id=str(tenant_id),
                applicant_id=str(applicant_id),
                application_id=str(application_id),
            )
            return

        await notification_service.send_notification(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
            recipient_id=supervisor_id,
            recipient_role="supervisor",
            event_type=NotificationEventType.REMINDER.value,
            application_title="差标合规预警——下属员工连续超标",
            applicant_name=str(applicant_id),     # P1阶段占位，实际应从 tx-org 拉取姓名
            total_amount=0,
            store_name="",
            brand_id=brand_id,
            comment=(
                f"您的下属员工（ID：{applicant_id}）近期已连续 {consecutive_count} 次"
                "提交超差标费用申请，请关注并指导其合规报销。"
                f"最新申请单号：{str(application_id)[:8]}..."
            ),
        )

        log.info(
            "a3_supervisor_notified",
            tenant_id=str(tenant_id),
            applicant_id=str(applicant_id),
            supervisor_id=str(supervisor_id),
            application_id=str(application_id),
            consecutive_count=consecutive_count,
        )

    except (OSError, RuntimeError, ValueError) as exc:
        # 通知失败不阻断流程，只记录日志
        log.error(
            "a3_notify_supervisor_error",
            tenant_id=str(tenant_id),
            applicant_id=str(applicant_id),
            application_id=str(application_id),
            error=f"{type(exc).__name__}: {exc}",
            exc_info=True,
        )


# =============================================================================
# 7. 申请提交前预检（快速版）
# =============================================================================

async def pre_check_before_submit(
    db: AsyncSession,
    tenant_id: UUID,
    brand_id: UUID,
    applicant_id: UUID,
    items: list[dict],
    destination_city: Optional[str] = None,
) -> dict:
    """
    申请提交前的快速预检（前端实时调用，<200ms）。

    不写DB，只计算合规状态。
    使用差标服务内存缓存（get_city_tier 有模块级城市缓存，避免重复查DB）。
    返回精简版合规报告，让用户在提交前了解问题。

    Args:
        items: [{"description": str, "amount_fen": int, "expense_type": str}]
               expense_type 可选，若未提供则从 description 推断
        destination_city: 目的地城市名（可选）

    Returns:
        {
          "can_submit": bool,
          "items": list[dict],    # 每项简要合规结果
          "issues_count": int,    # 有问题的项目数
          "warning_count": int,   # 警告（<20%超标）项目数
          "summary": str,         # 一句话摘要
        }
    """
    item_results = []
    issues_count = 0
    warning_count = 0
    can_submit = True

    staff_level = await _get_applicant_level(db, tenant_id, applicant_id)

    for idx, item in enumerate(items):
        description = item.get("description", "")
        amount_fen = int(item.get("amount_fen", 0))
        expense_type = item.get("expense_type") or _infer_expense_type(description)

        # 城市：优先用传入参数，其次从描述推断
        city = destination_city
        if not city:
            for city_name in _KNOWN_CITIES:
                if city_name in description:
                    city = city_name
                    break

        try:
            result = await check_item_compliance(
                db=db,
                tenant_id=tenant_id,
                brand_id=brand_id,
                applicant_id=applicant_id,
                item_description=description,
                item_amount_fen=amount_fen,
                expense_type=expense_type,
                destination_city=city,
                is_daily_limit=False,
            )

            status = result["status"]
            if status in ("over_limit_minor", "over_limit_major"):
                issues_count += 1
                can_submit = False
            elif status == "compliant_with_warning":
                warning_count += 1

            # 精简输出（去掉冗余字段，减少前端解析负担）
            item_results.append({
                "index": idx,
                "description": description,
                "status": status,
                "compliant": result["compliant"],
                "limit_fen": result["limit_fen"],
                "over_rate": result["over_rate"],
                "allowed_amount_fen": result["allowed_amount_fen"],
                "compliance_action": result["compliance_action"],
                "suggestion": result["suggestion"],
                "message": result["message"],
            })

        except (OperationalError, SQLAlchemyError, ValueError) as exc:
            log.warning(
                "a3_pre_check_item_error",
                idx=idx,
                description=description,
                error=f"{type(exc).__name__}: {exc}",
            )
            # 单项异常：放行，不阻断整体预检
            item_results.append({
                "index": idx,
                "description": description,
                "status": "no_rule",
                "compliant": True,
                "limit_fen": None,
                "over_rate": None,
                "allowed_amount_fen": amount_fen,
                "compliance_action": "none",
                "suggestion": None,
                "message": "检查异常，已放行",
            })

    # 生成摘要
    if not can_submit:
        if issues_count == 1:
            summary = f"有 {issues_count} 项费用不合规，请处理后再提交"
        else:
            summary = f"有 {issues_count} 项费用不合规，请处理后再提交"
    elif warning_count > 0:
        summary = f"有 {warning_count} 项费用轻微超标，审批人将看到高亮提示"
    else:
        summary = "所有费用项合规，可直接提交"

    return {
        "can_submit": can_submit,
        "staff_level": staff_level,
        "destination_city": destination_city,
        "items": item_results,
        "issues_count": issues_count,
        "warning_count": warning_count,
        "summary": summary,
    }


# =============================================================================
# 8. Agent 统一入口
# =============================================================================

async def run(
    db: AsyncSession,
    tenant_id: UUID,
    trigger: str,
    payload: dict,
) -> dict:
    """
    A3 Agent 统一入口。

    trigger="application_submit"  → check_application_compliance(payload["application_id"])
    trigger="pre_check"           → pre_check_before_submit(payload)
    trigger="new_store_init"      → 新店开业时复制同品牌差标配置

    所有异常捕获记录日志，不向上抛出（Agent 失败不影响业务主流程）。
    """
    log.info(
        "a3_agent_run_start",
        agent=AgentType.STANDARD_COMPLIANCE,
        trigger=trigger,
        tenant_id=str(tenant_id),
    )

    try:
        if trigger == "application_submit":
            application_id = uuid.UUID(payload["application_id"])
            result = await check_application_compliance(
                db=db,
                tenant_id=tenant_id,
                application_id=application_id,
            )

            # 若需要通知主管，异步触发（不阻断主流程）
            if result.get("escalate_to_supervisor") and result.get("supervisor_id"):
                brand_id_raw = payload.get("brand_id")
                brand_id = uuid.UUID(brand_id_raw) if brand_id_raw else uuid.UUID(int=0)
                # 查询连续超标次数
                history = await _check_historical_compliance_rate(
                    db=db,
                    tenant_id=tenant_id,
                    applicant_id=uuid.UUID(payload["applicant_id"])
                    if payload.get("applicant_id") else application_id,
                )
                import asyncio
                asyncio.create_task(
                    notify_supervisor_of_repeated_violations(
                        db=db,
                        tenant_id=tenant_id,
                        brand_id=brand_id,
                        applicant_id=uuid.UUID(payload["applicant_id"])
                        if payload.get("applicant_id") else application_id,
                        application_id=application_id,
                        consecutive_count=history["consecutive_over_limit"],
                    )
                )

            return result

        elif trigger == "pre_check":
            brand_id = uuid.UUID(payload["brand_id"])
            applicant_id = uuid.UUID(payload["applicant_id"])
            items = payload.get("items", [])
            destination_city = payload.get("destination_city")
            return await pre_check_before_submit(
                db=db,
                tenant_id=tenant_id,
                brand_id=brand_id,
                applicant_id=applicant_id,
                items=items,
                destination_city=destination_city,
            )

        elif trigger == "new_store_init":
            # 新店开业：复制同品牌差标配置
            brand_id = uuid.UUID(payload["brand_id"])
            source_brand_id = uuid.UUID(payload["source_brand_id"])
            copied_count = await std_svc.init_brand_standards(
                db=db,
                tenant_id=tenant_id,
                brand_id=brand_id,
                source_brand_id=source_brand_id,
            )
            result = {
                "trigger": trigger,
                "brand_id": str(brand_id),
                "source_brand_id": str(source_brand_id),
                "copied_standards": copied_count,
                "message": f"已从来源品牌复制 {copied_count} 条差标规则",
            }
            await _log_agent_job(
                db=db,
                tenant_id=tenant_id,
                job_type="new_store_init",
                trigger_source="new_store_event",
                result=result,
            )
            return result

        else:
            unknown_result = {
                "error": f"未知 trigger 类型: {trigger}",
                "trigger": trigger,
            }
            log.error(
                "a3_agent_unknown_trigger",
                agent=AgentType.STANDARD_COMPLIANCE,
                trigger=trigger,
                tenant_id=str(tenant_id),
            )
            return unknown_result

    except (ValueError, KeyError, AttributeError, RuntimeError, OSError, SQLAlchemyError) as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        log.error(
            "a3_agent_run_unhandled_error",
            agent=AgentType.STANDARD_COMPLIANCE,
            trigger=trigger,
            tenant_id=str(tenant_id),
            error=error_msg,
            exc_info=True,
        )
        return {
            "trigger": trigger,
            "error": error_msg,
        }
