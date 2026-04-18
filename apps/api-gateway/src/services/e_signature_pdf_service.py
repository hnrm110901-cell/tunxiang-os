"""
电子签约 PDF 生成服务

复用 certificate_pdf_service 的 reportlab + CJK 字体模式。
基于已签信封生成终稿 PDF，含：
  - 合同正文（template.content_text 或 placeholder 填充）
  - 每个签署人签名图 + 时间戳 + IP
  - 印章占位
  - 右下二维码（审计链 URL，留占位）

失败仅记日志，调用方容错。
"""

from __future__ import annotations

import io
import os
import uuid
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.e_signature import (
    SignatureEnvelope,
    SignatureRecord,
    SignatureTemplate,
    SignRecordStatus,
)

logger = structlog.get_logger()

PDF_DIR = "/tmp/e_signatures"
BRAND_COLOR_HEX = "#FF6B2C"


def _register_cjk_font() -> str:
    """注册中文字体，找不到 fallback Helvetica。"""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        candidates = [
            ("STHeiti", "/System/Library/Fonts/STHeiti Medium.ttc"),
            ("PingFang", "/System/Library/Fonts/PingFang.ttc"),
            ("NotoSansCJK", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            ("WenQuanYi", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        ]
        for name, path in candidates:
            if os.path.exists(path):
                try:
                    pdfmetrics.registerFont(TTFont(name, path))
                    return name
                except Exception:
                    continue
    except Exception as exc:  # pragma: no cover
        logger.debug("pdf_font.register_failed", error=str(exc))
    return "Helvetica"


class ESignaturePdfService:
    """签署完成 PDF 渲染"""

    @staticmethod
    async def render_signed_pdf(
        session: AsyncSession,
        envelope_id: uuid.UUID,
    ) -> Optional[str]:
        """生成终稿 PDF，返回本地路径（占位，生产 OSS）"""
        try:
            env_res = await session.execute(
                select(SignatureEnvelope).where(SignatureEnvelope.id == envelope_id)
            )
            env = env_res.scalar_one_or_none()
            if not env:
                return None

            tpl = None
            if env.template_id:
                tpl_res = await session.execute(
                    select(SignatureTemplate).where(SignatureTemplate.id == env.template_id)
                )
                tpl = tpl_res.scalar_one_or_none()

            rec_res = await session.execute(
                select(SignatureRecord).where(SignatureRecord.envelope_id == envelope_id)
                .order_by(SignatureRecord.sign_order.asc())
            )
            records = list(rec_res.scalars().all())

            os.makedirs(PDF_DIR, exist_ok=True)
            out_path = os.path.join(PDF_DIR, f"{env.envelope_no}.pdf")

            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import mm
            from reportlab.pdfgen import canvas as pdf_canvas

            font = _register_cjk_font()
            c = pdf_canvas.Canvas(out_path, pagesize=A4)
            width, height = A4

            # 顶部品牌色条
            c.setFillColorRGB(1.0, 0.42, 0.17)
            c.rect(0, height - 15 * mm, width, 15 * mm, fill=1, stroke=0)
            c.setFillColorRGB(1, 1, 1)
            c.setFont(font, 16)
            c.drawString(15 * mm, height - 10 * mm, "屯象OS 电子签约")

            # 标题
            c.setFillColorRGB(0, 0, 0)
            c.setFont(font, 18)
            subject = env.subject or (tpl.name if tpl else "合同")
            c.drawCentredString(width / 2, height - 30 * mm, subject)

            # 信封信息
            c.setFont(font, 10)
            y = height - 45 * mm
            c.drawString(15 * mm, y, f"信封编号: {env.envelope_no}")
            y -= 6 * mm
            c.drawString(15 * mm, y, f"完成时间: {env.completed_at.strftime('%Y-%m-%d %H:%M:%S') if env.completed_at else '-'}")
            y -= 10 * mm

            # 合同正文
            content = (tpl.content_text if tpl and tpl.content_text else "（合同正文占位，由模板 content_text 或 content_template_url 渲染）")
            # 简化：按换行逐行输出
            c.setFont(font, 10)
            for line in (content or "").split("\n"):
                if y < 60 * mm:
                    c.showPage()
                    y = height - 20 * mm
                    c.setFont(font, 10)
                c.drawString(15 * mm, y, line[:90])
                y -= 5 * mm

            # 签署人区
            if y < 80 * mm:
                c.showPage()
                y = height - 20 * mm
            y -= 10 * mm
            c.setFont(font, 12)
            c.drawString(15 * mm, y, "签署人：")
            y -= 8 * mm
            c.setFont(font, 9)
            for r in records:
                if y < 30 * mm:
                    c.showPage()
                    y = height - 20 * mm
                status_zh = {"signed": "已签署", "rejected": "已拒签", "pending": "待签署"}.get(r.status.value, r.status.value)
                line = (
                    f"  · {r.signer_name or r.signer_id}  角色: {r.signer_role.value}  "
                    f"状态: {status_zh}  时间: {r.signed_at.strftime('%Y-%m-%d %H:%M') if r.signed_at else '-'}  "
                    f"IP: {r.ip_address or '-'}"
                )
                c.drawString(15 * mm, y, line)
                y -= 5 * mm

            # 页脚
            c.setFont(font, 8)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString(15 * mm, 10 * mm, f"Generated by ZhiLianOS E-Signature @ {datetime.utcnow().isoformat()}Z")

            c.showPage()
            c.save()

            logger.info("e_signature.pdf_rendered", envelope_id=str(envelope_id), path=out_path)
            return out_path
        except Exception as exc:
            logger.error("e_signature.pdf_render_error", envelope_id=str(envelope_id), error=str(exc))
            return None
