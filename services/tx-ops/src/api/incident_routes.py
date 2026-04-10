"""门店异常事件中心 API 路由（Mock 数据版）

端点:
  GET   /api/v1/ops/incidents              异常列表
  GET   /api/v1/ops/incidents/summary      异常统计
  POST  /api/v1/ops/incidents              上报异常
  PATCH /api/v1/ops/incidents/{id}/status  更新状态

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/ops/incidents", tags=["ops-incidents"])
log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_VALID_TYPES = {"equipment", "food_safety", "customer_complaint", "staff", "supply", "environment", "security", "other"}
_VALID_SEVERITIES = {"critical", "high", "medium", "low"}
_VALID_STATUSES = {"reported", "confirmed", "handling", "resolved", "closed"}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ReportIncidentRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    store_name: str = Field(..., description="门店名称")
    incident_type: str = Field(..., description="异常类型")
    severity: str = Field("medium", description="严重度")
    title: str = Field(..., max_length=200)
    description: str = Field(..., description="详细描述")
    reporter_id: str = Field(..., description="上报人ID")
    reporter_name: str = Field(..., description="上报人姓名")
    evidence_urls: List[str] = Field(default_factory=list, description="证据图片/视频")
    location: Optional[str] = Field(None, description="事发位置: 前厅/后厨/收银台/仓库等")


class UpdateIncidentStatusRequest(BaseModel):
    status: str = Field(..., description="目标状态")
    handler_id: Optional[str] = Field(None, description="处理人ID")
    handler_name: Optional[str] = Field(None, description="处理人姓名")
    remark: Optional[str] = Field(None, description="处理备注")
    resolution: Optional[str] = Field(None, description="解决方案（resolved时必填）")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Mock 数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MOCK_INCIDENTS: List[Dict[str, Any]] = [
    {
        "id": "inc-001",
        "store_id": "store-001",
        "store_name": "尝在一起(芙蓉广场店)",
        "incident_type": "equipment",
        "severity": "high",
        "title": "后厨1号灶台点火器故障",
        "description": "1号灶台电子点火器无法点火，需要手动打火。影响出餐效率。已使用打火机临时替代。",
        "status": "handling",
        "reporter_id": "emp-201",
        "reporter_name": "厨师长陈明",
        "handler_id": "emp-301",
        "handler_name": "设备维护张工",
        "evidence_urls": ["https://oss.tunxiang.com/inc/001-stove.jpg"],
        "location": "后厨",
        "reported_at": "2026-04-10T11:20:00+08:00",
        "updated_at": "2026-04-10T12:00:00+08:00",
        "timeline": [
            {"time": "2026-04-10T11:20:00+08:00", "action": "reported", "operator": "陈明", "remark": "灶台点火器失灵"},
            {"time": "2026-04-10T11:35:00+08:00", "action": "confirmed", "operator": "店长李华", "remark": "已确认，联系维修"},
            {"time": "2026-04-10T12:00:00+08:00", "action": "handling", "operator": "张工", "remark": "维修师傅已到店，检查中"},
        ],
    },
    {
        "id": "inc-002",
        "store_id": "store-002",
        "store_name": "尝在一起(五一广场店)",
        "incident_type": "customer_complaint",
        "severity": "critical",
        "title": "顾客投诉菜品有异物",
        "description": "12号桌顾客反映酸菜鱼中发现一根头发丝。已安抚顾客并免单处理。需排查后厨卫生。",
        "status": "handling",
        "reporter_id": "emp-202",
        "reporter_name": "前厅经理王芳",
        "handler_id": "emp-302",
        "handler_name": "店长刘强",
        "evidence_urls": ["https://oss.tunxiang.com/inc/002-complaint.jpg"],
        "location": "前厅",
        "reported_at": "2026-04-10T12:45:00+08:00",
        "updated_at": "2026-04-10T13:10:00+08:00",
        "timeline": [
            {"time": "2026-04-10T12:45:00+08:00", "action": "reported", "operator": "王芳", "remark": "顾客投诉异物，已免单安抚"},
            {"time": "2026-04-10T12:50:00+08:00", "action": "confirmed", "operator": "刘强", "remark": "立即排查后厨，要求全员戴帽检查"},
            {"time": "2026-04-10T13:10:00+08:00", "action": "handling", "operator": "刘强", "remark": "后厨检查中，加强出品检查"},
        ],
    },
    {
        "id": "inc-003",
        "store_id": "store-003",
        "store_name": "最黔线(河西店)",
        "incident_type": "food_safety",
        "severity": "critical",
        "title": "冷库温度异常报警",
        "description": "冷库温度传感器报警，温度升至-5度（标准-18度）。疑似压缩机故障。已紧急转移食材到备用冷柜。",
        "status": "confirmed",
        "reporter_id": "emp-203",
        "reporter_name": "后厨刘师傅",
        "handler_id": None,
        "handler_name": None,
        "evidence_urls": ["https://oss.tunxiang.com/inc/003-freezer-1.jpg", "https://oss.tunxiang.com/inc/003-freezer-2.jpg"],
        "location": "仓库",
        "reported_at": "2026-04-10T09:15:00+08:00",
        "updated_at": "2026-04-10T09:30:00+08:00",
        "timeline": [
            {"time": "2026-04-10T09:15:00+08:00", "action": "reported", "operator": "刘师傅", "remark": "冷库温度报警"},
            {"time": "2026-04-10T09:30:00+08:00", "action": "confirmed", "operator": "店长张华", "remark": "已确认，食材已转移，联系冷库维修"},
        ],
    },
    {
        "id": "inc-004",
        "store_id": "store-001",
        "store_name": "尝在一起(芙蓉广场店)",
        "incident_type": "supply",
        "severity": "medium",
        "title": "酸菜鱼原料（黑鱼）缺货",
        "description": "今日黑鱼到货量不足，预计下午3点后无法出品酸菜鱼。供应商表示明早可补货。",
        "status": "resolved",
        "reporter_id": "emp-204",
        "reporter_name": "采购员赵丽",
        "handler_id": "emp-204",
        "handler_name": "采购员赵丽",
        "evidence_urls": [],
        "location": "仓库",
        "reported_at": "2026-04-10T08:30:00+08:00",
        "updated_at": "2026-04-10T10:00:00+08:00",
        "timeline": [
            {"time": "2026-04-10T08:30:00+08:00", "action": "reported", "operator": "赵丽", "remark": "黑鱼到货量不足20斤"},
            {"time": "2026-04-10T09:00:00+08:00", "action": "handling", "operator": "赵丽", "remark": "联系备用供应商紧急调货"},
            {"time": "2026-04-10T10:00:00+08:00", "action": "resolved", "operator": "赵丽", "remark": "备用供应商送达30斤，可支撑今日出品"},
        ],
    },
    {
        "id": "inc-005",
        "store_id": "store-004",
        "store_name": "尚宫厨(万达店)",
        "incident_type": "environment",
        "severity": "low",
        "title": "前厅空调制冷效果不佳",
        "description": "前厅3号空调出风口温度偏高，顾客反映用餐区偏热。已调低设定温度。",
        "status": "reported",
        "reporter_id": "emp-205",
        "reporter_name": "服务员小周",
        "handler_id": None,
        "handler_name": None,
        "evidence_urls": [],
        "location": "前厅",
        "reported_at": "2026-04-10T14:00:00+08:00",
        "updated_at": "2026-04-10T14:00:00+08:00",
        "timeline": [
            {"time": "2026-04-10T14:00:00+08:00", "action": "reported", "operator": "小周", "remark": "3号空调制冷不足"},
        ],
    },
    {
        "id": "inc-006",
        "store_id": "store-002",
        "store_name": "尝在一起(五一广场店)",
        "incident_type": "staff",
        "severity": "medium",
        "title": "午班服务员缺岗2人",
        "description": "午班应到8人实到6人，2人临时请病假。已从晚班调配1人支援。",
        "status": "closed",
        "reporter_id": "emp-206",
        "reporter_name": "前厅经理王芳",
        "handler_id": "emp-302",
        "handler_name": "店长刘强",
        "evidence_urls": [],
        "location": "前厅",
        "reported_at": "2026-04-10T10:30:00+08:00",
        "updated_at": "2026-04-10T11:00:00+08:00",
        "timeline": [
            {"time": "2026-04-10T10:30:00+08:00", "action": "reported", "operator": "王芳", "remark": "2人请病假"},
            {"time": "2026-04-10T10:45:00+08:00", "action": "handling", "operator": "刘强", "remark": "从晚班调配1人"},
            {"time": "2026-04-10T11:00:00+08:00", "action": "closed", "operator": "刘强", "remark": "调配到位，午高峰运转正常"},
        ],
    },
    {
        "id": "inc-007",
        "store_id": "store-005",
        "store_name": "最黔线(岳麓店)",
        "incident_type": "security",
        "severity": "high",
        "title": "监控摄像头离线",
        "description": "后厨2号监控摄像头从上午10点起离线，无法远程查看后厨画面。",
        "status": "reported",
        "reporter_id": "emp-207",
        "reporter_name": "IT运维小李",
        "handler_id": None,
        "handler_name": None,
        "evidence_urls": [],
        "location": "后厨",
        "reported_at": "2026-04-10T10:15:00+08:00",
        "updated_at": "2026-04-10T10:15:00+08:00",
        "timeline": [
            {"time": "2026-04-10T10:15:00+08:00", "action": "reported", "operator": "小李", "remark": "后厨2号摄像头离线"},
        ],
    },
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/summary")
async def get_incidents_summary(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """异常事件统计汇总。"""
    log.info("incidents_summary_requested", tenant_id=x_tenant_id)

    by_type: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    by_store: Dict[str, int] = {}

    for inc in _MOCK_INCIDENTS:
        by_type[inc["incident_type"]] = by_type.get(inc["incident_type"], 0) + 1
        by_severity[inc["severity"]] = by_severity.get(inc["severity"], 0) + 1
        by_status[inc["status"]] = by_status.get(inc["status"], 0) + 1
        by_store[inc["store_id"]] = by_store.get(inc["store_id"], 0) + 1

    return {
        "ok": True,
        "data": {
            "total": len(_MOCK_INCIDENTS),
            "by_type": by_type,
            "by_severity": by_severity,
            "by_status": by_status,
            "unresolved": sum(1 for i in _MOCK_INCIDENTS if i["status"] not in {"resolved", "closed"}),
            "critical_unresolved": sum(1 for i in _MOCK_INCIDENTS if i["severity"] == "critical" and i["status"] not in {"resolved", "closed"}),
            "top_stores": [
                {"store_id": sid, "store_name": next((i["store_name"] for i in _MOCK_INCIDENTS if i["store_id"] == sid), sid), "count": cnt}
                for sid, cnt in sorted(by_store.items(), key=lambda x: -x[1])[:5]
            ],
            "avg_resolve_minutes": 85,
        },
    }


@router.get("")
async def list_incidents(
    store_id: Optional[str] = Query(None),
    incident_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """异常事件列表，支持筛选。"""
    if incident_type and incident_type not in _VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"incident_type 必须是 {_VALID_TYPES} 之一")
    if severity and severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")
    if status and status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 必须是 {_VALID_STATUSES} 之一")

    log.info("incidents_listed", tenant_id=x_tenant_id)

    filtered = _MOCK_INCIDENTS[:]
    if store_id:
        filtered = [i for i in filtered if i["store_id"] == store_id]
    if incident_type:
        filtered = [i for i in filtered if i["incident_type"] == incident_type]
    if severity:
        filtered = [i for i in filtered if i["severity"] == severity]
    if status:
        filtered = [i for i in filtered if i["status"] == status]
    if q:
        q_lower = q.lower()
        filtered = [i for i in filtered if q_lower in i["title"].lower() or q_lower in i["description"].lower()]

    total = len(filtered)
    offset = (page - 1) * size
    items = filtered[offset: offset + size]

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.post("", status_code=201)
async def report_incident(
    body: ReportIncidentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """上报异常事件。"""
    if body.incident_type not in _VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"incident_type 必须是 {_VALID_TYPES} 之一")
    if body.severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")

    now = datetime.now(tz=timezone.utc).isoformat()
    new_incident: Dict[str, Any] = {
        "id": f"inc-{uuid.uuid4().hex[:8]}",
        "store_id": body.store_id,
        "store_name": body.store_name,
        "incident_type": body.incident_type,
        "severity": body.severity,
        "title": body.title,
        "description": body.description,
        "status": "reported",
        "reporter_id": body.reporter_id,
        "reporter_name": body.reporter_name,
        "handler_id": None,
        "handler_name": None,
        "evidence_urls": body.evidence_urls,
        "location": body.location,
        "reported_at": now,
        "updated_at": now,
        "timeline": [
            {"time": now, "action": "reported", "operator": body.reporter_name, "remark": body.description[:100]},
        ],
    }

    log.info("incident_reported", incident_id=new_incident["id"],
             store_id=body.store_id, incident_type=body.incident_type,
             severity=body.severity, tenant_id=x_tenant_id)
    return {"ok": True, "data": new_incident}


@router.patch("/{incident_id}/status")
async def update_incident_status(
    incident_id: str,
    body: UpdateIncidentStatusRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """更新异常事件状态。"""
    if body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 必须是 {_VALID_STATUSES} 之一")

    log.info("incident_status_updated", incident_id=incident_id,
             new_status=body.status, tenant_id=x_tenant_id)

    for inc in _MOCK_INCIDENTS:
        if inc["id"] == incident_id:
            now = datetime.now(tz=timezone.utc).isoformat()
            updated = {**inc, "status": body.status, "updated_at": now}
            if body.handler_id:
                updated["handler_id"] = body.handler_id
                updated["handler_name"] = body.handler_name
            updated["timeline"] = inc["timeline"] + [{
                "time": now,
                "action": body.status,
                "operator": body.handler_name or "system",
                "remark": body.remark or body.resolution or "",
            }]
            return {"ok": True, "data": updated}

    raise HTTPException(status_code=404, detail="异常事件不存在")
