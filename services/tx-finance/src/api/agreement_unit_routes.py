"""协议单位 API — 企业挂账体系

端点：
  GET    /api/v1/agreement-units                              — 协议单位列表
  POST   /api/v1/agreement-units                              — 新建协议单位
  GET    /api/v1/agreement-units/report/aging                 — 账龄分析
  GET    /api/v1/agreement-units/report/monthly               — 月度对账单
  GET    /api/v1/agreement-units/{unit_id}                    — 单位详情（含账户余额）
  PUT    /api/v1/agreement-units/{unit_id}                    — 更新单位信息
  POST   /api/v1/agreement-units/{unit_id}/suspend            — 暂停/启用
  GET    /api/v1/agreement-units/{unit_id}/transactions       — 挂账/还款流水（分页）
  POST   /api/v1/agreement-units/{unit_id}/charge             — 手动挂账
  POST   /api/v1/agreement-units/{unit_id}/repay              — 还款（普通/指定/批量）
  POST   /api/v1/agreement-units/{unit_id}/prepaid/recharge   — 预付充值
  POST   /api/v1/agreement-units/{unit_id}/prepaid/refund     — 预付退款
  GET    /api/v1/agreement-units/{unit_id}/prepaid/balance    — 预付余额
"""
import uuid
from datetime import datetime, date
from typing import Optional, List

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/agreement-units", tags=["协议单位"])


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


def _serialize_row(row: dict) -> dict:
    result = {}
    for k, v in row.items():
        if isinstance(v, uuid.UUID):
            result[k] = str(v)
        elif isinstance(v, (datetime, date)):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


def _format_voucher(unit_name: str, txn_type: str, amount_fen: int,
                    operator: str, notes: str, txn_id: str, created_at: str) -> str:
    """生成凭证文本（前端可打印）。"""
    type_label = {'charge': '手动挂账', 'repay': '还款', 'manual_charge': '手动挂账'}.get(txn_type, txn_type)
    amount_yuan = f"¥{amount_fen / 100:.2f}"
    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "    屯象OS 挂账凭证    ",
        "━━━━━━━━━━━━━━━━━━━━",
        f"单位: {unit_name}",
        f"类型: {type_label}",
        f"金额: {amount_yuan}",
        f"操作员: {operator}",
        f"时间: {created_at}",
    ]
    if notes:
        lines.append(f"备注: {notes}")
    lines += [
        f"流水号: {txn_id[:8]}...",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    return "\n".join(lines)


# ─── 依赖注入 ──────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─── Mock 数据（DB不可用时降级） ──────────────────────────────────────────────

_MOCK_UNITS = [
    {
        "id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "mock",
        "name": "示例企业A（测试数据）",
        "short_name": "企业A",
        "contact_name": "张经理",
        "contact_phone": "138-0000-0001",
        "credit_limit_fen": 100000_00,
        "settlement_cycle": "monthly",
        "settlement_day": 15,
        "status": "active",
        "notes": None,
        "credit_used_fen": 30000_00,
        "balance_fen": -30000_00,
        "total_consumed_fen": 50000_00,
        "total_repaid_fen": 20000_00,
        "created_at": "2026-01-01T00:00:00+08:00",
        "updated_at": "2026-04-06T00:00:00+08:00",
    }
]


# ─── 请求模型 ──────────────────────────────────────────────────────────────────

class UnitCreate(BaseModel):
    name: str = Field(..., max_length=100)
    short_name: Optional[str] = Field(None, max_length=50)
    contact_name: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=20)
    credit_limit_fen: int = Field(0, ge=0, description="授信额度（分）")
    settlement_cycle: Optional[str] = Field(None, description="monthly/weekly/custom")
    settlement_day: Optional[int] = Field(None, ge=1, le=31)
    notes: Optional[str] = None


class UnitUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    short_name: Optional[str] = Field(None, max_length=50)
    contact_name: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=20)
    credit_limit_fen: Optional[int] = Field(None, ge=0)
    settlement_cycle: Optional[str] = None
    settlement_day: Optional[int] = Field(None, ge=1, le=31)
    notes: Optional[str] = None


class SuspendRequest(BaseModel):
    action: str = Field("suspend", description="suspend/resume")
    notes: Optional[str] = None


class ChargeRequest(BaseModel):
    amount_fen: int = Field(..., gt=0, description="挂账金额（分）")
    order_id: Optional[str] = None
    notes: Optional[str] = None
    print_voucher: bool = False


class RepayRequest(BaseModel):
    repay_mode: str = Field("normal", description="normal/bulk/specific")
    amount_fen: Optional[int] = Field(None, gt=0, description="普通还款金额（分）")
    repay_method: str = Field("cash", description="cash/transfer/wechat")
    transaction_ids: Optional[List[str]] = Field(None, description="指定还款时传入流水ID列表")
    notes: Optional[str] = None
    print_voucher: bool = False


