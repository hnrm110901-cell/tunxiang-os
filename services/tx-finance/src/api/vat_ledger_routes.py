"""增值税台账 API 路由 — Y-F9 税务管理

端点清单（prefix: /api/v1/finance/vat）：
  GET    /output                  销项税台账列表（按月份分页）
  POST   /output                  新增销项税记录（从发票同步）
  GET    /input                   进项税台账列表
  POST   /input                   新增进项税记录（从采购单同步）
  PUT    /input/{id}/deduct       标记进项税已抵扣
  GET    /summary/{period_month}  月度增值税汇总（销项-进项=应缴税额）
  GET    /pl-accounts             P&L 科目映射列表
  PUT    /pl-accounts/{tax_code}  更新科目映射
  POST   /nuonuo/sync-poc         向诺诺平台推送发票 POC（mock）
"""

import hashlib
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/finance/vat", tags=["vat-ledger"])


# ── 依赖 ──────────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    """从 Header 提取 tenant_id，返回带 RLS 的 DB session。"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-ID 格式无效",
        )


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


# ── Pydantic Schema ────────────────────────────────────────────────────────────


class VatOutputCreateBody(BaseModel):
    """新增销项税记录请求体（通常由发票同步触发）。"""

    store_id: Optional[uuid.UUID] = None
    invoice_id: Optional[uuid.UUID] = None
    order_id: Optional[uuid.UUID] = None
    period_month: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="格式 2026-04")
    tax_code: str = Field(..., max_length=20)
    tax_rate: Decimal = Field(..., ge=0, le=1, description="税率，如 0.06")
    amount_excl_tax_fen: int = Field(..., gt=0, description="不含税金额（分）")
    tax_amount_fen: int = Field(..., ge=0, description="税额（分）")
    amount_incl_tax_fen: int = Field(..., gt=0, description="含税金额（分）")
    buyer_name: Optional[str] = Field(None, max_length=100)
    buyer_tax_id: Optional[str] = Field(None, max_length=20)
    invoice_date: date
    nuonuo_order_id: Optional[str] = Field(None, max_length=64)
    extra: Optional[dict[str, Any]] = None


class VatInputCreateBody(BaseModel):
    """新增进项税记录请求体（通常由采购单同步触发）。"""

    store_id: Optional[uuid.UUID] = None
    purchase_order_id: Optional[uuid.UUID] = None
    period_month: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    tax_code: str = Field(..., max_length=20)
    tax_rate: Decimal = Field(..., ge=0, le=1)
    amount_excl_tax_fen: int = Field(..., gt=0)
    tax_amount_fen: int = Field(..., ge=0)
    amount_incl_tax_fen: int = Field(..., gt=0)
    seller_name: Optional[str] = Field(None, max_length=100)
    seller_tax_id: Optional[str] = Field(None, max_length=20)
    invoice_code: Optional[str] = Field(None, max_length=20)
    invoice_number: Optional[str] = Field(None, max_length=10)
    invoice_date: date
    pl_account_code: Optional[str] = Field(None, max_length=20)
    extra: Optional[dict[str, Any]] = None


class PlAccountUpdateBody(BaseModel):
    """更新 P&L 科目映射请求体。"""

    pl_account_code: str = Field(..., max_length=20)
    pl_account_name: str = Field(..., max_length=100)
    account_type: str = Field(..., pattern=r"^(revenue|cost|tax_payable)$")
    is_active: bool = True


class NuonuoSyncPocBody(BaseModel):
    """诺诺平台推送 POC 请求体。"""

    invoice_id: uuid.UUID
    invoice_no: Optional[str] = None
    buyer_name: Optional[str] = None
    total_amount_fen: int = Field(..., gt=0)


# ── 路由 ──────────────────────────────────────────────────────────────────────


