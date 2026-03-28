"""厨打服务 — 自动生成 ESC/POS 厨打单并发送到档口打印机

负责：
1. 订单分单后，按档口生成厨打单并发送到对应网络打印机
2. 催菜/重做时，生成催单/重做厨打单
3. 通过 Mac mini 的 /api/print 接口桥接发送

所有打印内容使用 receipt_service.py 中的 ESC/POS 工具常量。
"""
import base64
import os
from datetime import datetime, timezone

import httpx
import structlog

from .receipt_service import (
    ESC, GS, LF, CUT,
    ALIGN_CENTER, ALIGN_LEFT,
    BOLD_ON, BOLD_OFF,
    DOUBLE_HEIGHT, NORMAL_SIZE,
)

logger = structlog.get_logger()

# Mac mini 打印代理地址
MAC_STATION_URL = os.getenv("MAC_STATION_URL", "http://localhost:8000")

# 打印超时（秒）
PRINT_TIMEOUT_SEC = 5


# ─── 厨打单格式化 ───


def format_kitchen_ticket(
    dept_name: str,
    table_number: str,
    order_no: str,
    items: list[dict],
    seq: int = 0,
    paper_width: int = 80,
) -> bytes:
    """生成标准厨打单 ESC/POS 字节流。

    格式：
    ┌──────────────────────────────┐
    │       [热菜档]               │  (居中大字)
    │ 桌号: A03  单号: 230001      │
    │ ──────────────────────────── │
    │   宫保鸡丁  x2               │  (大字加粗)
    │     [不要花生]               │  (备注)
    │   水煮鱼    x1               │
    │ ──────────────────────────── │
    │ 序号: #3  14:30              │
    └──────────────────────────────┘

    Args:
        dept_name: 档口名称
        table_number: 桌号
        order_no: 订单号
        items: [{"dish_name": ..., "quantity": ..., "notes": ...}]
        seq: 出品序号
        paper_width: 纸宽 58/80

    Returns:
        ESC/POS 字节流
    """
    cols = 48 if paper_width == 80 else 32
    sep = b'-' * cols + LF
    buf = bytearray()

    # 初始化打印机
    buf += ESC + b'\x40'

    # 档口名（居中大字加粗）
    buf += ALIGN_CENTER + DOUBLE_HEIGHT + BOLD_ON
    buf += f"[{dept_name}]\n".encode('gbk', errors='replace')
    buf += NORMAL_SIZE + BOLD_OFF

    # 桌号 + 订单号
    buf += ALIGN_LEFT
    buf += BOLD_ON
    buf += f"桌号: {table_number or '-'}".encode('gbk', errors='replace')
    buf += f"  单号: {order_no[-6:] if len(order_no) > 6 else order_no}\n".encode('gbk', errors='replace')
    buf += BOLD_OFF
    buf += sep

    # 菜品列表（大字加粗）
    for item in items:
        dish_name = item.get("dish_name", item.get("item_name", ""))
        quantity = item.get("quantity", 1)
        notes = item.get("notes", "")

        buf += BOLD_ON + DOUBLE_HEIGHT
        buf += f"  {dish_name}  x{quantity}\n".encode('gbk', errors='replace')
        buf += NORMAL_SIZE + BOLD_OFF

        if notes:
            buf += f"    [{notes}]\n".encode('gbk', errors='replace')

    buf += sep

    # 序号 + 时间
    now_str = datetime.now(timezone.utc).strftime("%H:%M")
    if seq > 0:
        buf += f"序号: #{seq}  {now_str}\n".encode('gbk', errors='replace')
    else:
        buf += f"时间: {now_str}\n".encode('gbk', errors='replace')

    buf += LF + CUT
    return bytes(buf)


def format_rush_ticket(
    dept_name: str,
    table_number: str,
    dish_name: str,
    quantity: int = 1,
    order_no: str = "",
    paper_width: int = 80,
) -> bytes:
    """生成催菜厨打单 — 大字 '催' + 菜品名。

    格式：
    ┌──────────────────────────────┐
    │       ★★★ 催 ★★★            │  (居中超大字)
    │       [热菜档]               │
    │ ──────────────────────────── │
    │   宫保鸡丁  x2               │  (大字加粗)
    │   桌号: A03                  │
    └──────────────────────────────┘
    """
    cols = 48 if paper_width == 80 else 32
    sep = b'-' * cols + LF
    buf = bytearray()

    buf += ESC + b'\x40'

    # 超大字 "催"
    buf += ALIGN_CENTER + DOUBLE_HEIGHT + BOLD_ON
    buf += "*** 催 ***\n".encode('gbk', errors='replace')
    buf += NORMAL_SIZE + BOLD_OFF

    # 档口名
    buf += BOLD_ON
    buf += f"[{dept_name}]\n".encode('gbk', errors='replace')
    buf += BOLD_OFF
    buf += sep

    # 菜品（大字加粗）
    buf += ALIGN_LEFT + BOLD_ON + DOUBLE_HEIGHT
    buf += f"  {dish_name}  x{quantity}\n".encode('gbk', errors='replace')
    buf += NORMAL_SIZE + BOLD_OFF

    # 桌号
    buf += BOLD_ON
    buf += f"  桌号: {table_number or '-'}".encode('gbk', errors='replace')
    if order_no:
        buf += f"  单号: {order_no[-6:]}\n".encode('gbk', errors='replace')
    else:
        buf += LF
    buf += BOLD_OFF

    buf += LF + CUT
    return bytes(buf)


