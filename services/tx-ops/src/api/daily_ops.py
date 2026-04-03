"""日清日结 API"""
from typing import Optional

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/ops", tags=["ops"])


@router.get("/daily/{store_id}")
async def get_daily_flow(store_id: str, date: Optional[str] = None):
    """获取门店当日流程状态"""
    from ..services.daily_ops_service import compute_flow_progress, get_flow_timeline
    statuses = {f"E{i}": "pending" for i in range(1, 9)}
    progress = compute_flow_progress(statuses)
    timeline = get_flow_timeline(statuses)
    return {"ok": True, "data": {"store_id": store_id, "date": date or "today", "progress": progress, "timeline": timeline}}


@router.post("/daily/{store_id}/nodes/{node_code}/start")
async def start_node(store_id: str, node_code: str, operator_id: str = ""):
    """开始执行节点"""
    from ..services.daily_ops_service import get_node_definition
    defn = get_node_definition(node_code)
    if not defn:
        return {"ok": False, "error": {"code": "INVALID_NODE", "message": f"Unknown node: {node_code}"}}
    return {"ok": True, "data": {"node_code": node_code, "name": defn["name"], "status": "in_progress", "check_items": defn["check_items"]}}


@router.post("/daily/{store_id}/nodes/{node_code}/complete")
async def complete_node(store_id: str, node_code: str, check_results: list[dict] = []):
    """完成节点（提交检查结果）"""
    from ..services.daily_ops_service import compute_node_check_result
    result = compute_node_check_result(check_results)
    return {"ok": True, "data": {"node_code": node_code, "check_result": result, "status": "completed"}}


@router.post("/daily/{store_id}/nodes/{node_code}/skip")
async def skip_node(store_id: str, node_code: str, reason: str = ""):
    """跳过节点"""
    return {"ok": True, "data": {"node_code": node_code, "status": "skipped", "reason": reason}}


@router.get("/daily/{store_id}/timeline")
async def get_timeline(store_id: str):
    """获取流程时间轴"""
    from ..services.daily_ops_service import get_flow_timeline
    statuses = {f"E{i}": "pending" for i in range(1, 9)}
    return {"ok": True, "data": {"timeline": get_flow_timeline(statuses)}}


# 复盘
@router.get("/daily/{store_id}/review")
async def get_review(store_id: str, date: Optional[str] = None):
    """获取复盘数据（E7）"""
    return {"ok": True, "data": {"top3_issues": [], "agent_suggestions": [], "kpi_comparison": {}}}


# 整改
@router.get("/daily/{store_id}/rectifications")
async def list_rectifications(store_id: str, status: Optional[str] = None):
    """整改任务列表（E8）"""
    return {"ok": True, "data": {"items": [], "total": 0}}


@router.post("/daily/{store_id}/rectifications")
async def create_rectification(store_id: str, data: dict):
    """新建整改任务"""
    return {"ok": True, "data": {"rectification_id": "new", "status": "pending"}}