class PrepaidRechargeRequest(BaseModel):
    amount_fen: int = Field(..., gt=0, description="充值金额（分）")
    notes: Optional[str] = None


class PrepaidRefundRequest(BaseModel):
    amount_fen: int = Field(..., gt=0, description="退款金额（分）")
    notes: Optional[str] = None


# ─── GET /agreement-units — 列表 ──────────────────────────────────────────────

@router.get("", summary="协议单位列表")
async def list_units(
    status: Optional[str] = Query(None, description="active/suspended/closed"),
    keyword: Optional[str] = Query(None, description="搜索单位名/联系人"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """协议单位列表，含账户余额汇总，支持状态筛选和关键字搜索。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    where_clauses = ["u.tenant_id = :tenant_id::UUID"]
    params: dict = {"tenant_id": str(tid)}

    if status:
        valid = {"active", "suspended", "closed"}
        if status not in valid:
            raise HTTPException(status_code=400, detail=f"status 必须是: {', '.join(valid)}")
        where_clauses.append("u.status = :status")
        params["status"] = status

    if keyword:
        where_clauses.append("(u.name ILIKE :kw OR u.contact_name ILIKE :kw)")
        params["kw"] = f"%{keyword}%"

    where_sql = " AND ".join(where_clauses)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM agreement_units u WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar()

        items_result = await db.execute(
            text(f"""
                SELECT u.id, u.name, u.short_name, u.contact_name, u.contact_phone,
                       u.credit_limit_fen, u.settlement_cycle, u.settlement_day,
                       u.status, u.notes, u.created_at, u.updated_at,
                       COALESCE(a.balance_fen, 0) AS balance_fen,
                       COALESCE(a.credit_used_fen, 0) AS credit_used_fen,
                       COALESCE(a.total_consumed_fen, 0) AS total_consumed_fen,
                       COALESCE(a.total_repaid_fen, 0) AS total_repaid_fen,
                       (u.credit_limit_fen - COALESCE(a.credit_used_fen, 0)) AS available_credit_fen
                FROM agreement_units u
                LEFT JOIN agreement_accounts a ON a.unit_id = u.id
                WHERE {where_sql}
                ORDER BY u.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [_serialize_row(dict(row)) for row in items_result.mappings().all()]
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，DB不可用时降级mock
        logger.warning("list_units.db_unavailable", error=str(exc))
        # DB不可用时返回mock数据
        return {
            "ok": True,
            "data": {"items": _MOCK_UNITS, "total": len(_MOCK_UNITS), "page": page, "size": size,
                     "_mock": True},
            "error": None,
        }

    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
        "error": None,
    }


# ─── POST /agreement-units — 新建 ─────────────────────────────────────────────

@router.post("", summary="新建协议单位")
async def create_unit(
    body: UnitCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """新建协议单位档案，同步初始化账户记录。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    valid_cycles = {None, "monthly", "weekly", "custom"}
    if body.settlement_cycle not in valid_cycles:
        raise HTTPException(status_code=400,
                            detail="settlement_cycle 必须是: monthly/weekly/custom")

    try:
        async with db.begin():
            # 创建档案
            unit_result = await db.execute(
                text("""
                    INSERT INTO agreement_units (
                        tenant_id, name, short_name, contact_name, contact_phone,
                        credit_limit_fen, settlement_cycle, settlement_day, status, notes
                    ) VALUES (
                        :tenant_id::UUID, :name, :short_name, :contact_name, :contact_phone,
                        :credit_limit_fen, :settlement_cycle, :settlement_day, 'active', :notes
                    )
                    RETURNING id, created_at
                """),
                {
                    "tenant_id": str(tid),
                    "name": body.name,
                    "short_name": body.short_name,
                    "contact_name": body.contact_name,
                    "contact_phone": body.contact_phone,
                    "credit_limit_fen": body.credit_limit_fen,
                    "settlement_cycle": body.settlement_cycle,
                    "settlement_day": body.settlement_day,
                    "notes": body.notes,
                },
            )
            unit_row = unit_result.mappings().first()
            unit_id = str(unit_row["id"])

            # 同步初始化账户
            await db.execute(
                text("""
                    INSERT INTO agreement_accounts (tenant_id, unit_id)
                    VALUES (:tenant_id::UUID, :unit_id::UUID)
                """),
                {"tenant_id": str(tid), "unit_id": unit_id},
            )
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("create_unit.failed", name=body.name, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="创建协议单位失败") from exc

    logger.info("agreement_unit_created", unit_id=unit_id, name=body.name)
    return {
        "ok": True,
        "data": {
            "unit_id": unit_id,
            "name": body.name,
            "status": "active",
            "created_at": unit_row["created_at"].isoformat() if unit_row["created_at"] else None,
        },
        "error": None,
    }


# ─── GET /report/aging — 账龄分析 ────────────────────────────────────────────
# 注：静态路由必须在 {unit_id} 动态路由之前注册

@router.get("/report/aging", summary="账龄分析报表")
async def aging_report(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """账龄分析：将各单位未还挂账按0-30/31-60/61-90/90天+分组统计。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    try:
        result = await db.execute(
            text("""
                SELECT
                    u.id AS unit_id,
                    u.name AS unit_name,
                    u.contact_name,
                    COALESCE(a.credit_used_fen, 0) AS total_owed_fen,
                    COALESCE(SUM(
                        CASE WHEN NOW() - t.created_at <= INTERVAL '30 days'
                             THEN t.amount_fen ELSE 0 END
                    ), 0) AS aged_0_30_fen,
                    COALESCE(SUM(
                        CASE WHEN NOW() - t.created_at > INTERVAL '30 days'
                              AND NOW() - t.created_at <= INTERVAL '60 days'
                             THEN t.amount_fen ELSE 0 END
                    ), 0) AS aged_31_60_fen,
                    COALESCE(SUM(
                        CASE WHEN NOW() - t.created_at > INTERVAL '60 days'
                              AND NOW() - t.created_at <= INTERVAL '90 days'
                             THEN t.amount_fen ELSE 0 END
                    ), 0) AS aged_61_90_fen,
                    COALESCE(SUM(
                        CASE WHEN NOW() - t.created_at > INTERVAL '90 days'
                             THEN t.amount_fen ELSE 0 END
                    ), 0) AS aged_90plus_fen
                FROM agreement_units u
                LEFT JOIN agreement_accounts a ON a.unit_id = u.id
                LEFT JOIN agreement_transactions t
                    ON t.unit_id = u.id
                    AND t.type IN ('charge', 'manual_charge')
                    AND t.tenant_id = :tenant_id::UUID
                WHERE u.tenant_id = :tenant_id::UUID
                  AND u.status != 'closed'
                GROUP BY u.id, u.name, u.contact_name, a.credit_used_fen
                ORDER BY total_owed_fen DESC
            """),
            {"tenant_id": str(tid)},
        )
        items = [_serialize_row(dict(row)) for row in result.mappings().all()]
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，DB不可用时降级mock
        logger.warning("aging_report.db_unavailable", error=str(exc))
        # mock
        items = [
            {
                "unit_id": "00000000-0000-0000-0000-000000000001",
                "unit_name": "示例企业A（测试数据）",
                "total_owed_fen": 30000_00,
                "aged_0_30_fen": 10000_00,
                "aged_31_60_fen": 8000_00,
                "aged_61_90_fen": 7000_00,
                "aged_90plus_fen": 5000_00,
            }
        ]
        return {"ok": True, "data": {"items": items, "_mock": True}, "error": None}

    return {"ok": True, "data": {"items": items}, "error": None}


# ─── GET /report/monthly — 月度对账单 ────────────────────────────────────────

@router.get("/report/monthly", summary="月度对账单")
async def monthly_statement(
    unit_id: str = Query(..., description="协议单位ID"),
    year: int = Query(..., ge=2020, le=2099),
    month: int = Query(..., ge=1, le=12),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """指定协议单位+月份的对账单（挂账明细+还款明细+期末余额）。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    uid = _parse_uuid(unit_id, "unit_id")

    try:
        # 单位信息
        unit_result = await db.execute(
            text("""
                SELECT u.id, u.name, u.credit_limit_fen,
                       COALESCE(a.balance_fen, 0) AS balance_fen
                FROM agreement_units u
                LEFT JOIN agreement_accounts a ON a.unit_id = u.id
                WHERE u.id = :id::UUID AND u.tenant_id = :tenant_id::UUID
            """),
            {"id": str(uid), "tenant_id": str(tid)},
        )
        unit = unit_result.mappings().first()
        if unit is None:
            raise HTTPException(status_code=404, detail=f"协议单位不存在: {unit_id}")

        # 流水明细
        txns_result = await db.execute(
            text("""
                SELECT id, type, amount_fen, order_id, repay_method, notes, created_at
                FROM agreement_transactions
                WHERE tenant_id = :tenant_id::UUID
                  AND unit_id = :unit_id::UUID
                  AND DATE_TRUNC('month', created_at) = MAKE_DATE(:year, :month, 1)::DATE
                ORDER BY created_at ASC
            """),
            {"tenant_id": str(tid), "unit_id": str(uid), "year": year, "month": month},
        )
        transactions = [_serialize_row(dict(row)) for row in txns_result.mappings().all()]

        total_charged = sum(t["amount_fen"] for t in transactions
                            if t["type"] in ("charge", "manual_charge"))
        total_repaid = sum(abs(t["amount_fen"]) for t in transactions if t["type"] == "repay")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("monthly_statement.failed", unit_id=unit_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="对账单查询失败") from exc

    return {
        "ok": True,
        "data": {
            "unit_id": unit_id,
            "unit_name": unit["name"],
            "year": year,
            "month": month,
            "summary": {
                "total_charged_fen": total_charged,
                "total_repaid_fen": total_repaid,
                "net_fen": total_charged - total_repaid,
                "current_balance_fen": unit["balance_fen"],
            },
            "transactions": transactions,
        },
        "error": None,
    }


# ─── GET /{unit_id} — 单位详情 ────────────────────────────────────────────────

@router.get("/{unit_id}", summary="协议单位详情（含账户余额）")
async def get_unit(
    unit_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    uid = _parse_uuid(unit_id, "unit_id")

    try:
        result = await db.execute(
            text("""
                SELECT u.id, u.name, u.short_name, u.contact_name, u.contact_phone,
                       u.credit_limit_fen, u.settlement_cycle, u.settlement_day,
                       u.status, u.notes, u.created_at, u.updated_at,
                       COALESCE(a.balance_fen, 0) AS balance_fen,
                       COALESCE(a.credit_used_fen, 0) AS credit_used_fen,
                       COALESCE(a.total_consumed_fen, 0) AS total_consumed_fen,
                       COALESCE(a.total_repaid_fen, 0) AS total_repaid_fen,
                       a.last_transaction_at,
                       (u.credit_limit_fen - COALESCE(a.credit_used_fen, 0)) AS available_credit_fen
                FROM agreement_units u
                LEFT JOIN agreement_accounts a ON a.unit_id = u.id
                WHERE u.id = :id::UUID AND u.tenant_id = :tenant_id::UUID
            """),
            {"id": str(uid), "tenant_id": str(tid)},
        )
        row = result.mappings().first()
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("get_unit.failed", unit_id=unit_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询协议单位失败") from exc

    if row is None:
        raise HTTPException(status_code=404, detail=f"协议单位不存在: {unit_id}")

    return {"ok": True, "data": _serialize_row(dict(row)), "error": None}


# ─── PUT /{unit_id} — 更新 ───────────────────────────────────────────────────

@router.put("/{unit_id}", summary="更新协议单位信息")
async def update_unit(
    unit_id: str = Path(...),
    body: UnitUpdate = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    uid = _parse_uuid(unit_id, "unit_id")

    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.short_name is not None:
        updates["short_name"] = body.short_name
    if body.contact_name is not None:
        updates["contact_name"] = body.contact_name
    if body.contact_phone is not None:
        updates["contact_phone"] = body.contact_phone
    if body.credit_limit_fen is not None:
        updates["credit_limit_fen"] = body.credit_limit_fen
    if body.settlement_cycle is not None:
        updates["settlement_cycle"] = body.settlement_cycle
    if body.settlement_day is not None:
        updates["settlement_day"] = body.settlement_day
    if body.notes is not None:
        updates["notes"] = body.notes

    if not updates:
        raise HTTPException(status_code=400, detail="无更新字段")

    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = str(uid)
    updates["tenant_id"] = str(tid)

    try:
        result = await db.execute(
            text(f"""
                UPDATE agreement_units
                SET {set_clauses}, updated_at = NOW()
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
                RETURNING id, updated_at
            """),
            updates,
        )
        row = result.mappings().first()
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("update_unit.failed", unit_id=unit_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="更新协议单位失败") from exc

    if row is None:
        raise HTTPException(status_code=404, detail=f"协议单位不存在: {unit_id}")

    return {
        "ok": True,
        "data": {"unit_id": unit_id, "updated_at": row["updated_at"].isoformat()},
        "error": None,
    }


# ─── POST /{unit_id}/suspend — 暂停/启用 ──────────────────────────────────────

@router.post("/{unit_id}/suspend", summary="暂停或启用协议单位")
async def toggle_suspend(
    unit_id: str = Path(...),
    body: SuspendRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    uid = _parse_uuid(unit_id, "unit_id")

    if body.action not in ("suspend", "resume"):
        raise HTTPException(status_code=400, detail="action 必须是 suspend 或 resume")

    new_status = "suspended" if body.action == "suspend" else "active"
    from_status = "active" if body.action == "suspend" else "suspended"

    try:
        result = await db.execute(
            text("""
                UPDATE agreement_units
                SET status = :new_status, updated_at = NOW()
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
                  AND status = :from_status
                RETURNING id, status
            """),
            {
                "new_status": new_status,
                "from_status": from_status,
                "id": str(uid),
                "tenant_id": str(tid),
            },
        )
        row = result.mappings().first()
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("toggle_suspend.failed", unit_id=unit_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="操作失败") from exc

    if row is None:
        raise HTTPException(
            status_code=409,
            detail=f"协议单位不存在或状态不符（期望状态: {from_status}）",
        )

    logger.info("agreement_unit_status_changed", unit_id=unit_id, new_status=new_status)
    return {"ok": True, "data": {"unit_id": unit_id, "status": new_status}, "error": None}


# ─── GET /{unit_id}/transactions — 流水 ──────────────────────────────────────

@router.get("/{unit_id}/transactions", summary="挂账/还款流水（分页）")
async def list_transactions(
    unit_id: str = Path(...),
    txn_type: Optional[str] = Query(None, description="charge/repay/manual_charge"),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    uid = _parse_uuid(unit_id, "unit_id")

    where_clauses = [
        "tenant_id = :tenant_id::UUID",
        "unit_id = :unit_id::UUID",
    ]
    params: dict = {"tenant_id": str(tid), "unit_id": str(uid)}

    if txn_type:
        valid = {"charge", "repay", "manual_charge"}
        if txn_type not in valid:
            raise HTTPException(status_code=400, detail=f"type 必须是: {', '.join(valid)}")
        where_clauses.append("type = :type")
        params["type"] = txn_type

    if start_date:
        where_clauses.append("created_at >= :start_date::DATE")
        params["start_date"] = start_date

    if end_date:
        where_clauses.append("created_at < (:end_date::DATE + INTERVAL '1 day')")
        params["end_date"] = end_date

    where_sql = " AND ".join(where_clauses)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM agreement_transactions WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar()

        items_result = await db.execute(
            text(f"""
                SELECT id, type, amount_fen, order_id, operator_id,
                       repay_method, notes, created_at
                FROM agreement_transactions
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [_serialize_row(dict(row)) for row in items_result.mappings().all()]
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，DB不可用时降级空列表
        logger.warning("list_transactions.db_unavailable", error=str(exc))
        return {
            "ok": True,
            "data": {"items": [], "total": 0, "page": page, "size": size, "_mock": True},
            "error": None,
        }

    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
        "error": None,
    }


# ─── POST /{unit_id}/charge — 手动挂账 ───────────────────────────────────────

@router.post("/{unit_id}/charge", summary="手动挂账")
async def manual_charge(
    unit_id: str = Path(...),
    body: ChargeRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """手动挂账：校验授信额度，超限返回400；成功后可选返回打印凭证数据。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")
    uid = _parse_uuid(unit_id, "unit_id")

    try:
        fetch = await db.execute(
            text("""
                SELECT u.id, u.name, u.credit_limit_fen, u.status,
                       COALESCE(a.credit_used_fen, 0) AS credit_used_fen,
                       a.id AS account_id
                FROM agreement_units u
                LEFT JOIN agreement_accounts a ON a.unit_id = u.id
                WHERE u.id = :id::UUID AND u.tenant_id = :tenant_id::UUID
            """),
            {"id": str(uid), "tenant_id": str(tid)},
        )
        unit = fetch.mappings().first()
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("manual_charge.fetch_failed", unit_id=unit_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询协议单位失败") from exc

    if unit is None:
        raise HTTPException(status_code=404, detail=f"协议单位不存在: {unit_id}")

    if unit["status"] != "active":
        raise HTTPException(status_code=409,
                            detail=f"协议单位状态 {unit['status']} 不允许挂账")

    # 授信额度检查
    available_credit = unit["credit_limit_fen"] - unit["credit_used_fen"]
    if body.amount_fen > available_credit:
        raise HTTPException(
            status_code=400,
            detail=(
                f"超出授信额度：可用 {available_credit} 分，本次需 {body.amount_fen} 分"
            ),
        )

    new_credit_used = unit["credit_used_fen"] + body.amount_fen
    account_id = str(unit["account_id"]) if unit["account_id"] else None

    try:
        async with db.begin():
            # 写流水
            txn_result = await db.execute(
                text("""
                    INSERT INTO agreement_transactions (
                        tenant_id, unit_id, account_id, type, amount_fen,
                        order_id, operator_id, notes
                    ) VALUES (
                        :tenant_id::UUID, :unit_id::UUID,
                        :account_id::UUID,
                        'manual_charge', :amount_fen,
                        :order_id, :operator_id::UUID, :notes
                    )
                    RETURNING id, created_at
                """),
                {
                    "tenant_id": str(tid),
                    "unit_id": str(uid),
                    "account_id": account_id,
                    "amount_fen": body.amount_fen,
                    "order_id": body.order_id,
                    "operator_id": str(op_id),
                    "notes": body.notes,
                },
            )
            txn_row = txn_result.mappings().first()

            # 更新账户
            await db.execute(
                text("""
                    UPDATE agreement_accounts
                    SET credit_used_fen = :new_credit_used,
                        balance_fen = balance_fen - :amount_fen,
                        total_consumed_fen = total_consumed_fen + :amount_fen,
                        last_transaction_at = NOW(),
                        updated_at = NOW()
                    WHERE unit_id = :unit_id::UUID AND tenant_id = :tenant_id::UUID
                """),
                {
                    "new_credit_used": new_credit_used,
                    "amount_fen": body.amount_fen,
                    "unit_id": str(uid),
                    "tenant_id": str(tid),
                },
            )
    except Exception as exc:
        logger.error("manual_charge.failed", unit_id=unit_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="手动挂账失败") from exc

    txn_id = str(txn_row["id"])
    created_at_str = txn_row["created_at"].isoformat() if txn_row["created_at"] else ""

    logger.info("agreement_unit_charged", unit_id=unit_id, txn_id=txn_id,
                amount_fen=body.amount_fen)

    response: dict = {
        "ok": True,
        "data": {
            "txn_id": txn_id,
            "unit_id": unit_id,
            "amount_fen": body.amount_fen,
            "new_credit_used_fen": new_credit_used,
            "available_credit_fen": unit["credit_limit_fen"] - new_credit_used,
            "created_at": created_at_str,
        },
        "error": None,
    }

    if body.print_voucher:
        response["data"]["voucher"] = _format_voucher(
            unit_name=unit["name"],
            txn_type="manual_charge",
            amount_fen=body.amount_fen,
            operator=str(op_id),
            notes=body.notes or "",
            txn_id=txn_id,
            created_at=created_at_str,
        )

    return response


# ─── POST /{unit_id}/repay — 还款 ────────────────────────────────────────────

@router.post("/{unit_id}/repay", summary="还款（普通/指定/批量）")
async def repay(
    unit_id: str = Path(...),
    body: RepayRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """还款接口，支持三种模式：
    - normal: 还指定金额
    - bulk: 一次性结清所有欠款（amount_fen 可留空，系统自动计算）
    - specific: 针对指定挂账流水还款（传 transaction_ids）
    """
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")
    uid = _parse_uuid(unit_id, "unit_id")

    valid_modes = {"normal", "bulk", "specific"}
    if body.repay_mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"repay_mode 必须是: {', '.join(valid_modes)}")

    valid_methods = {"cash", "transfer", "wechat"}
    if body.repay_method not in valid_methods:
        raise HTTPException(status_code=400, detail=f"repay_method 必须是: {', '.join(valid_methods)}")

    try:
        fetch = await db.execute(
            text("""
                SELECT u.id, u.name, u.status,
                       COALESCE(a.credit_used_fen, 0) AS credit_used_fen,
                       a.id AS account_id
                FROM agreement_units u
                LEFT JOIN agreement_accounts a ON a.unit_id = u.id
                WHERE u.id = :id::UUID AND u.tenant_id = :tenant_id::UUID
            """),
            {"id": str(uid), "tenant_id": str(tid)},
        )
        unit = fetch.mappings().first()
    except Exception as exc:
        logger.error("repay.fetch_failed", unit_id=unit_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询协议单位失败") from exc

    if unit is None:
        raise HTTPException(status_code=404, detail=f"协议单位不存在: {unit_id}")

    account_id = str(unit["account_id"]) if unit["account_id"] else None
    credit_used = unit["credit_used_fen"]

    # 确定还款金额
    if body.repay_mode == "bulk":
        pay_amount = credit_used
        if pay_amount <= 0:
            raise HTTPException(status_code=400, detail="当前无欠款，无需还款")
    elif body.repay_mode == "normal":
        if body.amount_fen is None:
            raise HTTPException(status_code=400, detail="普通还款需要提供 amount_fen")
        pay_amount = body.amount_fen
    else:  # specific
        if not body.transaction_ids:
            raise HTTPException(status_code=400, detail="指定还款需要提供 transaction_ids")
        # 计算指定流水的总金额
        try:
            sum_result = await db.execute(
                text("""
                    SELECT COALESCE(SUM(amount_fen), 0) AS total
                    FROM agreement_transactions
                    WHERE id = ANY(:ids::UUID[])
                      AND unit_id = :unit_id::UUID
                      AND tenant_id = :tenant_id::UUID
                      AND type IN ('charge', 'manual_charge')
                """),
                {
                    "ids": body.transaction_ids,
                    "unit_id": str(uid),
                    "tenant_id": str(tid),
                },
            )
            pay_amount = sum_result.scalar() or 0
        except Exception as exc:
            logger.error("repay.sum_specific_failed", error=str(exc), exc_info=True)
            raise HTTPException(status_code=500, detail="计算指定还款金额失败") from exc

    if pay_amount <= 0:
        raise HTTPException(status_code=400, detail="还款金额必须大于0")

    new_credit_used = max(0, credit_used - pay_amount)

    try:
        async with db.begin():
            # 写还款流水
            txn_result = await db.execute(
                text("""
                    INSERT INTO agreement_transactions (
                        tenant_id, unit_id, account_id, type, amount_fen,
                        operator_id, repay_method, notes
                    ) VALUES (
                        :tenant_id::UUID, :unit_id::UUID,
                        :account_id::UUID,
                        'repay', :amount_fen,
                        :operator_id::UUID, :repay_method, :notes
                    )
                    RETURNING id, created_at
                """),
                {
                    "tenant_id": str(tid),
                    "unit_id": str(uid),
                    "account_id": account_id,
                    "amount_fen": -pay_amount,   # 还款金额存为负数
                    "operator_id": str(op_id),
                    "repay_method": body.repay_method,
                    "notes": body.notes,
                },
            )
            txn_row = txn_result.mappings().first()

            # 更新账户
            await db.execute(
                text("""
                    UPDATE agreement_accounts
                    SET credit_used_fen = :new_credit_used,
                        balance_fen = balance_fen + :pay_amount,
                        total_repaid_fen = total_repaid_fen + :pay_amount,
                        last_transaction_at = NOW(),
                        updated_at = NOW()
                    WHERE unit_id = :unit_id::UUID AND tenant_id = :tenant_id::UUID
                """),
                {
                    "new_credit_used": new_credit_used,
                    "pay_amount": pay_amount,
                    "unit_id": str(uid),
                    "tenant_id": str(tid),
                },
            )
    except Exception as exc:
        logger.error("repay.failed", unit_id=unit_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="还款失败") from exc

    txn_id = str(txn_row["id"])
    created_at_str = txn_row["created_at"].isoformat() if txn_row["created_at"] else ""

    logger.info("agreement_unit_repaid", unit_id=unit_id, txn_id=txn_id,
                pay_amount=pay_amount, mode=body.repay_mode)

    response: dict = {
        "ok": True,
        "data": {
            "txn_id": txn_id,
            "unit_id": unit_id,
            "repay_mode": body.repay_mode,
            "pay_amount_fen": pay_amount,
            "new_credit_used_fen": new_credit_used,
            "created_at": created_at_str,
        },
        "error": None,
    }

    if body.print_voucher:
        response["data"]["voucher"] = _format_voucher(
            unit_name=unit["name"],
            txn_type="repay",
            amount_fen=pay_amount,
            operator=str(op_id),
            notes=body.notes or "",
            txn_id=txn_id,
            created_at=created_at_str,
        )

    return response


# ─── POST /{unit_id}/prepaid/recharge — 预付充值 ─────────────────────────────

@router.post("/{unit_id}/prepaid/recharge", summary="预付充值")
async def prepaid_recharge(
    unit_id: str = Path(...),
    body: PrepaidRechargeRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")
    uid = _parse_uuid(unit_id, "unit_id")

    try:
        fetch = await db.execute(
            text("""
                SELECT u.id, a.id AS account_id
                FROM agreement_units u
                LEFT JOIN agreement_accounts a ON a.unit_id = u.id
                WHERE u.id = :id::UUID AND u.tenant_id = :tenant_id::UUID
            """),
            {"id": str(uid), "tenant_id": str(tid)},
        )
        unit = fetch.mappings().first()
    except Exception as exc:
        logger.error("prepaid_recharge.fetch_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询协议单位失败") from exc

    if unit is None:
        raise HTTPException(status_code=404, detail=f"协议单位不存在: {unit_id}")

    account_id = str(unit["account_id"]) if unit["account_id"] else None

    try:
        async with db.begin():
            rec_result = await db.execute(
                text("""
                    INSERT INTO prepaid_records (
                        tenant_id, unit_id, account_id, type, amount_fen,
                        operator_id, notes
                    ) VALUES (
                        :tenant_id::UUID, :unit_id::UUID, :account_id::UUID,
                        'recharge', :amount_fen, :operator_id::UUID, :notes
                    )
                    RETURNING id, created_at
                """),
                {
                    "tenant_id": str(tid),
                    "unit_id": str(uid),
                    "account_id": account_id,
                    "amount_fen": body.amount_fen,
                    "operator_id": str(op_id),
                    "notes": body.notes,
                },
            )
            rec_row = rec_result.mappings().first()

            # 预付充值增加余额
            await db.execute(
                text("""
                    UPDATE agreement_accounts
                    SET balance_fen = balance_fen + :amount_fen,
                        last_transaction_at = NOW(),
                        updated_at = NOW()
                    WHERE unit_id = :unit_id::UUID AND tenant_id = :tenant_id::UUID
                """),
                {
                    "amount_fen": body.amount_fen,
                    "unit_id": str(uid),
                    "tenant_id": str(tid),
                },
            )
    except Exception as exc:
        logger.error("prepaid_recharge.failed", unit_id=unit_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="预付充值失败") from exc

    logger.info("prepaid_recharged", unit_id=unit_id, amount_fen=body.amount_fen)
    return {
        "ok": True,
        "data": {
            "record_id": str(rec_row["id"]),
            "unit_id": unit_id,
            "amount_fen": body.amount_fen,
            "type": "recharge",
            "created_at": rec_row["created_at"].isoformat() if rec_row["created_at"] else None,
        },
        "error": None,
    }


# ─── POST /{unit_id}/prepaid/refund — 预付退款 ───────────────────────────────

@router.post("/{unit_id}/prepaid/refund", summary="预付退款")
async def prepaid_refund(
    unit_id: str = Path(...),
    body: PrepaidRefundRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")
    uid = _parse_uuid(unit_id, "unit_id")

    try:
        fetch = await db.execute(
            text("""
                SELECT u.id, u.name,
                       COALESCE(a.balance_fen, 0) AS balance_fen,
                       a.id AS account_id
                FROM agreement_units u
                LEFT JOIN agreement_accounts a ON a.unit_id = u.id
                WHERE u.id = :id::UUID AND u.tenant_id = :tenant_id::UUID
            """),
            {"id": str(uid), "tenant_id": str(tid)},
        )
        unit = fetch.mappings().first()
    except Exception as exc:
        logger.error("prepaid_refund.fetch_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询协议单位失败") from exc

    if unit is None:
        raise HTTPException(status_code=404, detail=f"协议单位不存在: {unit_id}")

    if unit["balance_fen"] < body.amount_fen:
        raise HTTPException(
            status_code=400,
            detail=f"余额不足：当前余额 {unit['balance_fen']} 分，退款需 {body.amount_fen} 分",
        )

    account_id = str(unit["account_id"]) if unit["account_id"] else None

    try:
        async with db.begin():
            rec_result = await db.execute(
                text("""
                    INSERT INTO prepaid_records (
                        tenant_id, unit_id, account_id, type, amount_fen,
                        operator_id, notes
                    ) VALUES (
                        :tenant_id::UUID, :unit_id::UUID, :account_id::UUID,
                        'refund', :amount_fen, :operator_id::UUID, :notes
                    )
                    RETURNING id, created_at
                """),
                {
                    "tenant_id": str(tid),
                    "unit_id": str(uid),
                    "account_id": account_id,
                    "amount_fen": body.amount_fen,
                    "operator_id": str(op_id),
                    "notes": body.notes,
                },
            )
            rec_row = rec_result.mappings().first()

            await db.execute(
                text("""
                    UPDATE agreement_accounts
                    SET balance_fen = balance_fen - :amount_fen,
                        last_transaction_at = NOW(),
                        updated_at = NOW()
                    WHERE unit_id = :unit_id::UUID AND tenant_id = :tenant_id::UUID
                """),
                {
                    "amount_fen": body.amount_fen,
                    "unit_id": str(uid),
                    "tenant_id": str(tid),
                },
            )
    except Exception as exc:
        logger.error("prepaid_refund.failed", unit_id=unit_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="预付退款失败") from exc

    logger.info("prepaid_refunded", unit_id=unit_id, amount_fen=body.amount_fen)
    return {
        "ok": True,
        "data": {
            "record_id": str(rec_row["id"]),
            "unit_id": unit_id,
            "amount_fen": body.amount_fen,
            "type": "refund",
            "created_at": rec_row["created_at"].isoformat() if rec_row["created_at"] else None,
        },
        "error": None,
    }


# ─── GET /{unit_id}/prepaid/balance — 预付余额 ───────────────────────────────

@router.get("/{unit_id}/prepaid/balance", summary="预付余额")
async def prepaid_balance(
    unit_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    uid = _parse_uuid(unit_id, "unit_id")

    try:
        result = await db.execute(
            text("""
                SELECT u.name,
                       COALESCE(a.balance_fen, 0) AS balance_fen,
                       COALESCE(
                           (SELECT SUM(amount_fen) FROM prepaid_records
                            WHERE unit_id = u.id AND type = 'recharge'
                              AND tenant_id = :tenant_id::UUID), 0
                       ) AS total_recharged_fen,
                       COALESCE(
                           (SELECT SUM(amount_fen) FROM prepaid_records
                            WHERE unit_id = u.id AND type = 'refund'
                              AND tenant_id = :tenant_id::UUID), 0
                       ) AS total_refunded_fen
                FROM agreement_units u
                LEFT JOIN agreement_accounts a ON a.unit_id = u.id
                WHERE u.id = :id::UUID AND u.tenant_id = :tenant_id::UUID
            """),
            {"id": str(uid), "tenant_id": str(tid)},
        )
        row = result.mappings().first()
    except Exception as exc:
        logger.error("prepaid_balance.failed", unit_id=unit_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询预付余额失败") from exc

    if row is None:
        raise HTTPException(status_code=404, detail=f"协议单位不存在: {unit_id}")

    return {
        "ok": True,
        "data": _serialize_row(dict(row)),
        "error": None,
    }
