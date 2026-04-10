"""门店管理 & 桌台配置 API

端点（10个）：
  GET    /api/v1/trade/stores                — 门店列表
  POST   /api/v1/trade/stores                — 新增门店
  GET    /api/v1/trade/stores/{store_id}     — 门店详情
  PATCH  /api/v1/trade/stores/{store_id}     — 更新门店状态
  DELETE /api/v1/trade/stores/{store_id}     — 删除门店（软删）

  GET    /api/v1/trade/tables                — 桌台列表（按 store_id 过滤）
  POST   /api/v1/trade/tables                — 新增桌台
  GET    /api/v1/trade/tables/{table_id}     — 桌台详情
  PATCH  /api/v1/trade/tables/{table_id}     — 修改桌台
  DELETE /api/v1/trade/tables/{table_id}     — 删除桌台（软删）

统一响应格式: {"ok": bool, "data": {}, "error": None}
所有接口需 X-Tenant-ID header。
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["store-management"])

# ─── 工具 ──────────────────────────────────────────────────────────────────────

def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _get_tenant_id(request: Request) -> str:
    return request.headers.get("X-Tenant-ID", "")

# ─── Mock 存储（内存，重启清空） ───────────────────────────────────────────────

DEMO_TENANT_ID = "10000000-0000-0000-0000-000000000001"
DEMO_STORE_ID  = "20000000-0000-0000-0000-000000000001"

_STORES: List[dict] = [
    {
        "id": DEMO_STORE_ID, "tenant_id": DEMO_TENANT_ID,
        "name": "徐记海鲜·五一广场旗舰店", "type": "direct", "city": "长沙",
        "address": "湖南省长沙市天心区五一广场8号", "status": "active",
        "today_revenue_fen": 0, "table_count": 15,
        "manager": "李淳", "phone": "0731-88888888",
        "created_at": "2026-04-04T00:00:00Z", "is_deleted": False,
    },
    {
        "id": "s1", "tenant_id": "demo",
        "name": "五一广场店", "type": "direct", "city": "长沙",
        "address": "五一广场1号", "status": "active",
        "today_revenue_fen": 1280000, "table_count": 40,
        "manager": "李明", "phone": "13900001111",
        "created_at": "2024-03-01T00:00:00Z", "is_deleted": False,
    },
    {
        "id": "s2", "tenant_id": "demo",
        "name": "东塘店", "type": "direct", "city": "长沙",
        "address": "东塘路88号", "status": "active",
        "today_revenue_fen": 860000, "table_count": 28,
        "manager": "王芳", "phone": "13900002222",
        "created_at": "2024-05-15T00:00:00Z", "is_deleted": False,
    },
    {
        "id": "s3", "tenant_id": "demo",
        "name": "河西万达店", "type": "franchise", "city": "长沙",
        "address": "万达广场3楼", "status": "active",
        "today_revenue_fen": 720000, "table_count": 32,
        "manager": "赵强", "phone": "13900003333",
        "created_at": "2024-08-20T00:00:00Z", "is_deleted": False,
    },
    {
        "id": "s4", "tenant_id": "demo",
        "name": "株洲神农城店", "type": "franchise", "city": "株洲",
        "address": "神农城商圈B2", "status": "suspended",
        "today_revenue_fen": 0, "table_count": 24,
        "manager": "张建国", "phone": "13900004444",
        "created_at": "2024-11-10T00:00:00Z", "is_deleted": False,
    },
]

_TABLES: List[dict] = [
    # 演示门店桌台（徐记海鲜·五一广场旗舰店）
    {"id": "d01", "store_id": DEMO_STORE_ID, "number": "A01", "area": "大厅A区", "capacity": 4,  "status": "available", "shape": "square",    "note": "", "is_deleted": False},
    {"id": "d02", "store_id": DEMO_STORE_ID, "number": "A02", "area": "大厅A区", "capacity": 4,  "status": "available", "shape": "square",    "note": "", "is_deleted": False},
    {"id": "d03", "store_id": DEMO_STORE_ID, "number": "A03", "area": "大厅A区", "capacity": 6,  "status": "occupied",  "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "d04", "store_id": DEMO_STORE_ID, "number": "A04", "area": "大厅A区", "capacity": 6,  "status": "available", "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "d05", "store_id": DEMO_STORE_ID, "number": "A05", "area": "大厅A区", "capacity": 8,  "status": "available", "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "d06", "store_id": DEMO_STORE_ID, "number": "B01", "area": "大厅B区", "capacity": 4,  "status": "available", "shape": "square",    "note": "", "is_deleted": False},
    {"id": "d07", "store_id": DEMO_STORE_ID, "number": "B02", "area": "大厅B区", "capacity": 4,  "status": "reserved",  "shape": "square",    "note": "", "is_deleted": False},
    {"id": "d08", "store_id": DEMO_STORE_ID, "number": "B03", "area": "大厅B区", "capacity": 6,  "status": "available", "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "d09", "store_id": DEMO_STORE_ID, "number": "B04", "area": "大厅B区", "capacity": 8,  "status": "available", "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "d10", "store_id": DEMO_STORE_ID, "number": "B05", "area": "大厅B区", "capacity": 10, "status": "available", "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "d11", "store_id": DEMO_STORE_ID, "number": "VIP1","area": "贵宾包厢", "capacity": 8,  "status": "available", "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "d12", "store_id": DEMO_STORE_ID, "number": "VIP2","area": "贵宾包厢", "capacity": 10, "status": "available", "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "d13", "store_id": DEMO_STORE_ID, "number": "VIP3","area": "贵宾包厢", "capacity": 12, "status": "available", "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "d14", "store_id": DEMO_STORE_ID, "number": "VIP4","area": "贵宾包厢", "capacity": 16, "status": "occupied",  "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "d15", "store_id": DEMO_STORE_ID, "number": "T01", "area": "室外露台", "capacity": 4,  "status": "available", "shape": "round",     "note": "", "is_deleted": False},
    # 原 mock 门店桌台
    {"id": "t1",  "store_id": "s1", "number": "A01", "area": "大厅", "capacity": 4,  "status": "available", "shape": "square",    "note": "", "is_deleted": False},
    {"id": "t2",  "store_id": "s1", "number": "A02", "area": "大厅", "capacity": 2,  "status": "occupied",  "shape": "round",     "note": "", "is_deleted": False},
    {"id": "t3",  "store_id": "s1", "number": "A03", "area": "大厅", "capacity": 6,  "status": "available", "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "t4",  "store_id": "s1", "number": "A04", "area": "大厅", "capacity": 4,  "status": "reserved",  "shape": "square",    "note": "", "is_deleted": False},
    {"id": "t5",  "store_id": "s1", "number": "A05", "area": "大厅", "capacity": 4,  "status": "cleaning",  "shape": "square",    "note": "", "is_deleted": False},
    {"id": "t6",  "store_id": "s1", "number": "A06", "area": "大厅", "capacity": 8,  "status": "available", "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "t7",  "store_id": "s1", "number": "A07", "area": "大厅", "capacity": 2,  "status": "occupied",  "shape": "round",     "note": "", "is_deleted": False},
    {"id": "t8",  "store_id": "s1", "number": "A08", "area": "大厅", "capacity": 4,  "status": "available", "shape": "square",    "note": "", "is_deleted": False},
    {"id": "t9",  "store_id": "s1", "number": "B01", "area": "包厢", "capacity": 8,  "status": "reserved",  "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "t10", "store_id": "s1", "number": "B02", "area": "包厢", "capacity": 10, "status": "available", "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "t11", "store_id": "s1", "number": "B03", "area": "包厢", "capacity": 12, "status": "occupied",  "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "t12", "store_id": "s1", "number": "B04", "area": "包厢", "capacity": 8,  "status": "available", "shape": "rectangle", "note": "", "is_deleted": False},
    {"id": "t13", "store_id": "s1", "number": "C01", "area": "室外", "capacity": 4,  "status": "available", "shape": "square",    "note": "", "is_deleted": False},
    {"id": "t14", "store_id": "s1", "number": "C02", "area": "室外", "capacity": 4,  "status": "available", "shape": "square",    "note": "", "is_deleted": False},
    {"id": "t15", "store_id": "s1", "number": "C03", "area": "室外", "capacity": 2,  "status": "occupied",  "shape": "round",     "note": "", "is_deleted": False},
    {"id": "t16", "store_id": "s1", "number": "D01", "area": "吧台", "capacity": 2,  "status": "available", "shape": "round",     "note": "", "is_deleted": False},
    {"id": "t17", "store_id": "s1", "number": "D02", "area": "吧台", "capacity": 2,  "status": "occupied",  "shape": "round",     "note": "", "is_deleted": False},
    {"id": "t18", "store_id": "s1", "number": "D03", "area": "吧台", "capacity": 2,  "status": "available", "shape": "round",     "note": "", "is_deleted": False},
]

# ─── 请求/响应模型 ─────────────────────────────────────────────────────────────

class StoreCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    type: str = Field("direct", pattern="^(direct|franchise)$")
    city: str = Field(..., min_length=1, max_length=32)
    address: str = Field(..., min_length=1, max_length=128)
    status: str = Field("active", pattern="^(active|suspended)$")
    manager: str = Field("", max_length=32)
    phone: Optional[str] = Field(None, max_length=20)

class StorePatch(BaseModel):
    status: Optional[str] = Field(None, pattern="^(active|suspended)$")
    name: Optional[str] = Field(None, max_length=64)
    manager: Optional[str] = Field(None, max_length=32)
    phone: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = Field(None, max_length=128)

class TableCreate(BaseModel):
    store_id: str
    number: str = Field(..., min_length=1, max_length=16)
    area: str = Field("大厅", max_length=16)
    capacity: int = Field(4, ge=1, le=30)
    shape: str = Field("square", pattern="^(square|round|rectangle)$")
    note: Optional[str] = Field("", max_length=128)

class TablePatch(BaseModel):
    number: Optional[str] = Field(None, max_length=16)
    area: Optional[str] = Field(None, max_length=16)
    capacity: Optional[int] = Field(None, ge=1, le=30)
    shape: Optional[str] = Field(None, pattern="^(square|round|rectangle)$")
    status: Optional[str] = Field(None, pattern="^(available|occupied|reserved|cleaning)$")
    note: Optional[str] = Field(None, max_length=128)

# ─── 门店端点 ──────────────────────────────────────────────────────────────────

@router.get("/api/v1/trade/stores")
async def list_stores(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
):
    """门店列表（支持按状态/类型/城市过滤）"""
    items = [s for s in _STORES if not s["is_deleted"]]
    if status:
        items = [s for s in items if s["status"] == status]
    if type:
        items = [s for s in items if s["type"] == type]
    if city:
        items = [s for s in items if s["city"] == city]

    total = len(items)
    start = (page - 1) * size
    paged = items[start: start + size]
    return _ok({"items": paged, "total": total, "page": page, "size": size})


@router.post("/api/v1/trade/stores", status_code=201)
async def create_store(request: Request, body: StoreCreate):
    """新增门店"""
    new_store = {
        "id": str(uuid.uuid4()),
        "tenant_id": _get_tenant_id(request),
        "name": body.name,
        "type": body.type,
        "city": body.city,
        "address": body.address,
        "status": body.status,
        "today_revenue_fen": 0,
        "table_count": 0,
        "manager": body.manager,
        "phone": body.phone or "",
        "created_at": _now_iso(),
        "is_deleted": False,
    }
    _STORES.append(new_store)
    return _ok(new_store)


@router.get("/api/v1/trade/stores/{store_id}")
async def get_store(request: Request, store_id: str):
    """门店详情"""
    store = next((s for s in _STORES if s["id"] == store_id and not s["is_deleted"]), None)
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")
    return _ok(store)


@router.patch("/api/v1/trade/stores/{store_id}")
async def patch_store(request: Request, store_id: str, body: StorePatch):
    """更新门店信息/状态"""
    store = next((s for s in _STORES if s["id"] == store_id and not s["is_deleted"]), None)
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    if body.status is not None:
        store["status"] = body.status
    if body.name is not None:
        store["name"] = body.name
    if body.manager is not None:
        store["manager"] = body.manager
    if body.phone is not None:
        store["phone"] = body.phone
    if body.address is not None:
        store["address"] = body.address

    store["updated_at"] = _now_iso()
    return _ok(store)


@router.delete("/api/v1/trade/stores/{store_id}")
async def delete_store(request: Request, store_id: str):
    """软删除门店"""
    store = next((s for s in _STORES if s["id"] == store_id and not s["is_deleted"]), None)
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")
    store["is_deleted"] = True
    store["deleted_at"] = _now_iso()
    return _ok({"message": "Store deleted", "id": store_id})


# ─── 桌台端点 ──────────────────────────────────────────────────────────────────

@router.get("/api/v1/trade/tables")
async def list_tables(
    request: Request,
    store_id: Optional[str] = Query(None),
    area: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
):
    """桌台列表（按 store_id / area / status 过滤）"""
    items = [t for t in _TABLES if not t["is_deleted"]]
    if store_id:
        items = [t for t in items if t["store_id"] == store_id]
    if area:
        items = [t for t in items if t["area"] == area]
    if status:
        items = [t for t in items if t["status"] == status]

    total = len(items)
    start = (page - 1) * size
    paged = items[start: start + size]
    return _ok({"items": paged, "total": total, "page": page, "size": size})


@router.post("/api/v1/trade/tables", status_code=201)
async def create_table(request: Request, body: TableCreate):
    """新增桌台"""
    # 校验门店存在
    store = next((s for s in _STORES if s["id"] == body.store_id and not s["is_deleted"]), None)
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    new_table = {
        "id": str(uuid.uuid4()),
        "store_id": body.store_id,
        "number": body.number,
        "area": body.area,
        "capacity": body.capacity,
        "status": "available",
        "shape": body.shape,
        "note": body.note or "",
        "created_at": _now_iso(),
        "is_deleted": False,
    }
    _TABLES.append(new_table)
    # 更新门店桌台数
    store["table_count"] = len([t for t in _TABLES if t["store_id"] == body.store_id and not t["is_deleted"]])
    return _ok(new_table)


@router.get("/api/v1/trade/tables/{table_id}")
async def get_table(request: Request, table_id: str):
    """桌台详情"""
    table = next((t for t in _TABLES if t["id"] == table_id and not t["is_deleted"]), None)
    if table is None:
        raise HTTPException(status_code=404, detail="Table not found")
    return _ok(table)


@router.patch("/api/v1/trade/tables/{table_id}")
async def patch_table(request: Request, table_id: str, body: TablePatch):
    """修改桌台配置"""
    table = next((t for t in _TABLES if t["id"] == table_id and not t["is_deleted"]), None)
    if table is None:
        raise HTTPException(status_code=404, detail="Table not found")

    for field_name, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            table[field_name] = value

    table["updated_at"] = _now_iso()
    return _ok(table)


@router.delete("/api/v1/trade/tables/{table_id}")
async def delete_table(request: Request, table_id: str):
    """软删除桌台"""
    table = next((t for t in _TABLES if t["id"] == table_id and not t["is_deleted"]), None)
    if table is None:
        raise HTTPException(status_code=404, detail="Table not found")

    table["is_deleted"] = True
    table["deleted_at"] = _now_iso()

    # 更新门店桌台数
    store = next((s for s in _STORES if s["id"] == table["store_id"]), None)
    if store:
        store["table_count"] = len([
            t for t in _TABLES if t["store_id"] == table["store_id"] and not t["is_deleted"]
        ])

    return _ok({"message": "Table deleted", "id": table_id})
