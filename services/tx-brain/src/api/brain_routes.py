"""AI决策API路由 — 折扣守护 & 会员洞察 & 出餐调度预测 & 库存预警 & 巡店质检 & 财务稽核 & 智能客服 & 智能排菜 & 私域运营

Endpoints:
  POST /api/v1/brain/discount/analyze          — 折扣分析（event + history）
  POST /api/v1/brain/member/insight            — 会员洞察（member + orders）
  POST /api/v1/brain/dispatch/predict          — 出餐调度预测（order + kitchen_load）
  POST /api/v1/brain/inventory/analyze         — 库存预警分析（inventory + sales_history）
  POST /api/v1/brain/patrol/analyze            — 巡店质检分析（巡检清单 + 评分）
  POST /api/v1/brain/finance/audit             — 财务稽核（门店财务快照）
  POST /api/v1/brain/customer-service/handle   — 智能客服（顾客投诉/询问/反馈）
  POST /api/v1/brain/menu/optimize             — 智能排菜（库存 + 菜品表现）
  POST /api/v1/brain/crm/campaign              — 私域运营活动方案（微信群/朋友圈/小程序）
  GET  /api/v1/brain/health                    — AI服务健康检查（验证Claude API可达）
"""
from __future__ import annotations

from typing import Any

import anthropic
import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..agents.crm_operator import crm_operator
from ..agents.customer_service import customer_service
from ..agents.discount_guardian import discount_guardian
from ..agents.dispatch_predictor import dispatch_predictor
from ..agents.finance_auditor import finance_auditor
from ..agents.inventory_sentinel import inventory_sentinel
from ..agents.member_insight import member_insight
from ..agents.menu_optimizer import menu_optimizer
from ..agents.patrol_inspector import patrol_inspector

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/brain", tags=["brain"])


# ─── Request Models ──────────────────────────────────────────────


class DiscountAnalyzeRequest(BaseModel):
    event: dict[str, Any] = Field(..., description="折扣事件（含操作员/菜品/折扣信息）")
    history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="近30条同操作员折扣记录（可为空）",
    )


class MemberInsightRequest(BaseModel):
    member: dict[str, Any] = Field(..., description="会员基本信息")
    orders: list[dict[str, Any]] = Field(
        default_factory=list,
        description="近12个月订单列表（含菜品明细）",
    )


class DispatchPredictRequest(BaseModel):
    order: dict[str, Any] = Field(
        ...,
        description=(
            "订单信息：{id, items: [{dish_name, category, quantity, is_live_seafood}],"
            " table_size, created_at}"
        ),
    )
    kitchen_load: dict[str, Any] = Field(
        default_factory=dict,
        description="厨房当前负载：{pending_tasks, avg_wait_minutes, active_chefs}",
    )


class InventoryAnalyzeRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    tenant_id: str = Field(..., description="租户ID")
    inventory: list[dict[str, Any]] = Field(
        ...,
        description=(
            "当前库存列表：[{ingredient_name, current_qty, unit,"
            " min_qty, expiry_date, unit_cost_fen}]"
        ),
    )
    sales_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="近7天每日消耗量：[{date, ingredient_name, consumed_qty}]",
    )


class PatrolAnalyzeRequest(BaseModel):
    tenant_id: str = Field(..., description="租户ID")
    store_id: str = Field(..., description="门店ID")
    patrol_date: str = Field(..., description="巡检日期（YYYY-MM-DD）")
    inspector_name: str = Field(..., description="巡检员姓名")
    checklist_items: list[dict[str, Any]] = Field(
        ...,
        description=(
            "检查清单列表：[{category, item_name, result(pass|fail|na),"
            " score(0-10), photo_count, notes}]"
        ),
    )
    overall_score: float = Field(..., description="本次综合评分（0-100）")
    previous_score: float = Field(
        default=100.0,
        description="上次综合评分（用于趋势对比，默认100）",
    )


# ─── Endpoints ───────────────────────────────────────────────────


