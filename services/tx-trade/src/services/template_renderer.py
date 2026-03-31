"""小票模板渲染器 — 将 JSON config 转为 ESC/POS 字节流

设计：模板 config 中的 elements 列表，按顺序渲染每个 element，
最终拼接完整字节流（含初始化和切纸）。

支持的 element 类型：
  store_name      — 店名（居中/加粗/字号可配）
  store_address   — 门店地址
  separator       — 分隔线（char: - 或 =）
  order_info      — 订单信息行组（桌号/单号/收银员/时间）
  order_items     — 菜品明细表
  total_summary   — 合计区（小计/折扣/服务费/实付）
  payment_method  — 支付方式+找零
  qrcode          — 二维码
  barcode         — 条形码
  custom_text     — 自定义文字（支持 {{变量}} 替换）
  blank_lines     — 空行
  logo_text       — 品牌口号/备注文字
"""
import re
from typing import Any

import structlog

from .printer_driver import (
    ESC_INIT,
    ESC_ALIGN_LEFT,
    ESC_ALIGN_CENTER,
    ESC_ALIGN_RIGHT,
    ESC_BOLD_ON,
    ESC_BOLD_OFF,
    GS_SIZE_NORMAL,
    GS_SIZE_DOUBLE_WIDTH,
    GS_SIZE_DOUBLE_HEIGHT,
    GS_SIZE_DOUBLE_BOTH,
    GS_CUT_PARTIAL,
    ESC_FEED,
    LF,
    LINE_WIDTH,
    _gbk_len,
    _pad_two_columns,
    _pad_three_columns,
)

logger = structlog.get_logger()

# ─── 映射表 ───

_ALIGN_BYTES: dict[str, bytes] = {
    "left": ESC_ALIGN_LEFT,
    "center": ESC_ALIGN_CENTER,
    "right": ESC_ALIGN_RIGHT,
}

_SIZE_BYTES: dict[str, bytes] = {
    "normal": GS_SIZE_NORMAL,
    "double_width": GS_SIZE_DOUBLE_WIDTH,
    "double_height": GS_SIZE_DOUBLE_HEIGHT,
    "double_both": GS_SIZE_DOUBLE_BOTH,
}

# 支付方式中文名映射
_PAYMENT_LABELS: dict[str, str] = {
    "wechat": "微信支付",
    "alipay": "支付宝",
    "cash": "现金",
    "unionpay": "银联",
    "member": "会员余额",
    "credit": "挂账",
}

# 订单信息字段中文标签
_ORDER_INFO_LABELS: dict[str, str] = {
    "table_no": "桌号",
    "order_no": "单号",
    "cashier": "收银",
    "datetime": "时间",
}


# ─── 工具函数 ───


def _encode(text: str) -> bytes:
    """GBK 编码文本，带换行。"""
    return text.encode("gbk", errors="replace") + LF


def _sep(char: str = "-", width: int = LINE_WIDTH) -> bytes:
    """生成分割线字节。"""
    return (char * width).encode("ascii") + LF


def _build_qrcode(data: str, size: int = 6) -> bytes:
    """生成二维码 ESC/POS 指令。"""
    if not data:
        return b""
    encoded = data.encode("utf-8")
    data_len = len(encoded) + 3
    pL = data_len & 0xFF
    pH = (data_len >> 8) & 0xFF
    size = max(1, min(16, size))

    buf = bytearray()
    buf += b'\x1d\x28\x6b\x04\x00\x31\x41\x32\x00'           # Model 2
    buf += b'\x1d\x28\x6b\x03\x00\x31\x43' + bytes([size])    # 大小
    buf += b'\x1d\x28\x6b\x03\x00\x31\x45\x31'               # 纠错等级 M
    buf += b'\x1d\x28\x6b' + bytes([pL, pH]) + b'\x31\x50\x30' + encoded  # 存数据
    buf += b'\x1d\x28\x6b\x03\x00\x31\x51\x30'               # 打印
    buf += LF
    return bytes(buf)


def _build_barcode(data: str, barcode_type: str = "CODE128") -> bytes:
    """生成条形码 ESC/POS 指令。"""
    if not data:
        return b""
    type_map = {"CODE39": 4, "EAN13": 2, "CODE128": 73}
    code = type_map.get(barcode_type.upper(), 73)

    buf = bytearray()
    buf += ESC_ALIGN_CENTER
    buf += b'\x1d\x68\x50'   # 高度 80点
    buf += b'\x1d\x77\x02'   # 宽度 2
    buf += b'\x1d\x48\x02'   # HRI 在条码下方

    encoded = data.encode("ascii", errors="replace")
    if code == 73:
        buf += b'\x1d\x6b' + bytes([code, len(encoded)]) + encoded
    else:
        buf += b'\x1d\x6b' + bytes([code]) + encoded + b'\x00'

    buf += ESC_ALIGN_LEFT + LF
    return bytes(buf)


