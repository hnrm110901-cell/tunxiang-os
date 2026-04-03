"""桌边结账路由 — 服务员端 PWA 快速结账

POST /api/v1/orders/{order_id}/settle
  body: {method, member_id?, remark?}
  验证 method in [wechat, alipay, cash, credit, tab]
  更新 orders.status='paid', paid_at, payment_method (via payments 表)
  如果 method=='tab': 写入 tab_records 表（如不存在就跳过）
  返回 {"ok": true, "data": {"order_id": ..., "paid_at": ...}}
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1", tags=["table-side-pay"])

VALID_METHODS = {"wechat", "alipay", "cash", "credit", "tab"}

# method → payment category label（写入 payments.payment_category）
METHOD_CATEGORY: dict[str, str] = {
    "wechat": "移动支付",
    "alipay": "移动支付",
    "cash": "现金",
    "credit": "银联卡",
    "tab": "挂账",
}


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict) -> dict:
    return {"ok": True, "data": data, "error": None}


class SettleReq(BaseModel):
    method: str
    member_id: Optional[str] = None
    remark: Optional[str] = None

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        if v not in VALID_METHODS:
            raise ValueError(f"method must be one of {sorted(VALID_METHODS)}")
        return v


@router.post("/orders/{order_id}/settle")
async def settle_order(
    order_id: str,
    req: SettleReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """桌边快速结账 — 更新订单状态并记录支付方式"""
    tenant_id = _get_tenant_id(request)
    now = datetime.now(timezone.utc)

    # 1. 查询并锁定订单
    row = await db.execute(
        text(
            "SELECT id, status, final_amount_fen, total_amount_fen "
            "FROM orders "
            "WHERE id = :oid AND tenant_id = :tid "
            "FOR UPDATE"
        ),
        {"oid": order_id, "tid": tenant_id},
    )
    order = row.mappings().first()

    if not order:
        raise HTTPException(status_code=404, detail={"ok": False, "error": {"message": "订单不存在"}})

    if order["status"] == "paid":
        raise HTTPException(status_code=409, detail={"ok": False, "error": {"message": "订单已结账"}})

    amount_fen = order["final_amount_fen"] or order["total_amount_fen"] or 0

    # 2. 更新订单状态
    await db.execute(
        text(
            "UPDATE orders "
            "SET status = 'paid', "
            "    completed_at = :now, "
            "    updated_at = :now "
            "WHERE id = :oid AND tenant_id = :tid"
        ),
        {"now": now, "oid": order_id, "tid": tenant_id},
    )

    # 3. 写入 payments 记录
    payment_no = f"TSP-{uuid.uuid4().hex[:16].upper()}"
    payment_id = str(uuid.uuid4())
    credit_account_name: Optional[str] = None
    if req.method == "tab":
        credit_account_name = req.remark or "未填写"

    await db.execute(
        text(
            "INSERT INTO payments "
            "(id, tenant_id, order_id, payment_no, method, amount_fen, status, "
            " is_actual_revenue, actual_revenue_ratio, payment_category, "
            " credit_account_name, notes, paid_at, created_at, updated_at, is_deleted) "
            "VALUES "
            "(:id, :tid, :oid, :pno, :method, :amount, 'paid', "
            " true, 1.0, :category, "
            " :credit_name, :notes, :paid_at, :now, :now, false)"
        ),
        {
            "id": payment_id,
            "tid": tenant_id,
            "oid": order_id,
            "pno": payment_no,
            "method": req.method,
            "amount": amount_fen,
            "category": METHOD_CATEGORY.get(req.method, "其他"),
            "credit_name": credit_account_name,
            "notes": req.remark if req.method != "tab" else None,
            "paid_at": now,
            "now": now,
        },
    )

    # 4. 挂账时尝试写入 tab_records（表不存在则跳过）
    if req.method == "tab":
        try:
            await db.execute(
                text(
                    "INSERT INTO tab_records "
                    "(id, tenant_id, order_id, payment_id, unit_name, amount_fen, "
                    " created_at, updated_at, is_deleted) "
                    "VALUES "
                    "(:id, :tid, :oid, :pid, :unit, :amount, :now, :now, false)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tid": tenant_id,
                    "oid": order_id,
                    "pid": payment_id,
                    "unit": credit_account_name,
                    "amount": amount_fen,
                    "now": now,
                },
            )
        except Exception:  # noqa: BLE001 — tab_records 表可能不存在，静默跳过
            pass

    await db.commit()

    return _ok(
        {
            "order_id": order_id,
            "paid_at": now.isoformat(),
            "payment_no": payment_no,
            "method": req.method,
            "amount_fen": amount_fen,
        }
    )
