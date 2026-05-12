"""ModelRouter ``system`` 字段脱敏 — CSO 2026-05-11 F#5 audit S4 follow-up。

副发现：``DataSecurityGateway.mask_messages`` 只覆盖 ``messages`` 数组，
``system`` 字段过去直接 pipe 给 adapter。即使 brand_strategy 已做 sanitize（PR #458）
+ XML 隔离（PR #477）+ Pydantic 长度上限（PR #481），若仍有敏感字段（手机号 /
身份证 / 大额）从 brand 字段渗入 system_prompt，会绕过 mask 直达 Provider。

覆盖：
  1. system 含敏感字段（手机 / 身份证 / 大额金额）→ adapter 收到 masked 版本
  2. system=None → 无 mask 操作，adapter 收到 None，无 crash
  3. mask_ctx 共享 — messages + system 的脱敏 token 同属一份 ctx，可统一 unmask
  4. regression：messages mask 路径仍然工作（不破现有）
  5. stream_complete 同样 mask system 字段

运行方式：
    pytest shared/ai_providers/tests/test_router_system_mask.py -xvs
"""

from __future__ import annotations

from typing import AsyncGenerator, Optional

import pytest

from shared.ai_providers.router import MultiProviderRouter, TaskRoutingStrategy
from shared.ai_providers.security import DataSecurityGateway
from shared.ai_providers.types import (
    LLMResponse,
    ModelPricing,
    ProviderHealth,
    ProviderName,
)


class _CapturingAdapter:
    """Mock adapter，捕获 ``system`` 入参用于断言。

    实现 ``ProviderAdapter`` Protocol 的最小子集。
    """

    def __init__(self, response_text: str = "ok") -> None:
        self._response_text = response_text
        self.last_system: Optional[str] = None
        self.last_messages: Optional[list[dict[str, str]]] = None
        self.complete_calls: int = 0
        self.stream_calls: int = 0

    @property
    def name(self) -> ProviderName:
        return ProviderName.DEEPSEEK

    @property
    def available_models(self) -> list:  # type: ignore[type-arg]
        return []

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout_s: int = 30,
        tools: Optional[list[dict]] = None,
    ) -> LLMResponse:
        self.complete_calls += 1
        self.last_system = system
        self.last_messages = messages
        return LLMResponse(
            text=self._response_text,
            provider=ProviderName.DEEPSEEK,
            model_id=model,
            input_tokens=10,
            output_tokens=5,
            cost_rmb=0.0001,
            duration_ms=1,
            request_id="req-fake",
            finish_reason="stop",
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        tools: Optional[list[dict]] = None,
    ) -> AsyncGenerator[str, None]:
        self.stream_calls += 1
        self.last_system = system
        self.last_messages = messages
        for chunk in [self._response_text]:
            yield chunk

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(provider=ProviderName.DEEPSEEK, is_available=True)

    def get_pricing(self, model: str) -> ModelPricing:
        return ModelPricing(input_rmb_per_million=1.0, output_rmb_per_million=2.0)


