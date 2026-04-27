"""活鲜称重单 / 宴席通知单 / 企业挂账单 — ESC/POS 打印模板服务

支持纸宽：
  58mm  32字符/行（ASCII）
  80mm  48字符/行（ASCII）

输出格式：base64编码的 ESC/POS 字节流，供 TXBridge.print() 直接调用。
编码：GBK（热敏打印机中文标准）
"""

import base64
from datetime import datetime
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# ─── ESC/POS 指令常量 ──────────────────────────────────────────────────────────

ESC_INIT = b"\x1b\x40"  # 初始化打印机
ESC_ALIGN_LEFT = b"\x1b\x61\x00"  # 左对齐
ESC_ALIGN_CENTER = b"\x1b\x61\x01"  # 居中
ESC_ALIGN_RIGHT = b"\x1b\x61\x02"  # 右对齐
ESC_BOLD_ON = b"\x1b\x45\x01"  # 加粗开
ESC_BOLD_OFF = b"\x1b\x45\x00"  # 加粗关
GS_SIZE_NORMAL = b"\x1d\x21\x00"  # 正常字号
GS_SIZE_DBL_W = b"\x1d\x21\x10"  # 双倍宽
GS_SIZE_DBL_BOTH = b"\x1d\x21\x11"  # 双倍宽高
GS_CUT_PARTIAL = b"\x1d\x56\x01"  # 半切
ESC_CHINESE_ON = b"\x1c\x26"  # 中文模式开
LF = b"\x0a"  # 换行

# 纸宽字符数
WIDTH_58MM = 32
WIDTH_80MM = 48


# ─── 内部工具函数 ──────────────────────────────────────────────────────────────


def _gbk_len(text: str) -> int:
    """文本的 GBK 字节宽度（中文2字节，ASCII 1字节）。"""
    return len(text.encode("gbk", errors="replace"))


def _gbk(text: str) -> bytes:
    """字符串转 GBK bytes。"""
    return text.encode("gbk", errors="replace")


def _center_text(text: str, width: int) -> str:
    """居中文本（按GBK宽度）。"""
    text_w = _gbk_len(text)
    if text_w >= width:
        return text
    pad = (width - text_w) // 2
    return " " * pad + text


def _pad_right(text: str, width: int) -> str:
    """右侧填充空格到指定宽度。"""
    text_w = _gbk_len(text)
    if text_w >= width:
        return text
    return text + " " * (width - text_w)


def _two_col(left: str, right: str, width: int) -> str:
    """左右两列对齐。"""
    lw = _gbk_len(left)
    rw = _gbk_len(right)
    spaces = max(1, width - lw - rw)
    return left + " " * spaces + right


def _line(width: int, char: str = "-") -> str:
    """打印分割线。"""
    # 一个 '-' 是1字节，直接用字符数
    return char * width


def _fmt_yuan(fen: int) -> str:
    """分转元字符串，带 ¥ 前缀。"""
    return f"\xa5{fen / 100:.2f}"  # \xa5 = GBK ¥


def _fmt_weight(gram: float) -> str:
    """克转斤/kg 显示。"""
    if gram >= 500:
        kg = gram / 1000
        return f"{kg:.3f}kg"
    return f"{gram:.0f}g"


def _build(chunks: list) -> bytes:
    """拼接 bytes 列表，str 自动转 GBK。"""
    out = b""
    for c in chunks:
        if isinstance(c, bytes):
            out += c
        elif isinstance(c, str):
            out += _gbk(c)
    return out


def _get_width(store_config: Optional[dict]) -> int:
    """从 store_config 获取纸宽字符数，默认80mm。"""
    if store_config and store_config.get("paper_width_mm") == 58:
        return WIDTH_58MM
    return WIDTH_80MM


# ─── 公共模块：页头 / 页脚 ─────────────────────────────────────────────────────


def _header_block(
    title: str,
    store_name: str,
    width: int,
    subtitle: str = "",
) -> bytes:
    """生成通用页头：门店名（大字）+ 单据标题 + 可选副标题。"""
    chunks: list = [
        ESC_INIT,
        ESC_CHINESE_ON,
        ESC_ALIGN_CENTER,
        GS_SIZE_DBL_BOTH,
        ESC_BOLD_ON,
        store_name,
        LF,
        GS_SIZE_NORMAL,
        ESC_BOLD_OFF,
        ESC_BOLD_ON,
        title,
        ESC_BOLD_OFF,
        LF,
    ]
    if subtitle:
        chunks += [subtitle, LF]
    chunks += [
        ESC_ALIGN_LEFT,
        _line(width),
        LF,
    ]
    return _build(chunks)


