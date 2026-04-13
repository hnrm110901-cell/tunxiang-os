"""
备用金管理 API 路由

共8个端点，覆盖备用金账户的完整生命周期：
  开户 → 日常支出录入 → 余额查看 → 月末核销 → 补充申请 → 离职归还
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from src.api.expense_routes import get_current_user, get_tenant_id

# 财务确认操作允许的角色（由 Gateway 注入 X-User-Role header）
_FINANCE_ROLES = {"brand_finance", "brand_cfo", "hq_finance", "admin"}
_role_log = structlog.get_logger(__name__)


async def require_finance_role(
    x_user_role: str = Header(default="", alias="X-User-Role"),
) -> str:
    """验证调用者具有财务角色（brand_finance / brand_cfo / hq_finance / admin）。

    X-User-Role header 由 API Gateway 在认证后注入。
    未传入 header 时（内部调用 / 开发环境）降级放行，记录警告日志。
    """
    if not x_user_role:
        _role_log.warning("finance_role_check_skipped_no_header")
        return x_user_role
    if x_user_role not in _FINANCE_ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"需要财务角色（brand_finance/brand_cfo/hq_finance），当前角色：{x_user_role}",
        )
    return x_user_role

try:
    from src.services import petty_cash_service
except ImportError:
    petty_cash_service = None  # type: ignore[assignment]

try:
    from src.agents import a1_petty_cash_guardian
except ImportError:
    a1_petty_cash_guardian = None  # type: ignore[assignment]

router = APIRouter()
log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class PettyCashAccountCreate(BaseModel):
    store_id: UUID
    brand_id: UUID
    keeper_id: UUID           # 保管人员工ID（通常是店长）
    approved_limit: int       # 审批额度上限（分）
    warning_threshold: int    # 预警阈值（分）
    opening_balance: int = 0  # 期初余额（分），默认0


class ExpenseRecordCreate(BaseModel):
    amount: int               # 支出金额（分，正整数）
    description: str = Field(..., max_length=200)
    expense_date: Optional[date] = None   # 默认今天
    reference_id: Optional[UUID] = None
    reference_type: Optional[str] = None
    notes: Optional[str] = None


class PosReconcileRequest(BaseModel):
    pos_session_id: str
    pos_declared_amount: int  # POS申报的备用金支出（分）
    reconcile_date: date


class FreezeAccountRequest(BaseModel):
    reason: str = Field(..., min_length=5)


class UnfreezeAccountRequest(BaseModel):
    returned_amount: int = 0  # 归还金额（分），0=无需归还


class ConfirmSettlementRequest(BaseModel):
    settlement_id: UUID


class GenerateSettlementRequest(BaseModel):
    store_id: UUID
    settlement_month: str  # 格式 YYYY-MM


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _fen_to_yuan(fen: int) -> str:
    """分转元，保留两位小数，返回字符串。"""
    return f"{fen / 100:.2f}"


def _account_to_dict(account: Any, include_transactions: bool = False) -> Dict[str, Any]:
    """将 PettyCashAccount ORM 对象序列化为响应字典。"""
    data: Dict[str, Any] = {
        "account_id": str(account.id),
        "tenant_id": str(account.tenant_id),
        "store_id": str(account.store_id),
        "brand_id": str(account.brand_id),
        "keeper_id": str(account.keeper_id),
        "balance_fen": account.balance,
        "balance_yuan": _fen_to_yuan(account.balance),
        "approved_limit_fen": account.approved_limit,
        "approved_limit_yuan": _fen_to_yuan(account.approved_limit),
        "warning_threshold_fen": account.warning_threshold,
        "warning_threshold_yuan": _fen_to_yuan(account.warning_threshold),
        "is_below_threshold": account.balance < account.warning_threshold,
        "daily_avg_7d_fen": account.daily_avg_7d,
        "daily_avg_7d_yuan": _fen_to_yuan(account.daily_avg_7d or 0),
        "status": account.status,
        "frozen_reason": account.frozen_reason,
        "frozen_at": account.frozen_at.isoformat() if account.frozen_at else None,
        "last_reconciled_at": account.last_reconciled_at.isoformat() if account.last_reconciled_at else None,
        "pos_session_ref": account.pos_session_ref if hasattr(account, "pos_session_ref") else None,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
    }
    if include_transactions and hasattr(account, "transactions") and account.transactions:
        data["recent_transactions"] = [
            _transaction_to_dict(t) for t in account.transactions
        ]
    return data


def _transaction_to_dict(txn: Any) -> Dict[str, Any]:
    """将 PettyCashTransaction ORM 对象序列化为响应字典。"""
    return {
        "transaction_id": str(txn.id),
        "account_id": str(txn.account_id),
        "transaction_type": txn.transaction_type,
        "amount_fen": txn.amount,
        "amount_yuan": _fen_to_yuan(abs(txn.amount)),
        "balance_after_fen": txn.balance_after,
        "balance_after_yuan": _fen_to_yuan(txn.balance_after),
        "description": txn.description,
        "expense_date": txn.expense_date.isoformat() if txn.expense_date else None,
        "reference_id": str(txn.reference_id) if txn.reference_id else None,
        "reference_type": txn.reference_type,
        "operator_id": str(txn.operator_id) if txn.operator_id else None,
        "is_reconciled": txn.is_reconciled,
        "reconciled_at": txn.reconciled_at.isoformat() if txn.reconciled_at else None,
        "notes": txn.notes,
        "created_at": txn.created_at.isoformat() if txn.created_at else None,
    }


def _settlement_to_dict(settlement: Any) -> Dict[str, Any]:
    """将 PettyCashSettlement ORM 对象序列化为响应字典。"""
    return {
        "settlement_id": str(settlement.id),
        "account_id": str(settlement.account_id),
        "store_id": str(settlement.store_id),
        "settlement_month": settlement.settlement_month,
        "period_start": settlement.period_start.isoformat() if settlement.period_start else None,
        "period_end": settlement.period_end.isoformat() if settlement.period_end else None,
        "opening_balance_fen": settlement.opening_balance,
        "opening_balance_yuan": _fen_to_yuan(settlement.opening_balance),
        "total_income_fen": settlement.total_income,
        "total_income_yuan": _fen_to_yuan(settlement.total_income),
        "total_expense_fen": settlement.total_expense,
        "total_expense_yuan": _fen_to_yuan(settlement.total_expense),
        "closing_balance_fen": settlement.closing_balance,
        "closing_balance_yuan": _fen_to_yuan(settlement.closing_balance),
        "reconciled_count": settlement.reconciled_count,
        "unreconciled_count": settlement.unreconciled_count,
        "status": settlement.status,
        "generated_by": settlement.generated_by,
        "confirmed_by": str(settlement.confirmed_by) if settlement.confirmed_by else None,
        "confirmed_at": settlement.confirmed_at.isoformat() if settlement.confirmed_at else None,
        "created_at": settlement.created_at.isoformat() if settlement.created_at else None,
        "updated_at": settlement.updated_at.isoformat() if settlement.updated_at else None,
    }


def _require_petty_cash_service() -> Any:
    if petty_cash_service is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="备用金服务暂不可用，请稍后重试")
    return petty_cash_service


# ---------------------------------------------------------------------------
# 端点1：POST /accounts — 开设备用金账户
# ---------------------------------------------------------------------------

@router.post(
    "/accounts",
    status_code=status.HTTP_201_CREATED,
    summary="开设备用金账户",
    description="为指定门店开设备用金账户（每门店唯一）。若期初余额>0，自动生成 OPENING_BALANCE 流水。",
)
async def create_petty_cash_account(
    body: PettyCashAccountCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    operator_id: UUID = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    开设备用金账户。

    - **store_id**: 门店UUID（每门店唯一，重复开户返回 409）
    - **approved_limit**: 审批额度上限（分），必须 > 0
    - **warning_threshold**: 余额预警阈值（分），低于此值推送预警
    - **opening_balance**: 期初余额（分），默认 0
    """
    svc = _require_petty_cash_service()

    account = await svc.create_account(
        db=db,
        tenant_id=tenant_id,
        store_id=body.store_id,
        brand_id=body.brand_id,
        keeper_id=body.keeper_id,
        approved_limit=body.approved_limit,
        warning_threshold=body.warning_threshold,
        opening_balance=body.opening_balance,
    )
    await db.commit()

    log.info(
        "api_petty_cash_account_created",
        tenant_id=str(tenant_id),
        store_id=str(body.store_id),
        account_id=str(account.id),
        operator_id=str(operator_id),
    )

    return {
        "ok": True,
        "data": _account_to_dict(account),
    }