@router.post("/discount/analyze")
async def analyze_discount(req: DiscountAnalyzeRequest) -> dict[str, Any]:
    """POST /api/v1/brain/discount/analyze

    调用折扣守护Agent分析折扣事件是否合规。
    返回 allow/warn/reject 决策及置信度、风险因素、三条硬约束校验结果。
    """
    try:
        result = await discount_guardian.analyze(req.event, req.history)
    except anthropic.APIConnectionError as exc:
        logger.error("discount_analyze_connection_error", error=str(exc))
        return {
            "ok": False,
            "error": {
                "code": "AI_CONNECTION_ERROR",
                "message": "无法连接Claude API，请稍后重试",
            },
        }
    except anthropic.APIError as exc:
        logger.error(
            "discount_analyze_api_error",
            status_code=getattr(exc, "status_code", None),
            error=str(exc),
        )
        return {
            "ok": False,
            "error": {
                "code": "AI_API_ERROR",
                "message": f"Claude API错误: {exc}",
            },
        }

    return {"ok": True, "data": result}


@router.post("/member/insight")
async def member_insight_endpoint(req: MemberInsightRequest) -> dict[str, Any]:
    """POST /api/v1/brain/member/insight

    调用会员洞察Agent分析会员消费行为。
    返回会员分层、关键洞察、推荐菜品及行动建议。
    """
    try:
        result = await member_insight.analyze(req.member, req.orders)
    except anthropic.APIConnectionError as exc:
        logger.error("member_insight_connection_error", error=str(exc))
        return {
            "ok": False,
            "error": {
                "code": "AI_CONNECTION_ERROR",
                "message": "无法连接Claude API，请稍后重试",
            },
        }
    except anthropic.APIError as exc:
        logger.error(
            "member_insight_api_error",
            status_code=getattr(exc, "status_code", None),
            error=str(exc),
        )
        return {
            "ok": False,
            "error": {
                "code": "AI_API_ERROR",
                "message": f"Claude API错误: {exc}",
            },
        }

    return {"ok": True, "data": result}


@router.post("/dispatch/predict")
async def dispatch_predict(req: DispatchPredictRequest) -> dict[str, Any]:
    """POST /api/v1/brain/dispatch/predict

    调用出餐调度预测Agent预测出餐时间。
    低负载普通订单走快路径（不调Claude），高负载/活鲜/大桌走慢路径（Claude sonnet）。
    返回 estimated_minutes/confidence/key_bottleneck/recommendations/source。
    """
    try:
        result = await dispatch_predictor.predict(req.order, req.kitchen_load)
    except anthropic.APIConnectionError as exc:
        logger.error("dispatch_predict_connection_error", error=str(exc))
        return {
            "ok": False,
            "error": {
                "code": "AI_CONNECTION_ERROR",
                "message": "无法连接Claude API，请稍后重试",
            },
        }
    except anthropic.APIError as exc:
        logger.error(
            "dispatch_predict_api_error",
            status_code=getattr(exc, "status_code", None),
            error=str(exc),
        )
        return {
            "ok": False,
            "error": {
                "code": "AI_API_ERROR",
                "message": f"Claude API错误: {exc}",
            },
        }

    return {"ok": True, "data": result}


@router.post("/inventory/analyze")
async def inventory_analyze(req: InventoryAnalyzeRequest) -> dict[str, Any]:
    """POST /api/v1/brain/inventory/analyze

    调用库存预警Agent分析缺货风险，生成采购建议。
    食安合规硬约束：临期食材（效期≤3天）强制标红。
    返回 risk_items/summary/total_purchase_budget_estimate_fen。
    """
    try:
        result = await inventory_sentinel.analyze(
            req.store_id,
            req.tenant_id,
            req.inventory,
            req.sales_history,
        )
    except anthropic.APIConnectionError as exc:
        logger.error("inventory_analyze_connection_error", error=str(exc))
        return {
            "ok": False,
            "error": {
                "code": "AI_CONNECTION_ERROR",
                "message": "无法连接Claude API，请稍后重试",
            },
        }
    except anthropic.APIError as exc:
        logger.error(
            "inventory_analyze_api_error",
            status_code=getattr(exc, "status_code", None),
            error=str(exc),
        )
        return {
            "ok": False,
            "error": {
                "code": "AI_API_ERROR",
                "message": f"Claude API错误: {exc}",
            },
        }

    return {"ok": True, "data": result}


