"""
数据字典 & 审计日志查询 API 路由

端点:
  GET    /api/v1/system/dictionaries              — 字典列表
  POST   /api/v1/system/dictionaries              — 创建字典
  PUT    /api/v1/system/dictionaries/{code}        — 更新字典
  DELETE /api/v1/system/dictionaries/{code}        — 删除字典
  GET    /api/v1/system/dictionaries/{code}/items  — 字典项列表
  POST   /api/v1/system/dictionaries/{code}/items  — 创建字典项
  PUT    /api/v1/system/dictionaries/{code}/items/{item_id} — 更新字典项
  DELETE /api/v1/system/dictionaries/{code}/items/{item_id} — 删除字典项
  GET    /api/v1/system/audit-logs                 — 审计日志查询

所有端点需要 X-Tenant-ID header（由 TenantMiddleware 校验）。
当前为 Mock 实现，后续接入真实数据库。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/system", tags=["system-dictionary"])

# ────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ────────────────────────────────────────────────────────────────────


class DictionarySchema(BaseModel):
    id: str
    code: str
    name: str
    description: str = ""
    is_system: bool = False
    is_enabled: bool = True
    item_count: int = 0
    created_at: str


class DictionaryItemSchema(BaseModel):
    id: str
    dictionary_id: str
    code: str
    label: str
    value: str
    color: Optional[str] = None
    icon: Optional[str] = None
    sort_order: int = 0
    is_enabled: bool = True
    created_at: str


class CreateDictionaryRequest(BaseModel):
    code: str = Field(..., pattern=r"^[a-z_]+$")
    name: str
    description: str = ""


class UpdateDictionaryRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_enabled: Optional[bool] = None


class CreateDictionaryItemRequest(BaseModel):
    code: str
    label: str
    value: str
    color: Optional[str] = None
    icon: Optional[str] = None
    sort_order: int = 0


class UpdateDictionaryItemRequest(BaseModel):
    label: Optional[str] = None
    value: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    is_enabled: Optional[bool] = None


class AuditLogSchema(BaseModel):
    id: str
    timestamp: str
    user_name: str
    user_id: str
    action: str
    resource_type: str
    resource_id: str
    ip_address: str
    old_data: Optional[dict] = None
    new_data: Optional[dict] = None
    description: str


# ────────────────────────────────────────────────────────────────────
# Mock data store (in-memory, replaced by DB later)
# ────────────────────────────────────────────────────────────────────

_now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

_DICTIONARIES: list[DictionarySchema] = [
    DictionarySchema(id="1", code="order_status", name="订单状态", description="订单全生命周期状态", is_system=True, is_enabled=True, item_count=6, created_at=_now),
    DictionarySchema(id="2", code="payment_method", name="支付方式", description="支持的支付渠道", is_system=True, is_enabled=True, item_count=5, created_at=_now),
    DictionarySchema(id="3", code="dish_category", name="菜品分类", description="菜品的大类/小类", is_system=False, is_enabled=True, item_count=8, created_at=_now),
    DictionarySchema(id="4", code="member_level", name="会员等级", description="会员分级体系", is_system=True, is_enabled=True, item_count=4, created_at=_now),
    DictionarySchema(id="5", code="employee_role", name="员工角色", description="员工职位角色", is_system=True, is_enabled=True, item_count=7, created_at=_now),
    DictionarySchema(id="6", code="leave_type", name="请假类型", description="请假审批类型", is_system=False, is_enabled=True, item_count=5, created_at=_now),
    DictionarySchema(id="7", code="coupon_type", name="优惠券类型", description="优惠券发放类型", is_system=False, is_enabled=True, item_count=4, created_at=_now),
    DictionarySchema(id="8", code="delivery_platform", name="外卖平台", description="接入的外卖平台", is_system=True, is_enabled=True, item_count=3, created_at=_now),
]

_DICTIONARY_ITEMS: dict[str, list[DictionaryItemSchema]] = {
    "order_status": [
        DictionaryItemSchema(id="101", dictionary_id="1", code="pending", label="待确认", value="pending", color="#faad14", icon="ClockCircleOutlined", sort_order=1, is_enabled=True, created_at=_now),
        DictionaryItemSchema(id="102", dictionary_id="1", code="confirmed", label="已确认", value="confirmed", color="#1890ff", icon="CheckCircleOutlined", sort_order=2, is_enabled=True, created_at=_now),
        DictionaryItemSchema(id="103", dictionary_id="1", code="preparing", label="制作中", value="preparing", color="#722ed1", icon="FireOutlined", sort_order=3, is_enabled=True, created_at=_now),
        DictionaryItemSchema(id="104", dictionary_id="1", code="ready", label="待取餐", value="ready", color="#52c41a", icon="BellOutlined", sort_order=4, is_enabled=True, created_at=_now),
        DictionaryItemSchema(id="105", dictionary_id="1", code="completed", label="已完成", value="completed", color="#389e0d", icon="CheckOutlined", sort_order=5, is_enabled=True, created_at=_now),
        DictionaryItemSchema(id="106", dictionary_id="1", code="cancelled", label="已取消", value="cancelled", color="#ff4d4f", icon="CloseCircleOutlined", sort_order=6, is_enabled=True, created_at=_now),
    ],
    "payment_method": [
        DictionaryItemSchema(id="201", dictionary_id="2", code="wechat", label="微信支付", value="wechat", color="#07C160", sort_order=1, is_enabled=True, created_at=_now),
        DictionaryItemSchema(id="202", dictionary_id="2", code="alipay", label="支付宝", value="alipay", color="#1677FF", sort_order=2, is_enabled=True, created_at=_now),
        DictionaryItemSchema(id="203", dictionary_id="2", code="cash", label="现金", value="cash", color="#faad14", sort_order=3, is_enabled=True, created_at=_now),
        DictionaryItemSchema(id="204", dictionary_id="2", code="unionpay", label="银联卡", value="unionpay", color="#cf1322", sort_order=4, is_enabled=True, created_at=_now),
        DictionaryItemSchema(id="205", dictionary_id="2", code="member_balance", label="会员余额", value="member_balance", color="#FF6B35", sort_order=5, is_enabled=True, created_at=_now),
    ],
}

_AUDIT_LOGS: list[AuditLogSchema] = [
    AuditLogSchema(id="1", timestamp="2026-04-02 10:23:45", user_name="李淳", user_id="u001", action="update", resource_type="dish", resource_id="dish-001", ip_address="192.168.1.100", old_data={"price": 68}, new_data={"price": 78}, description="修改菜品价格"),
    AuditLogSchema(id="2", timestamp="2026-04-02 10:15:30", user_name="张管理", user_id="u002", action="create", resource_type="member", resource_id="mem-100", ip_address="192.168.1.101", old_data=None, new_data={"name": "王先生", "level": "gold"}, description="新建会员"),
    AuditLogSchema(id="3", timestamp="2026-04-02 09:55:12", user_name="刘店长", user_id="u003", action="delete", resource_type="order", resource_id="ord-999", ip_address="10.0.0.55", old_data={"order_no": "TX20260402001", "total": 288}, new_data=None, description="删除已取消订单"),
    AuditLogSchema(id="4", timestamp="2026-04-02 09:30:00", user_name="李淳", user_id="u001", action="login", resource_type="system", resource_id="-", ip_address="120.229.10.5", old_data=None, new_data=None, description="管理后台登录"),
    AuditLogSchema(id="5", timestamp="2026-04-02 09:00:05", user_name="张管理", user_id="u002", action="export", resource_type="order", resource_id="batch-0402", ip_address="192.168.1.101", old_data=None, new_data={"format": "csv", "count": 1523}, description="导出订单数据"),
    AuditLogSchema(id="6", timestamp="2026-04-01 18:45:22", user_name="王总监", user_id="u004", action="approve", resource_type="employee", resource_id="emp-055", ip_address="192.168.1.102", old_data={"status": "pending"}, new_data={"status": "approved"}, description="审批员工请假申请"),
]


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, status: int = 400) -> dict:
    return {"ok": False, "data": None, "error": {"message": msg, "status": status}}


# ────────────────────────────────────────────────────────────────────
# Dictionary CRUD
# ────────────────────────────────────────────────────────────────────


@router.get("/dictionaries")
async def list_dictionaries(
    request: Request,
    keyword: str = Query("", description="搜索关键词"),
) -> dict:
    """字典列表"""
    results = _DICTIONARIES
    if keyword:
        results = [
            d for d in results
            if keyword in d.name or keyword in d.code or keyword in d.description
        ]
    return _ok({"items": [d.model_dump() for d in results], "total": len(results)})


@router.post("/dictionaries")
async def create_dictionary(request: Request, body: CreateDictionaryRequest) -> dict:
    """创建字典"""
    if any(d.code == body.code for d in _DICTIONARIES):
        return _err(f"字典编码 '{body.code}' 已存在")

    new_dict = DictionarySchema(
        id=str(uuid4())[:8],
        code=body.code,
        name=body.name,
        description=body.description,
        is_system=False,
        is_enabled=True,
        item_count=0,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    _DICTIONARIES.append(new_dict)
    logger.info("dictionary_created", code=body.code, name=body.name)
    return _ok(new_dict.model_dump())


@router.put("/dictionaries/{code}")
async def update_dictionary(
    request: Request,
    code: str,
    body: UpdateDictionaryRequest,
) -> dict:
    """更新字典"""
    for idx, d in enumerate(_DICTIONARIES):
        if d.code == code:
            updated = d.model_dump()
            for k, v in body.model_dump(exclude_none=True).items():
                updated[k] = v
            _DICTIONARIES[idx] = DictionarySchema(**updated)
            logger.info("dictionary_updated", code=code)
            return _ok(_DICTIONARIES[idx].model_dump())

    return _err(f"字典 '{code}' 不存在", 404)


@router.delete("/dictionaries/{code}")
async def delete_dictionary(request: Request, code: str) -> dict:
    """删除字典（系统字典不可删除）"""
    for idx, d in enumerate(_DICTIONARIES):
        if d.code == code:
            if d.is_system:
                return _err("系统字典不可删除")
            _DICTIONARIES.pop(idx)
            _DICTIONARY_ITEMS.pop(code, None)
            logger.info("dictionary_deleted", code=code)
            return _ok({"deleted": code})

    return _err(f"字典 '{code}' 不存在", 404)


# ────────────────────────────────────────────────────────────────────
# Dictionary Item CRUD
# ────────────────────────────────────────────────────────────────────


@router.get("/dictionaries/{code}/items")
async def list_dictionary_items(request: Request, code: str) -> dict:
    """字典项列表"""
    items = _DICTIONARY_ITEMS.get(code, [])
    sorted_items = sorted(items, key=lambda x: x.sort_order)
    return _ok({"items": [i.model_dump() for i in sorted_items], "total": len(sorted_items)})


@router.post("/dictionaries/{code}/items")
async def create_dictionary_item(
    request: Request,
    code: str,
    body: CreateDictionaryItemRequest,
) -> dict:
    """创建字典项"""
    # find parent dict
    parent = next((d for d in _DICTIONARIES if d.code == code), None)
    if not parent:
        return _err(f"字典 '{code}' 不存在", 404)

    if code not in _DICTIONARY_ITEMS:
        _DICTIONARY_ITEMS[code] = []

    new_item = DictionaryItemSchema(
        id=str(uuid4())[:8],
        dictionary_id=parent.id,
        code=body.code,
        label=body.label,
        value=body.value,
        color=body.color,
        icon=body.icon,
        sort_order=body.sort_order or len(_DICTIONARY_ITEMS[code]) + 1,
        is_enabled=True,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    _DICTIONARY_ITEMS[code].append(new_item)

    # update item_count
    for idx, d in enumerate(_DICTIONARIES):
        if d.code == code:
            updated = d.model_dump()
            updated["item_count"] = len(_DICTIONARY_ITEMS[code])
            _DICTIONARIES[idx] = DictionarySchema(**updated)
            break

    logger.info("dictionary_item_created", dict_code=code, item_code=body.code)
    return _ok(new_item.model_dump())


@router.put("/dictionaries/{code}/items/{item_id}")
async def update_dictionary_item(
    request: Request,
    code: str,
    item_id: str,
    body: UpdateDictionaryItemRequest,
) -> dict:
    """更新字典项"""
    items = _DICTIONARY_ITEMS.get(code, [])
    for idx, item in enumerate(items):
        if item.id == item_id:
            updated = item.model_dump()
            for k, v in body.model_dump(exclude_none=True).items():
                updated[k] = v
            items[idx] = DictionaryItemSchema(**updated)
            logger.info("dictionary_item_updated", dict_code=code, item_id=item_id)
            return _ok(items[idx].model_dump())

    return _err(f"字典项 '{item_id}' 不存在", 404)


@router.delete("/dictionaries/{code}/items/{item_id}")
async def delete_dictionary_item(
    request: Request,
    code: str,
    item_id: str,
) -> dict:
    """删除字典项"""
    items = _DICTIONARY_ITEMS.get(code, [])
    for idx, item in enumerate(items):
        if item.id == item_id:
            items.pop(idx)
            # update item_count
            for didx, d in enumerate(_DICTIONARIES):
                if d.code == code:
                    updated = d.model_dump()
                    updated["item_count"] = len(items)
                    _DICTIONARIES[didx] = DictionarySchema(**updated)
                    break
            logger.info("dictionary_item_deleted", dict_code=code, item_id=item_id)
            return _ok({"deleted": item_id})

    return _err(f"字典项 '{item_id}' 不存在", 404)


# ────────────────────────────────────────────────────────────────────
# Audit Logs
# ────────────────────────────────────────────────────────────────────


@router.get("/audit-logs")
async def list_audit_logs(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user_name: str = Query("", description="操作人筛选"),
    action: str = Query("", description="操作类型筛选"),
    resource_type: str = Query("", description="资源类型筛选"),
    start_date: str = Query("", description="开始日期 YYYY-MM-DD"),
    end_date: str = Query("", description="结束日期 YYYY-MM-DD"),
) -> dict:
    """审计日志查询（分页+筛选）"""
    results = list(_AUDIT_LOGS)

    if user_name:
        results = [r for r in results if user_name in r.user_name]
    if action:
        results = [r for r in results if r.action == action]
    if resource_type:
        results = [r for r in results if r.resource_type == resource_type]
    if start_date:
        results = [r for r in results if r.timestamp >= start_date]
    if end_date:
        results = [r for r in results if r.timestamp <= end_date + " 23:59:59"]

    total = len(results)
    start = (page - 1) * size
    page_items = results[start : start + size]

    return _ok({"items": [r.model_dump() for r in page_items], "total": total})