# ---------------------------------------------------------------------------
# 端点2：GET /accounts/{store_id} — 查询门店备用金账户
# ---------------------------------------------------------------------------

@router.get(
    "/accounts/{store_id}",
    summary="查询门店备用金账户",
    description="按门店UUID查询备用金账户详情，包含余额、状态及最近10条流水。",
)
async def get_petty_cash_account(
    store_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _operator_id: UUID = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    查询门店备用金账户详情。

    返回字段包含：
    - **balance_fen** / **balance_yuan**：当前余额（分 / 元）
    - **is_below_threshold**：是否低于预警阈值
    - **recent_transactions**：最近10条流水记录
    """
    svc = _require_petty_cash_service()

    account = await svc.get_account_by_store(
        db=db,
        tenant_id=tenant_id,
        store_id=store_id,
    )

    return {
        "ok": True,
        "data": _account_to_dict(account, include_transactions=True),
    }


# ---------------------------------------------------------------------------
# 端点3：POST /accounts/{account_id}/expenses — 录入日常支出
# ---------------------------------------------------------------------------

@router.post(
    "/accounts/{account_id}/expenses",
    status_code=status.HTTP_201_CREATED,
    summary="录入日常支出",
    description="向指定账户录入一笔日常支出流水，同时触发 A1 守护 Agent 异常检测。",
)
async def record_expense(
    account_id: UUID,
    body: ExpenseRecordCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    operator_id: UUID = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    录入日常支出流水（DAILY_USE）。

    - 余额不足时仍允许录入，响应中会附加 `warning_note`
    - 若 A1 守护 Agent 检测到异常（单笔超日均50%），响应中追加 `anomaly_alert`
    - 金额以**分**为单位传入，响应同时返回分和元
    """
    svc = _require_petty_cash_service()

    expense_date = body.expense_date or date.today()

    txn = await svc.record_expense(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        amount=body.amount,
        description=body.description,
        operator_id=operator_id,
        expense_date=expense_date,
        reference_id=body.reference_id,
        reference_type=body.reference_type,
        notes=body.notes,
    )
    await db.commit()

    log.info(
        "api_petty_cash_expense_recorded",
        tenant_id=str(tenant_id),
        account_id=str(account_id),
        transaction_id=str(txn.id),
        amount=body.amount,
        operator_id=str(operator_id),
    )

    response_data: Dict[str, Any] = {
        "ok": True,
        "data": _transaction_to_dict(txn),
    }

    # A1 守护 Agent 异常检测（旁路，不阻塞主流程）
    if a1_petty_cash_guardian is not None:
        try:
            anomaly = await a1_petty_cash_guardian.detect_transaction_anomaly(
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                transaction_id=txn.id,
                amount=body.amount,
            )
            if anomaly:
                response_data["anomaly_alert"] = anomaly
                log.warning(
                    "api_petty_cash_anomaly_detected",
                    tenant_id=str(tenant_id),
                    account_id=str(account_id),
                    transaction_id=str(txn.id),
                    over_rate=anomaly.get("over_rate"),
                )
        except Exception as exc:  # 旁路检测失败不阻断主业务
            log.warning(
                "api_petty_cash_anomaly_check_failed",
                tenant_id=str(tenant_id),
                account_id=str(account_id),
                error=str(exc),
                exc_info=True,
            )

    return response_data


# ---------------------------------------------------------------------------
# 端点4：GET /accounts/{account_id}/balance — 查询实时余额
# ---------------------------------------------------------------------------

@router.get(
    "/accounts/{account_id}/balance",
    summary="查询实时余额",
    description="轻量余额查询接口，适合前端高频轮询场景。",
)
async def get_account_balance(
    account_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _operator_id: UUID = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    查询实时余额（轻量接口）。

    返回：
    - **balance_fen** / **balance_yuan**：当前余额
    - **warning_threshold_fen**：预警阈值
    - **status**：账户状态（active/frozen/closed）
    - **is_below_threshold**：是否低于预警线
    """
    svc = _require_petty_cash_service()

    # 复用内部工具查询账户（防跨租户）
    from sqlalchemy import select
    from src.models.petty_cash import PettyCashAccount

    stmt = select(PettyCashAccount).where(
        PettyCashAccount.tenant_id == tenant_id,
        PettyCashAccount.id == account_id,
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()

    if account is None:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="备用金账户不存在或无权限访问",
        )

    return {
        "ok": True,
        "data": {
            "account_id": str(account.id),
            "balance_fen": account.balance,
            "balance_yuan": _fen_to_yuan(account.balance),
            "warning_threshold_fen": account.warning_threshold,
            "warning_threshold_yuan": _fen_to_yuan(account.warning_threshold),
            "status": account.status,
            "is_below_threshold": account.balance < account.warning_threshold,
        },
    }


# ---------------------------------------------------------------------------
# 端点5：POST /accounts/{account_id}/pos-reconcile — POS日结手动对账
# ---------------------------------------------------------------------------

@router.post(
    "/accounts/{account_id}/pos-reconcile",
    summary="POS日结手动对账",
    description=(
        "将账户余额与 POS 日结上报余额进行比对。"
        "差异 ≤50元自动调平（写 POS_RECONCILE_ADJUST 流水）；"
        "差异 >50元标记需人工介入，不自动修改余额。"
        "此端点为手动触发，自动对账通过 POS 日结事件消费者处理。"
    ),
)
async def pos_reconcile(
    account_id: UUID,
    body: PosReconcileRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    operator_id: UUID = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    POS日结手动对账。

    - **pos_session_id**: POS日结会话ID（用于追踪）
    - **pos_declared_amount**: POS申报的备用金支出总额（分）
    - **reconcile_date**: 对账日期

    返回对账结果：`status=ok` 表示平账，`status=diff_detected` 表示存在差异需人工处理。
    """
    svc = _require_petty_cash_service()

    # 先通过 account_id 获取 store_id
    from sqlalchemy import select
    from src.models.petty_cash import PettyCashAccount

    stmt = select(PettyCashAccount).where(
        PettyCashAccount.tenant_id == tenant_id,
        PettyCashAccount.id == account_id,
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()

    if account is None:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="备用金账户不存在或无权限访问",
        )

    reconcile_result = await svc.reconcile_with_pos(
        db=db,
        tenant_id=tenant_id,
        store_id=account.store_id,
        pos_session_id=body.pos_session_id,
        pos_reported_balance=body.pos_declared_amount,
    )
    await db.commit()

    log.info(
        "api_petty_cash_pos_reconcile",
        tenant_id=str(tenant_id),
        account_id=str(account_id),
        pos_session_id=body.pos_session_id,
        reconcile_status=reconcile_result.get("status"),
        diff=reconcile_result.get("diff"),
        operator_id=str(operator_id),
    )

    # 响应中额外补充元单位字段，方便前端展示
    enriched = dict(reconcile_result)
    enriched["account_balance_yuan"] = _fen_to_yuan(reconcile_result["account_balance"])
    enriched["pos_balance_yuan"] = _fen_to_yuan(reconcile_result["pos_balance"])
    enriched["diff_yuan"] = _fen_to_yuan(abs(reconcile_result["diff"]))

    return {
        "ok": True,
        "data": enriched,
    }


# ---------------------------------------------------------------------------
# 端点6：GET /settlements — 查询月末核销单列表
# ---------------------------------------------------------------------------

@router.get(
    "/settlements",
    summary="查询月末核销单列表",
    description="查询月末核销单列表，支持按门店、月份、状态过滤，结果按 settlement_month 倒序分页。",
)
async def list_settlements(
    store_id: Optional[UUID] = Query(None, description="按门店过滤（可选）"),
    settlement_month: Optional[str] = Query(None, description="按月份过滤，格式 YYYY-MM（可选）"),
    settlement_status: Optional[str] = Query(None, alias="status", description="按状态过滤：draft/submitted/confirmed/closed（可选）"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    size: int = Query(20, ge=1, le=100, description="每页数量，最大100"),
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _operator_id: UUID = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    查询月末核销单列表（分页）。

    - **store_id**: 可选，按门店过滤
    - **settlement_month**: 可选，格式 YYYY-MM
    - **status**: 可选，draft/submitted/confirmed/closed
    - **page** / **size**: 分页参数
    """
    from sqlalchemy import select, func
    from src.models.petty_cash import PettyCashSettlement

    conditions = [PettyCashSettlement.tenant_id == tenant_id]

    if store_id is not None:
        conditions.append(PettyCashSettlement.store_id == store_id)
    if settlement_month is not None:
        conditions.append(PettyCashSettlement.settlement_month == settlement_month)
    if settlement_status is not None:
        conditions.append(PettyCashSettlement.status == settlement_status)

    # 统计总数
    count_stmt = select(func.count()).select_from(PettyCashSettlement).where(*conditions)
    count_result = await db.execute(count_stmt)
    total = int(count_result.scalar_one())

    # 分页查询
    offset = (page - 1) * size
    list_stmt = (
        select(PettyCashSettlement)
        .where(*conditions)
        .order_by(PettyCashSettlement.settlement_month.desc())
        .offset(offset)
        .limit(size)
    )
    list_result = await db.execute(list_stmt)
    settlements = list(list_result.scalars().all())

    return {
        "ok": True,
        "data": {
            "items": [_settlement_to_dict(s) for s in settlements],
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size if total > 0 else 0,
        },
    }


# ---------------------------------------------------------------------------
# 端点7：POST /settlements/generate — 手动触发生成月末核销单
# ---------------------------------------------------------------------------

@router.post(
    "/settlements/generate",
    status_code=status.HTTP_201_CREATED,
    summary="手动生成月末核销单",
    description=(
        "手动为指定门店生成月末核销单（幂等：若已存在则直接返回现有核销单）。"
        "通常由 A1 Agent 在月末自动触发，此端点供财务手动补生成。"
    ),
)
async def generate_monthly_settlement(
    body: GenerateSettlementRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    operator_id: UUID = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    手动生成月末核销单。

    - **store_id**: 门店UUID
    - **settlement_month**: 格式 YYYY-MM，如 "2026-04"

    幂等操作：若该门店该月核销单已存在，直接返回现有核销单，HTTP 201。
    """
    svc = _require_petty_cash_service()

    # 先查询门店账户 ID
    from sqlalchemy import select
    from src.models.petty_cash import PettyCashAccount

    stmt = select(PettyCashAccount).where(
        PettyCashAccount.tenant_id == tenant_id,
        PettyCashAccount.store_id == body.store_id,
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()

    if account is None:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该门店尚未开设备用金账户，无法生成核销单",
        )

    settlement = await svc.generate_monthly_settlement(
        db=db,
        tenant_id=tenant_id,
        account_id=account.id,
        settlement_month=body.settlement_month,
    )
    await db.commit()

    log.info(
        "api_petty_cash_settlement_generated",
        tenant_id=str(tenant_id),
        store_id=str(body.store_id),
        account_id=str(account.id),
        settlement_id=str(settlement.id),
        settlement_month=body.settlement_month,
        operator_id=str(operator_id),
    )

    return {
        "ok": True,
        "data": _settlement_to_dict(settlement),
    }


# ---------------------------------------------------------------------------
# 端点8：POST /settlements/confirm — 财务确认核销单
# ---------------------------------------------------------------------------

@router.post(
    "/settlements/confirm",
    summary="财务确认核销单",
    description=(
        "财务人员确认月末核销单（DRAFT/SUBMITTED → CONFIRMED）。"
        "确认后自动将期间内所有未核销流水标记为已核销。"
        "需要财务角色：brand_finance / brand_cfo / hq_finance / admin（通过 X-User-Role header 验证）。"
    ),
)
async def confirm_settlement(
    body: ConfirmSettlementRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    operator_id: UUID = Depends(get_current_user),
    _role: str = Depends(require_finance_role),
) -> Dict[str, Any]:
    """
    财务确认核销单。

    - **settlement_id**: 要确认的核销单UUID
    - 只有 `draft` 或 `submitted` 状态的核销单才可确认
    - 确认后自动将期间流水的 `is_reconciled` 置为 `True`
    - 需要财务角色（X-User-Role: brand_finance / brand_cfo / hq_finance / admin）
    """
    svc = _require_petty_cash_service()

    settlement = await svc.confirm_settlement(
        db=db,
        tenant_id=tenant_id,
        settlement_id=body.settlement_id,
        confirmed_by=operator_id,
    )
    await db.commit()

    log.info(
        "api_petty_cash_settlement_confirmed",
        tenant_id=str(tenant_id),
        settlement_id=str(body.settlement_id),
        confirmed_by=str(operator_id),
    )

    return {
        "ok": True,
        "data": _settlement_to_dict(settlement),
    }
