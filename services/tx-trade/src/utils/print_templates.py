"""
打印模板工具 — 生成格式化打印文本（语义标记DSL）

使用语义标记，由 android-shell TXBridge 解析为 ESC/POS 指令。

标记格式：
  [CENTER]内容[/CENTER]   居中
  [BOLD]内容[/BOLD]       加粗
  [LEFT]内容[/LEFT]       左对齐
  [RIGHT]内容[/RIGHT]     右对齐
  [SMALL]内容[/SMALL]     小号字体
  [LARGE]内容[/LARGE]     大号字体（双倍高）
  [DIVIDER]               全宽分隔线 ─ (=)
  [DIVIDER_THIN]          全宽细分隔线 (-)
  [CUT]                   切纸
  [FEED:N]                走纸N行
"""
from __future__ import annotations

from typing import Optional

# ─── 基础标记构建函数 ──────────────────────────────────────────────────────────

def center(text: str) -> str:
    """居中对齐标记。"""
    return f"[CENTER]{text}[/CENTER]"


def bold(text: str) -> str:
    """加粗标记。"""
    return f"[BOLD]{text}[/BOLD]"


def left(text: str) -> str:
    """左对齐标记。"""
    return f"[LEFT]{text}[/LEFT]"


def right(text: str) -> str:
    """右对齐标记。"""
    return f"[RIGHT]{text}[/RIGHT]"


def small(text: str) -> str:
    """小号字体标记。"""
    return f"[SMALL]{text}[/SMALL]"


def large(text: str) -> str:
    """大号字体（双倍高）标记。"""
    return f"[LARGE]{text}[/LARGE]"


def divider() -> str:
    """全宽等号分隔线。"""
    return "[DIVIDER]"


def divider_thin() -> str:
    """全宽短横分隔线。"""
    return "[DIVIDER_THIN]"


def cut() -> str:
    """切纸指令。"""
    return "[CUT]"


def feed(lines: int = 1) -> str:
    """走纸N行。"""
    return f"[FEED:{lines}]"


# ─── 辅助工具 ─────────────────────────────────────────────────────────────────

def _gbk_len(text: str) -> int:
    """计算文本的 GBK 字节宽度（中文算2字符，ASCII算1字符）。"""
    return len(text.encode("gbk", errors="replace"))


def row(left_text: str, right_text: str, width: int = 32) -> str:
    """生成左右对齐的一行，总宽度 width 字符（GBK字节宽度）。

    Args:
        left_text:  左侧内容
        right_text: 右侧内容
        width:      总宽度（GBK字符数），默认32（80mm纸宽的中文字符数）

    Returns:
        格式化后的一行字符串（不含换行）
    """
    lw = _gbk_len(left_text)
    rw = _gbk_len(right_text)
    spaces = max(1, width - lw - rw)
    return left_text + " " * spaces + right_text


def _fmt_fen(fen: int) -> str:
    """分转元，格式化为 ¥XX.XX。"""
    return f"¥{fen / 100:.2f}"


def _fmt_fen_per_jin(fen_per_jin: int) -> str:
    """每斤单价（分）转元，格式化为 ¥XX.XX/斤。"""
    return f"¥{fen_per_jin / 100:.2f}/斤"


# ─── 活鲜称重单模板 ───────────────────────────────────────────────────────────