def _footer_block(width: int, extra_lines: int = 3) -> bytes:
    """生成通用页脚：感谢语 + 走纸 + 切纸。"""
    chunks: list = [
        ESC_ALIGN_CENTER,
        _line(width, "="),
        LF,
        "*** 屯象OS ***",
        LF,
    ]
    for _ in range(extra_lines):
        chunks.append(LF)
    chunks.append(GS_CUT_PARTIAL)
    return _build(chunks)


# ─── 任务1-A：活鲜称重单 ───────────────────────────────────────────────────────


def generate_weigh_ticket(record: dict, store_config: Optional[dict] = None) -> str:
    """生成活鲜称重单 ESC/POS base64。

    record 字段：
      store_name      门店名称（必填）
      table_no        桌号
      waiter_name     服务员
      weigh_time      称重时间（str 或 datetime，默认 now）
      dish_name       品种名称（必填）
      tank_name       鱼缸/暂养区名称
      weight_gram     称重克数（必填）
      unit_price_fen  单价（分/500g 或 分/kg，取决于 price_unit）
      price_unit      单价单位：'500g'|'kg'|'g'，默认'500g'
      amount_fen      应收金额（分，必填）
      ticket_no       单据编号（可选）
    """
    width = _get_width(store_config)

    store_name = record.get("store_name", "屯象餐饮")
    table_no = record.get("table_no", "")
    waiter_name = record.get("waiter_name", "")
    dish_name = record.get("dish_name", "")
    tank_name = record.get("tank_name", "")
    weight_gram = float(record.get("weight_gram", 0))
    unit_price_fen = int(record.get("unit_price_fen", 0))
    price_unit = record.get("price_unit", "500g")
    amount_fen = int(record.get("amount_fen", 0))
    ticket_no = record.get("ticket_no", "")

    raw_time = record.get("weigh_time")
    if isinstance(raw_time, datetime):
        weigh_time_str = raw_time.strftime("%Y-%m-%d %H:%M:%S")
    elif raw_time:
        weigh_time_str = str(raw_time)
    else:
        weigh_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    unit_label = f"{_fmt_yuan(unit_price_fen)}/{price_unit}"

    chunks: list = [
        ESC_INIT,
        ESC_CHINESE_ON,
        # ── 页头 ──
        ESC_ALIGN_CENTER,
        GS_SIZE_DBL_BOTH,
        ESC_BOLD_ON,
        store_name,
        LF,
        GS_SIZE_NORMAL,
        ESC_BOLD_OFF,
        ESC_BOLD_ON,
        "【活鲜称重单】",
        ESC_BOLD_OFF,
        LF,
        ESC_ALIGN_LEFT,
        _line(width),
        LF,
        # ── 基本信息 ──
        _two_col("时间:" + weigh_time_str, "桌号:" + table_no, width),
        LF,
    ]
    if waiter_name:
        chunks += [f"服务员：{waiter_name}", LF]
    if ticket_no:
        chunks += [f"单据号：{ticket_no}", LF]
    chunks += [
        _line(width, "-"),
        LF,
        # ── 称重明细 ──
        ESC_BOLD_ON,
        _pad_right("品种", 12) + "鱼缸",
        ESC_BOLD_OFF,
        LF,
        _two_col(dish_name, tank_name or "-", width),
        LF,
        LF,
        ESC_BOLD_ON,
        "称重量",
        ESC_BOLD_OFF,
        LF,
    ]

    # 重量行
    weight_str = _fmt_weight(weight_gram)
    if weight_gram >= 500:
        jin = weight_gram / 500
        weight_str += f"  ({jin:.2f}斤)"
    chunks += [
        ESC_ALIGN_CENTER,
        GS_SIZE_DBL_W,
        ESC_BOLD_ON,
        weight_str,
        LF,
        GS_SIZE_NORMAL,
        ESC_BOLD_OFF,
        ESC_ALIGN_LEFT,
        LF,
        _two_col(f"单价：{unit_label}", f"金额：{_fmt_yuan(amount_fen)}", width),
        LF,
        _line(width, "="),
        LF,
        ESC_ALIGN_CENTER,
        GS_SIZE_DBL_W,
        ESC_BOLD_ON,
        f"合计：{_fmt_yuan(amount_fen)}",
        LF,
        GS_SIZE_NORMAL,
        ESC_BOLD_OFF,
        ESC_ALIGN_LEFT,
        _line(width, "="),
        LF,
        LF,
        # ── 确认签字栏 ──
        "顾客确认签字：",
        LF,
        LF,
        _line(width // 2, "_"),
        LF,
        LF,
        "（签字即表示对称重结果确认无异议）",
        LF,
        LF,
    ]
    chunks.append(_footer_block(width))

    data = _build(chunks)
    encoded = base64.b64encode(data).decode("ascii")
    logger.info("weigh_ticket_generated", dish=dish_name, weight_gram=weight_gram, amount_fen=amount_fen)
    return encoded


# ─── 任务1-B：宴席通知单 ──────────────────────────────────────────────────────

# 宴席节中文名映射（兜底展示）
_SECTION_NAMES = {
    "cold": "凉菜",
    "hot": "热菜",
    "seafood": "海鲜",
    "soup": "汤品",
    "staple": "主食",
    "dessert": "甜点",
    "fruit": "水果",
}


def generate_banquet_notice(
    session: dict,
    menu_sections: list,
    store_config: Optional[dict] = None,
) -> str:
    """生成宴席通知单 ESC/POS base64。

    session 字段：
      store_name        门店名称
      contract_no       合同号
      customer_name     客户/主办方
      customer_phone    联系电话（可选）
      start_time        开席时间（str 或 datetime）
      table_count       桌数
      pax_per_table     每桌人数
      banquet_type      宴席类型（婚宴/寿宴/商务宴等）
      menu_name         菜单档次名称（如"珍品宴·10800元/桌"）
      special_notes     特殊备注（可选）
      printed_by        打印人（可选）
      print_time        打印时间（可选，默认now）

    menu_sections 是列表，每项：
      section_type   节类型（cold/hot/seafood/soup/staple…）
      section_name   节名称（可覆盖默认中文名）
      sort_order     出品顺序（整数）
      dishes         list of dict: {dish_name, quantity, unit, notes}
    """
    width = _get_width(store_config)

    store_name = session.get("store_name", "屯象餐饮")
    contract_no = session.get("contract_no", "")
    customer_name = session.get("customer_name", "")
    customer_phone = session.get("customer_phone", "")
    table_count = int(session.get("table_count", 0))
    pax_per_table = int(session.get("pax_per_table", 0))
    banquet_type = session.get("banquet_type", "宴席")
    menu_name = session.get("menu_name", "")
    special_notes = session.get("special_notes", "")
    printed_by = session.get("printed_by", "")

    raw_start = session.get("start_time")
    if isinstance(raw_start, datetime):
        start_str = raw_start.strftime("%Y-%m-%d %H:%M")
    elif raw_start:
        start_str = str(raw_start)
    else:
        start_str = "待定"

    raw_print = session.get("print_time")
    if isinstance(raw_print, datetime):
        print_str = raw_print.strftime("%Y-%m-%d %H:%M")
    elif raw_print:
        print_str = str(raw_print)
    else:
        print_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── 页头 ──
    chunks: list = [
        ESC_INIT,
        ESC_CHINESE_ON,
        ESC_ALIGN_CENTER,
        GS_SIZE_DBL_BOTH,
        ESC_BOLD_ON,
        store_name,
        LF,
        GS_SIZE_NORMAL,
        ESC_BOLD_OFF,
        ESC_BOLD_ON,
        f"【{banquet_type}通知单】",
        ESC_BOLD_OFF,
        LF,
        ESC_ALIGN_LEFT,
        _line(width),
        LF,
    ]

    # ── 宴席基本信息 ──
    if contract_no:
        chunks += [f"合同号：{contract_no}", LF]
    chunks += [
        _two_col(f"客户：{customer_name}", f"电话：{customer_phone or '-'}", width),
        LF,
        f"类型：{banquet_type}  菜单：{menu_name}",
        LF,
        f"开席：{start_str}",
        LF,
        _two_col(f"桌数：{table_count}桌", f"每桌：{pax_per_table}人", width),
        LF,
        _line(width, "-"),
        LF,
    ]

    # ── 各节菜品清单 ──
    sorted_sections = sorted(menu_sections, key=lambda s: int(s.get("sort_order", 0)))
    for sec in sorted_sections:
        sec_type = sec.get("section_type", "")
        sec_name = sec.get("section_name") or _SECTION_NAMES.get(sec_type, sec_type or "其他")
        sort_order = sec.get("sort_order", "")
        dishes = sec.get("dishes", [])

        order_label = f"第{sort_order}道" if sort_order else ""
        chunks += [
            ESC_BOLD_ON,
            f"▌ {order_label}  {sec_name}",
            ESC_BOLD_OFF,
            LF,
        ]

        for dish in dishes:
            dish_name = dish.get("dish_name", "")
            quantity = dish.get("quantity", "")
            unit = dish.get("unit", "份")
            notes = dish.get("notes", "")
            qty_str = f"{quantity}{unit}" if quantity else ""
            if notes:
                line = _two_col(f"  · {dish_name}", f"{qty_str} {notes}", width)
            else:
                line = _two_col(f"  · {dish_name}", qty_str, width)
            chunks += [line, LF]

        chunks.append(LF)

    # ── 特殊备注 ──
    if special_notes:
        chunks += [
            _line(width, "-"),
            LF,
            ESC_BOLD_ON,
            "【特殊备注】",
            ESC_BOLD_OFF,
            LF,
            special_notes,
            LF,
            LF,
        ]

    # ── 页脚 ──
    chunks += [
        _line(width, "="),
        LF,
        _two_col(f"打印：{printed_by or '-'}", f"时间：{print_str}", width),
        LF,
        "（本通知单由屯象OS自动生成，请妥善保存）",
        LF,
        LF,
        LF,
        LF,
        GS_CUT_PARTIAL,
    ]

    data = _build(chunks)
    encoded = base64.b64encode(data).decode("ascii")
    logger.info(
        "banquet_notice_generated",
        contract_no=contract_no,
        sections_count=len(menu_sections),
    )
    return encoded


# ─── 任务1-C：企业挂账单 ──────────────────────────────────────────────────────


def generate_credit_account_ticket(
    order: dict,
    credit_info: dict,
    store_config: Optional[dict] = None,
) -> str:
    """生成企业挂账单 ESC/POS base64。

    order 字段：
      store_name        门店名称
      order_no          订单号
      table_no          桌号
      order_time        下单时间
      items             list of dict: {item_name, quantity, unit_price_fen, subtotal_fen}
      total_amount_fen  订单总额（分）
      final_amount_fen  实收金额（分）
      discount_amount_fen  优惠金额（分）
      cashier_name      收银员

    credit_info 字段：
      company_name      挂账单位名称（必填）
      company_code      单位代码（可选）
      contact_name      经办人姓名
      contact_phone     经办人电话（可选）
      credit_limit_fen  授信额度（分，可选）
      current_balance_fen  当前挂账余额（分，可选）
      notes             备注（可选）
    """
    width = _get_width(store_config)

    store_name = order.get("store_name", "屯象餐饮")
    order_no = order.get("order_no", "")
    table_no = order.get("table_no", "")
    items = order.get("items", [])
    total_fen = int(order.get("total_amount_fen", 0))
    final_fen = int(order.get("final_amount_fen", total_fen))
    discount_fen = int(order.get("discount_amount_fen", 0))
    cashier_name = order.get("cashier_name", "")

    raw_time = order.get("order_time")
    if isinstance(raw_time, datetime):
        time_str = raw_time.strftime("%Y-%m-%d %H:%M:%S")
    elif raw_time:
        time_str = str(raw_time)
    else:
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    company_name = credit_info.get("company_name", "")
    company_code = credit_info.get("company_code", "")
    contact_name = credit_info.get("contact_name", "")
    contact_phone = credit_info.get("contact_phone", "")
    credit_limit_fen = credit_info.get("credit_limit_fen")
    balance_fen = credit_info.get("current_balance_fen")
    notes = credit_info.get("notes", "")

    chunks: list = [
        ESC_INIT,
        ESC_CHINESE_ON,
        # ── 页头 ──
        ESC_ALIGN_CENTER,
        GS_SIZE_DBL_BOTH,
        ESC_BOLD_ON,
        store_name,
        LF,
        GS_SIZE_NORMAL,
        ESC_BOLD_OFF,
        ESC_BOLD_ON,
        "【企业挂账单】",
        ESC_BOLD_OFF,
        LF,
        ESC_ALIGN_LEFT,
        _line(width),
        LF,
        # ── 订单信息 ──
        f"单号：{order_no}",
        LF,
        _two_col(f"桌号：{table_no}", f"时间：{time_str[:16]}", width),
        LF,
        _two_col(f"收银：{cashier_name}", "", width),
        LF,
        _line(width, "-"),
        LF,
    ]

    # ── 消费明细 ──
    if items:
        # 表头
        header = _pad_right("品名", width - 20) + _pad_right("数量", 6) + _pad_right("单价", 8) + "小计"
        chunks += [ESC_BOLD_ON, header, ESC_BOLD_OFF, LF]
        for item in items:
            item_name = item.get("item_name", "")
            qty = item.get("quantity", 1)
            u_price_fen = int(item.get("unit_price_fen", 0))
            sub_fen = int(item.get("subtotal_fen", 0))
            name_w = width - 20
            name_truncated = item_name
            if _gbk_len(item_name) > name_w:
                # 截断
                encoded_name = item_name.encode("gbk", errors="replace")
                name_truncated = encoded_name[:name_w].decode("gbk", errors="replace")
            row = (
                _pad_right(name_truncated, name_w)
                + _pad_right(str(qty), 6)
                + _pad_right(_fmt_yuan(u_price_fen), 8)
                + _fmt_yuan(sub_fen)
            )
            chunks += [row, LF]
        chunks += [_line(width, "-"), LF]

    # ── 金额汇总 ──
    chunks += [
        _two_col("消费合计：", _fmt_yuan(total_fen), width),
        LF,
    ]
    if discount_fen:
        chunks += [_two_col("优惠减免：", f"-{_fmt_yuan(discount_fen)}", width), LF]
    chunks += [
        ESC_BOLD_ON,
        _two_col("挂账金额：", _fmt_yuan(final_fen), width),
        LF,
        ESC_BOLD_OFF,
        _line(width, "="),
        LF,
    ]

    # ── 挂账单位信息 ──
    chunks += [
        ESC_BOLD_ON,
        "【挂账单位信息】",
        ESC_BOLD_OFF,
        LF,
        f"单位名称：{company_name}",
        LF,
    ]
    if company_code:
        chunks += [f"单位代码：{company_code}", LF]
    chunks += [
        _two_col(f"经办人：{contact_name}", f"电话：{contact_phone or '-'}", width),
        LF,
    ]
    if credit_limit_fen is not None:
        chunks += [_two_col(f"授信额度：{_fmt_yuan(int(credit_limit_fen))}", "", width), LF]
    if balance_fen is not None:
        new_balance = int(balance_fen) + final_fen
        chunks += [
            _two_col(f"原挂账余额：{_fmt_yuan(int(balance_fen))}", "", width),
            LF,
            ESC_BOLD_ON,
            _two_col(f"本次后余额：{_fmt_yuan(new_balance)}", "", width),
            LF,
            ESC_BOLD_OFF,
        ]
    if notes:
        chunks += [f"备注：{notes}", LF]

    # ── 签字确认栏 ──
    chunks += [
        _line(width, "-"),
        LF,
        "经办人签字确认：",
        LF,
        LF,
        _line(width // 2, "_") + "        " + _line(width // 4, "_"),
        LF,
        "（签字）                          （日期）",
        LF,
        LF,
        "单位盖章：",
        LF,
        LF,
        _line(width // 2, "_"),
        LF,
        LF,
        "（本单一式两联：门店存根 / 单位留存）",
        LF,
        LF,
    ]
    chunks.append(_footer_block(width))

    data = _build(chunks)
    encoded = base64.b64encode(data).decode("ascii")
    logger.info(
        "credit_ticket_generated",
        order_no=order_no,
        company_name=company_name,
        final_fen=final_fen,
    )
    return encoded
