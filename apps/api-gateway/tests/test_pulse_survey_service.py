"""Pulse Survey Service 单元测试 — 匿名哈希 + 关键词情感"""
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

from src.services.pulse_survey_service import PulseSurveyService


class TestAnonymousHash:
    def test_deterministic(self):
        h1 = PulseSurveyService._hash_employee("emp001", "inst-uuid-1")
        h2 = PulseSurveyService._hash_employee("emp001", "inst-uuid-1")
        assert h1 == h2

    def test_different_instance_different_hash(self):
        h1 = PulseSurveyService._hash_employee("emp001", "inst-1")
        h2 = PulseSurveyService._hash_employee("emp001", "inst-2")
        assert h1 != h2

    def test_length_64(self):
        h = PulseSurveyService._hash_employee("e", "i")
        assert len(h) == 64


class TestKeywordSentiment:
    def test_positive(self):
        assert PulseSurveyService._kw_sentiment("工作很棒 非常满意") == "positive"

    def test_negative(self):
        assert PulseSurveyService._kw_sentiment("太差了 想辞职") == "negative"

    def test_neutral(self):
        assert PulseSurveyService._kw_sentiment("今天吃的米饭") == "neutral"

    def test_negative_takes_priority(self):
        # 负面关键词优先
        assert PulseSurveyService._kw_sentiment("服务挺好的 但很累") == "negative"
