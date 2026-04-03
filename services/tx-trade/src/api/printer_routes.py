"""打印机 API — 注册/打印/补打/状态/队列/配置/测试

路由前缀: /api/v1/printer
"""
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..services.print_manager import PrinterRole, get_print_manager

router = APIRouter(prefix="/api/v1/printer", tags=["printer"])


# ─── 请求/响应模型 ───


class RegisterPrinterReq(BaseModel):
    printer_id: Optional[str] = None
    ip: str = Field(..., description="打印机IP地址")
    port: int = Field(9100, description="端口号")
    role: str = Field(..., description="角色: cashier/kitchen/label")
    store_id: str = Field(..., description="门店ID")
    dept_id: Optional[str] = Field(None, description="关联档口ID（厨打用）")
    name: Optional[str] = Field(None, description="打印机名称")


class PrintReq(BaseModel):
    order_id: str = Field(..., description="订单ID")
    template_type: str = Field(..., description="模板类型: cashier_receipt/checkout_bill/shift_report/daily_report")
    store_id: str = Field(..., description="门店ID")
    order: dict = Field(..., description="订单/报表数据")
    store: Optional[dict] = Field(None, description="门店信息")
    payment: Optional[dict] = Field(None, description="支付信息")


class KitchenPrintReq(BaseModel):
    order_id: str
    store_id: str
    order: dict


class StoreConfigReq(BaseModel):
    store_id: str
    printers: list[dict] = Field(..., description="打印机配置列表 [{ip, port, role, dept_id, name}]")


class TestPrintReq(BaseModel):
    printer_id: str


# ─── 路由 ───


@router.post("/register")
async def register_printer(
    req: RegisterPrinterReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """注册打印机。"""
    import uuid

    mgr = get_print_manager()
    printer_id = req.printer_id or str(uuid.uuid4())

    try:
        # 验证 role
        PrinterRole(req.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效角色: {req.role}，可选: cashier/kitchen/label") from exc

    info = await mgr.register_printer(
        printer_id=printer_id,
        ip=req.ip,
        port=req.port,
        role=req.role,
        store_id=req.store_id,
        tenant_id=x_tenant_id,
        dept_id=req.dept_id,
        name=req.name,
    )
    return {"ok": True, "data": info.to_dict()}


@router.post("/print")
async def print_receipt(
    req: PrintReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """打印小票（指定模板+数据）。"""
    mgr = get_print_manager()
    try:
        task = await mgr.print_receipt(
            order_id=req.order_id,
            template_type=req.template_type,
            tenant_id=x_tenant_id,
            store_id=req.store_id,
            order=req.order,
            store=req.store,
            payment=req.payment,
        )
        return {"ok": True, "data": task.to_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=f"打印机连接失败: {exc}") from exc


@router.post("/kitchen")
async def print_kitchen_order(
    req: KitchenPrintReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """厨打分单 — 按档口分发。"""
    mgr = get_print_manager()
    try:
        tasks = await mgr.print_kitchen_order(
            order_id=req.order_id,
            tenant_id=x_tenant_id,
            store_id=req.store_id,
            order=req.order,
        )
        return {"ok": True, "data": [t.to_dict() for t in tasks]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reprint/{task_id}")
async def reprint(task_id: str):
    """补打。"""
    mgr = get_print_manager()
    try:
        task = await mgr.reprint(task_id)
        return {"ok": True, "data": task.to_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=f"打印机连接失败: {exc}") from exc


@router.get("/status/{store_id}")
async def printer_status(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取门店所有打印机状态。"""
    mgr = get_print_manager()
    statuses = await mgr.get_printer_status(store_id)
    return {"ok": True, "data": statuses}


@router.get("/queue/{store_id}")
async def print_queue(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取门店打印队列。"""
    mgr = get_print_manager()
    queue = await mgr.get_print_queue(store_id)
    return {"ok": True, "data": queue}


@router.post("/config")
async def configure_store(
    req: StoreConfigReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """门店打印机批量配置。"""
    mgr = get_print_manager()
    try:
        infos = await mgr.configure_store_printers(
            store_id=req.store_id,
            config=req.printers,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": [i.to_dict() for i in infos]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/test")
async def test_print(
    req: TestPrintReq,
):
    """测试打印（打印测试页）。"""
    mgr = get_print_manager()
    try:
        task = await mgr.test_print(req.printer_id)
        return {"ok": True, "data": task.to_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=f"打印机连接失败: {exc}") from exc