def render_live_seafood_receipt(data: dict) -> str:
    """生成活鲜称重单语义标记文本。

    Args:
        data: 称重单数据，字段说明：
            store_name (str):        门店名称，如"徐记海鲜·解放西路店"
            table_no (str):          桌台编号，如"A8"
            printed_at (str):        打印时间，如"2026-04-02 18:35"
            operator (str):          操作员姓名
            items (list[dict]):      称重条目列表，每项包含：
                dish_name (str):         菜品名称
                tank_zone (str):         鱼缸区域，如"A1鱼缸"
                weight_kg (float):       重量（千克）
                weight_jin (float):      重量（斤）
                price_per_jin_fen (int): 单价（分/斤）
                total_fen (int):         小计（分）
                note (str, optional):    备注，如"客户已验鱼"
            total_fen (int):         合计金额（分）

    Returns:
        语义标记字符串，可由 TXBridge.print() 直接使用
    """
    store_name: str = data.get("store_name", "屯象餐饮")
    table_no: str = data.get("table_no", "")
    printed_at: str = data.get("printed_at", "")
    operator: str = data.get("operator", "")
    items: list = data.get("items", [])
    total_fen: int = int(data.get("total_fen", 0))

    # 从打印时间中提取 HH:MM（如"2026-04-02 18:35" → "18:35"）
    time_short = printed_at.split(" ")[-1] if " " in printed_at else printed_at

    lines: list[str] = []

    # ── 页头 ──
    lines.append(center(bold("★ 活鲜称重单 ★")))
    lines.append(center(store_name))
    lines.append(divider())

    # ── 基本信息 ──
    if table_no and time_short:
        lines.append(left(row(f"桌台: {table_no}", f"时间: {time_short}")))
    elif table_no:
        lines.append(left(f"桌台: {table_no}"))
    if operator:
        lines.append(left(f"操作员: {operator}"))
    lines.append(divider())

    # ── 称重明细 ──
    for item in items:
        dish_name: str = item.get("dish_name", "")
        tank_zone: str = item.get("tank_zone", "")
        weight_kg: float = float(item.get("weight_kg", 0))
        weight_jin: float = float(item.get("weight_jin", weight_kg * 2))
        price_per_jin_fen: int = int(item.get("price_per_jin_fen", 0))
        item_total_fen: int = int(item.get("total_fen", 0))
        note: str = item.get("note", "")

        lines.append(left(bold(dish_name)))
        if tank_zone:
            lines.append(left(f"来源: {tank_zone}"))
        lines.append(left(f"重量: {weight_kg:.3f}kg ({weight_jin:.2f}斤)"))
        lines.append(left(_fmt_fen_per_jin(price_per_jin_fen).join(["单价: ", ""])))
        lines.append(left(f"金额: {_fmt_fen(item_total_fen)}"))
        if note:
            lines.append(left(f"{note} ✓"))
        lines.append(divider_thin())

    # ── 合计 ──
    lines.append(left(bold(f"合计: {_fmt_fen(total_fen)}")))
    lines.append(divider())

    # ── 页脚提示 ──
    lines.append(center(small("此单据为称重凭证，请保留")))
    lines.append(center(small("如有异议请在用餐前提出")))
    lines.append(divider())

    # 走纸 + 切纸
    lines.append(feed(3))
    lines.append(cut())

    return "\n".join(lines)


# ─── 宴席通知单模板 ───────────────────────────────────────────────────────────

def render_banquet_notice(data: dict) -> str:
    """生成宴席通知单语义标记文本（发给后厨各档口的出品计划）。

    Args:
        data: 宴席通知单数据，字段说明：
            store_name (str):        门店名称
            banquet_name (str):      宴席名称，如"2026-04-02 张总婚宴"
            session_no (int):        场次编号，如1
            table_count (int):       桌数
            party_size (int):        总人数
            arrive_time (str):       到场时间，如"18:00"
            start_time (str):        开席时间，如"18:30"
            printed_at (str):        打印时间
            contact_name (str):      联系人姓名
            contact_phone (str):     联系人电话（已脱敏）
            package_name (str):      套餐名称，如"豪华海鲜套餐 ¥3,980/桌"
            sections (list[dict]):   出品节次列表，每项包含：
                section_name (str):      节次名称，如"冷盘"
                serve_time (str):        上桌时间，如"18:30"
                items (list[dict]):      菜品列表，每项包含：
                    name (str):              菜品名称
                    qty_per_table (int):     每桌份数
                    note (str, optional):    备注，如"提前1小时腌制"
            special_notes (str):     特别注意事项（可选）
            dept (str):              此通知单发给哪个档口（可选）

    Returns:
        语义标记字符串，可由 TXBridge.print() 直接使用
    """
    store_name: str = data.get("store_name", "屯象餐饮")
    banquet_name: str = data.get("banquet_name", "")
    session_no: int = int(data.get("session_no", 1))
    table_count: int = int(data.get("table_count", 0))
    party_size: int = int(data.get("party_size", 0))
    arrive_time: str = data.get("arrive_time", "")
    start_time: str = data.get("start_time", "")
    printed_at: str = data.get("printed_at", "")
    contact_name: str = data.get("contact_name", "")
    contact_phone: str = data.get("contact_phone", "")
    package_name: str = data.get("package_name", "")
    sections: list = data.get("sections", [])
    special_notes: str = data.get("special_notes", "")
    dept: str = data.get("dept", "")

    lines: list[str] = []

    # ── 页头 ──
    lines.append(center(bold("宴席出品通知单")))
    lines.append(center(store_name))
    if banquet_name:
        lines.append(center(f"{banquet_name}  第{session_no}场"))
    lines.append(divider_thin())

    # ── 宴席基本信息 ──
    if arrive_time and start_time:
        lines.append(left(row(f"到场: {arrive_time}", f"开席: {start_time}")))
    if table_count and party_size:
        lines.append(left(row(f"桌数: {table_count}桌", f"人数: 约{party_size}人")))
    elif table_count:
        lines.append(left(f"桌数: {table_count}桌"))
    if package_name:
        lines.append(left(f"套餐: {package_name}"))
    if contact_name or contact_phone:
        lines.append(left(f"联系: {contact_name} {contact_phone}".strip()))
    if dept:
        lines.append(center(bold(f"发给: 【{dept}】")))
    lines.append(divider())

    # ── 特别注意 ──
    if special_notes:
        lines.append(center(bold("⚠  特别注意:")))
        lines.append(left(special_notes))
        lines.append(divider())

    # ── 各节次出品计划 ──
    for section in sections:
        section_name: str = section.get("section_name", "")
        serve_time: str = section.get("serve_time", "")
        section_items: list = section.get("items", [])

        # 节次标题行
        if serve_time:
            lines.append(left(row(bold(f"【{section_name}】"), f"上桌时间: {serve_time}")))
        else:
            lines.append(left(bold(f"【{section_name}】")))

        # 菜品列表
        for dish_item in section_items:
            item_name: str = dish_item.get("name", "")
            qty_per_table: int = int(dish_item.get("qty_per_table", 1))
            item_note: str = dish_item.get("note", "")
            total_qty: int = qty_per_table * table_count

            # 格式: "  红烧东星斑    × 1/桌  = 20份"
            qty_info = f"x{qty_per_table}/桌 = {total_qty}份" if table_count else f"x{qty_per_table}/桌"
            lines.append(left(row(f"  {item_name}", qty_info)))

            # 注意事项独占一行
            if item_note:
                lines.append(left(f"  -> {item_note}！"))

        lines.append(divider_thin())

    # ── 页脚 ──
    lines.append(divider())
    if printed_at:
        lines.append(left(f"打印时间: {printed_at}"))
    lines.append(center(small("请妥善保管，出品按此单执行")))
    lines.append(divider())

    # 走纸 + 切纸
    lines.append(feed(3))
    lines.append(cut())

    return "\n".join(lines)


