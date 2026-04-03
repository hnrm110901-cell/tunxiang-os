"""总部管理 API — 门店克隆 / 法人公司 / 批量操作

12 个端点：
- 门店克隆(3): 预览 / 单店克隆 / 批量克隆
- 法人公司(5): 创建法人 / 创建公司 / 门店归属 / 架构树 / 公司门店
- 批量操作(4): 批量创建 / 批量激活 / 批量停用 / Excel导入
"""

from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from services.legal_entity import (
    assign_store_to_company,
    create_company,
    create_legal_entity,
    get_company_stores,
    get_entity_structure,
)
from services.store_batch import (
    batch_activate,
    batch_create_stores,
    batch_deactivate,
    import_stores_from_excel,
)
from services.store_clone import batch_clone, clone_store, get_clone_preview

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CloneStoreReq(BaseModel):
    source_store_id: str
    new_store_name: str
    new_address: str


class NewStoreItem(BaseModel):
    name: str
    address: str


class BatchCloneReq(BaseModel):
    source_store_id: str
    new_stores: List[NewStoreItem]


class CreateLegalEntityReq(BaseModel):
    name: str
    tax_id: str
    type: str  # corporation / non_corporation


class CreateCompanyReq(BaseModel):
    name: str
    legal_entity_id: str


class AssignStoreReq(BaseModel):
    store_id: str
    company_id: str


class StoreInfo(BaseModel):
    name: str
    address: str
    brand_id: Optional[str] = None
    business_type: Optional[str] = None


class BatchCreateReq(BaseModel):
    stores: List[StoreInfo]


class BatchActivateReq(BaseModel):
    store_ids: List[str]


class BatchDeactivateReq(BaseModel):
    store_ids: List[str]
    reason: str


class ImportStoresReq(BaseModel):
    file_data: str


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _get_tenant(x_tenant_id: Optional[str]) -> str:
    """从 Header 提取 tenant_id，缺失时使用默认值。"""
    return x_tenant_id or "default_tenant"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  门店克隆（3 个端点）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/stores/{store_id}/clone-preview")
async def api_clone_preview(
    store_id: str,
    x_tenant_id: Optional[str] = Header(None),
):
    """克隆预览：查看源门店将复制哪些数据。"""
    tenant_id = _get_tenant(x_tenant_id)
    try:
        result = get_clone_preview(store_id, tenant_id)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stores/clone")
async def api_clone_store(
    req: CloneStoreReq,
    x_tenant_id: Optional[str] = Header(None),
):
    """单店克隆：深拷贝源门店全部配置到新门店。"""
    tenant_id = _get_tenant(x_tenant_id)
    try:
        result = clone_store(
            source_store_id=req.source_store_id,
            new_store_name=req.new_store_name,
            new_address=req.new_address,
            tenant_id=tenant_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stores/batch-clone")
async def api_batch_clone(
    req: BatchCloneReq,
    x_tenant_id: Optional[str] = Header(None),
):
    """批量克隆：从同一源门店克隆多家新门店。"""
    tenant_id = _get_tenant(x_tenant_id)
    try:
        new_stores = [{"name": s.name, "address": s.address} for s in req.new_stores]
        result = batch_clone(
            source_store_id=req.source_store_id,
            new_stores=new_stores,
            tenant_id=tenant_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  法人/公司管理（5 个端点）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/legal-entities")
async def api_create_legal_entity(
    req: CreateLegalEntityReq,
    x_tenant_id: Optional[str] = Header(None),
):
    """创建法人实体。"""
    tenant_id = _get_tenant(x_tenant_id)
    try:
        result = create_legal_entity(
            name=req.name,
            tax_id=req.tax_id,
            type=req.type,
            tenant_id=tenant_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/companies")
async def api_create_company(
    req: CreateCompanyReq,
    x_tenant_id: Optional[str] = Header(None),
):
    """创建公司（隶属于某法人实体）。"""
    tenant_id = _get_tenant(x_tenant_id)
    try:
        result = create_company(
            name=req.name,
            legal_entity_id=req.legal_entity_id,
            tenant_id=tenant_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stores/assign-company")
async def api_assign_store(
    req: AssignStoreReq,
    x_tenant_id: Optional[str] = Header(None),
):
    """门店归属公司。"""
    tenant_id = _get_tenant(x_tenant_id)
    try:
        result = assign_store_to_company(
            store_id=req.store_id,
            company_id=req.company_id,
            tenant_id=tenant_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/entity-structure")
async def api_entity_structure(
    x_tenant_id: Optional[str] = Header(None),
):
    """集团法人架构树。"""
    tenant_id = _get_tenant(x_tenant_id)
    result = get_entity_structure(tenant_id)
    return {"ok": True, "data": result}


@router.get("/companies/{company_id}/stores")
async def api_company_stores(
    company_id: str,
    x_tenant_id: Optional[str] = Header(None),
):
    """公司下属门店。"""
    tenant_id = _get_tenant(x_tenant_id)
    try:
        result = get_company_stores(company_id, tenant_id)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  批量操作（4 个端点）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/stores/batch-create")
async def api_batch_create(
    req: BatchCreateReq,
    x_tenant_id: Optional[str] = Header(None),
):
    """批量创建门店。"""
    tenant_id = _get_tenant(x_tenant_id)
    try:
        stores = [s.model_dump() for s in req.stores]
        result = batch_create_stores(stores, tenant_id)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stores/batch-activate")
async def api_batch_activate(
    req: BatchActivateReq,
    x_tenant_id: Optional[str] = Header(None),
):
    """批量激活门店。"""
    tenant_id = _get_tenant(x_tenant_id)
    try:
        result = batch_activate(req.store_ids, tenant_id)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stores/batch-deactivate")
async def api_batch_deactivate(
    req: BatchDeactivateReq,
    x_tenant_id: Optional[str] = Header(None),
):
    """批量停用门店。"""
    tenant_id = _get_tenant(x_tenant_id)
    try:
        result = batch_deactivate(req.store_ids, req.reason, tenant_id)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stores/import")
async def api_import_stores(
    req: ImportStoresReq,
    x_tenant_id: Optional[str] = Header(None),
):
    """Excel/CSV 导入门店。"""
    tenant_id = _get_tenant(x_tenant_id)
    try:
        result = import_stores_from_excel(req.file_data, tenant_id)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
