"""硬件配置中心 API 路由

提供硬件设备查询、门店配置管理、设备状态监控等 REST API。
所有接口需要 X-Tenant-ID header 进行租户隔离。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

import structlog

from ..device_registry import (
    DEVICE_CATEGORIES,
    DEVICE_REGISTRY,
    get_device,
    get_devices_by_category,
    get_recommended_config,
    search_devices,
)
from ..store_hardware_config import get_store_hardware_config

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/hardware", tags=["hardware"])


# ─── 请求/响应模型 ───

class DeviceConfigItem(BaseModel):
    """单个设备配置。"""
    device_key: str = Field(..., description="设备注册表标识")
    connection_params: dict = Field(default_factory=dict, description="连接参数")
    role: str = Field(default="", description="设备角色: cashier/kitchen/label")
    name: str = Field(default="", description="设备名称")
    dept_id: str = Field(default="", description="关联档口ID")


class StoreConfigRequest(BaseModel):
    """门店硬件配置请求。"""
    devices: list[DeviceConfigItem]


class AddDeviceRequest(BaseModel):
    """添加单个设备请求。"""
    device_key: str
    connection_params: dict = Field(default_factory=dict)
    role: str = ""
    name: str = ""
    dept_id: str = ""


class CreateTemplateRequest(BaseModel):
    """创建硬件模板请求。"""
    template_name: str
    devices: list[DeviceConfigItem]
    description: str = ""


class ApplyTemplateRequest(BaseModel):
    """应用模板请求。"""
    template_id: str
    connection_overrides: dict = Field(default_factory=dict)


class APIResponse(BaseModel):
    """统一 API 响应格式。"""
    ok: bool = True
    data: dict | list | None = None
    error: dict | None = None


# ─── 依赖注入 ───

def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    """从 header 获取租户 ID。"""
    return x_tenant_id


# ─── 设备查询接口 ───

@router.get("/categories", response_model=APIResponse)
async def list_categories() -> APIResponse:
    """获取所有设备品类。"""
    return APIResponse(data=DEVICE_CATEGORIES)


@router.get("/devices", response_model=APIResponse)
async def list_devices(
    brand: Optional[str] = Query(None, description="品牌关键词"),
    category: Optional[str] = Query(None, description="品类标识"),
    interface: Optional[str] = Query(None, description="接口类型"),
    protocol: Optional[str] = Query(None, description="协议类型"),
) -> APIResponse:
    """获取支持的设备清单（可筛选）。

    查询参数:
    - brand: 品牌关键词（模糊匹配），如 "商米", "北洋"
    - category: 品类标识，如 "printer", "pos_terminal"
    - interface: 接口类型，如 "ethernet", "usb"
    - protocol: 协议类型，如 "ESC/POS"
    """
    if brand or category or interface or protocol:
        devices = search_devices(brand=brand, category=category, interface=interface, protocol=protocol)
    else:
        devices = DEVICE_REGISTRY

    return APIResponse(data={"devices": devices, "total": len(devices)})


@router.get("/devices/{category}", response_model=APIResponse)
async def list_devices_by_category(category: str) -> APIResponse:
    """按品类筛选设备。

    Args:
        category: 品类标识，可选值见 /categories
    """
    if category not in DEVICE_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的品类: {category}，可选: {', '.join(DEVICE_CATEGORIES.keys())}",
        )

    devices = get_devices_by_category(category)
    return APIResponse(data={
        "category": category,
        "category_name": DEVICE_CATEGORIES[category],
        "devices": devices,
        "total": len(devices),
    })


@router.get("/devices/detail/{device_key}", response_model=APIResponse)
async def get_device_detail(device_key: str) -> APIResponse:
    """获取单个设备详细信息。"""
    try:
        device = get_device(device_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return APIResponse(data=device)


@router.get("/recommended/{store_size}", response_model=APIResponse)
async def get_recommended(store_size: str) -> APIResponse:
    """获取推荐门店硬件配置方案。

    Args:
        store_size: 门店规模 small / medium / large
    """
    if store_size not in ("small", "medium", "large"):
        raise HTTPException(status_code=400, detail="store_size 必须是 small/medium/large")

    config = get_recommended_config(store_size)
    # 展开设备详情
    detailed_config = {}
    for cat, keys in config.items():
        detailed_config[cat] = [
            {"device_key": k, **DEVICE_REGISTRY.get(k, {})}
            for k in keys
        ]

    return APIResponse(data={
        "store_size": store_size,
        "config": detailed_config,
    })


# ─── 门店硬件配置接口 ───

@router.post("/store/{store_id}/config", response_model=APIResponse)
async def configure_store(
    store_id: str,
    request: StoreConfigRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> APIResponse:
    """配置门店硬件设备。

    批量配置门店的所有硬件设备，会替换该门店的旧配置。
    """
    config = get_store_hardware_config()
    devices = [item.model_dump() for item in request.devices]

    try:
        results = await config.configure_store(store_id, devices, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "api.store_configured",
        store_id=store_id,
        device_count=len(results),
        tenant_id=tenant_id,
    )
    return APIResponse(data={"store_id": store_id, "devices": results})


@router.get("/store/{store_id}/config", response_model=APIResponse)
async def get_store_config(
    store_id: str,
    tenant_id: str = Depends(get_tenant_id),
) -> APIResponse:
    """获取门店硬件配置。"""
    config = get_store_hardware_config()
    devices = await config.get_store_config(store_id, tenant_id)
    return APIResponse(data={"store_id": store_id, "devices": devices, "total": len(devices)})


@router.post("/store/{store_id}/device", response_model=APIResponse)
async def add_store_device(
    store_id: str,
    request: AddDeviceRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> APIResponse:
    """向门店添加单个设备。"""
    config = get_store_hardware_config()
    try:
        result = await config.add_device(
            store_id=store_id,
            device_key=request.device_key,
            connection_params=request.connection_params,
            tenant_id=tenant_id,
            role=request.role,
            name=request.name,
            dept_id=request.dept_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return APIResponse(data=result)


@router.delete("/store/{store_id}/device/{instance_id}", response_model=APIResponse)
async def remove_store_device(
    store_id: str,
    instance_id: str,
    tenant_id: str = Depends(get_tenant_id),
) -> APIResponse:
    """从门店移除设备。"""
    config = get_store_hardware_config()
    try:
        await config.remove_device(store_id, instance_id, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return APIResponse(data={"removed": instance_id})


# ─── 设备状态与测试 ───

@router.get("/store/{store_id}/status", response_model=APIResponse)
async def get_store_status(
    store_id: str,
    tenant_id: str = Depends(get_tenant_id),
) -> APIResponse:
    """获取门店所有设备状态（缓存状态，不重新测试）。"""
    config = get_store_hardware_config()
    statuses = await config.get_device_status(store_id, tenant_id)
    online_count = sum(1 for s in statuses if s.get("last_status") == "online")
    return APIResponse(data={
        "store_id": store_id,
        "devices": statuses,
        "total": len(statuses),
        "online": online_count,
    })


@router.post("/store/{store_id}/test", response_model=APIResponse)
async def test_store_devices(
    store_id: str,
    tenant_id: str = Depends(get_tenant_id),
) -> APIResponse:
    """批量测试门店所有设备连通性。

    会逐一测试每个设备，返回连通性和延迟信息。
    """
    config = get_store_hardware_config()
    results = await config.test_all_devices(store_id, tenant_id)
    online_count = sum(1 for r in results if r.get("status") == "online")

    logger.info(
        "api.store_tested",
        store_id=store_id,
        total=len(results),
        online=online_count,
        tenant_id=tenant_id,
    )
    return APIResponse(data={
        "store_id": store_id,
        "results": results,
        "total": len(results),
        "online": online_count,
    })


@router.post("/store/{store_id}/test/{instance_id}", response_model=APIResponse)
async def test_single_device(
    store_id: str,
    instance_id: str,
    tenant_id: str = Depends(get_tenant_id),
) -> APIResponse:
    """测试单个设备连通性。"""
    config = get_store_hardware_config()
    try:
        result = await config.test_device(store_id, instance_id, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return APIResponse(data=result)


# ─── 硬件模板接口 ───

@router.post("/templates", response_model=APIResponse)
async def create_template(
    request: CreateTemplateRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> APIResponse:
    """创建硬件配置模板。"""
    config = get_store_hardware_config()
    devices = [item.model_dump() for item in request.devices]
    try:
        template = await config.create_store_template(
            template_name=request.template_name,
            devices=devices,
            tenant_id=tenant_id,
            description=request.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return APIResponse(data=template)


@router.get("/templates", response_model=APIResponse)
async def list_templates(
    tenant_id: str = Depends(get_tenant_id),
) -> APIResponse:
    """列出所有硬件配置模板。"""
    config = get_store_hardware_config()
    templates = await config.list_templates(tenant_id)
    return APIResponse(data={"templates": templates, "total": len(templates)})


@router.post("/store/{store_id}/apply-template", response_model=APIResponse)
async def apply_template(
    store_id: str,
    request: ApplyTemplateRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> APIResponse:
    """将硬件模板应用到门店。"""
    config = get_store_hardware_config()
    try:
        result = await config.apply_template(
            template_id=request.template_id,
            store_id=store_id,
            tenant_id=tenant_id,
            connection_overrides=request.connection_overrides,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return APIResponse(data={"store_id": store_id, "devices": result})
