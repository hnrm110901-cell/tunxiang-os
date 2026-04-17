"""
PromptAuditLog 模型 — D6 AI 决策层 LLM 调用审计

每次 LLMGateway.chat() 调用写一条记录，用于：
  - 合规审计（谁、在什么时候、调了哪个模型、多贵）
  - 安全回溯（input_risk_score 高的请求、output_flags 有泄露的请求）
  - 成本归因（tokens / cost_fen 按 provider 汇总）

注意：不保存原始 prompt 明文（只留 hash），避免 PII 落盘。
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from .base import Base


class PromptAuditLog(Base):
    """LLM Prompt 审计日志"""

    __tablename__ = "prompt_audit_logs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 请求追踪
    request_id = Column(String(64), nullable=False, index=True, comment="本次调用唯一ID（贯穿网关）")
    user_id = Column(String(64), nullable=True, index=True, comment="调用方用户ID（可空，系统内部调用）")

    # 输入侧
    input_hash = Column(String(64), nullable=False, comment="输入内容 SHA256 前 32 字符（不保存原文）")
    input_risk_score = Column(Integer, default=0, nullable=False, comment="prompt injection 风险分 0-100")

    # 输出侧
    output_flags = Column(JSONB, default=list, nullable=False, comment="输出泄露标志 [API_KEY, SECRET, ...]")

    # 性能与成本
    duration_ms = Column(Integer, default=0, nullable=False, comment="端到端耗时（毫秒）")
    tokens_in = Column(Integer, default=0, nullable=False, comment="输入 token 数")
    tokens_out = Column(Integer, default=0, nullable=False, comment="输出 token 数")
    cost_fen = Column(Integer, default=0, nullable=False, comment="成本（分），按 provider 单价计算")

    # 实际落地的 provider
    provider = Column(String(32), nullable=True, comment="实际命中的 provider: claude/deepseek/openai")
    model = Column(String(64), nullable=True, comment="实际使用的模型 ID")

    # 时间戳
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_prompt_audit_created", "created_at"),
        Index("idx_prompt_audit_user_created", "user_id", "created_at"),
    )
