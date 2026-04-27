"""
费用申请 API 路由

负责费用申请的创建、查询、提交、附件上传等操作。
共12个端点，覆盖费用申请全生命周期（草稿→提交→审批→归档）。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from src.models.expense_enums import ExpenseStatus

try:
    from src.services.expense_application_service import ExpenseApplicationService

    _expense_svc = ExpenseApplicationService()
except ImportError:
    _expense_svc = None  # type: ignore[assignment]

try:
    from src.services.approval_engine_service import ApprovalEngineService

    _approval_svc = ApprovalEngineService()
except ImportError:
    _approval_svc = None  # type: ignore[assignment]

router = APIRouter()
log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 依赖注入
# ---------------------------------------------------------------------------


async def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> UUID:
    try:
        return UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的租户ID格式")


async def get_current_user(x_user_id: str = Header(..., alias="X-User-ID")) -> UUID:
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户ID格式")


def _get_expense_service() -> "ExpenseApplicationService":
    if _expense_svc is None:
        raise HTTPException(status_code=503, detail="费用申请服务暂不可用，请稍后重试")
    return _expense_svc


def _get_approval_service() -> "ApprovalEngineService":
    if _approval_svc is None:
        raise HTTPException(status_code=503, detail="审批引擎服务暂不可用，请稍后重试")
    return _approval_svc


# ---------------------------------------------------------------------------
# Pydantic Schema
# ---------------------------------------------------------------------------


class ExpenseItemCreate(BaseModel):
    category_id: UUID
    description: str
    amount: int  # 分(fen)，不使用浮点，1元=100分
    quantity: float = 1.0
    unit: Optional[str] = None
    expense_date: date
    notes: Optional[str] = None


class ExpenseApplicationCreate(BaseModel):
    brand_id: UUID
    store_id: UUID
    scenario_id: UUID
    title: str = Field(..., max_length=200)
    items: List[ExpenseItemCreate] = Field(..., min_length=1)
    purpose: Optional[str] = None
    notes: Optional[str] = None
    metadata: dict = {}


class ExpenseApplicationUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    purpose: Optional[str] = None
    notes: Optional[str] = None
    items: Optional[List[ExpenseItemCreate]] = None
    metadata: Optional[dict] = None


class SubmitApplicationRequest(BaseModel):
    compliance_explanation: Optional[str] = Field(
        None,
        description=("超标说明（当费用项超标20%-50%时必填）。说明将记录到申请备注，供审批人参考。"),
        max_length=500,
    )


class PaginatedResponse(BaseModel):
    data: List[Any]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# 端点实现
# ---------------------------------------------------------------------------


@router.post("/applications", status_code=status.HTTP_201_CREATED)
async def create_application(
    body: ExpenseApplicationCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    创建费用申请（草稿状态）

    - 金额字段 amount 单位为分(fen)，例如：500分 = 5元
    - 创建后状态为 draft，需调用 /submit 提交审批
    """
    svc = _get_expense_service()
    try:
        items_data = [item.model_dump() for item in body.items]
        result = await svc.create_application(
            db=db,
            tenant_id=tenant_id,
            brand_id=body.brand_id,
            store_id=body.store_id,
            applicant_id=current_user_id,
            scenario_id=body.scenario_id,
            title=body.title,
            items=items_data,
            purpose=body.purpose,
            notes=body.notes,
            metadata=body.metadata,
        )
        log.info("expense_application_created", tenant_id=str(tenant_id), applicant_id=str(current_user_id))
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("expense_application_create_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="创建费用申请失败，请稍后重试")


@router.get("/applications")
async def list_applications(
    store_id: Optional[UUID] = Query(None, description="门店ID过滤"),
    application_status: Optional[ExpenseStatus] = Query(None, alias="status", description="申请状态过滤"),
    applicant_id: Optional[UUID] = Query(None, description="申请人ID过滤"),
    date_from: Optional[date] = Query(None, description="开始日期（含）"),
    date_to: Optional[date] = Query(None, description="结束日期（含）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """
    查询费用申请列表

    支持按门店、状态、申请人、日期范围过滤，支持分页。
    """
    svc = _get_expense_service()
    try:
        items, total = await svc.list_applications(
            db=db,
            tenant_id=tenant_id,
            store_id=store_id,
            status=application_status,
            applicant_id=applicant_id,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
        return PaginatedResponse(data=items, total=total, page=page, page_size=page_size)
    except Exception as exc:
        log.error("expense_applications_list_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="查询申请列表失败，请稍后重试")


@router.get("/applications/{application_id}")
async def get_application(
    application_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """获取费用申请详情"""
    svc = _get_expense_service()
    try:
        result = await svc.get_application(db=db, tenant_id=tenant_id, application_id=application_id)
        if result is None:
            raise HTTPException(status_code=404, detail="费用申请不存在或无权访问")
        return {"ok": True, "data": result}
    except HTTPException:
        raise
    except Exception as exc:
        log.error("expense_application_get_failed", error=str(exc), application_id=str(application_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取申请详情失败，请稍后重试")


@router.put("/applications/{application_id}")
async def update_application(
    application_id: UUID,
    body: ExpenseApplicationUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    更新草稿费用申请

    - 只允许修改 draft 状态的申请
    - 金额字段 amount 单位为分(fen)
    """
    svc = _get_expense_service()
    try:
        update_kwargs: Dict[str, Any] = {}
        if body.title is not None:
            update_kwargs["title"] = body.title
        if body.purpose is not None:
            update_kwargs["purpose"] = body.purpose
        if body.notes is not None:
            update_kwargs["notes"] = body.notes
        if body.items is not None:
            update_kwargs["items"] = [item.model_dump() for item in body.items]
        if body.metadata is not None:
            update_kwargs["metadata"] = body.metadata

        result = await svc.update_application(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
            **update_kwargs,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="费用申请不存在或无权修改")
        log.info("expense_application_updated", application_id=str(application_id), tenant_id=str(tenant_id))
        return {"ok": True, "data": result}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error(
            "expense_application_update_failed", error=str(exc), application_id=str(application_id), exc_info=True
        )
        raise HTTPException(status_code=500, detail="更新申请失败，请稍后重试")


@router.post("/applications/{application_id}/submit")
async def submit_application(
    application_id: UUID,
    body: SubmitApplicationRequest = SubmitApplicationRequest(),
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    提交费用申请（触发审批流）

    - 只允许提交 draft 状态的申请
    - 提交前由 A3 差标合规 Agent 自动检查费用项合规性：
      - 超标 >50%：超出部分自动截断至差标限额，备注中记录原始金额和超标率
      - 超标 20%-50%：必须在请求体中提供 compliance_explanation，否则返回 400
      - 超标 <20%：允许提交，审批单中高亮显示警告
    - 提交后自动创建审批实例，状态变为 submitted
    - 审批路由根据金额和场景自动匹配
    """
    expense_svc = _get_expense_service()
    approval_svc = _get_approval_service()
    try:
        # 先提交申请（含 A3 合规检查）
        submitted = await expense_svc.submit_application(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
            submitter_id=current_user_id,
            compliance_explanation=body.compliance_explanation,
        )
        if submitted is None:
            raise HTTPException(status_code=404, detail="费用申请不存在或无权提交")

        # 获取 brand_id（从提交结果或单独查询）
        brand_id = getattr(submitted, "brand_id", None) or (
            submitted.get("brand_id") if isinstance(submitted, dict) else None
        )

        # 创建审批实例
        approval_instance = await approval_svc.create_approval_instance(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
            brand_id=brand_id,
        )

        log.info(
            "expense_application_submitted",
            application_id=str(application_id),
            tenant_id=str(tenant_id),
        )
        return {
            "ok": True,
            "data": {
                "application": submitted,
                "approval_instance": approval_instance,
            },
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error(
            "expense_application_submit_failed", error=str(exc), application_id=str(application_id), exc_info=True
        )
        raise HTTPException(status_code=500, detail="提交申请失败，请稍后重试")


@router.post("/applications/{application_id}/attachments", status_code=status.HTTP_201_CREATED)
async def add_attachment(
    application_id: UUID,
    file: UploadFile = File(..., description="附件文件（支持图片、PDF格式，最大10MB）"),
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    上传费用申请附件（发票图片/PDF）

    - 支持格式：jpg/jpeg/png/pdf
    - 文件存储：腾讯云 COS（invoices 目录），Mock 模式下返回本地路径
    - 文件大小限制：10MB
    """
    svc = _get_expense_service()

    # 文件类型校验
    allowed_content_types = {"image/jpeg", "image/png", "image/jpg", "application/pdf"}
    if file.content_type not in allowed_content_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式：{file.content_type}，仅支持 JPG/PNG/PDF",
        )

    # 文件大小校验（10MB）
    MAX_FILE_SIZE = 10 * 1024 * 1024
    file_content = await file.read()
    if len(file_content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过限制（最大10MB）")

    try:
        from shared.integrations.cos_upload import get_cos_upload_service

        cos = get_cos_upload_service()
        upload_result = await cos.upload_file(
            file_bytes=file_content,
            filename=file.filename or "attachment",
            content_type=file.content_type or "application/octet-stream",
            folder="invoices",
        )
        file_url = upload_result["url"]

        result = await svc.add_attachment(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
            file_name=file.filename or "attachment",
            file_url=file_url,
            file_type=file.content_type or "application/octet-stream",
            file_size=len(file_content),
            uploaded_by=current_user_id,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="费用申请不存在或无权操作")

        log.info(
            "expense_attachment_added",
            application_id=str(application_id),
            file_name=file.filename,
            file_size=len(file_content),
        )
        return {"ok": True, "data": result}
    except HTTPException:
        raise
    except Exception as exc:
        log.error("expense_attachment_add_failed", error=str(exc), application_id=str(application_id), exc_info=True)
        raise HTTPException(status_code=500, detail="上传附件失败，请稍后重试")


@router.get("/applications/{application_id}/approval-trace")
async def get_approval_trace(
    application_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    查询审批轨迹

    返回该申请的完整审批链，包含每个节点的审批人、动作、意见、时间。
    """
    svc = _get_approval_service()
    try:
        result = await svc.get_approval_trace(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="审批记录不存在")
        return {"ok": True, "data": result}
    except HTTPException:
        raise
    except Exception as exc:
        log.error("approval_trace_get_failed", error=str(exc), application_id=str(application_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取审批轨迹失败，请稍后重试")


@router.get("/my-applications")
async def get_my_applications(
    application_status: Optional[ExpenseStatus] = Query(None, alias="status", description="申请状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """
    我的申请列表

    查询当前登录用户提交的所有费用申请，支持按状态过滤，支持分页。
    """
    svc = _get_expense_service()
    try:
        items, total = await svc.get_my_applications(
            db=db,
            tenant_id=tenant_id,
            applicant_id=current_user_id,
            status=application_status,
            page=page,
            page_size=page_size,
        )
        return PaginatedResponse(data=items, total=total, page=page, page_size=page_size)
    except Exception as exc:
        log.error("my_applications_list_failed", error=str(exc), user_id=str(current_user_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取我的申请列表失败，请稍后重试")


@router.get("/scenarios")
async def list_scenarios(
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    获取费用申请场景列表

    返回系统预置的10个费用场景（日常报销/备用金/出差/招待等）。
    """
    svc = _get_expense_service()
    try:
        items = await svc.list_scenarios(db=db, tenant_id=tenant_id)
        return {"ok": True, "data": items}
    except Exception as exc:
        log.error("scenarios_list_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取场景列表失败，请稍后重试")


@router.get("/categories")
async def list_categories(
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    获取费用科目树（层级结构）

    返回系统预置的12类费用科目，以树形层级展示（父子关系）。
    """
    svc = _get_expense_service()
    try:
        items = await svc.list_categories(db=db, tenant_id=tenant_id)
        return {"ok": True, "data": items}
    except Exception as exc:
        log.error("categories_list_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取科目列表失败，请稍后重试")


@router.get("/stats")
async def get_stats(
    store_id: Optional[UUID] = Query(None, description="门店ID（不传则汇总所有门店）"),
    date_from: Optional[date] = Query(None, description="统计开始日期"),
    date_to: Optional[date] = Query(None, description="统计结束日期"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    费用申请统计

    按门店/科目/状态汇总统计，金额单位为分(fen)。
    """
    svc = _get_expense_service()
    try:
        result = await svc.get_stats(
            db=db,
            tenant_id=tenant_id,
            store_id=store_id,
            date_from=date_from,
            date_to=date_to,
        )
        return {"ok": True, "data": result}
    except Exception as exc:
        log.error("expense_stats_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取统计数据失败，请稍后重试")


@router.delete("/applications/{application_id}")
async def delete_application(
    application_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    撤回/删除费用申请

    - 只允许撤回 draft 状态的申请
    - 已提交或审批中的申请无法直接删除
    """
    svc = _get_expense_service()
    try:
        result = await svc.delete_application(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
            operator_id=current_user_id,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="费用申请不存在或无权撤回")
        log.info(
            "expense_application_deleted",
            application_id=str(application_id),
            operator_id=str(current_user_id),
        )
        return {"ok": True, "message": "申请已成功撤回"}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error(
            "expense_application_delete_failed", error=str(exc), application_id=str(application_id), exc_info=True
        )
        raise HTTPException(status_code=500, detail="撤回申请失败，请稍后重试")


@router.get("/health-check")
async def route_health() -> Dict[str, Any]:
    """路由健康检查"""
    return {
        "module": "expense_routes",
        "status": "ready",
        "expense_service": "available" if _expense_svc is not None else "unavailable",
        "approval_service": "available" if _approval_svc is not None else "unavailable",
    }


# ─── 差标相关端点（P0-S2新增）───────────────────────────────────────────────

import src.services.expense_standard_service as _std_svc  # noqa: E402


class ExpenseStandardCreate(BaseModel):
    brand_id: UUID
    name: str
    staff_level: str  # StaffLevel 枚举值（store_staff/store_manager/region_manager/brand_manager/executive）
    city_tier: str  # CityTier 枚举值（tier1/tier2/tier3/other）
    expense_type: str  # TravelExpenseType 枚举值（accommodation/meal/transport/other_travel）
    daily_limit: int  # 每日限额，单位分(fen)，1元=100分
    single_limit: Optional[int] = None  # 单笔限额，单位分(fen)，None=不限单笔
    notes: Optional[str] = None
    effective_from: Optional[date] = None


class ComplianceCheckRequest(BaseModel):
    brand_id: UUID
    staff_level: str
    destination_city: str
    expense_type: str
    amount: int  # 申请金额，单位分(fen)
    is_daily: bool = False


@router.get("/standards")
async def list_standards(
    brand_id: UUID = Query(..., description="品牌ID"),
    staff_level: Optional[str] = Query(
        None, description="员工职级过滤（store_staff/store_manager/region_manager/brand_manager/executive）"
    ),
    city_tier: Optional[str] = Query(None, description="城市级别过滤（tier1/tier2/tier3/other）"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """查询差标规则列表

    按职级 + 城市级别 + 费用类型排序返回，支持多条件过滤。
    仅返回 is_active=True 的活跃规则。金额单位为分(fen)。
    """
    try:
        items = await _std_svc.list_standards(
            db=db,
            tenant_id=tenant_id,
            brand_id=brand_id,
            staff_level=staff_level,
            city_tier=city_tier,
            is_active=True,
        )
        return {"ok": True, "data": items, "total": len(items)}
    except Exception as exc:
        log.error("standards_list_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="查询差标列表失败，请稍后重试")


@router.post("/standards", status_code=201)
async def create_standard(
    body: ExpenseStandardCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """创建差标规则

    若同维度（brand_id + staff_level + city_tier + expense_type）已有活跃规则，
    系统自动版本化：旧规则 effective_to 设为今天，新规则立即生效。
    不硬删除历史记录，保留完整审计轨迹。金额单位为分(fen)。
    """
    try:
        result = await _std_svc.create_standard(
            db=db,
            tenant_id=tenant_id,
            brand_id=body.brand_id,
            name=body.name,
            staff_level=body.staff_level,
            city_tier=body.city_tier,
            expense_type=body.expense_type,
            daily_limit=body.daily_limit,
            single_limit=body.single_limit,
            notes=body.notes,
            effective_from=body.effective_from,
        )
        await db.commit()
        log.info(
            "expense_standard_created_via_api",
            tenant_id=str(tenant_id),
            brand_id=str(body.brand_id),
            standard_id=str(result.id),
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("standard_create_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="创建差标规则失败，请稍后重试")


@router.post("/standards/check-compliance")
async def check_compliance(
    body: ComplianceCheckRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """实时差标合规检查（申请提交前调用）

    性能目标：<100ms（利用城市级别内存缓存，无慢查询）。

    返回合规状态及所需操作：
    - compliant=True, action_required="none"：直接通过
    - compliant=True, action_required="none" (over_limit_minor)：高亮提示，可提交
    - compliant=False, action_required="add_note"：超标20-50%，必须填写说明
    - compliant=False, action_required="special_approval"：超标>50%，走特殊审批通道
    - status="no_rule"：无差标配置，自动通过

    所有金额单位为分(fen)。
    """
    try:
        result = await _std_svc.check_compliance(
            db=db,
            tenant_id=tenant_id,
            brand_id=body.brand_id,
            staff_level=body.staff_level,
            destination_city=body.destination_city,
            expense_type=body.expense_type,
            amount=body.amount,
            is_daily=body.is_daily,
        )
        return {"ok": True, "data": result}
    except Exception as exc:
        log.error("compliance_check_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="合规检查失败，请稍后重试")


@router.get("/standards/template")
async def get_standards_template() -> Dict[str, Any]:
    """获取餐饮行业推荐差标模板（无需认证）

    返回适合连锁餐饮品牌的推荐差标配置，涵盖5个职级 × 3个城市级别 × 3类费用。
    可作为新品牌首次配置差标的参考初始值，也可通过 POST /standards 批量导入。
    所有金额单位为分(fen)。
    """
    try:
        items = await _std_svc.get_default_standards_template()
        return {"ok": True, "data": items, "total": len(items)}
    except Exception as exc:
        log.error("standards_template_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="获取差标模板失败，请稍后重试")


@router.get("/cities/tiers")
async def list_city_tiers(
    city_name: Optional[str] = Query(None, description="城市名称搜索（模糊匹配）"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """查询城市级别映射表

    返回所有已配置城市的级别映射（tier1/tier2/tier3/other）。
    支持按城市名模糊搜索，方便前端选择目的地城市时实时预览城市级别。
    is_system=True 为系统预置数据（北上广深等），租户可追加自定义城市映射。
    """
    try:
        from sqlalchemy import select

        from ..models.expense_standard import StandardCityTier as _SCT

        where = [_SCT.tenant_id == tenant_id]
        if city_name:
            where.append(_SCT.city_name.like(f"%{city_name}%"))

        stmt = select(_SCT).where(*where).order_by(_SCT.tier.asc(), _SCT.city_name.asc()).limit(100)
        result = await db.execute(stmt)
        rows = list(result.scalars().all())

        data = [
            {
                "id": str(r.id),
                "city_name": r.city_name,
                "city_code": r.city_code,
                "province": r.province,
                "tier": r.tier,
                "is_system": r.is_system,
            }
            for r in rows
        ]
        return {"ok": True, "data": data, "total": len(data)}
    except Exception as exc:
        log.error("city_tiers_list_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="查询城市级别失败，请稍后重试")


@router.get("/cities/tiers/template")
async def get_city_tiers_template() -> Dict[str, Any]:
    """获取50个主要城市的级别映射模板（无需认证）

    返回覆盖全国50个主要城市的城市级别映射模板：
      - 一线城市（tier1）：北京、上海、广州、深圳（4个）
      - 新一线城市（tier2）：成都、杭州、重庆等（15个）
      - 二线城市（tier3）：合肥、福州、无锡等（31个）

    可作为新租户初始化城市差标配置的参考数据，
    也可通过 POST /cities/tiers/init 一键写入数据库。
    """
    try:
        items = await _std_svc.get_default_city_tiers_template()
        # 按城市级别分组统计
        tier_counts: Dict[str, int] = {}
        for item in items:
            tier = item["tier"]
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
        return {
            "ok": True,
            "data": items,
            "total": len(items),
            "tier_counts": tier_counts,
        }
    except Exception as exc:
        log.error("city_tiers_template_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="获取城市差标模板失败，请稍后重试")


@router.post("/cities/tiers/init")
async def init_city_tiers(
    skip_existing: bool = True,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """一键初始化50个城市差标映射（新租户首次配置时调用）

    将系统预置的50个城市（tier1/tier2/tier3）批量写入当前租户的 standard_city_tiers 表。

    Args:
        skip_existing: True（默认）=跳过已存在的城市（幂等，不覆盖），
                       False=强制更新已有城市的 tier

    返回：
        inserted: 实际新增的城市数量
        total: 模板总城市数量
    """
    try:
        inserted = await _std_svc.init_tenant_city_tiers(
            db=db,
            tenant_id=tenant_id,
            skip_existing=skip_existing,
        )
        await db.commit()
        return {
            "ok": True,
            "data": {
                "inserted": inserted,
                "total": 50,
                "message": f"城市差标初始化完成，新增 {inserted} 个城市映射",
            },
        }
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("city_tiers_init_db_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="城市差标初始化失败（数据库错误），请稍后重试")
    except Exception as exc:
        await db.rollback()
        log.error("city_tiers_init_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="城市差标初始化失败，请稍后重试")
