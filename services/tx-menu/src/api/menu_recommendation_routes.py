"""AI智能排菜推荐API

前缀: /api/v1/menu/recommendation

端点:
  POST /generate   — 根据门店数据生成菜单推荐方案
  GET  /history     — 获取历史推荐记录
  POST /apply       — 应用推荐方案到菜单

AI排菜决策因子:
  1. 食材库存利用 — 优先推荐库存充足/临期食材对应菜品
  2. 毛利结构优化 — 按"四象限"(明星/金牛/问题/瘦狗)平衡品类
  3. 季节性调整   — 根据季节/天气/节假日调整菜品权重
  4. 销售数据驱动 — 基于近7/30天销量趋势调整上架/下架
  5. 客群匹配     — 门店客群画像匹配菜品定位
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/menu/recommendation", tags=["menu-recommendation"])


# ─── Enums ────────────────────────────────────────────────────────────────────

class DishQuadrant(str, Enum):
    """菜品四象限分类"""
    STAR = "star"           # 明星：高销量+高毛利
    CASH_COW = "cash_cow"   # 金牛：低销量+高毛利
    QUESTION = "question"   # 问题：高销量+低毛利
    DOG = "dog"             # 瘦狗：低销量+低毛利


class RecommendationAction(str, Enum):
    """推荐动作"""
    KEEP = "keep"               # 保持不变
    PROMOTE = "promote"         # 提升推荐位
    DEMOTE = "demote"           # 降低排序
    ADD = "add"                 # 新增上架
    REMOVE = "remove"           # 建议下架
    PRICE_UP = "price_up"       # 建议涨价
    PRICE_DOWN = "price_down"   # 建议降价
    COMBO = "combo"             # 建议组合套餐


class SeasonalTag(str, Enum):
    """季节标签"""
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"
    HOLIDAY = "holiday"
    WEEKDAY = "weekday"
    WEEKEND = "weekend"


# ─── Models ────────────────────────────────────────────────────────────────────

class DishRecommendation(BaseModel):
    """单个菜品推荐"""
    dish_id: str
    dish_name: str
    category: str
    current_price_fen: int
    suggested_price_fen: Optional[int] = None
    quadrant: DishQuadrant
    action: RecommendationAction
    confidence: float = Field(ge=0, le=1, description="AI置信度 0-1")
    reasoning: str = ""
    factors: list[str] = Field(default_factory=list)
    # 数据指标
    sales_7d: int = 0
    sales_30d: int = 0
    gross_margin_pct: float = 0.0
    inventory_days: Optional[float] = None
    # 关联推荐
    combo_with: list[str] = Field(default_factory=list)


class GenerateRequest(BaseModel):
    """排菜推荐请求"""
    store_id: str
    target_date: Optional[str] = None       # 目标日期，默认明天
    meal_period: Optional[str] = None       # lunch/dinner/all
    max_dishes: int = Field(default=80, ge=10, le=200)
    optimization_goal: str = Field(
        default="balanced",
        description="balanced|margin|turnover|inventory"
    )
    exclude_categories: list[str] = Field(default_factory=list)
    budget_constraint_fen: Optional[int] = None


class RecommendationPlan(BaseModel):
    """推荐方案"""
    plan_id: str
    store_id: str
    generated_at: str
    target_date: str
    meal_period: str
    optimization_goal: str
    dishes: list[DishRecommendation]
    summary: RecommendationSummary


class RecommendationSummary(BaseModel):
    """方案摘要"""
    total_dishes: int
    keep_count: int
    promote_count: int
    demote_count: int
    add_count: int
    remove_count: int
    combo_count: int
    estimated_margin_change_pct: float = 0.0
    estimated_turnover_change_pct: float = 0.0
    ai_confidence: float = 0.0
    key_insights: list[str] = Field(default_factory=list)


class ApplyRequest(BaseModel):
    """应用方案请求"""
    plan_id: str
    store_id: str
    apply_actions: list[str] = Field(
        default_factory=list,
        description="要应用的dish_id列表，为空则全部应用"
    )
    effective_at: Optional[str] = None


class HistoryItem(BaseModel):
    """历史推荐记录"""
    plan_id: str
    store_id: str
    generated_at: str
    target_date: str
    total_dishes: int
    applied: bool
    applied_at: Optional[str] = None
    optimization_goal: str
    estimated_margin_change_pct: float


# ─── Mock Data ──────────────────────────────────────────────────────────────────

def _mock_recommendation(store_id: str, goal: str) -> RecommendationPlan:
    """生成 mock 推荐方案（真实逻辑需接入 tx-brain/Claude API）"""
    import uuid
    now = datetime.now()
    plan_id = f"plan_{uuid.uuid4().hex[:8]}"

    dishes = [
        DishRecommendation(
            dish_id="dish_001", dish_name="剁椒鱼头",
            category="招牌菜", current_price_fen=12800,
            quadrant=DishQuadrant.STAR, action=RecommendationAction.KEEP,
            confidence=0.92, reasoning="销量稳定增长，毛利率68%，保持当前排序",
            factors=["高销量", "高毛利", "食材充足"],
            sales_7d=156, sales_30d=623, gross_margin_pct=0.68,
        ),
        DishRecommendation(
            dish_id="dish_002", dish_name="酸菜鱼",
            category="热门菜", current_price_fen=6800,
            quadrant=DishQuadrant.QUESTION, action=RecommendationAction.PRICE_UP,
            confidence=0.78, reasoning="销量高但毛利仅38%，建议调价至¥78",
            suggested_price_fen=7800,
            factors=["高销量", "低毛利", "鱼价上涨"],
            sales_7d=189, sales_30d=812, gross_margin_pct=0.38,
        ),
        DishRecommendation(
            dish_id="dish_003", dish_name="松茸汽锅鸡",
            category="汤品", current_price_fen=16800,
            quadrant=DishQuadrant.CASH_COW, action=RecommendationAction.PROMOTE,
            confidence=0.85, reasoning="毛利75%但销量偏低，建议提升推荐位+首页展示",
            factors=["高毛利", "低销量", "季节应季"],
            sales_7d=23, sales_30d=89, gross_margin_pct=0.75,
            inventory_days=5.2,
        ),
        DishRecommendation(
            dish_id="dish_004", dish_name="清炒时蔬",
            category="蔬菜", current_price_fen=2800,
            quadrant=DishQuadrant.DOG, action=RecommendationAction.REMOVE,
            confidence=0.71, reasoning="连续30天日均销量<3，替换为'有机菜心'",
            factors=["极低销量", "低毛利", "可替换"],
            sales_7d=5, sales_30d=18, gross_margin_pct=0.42,
        ),
        DishRecommendation(
            dish_id="dish_005", dish_name="小龙虾拌面",
            category="面食", current_price_fen=4800,
            quadrant=DishQuadrant.STAR, action=RecommendationAction.COMBO,
            confidence=0.88, reasoning="与'冰粉'关联购买率62%，建议组合套餐",
            factors=["高关联度", "夏季热销", "套餐提升客单价"],
            sales_7d=134, sales_30d=520, gross_margin_pct=0.55,
            combo_with=["dish_010"],
        ),
        DishRecommendation(
            dish_id="dish_006", dish_name="香煎三文鱼",
            category="海鲜", current_price_fen=8800,
            quadrant=DishQuadrant.CASH_COW, action=RecommendationAction.ADD,
            confidence=0.82, reasoning="新品上市，预测毛利72%，建议周末限定上架",
            factors=["高毛利预测", "新品试销", "食材新鲜到货"],
            sales_7d=0, sales_30d=0, gross_margin_pct=0.72,
            inventory_days=2.0,
        ),
    ]

    summary = RecommendationSummary(
        total_dishes=len(dishes),
        keep_count=sum(1 for d in dishes if d.action == RecommendationAction.KEEP),
        promote_count=sum(1 for d in dishes if d.action == RecommendationAction.PROMOTE),
        demote_count=sum(1 for d in dishes if d.action == RecommendationAction.DEMOTE),
        add_count=sum(1 for d in dishes if d.action == RecommendationAction.ADD),
        remove_count=sum(1 for d in dishes if d.action == RecommendationAction.REMOVE),
        combo_count=sum(1 for d in dishes if d.action == RecommendationAction.COMBO),
        estimated_margin_change_pct=3.2,
        estimated_turnover_change_pct=1.8,
        ai_confidence=0.83,
        key_insights=[
            "酸菜鱼毛利偏低，建议调价¥10可提升整体毛利1.5%",
            "松茸汽锅鸡应季但曝光不足，提升推荐位预计增销40%",
            "清炒时蔬可替换为有机菜心，预计提升品类毛利8%",
            "小龙虾+冰粉组合套餐预计提升客单价¥6",
        ],
    )

    return RecommendationPlan(
        plan_id=plan_id,
        store_id=store_id,
        generated_at=now.isoformat(),
        target_date=(now.strftime("%Y-%m-%d")),
        meal_period="all",
        optimization_goal=goal,
        dishes=dishes,
        summary=summary,
    )


_MOCK_HISTORY: list[HistoryItem] = [
    HistoryItem(
        plan_id="plan_abc12345",
        store_id="store_001",
        generated_at="2026-04-10T09:30:00",
        target_date="2026-04-11",
        total_dishes=68,
        applied=True,
        applied_at="2026-04-10T10:15:00",
        optimization_goal="balanced",
        estimated_margin_change_pct=2.1,
    ),
    HistoryItem(
        plan_id="plan_def67890",
        store_id="store_001",
        generated_at="2026-04-07T09:00:00",
        target_date="2026-04-08",
        total_dishes=72,
        applied=True,
        applied_at="2026-04-07T11:00:00",
        optimization_goal="margin",
        estimated_margin_change_pct=4.5,
    ),
]


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_recommendation(
    req: GenerateRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """生成AI排菜推荐方案

    根据门店的销售数据、库存状况、毛利结构、季节因素等，
    调用 tx-brain (Claude API) 生成智能菜单优化建议。

    真实环境会调用:
    1. tx-supply 获取当前库存 + 临期食材
    2. tx-analytics 获取销售趋势 + 四象限分析
    3. tx-member 获取客群画像
    4. tx-brain 综合推理生成方案
    """
    logger.info(
        "menu_recommendation.generate",
        tenant_id=x_tenant_id,
        store_id=req.store_id,
        goal=req.optimization_goal,
    )

    try:
        plan = _mock_recommendation(req.store_id, req.optimization_goal)
        return {"ok": True, "data": plan.model_dump()}
    except Exception as e:
        logger.error("menu_recommendation.generate_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"推荐方案生成失败: {e}")


@router.get("/history")
async def get_recommendation_history(
    store_id: str,
    limit: int = 10,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """获取历史推荐记录"""
    logger.info(
        "menu_recommendation.history",
        tenant_id=x_tenant_id,
        store_id=store_id,
    )

    history = [h for h in _MOCK_HISTORY if h.store_id == store_id][:limit]
    return {
        "ok": True,
        "data": {
            "items": [h.model_dump() for h in history],
            "total": len(history),
        },
    }


@router.post("/apply")
async def apply_recommendation(
    req: ApplyRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """应用推荐方案到菜单

    将AI推荐的调整动作（调价/上架/下架/排序等）批量应用到菜单。
    实际操作通过调用 tx-menu 的菜品管理API完成。
    """
    logger.info(
        "menu_recommendation.apply",
        tenant_id=x_tenant_id,
        plan_id=req.plan_id,
        store_id=req.store_id,
        action_count=len(req.apply_actions),
    )

    # Mock：标记为已应用
    applied_count = len(req.apply_actions) if req.apply_actions else 6  # 默认全部
    return {
        "ok": True,
        "data": {
            "plan_id": req.plan_id,
            "applied_count": applied_count,
            "effective_at": req.effective_at or datetime.now().isoformat(),
            "message": f"已成功应用 {applied_count} 项菜单调整",
        },
    }
