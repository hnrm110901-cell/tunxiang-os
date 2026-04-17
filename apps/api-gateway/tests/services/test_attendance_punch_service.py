"""
D10 多打卡方式服务 — 单元测试

覆盖：
  1) Haversine 距离计算（已知坐标对）
  2) GPS 验证：边界内/刚好/边界外
  3) WiFi SSID 白名单
  4) Face mock
  5) QRCode TTL 过期/未过期/缺参
"""

import sys
import time
from unittest.mock import MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.services.attendance_punch_service import (  # noqa: E402
    AttendancePunchService,
    haversine_meters,
)


svc = AttendancePunchService()


class TestHaversine:
    def test_same_point_zero(self):
        assert haversine_meters(28.2, 112.9, 28.2, 112.9) == pytest.approx(0.0, abs=0.001)

    def test_short_distance(self):
        # 长沙市中心附近两点，约 0.001 度 ≈ 111m（纬度上）
        d = haversine_meters(28.2000, 112.9000, 28.2010, 112.9000)
        assert 100 < d < 120


class TestGPSVerify:
    store_lat, store_lng = 28.2000, 112.9000

    def test_inside_200m(self):
        # 纬度 +0.001 ≈ 111m
        v = svc.verify_gps(28.2010, 112.9000, self.store_lat, self.store_lng)
        assert v["verified"] is True
        assert v["distance_meters"] < 200

    def test_outside_200m(self):
        # 纬度 +0.005 ≈ 555m
        v = svc.verify_gps(28.2050, 112.9000, self.store_lat, self.store_lng)
        assert v["verified"] is False
        assert v["distance_meters"] > 200

    def test_custom_radius(self):
        v = svc.verify_gps(28.2050, 112.9000, self.store_lat, self.store_lng, radius_meters=1000)
        assert v["verified"] is True

    def test_boundary_just_outside(self):
        # 恰好略大于 200m
        v = svc.verify_gps(28.20181, 112.9000, self.store_lat, self.store_lng)
        assert v["distance_meters"] > 200
        assert v["verified"] is False


class TestWiFiVerify:
    def test_match(self):
        assert svc.verify_wifi("Store-WiFi", ["Store-WiFi", "Guest"])["verified"] is True

    def test_mismatch(self):
        assert svc.verify_wifi("Evil-WiFi", ["Store-WiFi"])["verified"] is False

    def test_empty_ssid(self):
        assert svc.verify_wifi("", ["Store-WiFi"])["verified"] is False


class TestFaceVerify:
    def test_with_token_passes(self):
        v = svc.verify_face("face-token-xyz")
        assert v["verified"] is True
        assert v["mock"] is True

    def test_no_token_fails(self):
        assert svc.verify_face(None)["verified"] is False


class TestQRCodeVerify:
    def test_fresh_code_ok(self):
        now = time.time()
        assert svc.verify_qrcode("CODE-X", now - 5)["verified"] is True

    def test_expired_code(self):
        v = svc.verify_qrcode("CODE-X", time.time() - 60)
        assert v["verified"] is False
        assert v["reason"] == "expired"

    def test_missing_params(self):
        assert svc.verify_qrcode("", None)["verified"] is False
