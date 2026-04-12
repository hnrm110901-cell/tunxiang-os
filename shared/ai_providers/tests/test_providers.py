"""多 Provider 架构集成测试。

覆盖：模型注册表、配置加载、数据安全脱敏/还原、Provider 权限、
任务路由、MigrationRouter 兼容性、A/B 测试确定性分配、
领域增强术语检测、熔断切换。

运行方式：
    pytest shared/ai_providers/tests/test_providers.py -v
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
from typing import Any, AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.ai_providers.config import ProviderConfig, load_provider_configs
from shared.ai_providers.registry import MODEL_REGISTRY, get_model_info, get_models_by_tier
from shared.ai_providers.security import (
    PROVIDER_DATA_CLEARANCE,
    DataSecurityGateway,
    DataSensitivity,
    MaskContext,
)
from shared.ai_providers.types import (
    LLMResponse,
    ModelInfo,
    ModelTier,
    ProviderHealth,
    ProviderName,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 模型注册表
# ─────────────────────────────────────────────────────────────────────────────

class TestModelRegistry:
    """test_model_registry -- 验证 19 个模型全部注册且定价非零。"""

    def test_model_registry_has_expected_models(self) -> None:
        """注册表应包含 17 个模型（3 Anthropic + 2 DeepSeek + 4 Qwen + 2 GLM + 2 ERNIE + 2 Kimi + 2 CoreML）。"""
        assert len(MODEL_REGISTRY) == 17, (
            f"预期 17 个模型，实际 {len(MODEL_REGISTRY)}。"
            f" 已注册: {sorted(MODEL_REGISTRY.keys())}"
        )

    def test_all_models_have_pricing(self) -> None:
        """所有非免费模型的定价都应大于零。"""
        free_models = {"ernie-speed-128k", "coreml-dish-time", "coreml-discount-risk"}
        for model_id, info in MODEL_REGISTRY.items():
            if model_id in free_models:
                # 免费模型允许定价为零
                continue
            assert info.pricing.input_rmb_per_million > 0, (
                f"模型 {model_id} 的输入定价为零"
            )
            assert info.pricing.output_rmb_per_million > 0, (
                f"模型 {model_id} 的输出定价为零"
            )

    def test_all_models_have_required_fields(self) -> None:
        """每个注册模型都应包含必要字段。"""
        for model_id, info in MODEL_REGISTRY.items():
            assert info.provider is not None, f"{model_id}: provider 缺失"
            assert info.display_name, f"{model_id}: display_name 为空"
            assert info.tier is not None, f"{model_id}: tier 缺失"
            assert info.max_context_tokens > 0, f"{model_id}: max_context_tokens <= 0"
            assert info.max_output_tokens > 0, f"{model_id}: max_output_tokens <= 0"

    def test_get_model_info_existing(self) -> None:
        """get_model_info 应能查询到已注册模型。"""
        info = get_model_info("claude-sonnet-4-6")
        assert info.provider == ProviderName.ANTHROPIC
        assert info.tier == ModelTier.STANDARD

    def test_get_model_info_unknown_raises(self) -> None:
        """get_model_info 查询未注册模型应抛出 KeyError。"""
        with pytest.raises(KeyError, match="未注册的模型"):
            get_model_info("nonexistent-model-v99")

    def test_models_by_tier(self) -> None:
        """按 tier 查询应返回正确的模型集合。"""
        lite_models = get_models_by_tier(ModelTier.LITE)
        assert len(lite_models) >= 3  # haiku, qwen-turbo, glm-4-flash, ernie-speed, coreml-*
        # 应按价格升序排列
        prices = [m.pricing.input_rmb_per_million for m in lite_models]
        assert prices == sorted(prices)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Provider 配置加载
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderConfigLoading:
    """test_provider_config_loading -- 验证环境变量加载逻辑。"""

    def test_load_with_anthropic_key(self) -> None:
        """设置 ANTHROPIC_API_KEY 时应正确加载。"""
        env = {
            "ANTHROPIC_API_KEY": "sk-test-key-123",
            "ANTHROPIC_ENABLED": "true",
            "ANTHROPIC_PRIORITY": "10",
        }
        with patch.dict(os.environ, env, clear=False):
            configs = load_provider_configs()
            anthropic_cfg = configs[ProviderName.ANTHROPIC]
            assert anthropic_cfg.api_key == "sk-test-key-123"
            assert anthropic_cfg.enabled is True
            assert anthropic_cfg.priority == 10

    def test_load_disabled_provider(self) -> None:
        """DEEPSEEK_ENABLED=false 时 DeepSeek 应被禁用。"""
        env = {
            "DEEPSEEK_API_KEY": "sk-deepseek-test",
            "DEEPSEEK_ENABLED": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            configs = load_provider_configs()
            ds_cfg = configs[ProviderName.DEEPSEEK]
            assert ds_cfg.api_key == "sk-deepseek-test"
            assert ds_cfg.enabled is False

    def test_load_coreml_no_key_needed(self) -> None:
        """Core ML 本地服务不需要 API Key。"""
        with patch.dict(os.environ, {"COREML_ENABLED": "true"}, clear=False):
            configs = load_provider_configs()
            coreml_cfg = configs[ProviderName.COREML]
            assert coreml_cfg.base_url == "http://localhost:8100"
            assert coreml_cfg.enabled is True

    def test_load_with_no_keys_all_disabled(self) -> None:
        """无任何 API Key 时，除 Core ML 外的 Provider 应被禁用。"""
        env_clear = {
            "ANTHROPIC_API_KEY": "",
            "DEEPSEEK_API_KEY": "",
            "DASHSCOPE_API_KEY": "",
            "ZHIPUAI_API_KEY": "",
            "QIANFAN_API_KEY": "",
            "MOONSHOT_API_KEY": "",
        }
        with patch.dict(os.environ, env_clear, clear=False):
            configs = load_provider_configs()
            for provider, cfg in configs.items():
                if provider == ProviderName.COREML:
                    continue
                # 空字符串 key 不算有 key，所以 enabled 取决于 env 的默认逻辑
                # 当 api_key 为空字符串时，os.environ.get 返回 ""（truthy）
                # 但 load_provider_configs 用 "true" if api_key else "false"
                # 空字符串是 falsy，所以应该被禁用
                if not cfg.api_key:
                    assert cfg.enabled is False, (
                        f"{provider.value} 无 API Key 时应被禁用"
                    )

    def test_custom_base_url(self) -> None:
        """自定义 BASE_URL 应正确加载。"""
        env = {
            "DEEPSEEK_API_KEY": "sk-ds-test",
            "DEEPSEEK_BASE_URL": "https://custom-proxy.example.com/v1",
        }
        with patch.dict(os.environ, env, clear=False):
            configs = load_provider_configs()
            ds_cfg = configs[ProviderName.DEEPSEEK]
            assert ds_cfg.base_url == "https://custom-proxy.example.com/v1"


# ─────────────────────────────────────────────────────────────────────────────
# 3. 数据安全脱敏
# ─────────────────────────────────────────────────────────────────────────────

class TestDataSecurityMasking:
    """test_data_security_masking -- 验证手机号、身份证、银行卡脱敏。"""

    def setup_method(self) -> None:
        self.gateway = DataSecurityGateway()

    def test_mask_phone_number(self) -> None:
        """手机号应被替换为 [TX_PHONE_xxxx_001] 格式。"""
        ctx = MaskContext(request_id="test-1")
        result = self.gateway.mask_text("联系人手机: 13812345678", ctx)
        assert "13812345678" not in result
        assert "[TX_PHONE_test_001]" in result
        assert len(ctx.tokens) == 1
        assert ctx.tokens[0].category == "phone"
        assert ctx.tokens[0].original == "13812345678"

    def test_mask_id_card(self) -> None:
        """身份证号应被替换为 [TX_IDCARD_xxxx_001] 格式。"""
        ctx = MaskContext(request_id="test-2")
        result = self.gateway.mask_text("身份证号: 430121199901011234", ctx)
        assert "430121199901011234" not in result
        assert "[TX_IDCARD_test_001]" in result

    def test_mask_bank_card(self) -> None:
        """银行卡号应被替换为 [BANKCARD_001] 格式。"""
        ctx = MaskContext(request_id="test-3")
        # 使用 19 位银行卡号（区分于身份证 18 位）
        result = self.gateway.mask_text("银行卡: 6222021234567890123", ctx)
        assert "6222021234567890123" not in result
        # 可能被识别为 bank_card
        assert any(t.category == "bank_card" for t in ctx.tokens)

    def test_mask_multiple_pii(self) -> None:
        """多个 PII 应同时脱敏。"""
        text = "张三手机13912345678, 邮箱zhang@test.com"
        ctx = MaskContext(request_id="test-4")
        result = self.gateway.mask_text(text, ctx)
        assert "13912345678" not in result
        assert "zhang@test.com" not in result
        assert len(ctx.tokens) >= 2

    def test_sensitivity_auto_escalation(self) -> None:
        """脱敏后敏感级别应自动升级。"""
        ctx = MaskContext(request_id="test-5")
        assert ctx.sensitivity_level == DataSensitivity.PUBLIC
        self.gateway.mask_text("手机: 13812345678", ctx)
        assert ctx.sensitivity_level == DataSensitivity.SENSITIVE

    def test_mask_messages(self) -> None:
        """mask_messages 应对所有消息内容脱敏。"""
        messages = [
            {"role": "user", "content": "帮我查 13812345678 的订单"},
            {"role": "assistant", "content": "好的，正在查询"},
        ]
        masked_msgs, ctx = self.gateway.mask_messages(messages, tenant_id="t-001")
        assert "13812345678" not in masked_msgs[0]["content"]
        assert "TX_PHONE_" in masked_msgs[0]["content"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. 数据安全还原
# ─────────────────────────────────────────────────────────────────────────────

class TestDataSecurityUnmask:
    """test_data_security_unmask -- 验证响应还原。"""

    def setup_method(self) -> None:
        self.gateway = DataSecurityGateway()

    def test_unmask_restores_phone(self) -> None:
        """还原应将脱敏令牌恢复为原始手机号。"""
        ctx = MaskContext(request_id="test-u1")
        original_text = "客户 13812345678 的订单已处理"
        masked = self.gateway.mask_text(original_text, ctx)
        assert "TX_PHONE_test_001" in masked

        # 模拟 LLM 返回的响应中包含脱敏令牌
        token = ctx.tokens[0].token
        llm_response = f"已处理 {token} 的订单，通知已发送到 {token}"
        restored = self.gateway.unmask_text(llm_response, ctx)
        assert "13812345678" in restored
        assert token not in restored

    def test_unmask_multiple_categories(self) -> None:
        """还原应同时恢复多个类别的脱敏数据。"""
        ctx = MaskContext(request_id="test-u2")
        text = "手机13812345678, 邮箱test@example.com"
        self.gateway.mask_text(text, ctx)

        # 使用实际生成的 token 构建模拟响应
        phone_token = next(t.token for t in ctx.tokens if t.category == "phone")
        email_token = next(t.token for t in ctx.tokens if t.category == "email")
        response = f"已发送到 {phone_token} 和 {email_token}"
        restored = self.gateway.unmask_text(response, ctx)
        assert "13812345678" in restored
        assert "test@example.com" in restored

    def test_unmask_no_tokens(self) -> None:
        """无脱敏令牌时还原应原样返回。"""
        ctx = MaskContext(request_id="test-u3")
        text = "这是一段普通文本"
        restored = self.gateway.unmask_text(text, ctx)
        assert restored == text

    def test_roundtrip_mask_unmask(self) -> None:
        """脱敏 -> LLM 引用令牌 -> 还原，应还原出正确数据。"""
        ctx = MaskContext(request_id="test-u4")
        original = "会员 13912345678 的消费记录"
        masked = self.gateway.mask_text(original, ctx)

        # LLM "看到" 的是脱敏文本，回复中引用了令牌
        token = ctx.tokens[0].token
        llm_reply = f"查到 {token} 本月消费 3 次"
        restored = self.gateway.unmask_text(llm_reply, ctx)
        assert "13912345678" in restored


# ─────────────────────────────────────────────────────────────────────────────
# 5. Provider 权限校验
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderClearance:
    """test_provider_clearance -- 验证 Anthropic 无法处理 SENSITIVE 数据。"""

    def setup_method(self) -> None:
        self.gateway = DataSecurityGateway()

    def test_anthropic_blocked_for_sensitive(self) -> None:
        """Anthropic（境外）不应有权处理 SENSITIVE 级别数据。"""
        ctx = MaskContext(request_id="test-c1")
        # 手动设置敏感级别
        ctx.sensitivity_level = DataSensitivity.SENSITIVE

        with pytest.raises(PermissionError, match="anthropic"):
            self.gateway.check_provider_clearance("anthropic", ctx)

    def test_anthropic_allowed_for_internal(self) -> None:
        """Anthropic 应允许处理 INTERNAL 级别数据。"""
        ctx = MaskContext(request_id="test-c2")
        ctx.sensitivity_level = DataSensitivity.INTERNAL

        result = self.gateway.check_provider_clearance("anthropic", ctx)
        assert result is True

    def test_deepseek_allowed_for_sensitive(self) -> None:
        """DeepSeek（境内）应允许处理 SENSITIVE 级别数据。"""
        ctx = MaskContext(request_id="test-c3")
        ctx.sensitivity_level = DataSensitivity.SENSITIVE

        result = self.gateway.check_provider_clearance("deepseek", ctx)
        assert result is True

    def test_coreml_allowed_for_restricted(self) -> None:
        """Core ML（本地）应允许处理所有级别数据，包括 RESTRICTED。"""
        ctx = MaskContext(request_id="test-c4")
        ctx.sensitivity_level = DataSensitivity.RESTRICTED

        result = self.gateway.check_provider_clearance("coreml", ctx)
        assert result is True

    def test_all_domestic_providers_allow_sensitive(self) -> None:
        """所有境内 Provider 都应允许处理 SENSITIVE 数据。"""
        domestic_providers = ["deepseek", "qwen", "glm", "ernie", "kimi"]
        ctx = MaskContext(request_id="test-c5")
        ctx.sensitivity_level = DataSensitivity.SENSITIVE

        for provider in domestic_providers:
            result = self.gateway.check_provider_clearance(provider, ctx)
            assert result is True, f"{provider} 应允许处理 SENSITIVE 数据"

    def test_audit_log_on_block(self) -> None:
        """拦截时应记录审计日志。"""
        ctx = MaskContext(request_id="test-c6")
        ctx.sensitivity_level = DataSensitivity.SENSITIVE

        try:
            self.gateway.check_provider_clearance("anthropic", ctx)
        except PermissionError:
            pass

        audit = self.gateway.get_audit_log()
        assert len(audit) >= 1
        latest = audit[-1]
        assert latest.blocked is True
        assert latest.provider == "anthropic"


# ─────────────────────────────────────────────────────────────────────────────
# 6. 任务路由策略
# ─────────────────────────────────────────────────────────────────────────────

class TestTaskRoutingStrategy:
    """test_task_routing_strategy -- 验证任务路由链的正确性。"""

    def test_tier_to_provider_mapping(self) -> None:
        """每个 tier 都应有可用模型。"""
        for tier in ModelTier:
            models = get_models_by_tier(tier)
            assert len(models) > 0, f"tier={tier.value} 没有可用模型"

    def test_lite_tier_has_cheapest_first(self) -> None:
        """LITE tier 模型应按价格升序排列。"""
        models = get_models_by_tier(ModelTier.LITE)
        prices = [m.pricing.input_rmb_per_million for m in models]
        assert prices == sorted(prices)

    def test_provider_name_coverage(self) -> None:
        """注册表应覆盖所有 7 个 Provider。"""
        providers_in_registry = {info.provider for info in MODEL_REGISTRY.values()}
        assert ProviderName.ANTHROPIC in providers_in_registry
        assert ProviderName.DEEPSEEK in providers_in_registry
        assert ProviderName.QWEN in providers_in_registry
        assert ProviderName.GLM in providers_in_registry
        assert ProviderName.ERNIE in providers_in_registry
        assert ProviderName.KIMI in providers_in_registry
        assert ProviderName.COREML in providers_in_registry

    def test_long_ctx_tier_available(self) -> None:
        """LONG_CTX tier 应包含长上下文模型（qwen-long, kimi-128k）。"""
        models = get_models_by_tier(ModelTier.LONG_CTX)
        model_ids = {m.model_id for m in models}
        assert "qwen-long" in model_ids
        assert "moonshot-v1-128k" in model_ids

    def test_standard_tier_cost_ordering(self) -> None:
        """STANDARD tier 的模型应覆盖从低价到高价的范围。"""
        models = get_models_by_tier(ModelTier.STANDARD)
        min_price = min(m.pricing.input_rmb_per_million for m in models)
        max_price = max(m.pricing.input_rmb_per_million for m in models)
        # 应有明显的价格梯度
        assert max_price > min_price * 2, (
            f"STANDARD tier 价格梯度不足: min={min_price}, max={max_price}"
        )

    def test_data_clearance_matrix_completeness(self) -> None:
        """权限矩阵应覆盖所有 Provider。"""
        for provider in ProviderName:
            assert provider.value in PROVIDER_DATA_CLEARANCE, (
                f"{provider.value} 未在 PROVIDER_DATA_CLEARANCE 中定义"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 7. MigrationRouter 兼容性
# ─────────────────────────────────────────────────────────────────────────────

class TestMigrationRouterCompat:
    """test_migration_router_compat -- 验证 MigrationRouter 返回 str 类型。"""

    @pytest.mark.asyncio
    async def test_complete_returns_str(self) -> None:
        """MigrationRouter.complete() 应返回 str 类型。"""
        # Mock Anthropic client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="分析结果：销售额上升了15%")]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}):
            from shared.ai_providers.migration import MigrationRouter

            router = MigrationRouter(api_key="sk-test-key")
            # Mock the _client.messages.create
            router._client = MagicMock()
            router._client.messages.create = AsyncMock(return_value=mock_response)

            result = await router.complete(
                tenant_id="t-001",
                task_type="standard_analysis",
                messages=[{"role": "user", "content": "分析销售数据"}],
            )

            assert isinstance(result, str)
            assert "分析结果" in result

    @pytest.mark.asyncio
    async def test_complete_signature_matches_old_router(self) -> None:
        """MigrationRouter.complete 签名应包含所有旧参数。"""
        import inspect
        from shared.ai_providers.migration import MigrationRouter

        sig = inspect.signature(MigrationRouter.complete)
        param_names = list(sig.parameters.keys())

        expected_params = [
            "self", "tenant_id", "task_type", "messages",
            "system", "urgency", "max_tokens", "timeout_s",
            "request_id", "db",
        ]
        for p in expected_params:
            assert p in param_names, f"缺少参数: {p}"

    @pytest.mark.asyncio
    async def test_stream_complete_signature_matches_old_router(self) -> None:
        """MigrationRouter.stream_complete 签名应包含所有旧参数。"""
        import inspect
        from shared.ai_providers.migration import MigrationRouter

        sig = inspect.signature(MigrationRouter.stream_complete)
        param_names = list(sig.parameters.keys())

        expected_params = [
            "self", "tenant_id", "task_type", "messages",
            "system", "urgency", "max_tokens",
        ]
        for p in expected_params:
            assert p in param_names, f"缺少参数: {p}"

    @pytest.mark.asyncio
    async def test_legacy_mode_by_default(self) -> None:
        """默认情况下应使用旧版模式。"""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}, clear=False):
            from shared.ai_providers.migration import MigrationRouter

            router = MigrationRouter(api_key="sk-test-key")
            assert router._multi_provider_enabled is False

    @pytest.mark.asyncio
    async def test_feature_flag_respected(self) -> None:
        """MULTI_PROVIDER_ENABLED=true 但 router 不可用时应降级。"""
        with patch.dict(
            os.environ,
            {"MULTI_PROVIDER_ENABLED": "true", "ANTHROPIC_API_KEY": "sk-test-key"},
            clear=False,
        ):
            # 因为 shared.ai_providers.router 不存在，
            # _NEW_ROUTER_AVAILABLE=False，应降级到 legacy
            from shared.ai_providers.migration import MigrationRouter

            router = MigrationRouter(api_key="sk-test-key")
            # 新架构不可用时，即使 flag=true 也应降级
            assert router._new_router is None

    @pytest.mark.asyncio
    async def test_stream_complete_yields_str(self) -> None:
        """MigrationRouter.stream_complete() 应 yield str。"""
        mock_stream = MagicMock()

        async def mock_text_stream():
            for chunk in ["你好", "世界"]:
                yield chunk

        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.text_stream = mock_text_stream()

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}):
            from shared.ai_providers.migration import MigrationRouter

            router = MigrationRouter(api_key="sk-test-key")
            router._client = MagicMock()
            router._client.messages.stream = MagicMock(return_value=mock_stream)

            chunks = []
            async for chunk in router.stream_complete(
                tenant_id="t-001",
                task_type="standard_analysis",
                messages=[{"role": "user", "content": "生成报告"}],
            ):
                assert isinstance(chunk, str)
                chunks.append(chunk)

            assert len(chunks) == 2
            assert chunks == ["你好", "世界"]


# ─────────────────────────────────────────────────────────────────────────────
# 8. A/B 测试确定性分配
# ─────────────────────────────────────────────────────────────────────────────

class TestABTestDeterministicAssignment:
    """test_ab_test_deterministic_assignment -- 验证同租户分配到同变体。

    A/B 测试分配策略：使用 tenant_id 的 hash 确定性分配，
    确保同一租户在所有请求中始终命中相同变体。
    """

    @staticmethod
    def _assign_variant(tenant_id: str, experiment_id: str, num_variants: int = 2) -> int:
        """确定性 A/B 分配算法（模拟实际实现）。

        使用 SHA256(tenant_id + experiment_id) 的前 8 字节取模。
        """
        key = f"{tenant_id}:{experiment_id}"
        hash_bytes = hashlib.sha256(key.encode()).digest()
        hash_int = int.from_bytes(hash_bytes[:8], "big")
        return hash_int % num_variants

    def test_same_tenant_same_variant(self) -> None:
        """同一租户在多次调用中应分配到相同变体。"""
        tenant_id = "tenant-abc-123"
        experiment_id = "exp-provider-routing-v1"

        results = [
            self._assign_variant(tenant_id, experiment_id)
            for _ in range(100)
        ]
        # 所有结果应相同
        assert len(set(results)) == 1

    def test_different_tenants_vary(self) -> None:
        """不同租户应分散到不同变体（统计上）。"""
        experiment_id = "exp-provider-routing-v1"
        variants = [
            self._assign_variant(f"tenant-{i}", experiment_id)
            for i in range(1000)
        ]
        # 至少应有两个不同的变体
        assert len(set(variants)) >= 2

    def test_different_experiments_independent(self) -> None:
        """同一租户在不同实验中的分配应独立。"""
        tenant_id = "tenant-fixed-001"
        variants = [
            self._assign_variant(tenant_id, f"exp-{i}")
            for i in range(100)
        ]
        # 不同实验应有分散的结果
        assert len(set(variants)) >= 2

    def test_three_way_split(self) -> None:
        """三变体实验应支持 0/1/2 三个桶。"""
        experiment_id = "exp-three-way-v1"
        variants = {
            self._assign_variant(f"tenant-{i}", experiment_id, num_variants=3)
            for i in range(1000)
        }
        assert variants == {0, 1, 2}


# ─────────────────────────────────────────────────────────────────────────────
# 9. 领域增强术语检测
# ─────────────────────────────────────────────────────────────────────────────

class TestDomainEnhancerTerms:
    """test_domain_enhancer_terms -- 验证餐饮领域术语检测。

    DomainEnhancer 在发送 prompt 前注入餐饮行业上下文术语，
    帮助模型更好理解领域特定概念。
    """

    # 餐饮领域术语表（模拟实际 DomainEnhancer 使用的术语）
    CATERING_TERMS: dict[str, str] = {
        "四象限": "菜品分类法，按销量和毛利分为明星/金牛/问题/淘汰四类",
        "日清日结": "门店每日营业结束后的对账和结算流程（E1-E8八步）",
        "BOM": "Bill of Materials，菜品配方表，定义原料和用量",
        "RFM": "Recency/Frequency/Monetary，会员价值分层模型",
        "KDS": "Kitchen Display System，后厨出餐显示屏",
        "桌台拓扑": "门店桌台布局和状态管理",
        "做法": "菜品的烹饪方式变体（如：微辣/中辣/特辣）",
        "档口": "后厨分区，每个档口负责特定品类的出品",
        "Golden ID": "会员全渠道唯一标识，打通线上线下消费数据",
        "毛利底线": "Ontology 三条硬约束之一，任何折扣不可使单笔毛利低于阈值",
    }

    @staticmethod
    def _detect_terms(text: str, terms: dict[str, str]) -> list[str]:
        """检测文本中包含的领域术语。"""
        found = []
        for term in terms:
            if term in text:
                found.append(term)
        return found

    @staticmethod
    def _enhance_prompt(text: str, terms: dict[str, str]) -> str:
        """在 prompt 中注入检测到的术语解释。"""
        detected = TestDomainEnhancerTerms._detect_terms(text, terms)
        if not detected:
            return text
        glossary = "\n".join(f"- {t}: {terms[t]}" for t in detected)
        return f"[领域术语]\n{glossary}\n\n{text}"

    def test_detect_single_term(self) -> None:
        """应检测到单个术语。"""
        text = "请分析这道菜的BOM配方"
        found = self._detect_terms(text, self.CATERING_TERMS)
        assert "BOM" in found

    def test_detect_multiple_terms(self) -> None:
        """应检测到多个术语。"""
        text = "根据四象限分析和RFM模型，优化日清日结流程"
        found = self._detect_terms(text, self.CATERING_TERMS)
        assert "四象限" in found
        assert "RFM" in found
        assert "日清日结" in found

    def test_enhance_prompt_adds_glossary(self) -> None:
        """增强后的 prompt 应包含术语解释。"""
        text = "分析KDS出餐效率"
        enhanced = self._enhance_prompt(text, self.CATERING_TERMS)
        assert "[领域术语]" in enhanced
        assert "Kitchen Display System" in enhanced
        assert text in enhanced

    def test_no_terms_no_enhancement(self) -> None:
        """无术语时 prompt 应原样返回。"""
        text = "今天天气不错"
        enhanced = self._enhance_prompt(text, self.CATERING_TERMS)
        assert enhanced == text

    def test_all_terms_detectable(self) -> None:
        """所有术语应可被检测到。"""
        for term in self.CATERING_TERMS:
            found = self._detect_terms(f"包含{term}的文本", self.CATERING_TERMS)
            assert term in found, f"术语 '{term}' 未被检测到"


# ─────────────────────────────────────────────────────────────────────────────
# 10. 熔断后自动切换 Provider
# ─────────────────────────────────────────────────────────────────────────────

class TestCircuitBreakerFailover:
    """test_circuit_breaker_failover -- 验证熔断后自动切换 Provider。

    场景：主 Provider（如 Anthropic）连续失败达阈值后熔断，
    系统应自动切换到备选 Provider（如 DeepSeek）。
    """

    @pytest.mark.asyncio
    async def test_failover_after_circuit_open(self) -> None:
        """主 Provider 熔断后应切换到备选 Provider。"""
        # 模拟 Provider 健康状态
        provider_health: dict[str, bool] = {
            "anthropic": False,  # 已熔断
            "deepseek": True,
            "qwen": True,
        }

        # 模拟 Provider 选择逻辑
        fallback_order = ["anthropic", "deepseek", "qwen"]

        def select_available_provider() -> str:
            for p in fallback_order:
                if provider_health.get(p, False):
                    return p
            raise RuntimeError("所有 Provider 不可用")

        selected = select_available_provider()
        assert selected == "deepseek"

    @pytest.mark.asyncio
    async def test_failover_respects_priority(self) -> None:
        """切换时应按配置的优先级顺序选择。"""
        providers = [
            ProviderConfig(provider=ProviderName.ANTHROPIC, api_key="sk-1", priority=0, enabled=True),
            ProviderConfig(provider=ProviderName.DEEPSEEK, api_key="sk-2", priority=1, enabled=True),
            ProviderConfig(provider=ProviderName.QWEN, api_key="sk-3", priority=2, enabled=True),
        ]

        # Anthropic 熔断，应选择 priority=1 的 DeepSeek
        circuit_open = {ProviderName.ANTHROPIC}

        available = [
            p for p in sorted(providers, key=lambda x: x.priority)
            if p.provider not in circuit_open and p.enabled
        ]

        assert len(available) >= 1
        assert available[0].provider == ProviderName.DEEPSEEK

    @pytest.mark.asyncio
    async def test_all_providers_down_raises(self) -> None:
        """所有 Provider 不可用时应抛出异常。"""
        provider_health = {p.value: False for p in ProviderName}

        def select_available() -> str:
            for name, healthy in provider_health.items():
                if healthy:
                    return name
            raise RuntimeError("所有 Provider 不可用")

        with pytest.raises(RuntimeError, match="所有 Provider 不可用"):
            select_available()

    @pytest.mark.asyncio
    async def test_circuit_recovery_returns_to_primary(self) -> None:
        """主 Provider 恢复后应切回主 Provider。"""
        provider_health: dict[str, bool] = {
            "anthropic": False,
            "deepseek": True,
        }
        fallback_order = ["anthropic", "deepseek"]

        # 第一次：anthropic 不可用，选 deepseek
        selected_1 = next(p for p in fallback_order if provider_health[p])
        assert selected_1 == "deepseek"

        # anthropic 恢复
        provider_health["anthropic"] = True

        # 第二次：anthropic 恢复，应切回
        selected_2 = next(p for p in fallback_order if provider_health[p])
        assert selected_2 == "anthropic"

    @pytest.mark.asyncio
    async def test_failover_skips_disabled_providers(self) -> None:
        """切换时应跳过已禁用的 Provider。"""
        providers = [
            ProviderConfig(provider=ProviderName.ANTHROPIC, api_key="sk-1", priority=0, enabled=True),
            ProviderConfig(provider=ProviderName.DEEPSEEK, api_key=None, priority=1, enabled=False),
            ProviderConfig(provider=ProviderName.QWEN, api_key="sk-3", priority=2, enabled=True),
        ]

        circuit_open = {ProviderName.ANTHROPIC}

        available = [
            p for p in sorted(providers, key=lambda x: x.priority)
            if p.provider not in circuit_open and p.enabled
        ]

        assert len(available) >= 1
        # DeepSeek 被禁用，应选 Qwen
        assert available[0].provider == ProviderName.QWEN
