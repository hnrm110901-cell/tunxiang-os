"""
费用申请服务
负责费用申请的生命周期管理：创建草稿、更新、提交、查询、统计。
不直接处理审批逻辑（由 approval_engine_service 负责）。

金额约定：所有金额存储为分(fen)，入参/出参统一用分，展示层负责转换。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.events.src.emitter import emit_event

from ..agents import a3_standard_compliance as _a3_agent
from ..models.expense_application import (
    ExpenseApplication,
    ExpenseAttachment,
    ExpenseCategory,
    ExpenseItem,
    ExpenseScenario,
)
from ..models.expense_enums import ExpenseStatus
from ..models.expense_events import (
    EXPENSE_APPLICATION_SUBMITTED,
)

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _assert_tenant(obj: Any, tenant_id: uuid.UUID, label: str = "resource") -> None:
    """确保对象的 tenant_id 与当前请求一致，防止跨租户访问。"""
    if obj is None or obj.tenant_id != tenant_id:
        raise LookupError(f"{label} not found for tenant {tenant_id}")


# ─────────────────────────────────────────────────────────────────────────────
# 费用申请 CRUD
# ─────────────────────────────────────────────────────────────────────────────


async def create_application(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    brand_id: uuid.UUID,
    store_id: uuid.UUID,
    applicant_id: uuid.UUID,
    scenario_id: uuid.UUID,
    title: str,
    items: list[dict],
    purpose: Optional[str] = None,
    notes: Optional[str] = None,
    metadata: Optional[dict] = None,
    legal_entity_id: Optional[uuid.UUID] = None,
) -> ExpenseApplication:
    """创建费用申请草稿。

    items 格式：
        [{"category_id": UUID, "description": str, "amount": int,
          "quantity": float, "unit": str, "expense_date": date, "notes": str}]

    金额（amount）单位为分(fen)。
    """
    log = logger.bind(tenant_id=str(tenant_id), store_id=str(store_id), applicant_id=str(applicant_id))

    if not items:
        raise ValueError("items must contain at least one expense line")

    total_amount = sum(item["amount"] for item in items)

    application = ExpenseApplication(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        brand_id=brand_id,
        store_id=store_id,
        applicant_id=applicant_id,
        scenario_id=scenario_id,
        title=title,
        total_amount=total_amount,
        currency="CNY",
        status=ExpenseStatus.DRAFT.value,
        legal_entity_id=legal_entity_id,
        purpose=purpose,
        notes=notes,
        metadata=metadata or {},
    )
    db.add(application)

    # 批量创建明细行（先 flush 获取 application.id）
    await db.flush()

    expense_items = []
    for item in items:
        expense_item = ExpenseItem(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            application_id=application.id,
            category_id=item["category_id"],
            description=item["description"],
            amount=item["amount"],
            quantity=item.get("quantity", 1),
            unit=item.get("unit"),
            invoice_id=item.get("invoice_id"),
            expense_date=item["expense_date"],
            notes=item.get("notes"),
        )
        expense_items.append(expense_item)

    db.add_all(expense_items)
    await db.flush()

    log.info(
        "expense_application_draft_created",
        application_id=str(application.id),
        total_amount=total_amount,
        item_count=len(expense_items),
    )

    return application


async def get_application(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
) -> ExpenseApplication:
    """查询单条申请，预加载 items、attachments、scenario。

    Raises:
        LookupError: 找不到或跨租户访问时抛出（路由层转换为 404）。
    """
    stmt = (
        select(ExpenseApplication)
        .where(
            ExpenseApplication.id == application_id,
            ExpenseApplication.tenant_id == tenant_id,
            ExpenseApplication.is_deleted == False,  # noqa: E712
        )
        .options(
            selectinload(ExpenseApplication.items).selectinload(ExpenseItem.category),
            selectinload(ExpenseApplication.attachments),
            selectinload(ExpenseApplication.scenario),
        )
    )
    result = await db.execute(stmt)
    application = result.scalar_one_or_none()

    if application is None:
        raise LookupError(f"ExpenseApplication {application_id} not found for tenant {tenant_id}")

    return application


async def list_applications(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    applicant_id: Optional[uuid.UUID] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ExpenseApplication], int]:
    """列出申请，支持多条件过滤，按 created_at DESC 排序。

    Returns:
        (items, total_count)
    """
    base_where = [
        ExpenseApplication.tenant_id == tenant_id,
        ExpenseApplication.is_deleted == False,  # noqa: E712
    ]

    if store_id is not None:
        base_where.append(ExpenseApplication.store_id == store_id)
    if status is not None:
        base_where.append(ExpenseApplication.status == status)
    if applicant_id is not None:
        base_where.append(ExpenseApplication.applicant_id == applicant_id)
    if date_from is not None:
        base_where.append(ExpenseApplication.created_at >= date_from)
    if date_to is not None:
        base_where.append(ExpenseApplication.created_at <= date_to)

    count_stmt = select(func.count()).select_from(ExpenseApplication).where(*base_where)
    count_result = await db.execute(count_stmt)
    total_count = count_result.scalar_one()

    offset = (page - 1) * page_size
    items_stmt = (
        select(ExpenseApplication)
        .where(*base_where)
        .order_by(ExpenseApplication.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .options(
            selectinload(ExpenseApplication.scenario),
        )
    )
    items_result = await db.execute(items_stmt)
    items = list(items_result.scalars().all())

    return items, total_count


async def update_application(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    **kwargs: Any,
) -> ExpenseApplication:
    """更新草稿申请。

    只允许 DRAFT 状态更新。可更新字段：title、purpose、notes、metadata、items。
    若 kwargs 包含 items（list[dict]），则先删除旧明细行再重建，并重新计算 total_amount。
    """
    application = await get_application(db, tenant_id, application_id)

    if application.status != ExpenseStatus.DRAFT.value:
        raise ValueError(
            f"Cannot update application in status '{application.status}'. Only DRAFT applications can be edited."
        )

    # 更新主字段
    allowed_fields = {"title", "purpose", "notes", "metadata"}
    for field in allowed_fields:
        if field in kwargs:
            setattr(application, field, kwargs[field])

    # 如果传了 items，重建明细行
    if "items" in kwargs:
        new_items_data: list[dict] = kwargs["items"]
        if not new_items_data:
            raise ValueError("items must contain at least one expense line")

        # 删除旧明细行（关系已配置 cascade delete-orphan，清空列表即可）
        application.items.clear()
        await db.flush()

        new_items = []
        for item in new_items_data:
            expense_item = ExpenseItem(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                application_id=application.id,
                category_id=item["category_id"],
                description=item["description"],
                amount=item["amount"],
                quantity=item.get("quantity", 1),
                unit=item.get("unit"),
                invoice_id=item.get("invoice_id"),
                expense_date=item["expense_date"],
                notes=item.get("notes"),
            )
            new_items.append(expense_item)

        db.add_all(new_items)
        application.total_amount = sum(item["amount"] for item in new_items_data)

    await db.flush()

    logger.info(
        "expense_application_updated",
        tenant_id=str(tenant_id),
        application_id=str(application_id),
        updated_fields=list(kwargs.keys()),
    )

    return application


async def submit_application(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    submitter_id: uuid.UUID,
    compliance_explanation: Optional[str] = None,
) -> ExpenseApplication:
    """提交费用申请（草稿 → 已提交）。

    提交前通过 A3 差标合规 Agent 执行合规检查：
      - 超标 >50%：截断超出部分（amount_fen = limit_fen），备注中记录原始金额和超标率
      - 超标 20%-50%：必须提供 compliance_explanation，否则拒绝提交（ValueError）
      - 超标 <20%：允许提交，备注中追加警告信息

    仅修改申请状态，审批实例由 approval_engine_service.create_approval_instance() 创建。
    提交后广播事件 EXPENSE_APPLICATION_SUBMITTED 至事件总线。
    """
    application = await get_application(db, tenant_id, application_id)

    if application.status != ExpenseStatus.DRAFT.value:
        raise ValueError(
            f"Cannot submit application in status '{application.status}'. Only DRAFT applications can be submitted."
        )

    # ── A3 差标合规检查 ────────────────────────────────────────────────────────
    log = logger.bind(
        tenant_id=str(tenant_id),
        application_id=str(application_id),
        submitter_id=str(submitter_id),
    )
    try:
        compliance_result = await _a3_agent.check_application_compliance(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
        )
        log.info(
            "a3_compliance_check_done",
            overall_status=compliance_result.get("overall_status"),
            can_submit=compliance_result.get("can_submit"),
            total_over_amount_fen=compliance_result.get("total_over_amount_fen", 0),
        )

        overall_status = compliance_result.get("overall_status", "compliant")
        item_results: list[dict] = compliance_result.get("items", [])

        # 遍历每个明细行，执行截断 / 校验说明 / 记录警告
        items_need_explanation: list[int] = compliance_result.get("required_explanation_items", [])

        # 先处理 >50% 截断项（over_limit_major）——无论 can_submit，直接截断
        for item_result in item_results:
            if item_result.get("status") == "over_limit_major":
                item_id_str = item_result.get("item_id")
                limit_fen: Optional[int] = item_result.get("limit_fen")
                original_fen: int = item_result.get("item_amount_fen", 0)
                over_rate: float = item_result.get("over_rate") or 0.0

                if item_id_str is None or limit_fen is None:
                    log.warning(
                        "a3_truncation_skipped_missing_fields",
                        item_result=item_result,
                    )
                    continue

                try:
                    item_uuid = uuid.UUID(item_id_str)
                except ValueError:
                    log.warning(
                        "a3_truncation_skipped_invalid_uuid",
                        item_id=item_id_str,
                    )
                    continue

                # 定位 expense_item 并截断金额
                stmt = select(ExpenseItem).where(
                    ExpenseItem.id == item_uuid,
                    ExpenseItem.tenant_id == tenant_id,
                )
                result = await db.execute(stmt)
                expense_item = result.scalar_one_or_none()

                if expense_item is None:
                    log.warning(
                        "a3_truncation_skipped_item_not_found",
                        item_id=item_id_str,
                        tenant_id=str(tenant_id),
                    )
                    continue

                original_yuan = original_fen / 100
                over_pct_str = f"{over_rate * 100:.1f}%"
                truncation_note = (
                    f"[系统截断] 原申请金额 {original_yuan:.2f} 元，"
                    f"超标率 {over_pct_str}，已截断至差标限额 {limit_fen / 100:.2f} 元"
                )

                expense_item.amount = limit_fen
                existing_notes = expense_item.notes or ""
                expense_item.notes = f"{existing_notes}；{truncation_note}" if existing_notes else truncation_note

                log.info(
                    "a3_item_truncated",
                    item_id=item_id_str,
                    original_fen=original_fen,
                    limit_fen=limit_fen,
                    over_rate=over_rate,
                )

        # 重新计算 total_amount（截断后）
        all_items_stmt = select(ExpenseItem).where(
            ExpenseItem.application_id == application_id,
            ExpenseItem.tenant_id == tenant_id,
            ExpenseItem.is_deleted == False,  # noqa: E712
        )
        all_items_result = await db.execute(all_items_stmt)
        all_items = list(all_items_result.scalars().all())
        application.total_amount = sum(i.amount for i in all_items)

        # 处理 20%-50% 超标项：必须有 compliance_explanation
        if items_need_explanation:
            if not compliance_explanation or not compliance_explanation.strip():
                raise ValueError(
                    f"申请中有 {len(items_need_explanation)} 个费用项超标20%-50%，"
                    "提交时必须在请求中提供 compliance_explanation（超标说明）"
                )
            # 将说明追加到申请备注
            existing_app_notes = application.notes or ""
            explanation_note = f"[超标说明] {compliance_explanation.strip()}"
            application.notes = f"{existing_app_notes}；{explanation_note}" if existing_app_notes else explanation_note
            log.info(
                "a3_compliance_explanation_recorded",
                items_need_explanation=items_need_explanation,
            )

        # 处理 <20% 警告项：允许提交，标记警告到申请 metadata
        if overall_status == "compliant" and compliance_result.get("total_over_amount_fen", 0) > 0:
            application.metadata = {
                **(application.metadata or {}),
                "compliance_warning": compliance_result.get("summary_message", ""),
            }

        await db.flush()

    except ValueError:
        # ValueError 是业务拒绝，直接向上层传播
        raise
    except Exception as exc:
        # A3 Agent 异常不阻断提交流程，但必须记录日志
        log.error(
            "a3_compliance_check_failed_non_blocking",
            error=f"{type(exc).__name__}: {exc}",
            exc_info=True,
        )
    # ── A3 合规检查结束 ────────────────────────────────────────────────────────

    now = _now_utc()
    application.status = ExpenseStatus.SUBMITTED.value
    application.submitted_at = now
    await db.flush()

    # 获取场景代码（用于事件 payload）
    scenario_code = ""
    if application.scenario is not None:
        scenario_code = application.scenario.code
    else:
        # scenario 未预加载时单独查
        scenario_stmt = select(ExpenseScenario).where(ExpenseScenario.id == application.scenario_id)
        scenario_result = await db.execute(scenario_stmt)
        scenario = scenario_result.scalar_one_or_none()
        scenario_code = scenario.code if scenario else ""

    logger.info(
        "expense_application_submitted",
        tenant_id=str(tenant_id),
        application_id=str(application_id),
        submitter_id=str(submitter_id),
        total_amount=application.total_amount,
        scenario_code=scenario_code,
    )

    # 旁路发射事件（不阻塞主业务，失败降级）
    asyncio.create_task(
        emit_event(
            event_type=EXPENSE_APPLICATION_SUBMITTED,
            tenant_id=tenant_id,
            stream_id=str(application_id),
            payload={
                "application_id": str(application_id),
                "tenant_id": str(tenant_id),
                "store_id": str(application.store_id),
                "applicant_id": str(application.applicant_id),
                "submitter_id": str(submitter_id),
                "scenario_code": scenario_code,
                "total_amount": application.total_amount,
                "submitted_at": now.isoformat(),
            },
            store_id=application.store_id,
            source_service="tx-expense",
            metadata={"operator_id": str(submitter_id)},
        )
    )

    return application


async def add_attachment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    file_name: str,
    file_url: str,
    file_type: Optional[str],
    file_size: Optional[int],
    uploaded_by: uuid.UUID,
) -> ExpenseAttachment:
    """为申请添加附件（发票/收据扫描件等）。

    申请状态必须是 DRAFT 或 SUBMITTED；审批进行中（IN_REVIEW 及之后）不允许补传。
    """
    application = await get_application(db, tenant_id, application_id)

    allowed_statuses = {ExpenseStatus.DRAFT.value, ExpenseStatus.SUBMITTED.value}
    if application.status not in allowed_statuses:
        raise ValueError(
            f"Cannot add attachments to application in status '{application.status}'. "
            "Attachments can only be added when status is DRAFT or SUBMITTED."
        )

    attachment = ExpenseAttachment(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        application_id=application_id,
        file_name=file_name,
        file_url=file_url,
        file_type=file_type,
        file_size=file_size,
        uploaded_by=uploaded_by,
    )
    db.add(attachment)
    await db.flush()

    logger.info(
        "expense_attachment_added",
        tenant_id=str(tenant_id),
        application_id=str(application_id),
        file_name=file_name,
        uploaded_by=str(uploaded_by),
    )

    return attachment


async def delete_application(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    operator_id: uuid.UUID,
) -> bool:
    """逻辑删除申请（is_deleted=True）。

    只允许 DRAFT 状态撤回。其他状态抛出 ValueError（路由层转换为 400）。
    """
    application = await get_application(db, tenant_id, application_id)

    if application.status != ExpenseStatus.DRAFT.value:
        raise ValueError(
            f"Cannot delete application in status '{application.status}'. "
            "Only DRAFT applications can be withdrawn. "
            "To cancel a submitted application, use the cancellation workflow."
        )

    application.is_deleted = True
    await db.flush()

    logger.info(
        "expense_application_deleted",
        tenant_id=str(tenant_id),
        application_id=str(application_id),
        operator_id=str(operator_id),
        previous_status=ExpenseStatus.DRAFT.value,
    )

    return True


# ─────────────────────────────────────────────────────────────────────────────
# 个人视图
# ─────────────────────────────────────────────────────────────────────────────


async def get_my_applications(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    applicant_id: uuid.UUID,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ExpenseApplication], int]:
    """按申请人查询我的申请列表，支持状态过滤，按 created_at DESC 排序。"""
    return await list_applications(
        db,
        tenant_id=tenant_id,
        applicant_id=applicant_id,
        status=status,
        page=page,
        page_size=page_size,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 统计
# ─────────────────────────────────────────────────────────────────────────────


async def get_stats(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: Optional[uuid.UUID] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> dict:
    """返回费用申请统计数据。

    Returns::

        {
            "total_count": int,
            "total_amount": int,          # 分(fen)
            "by_status": {status: count},
            "by_category": [{"category_name": str, "amount": int, "count": int}],
            "pending_approval_count": int,
        }
    """
    base_where = [
        ExpenseApplication.tenant_id == tenant_id,
        ExpenseApplication.is_deleted == False,  # noqa: E712
    ]
    if store_id is not None:
        base_where.append(ExpenseApplication.store_id == store_id)
    if date_from is not None:
        base_where.append(ExpenseApplication.created_at >= date_from)
    if date_to is not None:
        base_where.append(ExpenseApplication.created_at <= date_to)

    # 总数 + 总金额
    total_stmt = select(
        func.count().label("total_count"),
        func.coalesce(func.sum(ExpenseApplication.total_amount), 0).label("total_amount"),
    ).where(*base_where)
    total_result = await db.execute(total_stmt)
    total_row = total_result.mappings().one()
    total_count = int(total_row["total_count"])
    total_amount = int(total_row["total_amount"])

    # 按状态分组
    by_status_stmt = (
        select(
            ExpenseApplication.status,
            func.count().label("count"),
        )
        .where(*base_where)
        .group_by(ExpenseApplication.status)
    )
    by_status_result = await db.execute(by_status_stmt)
    by_status = {row["status"]: int(row["count"]) for row in by_status_result.mappings().all()}

    # 待审批数（SUBMITTED + IN_REVIEW）
    pending_statuses = [ExpenseStatus.SUBMITTED.value, ExpenseStatus.IN_REVIEW.value]
    pending_approval_count = sum(by_status.get(s, 0) for s in pending_statuses)

    # 按科目统计（JOIN expense_items + expense_categories）
    by_category_stmt = (
        select(
            ExpenseCategory.name.label("category_name"),
            func.coalesce(func.sum(ExpenseItem.amount), 0).label("amount"),
            func.count(ExpenseItem.id.distinct()).label("count"),
        )
        .join(ExpenseItem, ExpenseItem.category_id == ExpenseCategory.id)
        .join(ExpenseApplication, ExpenseApplication.id == ExpenseItem.application_id)
        .where(
            ExpenseItem.tenant_id == tenant_id,
            ExpenseApplication.is_deleted == False,  # noqa: E712
            *([ExpenseApplication.store_id == store_id] if store_id else []),
            *([ExpenseApplication.created_at >= date_from] if date_from else []),
            *([ExpenseApplication.created_at <= date_to] if date_to else []),
        )
        .group_by(ExpenseCategory.id, ExpenseCategory.name)
        .order_by(func.sum(ExpenseItem.amount).desc())
    )
    by_category_result = await db.execute(by_category_stmt)
    by_category = [
        {
            "category_name": row["category_name"],
            "amount": int(row["amount"]),
            "count": int(row["count"]),
        }
        for row in by_category_result.mappings().all()
    ]

    return {
        "total_count": total_count,
        "total_amount": total_amount,
        "by_status": by_status,
        "by_category": by_category,
        "pending_approval_count": pending_approval_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 场景 & 科目
# ─────────────────────────────────────────────────────────────────────────────


async def list_scenarios(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[ExpenseScenario]:
    """返回激活的场景列表，按 sort_order 排序。"""
    stmt = (
        select(ExpenseScenario)
        .where(
            ExpenseScenario.tenant_id == tenant_id,
            ExpenseScenario.is_active == True,  # noqa: E712
            ExpenseScenario.is_deleted == False,  # noqa: E712
        )
        .order_by(ExpenseScenario.sort_order.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_categories(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[dict]:
    """返回层级科目树（递归构建树形结构）。

    Returns 格式::

        [
            {
                "id": str,
                "name": str,
                "code": str,
                "parent_id": str | None,
                "sort_order": int,
                "is_system": bool,
                "children": [...],  # 递归
            },
            ...
        ]
    """
    stmt = (
        select(ExpenseCategory)
        .where(
            ExpenseCategory.tenant_id == tenant_id,
            ExpenseCategory.is_active == True,  # noqa: E712
            ExpenseCategory.is_deleted == False,  # noqa: E712
        )
        .order_by(ExpenseCategory.sort_order.asc())
    )
    result = await db.execute(stmt)
    all_categories = list(result.scalars().all())

    # 构建树形结构
    def _build_tree(parent_id: Optional[uuid.UUID]) -> list[dict]:
        nodes = []
        for cat in all_categories:
            if cat.parent_id == parent_id:
                node = {
                    "id": str(cat.id),
                    "name": cat.name,
                    "code": cat.code,
                    "description": cat.description,
                    "parent_id": str(cat.parent_id) if cat.parent_id else None,
                    "sort_order": cat.sort_order,
                    "is_system": cat.is_system,
                    "children": _build_tree(cat.id),
                }
                nodes.append(node)
        return nodes

    return _build_tree(None)
