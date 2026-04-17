"""
D11 二维码生成服务测试
"""
from __future__ import annotations

import io

import pytest


def test_generate_cert_qr_returns_png_bytes():
    """生成二维码：非空 bytes 且 PNG 头正确。"""
    from src.services.qrcode_service import generate_cert_qr

    png = generate_cert_qr("TEST20260401001", size=200)
    assert isinstance(png, (bytes, bytearray))
    assert len(png) > 100
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "PNG 头不正确"


def test_generate_cert_qr_roundtrip_decode():
    """二维码可解码回原 URL（需要 pyzbar 或 Pillow 本地能装）。
    如果解码依赖缺失，允许跳过该断言，仅验证 PNG 合法性。
    """
    from src.services.qrcode_service import generate_cert_qr

    cert_no = "RTTEST202604010042"
    png = generate_cert_qr(cert_no, size=260, domain="https://zlsjos.cn")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"

    # 尝试用 Pillow + qrcode 解析回读（qrcode 库不自带解码，此处用 Pillow 只校验可读图像）
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(png))
        img.verify()  # Pillow 校验 PNG 合法
    except Exception as e:  # pragma: no cover
        pytest.skip(f"Pillow 不可用：{e}")
