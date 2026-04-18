"""
租户计费服务 — 月度账单聚合 + 用量记录 + 发票联动

闭环：
  active installations → 计算本期应收（分） → 写入 app_billing_records
                       → 触发 ar_ap_service.create_ar 产生应收
                       → 触发 einvoice_service 开电子发票（可选）
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from io import BytesIO
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.app_marketplace import (
    AppBillingRecord,
    Application,
    AppInstallation,
    AppPricingTier,
)

logger = structlog.get_logger()


class BillingService:
    """租户月度计费服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ───────────────────── 内部辅助 ─────────────────────
    async def _get_tier(
        self, app_id: uuid.UUID, tier_name: Optional[str],
    ) -> Optional[AppPricingTier]:
        if not tier_name:
            return None
        r = await self.db.execute(
            select(AppPricingTier).where(
                AppPricingTier.app_id == app_id,
                AppPricingTier.tier_name == tier_name,
            )
        )
        return r.scalars().first()

    def _compute_line_fen(
        self,
        app: Application,
        tier: Optional[AppPricingTier],
        usage: Optional[Dict[str, Any]],
    ) -> int:
        """根据 price_model 计算单条账单金额（分）"""
        model = app.price_model
        if model == "free":
            return 0
        if model == "monthly":
            if tier:
                return int(tier.monthly_fee_fen or 0)
            return int(app.price_fen or 0)
        if model == "one_time":
            return int(app.price_fen or 0)
        if model == "usage_based":
            # 简化计费：api_calls 单价 1 分 / 次，超过 tier 限额部分
            limits = (tier.usage_limits_json or {}) if tier else {}
            base_fen = int(tier.monthly_fee_fen or 0) if tier else int(app.price_fen or 0)
            calls = int((usage or {}).get("api_calls", 0))
            quota = int(limits.get("api_calls", 0))
            overage = max(calls - quota, 0)
            return base_fen + overage * 1  # 1 分/次
        return 0

    # ───────────────────── 核心方法 ─────────────────────
    async def compute_monthly_invoice(
        self, tenant_id: str, period: str,
    ) -> Dict[str, Any]:
        """
        扫该租户所有 active 安装，产生/刷新本期计费记录。

        - 试用期内：line 金额记为 0
        - 一次调用幂等：同 (installation_id, period) 存在时原地更新金额
        """
        res = await self.db.execute(
            select(AppInstallation, Application).join(
                Application, Application.id == AppInstallation.app_id,
            ).where(
                AppInstallation.tenant_id == tenant_id,
                AppInstallation.status == "active",
            )
        )
        total_fen = 0
        line_items: List[Dict[str, Any]] = []
        for inst, app in res.all():
            tier = await self._get_tier(app.id, inst.tier_name)

            # 查是否已有本期记录
            existing = await self.db.execute(
                select(AppBillingRecord).where(
                    AppBillingRecord.installation_id == inst.id,
                    AppBillingRecord.billing_period == period,
                )
            )
            rec = existing.scalars().first()

            usage = (rec.usage_data_json if rec else None) or {}
            # 试用期内金额为 0
            if inst.trial_ends_at and inst.trial_ends_at > datetime.utcnow():
                amount_fen = 0
            else:
                amount_fen = self._compute_line_fen(app, tier, usage)

            if rec:
                rec.amount_fen = amount_fen
            else:
                rec = AppBillingRecord(
                    id=uuid.uuid4(),
                    installation_id=inst.id,
                    billing_period=period,
                    amount_fen=amount_fen,
                    usage_data_json=usage,
                )
                self.db.add(rec)

            total_fen += amount_fen
            line_items.append({
                "installation_id": str(inst.id),
                "app_code": app.code,
                "app_name": app.name,
                "tier": inst.tier_name,
                "price_model": app.price_model,
                "amount_fen": amount_fen,
                "amount_yuan": round(amount_fen / 100, 2),
            })

        await self.db.flush()

        invoice_no = f"INV-{tenant_id}-{period}"
        logger.info("monthly_invoice_computed",
                    tenant=tenant_id, period=period,
                    total_fen=total_fen, lines=len(line_items))

        return {
            "invoice_id": invoice_no,
            "tenant_id": tenant_id,
            "billing_period": period,
            "total_fen": total_fen,
            "total_yuan": round(total_fen / 100, 2),
            "line_items": line_items,
        }

    async def apply_usage_data(
        self,
        installation_id: str,
        period: str,
        usage_json: Dict[str, Any],
    ) -> Dict[str, Any]:
        """记录/累加用量（api_calls/storage_gb），覆盖式写入"""
        existing = await self.db.execute(
            select(AppBillingRecord).where(
                AppBillingRecord.installation_id == uuid.UUID(installation_id),
                AppBillingRecord.billing_period == period,
            )
        )
        rec = existing.scalars().first()
        if not rec:
            rec = AppBillingRecord(
                id=uuid.uuid4(),
                installation_id=uuid.UUID(installation_id),
                billing_period=period,
                amount_fen=0,
                usage_data_json=usage_json,
            )
            self.db.add(rec)
        else:
            merged = dict(rec.usage_data_json or {})
            for k, v in (usage_json or {}).items():
                merged[k] = (merged.get(k, 0) or 0) + v if isinstance(v, (int, float)) else v
            rec.usage_data_json = merged
        await self.db.flush()
        return {"installation_id": installation_id, "usage": rec.usage_data_json}

    async def check_usage_exceeded(self, installation_id: str) -> Dict[str, Any]:
        """检查用量是否超限（usage_based）"""
        inst = await self.db.get(AppInstallation, uuid.UUID(installation_id))
        if not inst:
            raise ValueError("installation not found")
        app = await self.db.get(Application, inst.app_id)
        tier = await self._get_tier(inst.app_id, inst.tier_name)
        limits = (tier.usage_limits_json or {}) if tier else {}

        period = datetime.utcnow().strftime("%Y-%m")
        r = await self.db.execute(
            select(AppBillingRecord).where(
                AppBillingRecord.installation_id == inst.id,
                AppBillingRecord.billing_period == period,
            )
        )
        rec = r.scalars().first()
        usage = (rec.usage_data_json if rec else {}) or {}

        exceeded: Dict[str, Dict[str, Any]] = {}
        for k, limit in limits.items():
            used = int(usage.get(k, 0) or 0)
            if used > int(limit or 0):
                exceeded[k] = {"used": used, "limit": int(limit)}

        return {
            "installation_id": installation_id,
            "app_code": app.code if app else None,
            "tier": inst.tier_name,
            "limits": limits,
            "current_usage": usage,
            "exceeded": exceeded,
            "is_exceeded": bool(exceeded),
        }

    async def generate_invoice_pdf(
        self,
        tenant_id: str,
        period: str,
    ) -> bytes:
        """
        生成发票 PDF（简易版，复用 reportlab）。
        无 reportlab 时回退到纯文本 bytes，保证 API 可用。
        """
        bill = await self.compute_monthly_invoice(tenant_id, period)
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas  # type: ignore

            buf = BytesIO()
            c = canvas.Canvas(buf, pagesize=A4)
            width, height = A4
            y = height - 50
            c.setFont("Helvetica-Bold", 16)
            c.drawString(50, y, f"Tunxiang OS Invoice — {period}")
            y -= 25
            c.setFont("Helvetica", 10)
            c.drawString(50, y, f"Tenant: {tenant_id}")
            y -= 15
            c.drawString(50, y, f"Invoice ID: {bill['invoice_id']}")
            y -= 25
            c.setFont("Helvetica-Bold", 11)
            c.drawString(50, y, "App")
            c.drawString(250, y, "Tier")
            c.drawString(330, y, "Model")
            c.drawString(430, y, "Amount (CNY)")
            y -= 15
            c.setFont("Helvetica", 10)
            for it in bill["line_items"]:
                c.drawString(50, y, (it["app_name"] or "")[:30])
                c.drawString(250, y, it["tier"] or "-")
                c.drawString(330, y, it["price_model"])
                c.drawString(430, y, f"{it['amount_yuan']:.2f}")
                y -= 13
                if y < 80:
                    c.showPage()
                    y = height - 50
            y -= 10
            c.setFont("Helvetica-Bold", 12)
            c.drawString(330, y, f"Total: ¥{bill['total_yuan']:.2f}")
            c.showPage()
            c.save()
            return buf.getvalue()
        except Exception:  # pragma: no cover — reportlab 未安装回退
            lines = [
                f"Tunxiang OS Invoice {bill['invoice_id']}",
                f"Tenant: {tenant_id} Period: {period}",
                "",
            ]
            for it in bill["line_items"]:
                lines.append(
                    f"{it['app_name']} [{it['tier']}] {it['price_model']}  ¥{it['amount_yuan']:.2f}"
                )
            lines.append("")
            lines.append(f"TOTAL ¥{bill['total_yuan']:.2f}")
            return "\n".join(lines).encode("utf-8")


def get_billing_service(db: AsyncSession) -> BillingService:
    return BillingService(db)