# ─── Mock 数据（调试用）────────────────────────────────────────────────────────

def _mock_live_seafood_receipt() -> dict:
    """活鲜称重单 Mock 数据。"""
    return {
        "store_name": "徐记海鲜·解放西路店",
        "table_no": "A8",
        "printed_at": "2026-04-02 18:35",
        "operator": "小王",
        "items": [
            {
                "dish_name": "清蒸石斑鱼",
                "tank_zone": "A1鱼缸",
                "weight_kg": 1.35,
                "weight_jin": 2.70,
                "price_per_jin_fen": 12800,
                "total_fen": 34560,
                "note": "客户已验鱼",
            },
            {
                "dish_name": "白灼活虾",
                "tank_zone": "B2虾池",
                "weight_kg": 0.50,
                "weight_jin": 1.00,
                "price_per_jin_fen": 8800,
                "total_fen": 8800,
                "note": "",
            },
        ],
        "total_fen": 43360,
    }


def _mock_banquet_notice(dept: Optional[str] = "热菜档口") -> dict:
    """宴席通知单 Mock 数据。"""
    return {
        "store_name": "徐记海鲜",
        "banquet_name": "2026-04-02 张总婚宴",
        "session_no": 1,
        "table_count": 20,
        "party_size": 200,
        "arrive_time": "18:00",
        "start_time": "18:30",
        "printed_at": "2026-04-02 15:00",
        "contact_name": "张先生",
        "contact_phone": "138****1234",
        "package_name": "豪华海鲜套餐 ¥3,980/桌",
        "sections": [
            {
                "section_name": "冷盘",
                "serve_time": "18:30",
                "items": [
                    {"name": "卤水拼盘", "qty_per_table": 1, "note": ""},
                    {"name": "醉虾", "qty_per_table": 1, "note": "提前1小时腌制"},
                ],
            },
            {
                "section_name": "热菜第一波",
                "serve_time": "18:45",
                "items": [
                    {"name": "红烧东星斑", "qty_per_table": 1, "note": ""},
                    {"name": "佛跳墙", "qty_per_table": 1, "note": "提前2小时准备"},
                    {"name": "清蒸石斑鱼", "qty_per_table": 1, "note": ""},
                ],
            },
            {
                "section_name": "主食",
                "serve_time": "19:30",
                "items": [
                    {"name": "扬州炒饭", "qty_per_table": 1, "note": ""},
                    {"name": "海鲜汤", "qty_per_table": 1, "note": ""},
                ],
            },
        ],
        "special_notes": "新郎对海鲜过敏，第5桌单独备素菜",
        "dept": dept or "热菜档口",
    }
