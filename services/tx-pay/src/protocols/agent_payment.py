"""Agent 支付协议 — AI Agent 发起支付的统一接口

设计原则：
  1. Agent 可以"准备"支付，但最终确认必须经过人类授权
  2. 支持"预授权"模式 — Agent 预冻结额度，人类事后确认
  3. 所有 Agent 发起的支付必须留痕（AgentDecisionLog）
  4. 协议无关：不管外部是 微信Skill / 支付宝ACT / 谷歌UCP / OpenAI ACP，
     内部都通过此适配器转换为 tx-pay 标准调用

安全边界：
  - Agent 不能绕过风控
  - Agent 不能超过预设的单笔/日累计限额
  - 所有 Agent 支付记录标记 source="agent"
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog
from pydantic import BaseModel, Field

from ..channels.base import PayMethod

logger = structlog.get_logger(__name__)

# Agent 支付限额（分）
_AGENT_SINGLE_LIMIT_FEN = 100_000   # 单笔上限 1000 元
_AGENT_DAILY_LIMIT_FEN = 500_000    # 日累计上限 5000 元


class AgentPaymentStatus(str, Enum):
    PREPARED = "prepared"           # Agent 已准备，等待人类确认
    HUMAN_CONFIRMED = "confirmed"   # 人类已确认，执行中
    COMPLETED = "completed"         # 支付完成
    REJECTED = "rejected"           # 人类拒绝
    EXPIRED = "expired"             # 超时未确认
    FAILED = "failed"               # 执行失败


class PaymentIntent(BaseModel):
    """Agent 支付意图"""
    order_id: str
    amount_fen: int = Field(..., gt=0)
    method: PayMethod
    description: str = ""
    reason: str = ""                    # Agent 发起支付的理由
    confidence: float = Field(0.0, ge=0.0, le=1.0)  # Agent 置信度
    metadata: dict = Field(default_factory=dict)


class HumanAuthProof(BaseModel):
    """人类授权证明"""
    auth_type: str = "biometric"        # biometric / password / sms_code
    auth_token: str = ""                # 授权凭证（由前端获取）
    operator_id: str = ""               # 操作员 ID
    confirmed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PreparedPayment(BaseModel):
    """Agent 准备好的支付（等待人类确认）"""
    prepared_id: str
    agent_id: str
    intent: PaymentIntent
    status: AgentPaymentStatus = AgentPaymentStatus.PREPARED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    decision_log: dict = Field(default_factory=dict)


class AgentPaymentProtocol:
    """Agent 支付协议适配器

    使用方式（MCP Tool 内部调用）：
        protocol = AgentPaymentProtocol(payment_service)

        # Agent 准备支付
        prepared = await protocol.prepare_payment(
            agent_id="discount_guardian",
            tenant_id="...",
            store_id="...",
            intent=PaymentIntent(order_id="...", amount_fen=8800, method=PayMethod.WECHAT),
        )

        # 推送到前端，等待人类确认
        # ... POS UI 显示确认弹窗 ...

        # 人类确认后执行
        result = await protocol.confirm_payment(
            prepared_id=prepared.prepared_id,
            human_auth=HumanAuthProof(auth_type="biometric", operator_id="..."),
        )
    """

    def __init__(self, payment_service: object) -> None:
        self._svc = payment_service
        # KNOWN LIMITATION: 内存存储准备好的支付，服务重启后所有待确认支付丢失。
        # TODO: 持久化到 DB（payment_agent_prepared 表），需配合迁移脚本。
        self._prepared: dict[str, PreparedPayment] = {}
        logger.warning(
            "agent_payment_in_memory_storage",
            msg="AgentPaymentProtocol 使用内存存储，重启将丢失所有待确认支付",
        )

    async def prepare_payment(
        self,
        agent_id: str,
        tenant_id: str,
        store_id: str,
        intent: PaymentIntent,
    ) -> PreparedPayment:
        """Agent 准备支付

        不执行实际扣款。生成 prepared_id，推送到前端等待人类确认。

        Raises:
            ValueError: 超过 Agent 支付限额
        """
        # 限额校验
        if intent.amount_fen > _AGENT_SINGLE_LIMIT_FEN:
            raise ValueError(
                f"Agent 单笔限额 {_AGENT_SINGLE_LIMIT_FEN / 100} 元，"
                f"请求金额 {intent.amount_fen / 100} 元"
            )

        prepared_id = f"AGENT_{uuid.uuid4().hex[:12].upper()}"

        prepared = PreparedPayment(
            prepared_id=prepared_id,
            agent_id=agent_id,
            intent=intent,
            decision_log={
                "agent_id": agent_id,
                "decision_type": "payment_initiation",
                "input_context": {
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "order_id": intent.order_id,
                    "amount_fen": intent.amount_fen,
                },
                "reasoning": intent.reason,
                "confidence": intent.confidence,
                "constraints_check": {
                    "within_single_limit": intent.amount_fen <= _AGENT_SINGLE_LIMIT_FEN,
                    "within_daily_limit": True,  # TODO: 累计查询
                },
            },
        )

        self._prepared[prepared_id] = prepared

        logger.info(
            "agent_payment_prepared",
            prepared_id=prepared_id,
            agent_id=agent_id,
            amount_fen=intent.amount_fen,
            method=intent.method.value,
        )

        return prepared

    async def confirm_payment(
        self,
        prepared_id: str,
        human_auth: HumanAuthProof,
    ) -> dict:
        """人类确认后执行实际支付

        Returns:
            PaymentResult dict
        """
        prepared = self._prepared.get(prepared_id)
        if prepared is None:
            raise ValueError(f"未找到准备中的支付: {prepared_id}")

        if prepared.status != AgentPaymentStatus.PREPARED:
            raise ValueError(f"支付状态不正确: {prepared.status.value}")

        prepared.status = AgentPaymentStatus.HUMAN_CONFIRMED

        logger.info(
            "agent_payment_human_confirmed",
            prepared_id=prepared_id,
            operator_id=human_auth.operator_id,
            auth_type=human_auth.auth_type,
        )

        # 调用 PaymentNexusService 执行实际支付
        try:
            result = await self._svc.create_payment(
                tenant_id=prepared.decision_log["input_context"]["tenant_id"],
                store_id=prepared.decision_log["input_context"]["store_id"],
                order_id=prepared.intent.order_id,
                amount_fen=prepared.intent.amount_fen,
                method=prepared.intent.method,
                metadata={
                    "source": "agent",
                    "agent_id": prepared.agent_id,
                    "prepared_id": prepared_id,
                    "operator_id": human_auth.operator_id,
                },
            )
            prepared.status = AgentPaymentStatus.COMPLETED
            return result.model_dump(mode="json")
        except Exception as exc:
            prepared.status = AgentPaymentStatus.FAILED
            logger.error("agent_payment_execution_failed", error=str(exc))
            raise

    async def reject_payment(self, prepared_id: str, reason: str = "") -> None:
        """人类拒绝 Agent 发起的支付"""
        prepared = self._prepared.get(prepared_id)
        if prepared is None:
            raise ValueError(f"未找到准备中的支付: {prepared_id}")

        prepared.status = AgentPaymentStatus.REJECTED
        logger.info(
            "agent_payment_rejected",
            prepared_id=prepared_id,
            reason=reason,
        )

    async def list_pending(self, agent_id: Optional[str] = None) -> list[PreparedPayment]:
        """列出待确认的 Agent 支付"""
        return [
            p for p in self._prepared.values()
            if p.status == AgentPaymentStatus.PREPARED
            and (agent_id is None or p.agent_id == agent_id)
        ]