def _apply_template_vars(text: str, context: dict[str, Any]) -> str:
    """将 {{key}} 占位符替换为 context 中的值。"""
    def replacer(m: re.Match) -> str:
        key = m.group(1).strip()
        return str(context.get(key, m.group(0)))

    return re.sub(r"\{\{(\w+)\}\}", replacer, text)


def _yuan_str(amount_yuan: float) -> str:
    """格式化金额（元），带 ¥ 前缀。"""
    return f"\xa5{amount_yuan:.2f}"


# ─── 主渲染器 ───


class TemplateRenderer:
    """将模板 JSON config 渲染为 ESC/POS 字节流。

    用法::

        renderer = TemplateRenderer()
        data = await renderer.render(config, context, paper_width=80)
        # data: bytes — 可直接通过 ESCPOSPrinter.send_raw() 发送
    """

    async def render(
        self,
        config: dict[str, Any],
        context: dict[str, Any],
        paper_width: int = 80,
    ) -> bytes:
        """渲染完整小票字节流。

        Args:
            config: 模板配置 {"elements": [...]}
            context: 订单上下文数据
            paper_width: 纸宽 mm（58 或 80），影响 LINE_WIDTH

        Returns:
            ESC/POS 字节流（含初始化 + 切纸）
        """
        # 58mm 纸宽 = 32 字符，80mm = 48 字符
        line_width = 32 if paper_width == 58 else LINE_WIDTH

        buf = bytearray()
        buf += ESC_INIT

        elements: list[dict[str, Any]] = config.get("elements", [])
        for element in elements:
            elem_type = element.get("type", "")
            try:
                chunk = self._render_element(elem_type, element, context, line_width)
                buf += chunk
            except KeyError as exc:
                logger.warning(
                    "template_renderer.missing_key",
                    element_type=elem_type,
                    key=str(exc),
                )
            except (ValueError, UnicodeEncodeError) as exc:
                logger.warning(
                    "template_renderer.render_error",
                    element_type=elem_type,
                    error=str(exc),
                )

        # 走纸 + 半切
        buf += ESC_FEED + b'\x03' + GS_CUT_PARTIAL
        return bytes(buf)

    def _render_element(
        self,
        elem_type: str,
        elem: dict[str, Any],
        ctx: dict[str, Any],
        line_width: int,
    ) -> bytes:
        """分发渲染单个 element。"""
        handlers = {
            "store_name": self._render_store_name,
            "store_address": self._render_store_address,
            "separator": self._render_separator,
            "order_info": self._render_order_info,
            "order_items": self._render_order_items,
            "total_summary": self._render_total_summary,
            "payment_method": self._render_payment_method,
            "qrcode": self._render_qrcode,
            "barcode": self._render_barcode,
            "custom_text": self._render_custom_text,
            "blank_lines": self._render_blank_lines,
            "logo_text": self._render_logo_text,
        }
        handler = handlers.get(elem_type)
        if handler is None:
            logger.warning("template_renderer.unknown_element", elem_type=elem_type)
            return b""
        return handler(elem, ctx, line_width)

    # ─── element 渲染方法 ───

    def _render_store_name(
        self, elem: dict, ctx: dict, line_width: int
    ) -> bytes:
        """店名。"""
        name = ctx.get("store_name", "")
        align = _ALIGN_BYTES.get(elem.get("align", "center"), ESC_ALIGN_CENTER)
        bold = elem.get("bold", True)
        size = _SIZE_BYTES.get(elem.get("size", "double_height"), GS_SIZE_DOUBLE_HEIGHT)

        buf = bytearray()
        buf += align + size
        if bold:
            buf += ESC_BOLD_ON
        buf += name.encode("gbk", errors="replace") + LF
        buf += GS_SIZE_NORMAL + ESC_BOLD_OFF + ESC_ALIGN_LEFT
        return bytes(buf)

    def _render_store_address(
        self, elem: dict, ctx: dict, line_width: int
    ) -> bytes:
        """门店地址。"""
        address = ctx.get("store_address", "")
        if not address:
            return b""
        align = _ALIGN_BYTES.get(elem.get("align", "center"), ESC_ALIGN_CENTER)
        bold = elem.get("bold", False)

        buf = bytearray()
        buf += align
        if bold:
            buf += ESC_BOLD_ON
        buf += address.encode("gbk", errors="replace") + LF
        if bold:
            buf += ESC_BOLD_OFF
        buf += ESC_ALIGN_LEFT
        return bytes(buf)

    def _render_separator(
        self, elem: dict, ctx: dict, line_width: int
    ) -> bytes:
        """分隔线。"""
        char = elem.get("char", "-")
        # 确保只用 ASCII 字符
        if not char or not char.isascii():
            char = "-"
        return _sep(char, line_width)

    def _render_order_info(
        self, elem: dict, ctx: dict, line_width: int
    ) -> bytes:
        """订单信息行组。"""
        fields: list[str] = elem.get("fields", ["table_no", "order_no", "cashier", "datetime"])
        ctx_keys = {
            "table_no": "table_no",
            "order_no": "order_no",
            "cashier": "cashier",
            "datetime": "datetime",
        }

        buf = bytearray()
        buf += ESC_ALIGN_LEFT
        for field in fields:
            label = _ORDER_INFO_LABELS.get(field, field)
            value = ctx.get(ctx_keys.get(field, field), "")
            if value:
                line = f"{label}: {value}"
                buf += line.encode("gbk", errors="replace") + LF
        return bytes(buf)

    def _render_order_items(
        self, elem: dict, ctx: dict, line_width: int
    ) -> bytes:
        """菜品明细表。"""
        show_price = elem.get("show_price", True)
        show_qty = elem.get("show_qty", True)
        show_subtotal = elem.get("show_subtotal", True)
        items: list[dict] = ctx.get("items", [])

        buf = bytearray()
        buf += ESC_ALIGN_LEFT + ESC_BOLD_ON

        # 表头
        if show_qty and show_subtotal:
            buf += _pad_three_columns("品名", "数量", "金额", line_width).encode(
                "gbk", errors="replace"
            ) + LF
        elif show_qty:
            buf += _pad_two_columns("品名", "数量", line_width).encode(
                "gbk", errors="replace"
            ) + LF
        else:
            buf += "品名".encode("gbk", errors="replace") + LF

        buf += ESC_BOLD_OFF + _sep("-", line_width)

        for item in items:
            name = item.get("name", "")
            qty = item.get("qty", 0)
            price = item.get("price_yuan", 0.0)
            subtotal = item.get("subtotal_yuan", 0.0)
            notes = item.get("notes", "")

            # 截断过长的菜名
            if _gbk_len(name) > line_width // 2:
                encoded = name.encode("gbk", errors="replace")
                name = encoded[: line_width // 2].decode("gbk", errors="replace")

            if show_qty and show_subtotal:
                amount_str = _yuan_str(subtotal)
                buf += _pad_three_columns(name, str(qty), amount_str, line_width).encode(
                    "gbk", errors="replace"
                ) + LF
            elif show_qty:
                buf += _pad_two_columns(name, str(qty), line_width).encode(
                    "gbk", errors="replace"
                ) + LF
            else:
                buf += name.encode("gbk", errors="replace") + LF

            # 单价行（可选）
            if show_price and not show_subtotal:
                price_line = f"  单价: {_yuan_str(price)}"
                buf += price_line.encode("gbk", errors="replace") + LF

            # 备注
            if notes:
                note_line = f"  [{notes}]"
                buf += ESC_BOLD_ON + note_line.encode("gbk", errors="replace") + LF
                buf += ESC_BOLD_OFF

        return bytes(buf)

    def _render_total_summary(
        self, elem: dict, ctx: dict, line_width: int
    ) -> bytes:
        """合计区。"""
        show_discount = elem.get("show_discount", True)
        show_service_fee = elem.get("show_service_fee", True)

        subtotal = ctx.get("subtotal_yuan", 0.0)
        discount = ctx.get("discount_yuan", 0.0)
        service_fee = ctx.get("service_fee_yuan", 0.0)
        total = ctx.get("total_yuan", 0.0)

        buf = bytearray()
        buf += ESC_ALIGN_LEFT

        buf += _pad_two_columns("小计:", _yuan_str(subtotal), line_width).encode(
            "gbk", errors="replace"
        ) + LF

        if show_discount and discount > 0:
            buf += _pad_two_columns(
                "优惠:", f"-{_yuan_str(discount)}", line_width
            ).encode("gbk", errors="replace") + LF

        if show_service_fee and service_fee > 0:
            buf += _pad_two_columns("服务费:", _yuan_str(service_fee), line_width).encode(
                "gbk", errors="replace"
            ) + LF

        # 实付（大字加粗）
        buf += GS_SIZE_DOUBLE_BOTH + ESC_BOLD_ON
        buf += _pad_two_columns("实付:", _yuan_str(total), line_width).encode(
            "gbk", errors="replace"
        ) + LF
        buf += GS_SIZE_NORMAL + ESC_BOLD_OFF
        return bytes(buf)

    def _render_payment_method(
        self, elem: dict, ctx: dict, line_width: int
    ) -> bytes:
        """支付方式 + 找零。"""
        show_change = elem.get("show_change", True)

        method = ctx.get("payment_method", "")
        label = _PAYMENT_LABELS.get(method, method)
        payment_amount = ctx.get("payment_amount_yuan", 0.0)
        change = ctx.get("change_yuan", 0.0)

        buf = bytearray()
        buf += ESC_ALIGN_LEFT
        buf += f"支付方式: {label}".encode("gbk", errors="replace") + LF

        if payment_amount > 0:
            buf += _pad_two_columns(
                "收款:", _yuan_str(payment_amount), line_width
            ).encode("gbk", errors="replace") + LF

        if show_change and change > 0:
            buf += _pad_two_columns(
                "找零:", _yuan_str(change), line_width
            ).encode("gbk", errors="replace") + LF

        return bytes(buf)

    def _render_qrcode(
        self, elem: dict, ctx: dict, line_width: int
    ) -> bytes:
        """二维码。"""
        content_field = elem.get("content_field", "order_id")
        static_content = elem.get("content", "")
        size = elem.get("size", 6)

        # 静态内容优先，否则从 context 取字段
        content = static_content or ctx.get(content_field, "")
        if not content:
            return b""

        buf = bytearray()
        buf += ESC_ALIGN_CENTER
        buf += _build_qrcode(content, size)
        buf += ESC_ALIGN_LEFT
        return bytes(buf)

    def _render_barcode(
        self, elem: dict, ctx: dict, line_width: int
    ) -> bytes:
        """条形码。"""
        content_field = elem.get("content_field", "order_no")
        static_content = elem.get("content", "")
        barcode_type = elem.get("barcode_type", "CODE128")

        content = static_content or ctx.get(content_field, "")
        if not content:
            return b""

        return _build_barcode(str(content), barcode_type)

    def _render_custom_text(
        self, elem: dict, ctx: dict, line_width: int
    ) -> bytes:
        """自定义文字（支持 {{变量}} 模板替换）。"""
        raw_content = elem.get("content", "")
        content = _apply_template_vars(raw_content, ctx)
        align = _ALIGN_BYTES.get(elem.get("align", "center"), ESC_ALIGN_CENTER)
        bold = elem.get("bold", False)
        size = _SIZE_BYTES.get(elem.get("size", "normal"), GS_SIZE_NORMAL)

        buf = bytearray()
        buf += align + size
        if bold:
            buf += ESC_BOLD_ON
        buf += content.encode("gbk", errors="replace") + LF
        if bold:
            buf += ESC_BOLD_OFF
        buf += GS_SIZE_NORMAL + ESC_ALIGN_LEFT
        return bytes(buf)

    def _render_blank_lines(
        self, elem: dict, ctx: dict, line_width: int
    ) -> bytes:
        """空行。"""
        count = max(1, min(10, elem.get("count", 1)))
        return LF * count

    def _render_logo_text(
        self, elem: dict, ctx: dict, line_width: int
    ) -> bytes:
        """品牌口号/备注文字，同 custom_text 但默认居中。"""
        raw_content = elem.get("content", "")
        content = _apply_template_vars(raw_content, ctx)
        align = _ALIGN_BYTES.get(elem.get("align", "center"), ESC_ALIGN_CENTER)
        bold = elem.get("bold", False)

        buf = bytearray()
        buf += align
        if bold:
            buf += ESC_BOLD_ON
        buf += content.encode("gbk", errors="replace") + LF
        if bold:
            buf += ESC_BOLD_OFF
        buf += ESC_ALIGN_LEFT
        return bytes(buf)


# 模块级单例（供其他模块 import 使用）
template_renderer = TemplateRenderer()
