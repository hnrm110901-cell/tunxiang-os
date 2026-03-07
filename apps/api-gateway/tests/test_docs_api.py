"""
测试 Phase 2 Month 2 — 开发者文档 & 沙箱
- get_endpoint_catalog（端点目录）
- get_auth_guide（鉴权说明）
- register_sandbox（沙箱账号注册）
"""
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/zhilian")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from src.api.docs_api import (  # noqa: E402
    ENDPOINT_CATALOG,
    AUTH_GUIDE,
    get_endpoint_catalog,
    get_auth_guide,
    register_sandbox,
    SandboxRegisterRequest,
)


# ── 静态目录结构 ───────────────────────────────────────────────────────────────

class TestEndpointCatalog:
    def test_has_all_four_levels(self):
        levels = {ep["level"] for ep in ENDPOINT_CATALOG}
        assert levels == {1, 2, 3, 4}

    def test_all_entries_have_required_fields(self):
        required = {"level", "key", "name", "method", "path", "description", "tier_required",
                    "request_params", "response_example", "code_examples"}
        for ep in ENDPOINT_CATALOG:
            missing = required - set(ep.keys())
            assert not missing, f"{ep['key']} 缺少字段: {missing}"

    def test_all_have_python_example(self):
        for ep in ENDPOINT_CATALOG:
            assert "python" in ep["code_examples"], f"{ep['key']} 缺少 python 示例"

    def test_all_have_nodejs_example(self):
        for ep in ENDPOINT_CATALOG:
            assert "nodejs" in ep["code_examples"], f"{ep['key']} 缺少 nodejs 示例"

    def test_level1_is_free(self):
        for ep in ENDPOINT_CATALOG:
            if ep["level"] == 1:
                assert ep["tier_required"] == "free"

    def test_level4_is_enterprise(self):
        for ep in ENDPOINT_CATALOG:
            if ep["level"] == 4:
                assert ep["tier_required"] == "enterprise"

    def test_response_example_has_code(self):
        for ep in ENDPOINT_CATALOG:
            assert "code" in ep["response_example"], f"{ep['key']} 缺少 response_example.code"
            assert ep["response_example"]["code"] == 200

    def test_minimum_count_per_level(self):
        from collections import Counter
        counts = Counter(ep["level"] for ep in ENDPOINT_CATALOG)
        for lvl in [1, 2, 3, 4]:
            assert counts[lvl] >= 1, f"Level {lvl} 没有端点"


# ── get_endpoint_catalog endpoint ──────────────────────────────────────────────

class TestGetEndpointCatalog:
    def test_returns_all_when_no_level_filter(self):
        result = asyncio.run(get_endpoint_catalog(level=None))
        assert result["total"] == len(ENDPOINT_CATALOG)

    def test_level_filter_works(self):
        result = asyncio.run(get_endpoint_catalog(level=1))
        expected = [ep for ep in ENDPOINT_CATALOG if ep["level"] == 1]
        assert result["total"] == len(expected)
        assert result["levels"] == [1]

    def test_level2_only(self):
        result = asyncio.run(get_endpoint_catalog(level=2))
        for ep in result["by_level"]["2"]["endpoints"]:
            assert ep["level"] == 2

    def test_result_has_by_level(self):
        result = asyncio.run(get_endpoint_catalog())
        assert "by_level" in result
        assert "levels" in result
        assert "total" in result

    def test_level_filter_nonexistent_returns_empty(self):
        result = asyncio.run(get_endpoint_catalog(level=99))
        assert result["total"] == 0


# ── get_auth_guide endpoint ────────────────────────────────────────────────────

class TestGetAuthGuide:
    def test_has_four_steps(self):
        result = asyncio.run(get_auth_guide())
        assert len(result["steps"]) == 4

    def test_steps_ordered(self):
        result = asyncio.run(get_auth_guide())
        for i, step in enumerate(result["steps"], start=1):
            assert step["step"] == i

    def test_step2_has_python_code(self):
        result = asyncio.run(get_auth_guide())
        step2 = result["steps"][1]
        assert "code_python" in step2
        assert "hmac" in step2["code_python"]

    def test_step3_has_headers(self):
        result = asyncio.run(get_auth_guide())
        step3 = result["steps"][2]
        header_names = [h["name"] for h in step3["headers"]]
        assert "X-API-Key" in header_names
        assert "X-Signature" in header_names
        assert "X-Timestamp" in header_names

    def test_step4_has_error_codes(self):
        result = asyncio.run(get_auth_guide())
        step4 = result["steps"][3]
        codes = [e["code"] for e in step4["error_codes"]]
        assert 401 in codes
        assert 429 in codes


# ── register_sandbox endpoint ─────────────────────────────────────────────────

class TestRegisterSandbox:
    def _make_db(self, email_exists: bool = False) -> AsyncMock:
        db = AsyncMock()
        r = MagicMock()
        r.first.return_value = (1,) if email_exists else None
        db.execute = AsyncMock(return_value=r)
        db.commit = AsyncMock()
        return db

    def test_api_key_has_sandbox_prefix(self):
        db = self._make_db(email_exists=False)
        req = SandboxRegisterRequest(name="测试沙箱", email="sandbox@test.com")
        result = asyncio.run(register_sandbox(req, db))
        assert result["api_key"].startswith("zlos_sbx_")

    def test_is_sandbox_true(self):
        db = self._make_db(email_exists=False)
        req = SandboxRegisterRequest(name="测试沙箱", email="sbx2@test.com")
        result = asyncio.run(register_sandbox(req, db))
        assert result["is_sandbox"] is True

    def test_api_secret_present(self):
        db = self._make_db(email_exists=False)
        req = SandboxRegisterRequest(name="测试沙箱", email="sbx3@test.com")
        result = asyncio.run(register_sandbox(req, db))
        assert len(result["api_secret"]) > 20

    def test_duplicate_raises_409(self):
        from fastapi import HTTPException
        db = self._make_db(email_exists=True)
        req = SandboxRegisterRequest(name="重复", email="dup@test.com")
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(register_sandbox(req, db))
        assert exc_info.value.status_code == 409

    def test_rate_limit_is_60(self):
        db = self._make_db(email_exists=False)
        req = SandboxRegisterRequest(name="沙箱用户", email="sbx4@test.com")
        result = asyncio.run(register_sandbox(req, db))
        assert result["rate_limit_rpm"] == 60

    def test_note_mentions_sandbox(self):
        db = self._make_db(email_exists=False)
        req = SandboxRegisterRequest(name="沙箱用户", email="sbx5@test.com")
        result = asyncio.run(register_sandbox(req, db))
        assert "沙箱" in result["note"]
