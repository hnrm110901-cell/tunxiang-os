"""Learning Points Service 单元测试 — 默认积分值 + 徽章规则"""
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

from src.services.learning_points_service import DEFAULT_POINTS, LearningPointsService


def test_default_points_values():
    assert DEFAULT_POINTS["course_complete"] == 10
    assert DEFAULT_POINTS["exam_pass"] == 20
    assert DEFAULT_POINTS["path_complete"] == 50
    assert DEFAULT_POINTS["teach_others"] == 15


def test_badges_defined():
    svc = LearningPointsService()
    assert "learning_master" in svc.BADGES
    assert "exam_ace" in svc.BADGES
    assert svc.BADGES["learning_master"]["paths_completed"] == 3
    assert svc.BADGES["exam_ace"]["min_points"] == 200