@router.post("/patrol/analyze")
async def patrol_analyze(req: PatrolAnalyzeRequest) -> dict[str, Any]:
    """POST /api/v1/brain/patrol/analyze

    调用巡店质检Agent分析巡检清单，自动识别违规项，生成整改建议。
    食安/消防违规强制触发自动预警，overall_score<60触发critical风险等级。
    返回 risk_level/violations/improvement_suggestions/score_trend/
    constraints_check/auto_alert_required/source。
    """
    try:
        result = await patrol_inspector.analyze(req.model_dump())
    except anthropic.APIConnectionError as exc:
        logger.error("patrol_analyze_connection_error", error=str(exc))
        return {
            "ok": False,
            "error": {
                "code": "AI_CONNECTION_ERROR",
                "message": "无法连接Claude API，请稍后重试",
            },
        }
    except anthropic.APIError as exc:
        logger.error(
            "patrol_analyze_api_error",
            status_code=getattr(exc, "status_code", None),
            error=str(exc),
        )
        return {
            "ok": False,
            "error": {
                "code": "AI_API_ERROR",
                "message": f"Claude API错误: {exc}",
            },
        }

    return {"ok": True, "data": result}


class FinanceAuditRequest(BaseModel):
    tenant_id: str = Field(..., description="租户ID")
    store_id: str = Field(..., description="门店ID")
    date: str = Field(..., description="财务日期（YYYY-MM-DD）")
    revenue_fen: int = Field(..., description="当日营收（分）")
    cost_fen: int = Field(..., description="当日成本（分）")
    discount_total_fen: int = Field(default=0, description="当日折扣合计（分）")
    void_count: int = Field(default=0, description="当日作废单数")
    void_amount_fen: int = Field(default=0, description="当日作废金额（分）")
    cash_actual_fen: int = Field(..., description="实际现金盘点（分）")
    cash_expected_fen: int = Field(..., description="系统预期现金（分）")
    total_order_count: int = Field(
        default=0,
        description="当日总订单数（用于计算作废率，为0时由Agent内部估算）",
    )
    high_discount_orders: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "高折扣订单列表：[{order_id, operator_id, discount_rate,"
            " amount_fen, created_at}]"
        ),
    )


@router.post("/finance/audit")
async def finance_audit(req: FinanceAuditRequest) -> dict[str, Any]:
    """POST /api/v1/brain/finance/audit

    调用财务稽核Agent分析门店当日财务快照。
    Python预计算关键指标（毛利率/作废率/现金差异/折扣率），
    再调用Claude识别异常模式。Claude失败时自动降级为规则引擎。
    返回 risk_level/score/anomalies/audit_suggestions/constraints_check/source。
    """
    try:
        result = await finance_auditor.analyze(req.model_dump())
    except anthropic.APIConnectionError as exc:
        logger.error("finance_audit_connection_error", error=str(exc))
        return {
            "ok": False,
            "error": {
                "code": "AI_CONNECTION_ERROR",
                "message": "无法连接Claude API，请稍后重试",
            },
        }
    except anthropic.APIError as exc:
        logger.error(
            "finance_audit_api_error",
            status_code=getattr(exc, "status_code", None),
            error=str(exc),
        )
        return {
            "ok": False,
            "error": {
                "code": "AI_API_ERROR",
                "message": f"Claude API错误: {exc}",
            },
        }

    return {"ok": True, "data": result}


