"""
证书 PDF 生成服务 — D11 培训证书 Nice-to-Have

- A4 横版，顶部品牌色 #FF6B2C 横条
- 居中"培训合格证书"大字
- 员工姓名 / 课程名 / 证书编号 / 颁发日期 / 到期日期
- 右下角二维码（指向 /public/cert/verify/{cert_no}）
- 公司签章区域占位
- 失败不抛：捕获异常仅记日志，调用方容错
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

from .qrcode_service import generate_cert_qr

logger = structlog.get_logger()

# 品牌色
BRAND_COLOR_HEX = "#FF6B2C"

# 证书输出目录
CERT_DIR = "/tmp/certificates"


def _register_cjk_font() -> str:
    """注册中文字体，优先系统 STHeiti，找不到 fallback 默认。

    Returns 注册后的字体名；fallback 时返回 'Helvetica'。
    """
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        # macOS 系统字体候选
        font_candidates = [
            ("STHeiti", "/System/Library/Fonts/STHeiti Medium.ttc"),
            ("STHeitiSC", "/System/Library/Fonts/STHeiti Light.ttc"),
            ("PingFang", "/System/Library/Fonts/PingFang.ttc"),
            # Linux 容器常见中文字体
            ("NotoSansCJK", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            ("WenQuanYi", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        ]
        for name, path in font_candidates:
            if os.path.exists(path):
                try:
                    pdfmetrics.registerFont(TTFont(name, path))
                    return name
                except Exception:
                    continue
    except Exception as e:  # pragma: no cover
        logger.warning("pdf.font.register.failed", error=str(e))
    return "Helvetica"


def _hex_to_rgb(hex_str: str):
    hex_str = hex_str.lstrip("#")
    return tuple(int(hex_str[i : i + 2], 16) / 255 for i in (0, 2, 4))


async def generate_certificate_pdf(
    session: AsyncSession,
    certificate_id: str,
    write_pdf_url: bool = True,
) -> bytes:
    """生成证书 PDF。

    Args:
        session: 异步数据库会话
        certificate_id: ExamCertificate.id (UUID str)
        write_pdf_url: 是否回写 ExamCertificate.pdf_url

    Returns:
        PDF bytes；失败返回空 bytes（不抛）。
    """
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfgen import canvas

        from ..models.employee import Employee
        from ..models.training import ExamCertificate, TrainingCourse

        # 读取证书 + 课程 + 员工
        cert_res = await session.execute(
            select(ExamCertificate).where(ExamCertificate.id == uuid.UUID(certificate_id))
        )
        cert = cert_res.scalar_one_or_none()
        if not cert:
            logger.warning("cert.pdf.not_found", cert_id=certificate_id)
            return b""

        course_res = await session.execute(
            select(TrainingCourse).where(TrainingCourse.id == cert.course_id)
        )
        course = course_res.scalar_one_or_none()
        course_title = course.title if course else "培训课程"

        emp_res = await session.execute(
            select(Employee).where(Employee.id == cert.employee_id)
        )
        emp = emp_res.scalar_one_or_none()
        emp_name = getattr(emp, "name", None) or cert.employee_id

        # 准备 PDF
        os.makedirs(CERT_DIR, exist_ok=True)
        buf = io.BytesIO()
        page_size = landscape(A4)
        c = canvas.Canvas(buf, pagesize=page_size)
        width, height = page_size

        font_name = _register_cjk_font()

        # 1. 顶部品牌色横条（高 60pt）
        r, g, b = _hex_to_rgb(BRAND_COLOR_HEX)
        c.setFillColorRGB(r, g, b)
        c.rect(0, height - 60, width, 60, fill=1, stroke=0)

        # 品牌名
        c.setFillColorRGB(1, 1, 1)
        c.setFont(font_name, 18)
        c.drawString(40, height - 40, "屯象OS · 智链培训")

        # 2. 居中大标题
        c.setFillColorRGB(r, g, b)
        c.setFont(font_name, 44)
        title = "培训合格证书"
        tw = c.stringWidth(title, font_name, 44)
        c.drawString((width - tw) / 2, height - 160, title)

        # 分隔线
        c.setStrokeColorRGB(r, g, b)
        c.setLineWidth(2)
        c.line(width / 2 - 120, height - 175, width / 2 + 120, height - 175)

        # 3. 正文信息
        c.setFillColorRGB(0.15, 0.15, 0.15)
        c.setFont(font_name, 16)

        y = height - 230
        line_gap = 36

        intro = f"兹证明  {emp_name}  同志"
        iw = c.stringWidth(intro, font_name, 16)
        c.drawString((width - iw) / 2, y, intro)

        y -= line_gap
        intro2 = f"参加并通过《{course_title}》考试，准予颁发合格证书。"
        iw2 = c.stringWidth(intro2, font_name, 16)
        c.drawString((width - iw2) / 2, y, intro2)

        # 4. 左下角元数据
        c.setFont(font_name, 12)
        meta_x = 60
        meta_y = 140
        c.drawString(meta_x, meta_y, f"证书编号：{cert.cert_no}")
        issued = cert.issued_at.strftime("%Y-%m-%d") if cert.issued_at else "-"
        expire = cert.expire_at.strftime("%Y-%m-%d") if cert.expire_at else "长期有效"
        c.drawString(meta_x, meta_y - 22, f"颁发日期：{issued}")
        c.drawString(meta_x, meta_y - 44, f"到期日期：{expire}")

        # 5. 公司签章区域占位（右下角偏左）
        c.setStrokeColorRGB(0.7, 0.7, 0.7)
        c.setDash(3, 3)
        c.circle(width - 280, 130, 45, stroke=1, fill=0)
        c.setDash()
        c.setFont(font_name, 10)
        c.setFillColorRGB(0.6, 0.6, 0.6)
        c.drawString(width - 305, 75, "（公司签章处）")

        # 6. 右下角二维码
        qr_png = generate_cert_qr(cert.cert_no, size=200)
        if qr_png:
            from reportlab.lib.utils import ImageReader

            qr_img = ImageReader(io.BytesIO(qr_png))
            qr_size = 110
            c.drawImage(
                qr_img,
                width - qr_size - 50,
                60 + qr_size,  # 底部再留 60
                width=qr_size,
                height=qr_size,
                preserveAspectRatio=True,
                mask="auto",
            )
            c.setFillColorRGB(0.4, 0.4, 0.4)
            c.setFont(font_name, 9)
            scan_hint = "扫码验证证书真伪"
            hw = c.stringWidth(scan_hint, font_name, 9)
            c.drawString(width - qr_size - 50 + (qr_size - hw) / 2, 55, scan_hint)

        c.showPage()
        c.save()
        pdf_bytes = buf.getvalue()

        # 写文件
        file_path = os.path.join(CERT_DIR, f"{cert.cert_no}.pdf")
        try:
            with open(file_path, "wb") as f:
                f.write(pdf_bytes)
        except Exception as e:  # pragma: no cover
            logger.warning("cert.pdf.write_file.failed", path=file_path, error=str(e))

        # 回写 pdf_url
        if write_pdf_url:
            try:
                cert.pdf_url = f"/api/v1/hr/training/exam/certificates/{cert.id}/pdf"
                await session.flush()
            except Exception as e:  # pragma: no cover
                logger.warning("cert.pdf.update_url.failed", cert_id=str(cert.id), error=str(e))

        logger.info("cert.pdf.generated", cert_no=cert.cert_no, size=len(pdf_bytes))
        return pdf_bytes

    except Exception as e:
        logger.exception("cert.pdf.generate.failed", cert_id=certificate_id, error=str(e))
        return b""


def load_certificate_pdf_from_disk(cert_no: str) -> Optional[bytes]:
    """从磁盘读取已生成的证书 PDF（用于 API 下载）。"""
    try:
        path = os.path.join(CERT_DIR, f"{cert_no}.pdf")
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read()
    except Exception as e:  # pragma: no cover
        logger.warning("cert.pdf.load.failed", cert_no=cert_no, error=str(e))
        return None


def mask_holder_name(name: str) -> str:
    """持证人姓名脱敏：张三 → 张*；张小三 → 张*三；英文首尾保留。"""
    if not name:
        return "*"
    n = name.strip()
    if len(n) <= 1:
        return n
    if len(n) == 2:
        return n[0] + "*"
    # 3 位及以上：首 + 中间*号（单个）+ 尾
    return n[0] + "*" + n[-1]