def _make_router(adapter: _CapturingAdapter) -> MultiProviderRouter:
    """构造一个最小可用的 MultiProviderRouter（含真实 DataSecurityGateway）。"""
    return MultiProviderRouter(
        adapters={"deepseek": adapter},  # type: ignore[dict-item]
        security_gateway=DataSecurityGateway(),
        routing_strategy=TaskRoutingStrategy(),
        max_retries=0,
        retry_delays=[],
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. system 含敏感字段 → adapter 收到 masked 版本
# ─────────────────────────────────────────────────────────────────────────────


class TestSystemFieldMasked:
    """system 字段中的敏感字段应在 adapter 调用前被 mask。"""

    @pytest.mark.asyncio
    async def test_system_phone_number_masked_in_adapter_call(self) -> None:
        """system 中含手机号时，adapter.complete 收到的 system 不应含原始号码。"""
        adapter = _CapturingAdapter()
        router = _make_router(adapter)

        sensitive_system = "你是品牌助手。联系电话 13812345678 是商户主联系人。"
        await router.complete(
            tenant_id="t-001",
            task_type="quick_classification",
            messages=[{"role": "user", "content": "测试消息"}],
            system=sensitive_system,
        )

        assert adapter.last_system is not None
        assert "13812345678" not in adapter.last_system, (
            f"adapter 收到了未脱敏的手机号: {adapter.last_system}"
        )
        assert "TX_PHONE_" in adapter.last_system, (
            f"adapter system 应包含脱敏 token: {adapter.last_system}"
        )

    @pytest.mark.asyncio
    async def test_system_id_card_masked_in_adapter_call(self) -> None:
        """system 中含身份证时应被脱敏。"""
        adapter = _CapturingAdapter()
        router = _make_router(adapter)

        await router.complete(
            tenant_id="t-002",
            task_type="quick_classification",
            messages=[{"role": "user", "content": "查询"}],
            system="法人身份证：430121199901011234，负责审核。",
        )

        assert adapter.last_system is not None
        assert "430121199901011234" not in adapter.last_system
        assert "TX_IDCARD_" in adapter.last_system

    @pytest.mark.asyncio
    async def test_system_large_amount_masked(self) -> None:
        """system 中含大额金额（¥10,000 以上）应被脱敏。"""
        adapter = _CapturingAdapter()
        router = _make_router(adapter)

        await router.complete(
            tenant_id="t-003",
            task_type="quick_classification",
            messages=[{"role": "user", "content": "测试"}],
            system="商户押金 ¥50,000，毛利底线 ¥15,000。",
        )

        assert adapter.last_system is not None
        # 大额金额应被替换
        assert "TX_AMOUNT_" in adapter.last_system, (
            f"大额金额未脱敏: {adapter.last_system}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. system=None 安全路径
# ─────────────────────────────────────────────────────────────────────────────


class TestSystemNoneSafe:
    """system=None 时应无 mask 操作，无 crash。"""

    @pytest.mark.asyncio
    async def test_system_none_passes_through(self) -> None:
        """system=None 时 adapter 应收到 None，无异常。"""
        adapter = _CapturingAdapter()
        router = _make_router(adapter)

        await router.complete(
            tenant_id="t-100",
            task_type="quick_classification",
            messages=[{"role": "user", "content": "你好"}],
            system=None,
        )

        assert adapter.complete_calls == 1
        assert adapter.last_system is None

    @pytest.mark.asyncio
    async def test_system_default_none(self) -> None:
        """不传 system 参数（默认 None）时应正常工作。"""
        adapter = _CapturingAdapter()
        router = _make_router(adapter)

        await router.complete(
            tenant_id="t-101",
            task_type="quick_classification",
            messages=[{"role": "user", "content": "你好"}],
        )

        assert adapter.last_system is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. mask_ctx 共享：messages + system 同 ctx
# ─────────────────────────────────────────────────────────────────────────────


class TestMaskContextShared:
    """messages 和 system 的脱敏应共享同一 MaskContext。"""

    def test_mask_system_shares_ctx_with_mask_messages(self) -> None:
        """mask_system 复用 mask_messages 产生的 ctx，token 编号连续，敏感级别合并。"""
        gateway = DataSecurityGateway()
        messages = [{"role": "user", "content": "客户手机 13912345678"}]
        system = "运维联系 13800001111 处理工单。"

        masked_msgs, ctx = gateway.mask_messages(messages, tenant_id="t-share")
        masked_sys = gateway.mask_system(system, ctx)

        # 两个手机号都应在同一 ctx.tokens 中
        phone_tokens = [t for t in ctx.tokens if t.category == "phone"]
        assert len(phone_tokens) == 2, (
            f"预期 2 个 phone token，实际 {len(phone_tokens)}: {[t.original for t in ctx.tokens]}"
        )
        originals = {t.original for t in phone_tokens}
        assert originals == {"13912345678", "13800001111"}

        # masked 文本不再包含原始号码
        assert "13912345678" not in masked_msgs[0]["content"]
        assert masked_sys is not None
        assert "13800001111" not in masked_sys

        # unmask 还原应同时还原两段
        restored_sys = gateway.unmask_text(masked_sys, ctx)
        assert "13800001111" in restored_sys
        restored_msg = gateway.unmask_text(masked_msgs[0]["content"], ctx)
        assert "13912345678" in restored_msg

    def test_mask_system_none_returns_none(self) -> None:
        """mask_system(None, ctx) 应返回 None，不改 ctx。"""
        gateway = DataSecurityGateway()
        ctx = gateway.mask_messages([{"role": "user", "content": "x"}], "t-1")[1]
        token_count_before = len(ctx.tokens)

        result = gateway.mask_system(None, ctx)

        assert result is None
        assert len(ctx.tokens) == token_count_before  # ctx 未被修改


# ─────────────────────────────────────────────────────────────────────────────
# 4. Regression：messages mask 路径未被破坏
# ─────────────────────────────────────────────────────────────────────────────


class TestMessagesMaskRegression:
    """确认 system 字段 mask 改动未破坏现有 messages mask 路径。"""

    @pytest.mark.asyncio
    async def test_messages_phone_still_masked(self) -> None:
        """messages 中的手机号仍应被脱敏（原有行为）。"""
        adapter = _CapturingAdapter()
        router = _make_router(adapter)

        await router.complete(
            tenant_id="t-reg-1",
            task_type="quick_classification",
            messages=[{"role": "user", "content": "请回访 13700001234"}],
        )

        assert adapter.last_messages is not None
        sent_content = adapter.last_messages[0]["content"]
        assert "13700001234" not in sent_content
        assert "TX_PHONE_" in sent_content

    @pytest.mark.asyncio
    async def test_unmask_restores_response_text(self) -> None:
        """LLM 响应中的脱敏 token 仍应被还原（router 调用方收到原值）。"""
        # 让 adapter 把 messages 中的 token 原样回显
        adapter = _CapturingAdapter()
        router = _make_router(adapter)

        # 把回显设为返回 messages 中第一个 token
        async def _capture_and_echo(
            messages: list[dict[str, str]],
            model: str,
            *,
            system: Optional[str] = None,
            max_tokens: int = 1024,
            temperature: float = 0.0,
            timeout_s: int = 30,
            tools: Optional[list[dict]] = None,
        ) -> LLMResponse:
            adapter.complete_calls += 1
            adapter.last_system = system
            adapter.last_messages = messages
            # 回显消息内容（含脱敏 token）
            return LLMResponse(
                text=messages[0]["content"],
                provider=ProviderName.DEEPSEEK,
                model_id=model,
                input_tokens=1,
                output_tokens=1,
                cost_rmb=0.0,
                duration_ms=1,
                request_id="r",
            )

        adapter.complete = _capture_and_echo  # type: ignore[method-assign]

        resp = await router.complete(
            tenant_id="t-reg-2",
            task_type="quick_classification",
            messages=[{"role": "user", "content": "回电 13911112222"}],
        )

        # router 应已 unmask，调用方看到原始号码
        assert "13911112222" in resp.text


# ─────────────────────────────────────────────────────────────────────────────
# 5. stream_complete 同样 mask system
# ─────────────────────────────────────────────────────────────────────────────


class TestStreamCompleteSystemMask:
    """stream_complete 也应 mask system 字段。"""

    @pytest.mark.asyncio
    async def test_stream_system_phone_masked(self) -> None:
        """stream_complete 时 adapter.stream 收到的 system 应已脱敏。"""
        adapter = _CapturingAdapter()
        router = _make_router(adapter)

        chunks: list[str] = []
        async for chunk in router.stream_complete(
            tenant_id="t-stream-1",
            task_type="quick_classification",
            messages=[{"role": "user", "content": "测试"}],
            system="紧急联系 13600006666。",
        ):
            chunks.append(chunk)

        assert adapter.stream_calls == 1
        assert adapter.last_system is not None
        assert "13600006666" not in adapter.last_system
        assert "TX_PHONE_" in adapter.last_system

    @pytest.mark.asyncio
    async def test_stream_system_none_safe(self) -> None:
        """stream_complete 在 system=None 时应正常工作。"""
        adapter = _CapturingAdapter()
        router = _make_router(adapter)

        chunks: list[str] = []
        async for chunk in router.stream_complete(
            tenant_id="t-stream-2",
            task_type="quick_classification",
            messages=[{"role": "user", "content": "hi"}],
            system=None,
        ):
            chunks.append(chunk)

        assert adapter.stream_calls == 1
        assert adapter.last_system is None


# ─────────────────────────────────────────────────────────────────────────────
# 6. security_gateway=None 时透传（防御性）
# ─────────────────────────────────────────────────────────────────────────────


class TestNoGatewayPassthrough:
    """security_gateway=None 时应原样透传 system，不 mask。"""

    @pytest.mark.asyncio
    async def test_no_gateway_system_unchanged(self) -> None:
        """无 gateway 时 adapter 应收到原始 system（兼容旧路径）。"""
        adapter = _CapturingAdapter()
        # 不传 security_gateway
        router = MultiProviderRouter(
            adapters={"deepseek": adapter},  # type: ignore[dict-item]
            security_gateway=None,
            routing_strategy=TaskRoutingStrategy(),
            max_retries=0,
            retry_delays=[],
        )

        raw_system = "电话 13822223333（不会被 mask，因为 gateway=None）"
        await router.complete(
            tenant_id="t-nogw",
            task_type="quick_classification",
            messages=[{"role": "user", "content": "x"}],
            system=raw_system,
        )

        assert adapter.last_system == raw_system