@router.get("/health")
async def brain_health() -> dict[str, Any]:
    """GET /api/v1/brain/health

    检查AI服务健康状态，验证Claude API是否可达。
    发送一条最小化请求到 claude-haiku 确认连通性。
    """
    import anthropic as _anthropic

    _client = _anthropic.AsyncAnthropic()

    try:
        msg = await _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8,
            messages=[{"role": "user", "content": "ping"}],
        )
        claude_ok = bool(msg.content)
        claude_status = "reachable"
    except _anthropic.APIConnectionError as exc:
        logger.warning("brain_health_connection_error", error=str(exc))
        claude_ok = False
        claude_status = f"connection_error: {exc}"
    except _anthropic.APIError as exc:
        logger.warning(
            "brain_health_api_error",
            status_code=getattr(exc, "status_code", None),
            error=str(exc),
        )
        claude_ok = False
        claude_status = f"api_error: {exc}"

    return {
        "ok": claude_ok,
        "data": {
            "service": "tx-brain",
            "agents": {
                "discount_guardian": "ready",
                "member_insight": "ready",
                "dispatch_predictor": "ready",
                "inventory_sentinel": "ready",
                "patrol_inspector": "ready",
                "finance_auditor": "ready",
                "customer_service": "ready",
                "menu_optimizer": "ready",
                "crm_operator": "ready",
            },
            "claude_api": claude_status,
        },
    }


# ─── 智能客服 ─────────────────────────────────────────────────────


class CustomerServiceRequest(BaseModel):
    tenant_id: str = Field(..., description="租户ID")
    store_id: str = Field(..., description="门店ID")
    customer_id: str = Field(default="", description="顾客ID（可选）")
    channel: str = Field(
        ...,
        description="消息渠道（wechat_mp / miniapp / review / call / in_store）",
    )
    message: str = Field(..., description="顾客原文消息")
    order_id: str = Field(default="", description="关联订单ID（可选）")
    message_type: str = Field(
        default="inquiry",
        description="消息类型（complaint / inquiry / feedback / praise）",
    )
    context_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="历史对话记录 [{role: user|assistant, content: str}]，可为空",
    )
    customer_tier: str = Field(
        default="regular",
        description="顾客等级（vip / regular / new），影响处置优先级",
    )


@router.post("/customer-service/handle")
async def customer_service_handle(req: CustomerServiceRequest) -> dict[str, Any]:
    """POST /api/v1/brain/customer-service/handle

    调用智能客服Agent处理顾客投诉/询问/反馈。
    Python预处理：VIP投诉/食品安全关键词/高额退款强制升级人工。
    Claude负责意图识别、情绪分析、生成中文回复及处置动作建议。
    返回 intent/sentiment/response/action_required/actions/
    constraints_check/escalate_to_human/source。
    """
    try:
        result = await customer_service.handle(req.model_dump())
    except anthropic.APIConnectionError as exc:
        logger.error("customer_service_connection_error", error=str(exc))
        return {
            "ok": False,
            "error": {
                "code": "AI_CONNECTION_ERROR",
                "message": "无法连接Claude API，请稍后重试",
            },
        }
    except anthropic.APIError as exc:
        logger.error(
            "customer_service_api_error",
            status_code=getattr(exc, "status_code", None),
            error=str(exc),
        )
        return {
            "ok": False,
            "error": {
                "code": "AI_API_ERROR",
                "message": f"Claude API错误: {exc}",
            },
        }

    return {"ok": True, "data": result}


# ─── 智能排菜 ──────────────────────────────────────────────────────


class MenuOptimizeRequest(BaseModel):
    tenant_id: str = Field(..., description="租户ID")
    store_id: str = Field(..., description="门店ID")
    date: str = Field(..., description="日期（YYYY-MM-DD）")
    meal_period: str = Field(
        ...,
        description="餐段（breakfast / lunch / dinner）",
    )
    current_inventory: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "当前库存列表："
            "[{ingredient_id, name, quantity, unit, expiry_days, cost_per_unit_fen}]"
        ),
    )
    dish_performance: list[dict[str, Any]] = Field(
        ...,
        description=(
            "菜品表现数据："
            "[{dish_id, dish_name, category, avg_daily_orders, margin_rate,"
            " prep_time_minutes, is_available}]"
        ),
    )
    weather: str = Field(
        default="",
        description="天气（sunny / rainy / hot / cold），可空",
    )
    day_type: str = Field(
        default="weekday",
        description="日期类型（weekday / weekend / holiday）",
    )


