"""
自然语言问数（NLQ）BFF

POST /api/v1/nlq/query   — 提交自然语言问题，返回结构化数据 + SQL + 图表配置
GET  /api/v1/nlq/history — 历史问答记录
GET  /api/v1/nlq/suggestions — 热门问题推荐
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/nlq", tags=["nlq"])


class NLQRequest(BaseModel):
    query: str
    store_id: str | None = None
    date_range: dict | None = None  # {"start": "2026-04-01", "end": "2026-04-07"}


async def _get_db_with_tenant(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


@router.post("/query")
async def nlq_query(
    body: NLQRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """
    自然语言问数主接口。
    Phase 1: 调用 tx-brain 的 reasoning_engine 解析意图 → 生成 SQL → 执行 → 返回结构化结果。
    当前实现为骨架，返回意图解析结果和 mock 数据结构，待 tx-brain 集成后替换。
    """
    query = body.query.strip()
    if not query:
        return {"ok": False, "error": "query is empty"}

    # TODO: 调用 tx-brain reasoning_engine 做意图解析 + SQL 生成
    # 当前返回骨架响应
    return {
        "ok": True,
        "data": {
            "query": query,
            "intent": "revenue_analysis",  # 待 tx-brain 实现
            "sql": f"-- 待 tx-brain 生成 SQL\n-- Query: {query}",
            "columns": ["门店", "今日营业额", "昨日营业额", "环比"],
            "rows": [],  # 待数据库执行结果填充
            "chart_type": "bar",  # 建议图表类型
            "summary": f"已收到问题：{query}。AI分析功能将在 Phase 2 完全激活。",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/suggestions")
async def get_suggestions(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> dict:
    """热门/推荐问题列表"""
    return {
        "ok": True,
        "data": [
            {"id": "s1", "text": "今天各门店营业额对比", "category": "营收"},
            {"id": "s2", "text": "本周哪个菜品点单最多", "category": "菜品"},
            {"id": "s3", "text": "上个月会员复购率趋势", "category": "会员"},
            {"id": "s4", "text": "毛利率低于30%的菜品有哪些", "category": "成本"},
            {"id": "s5", "text": "本周翻台率最高的门店", "category": "运营"},
            {"id": "s6", "text": "今日待处理的Agent行动", "category": "Agent"},
        ],
    }


@router.get("/history")
async def get_query_history(
    limit: int = 20,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """问答历史（Phase 1：返回空，后续接入持久化）"""
    return {"ok": True, "data": [], "total": 0}
