"""数据安全网关 — 所有 LLM 请求的必经之路。

职责：
  1. 数据分级：根据内容自动判定敏感级别
  2. 请求脱敏：PII/商业敏感数据 → Token化替换
  3. 响应还原：Token → 真实数据
  4. Provider 权限校验：确保数据不发往无权限的 Provider
  5. 审计日志：所有出境数据可追溯

遵循：
  - 《个人信息保护法》(PIPL)
  - 《数据安全法》
  - 屯象OS CLAUDE.md 安全规范
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import structlog

from .types import DataSensitivity  # 统一使用 types.py 中的定义，避免重复

logger = structlog.get_logger()


# Provider 数据权限矩阵
PROVIDER_DATA_CLEARANCE: dict[str, list[DataSensitivity]] = {
    "coreml": [DataSensitivity.PUBLIC, DataSensitivity.INTERNAL, DataSensitivity.SENSITIVE, DataSensitivity.RESTRICTED],
    "deepseek": [DataSensitivity.PUBLIC, DataSensitivity.INTERNAL, DataSensitivity.SENSITIVE],
    "qwen": [DataSensitivity.PUBLIC, DataSensitivity.INTERNAL, DataSensitivity.SENSITIVE],
    "glm": [DataSensitivity.PUBLIC, DataSensitivity.INTERNAL, DataSensitivity.SENSITIVE],
    "ernie": [DataSensitivity.PUBLIC, DataSensitivity.INTERNAL, DataSensitivity.SENSITIVE],
    "kimi": [DataSensitivity.PUBLIC, DataSensitivity.INTERNAL, DataSensitivity.SENSITIVE],
    "anthropic": [DataSensitivity.PUBLIC, DataSensitivity.INTERNAL],  # 境外，仅非敏感
}


@dataclass
class MaskToken:
    """脱敏令牌：记录原始值和替换令牌的映射。"""

    token: str  # 替换后的令牌，如 [TX_PHONE_a1b2_001]
    original: str  # 原始值
    category: str  # 脱敏类别：phone/id_card/bank_card/amount/name
    position: tuple[int, int] = (0, 0)  # 在原文中的位置


@dataclass
class MaskContext:
    """脱敏上下文：保存单次请求的所有脱敏映射，用于响应还原。"""

    request_id: str
    tokens: list[MaskToken] = field(default_factory=list)
    sensitivity_level: DataSensitivity = DataSensitivity.PUBLIC
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        # 确保 request_id 至少 4 字符，用于生成唯一脱敏 token
        if len(self.request_id) < 4:
            self.request_id = self.request_id.ljust(4, "0")

    @property
    def short_id(self) -> str:
        """request_id 前 4 位，用于脱敏 token 命名空间。"""
        return self.request_id[:4]

    def add_token(self, token: MaskToken) -> None:
        self.tokens.append(token)
        # 自动提升敏感级别
        category_sensitivity = {
            "phone": DataSensitivity.SENSITIVE,
            "id_card": DataSensitivity.SENSITIVE,
            "bank_card": DataSensitivity.SENSITIVE,
            "amount": DataSensitivity.INTERNAL,
            "name": DataSensitivity.INTERNAL,
            "store_name": DataSensitivity.INTERNAL,
            "address": DataSensitivity.SENSITIVE,
            "email": DataSensitivity.SENSITIVE,
        }
        level = category_sensitivity.get(token.category, DataSensitivity.INTERNAL)
        if list(DataSensitivity).index(level) > list(DataSensitivity).index(self.sensitivity_level):
            self.sensitivity_level = level


@dataclass
class AuditEntry:
    """审计日志条目。"""

    request_id: str
    tenant_id: str
    provider: str
    sensitivity_level: str
    masked_fields_count: int
    categories: list[str]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    blocked: bool = False
    block_reason: Optional[str] = None


class DataSecurityGateway:
    """数据安全网关。

    使用示例：
        gateway = DataSecurityGateway()
        # 脱敏
        masked_messages, ctx = gateway.mask_messages(messages, tenant_id="...")
        # 检查是否可发往目标 Provider
        gateway.check_provider_clearance("anthropic", ctx)
        # 调用 LLM...
        # 还原响应中的令牌
        restored_text = gateway.unmask_text(response_text, ctx)
    """

    # ── 脱敏正则规则 ──────────────────────────────────────────────────────────

    MASK_PATTERNS: list[tuple[str, str, re.Pattern]] = [
        # (category, token_prefix, regex_pattern)
        ("phone", "PHONE", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
        ("id_card", "IDCARD", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
        ("bank_card", "BANKCARD", re.compile(r"(?<!\d)\d{16,19}(?!\d)")),
        ("email", "EMAIL", re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")),
        ("address", "ADDR", re.compile(r"[\u4e00-\u9fa5]{2,}(省|市|区|县|镇|乡|路|街|号|栋|单元|室|楼)")),
    ]

    # 大额金额模式（¥10,000 以上）
    AMOUNT_PATTERN = re.compile(r"¥\s*[\d,]+\.?\d*")
    AMOUNT_THRESHOLD = 10_000

    def __init__(self, custom_rules: Optional[list[tuple[str, str, re.Pattern]]] = None):
        self._custom_rules = custom_rules or []
        self._audit_log: list[AuditEntry] = []

    # ── 核心：脱敏 ──────────────────────────────────────────────────────────

    def mask_text(self, text: str, ctx: MaskContext) -> str:
        """对单段文本执行脱敏。

        Args:
            text: 原始文本
            ctx:  脱敏上下文（会被修改，追加令牌映射）

        Returns:
            脱敏后的文本
        """
        masked = text
        counter: dict[str, int] = {}

        all_patterns = self.MASK_PATTERNS + self._custom_rules

        for category, prefix, pattern in all_patterns:
            for match in pattern.finditer(masked):
                original = match.group()
                count = counter.get(category, 0) + 1
                counter[category] = count
                token_str = f"[TX_{prefix}_{ctx.short_id}_{count:03d}]"

                mask_token = MaskToken(
                    token=token_str,
                    original=original,
                    category=category,
                    position=(match.start(), match.end()),
                )
                ctx.add_token(mask_token)
                masked = masked.replace(original, token_str, 1)

        # 大额金额脱敏
        for match in self.AMOUNT_PATTERN.finditer(masked):
            amount_str = match.group()
            try:
                amount_val = float(amount_str.replace("¥", "").replace(",", "").strip())
                if amount_val >= self.AMOUNT_THRESHOLD:
                    count = counter.get("amount", 0) + 1
                    counter["amount"] = count
                    token_str = f"[TX_AMOUNT_{ctx.short_id}_{count:03d}]"
                    ctx.add_token(
                        MaskToken(
                            token=token_str,
                            original=amount_str,
                            category="amount",
                        )
                    )
                    masked = masked.replace(amount_str, token_str, 1)
            except ValueError:
                pass

        return masked

    def mask_messages(
        self,
        messages: list[dict[str, str]],
        tenant_id: str,
    ) -> tuple[list[dict[str, str]], MaskContext]:
        """对消息列表执行脱敏。

        Args:
            messages:  消息列表，格式 [{"role": "...", "content": "..."}]
            tenant_id: 租户 ID（审计用）

        Returns:
            (脱敏后的消息列表, 脱敏上下文)
        """
        ctx = MaskContext(request_id=str(uuid.uuid4()))
        masked_messages = []

        for msg in messages:
            masked_msg = dict(msg)
            if "content" in msg and isinstance(msg["content"], str):
                masked_msg["content"] = self.mask_text(msg["content"], ctx)
            masked_messages.append(masked_msg)

        logger.info(
            "data_security_mask_complete",
            request_id=ctx.request_id,
            tenant_id=tenant_id,
            sensitivity=ctx.sensitivity_level.value,
            masked_count=len(ctx.tokens),
            categories=list({t.category for t in ctx.tokens}),
        )

        return masked_messages, ctx

    # ── 核心：还原 ──────────────────────────────────────────────────────────

    def unmask_text(self, text: str, ctx: MaskContext) -> str:
        """将响应文本中的令牌还原为原始值。

        Args:
            text: LLM 响应文本（可能包含脱敏令牌）
            ctx:  脱敏上下文

        Returns:
            还原后的文本
        """
        restored = text
        for token in ctx.tokens:
            restored = restored.replace(token.token, token.original)
        return restored

    # ── Provider 权限检查 ──────────────────────────────────────────────────

    def check_provider_clearance(
        self,
        provider_name: str,
        ctx: MaskContext,
    ) -> bool:
        """检查目标 Provider 是否有权处理当前敏感级别的数据。

        Args:
            provider_name: Provider 标识（如 "anthropic", "deepseek"）
            ctx:           脱敏上下文

        Returns:
            True 表示允许，False 表示拒绝

        Raises:
            PermissionError: 当数据敏感级别超出 Provider 权限时
        """
        allowed = PROVIDER_DATA_CLEARANCE.get(provider_name, [])

        if ctx.sensitivity_level not in allowed:
            msg = (
                f"数据安全拦截：{provider_name} 无权处理 {ctx.sensitivity_level.value} 级别数据。"
                f" 已脱敏字段: {len(ctx.tokens)} 个, 类别: {[t.category for t in ctx.tokens]}"
            )
            logger.warning(
                "data_security_blocked",
                provider=provider_name,
                sensitivity=ctx.sensitivity_level.value,
                reason=msg,
            )
            self._audit_log.append(
                AuditEntry(
                    request_id=ctx.request_id,
                    tenant_id="",
                    provider=provider_name,
                    sensitivity_level=ctx.sensitivity_level.value,
                    masked_fields_count=len(ctx.tokens),
                    categories=[t.category for t in ctx.tokens],
                    blocked=True,
                    block_reason=msg,
                )
            )
            raise PermissionError(msg)

        return True

    # ── 自动检测数据敏感级别 ──────────────────────────────────────────────

    def detect_sensitivity(self, text: str) -> DataSensitivity:
        """快速检测文本的数据敏感级别（不执行脱敏）。"""
        ctx = MaskContext(request_id="detect")
        self.mask_text(text, ctx)
        return ctx.sensitivity_level

    # ── 审计日志 ──────────────────────────────────────────────────────────

    def record_audit(
        self,
        ctx: MaskContext,
        tenant_id: str,
        provider_name: str,
    ) -> AuditEntry:
        """记录审计日志。"""
        entry = AuditEntry(
            request_id=ctx.request_id,
            tenant_id=tenant_id,
            provider=provider_name,
            sensitivity_level=ctx.sensitivity_level.value,
            masked_fields_count=len(ctx.tokens),
            categories=list({t.category for t in ctx.tokens}),
        )
        self._audit_log.append(entry)
        return entry

    def get_audit_log(self) -> list[AuditEntry]:
        """获取审计日志（内存存储，生产环境应写入 DB）。"""
        return list(self._audit_log)
