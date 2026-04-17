"""
LLMGateway — 降级链 + 安全网关 + 审计日志 的统一入口

调用顺序：
  1. sanitize_input + scrub_pii（前置安全）
  2. 按 priority 顺序尝试 provider，每个 provider 3 次指数退避重试
  3. 任一 provider 成功立即返回；全部失败抛 LLMAllProvidersFailedError
  4. filter_output（后置安全）
  5. 写 PromptAuditLog（best-effort，DB 不可用不阻塞）
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from typing import Any, Dict, List, Optional

import structlog

from .base import LLMAllProvidersFailedError, LLMProvider, LLMProviderError
from .security import filter_output, sanitize_input, scrub_pii

logger = structlog.get_logger()

# 单个 provider 的重试参数
MAX_RETRIES = 3
BACKOFF_BASE = 0.5  # 秒


class LLMGateway:
    """LLM 治理网关（单例，线程安全）"""

    def __init__(
        self,
        providers: List[LLMProvider],
        timeout: float = 5.0,
        fallback_enabled: bool = True,
        security_enabled: bool = True,
    ):
        self.providers = providers
        self.timeout = timeout
        self.fallback_enabled = fallback_enabled
        self.security_enabled = security_enabled

    # ── 核心入口 ────────────────────────────────────────────────────────────

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        网关统一入口

        Returns:
            dict，在 provider chat 返回基础上附加：
              - request_id, input_risk_score, output_flags, duration_ms, fallback_chain
        """
        request_id = request_id or str(uuid.uuid4())
        start = time.perf_counter()

        # ── 前置安全 ─────────────────────────────────────────────────────────
        input_risk_score = 0
        cleaned_messages = messages
        if self.security_enabled:
            cleaned_messages, input_risk_score = self._preprocess(messages)

        # 计算 input hash（审计用，不保存原文）
        input_blob = (system or "") + "||".join(
            f"{m.get('role')}:{m.get('content', '')}" for m in cleaned_messages
        )
        input_hash = hashlib.sha256(input_blob.encode("utf-8")).hexdigest()[:32]

        # ── 降级链执行 ───────────────────────────────────────────────────────
        errors: Dict[str, str] = {}
        fallback_chain: List[str] = []
        response: Optional[Dict[str, Any]] = None

        for provider in self.providers:
            if not provider.is_available():
                errors[provider.name] = "not configured"
                continue
            fallback_chain.append(provider.name)
            try:
                response = await self._call_with_retry(
                    provider,
                    cleaned_messages,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                break  # 成功即跳出
            except LLMProviderError as e:
                errors[provider.name] = str(e)
                logger.warning(
                    "llm_provider_failed",
                    provider=provider.name,
                    error=str(e),
                    request_id=request_id,
                )
                if not self.fallback_enabled:
                    break

        if response is None:
            raise LLMAllProvidersFailedError(errors)

        # ── 后置安全（输出过滤）──────────────────────────────────────────────
        output_flags: List[str] = []
        if self.security_enabled:
            fr = filter_output(response.get("text", ""))
            response["text"] = fr.safe_text
            output_flags = fr.flags

        duration_ms = int((time.perf_counter() - start) * 1000)
        response.update(
            {
                "request_id": request_id,
                "input_risk_score": input_risk_score,
                "output_flags": output_flags,
                "duration_ms": duration_ms,
                "fallback_chain": fallback_chain,
            }
        )

        # ── 审计日志（best-effort）───────────────────────────────────────────
        await self._write_audit(
            request_id=request_id,
            user_id=user_id,
            input_hash=input_hash,
            input_risk_score=input_risk_score,
            output_flags=output_flags,
            duration_ms=duration_ms,
            tokens_in=response.get("tokens_in", 0),
            tokens_out=response.get("tokens_out", 0),
            provider=response.get("provider", ""),
            model=response.get("model", ""),
        )

        return response

    # ── 私有方法 ────────────────────────────────────────────────────────────

    def _preprocess(self, messages: List[Dict[str, Any]]):
        """逐条消息做 sanitize + scrub，返回 (cleaned, max_risk_score)"""
        max_risk = 0
        cleaned: List[Dict[str, Any]] = []
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str):
                sr = sanitize_input(content)
                max_risk = max(max_risk, sr.risk_score)
                scrubbed = scrub_pii(sr.cleaned)
                cleaned.append({**m, "content": scrubbed})
            else:
                # 多模态内容不处理（image/tool blocks）
                cleaned.append(m)
        return cleaned, max_risk

    async def _call_with_retry(
        self,
        provider: LLMProvider,
        messages: List[Dict[str, Any]],
        **kwargs,
    ) -> Dict[str, Any]:
        """单个 provider 调用 + 指数退避重试"""
        last_err: Optional[LLMProviderError] = None
        for attempt in range(MAX_RETRIES):
            try:
                return await provider.chat(messages, timeout=self.timeout, **kwargs)
            except LLMProviderError as e:
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
        assert last_err is not None
        raise last_err

    async def _write_audit(self, **fields) -> None:
        """写 PromptAuditLog（失败不阻塞主流程）"""
        try:
            from ...core.database import async_session_maker
            from ...models.prompt_audit_log import PromptAuditLog

            async with async_session_maker() as session:
                log = PromptAuditLog(
                    id=str(uuid.uuid4()),
                    request_id=fields.get("request_id"),
                    user_id=fields.get("user_id"),
                    input_hash=fields.get("input_hash"),
                    input_risk_score=fields.get("input_risk_score", 0),
                    output_flags=fields.get("output_flags", []),
                    duration_ms=fields.get("duration_ms", 0),
                    tokens_in=fields.get("tokens_in", 0),
                    tokens_out=fields.get("tokens_out", 0),
                    cost_fen=0,  # 成本计算后续补
                    provider=fields.get("provider"),
                    model=fields.get("model"),
                )
                session.add(log)
                await session.commit()
        except Exception as e:
            logger.warning("llm_audit_write_failed", error=str(e))