@router.get("/output")
async def list_output_records(
    period_month: Optional[str] = Query(None, description="格式 2026-04，为空返回所有月份"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """销项税台账列表，按月份分页查询。"""
    from sqlalchemy import MetaData, Table

    meta = MetaData()
    tbl = Table("vat_output_records", meta, autoload_with=db.sync_session.bind if hasattr(db, "sync_session") else None)

    # 使用 text SQL 避免 ORM 模型依赖，保持轻量
    from sqlalchemy import text

    where_clause = "tenant_id = :tenant_id AND is_deleted = false"
    params: dict[str, Any] = {"tenant_id": str(tenant_id)}

    if period_month:
        where_clause += " AND period_month = :period_month"
        params["period_month"] = period_month

    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM vat_output_records WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar_one()

        rows_result = await db.execute(
            text(
                f"SELECT * FROM vat_output_records WHERE {where_clause} "
                f"ORDER BY invoice_date DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        rows = [dict(r._mapping) for r in rows_result]
    except SQLAlchemyError as exc:
        logger.error("vat_output_list_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询销项税台账失败") from exc

    return _ok({"items": rows, "total": total, "page": page, "size": size})


@router.post("/output", status_code=status.HTTP_201_CREATED)
async def create_output_record(
    body: VatOutputCreateBody,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """新增销项税记录（从电子发票同步时调用）。"""
    from sqlalchemy import text

    record_id = uuid.uuid4()
    try:
        await db.execute(
            text("""
                INSERT INTO vat_output_records (
                    id, tenant_id, store_id, invoice_id, order_id,
                    period_month, tax_code, tax_rate,
                    amount_excl_tax_fen, tax_amount_fen, amount_incl_tax_fen,
                    buyer_name, buyer_tax_id, invoice_date,
                    nuonuo_order_id, extra
                ) VALUES (
                    :id, :tenant_id, :store_id, :invoice_id, :order_id,
                    :period_month, :tax_code, :tax_rate,
                    :amount_excl_tax_fen, :tax_amount_fen, :amount_incl_tax_fen,
                    :buyer_name, :buyer_tax_id, :invoice_date,
                    :nuonuo_order_id, :extra::jsonb
                )
            """),
            {
                "id": str(record_id),
                "tenant_id": str(tenant_id),
                "store_id": str(body.store_id) if body.store_id else None,
                "invoice_id": str(body.invoice_id) if body.invoice_id else None,
                "order_id": str(body.order_id) if body.order_id else None,
                "period_month": body.period_month,
                "tax_code": body.tax_code,
                "tax_rate": str(body.tax_rate),
                "amount_excl_tax_fen": body.amount_excl_tax_fen,
                "tax_amount_fen": body.tax_amount_fen,
                "amount_incl_tax_fen": body.amount_incl_tax_fen,
                "buyer_name": body.buyer_name,
                "buyer_tax_id": body.buyer_tax_id,
                "invoice_date": body.invoice_date.isoformat(),
                "nuonuo_order_id": body.nuonuo_order_id,
                "extra": str(body.extra) if body.extra else "null",
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("vat_output_create_error", error=str(exc))
        raise HTTPException(status_code=500, detail="新增销项税记录失败") from exc

    logger.info("vat_output_created", record_id=str(record_id), tenant_id=str(tenant_id))
    return _ok({"id": str(record_id), "period_month": body.period_month})


@router.get("/input")
async def list_input_records(
    period_month: Optional[str] = Query(None),
    deduction_status: Optional[str] = Query(None, description="pending/deducted/rejected"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """进项税台账列表，支持按月份、抵扣状态筛选。"""
    from sqlalchemy import text

    where_clause = "tenant_id = :tenant_id AND is_deleted = false"
    params: dict[str, Any] = {"tenant_id": str(tenant_id)}

    if period_month:
        where_clause += " AND period_month = :period_month"
        params["period_month"] = period_month
    if deduction_status:
        where_clause += " AND deduction_status = :deduction_status"
        params["deduction_status"] = deduction_status

    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM vat_input_records WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar_one()

        rows_result = await db.execute(
            text(
                f"SELECT * FROM vat_input_records WHERE {where_clause} "
                f"ORDER BY invoice_date DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        rows = [dict(r._mapping) for r in rows_result]
    except SQLAlchemyError as exc:
        logger.error("vat_input_list_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询进项税台账失败") from exc

    return _ok({"items": rows, "total": total, "page": page, "size": size})


@router.post("/input", status_code=status.HTTP_201_CREATED)
async def create_input_record(
    body: VatInputCreateBody,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """新增进项税记录（从采购单同步时调用）。"""
    import json

    from sqlalchemy import text

    record_id = uuid.uuid4()
    try:
        await db.execute(
            text("""
                INSERT INTO vat_input_records (
                    id, tenant_id, store_id, purchase_order_id,
                    period_month, tax_code, tax_rate,
                    amount_excl_tax_fen, tax_amount_fen, amount_incl_tax_fen,
                    seller_name, seller_tax_id, invoice_code, invoice_number,
                    invoice_date, pl_account_code, extra
                ) VALUES (
                    :id, :tenant_id, :store_id, :purchase_order_id,
                    :period_month, :tax_code, :tax_rate,
                    :amount_excl_tax_fen, :tax_amount_fen, :amount_incl_tax_fen,
                    :seller_name, :seller_tax_id, :invoice_code, :invoice_number,
                    :invoice_date, :pl_account_code, :extra::jsonb
                )
            """),
            {
                "id": str(record_id),
                "tenant_id": str(tenant_id),
                "store_id": str(body.store_id) if body.store_id else None,
                "purchase_order_id": str(body.purchase_order_id) if body.purchase_order_id else None,
                "period_month": body.period_month,
                "tax_code": body.tax_code,
                "tax_rate": str(body.tax_rate),
                "amount_excl_tax_fen": body.amount_excl_tax_fen,
                "tax_amount_fen": body.tax_amount_fen,
                "amount_incl_tax_fen": body.amount_incl_tax_fen,
                "seller_name": body.seller_name,
                "seller_tax_id": body.seller_tax_id,
                "invoice_code": body.invoice_code,
                "invoice_number": body.invoice_number,
                "invoice_date": body.invoice_date.isoformat(),
                "pl_account_code": body.pl_account_code,
                "extra": json.dumps(body.extra) if body.extra else "null",
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("vat_input_create_error", error=str(exc))
        raise HTTPException(status_code=500, detail="新增进项税记录失败") from exc

    logger.info("vat_input_created", record_id=str(record_id), tenant_id=str(tenant_id))
    return _ok({"id": str(record_id), "period_month": body.period_month})


@router.put("/input/{record_id}/deduct")
async def deduct_input_record(
    record_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """标记进项税已抵扣（pending → deducted）。"""
    from sqlalchemy import text

    try:
        result = await db.execute(
            text("""
                UPDATE vat_input_records
                SET deduction_status = 'deducted', updated_at = NOW()
                WHERE id = :id AND tenant_id = :tenant_id
                  AND deduction_status = 'pending' AND is_deleted = false
                RETURNING id
            """),
            {"id": str(record_id), "tenant_id": str(tenant_id)},
        )
        updated = result.fetchone()
        if not updated:
            raise HTTPException(
                status_code=404,
                detail="记录不存在或已非 pending 状态，无法标记抵扣",
            )
        await db.commit()
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("vat_input_deduct_error", record_id=str(record_id), error=str(exc))
        raise HTTPException(status_code=500, detail="标记抵扣失败") from exc

    logger.info("vat_input_deducted", record_id=str(record_id))
    return _ok({"id": str(record_id), "deduction_status": "deducted"})


@router.get("/summary/{period_month}")
async def get_monthly_summary(
    period_month: str,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """月度增值税汇总：销项税额 - 进项税额 = 应缴增值税。

    所有金额均为整数（分），严格无浮点。
    """
    from sqlalchemy import text

    try:
        output_result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(tax_amount_fen), 0) AS output_tax_fen,
                    COUNT(*) AS output_count
                FROM vat_output_records
                WHERE tenant_id = :tenant_id
                  AND period_month = :period_month
                  AND status != 'voided'
                  AND is_deleted = false
            """),
            {"tenant_id": str(tenant_id), "period_month": period_month},
        )
        output_row = output_result.fetchone()
        output_tax_fen = int(output_row.output_tax_fen)
        output_count = int(output_row.output_count)

        input_result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(tax_amount_fen), 0) AS input_tax_fen,
                    COUNT(*) AS input_count
                FROM vat_input_records
                WHERE tenant_id = :tenant_id
                  AND period_month = :period_month
                  AND deduction_status = 'deducted'
                  AND is_deleted = false
            """),
            {"tenant_id": str(tenant_id), "period_month": period_month},
        )
        input_row = input_result.fetchone()
        input_tax_fen = int(input_row.input_tax_fen)
        input_count = int(input_row.input_count)

        # P&L 各科目汇总（取进项税的科目分组）
        pl_result = await db.execute(
            text("""
                SELECT
                    vi.pl_account_code,
                    pam.pl_account_name,
                    pam.account_type,
                    COALESCE(SUM(vi.amount_excl_tax_fen), 0) AS amount_excl_tax_fen,
                    COALESCE(SUM(vi.tax_amount_fen), 0) AS tax_amount_fen
                FROM vat_input_records vi
                LEFT JOIN pl_account_mappings pam
                    ON pam.tax_code = vi.tax_code AND pam.tenant_id = vi.tenant_id
                WHERE vi.tenant_id = :tenant_id
                  AND vi.period_month = :period_month
                  AND vi.is_deleted = false
                  AND vi.pl_account_code IS NOT NULL
                GROUP BY vi.pl_account_code, pam.pl_account_name, pam.account_type
                ORDER BY vi.pl_account_code
            """),
            {"tenant_id": str(tenant_id), "period_month": period_month},
        )
        pl_summary = [dict(r._mapping) for r in pl_result]

    except SQLAlchemyError as exc:
        logger.error("vat_summary_error", period_month=period_month, error=str(exc))
        raise HTTPException(status_code=500, detail="获取增值税汇总失败") from exc

    net_payable_fen = output_tax_fen - input_tax_fen

    return _ok(
        {
            "period_month": period_month,
            "output_tax_fen": output_tax_fen,  # 销项税额（分）
            "input_tax_fen": input_tax_fen,  # 进项税额（分，仅已抵扣）
            "net_payable_fen": net_payable_fen,  # 应缴增值税（分）
            "output_count": output_count,
            "input_count": input_count,
            "pl_summary": pl_summary,
        }
    )


@router.get("/pl-accounts")
async def list_pl_accounts(
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """P&L 科目映射列表。"""
    from sqlalchemy import text

    try:
        result = await db.execute(
            text("""
                SELECT * FROM pl_account_mappings
                WHERE tenant_id = :tenant_id
                ORDER BY tax_code
            """),
            {"tenant_id": str(tenant_id)},
        )
        rows = [dict(r._mapping) for r in result]
    except SQLAlchemyError as exc:
        logger.error("pl_accounts_list_error", error=str(exc))
        raise HTTPException(status_code=500, detail="获取科目映射失败") from exc

    return _ok({"items": rows, "total": len(rows)})


@router.put("/pl-accounts/{tax_code}")
async def upsert_pl_account(
    tax_code: str,
    body: PlAccountUpdateBody,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """更新（或新增）P&L 科目映射（upsert by tenant_id + tax_code）。"""
    from sqlalchemy import text

    mapping_id = uuid.uuid4()
    try:
        await db.execute(
            text("""
                INSERT INTO pl_account_mappings (
                    id, tenant_id, tax_code, pl_account_code, pl_account_name,
                    account_type, is_active
                ) VALUES (
                    :id, :tenant_id, :tax_code, :pl_account_code, :pl_account_name,
                    :account_type, :is_active
                )
                ON CONFLICT (tenant_id, tax_code)
                DO UPDATE SET
                    pl_account_code = EXCLUDED.pl_account_code,
                    pl_account_name = EXCLUDED.pl_account_name,
                    account_type    = EXCLUDED.account_type,
                    is_active       = EXCLUDED.is_active
            """),
            {
                "id": str(mapping_id),
                "tenant_id": str(tenant_id),
                "tax_code": tax_code,
                "pl_account_code": body.pl_account_code,
                "pl_account_name": body.pl_account_name,
                "account_type": body.account_type,
                "is_active": body.is_active,
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("pl_account_upsert_error", tax_code=tax_code, error=str(exc))
        raise HTTPException(status_code=500, detail="更新科目映射失败") from exc

    logger.info("pl_account_upserted", tax_code=tax_code, tenant_id=str(tenant_id))
    return _ok({"tax_code": tax_code, "pl_account_code": body.pl_account_code})


@router.post("/nuonuo/sync-poc", status_code=status.HTTP_202_ACCEPTED)
async def nuonuo_sync_poc(
    body: NuonuoSyncPocBody,
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
) -> dict[str, Any]:
    """向诺诺平台推送发票 POC（当前为 mock，生产环境替换说明见下方注释）。

    生产环境替换方式：
    1. 安装诺诺 Python SDK：`pip install nuonuo-sdk`
    2. 从环境变量读取 APP_KEY / APP_SECRET / MERCHANT_NO
    3. 调用 `nuonuo_client.issue_invoice(invoice_data)` 替换本函数中的 mock 逻辑
    4. 将返回的 `order_sn` 写入 `vat_output_records.nuonuo_order_id`
    5. 注册诺诺回调地址 POST /api/v1/finance/vat/nuonuo/callback 更新状态
    """
    # mock：生成伪随机诺诺流水号，模拟提交成功
    mock_order_id = f"MOCK_{hashlib.md5(str(body.invoice_id).encode()).hexdigest()[:16].upper()}"

    logger.info(
        "nuonuo_sync_poc",
        invoice_id=str(body.invoice_id),
        mock_order_id=mock_order_id,
        tenant_id=str(tenant_id),
        note="MOCK — 生产环境请替换为诺诺 SDK 真实调用",
    )

    return _ok(
        {
            "nuonuo_order_id": mock_order_id,
            "status": "submitted",
            "invoice_id": str(body.invoice_id),
            "mock": True,  # 生产环境删除此字段
            "note": "MOCK_MODE: 生产环境请接入诺诺开放平台 SDK",
        }
    )
