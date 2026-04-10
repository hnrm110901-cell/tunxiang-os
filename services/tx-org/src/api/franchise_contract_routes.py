"""
加盟商合同+收费管理路由

端点清单：
  ─ 合同管理 ─
  GET    /api/v1/org/franchise/contracts              — 合同列表（franchisee_id/status/expiring过滤）
  GET    /api/v1/org/franchise/contracts/expiring     — 即将到期合同
  GET    /api/v1/org/franchise/contracts/{id}         — 合同详情
  POST   /api/v1/org/franchise/contracts              — 创建合同（自动生成contract_no）
  PUT    /api/v1/org/franchise/contracts/{id}         — 更新合同
  POST   /api/v1/org/franchise/contracts/{id}/send-alert  — 触发到期提醒

  ─ 收费管理 ─
  GET    /api/v1/org/franchise/fees                   — 收费记录列表
  POST   /api/v1/org/franchise/fees                   — 新增收费记录
  PUT    /api/v1/org/franchise/fees/{id}/pay          — 标记付款
  GET    /api/v1/org/franchise/fees/overdue           — 逾期未付记录
  GET    /api/v1/org/franchise/fees/stats             — 收费统计

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
金额单位：分（int）。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/org/franchise", tags=["franchise-contracts"])

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Mock 数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_TODAY = date(2026, 4, 6)

MOCK_CONTRACTS: list[dict[str, Any]] = [
    {
        "id": "fc-001",
        "contract_no": "FC-202604-0001",
        "contract_type": "initial",
        "franchisee_id": "fr-001",
        "franchisee_name": "长沙五一广场店",
        "sign_date": "2024-03-01",
        "start_date": "2024-03-01",
        "end_date": "2027-02-28",
        "contract_amount_fen": 30000000,
        "file_url": None,
        "status": "active",
        "alert_days_before": 30,
        "days_to_expire": 695,
        "notes": "首签合同，三年期",
        "created_by": None,
        "is_deleted": False,
        "created_at": "2024-03-01T09:00:00+08:00",
        "updated_at": "2024-03-01T09:00:00+08:00",
    },
    {
        "id": "fc-002",
        "contract_no": "FC-202604-0002",
        "contract_type": "renewal",
        "franchisee_id": "fr-002",
        "franchisee_name": "武汉光谷店",
        "sign_date": "2026-01-15",
        "start_date": "2026-01-15",
        "end_date": "2026-05-05",
        "contract_amount_fen": 12000000,
        "file_url": None,
        "status": "active",
        "alert_days_before": 30,
        "days_to_expire": 29,
        "notes": "续签合同，到期前请及时续签",
        "created_by": None,
        "is_deleted": False,
        "created_at": "2026-01-15T10:00:00+08:00",
        "updated_at": "2026-01-15T10:00:00+08:00",
    },
    {
        "id": "fc-003",
        "contract_no": "FC-202604-0003",
        "contract_type": "initial",
        "franchisee_id": "fr-003",
        "franchisee_name": "深圳南山店",
        "sign_date": "2025-06-01",
        "start_date": "2025-06-01",
        "end_date": "2028-05-31",
        "contract_amount_fen": 30000000,
        "file_url": None,
        "status": "active",
        "alert_days_before": 30,
        "days_to_expire": 786,
        "notes": None,
        "created_by": None,
        "is_deleted": False,
        "created_at": "2025-06-01T09:00:00+08:00",
        "updated_at": "2025-06-01T09:00:00+08:00",
    },
]

MOCK_FEE_RECORDS: list[dict[str, Any]] = [
    {
        "id": "fee-001",
        "franchisee_id": "fr-001",
        "franchisee_name": "长沙五一广场店",
        "contract_id": "fc-001",
        "fee_type": "joining_fee",
        "period_start": None,
        "period_end": None,
        "amount_fen": 10000000,
        "paid_fen": 10000000,
        "due_date": "2024-03-15",
        "status": "paid",
        "receipt_no": "RCP-2024-0001",
        "receipt_url": None,
        "notes": "加盟费一次性付清",
        "created_at": "2024-03-01T09:00:00+08:00",
        "updated_at": "2024-03-15T14:00:00+08:00",
    },
    {
        "id": "fee-002",
        "franchisee_id": "fr-001",
        "franchisee_name": "长沙五一广场店",
        "contract_id": "fc-001",
        "fee_type": "royalty",
        "period_start": "2026-01-01",
        "period_end": "2026-03-31",
        "amount_fen": 500000,
        "paid_fen": 0,
        "due_date": "2026-04-10",
        "status": "unpaid",
        "receipt_no": None,
        "receipt_url": None,
        "notes": "2026年Q1提成",
        "created_at": "2026-04-01T09:00:00+08:00",
        "updated_at": "2026-04-01T09:00:00+08:00",
    },
    {
        "id": "fee-003",
        "franchisee_id": "fr-002",
        "franchisee_name": "武汉光谷店",
        "contract_id": "fc-002",
        "fee_type": "management_fee",
        "period_start": "2026-01-01",
        "period_end": "2026-03-31",
        "amount_fen": 300000,
        "paid_fen": 0,
        "due_date": "2026-03-31",
        "status": "overdue",
        "receipt_no": None,
        "receipt_url": None,
        "notes": "管理费逾期未付",
        "created_at": "2026-01-01T09:00:00+08:00",
        "updated_at": "2026-04-01T09:00:00+08:00",
    },
    {
        "id": "fee-004",
        "franchisee_id": "fr-003",
        "franchisee_name": "深圳南山店",
        "contract_id": "fc-003",
        "fee_type": "deposit",
        "period_start": None,
        "period_end": None,
        "amount_fen": 5000000,
        "paid_fen": 2500000,
        "due_date": "2025-06-30",
        "status": "partial",
        "receipt_no": "RCP-2025-0001",
        "receipt_url": None,
        "notes": "保证金分两期缴纳，已付第一期",
        "created_at": "2025-06-01T09:00:00+08:00",
        "updated_at": "2025-07-01T09:00:00+08:00",
    },
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pydantic 模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ContractCreate(BaseModel):
    franchisee_id: str
    franchisee_name: Optional[str] = None
    contract_type: str = Field(
        ..., description="initial / renewal / amendment"
    )
    sign_date: str
    start_date: str
    end_date: str
    contract_amount_fen: int = Field(default=0, ge=0)
    file_url: Optional[str] = None
    alert_days_before: int = Field(default=30, ge=1)
    notes: Optional[str] = None


class ContractUpdate(BaseModel):
    contract_type: Optional[str] = None
    sign_date: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    contract_amount_fen: Optional[int] = Field(default=None, ge=0)
    file_url: Optional[str] = None
    status: Optional[str] = None
    alert_days_before: Optional[int] = Field(default=None, ge=1)
    notes: Optional[str] = None


class FeeRecordCreate(BaseModel):
    franchisee_id: str
    franchisee_name: Optional[str] = None
    contract_id: Optional[str] = None
    fee_type: str = Field(
        ...,
        description="joining_fee/royalty/management_fee/marketing_fee/deposit",
    )
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    amount_fen: int = Field(..., gt=0)
    due_date: Optional[str] = None
    notes: Optional[str] = None


class FeePayRequest(BaseModel):
    paid_fen: int = Field(..., gt=0, description="本次实际付款金额（分）")
    receipt_no: Optional[str] = None
    receipt_url: Optional[str] = None
    notes: Optional[str] = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _compute_days_to_expire(end_date_str: str) -> int:
    """计算距到期天数（可为负数表示已过期）。"""
    end_dt = date.fromisoformat(end_date_str)
    return (end_dt - _TODAY).days


def _generate_contract_no() -> str:
    """自动生成合同编号：FC-YYYYMM-XXXX。"""
    ym = datetime.now().strftime("%Y%m")
    suffix = str(uuid.uuid4().int)[:4].zfill(4)
    return f"FC-{ym}-{suffix}"


def _enrich_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """补充 days_to_expire 字段。"""
    enriched = dict(contract)
    enriched["days_to_expire"] = _compute_days_to_expire(contract["end_date"])
    return enriched


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  合同管理端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/contracts/expiring")
async def get_expiring_contracts(
    days: int = Query(default=30, ge=1, description="N天内到期"),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """即将到期合同列表（end_date <= today + days）。"""
    threshold = days
    expiring = []
    for c in MOCK_CONTRACTS:
        if c.get("is_deleted"):
            continue
        days_left = _compute_days_to_expire(c["end_date"])
        if 0 <= days_left <= threshold:
            enriched = _enrich_contract(c)
            enriched["warning"] = True
            expiring.append(enriched)

    expiring.sort(key=lambda x: x["days_to_expire"])
    logger.info(
        "franchise_contracts_expiring_queried",
        tenant_id=x_tenant_id,
        days=days,
        count=len(expiring),
    )
    return {"ok": True, "data": {"items": expiring, "total": len(expiring)}}


@router.get("/contracts")
async def list_contracts(
    franchisee_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    expiring: Optional[int] = Query(default=None, description="N天内到期过滤"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """合同列表，支持多维过滤。"""
    items = [c for c in MOCK_CONTRACTS if not c.get("is_deleted")]

    if franchisee_id:
        items = [c for c in items if c["franchisee_id"] == franchisee_id]
    if status:
        items = [c for c in items if c["status"] == status]
    if expiring is not None:
        items = [
            c for c in items
            if 0 <= _compute_days_to_expire(c["end_date"]) <= expiring
        ]

    total = len(items)
    start = (page - 1) * size
    page_items = [_enrich_contract(c) for c in items[start: start + size]]

    logger.info(
        "franchise_contracts_listed",
        tenant_id=x_tenant_id,
        total=total,
        page=page,
    )
    return {"ok": True, "data": {"items": page_items, "total": total}}


@router.get("/contracts/{contract_id}")
async def get_contract(
    contract_id: str,
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """合同详情。"""
    for c in MOCK_CONTRACTS:
        if c["id"] == contract_id and not c.get("is_deleted"):
            return {"ok": True, "data": _enrich_contract(c)}

    raise HTTPException(status_code=404, detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "合同不存在"}})


@router.post("/contracts")
async def create_contract(
    body: ContractCreate,
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """创建合同，自动生成合同编号。"""
    contract_no = _generate_contract_no()
    now_str = datetime.now().isoformat()
    new_contract: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "contract_no": contract_no,
        "contract_type": body.contract_type,
        "franchisee_id": body.franchisee_id,
        "franchisee_name": body.franchisee_name or "",
        "sign_date": body.sign_date,
        "start_date": body.start_date,
        "end_date": body.end_date,
        "contract_amount_fen": body.contract_amount_fen,
        "file_url": body.file_url,
        "status": "active",
        "alert_days_before": body.alert_days_before,
        "notes": body.notes,
        "created_by": None,
        "is_deleted": False,
        "created_at": now_str,
        "updated_at": now_str,
    }
    MOCK_CONTRACTS.append(new_contract)

    logger.info(
        "franchise_contract_created",
        tenant_id=x_tenant_id,
        contract_id=new_contract["id"],
        contract_no=contract_no,
    )
    return {"ok": True, "data": _enrich_contract(new_contract)}


@router.put("/contracts/{contract_id}")
async def update_contract(
    contract_id: str,
    body: ContractUpdate,
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """更新合同信息。"""
    for i, c in enumerate(MOCK_CONTRACTS):
        if c["id"] == contract_id and not c.get("is_deleted"):
            updated = dict(c)
            update_data = body.model_dump(exclude_none=True)
            updated.update(update_data)
            updated["updated_at"] = datetime.now().isoformat()
            MOCK_CONTRACTS[i] = updated

            logger.info(
                "franchise_contract_updated",
                tenant_id=x_tenant_id,
                contract_id=contract_id,
                fields=list(update_data.keys()),
            )
            return {"ok": True, "data": _enrich_contract(updated)}

    raise HTTPException(status_code=404, detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "合同不存在"}})


@router.post("/contracts/{contract_id}/send-alert")
async def send_contract_alert(
    contract_id: str,
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """触发到期提醒（模拟发送企微通知）。"""
    target: Optional[dict[str, Any]] = None
    for c in MOCK_CONTRACTS:
        if c["id"] == contract_id and not c.get("is_deleted"):
            target = c
            break

    if target is None:
        raise HTTPException(
            status_code=404,
            detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "合同不存在"}},
        )

    days_left = _compute_days_to_expire(target["end_date"])
    alert_msg = (
        f"【屯象OS合同到期提醒】加盟商「{target.get('franchisee_name', target['franchisee_id'])}」"
        f"合同（{target['contract_no']}）将于 {target['end_date']} 到期，"
        f"距今还有 {days_left} 天，请及时跟进续签事宜。"
    )

    # 模拟企微通知发送（实际接入企微 webhook 时替换此处）
    logger.info(
        "franchise_contract_alert_sent",
        tenant_id=x_tenant_id,
        contract_id=contract_id,
        contract_no=target["contract_no"],
        days_to_expire=days_left,
        alert_msg=alert_msg,
        channel="wecom_mock",
    )

    return {
        "ok": True,
        "data": {
            "contract_id": contract_id,
            "contract_no": target["contract_no"],
            "days_to_expire": days_left,
            "alert_sent": True,
            "channel": "wecom_mock",
            "message": alert_msg,
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  收费管理端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/fees/overdue")
async def get_overdue_fees(
    franchisee_id: Optional[str] = Query(default=None),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """逾期未付收费记录。"""
    overdue = [
        r for r in MOCK_FEE_RECORDS
        if r["status"] == "overdue" and (
            franchisee_id is None or r["franchisee_id"] == franchisee_id
        )
    ]

    total_overdue_fen = sum(
        r["amount_fen"] - r["paid_fen"] for r in overdue
    )

    logger.info(
        "franchise_fees_overdue_queried",
        tenant_id=x_tenant_id,
        count=len(overdue),
        total_overdue_fen=total_overdue_fen,
    )
    return {
        "ok": True,
        "data": {
            "items": overdue,
            "total": len(overdue),
            "total_overdue_fen": total_overdue_fen,
        },
    }


@router.get("/fees/stats")
async def get_fee_stats(
    franchisee_id: Optional[str] = Query(default=None),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """收费统计：按类型汇总应收/已收/逾期金额。"""
    records = MOCK_FEE_RECORDS
    if franchisee_id:
        records = [r for r in records if r["franchisee_id"] == franchisee_id]

    total_amount_fen: int = 0
    total_paid_fen: int = 0
    total_overdue_fen: int = 0
    by_type: dict[str, dict[str, int]] = {}

    for r in records:
        fee_type = r["fee_type"]
        if fee_type not in by_type:
            by_type[fee_type] = {"amount_fen": 0, "paid_fen": 0, "overdue_fen": 0}

        by_type[fee_type]["amount_fen"] += r["amount_fen"]
        by_type[fee_type]["paid_fen"] += r["paid_fen"]
        total_amount_fen += r["amount_fen"]
        total_paid_fen += r["paid_fen"]

        if r["status"] == "overdue":
            overdue_fen = r["amount_fen"] - r["paid_fen"]
            by_type[fee_type]["overdue_fen"] += overdue_fen
            total_overdue_fen += overdue_fen

    by_type_list = [
        {"fee_type": k, **v} for k, v in by_type.items()
    ]

    logger.info(
        "franchise_fees_stats_queried",
        tenant_id=x_tenant_id,
        total_amount_fen=total_amount_fen,
        total_paid_fen=total_paid_fen,
        total_overdue_fen=total_overdue_fen,
    )
    return {
        "ok": True,
        "data": {
            "total_amount_fen": total_amount_fen,
            "total_paid_fen": total_paid_fen,
            "total_unpaid_fen": total_amount_fen - total_paid_fen,
            "total_overdue_fen": total_overdue_fen,
            "by_type": by_type_list,
        },
    }


@router.get("/fees")
async def list_fees(
    franchisee_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    fee_type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """收费记录列表，支持多维过滤。"""
    items = list(MOCK_FEE_RECORDS)

    if franchisee_id:
        items = [r for r in items if r["franchisee_id"] == franchisee_id]
    if status:
        items = [r for r in items if r["status"] == status]
    if fee_type:
        items = [r for r in items if r["fee_type"] == fee_type]

    total = len(items)
    start = (page - 1) * size
    page_items = items[start: start + size]

    logger.info(
        "franchise_fees_listed",
        tenant_id=x_tenant_id,
        total=total,
        page=page,
    )
    return {"ok": True, "data": {"items": page_items, "total": total}}


@router.post("/fees")
async def create_fee_record(
    body: FeeRecordCreate,
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """新增收费记录。"""
    now_str = datetime.now().isoformat()
    new_record: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "franchisee_id": body.franchisee_id,
        "franchisee_name": body.franchisee_name or "",
        "contract_id": body.contract_id,
        "fee_type": body.fee_type,
        "period_start": body.period_start,
        "period_end": body.period_end,
        "amount_fen": body.amount_fen,
        "paid_fen": 0,
        "due_date": body.due_date,
        "status": "unpaid",
        "receipt_no": None,
        "receipt_url": None,
        "notes": body.notes,
        "created_at": now_str,
        "updated_at": now_str,
    }
    MOCK_FEE_RECORDS.append(new_record)

    logger.info(
        "franchise_fee_record_created",
        tenant_id=x_tenant_id,
        fee_id=new_record["id"],
        fee_type=body.fee_type,
        amount_fen=body.amount_fen,
    )
    return {"ok": True, "data": new_record}


@router.put("/fees/{fee_id}/pay")
async def pay_fee_record(
    fee_id: str,
    body: FeePayRequest,
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """标记付款：更新 paid_fen / status / receipt_no。"""
    for i, r in enumerate(MOCK_FEE_RECORDS):
        if r["id"] == fee_id:
            updated = dict(r)
            new_paid = r["paid_fen"] + body.paid_fen

            if new_paid > r["amount_fen"]:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "ok": False,
                        "error": {
                            "code": "OVERPAYMENT",
                            "message": f"付款金额超出应收金额。应收：{r['amount_fen']}分，已付：{r['paid_fen']}分，本次：{body.paid_fen}分",
                        },
                    },
                )

            updated["paid_fen"] = new_paid
            if new_paid >= r["amount_fen"]:
                updated["status"] = "paid"
            elif new_paid > 0:
                updated["status"] = "partial"

            if body.receipt_no:
                updated["receipt_no"] = body.receipt_no
            if body.receipt_url:
                updated["receipt_url"] = body.receipt_url
            if body.notes:
                updated["notes"] = body.notes
            updated["updated_at"] = datetime.now().isoformat()

            MOCK_FEE_RECORDS[i] = updated

            logger.info(
                "franchise_fee_paid",
                tenant_id=x_tenant_id,
                fee_id=fee_id,
                paid_fen=body.paid_fen,
                new_total_paid_fen=new_paid,
                new_status=updated["status"],
            )
            return {"ok": True, "data": updated}

    raise HTTPException(
        status_code=404,
        detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "收费记录不存在"}},
    )
