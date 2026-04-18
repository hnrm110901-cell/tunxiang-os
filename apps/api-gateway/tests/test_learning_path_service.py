"""Learning Path Service 单元测试 — 前置课程校验 + 推荐逻辑"""
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

from src.services.learning_path_service import LearningPathService


def _courses():
    return [
        {"course_id": "c1", "order": 1, "is_mandatory": True, "prerequisite_ids": []},
        {"course_id": "c2", "order": 2, "is_mandatory": True, "prerequisite_ids": ["c1"]},
        {"course_id": "c3", "order": 3, "is_mandatory": True, "prerequisite_ids": ["c1", "c2"]},
    ]


class TestFindNext:
    def test_first_course_when_empty(self):
        next_c = LearningPathService._find_next_available_course(_courses(), set())
        assert next_c["course_id"] == "c1"

    def test_next_after_c1(self):
        next_c = LearningPathService._find_next_available_course(_courses(), {"c1"})
        assert next_c["course_id"] == "c2"

    def test_next_respects_prereq(self):
        # 完成 c1 但没完成 c2 时，c3 不应返回
        next_c = LearningPathService._find_next_available_course(_courses(), {"c1"})
        assert next_c["course_id"] == "c2"

    def test_all_done(self):
        assert LearningPathService._find_next_available_course(_courses(), {"c1", "c2", "c3"}) is None

    def test_skip_order_if_prereq_met(self):
        # 跳开场景：即使 c3 order 靠后，只要前置都满足就返回
        # 这里只完成 c1 和 c2，返回 c3
        next_c = LearningPathService._find_next_available_course(_courses(), {"c1", "c2"})
        assert next_c["course_id"] == "c3"
