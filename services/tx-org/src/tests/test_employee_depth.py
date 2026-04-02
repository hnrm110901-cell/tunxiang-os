"""员工深度业务逻辑 + API 端点测试

覆盖: calculate_performance_attribution, calculate_commission,
      manage_training, get_training_progress, get_employee_scorecard,
      以及5个API端点
"""
import sys
import os
import uuid
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── API 冒烟测试 ──────────────────────────────────────────────
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


class TestEmployeeDepthAPI:
    """员工深度 API 端点冒烟测试"""

    def test_performance_attribution(self):
        r = client.post(
            "/api/v1/org/depth/employees/e1/performance-attribution?tenant_id=t1",
            json={"date_start": "2026-03-01", "date_end": "2026-03-27"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["employee_id"] == "e1"
        assert "tables_served" in data["data"]

    def test_commission(self):
        r = client.post(
            "/api/v1/org/depth/employees/e1/commission?tenant_id=t1",
            json={"month": "2026-03"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "total_commission_fen" in data["data"]
        assert "base_commission_fen" in data["data"]

    def test_manage_training(self):
        r = client.post(
            "/api/v1/org/depth/employees/e1/training?tenant_id=t1",
            json={
                "action": "assign",
                "course_name": "食品安全基础",
                "category": "food_safety",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["status"] == "pending"

    def test_training_progress(self):
        r = client.get("/api/v1/org/depth/employees/e1/training-progress?tenant_id=t1")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "completed" in data["data"]
        assert "completion_rate" in data["data"]

    def test_scorecard(self):
        r = client.get("/api/v1/org/depth/employees/e1/scorecard?tenant_id=t1")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "dimensions" in data["data"]
        assert "overall_score" in data["data"]

    def test_commission_month_format(self):
        """测试不同月份格式"""
        r = client.post(
            "/api/v1/org/depth/employees/e1/commission?tenant_id=t1",
            json={"month": "2026-12"},
        )
        assert r.status_code == 200
        assert r.json()["data"]["month"] == "2026-12"


# ── 业务逻辑单元测试 ──────────────────────────────────────────

from services.employee_depth import (
    COMMISSION_BASE_RATE,
    COMMISSION_RECOMMEND_RATE,
    COMMISSION_BOTTLE_FEN,
    COMMISSION_UPSELL_RATE,
    TRAINING_STATUS_PENDING,
    TRAINING_STATUS_IN_PROGRESS,
    TRAINING_STATUS_COMPLETED,
    TRAINING_STATUS_FAILED,
)


class TestCommissionConstants:
    """提成常量验证"""

    def test_base_rate(self):
        assert COMMISSION_BASE_RATE == 0.005

    def test_recommend_rate(self):
        assert COMMISSION_RECOMMEND_RATE == 0.02

    def test_bottle_fen(self):
        """开瓶提成单位为分"""
        assert COMMISSION_BOTTLE_FEN == 500
        assert isinstance(COMMISSION_BOTTLE_FEN, int)

    def test_upsell_rate(self):
        assert COMMISSION_UPSELL_RATE == 0.03

    def test_base_commission_calculation(self):
        """基础提成计算: 10万分 * 0.5% = 500分"""
        service_total_fen = 100000
        base_commission = int(service_total_fen * COMMISSION_BASE_RATE)
        assert base_commission == 500

    def test_bottle_commission_calculation(self):
        """开瓶提成: 3瓶 * 500分 = 1500分"""
        bottle_count = 3
        bottle_commission = bottle_count * COMMISSION_BOTTLE_FEN
        assert bottle_commission == 1500


class TestTrainingConstants:
    """培训状态常量（manage_training 已落库 employee_trainings，不再使用内存 dict）。"""

    def test_training_status_values(self):
        assert TRAINING_STATUS_PENDING == "pending"
        assert TRAINING_STATUS_IN_PROGRESS == "in_progress"
        assert TRAINING_STATUS_COMPLETED == "completed"
        assert TRAINING_STATUS_FAILED == "failed"
