"""打印模板路由 — 活鲜称重单 / 宴席通知单 / 企业挂账单

端点（ESC/POS base64，TXBridge.print 直接使用）：
  POST /api/v1/print/weigh-ticket              生成活鲜称重单打印数据（ESC/POS base64）
  POST /api/v1/print/banquet-notice            生成宴席通知单打印数据（ESC/POS base64）
  POST /api/v1/print/credit-ticket             生成企业挂账单打印数据（ESC/POS base64）

端点（语义标记文本，前端 TXBridge.print(content) 或网络打印）：
  POST /api/v1/print/live-seafood-receipt      活鲜称重单（语义标记文本）
  GET  /api/v1/print/live-seafood-receipt/preview  活鲜称重单 Mock 预览
  POST /api/v1/print/banquet-notice-v2         宴席通知单（语义标记文本，新格式）
  GET  /api/v1/print/banquet-notice-v2/preview 宴席通知单 Mock 预览

返回：
  ESC/POS 端点：{"ok": true, "data": {"base64": "...", "content_type": "application/escpos"}}
  语义标记端点：{"ok": true, "data": {"content": "...", "printer_hint": "receipt"}}
前端调用：TXBridge.print(data.base64) 或 TXBridge.print(data.content)
"""
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..services.print_template_service import (
    generate_banquet_notice,
    generate_credit_account_ticket,
    generate_weigh_ticket,
)
from ..utils.print_templates import (
    _mock_banquet_notice,
    _mock_live_seafood_receipt,
    render_banquet_notice,
    render_live_seafood_receipt,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/print", tags=["print-template"])


def _tenant(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 请求模型 ──────────────────────────────────────────────────────────────────

class StoreConfigModel(BaseModel):
    paper_width_mm: int = Field(default=80, description="纸宽毫米：58 或 80")


class WeighTicketReq(BaseModel):
    """活鲜称重单请求。"""
    store_name: str = Field(..., description="门店名称")
    table_no: Optional[str] = Field(default="", description="桌号")
    waiter_name: Optional[str] = Field(default="", description="服务员姓名")
    weigh_time: Optional[str] = Field(default=None, description="称重时间，ISO格式")
    dish_name: str = Field(..., description="活鲜品种名称")
    tank_name: Optional[str] = Field(default="", description="鱼缸/暂养区名称")
    weight_gram: float = Field(..., ge=0, description="称重克数")
    unit_price_fen: int = Field(..., ge=0, description="单价（分）")
    price_unit: str = Field(default="500g", description="单价单位：500g|kg|g")
    amount_fen: int = Field(..., ge=0, description="应收金额（分）")
    ticket_no: Optional[str] = Field(default="", description="单据编号")
    store_config: Optional[StoreConfigModel] = None


class BanquetDishItem(BaseModel):
    dish_name: str
    quantity: Optional[str] = ""
    unit: Optional[str] = "份"
    notes: Optional[str] = ""


class BanquetSectionModel(BaseModel):
    section_type: Optional[str] = ""
    section_name: Optional[str] = ""
    sort_order: int = 0
    dishes: list[BanquetDishItem] = Field(default_factory=list)


class BanquetSessionModel(BaseModel):
    store_name: str
    contract_no: Optional[str] = ""
    customer_name: Optional[str] = ""
    customer_phone: Optional[str] = ""
    start_time: Optional[str] = None
    table_count: int = 0
    pax_per_table: int = 0
    banquet_type: Optional[str] = "宴席"
    menu_name: Optional[str] = ""
    special_notes: Optional[str] = ""
    printed_by: Optional[str] = ""
    print_time: Optional[str] = None


class BanquetNoticeReq(BaseModel):
    session: BanquetSessionModel
    menu_sections: list[BanquetSectionModel] = Field(default_factory=list)
    store_config: Optional[StoreConfigModel] = None


class CreditOrderItem(BaseModel):
    item_name: str
    quantity: int = 1
    unit_price_fen: int = 0
    subtotal_fen: int = 0


class CreditOrderModel(BaseModel):
    store_name: str
    order_no: Optional[str] = ""
    table_no: Optional[str] = ""
    order_time: Optional[str] = None
    items: list[CreditOrderItem] = Field(default_factory=list)
    total_amount_fen: int = 0
    final_amount_fen: int = 0
    discount_amount_fen: int = 0
    cashier_name: Optional[str] = ""


class CreditInfoModel(BaseModel):
    company_name: str = Field(..., description="挂账单位名称")
    company_code: Optional[str] = ""
    contact_name: Optional[str] = ""
    contact_phone: Optional[str] = ""
    credit_limit_fen: Optional[int] = None
    current_balance_fen: Optional[int] = None
    notes: Optional[str] = ""


class CreditTicketReq(BaseModel):
    order: CreditOrderModel
    credit_info: CreditInfoModel
    store_config: Optional[StoreConfigModel] = None


# ─── 端点 ──────────────────────────────────────────────────────────────────────

@router.post("/weigh-ticket", summary="生成活鲜称重单打印数据")
async def gen_weigh_ticket(req: WeighTicketReq, request: Request) -> dict:
    """生成活鲜称重单 ESC/POS base64 数据。

    返回 base64 字符串，前端通过 TXBridge.print(data.base64) 发送到打印机。
    """
    _tenant(request)

    try:
        store_cfg = req.store_config.model_dump() if req.store_config else None
        record = {
            "store_name":      req.store_name,
            "table_no":        req.table_no or "",
            "waiter_name":     req.waiter_name or "",
            "weigh_time":      req.weigh_time,
            "dish_name":       req.dish_name,
            "tank_name":       req.tank_name or "",
            "weight_gram":     req.weight_gram,
            "unit_price_fen":  req.unit_price_fen,
            "price_unit":      req.price_unit,
            "amount_fen":      req.amount_fen,
            "ticket_no":       req.ticket_no or "",
        }
        b64 = generate_weigh_ticket(record, store_config=store_cfg)
    except (ValueError, KeyError, UnicodeEncodeError) as exc:
        logger.error("weigh_ticket_error", error=str(exc))
        raise HTTPException(status_code=422, detail=f"生成称重单失败: {exc}") from exc

    return _ok({
        "base64": b64,
        "content_type": "application/escpos",
        "description": f"活鲜称重单 - {req.dish_name} - {req.weight_gram}g",
    })


@router.post("/banquet-notice", summary="生成宴席通知单打印数据")
async def gen_banquet_notice(req: BanquetNoticeReq, request: Request) -> dict:
    """生成宴席通知单 ESC/POS base64 数据。"""
    _tenant(request)

    try:
        store_cfg = req.store_config.model_dump() if req.store_config else None
        session_dict = req.session.model_dump()
        sections_list = [
            {
                "section_type": sec.section_type,
                "section_name": sec.section_name,
                "sort_order":   sec.sort_order,
                "dishes":       [d.model_dump() for d in sec.dishes],
            }
            for sec in req.menu_sections
        ]
        b64 = generate_banquet_notice(session_dict, sections_list, store_config=store_cfg)
    except (ValueError, KeyError, UnicodeEncodeError) as exc:
        logger.error("banquet_notice_error", error=str(exc))
        raise HTTPException(status_code=422, detail=f"生成宴席通知单失败: {exc}") from exc

    return _ok({
        "base64": b64,
        "content_type": "application/escpos",
        "description": f"宴席通知单 - {req.session.customer_name} - {req.session.start_time}",
    })


@router.post("/credit-ticket", summary="生成企业挂账单打印数据")
async def gen_credit_ticket(req: CreditTicketReq, request: Request) -> dict:
    """生成企业挂账单 ESC/POS base64 数据。"""
    _tenant(request)

    try:
        store_cfg = req.store_config.model_dump() if req.store_config else None
        order_dict = req.order.model_dump()
        credit_dict = req.credit_info.model_dump()
        b64 = generate_credit_account_ticket(order_dict, credit_dict, store_config=store_cfg)
    except (ValueError, KeyError, UnicodeEncodeError) as exc:
        logger.error("credit_ticket_error", error=str(exc))
        raise HTTPException(status_code=422, detail=f"生成挂账单失败: {exc}") from exc

    return _ok({
        "base64": b64,
        "content_type": "application/escpos",
        "description": f"企业挂账单 - {req.credit_info.company_name} - {req.order.order_no}",
    })


# ─── 新格式端点：语义标记文本（语义DSL，供 TXBridge.print(content) 使用）──────


class LiveSeafoodReceiptItemReq(BaseModel):
    """活鲜称重单单项。"""
    dish_name: str = Field(..., description="菜品名称")
    tank_zone: str = Field(..., description="鱼缸区域，如'A1鱼缸'")
    weight_kg: float = Field(..., ge=0, description="重量（千克）")
    weight_jin: float = Field(..., ge=0, description="重量（斤）")
    price_per_jin_fen: int = Field(..., ge=0, description="单价（分/斤）")
    total_fen: int = Field(..., ge=0, description="小计（分）")
    note: Optional[str] = Field(default="", description="备注，如'客户已验鱼'")


class LiveSeafoodReceiptReq(BaseModel):
    """活鲜称重单请求（语义标记版本）。"""
    store_name: str = Field(..., description="门店名称")
    table_no: str = Field(default="", description="桌台编号")
    printed_at: str = Field(default="", description="打印时间，如'2026-04-02 18:35'")
    operator: str = Field(default="", description="操作员姓名")
    items: list[LiveSeafoodReceiptItemReq] = Field(..., description="称重条目列表")
    total_fen: int = Field(..., ge=0, description="合计金额（分）")


class BanquetSectionItemReq(BaseModel):
    """宴席节次菜品条目。"""
    name: str = Field(..., description="菜品名称")
    qty_per_table: int = Field(default=1, ge=1, description="每桌份数")
    note: str = Field(default="", description="备注，如'提前1小时腌制'")


class BanquetSectionReq(BaseModel):
    """宴席出品节次。"""
    section_name: str = Field(..., description="节次名称，如'冷盘'")
    serve_time: str = Field(default="", description="上桌时间，如'18:30'")
    items: list[BanquetSectionItemReq] = Field(default_factory=list)


class BanquetNoticeV2Req(BaseModel):
    """宴席通知单请求（语义标记版本，新字段结构）。"""
    store_name: str = Field(..., description="门店名称")
    banquet_name: str = Field(default="", description="宴席名称")
    session_no: int = Field(default=1, ge=1, description="场次编号")
    table_count: int = Field(default=0, ge=0, description="桌数")
    party_size: int = Field(default=0, ge=0, description="总人数")
    arrive_time: str = Field(default="", description="到场时间，如'18:00'")
    start_time: str = Field(default="", description="开席时间，如'18:30'")
    printed_at: str = Field(default="", description="打印时间")
    contact_name: str = Field(default="", description="联系人姓名")
    contact_phone: str = Field(default="", description="联系人电话（已脱敏）")
    package_name: str = Field(default="", description="套餐名称")
    sections: list[BanquetSectionReq] = Field(default_factory=list)
    special_notes: str = Field(default="", description="特别注意事项")
    dept: str = Field(default="", description="此通知单发给哪个档口")


@router.post("/live-seafood-receipt", summary="生成活鲜称重单（语义标记文本）")
async def gen_live_seafood_receipt(req: LiveSeafoodReceiptReq, request: Request) -> dict:
    """生成活鲜称重单语义标记文本。

    返回 content 字段，前端通过 TXBridge.print(content) 发送到打印机。
    """
    _tenant(request)

    try:
        data = req.model_dump()
        content = render_live_seafood_receipt(data)
    except (ValueError, KeyError) as exc:
        logger.error("live_seafood_receipt_error", error=str(exc))
        raise HTTPException(status_code=422, detail=f"生成活鲜称重单失败: {exc}") from exc

    logger.info(
        "live_seafood_receipt_generated",
        table_no=req.table_no,
        item_count=len(req.items),
        total_fen=req.total_fen,
    )
    return _ok({
        "content": content,
        "printer_hint": "receipt",
        "description": f"活鲜称重单 - {req.table_no} - {req.total_fen}分",
    })


@router.get("/live-seafood-receipt/preview", summary="活鲜称重单 Mock 预览")
async def preview_live_seafood_receipt(
    table_no: str = Query(default="A8", description="桌号"),
) -> dict:
    """返回 Mock 数据渲染的活鲜称重单预览，供开发调试使用。不需要 X-Tenant-ID。"""
    mock = _mock_live_seafood_receipt()
    mock["table_no"] = table_no
    content = render_live_seafood_receipt(mock)
    return _ok({
        "content": content,
        "printer_hint": "receipt",
        "mock": True,
        "description": f"[MOCK] 活鲜称重单预览 - 桌号{table_no}",
    })


@router.post("/banquet-notice-v2", summary="生成宴席通知单（语义标记文本，新格式）")
async def gen_banquet_notice_v2(req: BanquetNoticeV2Req, request: Request) -> dict:
    """生成宴席出品通知单语义标记文本。

    返回 content 字段，前端通过 TXBridge.print(content) 发送到打印机。
    """
    _tenant(request)

    try:
        data = req.model_dump()
        content = render_banquet_notice(data)
    except (ValueError, KeyError) as exc:
        logger.error("banquet_notice_v2_error", error=str(exc))
        raise HTTPException(status_code=422, detail=f"生成宴席通知单失败: {exc}") from exc

    logger.info(
        "banquet_notice_v2_generated",
        banquet_name=req.banquet_name,
        dept=req.dept,
        table_count=req.table_count,
    )
    return _ok({
        "content": content,
        "printer_hint": "receipt",
        "description": f"宴席通知单 - {req.banquet_name} - {req.dept or '全档口'}",
    })


@router.get("/banquet-notice-v2/preview", summary="宴席通知单 Mock 预览")
async def preview_banquet_notice_v2(
    dept: str = Query(default="热菜档口", description="档口名称"),
) -> dict:
    """返回 Mock 数据渲染的宴席通知单预览，供开发调试使用。不需要 X-Tenant-ID。"""
    mock = _mock_banquet_notice(dept=dept)
    content = render_banquet_notice(mock)
    return _ok({
        "content": content,
        "printer_hint": "receipt",
        "mock": True,
        "description": f"[MOCK] 宴席通知单预览 - 档口:{dept}",
    })