@router.post("/menu/optimize")
async def menu_optimize(req: MenuOptimizeRequest) -> dict[str, Any]:
    """POST /api/v1/brain/menu/optimize

    调用智能排菜Agent，根据当前库存、历史销量、利润数据推荐最优菜品排序。
    Python预计算临期食材关联菜品、平均毛利率、多样性指标；
    再调用Claude（claude-sonnet-4-6）生成完整排菜方案。Claude失败时降级为规则引擎。
    返回 featured_dishes/dishes_to_promote/dishes_to_deplete/
    suggested_combos/menu_adjustments/constraints_check/source。
    """
    try:
        result = await menu_optimizer.optimize(req.model_dump())
    except anthropic.APIConnectionError as exc:
        logger.error("menu_optimize_connection_error", error=str(exc))
        return {
            "ok": False,
            "error": {
                "code": "AI_CONNECTION_ERROR",
                "message": "无法连接Claude API，请稍后重试",
            },
        }
    except anthropic.APIError as exc:
        logger.error(
            "menu_optimize_api_error",
            status_code=getattr(exc, "status_code", None),
            error=str(exc),
        )
        return {
            "ok": False,
            "error": {
                "code": "AI_API_ERROR",
                "message": f"Claude API错误: {exc}",
            },
        }

    return {"ok": True, "data": result}


# ─── 私域运营 ──────────────────────────────────────────────────────


class CRMCampaignRequest(BaseModel):
    tenant_id: str = Field(..., description="租户ID")
    store_id: str = Field(..., description="门店ID")
    brand_name: str = Field(..., description="品牌名称")
    campaign_type: str = Field(
        ...,
        description="活动类型（retention / reactivation / upsell / event / holiday）",
    )
    target_segment: str = Field(
        ...,
        description="目标用户群（vip / regular / at_risk / new）",
    )
    target_count: int = Field(..., description="目标用户数量")
    budget_fen: int = Field(..., description="活动预算（分）")
    key_dishes: list[str] = Field(
        default_factory=list,
        description="重点推广菜品名列表",
    )
    discount_limit: float | None = Field(
        default=None,
        description="最大折扣率（如0.2=8折），可空",
    )
    special_occasion: str = Field(
        default="",
        description="特殊场合（可空，如'母亲节'）",
    )


@router.post("/crm/campaign")
async def crm_campaign(req: CRMCampaignRequest) -> dict[str, Any]:
    """POST /api/v1/brain/crm/campaign

    调用私域运营Agent生成微信群/朋友圈/小程序推送内容。
    使用 claude-haiku-4-5-20251001（文案生成，高频低成本）。
    Python预检折扣合规性；Claude负责生成有品牌温度的文案。
    Claude失败时自动降级为模板文案兜底。
    返回 campaign_name/wechat_group_message/moments_copy/
    miniapp_push_title/miniapp_push_content/coupon_suggestion/
    send_time_suggestion/constraints_check/source。
    """
    try:
        result = await crm_operator.generate_campaign(req.model_dump())
    except anthropic.APIConnectionError as exc:
        logger.error("crm_campaign_connection_error", error=str(exc))
        return {
            "ok": False,
            "error": {
                "code": "AI_CONNECTION_ERROR",
                "message": "无法连接Claude API，请稍后重试",
            },
        }
    except anthropic.APIError as exc:
        logger.error(
            "crm_campaign_api_error",
            status_code=getattr(exc, "status_code", None),
            error=str(exc),
        )
        return {
            "ok": False,
            "error": {
                "code": "AI_API_ERROR",
                "message": f"Claude API错误: {exc}",
            },
        }

    return {"ok": True, "data": result}
