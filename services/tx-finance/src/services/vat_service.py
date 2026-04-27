"""企业增值税服务 — 月度申报 + 进项发票抵扣（v102）

核心逻辑：
  1. create_declaration：从当期订单收入自动计算销项税，创建申报草稿
  2. add_input_invoice：录入进项发票，更新 input_tax_fen 和 payable_tax_fen
  3. verify_input_invoice：税务专员确认/驳回进项发票
  4. submit_declaration：提交申报（draft/reviewing → filed）
  5. mark_paid：记录实际缴税（filed → paid）
  6. get_declaration_detail：申报详情含全部进项发票
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 餐饮服务适用税率（一般纳税人 6%；小规模 3%）
DEFAULT_VAT_RATE = 0.06

VALID_STATUSES = ("draft", "reviewing", "filed", "paid")
VALID_INVOICE_TYPES = ("vat_special", "vat_ordinary", "electronic_vat_special")


class VATService:
    """增值税申报数据访问层 + 业务逻辑"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ══════════════════════════════════════════════════════
    # 申报单
    # ══════════════════════════════════════════════════════

    async def create_declaration(
        self,
        store_id: str,
        period: str,
        period_type: str = "monthly",
        tax_rate: float = DEFAULT_VAT_RATE,
        created_by: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建增值税申报单。

        销项税额从当期 orders 自动汇总：
          gross_revenue = SUM(orders.total_amount_fen) WHERE store_id + period
          output_tax = floor(gross_revenue * tax_rate / (1 + tax_rate))  ← 价税合并拆分
        """
        await self._set_tenant()
        sid = uuid.UUID(store_id)

        # 从订单表计算当期收入（期间格式 YYYY-MM）
        gross_revenue_fen = await self._calc_period_revenue(sid, period)
        # 价税合并时反算销项税：output = revenue * rate / (1 + rate)
        output_tax_fen = int(gross_revenue_fen * tax_rate / (1 + tax_rate))

        cb = uuid.UUID(created_by) if created_by else None

        result = await self.db.execute(
            text("""
                INSERT INTO vat_declarations
                    (tenant_id, store_id, period, period_type,
                     tax_rate, gross_revenue_fen, output_tax_fen,
                     input_tax_fen, payable_tax_fen, paid_tax_fen,
                     status, note, created_by)
                VALUES
                    (:tid, :sid, :period, :ptype,
                     :rate, :gross, :output,
                     0, :output, 0,
                     'draft', :note, :cb)
                ON CONFLICT (tenant_id, store_id, period)
                DO UPDATE SET
                    tax_rate           = EXCLUDED.tax_rate,
                    gross_revenue_fen  = EXCLUDED.gross_revenue_fen,
                    output_tax_fen     = EXCLUDED.output_tax_fen,
                    payable_tax_fen    = vat_declarations.output_tax_fen - vat_declarations.input_tax_fen,
                    updated_at         = NOW()
                RETURNING id, store_id, period, period_type, tax_rate,
                          gross_revenue_fen, output_tax_fen, input_tax_fen,
                          payable_tax_fen, paid_tax_fen, status,
                          filed_at, paid_at, nuonuo_declaration_no,
                          note, created_at, updated_at
            """),
            {
                "tid": self._tid,
                "sid": sid,
                "period": period,
                "ptype": period_type,
                "rate": tax_rate,
                "gross": gross_revenue_fen,
                "output": output_tax_fen,
                "note": note,
                "cb": cb,
            },
        )
        row = result.fetchone()
        await self.db.flush()
        log.info(
            "vat_declaration_created",
            store_id=store_id,
            period=period,
            output_tax_fen=output_tax_fen,
            tenant_id=self.tenant_id,
        )
        return self._decl_row(row)

    async def get_declaration(self, declaration_id: str) -> Optional[Dict[str, Any]]:
        """查询申报单（不含进项发票列表）"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, store_id, period, period_type, tax_rate,
                       gross_revenue_fen, output_tax_fen, input_tax_fen,
                       payable_tax_fen, paid_tax_fen, status,
                       filed_at, paid_at, nuonuo_declaration_no,
                       note, created_at, updated_at
                FROM vat_declarations
                WHERE id = :id AND tenant_id = :tid
            """),
            {"id": uuid.UUID(declaration_id), "tid": self._tid},
        )
        row = result.fetchone()
        return self._decl_row(row) if row else None

    async def list_declarations(
        self,
        store_id: Optional[str] = None,
        period: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查询申报单列表"""
        await self._set_tenant()
        sql = """
            SELECT id, store_id, period, period_type, tax_rate,
                   gross_revenue_fen, output_tax_fen, input_tax_fen,
                   payable_tax_fen, paid_tax_fen, status,
                   filed_at, paid_at, nuonuo_declaration_no,
                   note, created_at, updated_at
            FROM vat_declarations
            WHERE tenant_id = :tid
        """
        params: Dict[str, Any] = {"tid": self._tid}
        if store_id:
            sql += " AND store_id = :sid"
            params["sid"] = uuid.UUID(store_id)
        if period:
            sql += " AND period = :period"
            params["period"] = period
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY period DESC, store_id"
        result = await self.db.execute(text(sql), params)
        return [self._decl_row(r) for r in result.fetchall()]

    async def submit_declaration(
        self,
        declaration_id: str,
        nuonuo_declaration_no: Optional[str] = None,
    ) -> Dict[str, Any]:
        """提交申报（draft/reviewing → filed）"""
        await self._set_tenant()
        decl = await self.get_declaration(declaration_id)
        if not decl:
            raise ValueError(f"申报单 {declaration_id} 不存在")
        if decl["status"] not in ("draft", "reviewing"):
            raise ValueError(f"只有 draft/reviewing 状态可提交，当前: {decl['status']}")

        now = datetime.now(timezone.utc)
        await self.db.execute(
            text("""
                UPDATE vat_declarations
                SET status = 'filed',
                    filed_at = :now,
                    nuonuo_declaration_no = COALESCE(:nuonuo, nuonuo_declaration_no),
                    updated_at = :now
                WHERE id = :id AND tenant_id = :tid
            """),
            {
                "now": now,
                "nuonuo": nuonuo_declaration_no,
                "id": uuid.UUID(declaration_id),
                "tid": self._tid,
            },
        )
        await self.db.flush()
        log.info(
            "vat_declaration_filed",
            declaration_id=declaration_id,
            nuonuo_no=nuonuo_declaration_no,
            tenant_id=self.tenant_id,
        )
        return await self.get_declaration(declaration_id)  # type: ignore[return-value]

    async def mark_paid(self, declaration_id: str, paid_tax_fen: int) -> Dict[str, Any]:
        """记录实际缴税金额（filed → paid）"""
        await self._set_tenant()
        decl = await self.get_declaration(declaration_id)
        if not decl:
            raise ValueError(f"申报单 {declaration_id} 不存在")
        if decl["status"] != "filed":
            raise ValueError(f"只有 filed 状态可标记已缴，当前: {decl['status']}")

        now = datetime.now(timezone.utc)
        await self.db.execute(
            text("""
                UPDATE vat_declarations
                SET status = 'paid', paid_at = :now,
                    paid_tax_fen = :paid, updated_at = :now
                WHERE id = :id AND tenant_id = :tid
            """),
            {"now": now, "paid": paid_tax_fen, "id": uuid.UUID(declaration_id), "tid": self._tid},
        )
        await self.db.flush()
        log.info("vat_declaration_paid", declaration_id=declaration_id, paid_fen=paid_tax_fen, tenant_id=self.tenant_id)
        return await self.get_declaration(declaration_id)  # type: ignore[return-value]

    # ══════════════════════════════════════════════════════
    # 进项发票
    # ══════════════════════════════════════════════════════

    async def add_input_invoice(
        self,
        declaration_id: str,
        invoice_no: str,
        invoice_date: str,
        supplier_name: str,
        amount_fen: int,
        tax_rate: float = DEFAULT_VAT_RATE,
        invoice_type: str = "vat_special",
        supplier_tax_no: Optional[str] = None,
    ) -> Dict[str, Any]:
        """录入进项发票，自动重算申报单 payable_tax_fen"""
        await self._set_tenant()
        decl = await self.get_declaration(declaration_id)
        if not decl:
            raise ValueError(f"申报单 {declaration_id} 不存在")
        if decl["status"] in ("filed", "paid"):
            raise ValueError(f"申报单已提交，无法再添加进项发票（状态: {decl['status']}）")
        if invoice_type not in VALID_INVOICE_TYPES:
            raise ValueError(f"invoice_type 必须是: {', '.join(VALID_INVOICE_TYPES)}")

        # 价税合并拆分：input_tax = amount * rate / (1 + rate)
        input_tax_fen = int(amount_fen * tax_rate / (1 + tax_rate))

        inv_id = uuid.uuid4()
        await self.db.execute(
            text("""
                INSERT INTO vat_input_invoices
                    (id, tenant_id, declaration_id, invoice_no, invoice_date,
                     supplier_name, supplier_tax_no, amount_fen, tax_rate,
                     input_tax_fen, invoice_type, status)
                VALUES
                    (:id, :tid, :did, :inv_no, :inv_date::date,
                     :sup_name, :sup_tax, :amount, :rate,
                     :input_tax, :inv_type, 'pending')
                ON CONFLICT (tenant_id, declaration_id, invoice_no)
                DO UPDATE SET
                    amount_fen    = EXCLUDED.amount_fen,
                    input_tax_fen = EXCLUDED.input_tax_fen,
                    invoice_date  = EXCLUDED.invoice_date
            """),
            {
                "id": inv_id,
                "tid": self._tid,
                "did": uuid.UUID(declaration_id),
                "inv_no": invoice_no,
                "inv_date": invoice_date,
                "sup_name": supplier_name,
                "sup_tax": supplier_tax_no,
                "amount": amount_fen,
                "rate": tax_rate,
                "input_tax": input_tax_fen,
                "inv_type": invoice_type,
            },
        )

        # 重算 input_tax_fen（只含 verified/pending 的发票）
        await self._recalc_declaration_tax(declaration_id)
        await self.db.flush()
        log.info(
            "vat_input_invoice_added",
            declaration_id=declaration_id,
            invoice_no=invoice_no,
            input_tax_fen=input_tax_fen,
            tenant_id=self.tenant_id,
        )

        return {
            "invoice_id": str(inv_id),
            "declaration_id": declaration_id,
            "invoice_no": invoice_no,
            "input_tax_fen": input_tax_fen,
            "input_tax_yuan": round(input_tax_fen / 100, 2),
        }

    async def verify_input_invoice(
        self,
        invoice_id: str,
        verified: bool,
        rejection_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """验证/驳回进项发票，重算申报单应纳税额"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, declaration_id, invoice_no, status
                FROM vat_input_invoices
                WHERE id = :id AND tenant_id = :tid
            """),
            {"id": uuid.UUID(invoice_id), "tid": self._tid},
        )
        row = result.fetchone()
        if not row:
            raise ValueError(f"进项发票 {invoice_id} 不存在")
        if row.status != "pending":
            raise ValueError(f"只有 pending 状态可验证，当前: {row.status}")

        now = datetime.now(timezone.utc)
        new_status = "verified" if verified else "rejected"
        await self.db.execute(
            text("""
                UPDATE vat_input_invoices
                SET status = :status,
                    verified_at = CASE WHEN :verified THEN :now ELSE NULL END,
                    rejection_reason = :reason
                WHERE id = :id AND tenant_id = :tid
            """),
            {
                "status": new_status,
                "verified": verified,
                "now": now,
                "reason": rejection_reason,
                "id": uuid.UUID(invoice_id),
                "tid": self._tid,
            },
        )
        # 驳回时从计算中排除该发票
        await self._recalc_declaration_tax(str(row.declaration_id))
        await self.db.flush()
        return {"invoice_id": invoice_id, "status": new_status}

    async def list_input_invoices(self, declaration_id: str) -> List[Dict[str, Any]]:
        """查询申报单的进项发票列表"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, invoice_no, invoice_date, supplier_name, supplier_tax_no,
                       amount_fen, tax_rate, input_tax_fen, invoice_type,
                       status, verified_at, rejection_reason, created_at
                FROM vat_input_invoices
                WHERE tenant_id = :tid AND declaration_id = :did
                ORDER BY invoice_date, invoice_no
            """),
            {"tid": self._tid, "did": uuid.UUID(declaration_id)},
        )
        return [self._invoice_row(r) for r in result.fetchall()]

    async def get_declaration_detail(self, declaration_id: str) -> Optional[Dict[str, Any]]:
        """申报单详情 + 进项发票列表"""
        decl = await self.get_declaration(declaration_id)
        if not decl:
            return None
        invoices = await self.list_input_invoices(declaration_id)
        decl["input_invoices"] = invoices
        decl["input_invoice_count"] = len(invoices)
        return decl

    # ══════════════════════════════════════════════════════
    # 内部工具
    # ══════════════════════════════════════════════════════

    async def _calc_period_revenue(self, store_id: uuid.UUID, period: str) -> int:
        """从 orders 表汇总当期收入（只计 paid 状态订单）"""
        # period 格式 YYYY-MM → 月份范围
        try:
            year, month = int(period[:4]), int(period[5:7])
        except (ValueError, IndexError):
            return 0

        result = await self.db.execute(
            text("""
                SELECT COALESCE(SUM(total_amount_fen), 0) AS revenue
                FROM orders
                WHERE tenant_id = :tid AND store_id = :sid
                  AND status = 'paid'
                  AND DATE_TRUNC('month', created_at) = DATE_TRUNC('month', :period_date::date)
            """),
            {
                "tid": self._tid,
                "sid": store_id,
                "period_date": f"{year}-{month:02d}-01",
            },
        )
        row = result.fetchone()
        return int(row.revenue) if row else 0

    async def _recalc_declaration_tax(self, declaration_id: str) -> None:
        """重算申报单 input_tax_fen 和 payable_tax_fen（排除 rejected 发票）"""
        result = await self.db.execute(
            text("""
                SELECT COALESCE(SUM(input_tax_fen), 0) AS total_input
                FROM vat_input_invoices
                WHERE tenant_id = :tid AND declaration_id = :did
                  AND status != 'rejected'
            """),
            {"tid": self._tid, "did": uuid.UUID(declaration_id)},
        )
        row = result.fetchone()
        total_input = int(row.total_input) if row else 0

        await self.db.execute(
            text("""
                UPDATE vat_declarations
                SET input_tax_fen = :input,
                    payable_tax_fen = GREATEST(0, output_tax_fen - :input),
                    updated_at = NOW()
                WHERE id = :id AND tenant_id = :tid
            """),
            {"input": total_input, "id": uuid.UUID(declaration_id), "tid": self._tid},
        )

    def _decl_row(self, row) -> Dict[str, Any]:
        return {
            "declaration_id": str(row.id),
            "tenant_id": self.tenant_id,
            "store_id": str(row.store_id),
            "period": row.period,
            "period_type": row.period_type,
            "tax_rate": float(row.tax_rate),
            "gross_revenue_fen": row.gross_revenue_fen,
            "gross_revenue_yuan": round(row.gross_revenue_fen / 100, 2),
            "output_tax_fen": row.output_tax_fen,
            "output_tax_yuan": round(row.output_tax_fen / 100, 2),
            "input_tax_fen": row.input_tax_fen,
            "input_tax_yuan": round(row.input_tax_fen / 100, 2),
            "payable_tax_fen": row.payable_tax_fen,
            "payable_tax_yuan": round(row.payable_tax_fen / 100, 2),
            "paid_tax_fen": row.paid_tax_fen,
            "paid_tax_yuan": round(row.paid_tax_fen / 100, 2),
            "status": row.status,
            "filed_at": row.filed_at.isoformat() if row.filed_at else None,
            "paid_at": row.paid_at.isoformat() if row.paid_at else None,
            "nuonuo_declaration_no": row.nuonuo_declaration_no,
            "note": getattr(row, "note", None),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _invoice_row(self, row) -> Dict[str, Any]:
        return {
            "invoice_id": str(row.id),
            "invoice_no": row.invoice_no,
            "invoice_date": str(row.invoice_date) if row.invoice_date else None,
            "supplier_name": row.supplier_name,
            "supplier_tax_no": row.supplier_tax_no,
            "amount_fen": row.amount_fen,
            "amount_yuan": round(row.amount_fen / 100, 2),
            "tax_rate": float(row.tax_rate),
            "input_tax_fen": row.input_tax_fen,
            "input_tax_yuan": round(row.input_tax_fen / 100, 2),
            "invoice_type": row.invoice_type,
            "status": row.status,
            "verified_at": row.verified_at.isoformat() if row.verified_at else None,
            "rejection_reason": row.rejection_reason,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