def format_remake_ticket(
    dept_name: str,
    table_number: str,
    dish_name: str,
    reason: str,
    quantity: int = 1,
    order_no: str = "",
    paper_width: int = 80,
) -> bytes:
    """生成重做厨打单 — 大字 '重做' + 菜品名 + 原因。

    格式：
    ┌──────────────────────────────┐
    │       ★★ 重做 ★★            │  (居中超大字)
    │       [热菜档]               │
    │ ──────────────────────────── │
    │   宫保鸡丁  x1               │  (大字加粗)
    │   原因: 太咸                 │
    │   桌号: A03                  │
    └──────────────────────────────┘
    """
    cols = 48 if paper_width == 80 else 32
    sep = b'-' * cols + LF
    buf = bytearray()

    buf += ESC + b'\x40'

    # 超大字 "重做"
    buf += ALIGN_CENTER + DOUBLE_HEIGHT + BOLD_ON
    buf += "** 重做 **\n".encode('gbk', errors='replace')
    buf += NORMAL_SIZE + BOLD_OFF

    # 档口名
    buf += BOLD_ON
    buf += f"[{dept_name}]\n".encode('gbk', errors='replace')
    buf += BOLD_OFF
    buf += sep

    # 菜品（大字加粗）
    buf += ALIGN_LEFT + BOLD_ON + DOUBLE_HEIGHT
    buf += f"  {dish_name}  x{quantity}\n".encode('gbk', errors='replace')
    buf += NORMAL_SIZE + BOLD_OFF

    # 原因（加粗）
    buf += BOLD_ON
    buf += f"  原因: {reason}\n".encode('gbk', errors='replace')
    buf += BOLD_OFF

    # 桌号
    buf += f"  桌号: {table_number or '-'}".encode('gbk', errors='replace')
    if order_no:
        buf += f"  单号: {order_no[-6:]}\n".encode('gbk', errors='replace')
    else:
        buf += LF

    buf += LF + CUT
    return bytes(buf)


# ─── 打印发送 ───


async def send_to_printer(
    esc_pos_bytes: bytes,
    printer_address: str | None = None,
    printer_id: str | None = None,
) -> bool:
    """通过 Mac mini 的 /api/print 接口发送 ESC/POS 数据到网络打印机。

    Args:
        esc_pos_bytes: ESC/POS 字节流
        printer_address: 打印机网络地址 host:port（优先使用）
        printer_id: 打印机标识名（备选）

    Returns:
        是否发送成功
    """
    log = logger.bind(
        printer_address=printer_address,
        printer_id=printer_id,
        bytes_len=len(esc_pos_bytes),
    )

    payload: dict = {
        "content_base64": base64.b64encode(esc_pos_bytes).decode("ascii"),
    }
    if printer_id:
        payload["printer_id"] = printer_id

    try:
        async with httpx.AsyncClient(timeout=PRINT_TIMEOUT_SEC) as client:
            resp = await client.post(f"{MAC_STATION_URL}/api/print", json=payload)
            result = resp.json()
            if result.get("ok"):
                log.info("kitchen_print.sent")
                return True
            log.warning("kitchen_print.failed", response=result)
            return False
    except httpx.ConnectError:
        log.error("kitchen_print.mac_station_unavailable")
        return False
    except httpx.TimeoutException:
        log.error("kitchen_print.timeout")
        return False


async def print_kitchen_tickets_for_dispatch(
    dept_tasks: list[dict],
    order_no: str,
    table_number: str,
) -> list[dict]:
    """订单分单完成后，为每个档口生成并发送厨打单。

    Args:
        dept_tasks: dispatch_order_to_kds() 的返回结果中的 dept_tasks
        order_no: 订单号
        table_number: 桌号

    Returns:
        [{"dept_name": ..., "printed": bool, "printer_address": ...}]
    """
    log = logger.bind(order_no=order_no, dept_count=len(dept_tasks))
    results = []

    for seq, dept in enumerate(dept_tasks, start=1):
        dept_name = dept.get("dept_name", "默认档口")
        printer_address = dept.get("printer_address")
        printer_id = dept.get("printer_id")
        items = dept.get("items", [])

        if not items:
            continue

        # 生成厨打单
        ticket_bytes = format_kitchen_ticket(
            dept_name=dept_name,
            table_number=table_number,
            order_no=order_no,
            items=items,
            seq=seq,
        )

        # 发送到打印机
        printed = await send_to_printer(
            ticket_bytes,
            printer_address=printer_address,
            printer_id=printer_id,
        )

        results.append({
            "dept_id": dept.get("dept_id"),
            "dept_name": dept_name,
            "printed": printed,
            "printer_address": printer_address,
            "item_count": len(items),
        })

    log.info("kitchen_print.dispatch_done", results=results)
    return results


async def print_rush_ticket(
    dept_name: str,
    table_number: str,
    dish_name: str,
    quantity: int = 1,
    order_no: str = "",
    printer_address: str | None = None,
    printer_id: str | None = None,
) -> bool:
    """发送催菜厨打单到档口打印机。"""
    ticket = format_rush_ticket(
        dept_name=dept_name,
        table_number=table_number,
        dish_name=dish_name,
        quantity=quantity,
        order_no=order_no,
    )
    return await send_to_printer(ticket, printer_address=printer_address, printer_id=printer_id)


async def print_remake_ticket(
    dept_name: str,
    table_number: str,
    dish_name: str,
    reason: str,
    quantity: int = 1,
    order_no: str = "",
    printer_address: str | None = None,
    printer_id: str | None = None,
) -> bool:
    """发送重做厨打单到档口打印机。"""
    ticket = format_remake_ticket(
        dept_name=dept_name,
        table_number=table_number,
        dish_name=dish_name,
        reason=reason,
        quantity=quantity,
        order_no=order_no,
    )
    return await send_to_printer(ticket, printer_address=printer_address, printer_id=printer_id)
