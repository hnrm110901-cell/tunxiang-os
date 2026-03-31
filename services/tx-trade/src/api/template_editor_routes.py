"""小票可视化编辑器 API

路由前缀: /api/v1/receipt-templates

端点：
  GET    /api/v1/receipt-templates                          — 列出模板
  POST   /api/v1/receipt-templates                          — 创建模板
  GET    /api/v1/receipt-templates/elements/catalog         — element 类型目录
  POST   /api/v1/receipt-templates/preview                  — 预览（返回可视化行）
  GET    /api/v1/receipt-templates/{template_id}            — 获取单模板
  PUT    /api/v1/receipt-templates/{template_id}            — 更新模板
  DELETE /api/v1/receipt-templates/{template_id}            — 删除模板
  POST   /api/v1/receipt-templates/{template_id}/set-default — 设为默认
  POST   /api/v1/receipt-templates/{template_id}/duplicate  — 复制模板
"""
import uuid
from datetime import datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import NoResultFound, IntegrityError

from shared.ontology.src.database import async_session_factory

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/receipt-templates", tags=["receipt-templates"])


# ─── Pydantic 模型 ───


class ElementDef(BaseModel):
    """单个 element 定义（模板配置中的元素）。"""
    id: str
    type: str
    # 以下字段均可选，element 类型不同字段不同
    align: Optional[str] = None
    bold: Optional[bool] = None
    size: Optional[str] = None
    char: Optional[str] = None
    fields: Optional[list[str]] = None
    show_price: Optional[bool] = None
    show_qty: Optional[bool] = None
    show_subtotal: Optional[bool] = None
    show_discount: Optional[bool] = None
    show_service_fee: Optional[bool] = None
    show_change: Optional[bool] = None
    content_field: Optional[str] = None
    content: Optional[str] = None
    count: Optional[int] = None
    barcode_type: Optional[str] = None

    model_config = {"extra": "allow"}


class TemplateConfig(BaseModel):
    """模板 config JSON 结构。"""
    paper_width: int = Field(80, description="纸宽 mm: 58 或 80")
    elements: list[ElementDef] = Field(default_factory=list)


class CreateTemplateReq(BaseModel):
    store_id: uuid.UUID
    template_name: str = Field(..., max_length=100)
    print_type: str = Field("receipt", description="receipt/kitchen/checkout/label")
    paper_width: int = Field(80, description="纸宽 mm: 58 或 80")
    config: TemplateConfig
    is_default: bool = False


