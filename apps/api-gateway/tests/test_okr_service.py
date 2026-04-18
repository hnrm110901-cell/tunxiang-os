"""OKR Service 单元测试 — KR 进度、健康分、加权平均"""
import os
for _k, _v in {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    "SECRET_KEY": "test-secret",
    "JWT_SECRET": "test-jwt",
}.items():
    os.environ.setdefault(_k, _v)

from decimal import Decimal
from types import SimpleNamespace

import pytest
from src.services.okr_service import OKRService


@pytest.fixture
def svc():
    return OKRService()


class TestKRProgress:
    def _kr(self, metric_type="numeric", start=0, target=100, current=50):
        return SimpleNamespace(
            metric_type=metric_type,
            start_value=Decimal(str(start)),
            target_value=Decimal(str(target)),
            current_value=Decimal(str(current)),
        )

    def test_numeric_half(self, svc):
        assert svc._calc_kr_progress(self._kr(current=50)) == Decimal("50.0")

    def test_numeric_cap_100(self, svc):
        assert svc._calc_kr_progress(self._kr(current=150)) == Decimal("100.0")

    def test_numeric_floor_zero(self, svc):
        assert svc._calc_kr_progress(self._kr(start=50, target=100, current=0)) == Decimal("0.0")

    def test_boolean(self, svc):
        assert svc._calc_kr_progress(self._kr(metric_type="boolean", current=1)) == Decimal("100")
        assert svc._calc_kr_progress(self._kr(metric_type="boolean", current=0)) == Decimal("0")

    def test_milestone(self, svc):
        assert svc._calc_kr_progress(self._kr(metric_type="milestone", current=42)) == Decimal("42.0")

    def test_same_start_target(self, svc):
        assert svc._calc_kr_progress(self._kr(start=100, target=100, current=100)) == Decimal("100")


class TestHealthCheck:
    def test_green(self, svc):
        assert svc.health_check_by_progress(75.0) == "green"
        assert svc.health_check_by_progress(100.0) == "green"

    def test_yellow(self, svc):
        assert svc.health_check_by_progress(50.0) == "yellow"
        assert svc.health_check_by_progress(40.0) == "yellow"

    def test_red(self, svc):
        assert svc.health_check_by_progress(20.0) == "red"
        assert svc.health_check_by_progress(0.0) == "red"
