"""条码生成器 — 为订单明细自动生成唯一条码（v342）

格式: {store_code}-{MMDD}-{table_no}-{seq:03d}
示例: SH01-0425-A12-001

用于 KDS 扫码划菜流程：
1. 订单创建时自动为每个 order_item 生成 barcode
2. 厨房出品后扫码确认划菜
3. 条码打印在厨打单/标签上
"""

from datetime import datetime, timezone

import structlog

logger = structlog.get_logger()


def generate_barcode(
    store_code: str,
    table_no: str,
    seq: int,
    order_time: datetime | None = None,
) -> str:
    """生成菜品条码。

    格式: {store_code}-{MMDD}-{table_no}-{seq:03d}

    Args:
        store_code: 门店编号（如 SH01）
        table_no: 桌号（如 A12）
        seq: 当前订单内的菜品序号（从1开始）
        order_time: 下单时间，默认当前时间

    Returns:
        条码字符串，最长30字符
    """
    now = order_time or datetime.now(timezone.utc)
    mmdd = now.strftime("%m%d")

    # 清理桌号中的特殊字符，确保条码可读
    safe_table = (table_no or "T0").replace("-", "").replace(" ", "")[:6]
    safe_store = (store_code or "S0")[:6]

    barcode = f"{safe_store}-{mmdd}-{safe_table}-{seq:03d}"

    # 确保不超过30字符
    if len(barcode) > 30:
        barcode = barcode[:30]

    return barcode


def generate_barcodes_for_order(
    store_code: str,
    table_no: str,
    item_count: int,
    order_time: datetime | None = None,
) -> list[str]:
    """为整个订单批量生成条码。

    Args:
        store_code: 门店编号
        table_no: 桌号
        item_count: 菜品数量
        order_time: 下单时间

    Returns:
        条码列表，按序号排列
    """
    return [generate_barcode(store_code, table_no, seq=i + 1, order_time=order_time) for i in range(item_count)]
