"""
主动服务建议 + 三约束状态 API Routes (Phase 3-B)

GET  /api/v1/service/suggestions/{order_id}
     获取该订单的主动服务建议列表

GET  /api/v1/service/suggestions/all
     params: store_id
     获取所有桌台的建议汇总（店长视角）

POST /api/v1/service/suggestions/{order_id}/{suggestion_type}/dismiss
     服务员忽略某条建议

GET  /api/v1/orders/{order_id}/constraint-status
     快速返回三约束状态（聚合查询，目标 < 100ms）
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query

from ..services.proactive_service_agent import (
    ConstraintStatus,
    ServiceSuggestion,
    dismiss_suggestion,
    get_constraint_status,
    get_service_suggestions,
    get_table_suggestions,
)

router = APIRouter()

# ─── 依赖注入辅助 ───

async def _get_db():
    """
    尝试获取数据库会话。
    如果 shared.ontology 不可用（测试/离线环境），返回 None，
    各 service 函数会自动降级到 Mock 数据。
    """
    try:
        from shared.ontology.src.database import async_session_factory
        async with async_session_factory() as session:
            yield session
    except Exception:  # noqa: BLE001 — MLPS3-P0: 离线/测试环境DB不可用，降级为None
        yield None


def _get_tenant_id(x_tenant_id: str = Header(default='demo-tenant')) -> str:
    return x_tenant_id


# ─── 响应序列化辅助 ───

def _suggestion_to_dict(s: ServiceSuggestion) -> dict[str, Any]:
    return {
        'type': s.type,
        'message': s.message,
        'urgency': s.urgency,
        'action_label': s.action_label,
        'action_data': s.action_data,
    }


def _constraint_to_dict(cs: ConstraintStatus) -> dict[str, Any]:
    return {
        'margin': {
            'ok': cs.margin.ok,
            'pct': cs.margin.pct,
            'level': cs.margin.level,
        },
        'food_safety': {
            'ok': cs.food_safety.ok,
            'issues': cs.food_safety.issues,
            'level': cs.food_safety.level,
        },
        'service_time': {
            'ok': cs.service_time.ok,
            'elapsed_min': cs.service_time.elapsed_min,
            'limit_min': cs.service_time.limit_min,
            'level': cs.service_time.level,
        },
    }


# ─── 路由 ───

@router.get('/api/v1/service/suggestions/all')
async def list_all_suggestions(
    store_id: str = Query(..., description='门店ID'),
    tenant_id: str = Depends(_get_tenant_id),
    db=Depends(_get_db),
):
    """
    店长视角：获取所有在台桌台的主动服务建议汇总。
    返回 {table_no: [suggestion, ...]}
    """
    result = await get_table_suggestions(
        store_id=store_id,
        tenant_id=tenant_id,
        db=db,
    )
    serialized = {
        table_no: [_suggestion_to_dict(s) for s in suggs]
        for table_no, suggs in result.items()
    }
    return {'ok': True, 'data': serialized}


@router.get('/api/v1/service/suggestions/{order_id}')
async def get_order_suggestions(
    order_id: str,
    tenant_id: str = Depends(_get_tenant_id),
    db=Depends(_get_db),
):
    """
    服务员视角：获取指定订单的主动服务建议列表。
    """
    suggestions = await get_service_suggestions(
        order_id=order_id,
        tenant_id=tenant_id,
        db=db,
    )
    return {
        'ok': True,
        'data': [_suggestion_to_dict(s) for s in suggestions],
    }


@router.post('/api/v1/service/suggestions/{order_id}/{suggestion_type}/dismiss')
async def dismiss_order_suggestion(
    order_id: str,
    suggestion_type: str,
    tenant_id: str = Depends(_get_tenant_id),
    db=Depends(_get_db),
):
    """
    服务员忽略某条建议，本次营业内不再重复提示。
    suggestion_type: upsell / refill / dessert / checkout_hint
    """
    dismiss_suggestion(
        order_id=order_id,
        suggestion_type=suggestion_type,
        tenant_id=tenant_id,
        db=db,
    )
    return {'ok': True, 'data': {'dismissed': suggestion_type}}


@router.get('/api/v1/orders/{order_id}/constraint-status')
async def get_order_constraint_status(
    order_id: str,
    tenant_id: str = Depends(_get_tenant_id),
    db=Depends(_get_db),
):
    """
    三约束实时状态（毛利 / 食安 / 出餐时长）。
    并发聚合查询，目标响应时间 < 100ms。
    DB 不可用时自动降级返回演示数据。
    """
    status = await get_constraint_status(
        order_id=order_id,
        tenant_id=tenant_id,
        db=db,
    )
    return {'ok': True, 'data': _constraint_to_dict(status)}
