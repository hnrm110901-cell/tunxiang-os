"""shared/prompt_cache 单元测试

覆盖：
  · BaseCachedPromptBuilder：构造消息 + cache_control + usage 提取 + size 校验
  · parse_json_response / extract_text_from_content：valid / code-fence / broken / empty
  · compute_cache_hit_rate / aggregate_usage：单次 + 多次聚合
  · UsageStats：属性 + 从 response 构造
  · AnthropicCacheInvoker：懒加载 + 错误路径（SDK 未装 / api_key 缺失）
    真实 SDK 调用路径需要 mock，不纳入单元测试

执行：
  pytest shared/prompt_cache/tests/test_prompt_cache.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.prompt_cache import (  # noqa: E402
    AnthropicCacheInvoker,
    BaseCachedPromptBuilder,
    UsageStats,
    aggregate_usage,
    compute_cache_hit_rate,
    parse_json_response,
)
from shared.prompt_cache.metrics import CacheHitTargets  # noqa: E402
from shared.prompt_cache.response_parser import (  # noqa: E402
    extract_text_from_content,
    parse_response,
)

# ────────────────────────────────────────────────
# 1. BaseCachedPromptBuilder
# ────────────────────────────────────────────────


class _DummyBuilder(BaseCachedPromptBuilder):
    """测试用子类：schema 和 benchmarks 都 > 1024 tokens 等价长度"""

    MODEL_ID = "claude-sonnet-4-7"
    MAX_TOKENS = 1024

    @classmethod
    def stable_system(cls) -> str:
        return "你是预算预测 Agent\n" + "x" * 3000  # ~1500+ tokens

    @classmethod
    def domain_benchmarks(cls) -> str:
        return "【行业基准】\n" + "y" * 3000

    @classmethod
    def serialize_user_context(cls, bundle):
        return json.dumps(bundle, ensure_ascii=False)


class _TinyBuilder(BaseCachedPromptBuilder):
    """故意让 cacheable 段太小，触发 validate_cache_size 失败"""

    @classmethod
    def stable_system(cls) -> str:
        return "short"

    @classmethod
    def domain_benchmarks(cls) -> str:
        return "short"

    @classmethod
    def serialize_user_context(cls, bundle):
        return str(bundle)


class TestBaseCachedPromptBuilder:
    def test_build_messages_has_two_cache_blocks(self):
        msg = _DummyBuilder.build_messages({"hello": "world"})
        assert msg["model"] == "claude-sonnet-4-7"
        assert msg["max_tokens"] == 1024
        assert len(msg["system"]) == 2
        assert all(
            b["cache_control"]["type"] == "ephemeral" for b in msg["system"]
        )

    def test_build_messages_user_has_prefix(self):
        msg = _DummyBuilder.build_messages({"x": 1})
        user_content = msg["messages"][0]["content"]
        assert user_content.startswith(_DummyBuilder.USER_PROMPT_PREFIX)
        assert '"x": 1' in user_content

    def test_build_messages_system_block_content_matches(self):
        msg = _DummyBuilder.build_messages({})
        assert msg["system"][0]["text"] == _DummyBuilder.stable_system()
        assert msg["system"][1]["text"] == _DummyBuilder.domain_benchmarks()

    def test_extract_usage_normalizes_field_names(self):
        response = {
            "usage": {
                "cache_read_input_tokens": 3000,
                "cache_creation_input_tokens": 0,
                "input_tokens": 500,
                "output_tokens": 200,
            }
        }
        out = _DummyBuilder.extract_usage(response)
        assert out == {
            "cache_read_tokens": 3000,
            "cache_creation_tokens": 0,
            "input_tokens": 500,
            "output_tokens": 200,
        }

    def test_extract_usage_missing_fields_default_zero(self):
        assert _DummyBuilder.extract_usage({"usage": {}}) == {
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
        assert _DummyBuilder.extract_usage({}) == {
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }

    def test_expected_cache_read_tokens_reasonable(self):
        est = _DummyBuilder.expected_cache_read_tokens()
        # 6000+ 字符 / 2 ≈ 3000 tokens
        assert 2000 < est < 4000

    def test_validate_cache_size_accepts_valid_builder(self):
        ok, msg = _DummyBuilder.validate_cache_size()
        assert ok is True
        assert "达标" in msg

    def test_validate_cache_size_rejects_tiny_builder(self):
        ok, msg = _TinyBuilder.validate_cache_size()
        assert ok is False
        assert "1024" in msg

    def test_cannot_instantiate_base_class(self):
        with pytest.raises(TypeError):
            BaseCachedPromptBuilder()


# ────────────────────────────────────────────────
# 2. response_parser
# ────────────────────────────────────────────────


class TestResponseParser:
    def test_parse_valid_json(self):
        assert parse_json_response('{"a": 1}') == {"a": 1}

    def test_parse_json_code_fence(self):
        raw = '```json\n{"a": 1}\n```'
        assert parse_json_response(raw) == {"a": 1}

    def test_parse_generic_code_fence(self):
        raw = '```\n{"b": 2}\n```'
        assert parse_json_response(raw) == {"b": 2}

    def test_parse_broken_returns_empty(self):
        assert parse_json_response("not json") == {}

    def test_parse_empty_returns_empty(self):
        assert parse_json_response("") == {}
        assert parse_json_response(None) == {}
        assert parse_json_response("   ") == {}

    def test_parse_list_returns_empty(self):
        """顶层是 list 不是 dict → 拒绝"""
        assert parse_json_response("[1, 2, 3]") == {}

    def test_extract_text_from_content_list(self):
        content = [
            {"type": "text", "text": "hello "},
            {"type": "text", "text": "world"},
            {"type": "tool_use", "name": "skip"},
        ]
        assert extract_text_from_content(content) == "hello world"

    def test_extract_text_from_content_str(self):
        assert extract_text_from_content("bare string") == "bare string"

    def test_extract_text_from_content_none(self):
        assert extract_text_from_content(None) == ""

    def test_parse_response_end_to_end(self):
        response = {
            "content": [
                {"type": "text", "text": '```json\n{"analysis": "ok"}\n```'}
            ]
        }
        assert parse_response(response) == {"analysis": "ok"}


# ────────────────────────────────────────────────
# 3. UsageStats
# ────────────────────────────────────────────────


class TestUsageStats:
    def test_cache_hit_rate_zero_when_empty(self):
        assert UsageStats().cache_hit_rate == 0.0

    def test_cache_hit_rate_typical(self):
        u = UsageStats(
            cache_read_tokens=3000, cache_creation_tokens=0, input_tokens=500
        )
        assert abs(u.cache_hit_rate - 0.8571) < 0.001

    def test_from_response_normalizes_fields(self):
        response = {
            "usage": {
                "cache_read_input_tokens": 3000,
                "cache_creation_input_tokens": 500,
                "input_tokens": 1500,
                "output_tokens": 200,
            }
        }
        u = UsageStats.from_response(response)
        assert u.cache_read_tokens == 3000
        assert u.input_tokens == 1500
        assert u.total_input == 5000

    def test_from_response_handles_missing_usage(self):
        u = UsageStats.from_response({})
        assert u.cache_read_tokens == 0


# ────────────────────────────────────────────────
# 4. 聚合 metrics
# ────────────────────────────────────────────────


class TestMetrics:
    def test_compute_cache_hit_rate_zero_when_no_input(self):
        assert (
            compute_cache_hit_rate(
                cache_read_tokens=0, cache_creation_tokens=0, input_tokens=0
            )
            == 0.0
        )

    def test_compute_cache_hit_rate_rounded(self):
        rate = compute_cache_hit_rate(
            cache_read_tokens=750,
            cache_creation_tokens=0,
            input_tokens=250,
        )
        assert rate == 0.75

    def test_aggregate_usage_sums_all_fields(self):
        rows = [
            {
                "cache_read_tokens": 1000,
                "cache_creation_tokens": 3500,
                "input_tokens": 500,
                "output_tokens": 300,
            },
            {
                "cache_read_tokens": 3000,
                "cache_creation_tokens": 0,
                "input_tokens": 500,
                "output_tokens": 200,
            },
            {
                "cache_read_tokens": 3200,
                "cache_creation_tokens": 0,
                "input_tokens": 400,
                "output_tokens": 250,
            },
        ]
        agg = aggregate_usage(rows)
        assert agg.call_count == 3
        assert agg.cache_read_tokens == 7200
        assert agg.cache_creation_tokens == 3500
        assert agg.input_tokens == 1400
        assert agg.output_tokens == 750
        assert agg.total_input == 7200 + 3500 + 1400

    def test_aggregate_usage_empty_iterable(self):
        agg = aggregate_usage([])
        assert agg.call_count == 0
        assert agg.cache_hit_rate == 0.0

    def test_aggregate_meets_steady_target_75(self):
        rows = [
            {"cache_read_tokens": 750, "cache_creation_tokens": 0, "input_tokens": 250}
        ]
        agg = aggregate_usage(rows)
        assert agg.cache_hit_rate == 0.75
        assert agg.meets_steady_target is True

    def test_aggregate_below_target(self):
        rows = [
            {"cache_read_tokens": 400, "cache_creation_tokens": 300, "input_tokens": 300}
        ]
        agg = aggregate_usage(rows)
        assert agg.cache_hit_rate == 0.40
        assert agg.meets_steady_target is False

    def test_aggregate_to_dict_contract(self):
        rows = [
            {
                "cache_read_tokens": 3000,
                "cache_creation_tokens": 0,
                "input_tokens": 1000,
                "output_tokens": 300,
            }
        ]
        d = aggregate_usage(rows).to_dict()
        # 供 API /summary 端点直接返回
        for key in (
            "cache_read_tokens",
            "cache_creation_tokens",
            "input_tokens",
            "output_tokens",
            "call_count",
            "total_input_tokens",
            "cache_hit_rate",
            "meets_steady_target",
            "steady_target",
        ):
            assert key in d
        assert d["steady_target"] == CacheHitTargets.STEADY

    def test_targets_constants(self):
        assert CacheHitTargets.LAUNCH == 0.40
        assert CacheHitTargets.STEADY == 0.75
        assert CacheHitTargets.EXCELLENT == 0.85


# ────────────────────────────────────────────────
# 5. AnthropicCacheInvoker（错误路径）
# ────────────────────────────────────────────────


class TestAnthropicCacheInvoker:
    def test_init_reads_env_api_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
        invoker = AnthropicCacheInvoker()
        assert invoker.api_key == "sk-test-123"

    def test_init_explicit_api_key_wins(self):
        invoker = AnthropicCacheInvoker(api_key="explicit-key")
        assert invoker.api_key == "explicit-key"

    def test_invocation_without_api_key_raises_runtime(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        invoker = AnthropicCacheInvoker()
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            asyncio.run(invoker({"model": "x"}))

    def test_sdk_response_to_dict_already_dict(self):
        from shared.prompt_cache.invoker import _sdk_response_to_dict

        assert _sdk_response_to_dict({"content": []}) == {"content": []}

    def test_sdk_response_to_dict_pydantic_like(self):
        from shared.prompt_cache.invoker import _sdk_response_to_dict

        class FakePydantic:
            def model_dump(self):
                return {"content": [{"type": "text", "text": "ok"}], "usage": {}}

        out = _sdk_response_to_dict(FakePydantic())
        assert out["content"][0]["text"] == "ok"

    def test_defaults(self):
        invoker = AnthropicCacheInvoker(api_key="x")
        assert invoker.timeout_s == 60.0
        assert invoker.max_retries == 2
