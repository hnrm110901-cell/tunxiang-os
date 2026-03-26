"""知识图谱自然语言查询 API"""
from typing import Optional

from fastapi import APIRouter, Query

from ..services.knowledge_graph import (
    KnowledgeGraphService,
    NLQueryResult,
    seed_knowledge_graph,
)

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

# 全局知识图谱实例（生产中应通过依赖注入）
_kg: Optional[KnowledgeGraphService] = None


def get_kg() -> KnowledgeGraphService:
    """获取知识图谱单例（懒加载 + 种子数据）"""
    global _kg
    if _kg is None:
        _kg = seed_knowledge_graph()
    return _kg


# ─── 自然语言查询 ───


@router.post("/query")
async def query_natural_language(
    body: dict,
) -> dict:
    """自然语言查询

    Body:
        question: str — 自然语言问题（中文）
        tenant_id: str | None — 租户 ID（可选）
        format: str — 返回格式 text/table/chart_data（默认 text）

    Examples:
        {"question": "长沙地区海鲜酒楼的平均翻台率是多少？"}
        {"question": "剁椒鱼头的最优定价区间是多少？"}
        {"question": "哪些门店的人效最高？"}
    """
    question = body.get("question", "")
    if not question:
        return {"ok": False, "error": {"code": "MISSING_QUESTION", "message": "请输入问题"}}

    tenant_id = body.get("tenant_id")
    fmt = body.get("format", "text")

    kg = get_kg()
    result: NLQueryResult = kg.query_natural_language(question, tenant_id=tenant_id)

    # 如果需要非文本格式，重新生成答案
    if fmt != "text":
        result.answer = kg.generate_answer(question, result.data, format=fmt)

    return {
        "ok": True,
        "data": {
            "question": result.question,
            "answer": result.answer,
            "intent": {
                "type": result.intent.intent_type,
                "entities": result.intent.entities,
                "metric": result.intent.metric,
                "aggregation": result.intent.aggregation,
                "time_range": result.intent.time_range,
                "filters": result.intent.filters,
            },
            "data": result.data,
            "confidence": result.confidence,
            "sources": result.sources,
            "suggestions": result.suggestions,
            "query_ms": result.query_ms,
        },
    }


# ─── 图谱统计 ───


@router.get("/graph/stats")
async def get_graph_stats() -> dict:
    """知识图谱统计信息

    返回实体数量、关系数量、最后更新时间等。
    """
    kg = get_kg()
    stats = kg.get_graph_stats()
    return {"ok": True, "data": stats}


# ─── 行业基准 ───


@router.get("/benchmarks/{metric}")
async def get_benchmarks(
    metric: str,
    business_type: Optional[str] = Query(None, description="业态类型"),
    city: Optional[str] = Query(None, description="城市"),
) -> dict:
    """获取行业基准数据

    Path:
        metric: 指标名（turnover_rate/avg_check/profit_margin/labor_efficiency/revenue 等）

    Query:
        business_type: 业态（如"海鲜酒楼"）
        city: 城市（如"长沙"）
    """
    kg = get_kg()
    benchmark = kg.get_benchmark(metric, business_type=business_type, city=city)
    return {"ok": True, "data": {"metric": metric, "benchmark": benchmark}}


# ─── 最佳实践 ───


@router.get("/practices")
async def get_best_practices(
    metric: Optional[str] = Query(None, description="筛选指标"),
    store_id: Optional[str] = Query(None, description="门店 ID（获取适用实践）"),
) -> dict:
    """获取最佳实践

    Query:
        metric: 按指标筛选（如 turnover_rate）
        store_id: 获取适用于指定门店的实践
    """
    kg = get_kg()

    if store_id:
        practices = kg.get_applicable_practices(store_id)
    elif metric:
        practices = kg.discover_best_practices(metric)
    else:
        # 返回所有最佳实践
        practices = list(kg._entities.get("best_practice", {}).values())

    return {"ok": True, "data": {"practices": practices, "total": len(practices)}}


# ─── 推荐问题 ───


@router.get("/suggestions")
async def get_suggestions(
    store_id: Optional[str] = Query(None, description="门店 ID"),
) -> dict:
    """获取推荐问题列表

    为门店老板提供常见的有价值问题示例。
    """
    general_suggestions = [
        "长沙地区海鲜酒楼的平均翻台率是多少？",
        "剁椒鱼头的最优定价区间是多少？",
        "哪些门店的人效最高？",
        "上周营业额为什么下降了？",
        "推荐适合200人宴会的菜单",
        "我们的毛利率跟行业平均比怎么样？",
        "翻台率怎么提升？",
        "哪些菜品的毛利率最高？",
        "客单价排名前5的门店是哪些？",
        "最近一周客流量的趋势怎么样？",
    ]

    store_suggestions: list[str] = []
    if store_id:
        kg = get_kg()
        store = kg.get_entity("store", store_id)
        if store:
            name = store.get("name", "")
            store_suggestions = [
                f"{name}的翻台率跟行业平均比怎么样？",
                f"{name}最近一周营业额趋势如何？",
                f"有哪些最佳实践可以帮助{name}提升人效？",
            ]

    return {
        "ok": True,
        "data": {
            "general": general_suggestions,
            "store_specific": store_suggestions,
        },
    }
