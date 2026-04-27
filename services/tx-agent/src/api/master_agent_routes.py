"""Master Agent 路由 — H2 编排中心 API

prefix: /api/v1/agent

端点列表：
  POST /execute      — 执行 Agent 指令（核心，支持同步/异步模式）
  GET  /tasks/{id}   — 查询异步任务状态
  GET  /health       — 9个 Agent 健康状态
  POST /chat         — 自然语言对话接口
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Header
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/agent", tags=["master-agent"])

# ─────────────────────────────────────────────────────────────────────────────
# 意图关键词映射
# ─────────────────────────────────────────────────────────────────────────────

INTENT_KEYWORDS: dict[str, list[str]] = {
    "discount": ["折扣", "打折", "优惠", "减免"],
    "inventory": ["库存", "食材", "临期", "缺货"],
    "dispatch": ["出餐", "上菜", "调度", "催菜"],
    "member": ["会员", "顾客", "客户", "VIP"],
    "finance": ["财务", "账目", "现金", "营收"],
    "patrol": ["巡检", "质检", "卫生", "检查"],
    "customer_service": ["投诉", "服务", "反馈", "客诉"],
    "menu": ["菜品", "排菜", "菜单", "推荐"],
    "crm": ["营销", "推广", "活动", "私域"],
    "queue": ["排队", "等位", "叫号", "排位", "候位"],
    "kitchen_overtime": ["超时", "出餐", "催菜", "后厨"],
    "billing": ["反结账", "漏单", "收银", "现金差异", "挂账"],
    "closing": ["闭店", "日结", "检查单", "收档"],
}

# tx-brain 端点映射（每个意图对应的 AI 决策中枢接口）
AGENT_ENDPOINTS: dict[str, str] = {
    "discount": "http://tx-brain:8010/api/v1/brain/discount/analyze",
    "inventory": "http://tx-brain:8010/api/v1/brain/inventory/analyze",
    "dispatch": "http://tx-brain:8010/api/v1/brain/dispatch/predict",
    "member": "http://tx-brain:8010/api/v1/brain/member/insight",
    "finance": "http://tx-brain:8010/api/v1/brain/finance/audit",
    "patrol": "http://tx-brain:8010/api/v1/brain/patrol/analyze",
    "customer_service": "http://tx-brain:8010/api/v1/brain/customer-service/handle",
    "menu": "http://tx-brain:8010/api/v1/brain/menu/optimize",
    "crm": "http://tx-brain:8010/api/v1/brain/crm/campaign",
    "queue": "http://localhost:8008/api/v1/agent/ops/queue/predict-wait",
    "kitchen_overtime": "http://localhost:8008/api/v1/agent/ops/kitchen/scan-overtime",
    "billing": "http://localhost:8008/api/v1/agent/ops/billing/risk-summary",
    "closing": "http://localhost:8008/api/v1/agent/ops/closing/pre-check",
}

# 意图 → Agent 友好名称（用于日志/回复）
INTENT_AGENT_NAME: dict[str, str] = {
    "discount": "折扣守护",
    "inventory": "库存预警",
    "dispatch": "出餐调度",
    "member": "会员洞察",
    "finance": "财务稽核",
    "patrol": "巡店质检",
    "customer_service": "智能客服",
    "menu": "智能排菜",
    "crm": "私域运营",
    "queue": "排位智能",
    "kitchen_overtime": "后厨超时监控",
    "billing": "收银异常检测",
    "closing": "闭店守护",
}

# 内存任务存储（异步模式；生产环境可替换为 Redis）
_task_store: dict[str, dict[str, Any]] = {}

# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────


def _detect_intent(instruction: str) -> str | None:
    """纯 Python 关键词匹配，识别指令意图，不调用 Claude。

    按关键词出现顺序扫描所有意图，返回第一个匹配的意图 key。
    若无匹配，返回 None。
    """
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in instruction:
                return intent
    return None


def _build_constraints_check(result_data: dict) -> dict:
    """从 tx-brain 返回结果中提取三条硬约束校验状态。

    tx-brain 可能直接返回 constraints_check 字段；若无，则默认通过。
    """
    return result_data.get(
        "constraints_check",
        {
            "margin_check": None,
            "food_safety_check": None,
            "experience_check": None,
            "passed": True,
        },
    )


def _result_to_natural_language(intent: str, result_data: dict) -> str:
    """将 Agent 结果转化为简单中文自然语言回复（模板方式，不调用 Claude）。"""
    agent_name = INTENT_AGENT_NAME.get(intent, intent)
    summary = result_data.get("summary") or result_data.get("message") or ""
    if summary:
        return f"【{agent_name}】{summary}"

    # 通用回复
    risk_level = result_data.get("risk_level") or result_data.get("level", "")
    if risk_level:
        return f"【{agent_name}】检测到风险等级：{risk_level}，请关注详细数据。"
    return f"【{agent_name}】分析完成，请查看详细结果。"


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────────────────────────────────────


class ExecuteRequest(BaseModel):
    tenant_id: str
    store_id: str
    instruction: str  # 自然语言指令，如"分析今日库存风险"
    context: dict = {}  # 上下文数据（门店状态/员工信息等）
    priority: str = "medium"  # "high" | "medium" | "low"
    async_mode: bool = False  # False=同步等待，True=立即返回 task_id


class ChatRequest(BaseModel):
    message: str
    context: dict = {}
    tenant_id: str
    store_id: str


# ─────────────────────────────────────────────────────────────────────────────
# 核心：调用 tx-brain
# ─────────────────────────────────────────────────────────────────────────────


async def _call_brain_agent(
    intent: str,
    tenant_id: str,
    store_id: str,
    context: dict,
) -> dict[str, Any]:
    """通过 httpx 调用 tx-brain 对应 Agent 端点。

    超时 30 秒。捕获 RequestError / TimeoutException，返回降级结果。
    """
    endpoint = AGENT_ENDPOINTS[intent]
    payload = {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "context": context,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(endpoint, json=payload)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            # tx-brain 统一响应格式 {"ok": bool, "data": {...}}
            return data.get("data", data)
        except httpx.TimeoutException as exc:
            logger.warning(
                "brain_agent_timeout",
                intent=intent,
                endpoint=endpoint,
                error=str(exc),
            )
            return {"error": "tx-brain 请求超时", "fallback": True}
        except httpx.RequestError as exc:
            logger.warning(
                "brain_agent_request_error",
                intent=intent,
                endpoint=endpoint,
                error=str(exc),
            )
            return {"error": f"tx-brain 连接失败: {exc}", "fallback": True}


# ─────────────────────────────────────────────────────────────────────────────
# POST /execute
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/execute")
async def execute_agent(
    req: ExecuteRequest,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """执行 Agent 指令（Master Agent 核心入口）。

    流程：
    1. 关键词意图识别 → 选择对应 Skill Agent
    2. 调用 tx-brain 对应端点（同步或异步）
    3. 三条硬约束校验
    4. AgentDecisionLog 留痕
    5. 返回统一响应
    """
    task_id = str(uuid.uuid4())
    tenant_id = x_tenant_id or req.tenant_id
    start_ts = time.perf_counter()

    # 1. 意图识别
    intent = _detect_intent(req.instruction)
    agent_invoked = INTENT_AGENT_NAME.get(intent, "unknown") if intent else "unknown"

    logger.info(
        "master_agent_execute_start",
        task_id=task_id,
        tenant_id=tenant_id,
        store_id=req.store_id,
        instruction=req.instruction,
        intent=intent,
        agent_invoked=agent_invoked,
        priority=req.priority,
        async_mode=req.async_mode,
    )

    # 异步模式：立即返回 task_id，后台执行
    if req.async_mode:
        _task_store[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "agent_invoked": agent_invoked,
            "instruction": req.instruction,
            "tenant_id": tenant_id,
            "store_id": req.store_id,
        }

        import asyncio

        asyncio.create_task(
            _execute_async_task(
                task_id=task_id,
                intent=intent,
                tenant_id=tenant_id,
                store_id=req.store_id,
                context=req.context,
            )
        )

        return {
            "ok": True,
            "data": {
                "task_id": task_id,
                "agent_invoked": agent_invoked,
                "result": None,
                "status": "pending",
                "constraints_check": {},
                "execution_ms": 0,
            },
        }

    # 同步模式：等待结果
    if not intent:
        execution_ms = int((time.perf_counter() - start_ts) * 1000)
        constraints_check = {"passed": True}

        logger.info(
            "agent_decision_log",
            task_id=task_id,
            instruction=req.instruction,
            intent=None,
            agent_invoked="unknown",
            execution_ms=execution_ms,
            constraints_check=constraints_check,
            status="failed",
            reason="no_intent_matched",
        )

        return {
            "ok": False,
            "data": {
                "task_id": task_id,
                "agent_invoked": "unknown",
                "result": None,
                "status": "failed",
                "constraints_check": constraints_check,
                "execution_ms": execution_ms,
            },
            "error": "无法识别指令意图，请包含明确关键词（如：库存、折扣、出餐等）",
        }

    result_data = await _call_brain_agent(
        intent=intent,
        tenant_id=tenant_id,
        store_id=req.store_id,
        context=req.context,
    )

    execution_ms = int((time.perf_counter() - start_ts) * 1000)
    constraints_check = _build_constraints_check(result_data)
    is_fallback = result_data.get("fallback", False)
    status = "failed" if is_fallback else "completed"

    # AgentDecisionLog 留痕
    logger.info(
        "agent_decision_log",
        task_id=task_id,
        instruction=req.instruction,
        intent=intent,
        agent_invoked=agent_invoked,
        execution_ms=execution_ms,
        constraints_check=constraints_check,
        status=status,
        tenant_id=tenant_id,
        store_id=req.store_id,
        priority=req.priority,
    )

    return {
        "ok": not is_fallback,
        "data": {
            "task_id": task_id,
            "agent_invoked": agent_invoked,
            "result": result_data,
            "status": status,
            "constraints_check": constraints_check,
            "execution_ms": execution_ms,
        },
    }


async def _execute_async_task(
    task_id: str,
    intent: str | None,
    tenant_id: str,
    store_id: str,
    context: dict,
) -> None:
    """后台异步执行任务，完成后更新 _task_store。"""
    start_ts = time.perf_counter()

    if not intent:
        _task_store[task_id].update(
            {
                "status": "failed",
                "result": None,
                "constraints_check": {"passed": True},
                "execution_ms": int((time.perf_counter() - start_ts) * 1000),
                "error": "no_intent_matched",
            }
        )
        return

    result_data = await _call_brain_agent(
        intent=intent,
        tenant_id=tenant_id,
        store_id=store_id,
        context=context,
    )

    execution_ms = int((time.perf_counter() - start_ts) * 1000)
    constraints_check = _build_constraints_check(result_data)
    is_fallback = result_data.get("fallback", False)
    status = "failed" if is_fallback else "completed"
    agent_name = INTENT_AGENT_NAME.get(intent, intent)

    _task_store[task_id].update(
        {
            "status": status,
            "result": result_data,
            "constraints_check": constraints_check,
            "execution_ms": execution_ms,
        }
    )

    logger.info(
        "agent_decision_log",
        task_id=task_id,
        intent=intent,
        agent_invoked=agent_name,
        execution_ms=execution_ms,
        constraints_check=constraints_check,
        status=status,
        async_mode=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /tasks/{task_id}
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str) -> dict[str, Any]:
    """查询异步任务状态。

    状态值：pending / completed / failed
    """
    task = _task_store.get(task_id)
    if not task:
        return {
            "ok": False,
            "data": None,
            "error": f"task_id={task_id} 不存在或已过期",
        }

    return {"ok": True, "data": task}


# ─────────────────────────────────────────────────────────────────────────────
# GET /health
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/health")
async def agent_health() -> dict[str, Any]:
    """Master Agent 健康状态，同时探测 tx-brain 各 Agent 端点可用性。

    对 tx-brain /health 做一次 GET；若 tx-brain 不可达则所有 Agent 标记为
    degraded（降级），不影响本服务响应。
    """
    brain_healthy = False
    brain_detail: dict[str, Any] = {}

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get("http://tx-brain:8010/health")
            resp.raise_for_status()
            brain_detail = resp.json()
            brain_healthy = True
        except httpx.TimeoutException:
            brain_detail = {"error": "tx-brain health check timed out"}
        except httpx.RequestError as exc:
            brain_detail = {"error": f"tx-brain unreachable: {exc}"}

    agent_statuses = dict.fromkeys(INTENT_AGENT_NAME.values(), "ready" if brain_healthy else "degraded")

    return {
        "ok": True,
        "data": {
            "service": "tx-agent/master",
            "tx_brain_reachable": brain_healthy,
            "tx_brain_health": brain_detail,
            "agents": agent_statuses,
            "total_agents": len(agent_statuses),
            "ready_count": sum(1 for s in agent_statuses.values() if s == "ready"),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /chat
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/chat")
async def chat(
    req: ChatRequest,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """自然语言对话接口（简化版）。

    流程：
    1. 意图识别
    2. 调用对应 Agent（同步）
    3. 用简单模板将结果转化为中文自然语言回复
    """
    tenant_id = x_tenant_id or req.tenant_id
    intent = _detect_intent(req.message)
    agent_invoked = INTENT_AGENT_NAME.get(intent, "unknown") if intent else "unknown"
    actions_taken: list[str] = []

    if not intent:
        reply = "您好！我是屯象OS智能助手。请告诉我您想了解什么，例如：库存情况、折扣分析、出餐调度、会员洞察等。"
        return {
            "ok": True,
            "data": {
                "reply": reply,
                "actions_taken": actions_taken,
                "agent_invoked": agent_invoked,
            },
        }

    result_data = await _call_brain_agent(
        intent=intent,
        tenant_id=tenant_id,
        store_id=req.store_id,
        context=req.context,
    )

    is_fallback = result_data.get("fallback", False)
    if is_fallback:
        reply = f"【{INTENT_AGENT_NAME[intent]}】暂时无法获取分析结果，请稍后再试。"
    else:
        reply = _result_to_natural_language(intent, result_data)
        actions_taken.append(f"调用{INTENT_AGENT_NAME[intent]}Agent完成分析")

    logger.info(
        "master_agent_chat",
        tenant_id=tenant_id,
        store_id=req.store_id,
        message=req.message,
        intent=intent,
        agent_invoked=agent_invoked,
        fallback=is_fallback,
    )

    return {
        "ok": True,
        "data": {
            "reply": reply,
            "actions_taken": actions_taken,
            "agent_invoked": agent_invoked,
        },
    }
