"""MCP 支付工具定义 — 注册到 MCP Server 的支付能力

这些工具会被注入到 services/mcp-server/src/agent_registry.py 中，
使任何 AI Agent（Claude/ChatGPT/Cursor/钉钉AI 等）都能调用支付能力。

工具分级：
  - 只读工具（无副作用）：query / summary / status → Agent 可自由调用
  - 准备工具（预授权）：prepare → Agent 可调用，但不扣款
  - 执行工具（有副作用）：confirm / refund → 必须经过人类确认

安全规则：
  - 所有执行类工具必须带 human_auth_required=True
  - Agent 单笔限额 1000 元，日累计 5000 元
  - 所有调用留痕到 AgentDecisionLog
"""
from __future__ import annotations

# MCP 工具注册表 — 供 mcp-server/src/agent_registry.py 导入
PAYMENT_MCP_TOOLS: dict[str, dict] = {

    # ─── 只读工具（Agent 可自由调用） ─────────────────────────

    "payment__query_status": {
        "agent_id": "payment_nexus",
        "description": "查询支付状态。输入 payment_id，返回支付方式、金额、状态、第三方流水号。",
        "params": {
            "payment_id": {"type": "string", "description": "支付单号", "required": True},
        },
        "endpoint": "POST /api/v1/pay/query",
        "service_url": "http://localhost:8013",
        "human_auth_required": False,
    },

    "payment__daily_summary": {
        "agent_id": "payment_nexus",
        "description": "获取门店当日支付汇总，按支付方式分组（微信/支付宝/现金/储值/挂账），含手续费计算。",
        "params": {
            "store_id": {"type": "string", "description": "门店ID", "required": True},
            "summary_date": {"type": "string", "description": "日期 YYYY-MM-DD（默认今天）", "required": False},
        },
        "endpoint": "GET /api/v1/pay/daily-summary",
        "service_url": "http://localhost:8013",
        "human_auth_required": False,
    },

    "payment__list_channels": {
        "agent_id": "payment_nexus",
        "description": "列出当前已注册的所有支付渠道及其支持的支付方式。用于诊断渠道配置问题。",
        "params": {},
        "endpoint": "GET /api/v1/pay/admin/channels",
        "service_url": "http://localhost:8013",
        "human_auth_required": False,
    },

    "payment__list_pending_agent_payments": {
        "agent_id": "payment_nexus",
        "description": "列出所有等待人类确认的 Agent 发起的支付请求。用于 POS 端展示确认弹窗。",
        "params": {
            "agent_id": {"type": "string", "description": "筛选特定 Agent（可选）", "required": False},
        },
        "endpoint": "GET /api/v1/pay/agent/pending",
        "service_url": "http://localhost:8013",
        "human_auth_required": False,
    },

    # ─── 准备工具（预授权，不扣款） ──────────────────────────

    "payment__prepare": {
        "agent_id": "payment_nexus",
        "description": (
            "Agent 准备一笔支付（不扣款）。生成 prepared_id 后推送到 POS 端，"
            "等待收银员确认。单笔上限 1000 元。"
        ),
        "params": {
            "order_id": {"type": "string", "description": "订单ID", "required": True},
            "amount_fen": {"type": "integer", "description": "金额（分）", "required": True},
            "method": {
                "type": "string",
                "description": "支付方式: wechat/alipay/cash/member_balance/credit_account",
                "required": True,
            },
            "reason": {"type": "string", "description": "Agent 发起支付的理由", "required": True},
        },
        "endpoint": "POST /api/v1/pay/agent/prepare",
        "service_url": "http://localhost:8013",
        "human_auth_required": False,  # 准备阶段不需要人类确认
    },

    # ─── 执行工具（必须人类确认） ─────────────────────────────

    "payment__confirm_agent": {
        "agent_id": "payment_nexus",
        "description": (
            "确认 Agent 准备的支付并执行实际扣款。"
            "必须由收银员通过生物识别/密码确认后才能调用。"
        ),
        "params": {
            "prepared_id": {"type": "string", "description": "Agent 准备的支付ID", "required": True},
            "operator_id": {"type": "string", "description": "操作员ID", "required": True},
            "auth_type": {"type": "string", "description": "认证方式: biometric/password/sms_code", "required": True},
        },
        "endpoint": "POST /api/v1/pay/agent/confirm",
        "service_url": "http://localhost:8013",
        "human_auth_required": True,
    },

    "payment__refund": {
        "agent_id": "payment_nexus",
        "description": "发起退款。需要管理员审批（非 Agent 自主决策）。",
        "params": {
            "payment_id": {"type": "string", "description": "原支付单号", "required": True},
            "refund_amount_fen": {"type": "integer", "description": "退款金额（分）", "required": True},
            "reason": {"type": "string", "description": "退款原因", "required": True},
        },
        "endpoint": "POST /api/v1/pay/refund",
        "service_url": "http://localhost:8013",
        "human_auth_required": True,
    },
}


# ─── 协议适配器注册表（微信Skill/支付宝ACT/谷歌UCP/OpenAI ACP） ────

PROTOCOL_ADAPTERS: dict[str, dict] = {
    "wechat_skill": {
        "name": "微信支付 AI Skill",
        "status": "planned",       # planned / alpha / stable
        "description": "对接微信面向AI的支付技能包，支持 Agent 通过微信 Skill 协议发起支付。",
        "spec_url": "",
    },
    "alipay_act": {
        "name": "支付宝 ACT 智能体信任协议",
        "status": "planned",
        "description": "对接支付宝 Agentic Commerce Trust 协议，支持 Agent 间可信商业交互。",
        "spec_url": "",
    },
    "google_ucp": {
        "name": "Google Universal Commerce Protocol",
        "status": "planned",
        "description": "对接谷歌通用商务协议，支持 Agent 完成跨平台购物与支付。",
        "spec_url": "",
    },
    "openai_acp": {
        "name": "OpenAI Agent Commerce Protocol",
        "status": "planned",
        "description": "对接 OpenAI 智能体电商协议。",
        "spec_url": "",
    },
}