class UpdateTemplateReq(BaseModel):
    template_name: Optional[str] = Field(None, max_length=100)
    print_type: Optional[str] = None
    paper_width: Optional[int] = None
    config: Optional[TemplateConfig] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class TemplateResp(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    template_name: str
    print_type: str
    paper_width: int
    is_default: bool
    is_active: bool
    config: Optional[dict] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TemplateListResp(BaseModel):
    ok: bool = True
    data: dict[str, Any]


class PreviewLine(BaseModel):
    type: str                          # text | separator | qrcode | barcode | blank
    content: Optional[str] = None
    align: Optional[str] = None
    bold: Optional[bool] = None
    size: Optional[str] = None
    char: Optional[str] = None


class PreviewReq(BaseModel):
    config: TemplateConfig


class PreviewResp(BaseModel):
    ok: bool = True
    data: dict[str, Any]


# ─── element 目录（供前端编辑器使用）───

_ELEMENTS_CATALOG = [
    {
        "type": "store_name",
        "label": "店名",
        "icon": "store",
        "category": "基础信息",
        "props": [
            {"key": "align", "label": "对齐", "type": "select",
             "options": ["left", "center", "right"], "default": "center"},
            {"key": "bold", "label": "加粗", "type": "boolean", "default": True},
            {"key": "size", "label": "字体大小", "type": "select",
             "options": ["normal", "double_width", "double_height", "double_both"],
             "default": "double_height"},
        ],
    },
    {
        "type": "store_address",
        "label": "门店地址",
        "icon": "location",
        "category": "基础信息",
        "props": [
            {"key": "align", "label": "对齐", "type": "select",
             "options": ["left", "center", "right"], "default": "center"},
            {"key": "bold", "label": "加粗", "type": "boolean", "default": False},
        ],
    },
    {
        "type": "separator",
        "label": "分隔线",
        "icon": "minus",
        "category": "布局",
        "props": [
            {"key": "char", "label": "分隔符", "type": "select",
             "options": ["-", "=", "*"], "default": "-"},
        ],
    },
    {
        "type": "order_info",
        "label": "订单信息",
        "icon": "receipt",
        "category": "订单数据",
        "props": [
            {"key": "fields", "label": "显示字段", "type": "multiselect",
             "options": ["table_no", "order_no", "cashier", "datetime"],
             "default": ["table_no", "order_no", "cashier", "datetime"]},
        ],
    },
    {
        "type": "order_items",
        "label": "菜品明细",
        "icon": "list",
        "category": "订单数据",
        "props": [
            {"key": "show_price", "label": "显示单价", "type": "boolean", "default": True},
            {"key": "show_qty", "label": "显示数量", "type": "boolean", "default": True},
            {"key": "show_subtotal", "label": "显示小计", "type": "boolean", "default": True},
        ],
    },
    {
        "type": "total_summary",
        "label": "合计汇总",
        "icon": "calculator",
        "category": "订单数据",
        "props": [
            {"key": "show_discount", "label": "显示折扣", "type": "boolean", "default": True},
            {"key": "show_service_fee", "label": "显示服务费", "type": "boolean",
             "default": True},
        ],
    },
    {
        "type": "payment_method",
        "label": "支付方式",
        "icon": "payment",
        "category": "订单数据",
        "props": [
            {"key": "show_change", "label": "显示找零", "type": "boolean", "default": True},
        ],
    },
    {
        "type": "qrcode",
        "label": "二维码",
        "icon": "qrcode",
        "category": "多媒体",
        "props": [
            {"key": "content_field", "label": "内容字段", "type": "select",
             "options": ["order_id", "order_no", "store_id"], "default": "order_id"},
            {"key": "content", "label": "固定内容（留空则取字段）", "type": "text",
             "default": ""},
            {"key": "size", "label": "二维码大小(1-16)", "type": "number", "default": 8},
        ],
    },
    {
        "type": "barcode",
        "label": "条形码",
        "icon": "barcode",
        "category": "多媒体",
        "props": [
            {"key": "content_field", "label": "内容字段", "type": "select",
             "options": ["order_no", "order_id"], "default": "order_no"},
            {"key": "content", "label": "固定内容（留空则取字段）", "type": "text",
             "default": ""},
            {"key": "barcode_type", "label": "条码类型", "type": "select",
             "options": ["CODE128", "EAN13", "CODE39"], "default": "CODE128"},
        ],
    },
    {
        "type": "custom_text",
        "label": "自定义文字",
        "icon": "text",
        "category": "自定义",
        "props": [
            {"key": "content", "label": "文字内容（支持 {{变量}}）", "type": "text",
             "default": "谢谢惠顾，欢迎再来！"},
            {"key": "align", "label": "对齐", "type": "select",
             "options": ["left", "center", "right"], "default": "center"},
            {"key": "bold", "label": "加粗", "type": "boolean", "default": False},
            {"key": "size", "label": "字体大小", "type": "select",
             "options": ["normal", "double_width", "double_height", "double_both"],
             "default": "normal"},
        ],
    },
    {
        "type": "blank_lines",
        "label": "空行",
        "icon": "rows",
        "category": "布局",
        "props": [
            {"key": "count", "label": "行数", "type": "number", "default": 2},
        ],
    },
    {
        "type": "logo_text",
        "label": "品牌口号",
        "icon": "star",
        "category": "自定义",
        "props": [
            {"key": "content", "label": "文字内容", "type": "text",
             "default": "屯象OS · 智慧餐饮"},
            {"key": "align", "label": "对齐", "type": "select",
             "options": ["left", "center", "right"], "default": "center"},
            {"key": "bold", "label": "加粗", "type": "boolean", "default": False},
        ],
    },
]

# ─── 预览用示例数据 ───

_SAMPLE_CONTEXT: dict[str, Any] = {
    "store_name": "好味道火锅",
    "store_address": "长沙市天心区解放西路88号",
    "table_no": "A08",
    "order_no": "TX20260331120001A",
    "cashier": "李淳",
    "datetime": "2026-03-31 12:00:00",
    "items": [
        {"name": "毛肚", "qty": 2, "price_yuan": 32.0, "subtotal_yuan": 64.0, "notes": ""},
        {"name": "黄喉", "qty": 1, "price_yuan": 28.0, "subtotal_yuan": 28.0, "notes": "不要辣"},
        {"name": "鸭血", "qty": 1, "price_yuan": 18.0, "subtotal_yuan": 18.0, "notes": ""},
        {"name": "牛肉", "qty": 2, "price_yuan": 45.0, "subtotal_yuan": 90.0, "notes": ""},
    ],
    "subtotal_yuan": 200.0,
    "discount_yuan": 20.0,
    "service_fee_yuan": 0.0,
    "total_yuan": 180.0,
    "payment_method": "wechat",
    "payment_amount_yuan": 180.0,
    "change_yuan": 0.0,
    "order_id": "3f4a8b2c-1234-5678-abcd-ef0123456789",
}

_PAYMENT_LABELS_PREVIEW: dict[str, str] = {
    "wechat": "微信支付",
    "alipay": "支付宝",
    "cash": "现金",
    "unionpay": "银联",
    "member": "会员余额",
    "credit": "挂账",
}


# ─── 预览渲染器（生成可视化行列表）───

def _preview_lines_from_config(
    config: TemplateConfig,
) -> list[dict[str, Any]]:
    """将 config 转为前端可渲染的预览行列表（使用 sample data）。"""
    ctx = _SAMPLE_CONTEXT
    lines: list[dict[str, Any]] = []
    char_width = 32 if config.paper_width == 58 else 48

    for elem in config.elements:
        etype = elem.type

        if etype == "store_name":
            lines.append({
                "type": "text",
                "content": ctx["store_name"],
                "align": elem.align or "center",
                "bold": elem.bold if elem.bold is not None else True,
                "size": elem.size or "double_height",
            })

        elif etype == "store_address":
            addr = ctx.get("store_address", "")
            if addr:
                lines.append({
                    "type": "text",
                    "content": addr,
                    "align": elem.align or "center",
                    "bold": elem.bold or False,
                    "size": "normal",
                })

        elif etype == "separator":
            lines.append({"type": "separator", "char": elem.char or "-"})

        elif etype == "order_info":
            field_list = elem.fields or ["table_no", "order_no", "cashier", "datetime"]
            label_map = {"table_no": "桌号", "order_no": "单号",
                         "cashier": "收银", "datetime": "时间"}
            for field in field_list:
                value = ctx.get(field, "")
                if value:
                    lines.append({
                        "type": "text",
                        "content": f"{label_map.get(field, field)}: {value}",
                        "align": "left",
                        "bold": False,
                        "size": "normal",
                    })

        elif etype == "order_items":
            show_qty = elem.show_qty if elem.show_qty is not None else True
            show_subtotal = elem.show_subtotal if elem.show_subtotal is not None else True
            # 表头
            if show_qty and show_subtotal:
                lines.append({
                    "type": "text",
                    "content": f"{'品名':<{char_width // 2}}{'数量':<8}{'金额':>8}",
                    "align": "left",
                    "bold": True,
                    "size": "normal",
                })
            lines.append({"type": "separator", "char": "-"})
            for item in ctx.get("items", []):
                name = item["name"]
                qty = item["qty"]
                subtotal = item["subtotal_yuan"]
                content = f"{name}"
                if show_qty:
                    content += f"  x{qty}"
                if show_subtotal:
                    content += f"  ¥{subtotal:.2f}"
                lines.append({
                    "type": "text",
                    "content": content,
                    "align": "left",
                    "bold": False,
                    "size": "normal",
                })
                if item.get("notes"):
                    lines.append({
                        "type": "text",
                        "content": f"  [{item['notes']}]",
                        "align": "left",
                        "bold": True,
                        "size": "normal",
                    })

        elif etype == "total_summary":
            show_discount = elem.show_discount if elem.show_discount is not None else True
            show_service_fee = (
                elem.show_service_fee if elem.show_service_fee is not None else True
            )
            lines.append({
                "type": "text",
                "content": f"小计: ¥{ctx['subtotal_yuan']:.2f}",
                "align": "left",
                "bold": False,
                "size": "normal",
            })
            if show_discount and ctx.get("discount_yuan", 0) > 0:
                lines.append({
                    "type": "text",
                    "content": f"优惠: -¥{ctx['discount_yuan']:.2f}",
                    "align": "left",
                    "bold": False,
                    "size": "normal",
                })
            if show_service_fee and ctx.get("service_fee_yuan", 0) > 0:
                lines.append({
                    "type": "text",
                    "content": f"服务费: ¥{ctx['service_fee_yuan']:.2f}",
                    "align": "left",
                    "bold": False,
                    "size": "normal",
                })
            lines.append({
                "type": "text",
                "content": f"实付: ¥{ctx['total_yuan']:.2f}",
                "align": "left",
                "bold": True,
                "size": "double_both",
            })

        elif etype == "payment_method":
            show_change = elem.show_change if elem.show_change is not None else True
            method = ctx.get("payment_method", "")
            label = _PAYMENT_LABELS_PREVIEW.get(method, method)
            lines.append({
                "type": "text",
                "content": f"支付方式: {label}",
                "align": "left",
                "bold": False,
                "size": "normal",
            })
            pay_amt = ctx.get("payment_amount_yuan", 0.0)
            if pay_amt > 0:
                lines.append({
                    "type": "text",
                    "content": f"收款: ¥{pay_amt:.2f}",
                    "align": "left",
                    "bold": False,
                    "size": "normal",
                })
            if show_change and ctx.get("change_yuan", 0) > 0:
                lines.append({
                    "type": "text",
                    "content": f"找零: ¥{ctx['change_yuan']:.2f}",
                    "align": "left",
                    "bold": False,
                    "size": "normal",
                })

        elif etype == "qrcode":
            content = elem.content or ctx.get(elem.content_field or "order_id", "")
            if content:
                lines.append({"type": "qrcode", "content": str(content)})

        elif etype == "barcode":
            content = elem.content or ctx.get(elem.content_field or "order_no", "")
            if content:
                lines.append({
                    "type": "barcode",
                    "content": str(content),
                    "barcode_type": elem.barcode_type or "CODE128",
                })

        elif etype in ("custom_text", "logo_text"):
            raw = elem.content or ""
            import re
            rendered = re.sub(
                r"\{\{(\w+)\}\}",
                lambda m: str(ctx.get(m.group(1), m.group(0))),
                raw,
            )
            lines.append({
                "type": "text",
                "content": rendered,
                "align": elem.align or "center",
                "bold": elem.bold or False,
                "size": elem.size or "normal",
            })

        elif etype == "blank_lines":
            count = max(1, min(10, elem.count or 1))
            for _ in range(count):
                lines.append({"type": "blank"})

    return lines


# ─── 数据库辅助函数 ───


async def _get_template_or_404(
    template_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    """从数据库取模板，不存在则 404。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT id, tenant_id, store_id, template_name, print_type, "
                "paper_width, is_default, is_active, config, "
                "created_at, updated_at "
                "FROM receipt_templates "
                "WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false"
            ),
            {"id": template_id, "tenant_id": tenant_id},
        )
        row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    return dict(row)


def _row_to_resp(row: dict[str, Any]) -> dict[str, Any]:
    """将数据库行转为响应字典。"""
    return {
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "store_id": str(row["store_id"]),
        "template_name": row["template_name"],
        "print_type": row["print_type"],
        "paper_width": row["paper_width"],
        "is_default": row["is_default"],
        "is_active": row["is_active"],
        "config": row.get("config"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


# ─── 路由 ───


@router.get("/elements/catalog")
async def get_elements_catalog():
    """获取所有可用 element 类型及其属性定义（供前端编辑器渲染属性面板）。"""
    return {"ok": True, "data": {"elements": _ELEMENTS_CATALOG}}


@router.get("")
async def list_templates(
    store_id: Optional[uuid.UUID] = Query(None, description="门店ID过滤"),
    print_type: Optional[str] = Query(None, description="模板类型过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """列出模板（支持 store_id / print_type 过滤，分页）。"""
    tenant_id = uuid.UUID(x_tenant_id)
    offset = (page - 1) * size

    conditions = [
        "tenant_id = :tenant_id",
        "is_deleted = false",
    ]
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": size, "offset": offset}

    if store_id is not None:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id

    if print_type is not None:
        conditions.append("print_type = :print_type")
        params["print_type"] = print_type

    where_clause = " AND ".join(conditions)

    async with async_session_factory() as session:
        count_result = await session.execute(
            text(f"SELECT COUNT(*) FROM receipt_templates WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        rows_result = await session.execute(
            text(
                f"SELECT id, tenant_id, store_id, template_name, print_type, "
                f"paper_width, is_default, is_active, config, created_at, updated_at "
                f"FROM receipt_templates "
                f"WHERE {where_clause} "
                f"ORDER BY is_default DESC, created_at DESC "
                f"LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        rows = [dict(r) for r in rows_result.mappings()]

    logger.info("template.list", tenant_id=str(tenant_id), total=total)
    return {
        "ok": True,
        "data": {
            "items": [_row_to_resp(r) for r in rows],
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.post("", status_code=201)
async def create_template(
    req: CreateTemplateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建新模板（JSON config 格式）。"""
    tenant_id = uuid.UUID(x_tenant_id)
    template_id = uuid.uuid4()
    config_dict = req.config.model_dump()

    try:
        async with async_session_factory() as session:
            async with session.begin():
                # 若设为默认，先清除同类型旧默认
                if req.is_default:
                    await session.execute(
                        text(
                            "UPDATE receipt_templates SET is_default = false "
                            "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                            "AND print_type = :print_type AND is_deleted = false"
                        ),
                        {
                            "tenant_id": tenant_id,
                            "store_id": req.store_id,
                            "print_type": req.print_type,
                        },
                    )
                await session.execute(
                    text(
                        "INSERT INTO receipt_templates "
                        "(id, tenant_id, store_id, template_name, print_type, "
                        "paper_width, template_content, is_default, is_active, config) "
                        "VALUES (:id, :tenant_id, :store_id, :template_name, :print_type, "
                        ":paper_width, :template_content, :is_default, true, :config::jsonb)"
                    ),
                    {
                        "id": template_id,
                        "tenant_id": tenant_id,
                        "store_id": req.store_id,
                        "template_name": req.template_name,
                        "print_type": req.print_type,
                        "paper_width": req.paper_width,
                        "template_content": "",     # JSON 模板不需要 Jinja 内容
                        "is_default": req.is_default,
                        "config": __import__("json").dumps(config_dict, ensure_ascii=False),
                    },
                )
    except IntegrityError as exc:
        logger.error("template.create_failed", error=str(exc))
        raise HTTPException(status_code=409, detail="模板创建冲突，请检查参数") from exc

    logger.info("template.created", template_id=str(template_id), tenant_id=str(tenant_id))
    return {
        "ok": True,
        "data": {
            "id": str(template_id),
            "template_name": req.template_name,
        },
    }


@router.get("/{template_id}")
async def get_template(
    template_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取单个模板详情（含 config）。"""
    tenant_id = uuid.UUID(x_tenant_id)
    row = await _get_template_or_404(template_id, tenant_id)
    return {"ok": True, "data": _row_to_resp(row)}


@router.put("/{template_id}")
async def update_template(
    template_id: uuid.UUID,
    req: UpdateTemplateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """更新模板（部分更新，仅修改传入字段）。"""
    tenant_id = uuid.UUID(x_tenant_id)
    # 确认模板存在
    existing = await _get_template_or_404(template_id, tenant_id)

    set_parts: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": template_id, "tenant_id": tenant_id}

    if req.template_name is not None:
        set_parts.append("template_name = :template_name")
        params["template_name"] = req.template_name

    if req.print_type is not None:
        set_parts.append("print_type = :print_type")
        params["print_type"] = req.print_type

    if req.paper_width is not None:
        set_parts.append("paper_width = :paper_width")
        params["paper_width"] = req.paper_width

    if req.is_active is not None:
        set_parts.append("is_active = :is_active")
        params["is_active"] = req.is_active

    if req.config is not None:
        set_parts.append("config = :config::jsonb")
        params["config"] = __import__("json").dumps(
            req.config.model_dump(), ensure_ascii=False
        )

    import json

    async with async_session_factory() as session:
        async with session.begin():
            if req.is_default is True:
                # 清除同门店同类型其他默认
                effective_print_type = req.print_type or existing["print_type"]
                await session.execute(
                    text(
                        "UPDATE receipt_templates SET is_default = false "
                        "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                        "AND print_type = :print_type AND is_deleted = false"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "store_id": existing["store_id"],
                        "print_type": effective_print_type,
                    },
                )
                set_parts.append("is_default = true")
            elif req.is_default is False:
                set_parts.append("is_default = false")

            set_clause = ", ".join(set_parts)
            await session.execute(
                text(
                    f"UPDATE receipt_templates SET {set_clause} "
                    f"WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false"
                ),
                params,
            )

    logger.info("template.updated", template_id=str(template_id))
    return {"ok": True, "data": {"id": str(template_id)}}


@router.delete("/{template_id}")
async def delete_template(
    template_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """软删除模板。"""
    tenant_id = uuid.UUID(x_tenant_id)
    await _get_template_or_404(template_id, tenant_id)

    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "UPDATE receipt_templates "
                    "SET is_deleted = true, updated_at = NOW() "
                    "WHERE id = :id AND tenant_id = :tenant_id"
                ),
                {"id": template_id, "tenant_id": tenant_id},
            )

    logger.info("template.deleted", template_id=str(template_id))
    return {"ok": True, "data": {"id": str(template_id)}}


@router.post("/{template_id}/set-default")
async def set_default_template(
    template_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """将指定模板设为同门店同类型的默认模板。"""
    tenant_id = uuid.UUID(x_tenant_id)
    row = await _get_template_or_404(template_id, tenant_id)

    async with async_session_factory() as session:
        async with session.begin():
            # 清除旧默认
            await session.execute(
                text(
                    "UPDATE receipt_templates SET is_default = false "
                    "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                    "AND print_type = :print_type AND is_deleted = false"
                ),
                {
                    "tenant_id": tenant_id,
                    "store_id": row["store_id"],
                    "print_type": row["print_type"],
                },
            )
            # 设新默认
            await session.execute(
                text(
                    "UPDATE receipt_templates "
                    "SET is_default = true, updated_at = NOW() "
                    "WHERE id = :id AND tenant_id = :tenant_id"
                ),
                {"id": template_id, "tenant_id": tenant_id},
            )

    logger.info("template.set_default", template_id=str(template_id))
    return {"ok": True, "data": {"id": str(template_id), "is_default": True}}


@router.post("/{template_id}/duplicate", status_code=201)
async def duplicate_template(
    template_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """复制模板，新模板名称加 " (副本)" 后缀，is_default=false。"""
    import json

    tenant_id = uuid.UUID(x_tenant_id)
    row = await _get_template_or_404(template_id, tenant_id)

    new_id = uuid.uuid4()
    new_name = f"{row['template_name']} (副本)"[:100]
    config_json = json.dumps(row.get("config") or {}, ensure_ascii=False)

    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO receipt_templates "
                    "(id, tenant_id, store_id, template_name, print_type, "
                    "paper_width, template_content, is_default, is_active, config) "
                    "VALUES (:id, :tenant_id, :store_id, :template_name, :print_type, "
                    ":paper_width, :template_content, false, true, :config::jsonb)"
                ),
                {
                    "id": new_id,
                    "tenant_id": tenant_id,
                    "store_id": row["store_id"],
                    "template_name": new_name,
                    "print_type": row["print_type"],
                    "paper_width": row["paper_width"],
                    "template_content": "",
                    "config": config_json,
                },
            )

    logger.info(
        "template.duplicated",
        source_id=str(template_id),
        new_id=str(new_id),
    )
    return {
        "ok": True,
        "data": {
            "id": str(new_id),
            "template_name": new_name,
        },
    }


@router.post("/preview")
async def preview_template(
    req: PreviewReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """预览模板（使用内置示例数据，返回可视化行数组，不依赖真实订单）。

    返回格式::

        {
            "preview_lines": [
                {"type": "text", "content": "好味道火锅", "align": "center", ...},
                {"type": "separator", "char": "-"},
                ...
            ],
            "paper_width_mm": 80,
            "char_width": 48
        }
    """
    paper_width = req.config.paper_width
    char_width = 32 if paper_width == 58 else 48
    lines = _preview_lines_from_config(req.config)

    return {
        "ok": True,
        "data": {
            "preview_lines": lines,
            "paper_width_mm": paper_width,
            "char_width": char_width,
            "sample_data_note": "预览使用内置示例数据，实际打印以真实订单为准",
        },
    }
