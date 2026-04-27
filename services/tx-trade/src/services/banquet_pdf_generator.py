"""宴会合同 PDF 生成器 — placeholder 版（Track R2-C / Sprint R2）

本模块当前仅返回 fake S3 URL + 字符串摘要模板，不引入 reportlab / weasyprint
等重依赖。真实 PDF 渲染与电子签（e 签宝 / 法大大 / 腾讯电子签）在 R3 打通。

电子签接入点（R3 预留）：
    ─── generate_contract_pdf ───
      当前返回：("https://fake-s3.banquet-contracts/{tenant}/{contract_id}.pdf",
                 "合同文本摘要...")
      R3 切换：调用选型方（法大大）的合同草稿 API → 获取真实 pdf_url +
               signature_request_id

    ─── signature_provider ───
      当前：banquet_contract_service.mark_signed 入参 signature_provider='placeholder'
      R3：签约方 webhook 回传 signature_provider='fadada'|'esign'|'tencent'
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from shared.ontology.src.extensions.banquet_leads import BanquetType

# PDF 模板 — 用纯字符串拼接，不渲染真实 PDF
_CONTRACT_TEXT_TEMPLATE = """
宴会服务合同草稿（Placeholder，R3 接入电子签后替换为真 PDF）

合同编号: {contract_id}
租户ID: {tenant_id}
宴会类型: {banquet_type_label}
桌数: {tables}
合同总金额: ¥{total_yuan:.2f}
订金: ¥{deposit_yuan:.2f} ({deposit_ratio_pct:.0f}%)
预定日期: {scheduled_date}
销售经理ID: {sales_employee_id}
客户ID: {customer_id}
关联商机ID: {lead_id}

生成时间: {generated_at}

【服务内容】
    厨房: 按套餐执行（明细见 EO 工单）
    前厅: 签到/接待/摆台
    采购: 食材到位（批次信息见 EO 工单）
    财务: 订金收取 + 尾款结算
    营销: 邀请函 + 物料

【结算条款】
    订金 {deposit_yuan:.2f} 元于签约后 3 日内支付
    尾款 {remainder_yuan:.2f} 元于宴会当日结算

【甲乙双方确认】
    甲方（客户）: ____________
    乙方（门店）: ____________
"""


_BANQUET_TYPE_LABELS: dict[str, str] = {
    "wedding": "婚宴",
    "birthday": "生日宴",
    "corporate": "商务宴请",
    "baby_banquet": "满月/百日宴",
    "reunion": "家庭聚餐",
    "graduation": "升学/谢师宴",
}


def generate_contract_pdf(
    *,
    contract_id: uuid.UUID,
    tenant_id: uuid.UUID,
    lead_id: uuid.UUID,
    customer_id: uuid.UUID,
    sales_employee_id: uuid.UUID | None,
    banquet_type: BanquetType,
    tables: int,
    total_amount_fen: int,
    deposit_fen: int,
    scheduled_date: Any | None,
    template_id: str | None = None,
) -> tuple[str, str, int]:
    """生成合同 PDF 的 placeholder。

    Returns:
        (pdf_url, content_text, generation_ms)
        pdf_url:        fake S3 URL（R3 切换为法大大/e 签宝/腾讯电子签真 URL）
        content_text:   合同草稿文本（用于 metadata 留痕 + 人工对照）
        generation_ms:  生成耗时（毫秒）
    """
    start = time.perf_counter()

    # placeholder：URL 仅用 contract_id 构造，stable 且无副作用
    pdf_url = (
        f"https://fake-s3.banquet-contracts.tunxiang.local/"
        f"{tenant_id}/{contract_id}.pdf"
    )

    deposit_ratio = (
        Decimal(deposit_fen) / Decimal(total_amount_fen)
        if total_amount_fen > 0
        else Decimal(0)
    )
    text = _CONTRACT_TEXT_TEMPLATE.format(
        contract_id=contract_id,
        tenant_id=tenant_id,
        banquet_type_label=_BANQUET_TYPE_LABELS.get(
            banquet_type.value, banquet_type.value
        ),
        tables=tables,
        total_yuan=total_amount_fen / 100,
        deposit_yuan=deposit_fen / 100,
        deposit_ratio_pct=float(deposit_ratio * 100),
        remainder_yuan=(total_amount_fen - deposit_fen) / 100,
        scheduled_date=scheduled_date.isoformat() if scheduled_date else "待定",
        sales_employee_id=sales_employee_id or "未指派",
        customer_id=customer_id,
        lead_id=lead_id,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    generation_ms = int((time.perf_counter() - start) * 1000)
    return pdf_url, text, generation_ms


__all__ = ["generate_contract_pdf"]
