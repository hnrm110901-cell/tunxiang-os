"""Hub API — 屯象科技运维管理端

跨租户操作，不走 RLS。需要 platform-admin 级别认证。
仅 hub.tunxiangos.com 可访问（Nginx IP 白名单保护）。
"""
from typing import Optional

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/hub", tags=["hub"])


# ─── 商户管理 ───

@router.get("/merchants")
async def list_merchants(status: Optional[str] = None, page: int = 1, size: int = 20):
    """列出所有商户"""
    return {"ok": True, "data": {"items": [
        {"id": "m1", "name": "尝在一起", "template": "standard", "stores": 5, "status": "active", "expires": "2027-03-22"},
        {"id": "m2", "name": "徐记海鲜", "template": "pro", "stores": 100, "status": "active", "expires": "2027-06-30"},
        {"id": "m3", "name": "最黔线", "template": "standard", "stores": 8, "status": "trial", "expires": "2026-04-22"},
        {"id": "m4", "name": "尚宫厨", "template": "lite", "stores": 3, "status": "active", "expires": "2027-01-15"},
    ], "total": 4}}

@router.post("/merchants")
async def create_merchant(data: dict):
    """新建商户（开户）"""
    return {"ok": True, "data": {"merchant_id": "new", "status": "created"}}

@router.patch("/merchants/{merchant_id}")
async def update_merchant(merchant_id: str, data: dict):
    """更新商户（续费/升级/停用）"""
    return {"ok": True, "data": {"merchant_id": merchant_id, "updated": True}}


# ─── 全局门店 ───

@router.get("/stores")
async def list_all_stores(merchant_id: Optional[str] = None, online: Optional[bool] = None, page: int = 1, size: int = 20):
    """全局门店列表（跨商户）"""
    return {"ok": True, "data": {"items": [
        {"store_id": "s1", "name": "芙蓉路店", "merchant": "尝在一起", "online": True, "last_sync": "2026-03-23T15:30:00", "version": "3.3.0"},
        {"store_id": "s2", "name": "岳麓店", "merchant": "尝在一起", "online": True, "last_sync": "2026-03-23T15:28:00", "version": "3.3.0"},
        {"store_id": "s3", "name": "五一广场店", "merchant": "徐记海鲜", "online": False, "last_sync": "2026-03-23T10:00:00", "version": "3.2.0"},
    ], "total": 113}}


# ─── 模板管理 ───

@router.get("/templates")
async def list_templates():
    """模板列表"""
    from .templates import compare_templates
    return {"ok": True, "data": compare_templates()}

@router.post("/merchants/{merchant_id}/template")
async def assign_template(merchant_id: str, template_id: str):
    """为商户分配模板"""
    return {"ok": True, "data": {"merchant_id": merchant_id, "template": template_id}}


# ─── Adapter 监控 ───

@router.get("/adapters")
async def list_adapter_status():
    """所有 Adapter 连接状态"""
    return {"ok": True, "data": [
        {"adapter": "pinzhi", "merchant": "尝在一起", "status": "connected", "last_sync": "2026-03-23T15:25:00", "success_rate": 99.2},
        {"adapter": "aoqiwei", "merchant": "徐记海鲜", "status": "connected", "last_sync": "2026-03-23T15:20:00", "success_rate": 98.5},
        {"adapter": "kingdee", "merchant": "徐记海鲜", "status": "error", "last_sync": "2026-03-23T08:00:00", "success_rate": 85.0, "error": "Token expired"},
    ]}


# ─── Agent 全局监控 ───

@router.get("/agents/health")
async def agent_global_health():
    """所有商户的 Agent 健康度"""
    return {"ok": True, "data": {
        "total_executions_today": 12500,
        "success_rate": 97.3,
        "constraint_violations": 23,
        "top_agents": [
            {"agent": "discount_guard", "executions": 3200, "violations": 15},
            {"agent": "inventory_alert", "executions": 2800, "violations": 5},
            {"agent": "serve_dispatch", "executions": 2100, "violations": 3},
        ],
    }}


# ─── 计费账单 ───

@router.get("/billing")
async def get_billing(month: Optional[str] = None):
    """计费账单"""
    return {"ok": True, "data": {
        "month": month or "2026-03",
        "total_revenue_yuan": 325000,
        "breakdown": {
            "haas": {"label": "硬件租赁(HaaS)", "yuan": 100000, "pct": 30.8},
            "saas": {"label": "软件服务(SaaS)", "yuan": 175000, "pct": 53.8},
            "ai": {"label": "AI增值", "yuan": 50000, "pct": 15.4},
        },
        "merchants": 50,
        "active_stores": 380,
        "arr_yuan": 3900000,
    }}


# ─── 部署管理 ───

@router.get("/deployment/mac-minis")
async def list_mac_minis():
    """Mac mini 舰队状态"""
    return {"ok": True, "data": [
        {"store": "芙蓉路店", "ip": "100.64.1.10", "tailscale": "online", "version": "3.3.0", "last_heartbeat": "2026-03-23T15:30:00", "cpu_pct": 12, "mem_pct": 45},
        {"store": "岳麓店", "ip": "100.64.1.11", "tailscale": "online", "version": "3.3.0", "last_heartbeat": "2026-03-23T15:29:00", "cpu_pct": 8, "mem_pct": 38},
        {"store": "五一广场店", "ip": "100.64.1.20", "tailscale": "offline", "version": "3.2.0", "last_heartbeat": "2026-03-23T10:00:00", "cpu_pct": 0, "mem_pct": 0},
    ]}

@router.post("/deployment/push-update")
async def push_update(store_ids: list[str], target_version: str):
    """远程推送软件更新"""
    return {"ok": True, "data": {"pushed": len(store_ids), "target_version": target_version}}


# ─── 工单系统 ───

@router.get("/tickets")
async def list_tickets(status: Optional[str] = None):
    """工单列表"""
    return {"ok": True, "data": {"items": [
        {"id": "T001", "merchant": "尝在一起", "title": "POS打印机故障", "priority": "high", "status": "open", "created": "2026-03-23T14:00:00", "assignee": "张工"},
        {"id": "T002", "merchant": "徐记海鲜", "title": "金蝶凭证同步失败", "priority": "medium", "status": "in_progress", "created": "2026-03-23T10:00:00", "assignee": "李工"},
    ], "total": 2}}

@router.post("/tickets")
async def create_ticket(data: dict):
    return {"ok": True, "data": {"ticket_id": "T003"}}


# ─── 平台数据 ───

@router.get("/platform/stats")
async def platform_stats():
    """平台运营数据"""
    return {"ok": True, "data": {
        "total_merchants": 50,
        "total_stores": 380,
        "active_stores_today": 352,
        "total_orders_today": 28500,
        "gmv_today_yuan": 4250000,
        "agent_calls_today": 12500,
        "avg_response_ms": 45,
    }}
