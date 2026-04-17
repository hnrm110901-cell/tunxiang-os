"""
二维码服务 — D11 培训证书 Nice-to-Have

生成指向公开验证页 `/public/cert/verify/{cert_no}` 的二维码 PNG。
使用 `qrcode` + Pillow，失败时捕获返回空 bytes 不影响主流程。
"""

from __future__ import annotations

import io
import os
from typing import Optional

import structlog

logger = structlog.get_logger()


def _verify_url(cert_no: str, domain: Optional[str] = None) -> str:
    """构造证书验证 URL。domain 未传则从环境变量取，兜底 localhost。"""
    base = domain or os.getenv("PUBLIC_DOMAIN") or "http://localhost:8000"
    base = base.rstrip("/")
    return f"{base}/public/cert/verify/{cert_no}"


def generate_cert_qr(cert_no: str, size: int = 200, domain: Optional[str] = None) -> bytes:
    """生成证书验证二维码 PNG bytes。

    Args:
        cert_no: 证书编号
        size: 二维码边长（像素），默认 200
        domain: 公开域名（可选，默认读 env PUBLIC_DOMAIN）

    Returns:
        PNG 字节；失败返回空 bytes（不抛）。
    """
    try:
        import qrcode  # type: ignore

        url = _verify_url(cert_no, domain)
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        # 缩放到指定大小
        img = img.resize((size, size))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:  # pragma: no cover
        logger.warning("qrcode.generate.failed", cert_no=cert_no, error=str(e))
        return b""
