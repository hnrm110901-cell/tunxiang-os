"""D8 知识库 — 案例沉淀、案例搜索、SOP建议、最佳实践推荐

支持将经营改进案例沉淀为组织知识，并提供检索和推荐能力。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _serialize_row(row_mapping: dict) -> dict:
    result = {}
    for key, val in row_mapping.items():
        if val is None:
            result[key] = None
        elif hasattr(val, "isoformat"):
            result[key] = val.isoformat()
        elif hasattr(val, "hex"):
            result[key] = str(val)
        else:
            result[key] = val
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  案例沉淀
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def save_case(
    store_id: str,
    case_data: Dict[str, Any],
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """沉淀一条经营案例并写入 DB。"""
    case_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    case = {
        "case_id": case_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "title": case_data.get("title", ""),
        "category": case_data.get("category", "general"),
        "problem": case_data.get("problem", ""),
        "solution": case_data.get("solution", ""),
        "result": case_data.get("result", ""),
        "tags": case_data.get("tags", []),
        "author_id": case_data.get("author_id", ""),
        "status": "active",
        "views": 0,
        "likes": 0,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    if db is not None:
        try:
            await _set_rls(db, tenant_id)
            await db.execute(
                text(
                    """
                    INSERT INTO knowledge_cases
                      (id, tenant_id, store_id, title, category, problem, solution,
                       result, tags, author_id, status, views, likes, created_at, updated_at)
                    VALUES
                      (:id, NULLIF(current_setting('app.tenant_id', true), '')::uuid,
                       :store_id, :title, :category, :problem, :solution,
                       :result, :tags::jsonb, :author_id, 'active', 0, 0, :now, :now)
                    """
                ),
                {
                    "id": case_id,
                    "store_id": store_id,
                    "title": case["title"],
                    "category": case["category"],
                    "problem": case["problem"],
                    "solution": case["solution"],
                    "result": case["result"],
                    "tags": str(case["tags"]).replace("'", '"'),
                    "author_id": case["author_id"],
                    "now": now,
                },
            )
        except SQLAlchemyError as exc:
            log.error("case_save_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)

    log.info("case_saved", case_id=case_id, store_id=store_id, tenant_id=tenant_id, category=case["category"])
    return case


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  案例搜索
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def search_cases(
    keyword: str,
    tenant_id: str,
    db: Any,
    *,
    category: Optional[str] = None,
    cases: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """搜索案例库（优先从 DB 查询）。"""
    results: List[Dict[str, Any]] = []

    if db is not None and not cases:
        try:
            await _set_rls(db, tenant_id)
            where_clauses = [
                "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid",
                "status = 'active'",
                "is_deleted = false",
                "(title ILIKE :kw OR problem ILIKE :kw OR solution ILIKE :kw OR tags::text ILIKE :kw)",
            ]
            params: dict = {"kw": f"%{keyword}%"}

            if category:
                where_clauses.append("category = :category")
                params["category"] = category

            where_sql = " AND ".join(where_clauses)

            rows_result = await db.execute(
                text(
                    f"""
                    SELECT id AS case_id, store_id, title, category, problem,
                           solution, result, tags, author_id, status, views, likes,
                           created_at, updated_at
                    FROM knowledge_cases
                    WHERE {where_sql}
                    ORDER BY created_at DESC
                    LIMIT 50
                    """
                ),
                params,
            )
            results = [_serialize_row(dict(row._mapping)) for row in rows_result]
        except SQLAlchemyError as exc:
            log.error("case_search_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)
    else:
        all_cases = cases or []
        keyword_lower = keyword.lower()
        for c in all_cases:
            if c.get("tenant_id") != tenant_id:
                continue
            if category and c.get("category") != category:
                continue
            searchable = " ".join(
                [
                    c.get("title", ""),
                    c.get("problem", ""),
                    c.get("solution", ""),
                    " ".join(c.get("tags", [])),
                ]
            ).lower()
            if keyword_lower in searchable:
                results.append(c)

    log.info("cases_searched", tenant_id=tenant_id, keyword=keyword, result_count=len(results))

    return {
        "keyword": keyword,
        "tenant_id": tenant_id,
        "results": results,
        "total": len(results),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SOP 优化建议
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# 内置 SOP 建议模板
_SOP_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
    "food_safety": [
        {
            "title": "食材验收 SOP 优化",
            "steps": ["到货时核对品名/数量/批次", "检查温度（冷链≤4°C）", "记录效期并贴标", "不合格品拒收并拍照留证"],
            "frequency": "每次到货",
        },
        {
            "title": "后厨卫生检查 SOP",
            "steps": ["每日营业前检查冰箱温度", "操作台消毒", "员工健康自查", "餐具消毒记录"],
            "frequency": "每日",
        },
    ],
    "cost": [
        {
            "title": "损耗管控 SOP",
            "steps": ["每日盘点高值食材", "登记损耗原因", "周汇总分析损耗趋势", "月度调整备料标准"],
            "frequency": "每日",
        },
        {
            "title": "采购价格核查 SOP",
            "steps": ["每周比对三家供应商报价", "异常涨价需主管审批", "季度供应商评估"],
            "frequency": "每周",
        },
    ],
    "service": [
        {
            "title": "客诉处理 SOP",
            "steps": ["2分钟内响应", "道歉并记录问题", "现场解决或升级店长", "事后回访并记录"],
            "frequency": "即时",
        },
    ],
    "equipment": [
        {
            "title": "设备巡检 SOP",
            "steps": ["每日检查冰箱/烤箱/排烟运行状态", "异常声响立即报修", "月度保养记录"],
            "frequency": "每日",
        },
    ],
}


async def get_sop_suggestions(
    store_id: str,
    issue_type: str,
    tenant_id: str,
    db: Any,
    *,
    custom_templates: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """根据问题类型获取 SOP 优化建议。"""
    templates = custom_templates or _SOP_TEMPLATES
    suggestions = templates.get(issue_type, [])

    log.info(
        "sop_suggestions_queried",
        store_id=store_id,
        tenant_id=tenant_id,
        issue_type=issue_type,
        suggestion_count=len(suggestions),
    )

    return {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "issue_type": issue_type,
        "suggestions": suggestions,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  最佳实践推荐
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_best_practices(
    metric: str,
    tenant_id: str,
    db: Any,
    *,
    store_metrics: Optional[List[Dict[str, Any]]] = None,
    cases: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """根据指标推荐最佳实践。"""
    metrics = store_metrics or []
    all_cases = cases or []

    sorted_stores = sorted(metrics, key=lambda x: x.get("value", 0), reverse=True)
    top_stores = sorted_stores[:3]

    related_cases = [c for c in all_cases if c.get("tenant_id") == tenant_id and metric in c.get("tags", [])]

    recommendations = _build_recommendations(metric, top_stores)

    log.info(
        "best_practices_queried",
        tenant_id=tenant_id,
        metric=metric,
        top_store_count=len(top_stores),
        related_case_count=len(related_cases),
    )

    return {
        "metric": metric,
        "tenant_id": tenant_id,
        "top_stores": top_stores,
        "related_cases": related_cases,
        "recommendations": recommendations,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _build_recommendations(
    metric: str,
    top_stores: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """根据指标和 TOP 门店生成推荐。"""
    _metric_advice: Dict[str, str] = {
        "gross_margin": "学习高毛利门店的成本控制和产品定价策略",
        "waste_ratio": "参考低损耗门店的库存管理和备料标准",
        "customer_satisfaction": "学习高满意度门店的服务流程和客诉处理",
        "staff_efficiency": "参考高人效门店的排班和激励方案",
    }

    recommendations: List[Dict[str, Any]] = []
    advice = _metric_advice.get(metric, f"学习 {metric} 指标优秀门店的经验")

    if top_stores:
        recommendations.append(
            {
                "type": "benchmark",
                "title": f"标杆门店对标 — {metric}",
                "description": advice,
                "reference_stores": [s.get("store_id", "") for s in top_stores],
            }
        )

    return recommendations
