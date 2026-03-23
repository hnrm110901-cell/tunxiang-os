"""
品智订单同步模块
拉取品智订单数据并映射为屯象 Ontology Order 格式
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger()


class PinzhiOrderSync:
    """品智订单同步器"""

    def __init__(self, adapter):
        """
        Args:
            adapter: PinzhiAdapter 实例（提供 _request / _add_sign 等能力）
        """
        self.adapter = adapter

    async def fetch_orders(
        self,
        store_id: str,
        start_date: str,
        end_date: str,
        page: int = 1,
    ) -> list[dict]:
        """
        从品智拉取指定门店和日期范围的订单。

        品智 orderNew.do 仅支持单日查询（businessDate），
        此处自动按天遍历 [start_date, end_date] 区间。

        Args:
            store_id: 门店 ognid
            start_date: 开始日期 yyyy-MM-dd
            end_date: 结束日期 yyyy-MM-dd
            page: 页码（针对每一天的分页）

        Returns:
            品智原始订单列表
        """
        all_orders: list[dict] = []
        current = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        while current <= end:
            biz_date = current.strftime("%Y-%m-%d")
            page_idx = page
            while True:
                orders = await self.adapter.query_orders(
                    ognid=store_id,
                    business_date=biz_date,
                    page_index=page_idx,
                )
                if not orders:
                    break
                all_orders.extend(orders)
                if len(orders) < 20:
                    break
                page_idx += 1
            current = current.replace(day=current.day + 1) if current < end else end
            if current == end and biz_date == end_date:
                break
            # 安全递增日期
            from datetime import timedelta
            current = datetime.strptime(biz_date, "%Y-%m-%d") + timedelta(days=1)

        logger.info(
            "pinzhi_orders_fetched",
            store_id=store_id,
            start_date=start_date,
            end_date=end_date,
            count=len(all_orders),
        )
        return all_orders

    @staticmethod
    def map_to_tunxiang_order(pinzhi_order: dict) -> dict:
        """
        将品智原始订单映射为屯象 Ontology Order 格式（纯函数）。

        金额单位统一为分(fen)。

        Args:
            pinzhi_order: 品智原始订单字典

        Returns:
            屯象标准订单字典
        """
        # 品智 billStatus: 0=未结账, 1=已结账, 2=已退单
        status_map = {0: "pending", 1: "completed", 2: "cancelled"}
        bill_status = pinzhi_order.get("billStatus", 0)

        # 品智 orderSource: 1=堂食, 2=外卖, 3=自提
        source_map = {1: "dine_in", 2: "delivery", 3: "takeaway"}
        order_source = pinzhi_order.get("orderSource", 1)

        # 解析订单项（品智金额单位已为分）
        items = []
        for idx, dish in enumerate(pinzhi_order.get("dishList", []), start=1):
            unit_price_fen = int(dish.get("dishPrice", dish.get("price", 0)))
            qty = int(dish.get("dishNum", dish.get("quantity", 1)))
            items.append({
                "item_id": str(dish.get("dishId", f"{pinzhi_order.get('billId', '')}_{idx}")),
                "dish_id": str(dish.get("dishId", "")),
                "dish_name": str(dish.get("dishName", "")),
                "quantity": qty,
                "unit_price_fen": unit_price_fen,
                "subtotal_fen": unit_price_fen * qty,
            })

        # 支付信息
        payments = []
        for pay in pinzhi_order.get("paymentList", []):
            payments.append({
                "pay_type": str(pay.get("payType", "")),
                "pay_name": str(pay.get("payName", "")),
                "amount_fen": int(pay.get("payMoney", 0)),
            })

        return {
            "order_id": str(pinzhi_order.get("billId", "")),
            "order_number": str(pinzhi_order.get("billNo", "")),
            "order_type": source_map.get(order_source, "dine_in"),
            "order_status": status_map.get(bill_status, "pending"),
            "table_number": pinzhi_order.get("tableNo"),
            "customer_id": pinzhi_order.get("vipCard"),
            "head_count": pinzhi_order.get("personNum"),
            "items": items,
            "subtotal_fen": int(pinzhi_order.get("dishPriceTotal", 0)),
            "discount_fen": int(pinzhi_order.get("specialOfferPrice", 0)),
            "service_charge_fen": int(pinzhi_order.get("teaPrice", 0)),
            "total_fen": int(pinzhi_order.get("realPrice", 0)),
            "payments": payments,
            "waiter_id": pinzhi_order.get("openOrderUser"),
            "cashier_id": pinzhi_order.get("cashiers"),
            "created_at": pinzhi_order.get("openTime"),
            "completed_at": pinzhi_order.get("payTime"),
            "remark": pinzhi_order.get("remark"),
            "source_system": "pinzhi",
        }

    async def sync_orders(self, store_id: str, date: str) -> dict:
        """
        完整同步流程：拉取 + 映射 + 返回统计。

        Args:
            store_id: 门店 ognid
            date: 同步日期 yyyy-MM-dd

        Returns:
            同步统计 {"total": int, "success": int, "failed": int, "orders": list}
        """
        raw_orders = await self.fetch_orders(store_id, date, date)

        mapped: list[dict] = []
        failed = 0
        for raw in raw_orders:
            try:
                mapped.append(self.map_to_tunxiang_order(raw))
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "order_mapping_failed",
                    bill_id=raw.get("billId"),
                    error=str(exc),
                )
                failed += 1

        logger.info(
            "pinzhi_orders_synced",
            store_id=store_id,
            date=date,
            total=len(raw_orders),
            success=len(mapped),
            failed=failed,
        )

        return {
            "total": len(raw_orders),
            "success": len(mapped),
            "failed": failed,
            "orders": mapped,
        }
