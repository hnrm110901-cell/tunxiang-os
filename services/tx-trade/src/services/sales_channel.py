"""多收入渠道统一引擎 — 2030演进基础

8种渠道独立毛利核算。
金额统一存分（fen），展示时 /100 转元。
"""

import asyncio
import math
from datetime import date

import structlog

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import ChannelEventType

logger = structlog.get_logger()


class SalesChannelEngine:
    """多收入渠道统一引擎 — 8种渠道独立毛利核算"""

    CHANNELS = {
        "dine_in": {
            "name": "堂食",
            "fee_rate": 0.0,
            "commission_rate": 0.0,
        },
        "takeaway": {
            "name": "外带",
            "fee_rate": 0.0,
            "commission_rate": 0.0,
        },
        "delivery_meituan": {
            "name": "美团外卖",
            "fee_rate": 0.0,
            "commission_rate": 0.18,
        },
        "delivery_eleme": {
            "name": "饿了么",
            "fee_rate": 0.0,
            "commission_rate": 0.20,
        },
        "delivery_douyin": {
            "name": "抖音外卖",
            "fee_rate": 0.0,
            "commission_rate": 0.10,
        },
        "group_buy": {
            "name": "团购",
            "fee_rate": 0.0,
            "commission_rate": 0.12,
        },
        "banquet": {
            "name": "宴会",
            "fee_rate": 0.0,
            "commission_rate": 0.0,
        },
        "catering": {
            "name": "外烩",
            "fee_rate": 0.0,
            "commission_rate": 0.0,
        },
    }

    # 支付渠道手续费率
    PAYMENT_FEE_RATES = {
        "wechat": 0.006,  # 微信支付 0.6%
        "alipay": 0.006,  # 支付宝 0.6%
        "unionpay": 0.006,  # 银联 0.6%
        "cash": 0.0,  # 现金无手续费
        "member_balance": 0.0,  # 会员余额无手续费
        "credit": 0.0,  # 挂账无手续费
    }

    def calculate_channel_profit(
        self,
        order: dict,
        channel: str,
        payment_method: str = "wechat",
    ) -> dict:
        """计算单笔订单渠道利润

        公式: gross_revenue - platform_commission - payment_fee - food_cost = net_profit

        Args:
            order: {order_id, total_amount_fen, discount_amount_fen, final_amount_fen,
                    food_cost_fen, items: [{cost_fen}]}
            channel: 渠道代码
            payment_method: 支付方式

        Returns:
            {gross_revenue_fen, platform_commission_fen, payment_fee_fen,
             food_cost_fen, net_profit_fen, net_margin_rate}
        """
        if channel not in self.CHANNELS:
            raise ValueError(f"未知渠道: {channel}")

        ch_config = self.CHANNELS[channel]
        gross_revenue_fen = order.get("final_amount_fen") or order.get("total_amount_fen", 0)

        # 平台佣金
        commission_rate = ch_config["commission_rate"]
        platform_commission_fen = math.ceil(gross_revenue_fen * commission_rate)

        # 支付手续费
        fee_rate = self.PAYMENT_FEE_RATES.get(payment_method, 0.006)
        payment_fee_fen = math.ceil(gross_revenue_fen * fee_rate)

        # 食材成本
        food_cost_fen = order.get("food_cost_fen", 0)
        if not food_cost_fen and order.get("items"):
            food_cost_fen = sum(item.get("cost_fen", 0) or 0 for item in order["items"])

        # 净利润
        net_profit_fen = gross_revenue_fen - platform_commission_fen - payment_fee_fen - food_cost_fen
        net_margin_rate = net_profit_fen / gross_revenue_fen if gross_revenue_fen > 0 else 0.0

        result = {
            "order_id": order.get("order_id"),
            "channel": channel,
            "channel_name": ch_config["name"],
            "gross_revenue_fen": gross_revenue_fen,
            "platform_commission_fen": platform_commission_fen,
            "commission_rate": commission_rate,
            "payment_fee_fen": payment_fee_fen,
            "payment_fee_rate": fee_rate,
            "food_cost_fen": food_cost_fen,
            "net_profit_fen": net_profit_fen,
            "net_margin_rate": round(net_margin_rate, 4),
        }

        logger.info(
            "channel_profit_calculated",
            order_id=order.get("order_id"),
            channel=channel,
            net_profit_fen=net_profit_fen,
            net_margin_rate=round(net_margin_rate, 4),
        )

        # 发射 CHANNEL.COMMISSION_CALC 事件（供 ChannelMarginProjector 更新 mv_channel_margin）
        tenant_id = order.get("tenant_id", "")
        store_id = order.get("store_id", "")
        if tenant_id and store_id:
            asyncio.create_task(
                emit_event(
                    event_type=ChannelEventType.COMMISSION_CALC,
                    tenant_id=tenant_id,
                    stream_id=str(order.get("order_id", "")),
                    payload={
                        "channel": channel,
                        "gross_revenue_fen": gross_revenue_fen,
                        "commission_fen": platform_commission_fen,  # ChannelMarginProjector 读取此字段
                        "platform_commission_fen": platform_commission_fen,  # 保留原名便于审计
                        "commission_rate": commission_rate,
                        "payment_fee_fen": payment_fee_fen,
                        "food_cost_fen": food_cost_fen,
                        "net_profit_fen": net_profit_fen,
                        "net_margin_rate": round(net_margin_rate, 4),
                    },
                    store_id=store_id,
                    source_service="tx-trade",
                    metadata={"channel": channel},
                )
            )

        return result

    def get_channel_summary(
        self,
        orders: list[dict],
        store_id: str,
        biz_date: date,
    ) -> dict:
        """渠道维度日汇总

        Args:
            orders: [{order_id, sales_channel, total_amount_fen, final_amount_fen,
                      food_cost_fen, guest_count, payment_method, items}]
            store_id: 门店ID
            biz_date: 营业日期

        Returns:
            {store_id, biz_date, channels: {channel: {orders, revenue_fen, avg_check_fen,
             cost_fen, commission_fen, net_profit_fen, margin_rate, guests}}, totals}
        """
        channels: dict[str, dict] = {}

        for order in orders:
            channel = order.get("sales_channel", "dine_in")
            if channel not in channels:
                channels[channel] = {
                    "channel": channel,
                    "channel_name": self.CHANNELS.get(channel, {}).get("name", channel),
                    "order_count": 0,
                    "revenue_fen": 0,
                    "cost_fen": 0,
                    "commission_fen": 0,
                    "payment_fee_fen": 0,
                    "net_profit_fen": 0,
                    "guest_count": 0,
                }

            ch = channels[channel]
            profit = self.calculate_channel_profit(
                order,
                channel,
                order.get("payment_method", "wechat"),
            )

            ch["order_count"] += 1
            ch["revenue_fen"] += profit["gross_revenue_fen"]
            ch["cost_fen"] += profit["food_cost_fen"]
            ch["commission_fen"] += profit["platform_commission_fen"]
            ch["payment_fee_fen"] += profit["payment_fee_fen"]
            ch["net_profit_fen"] += profit["net_profit_fen"]
            ch["guest_count"] += order.get("guest_count", 1)

        # 计算客单价和毛利率
        for ch in channels.values():
            ch["avg_check_fen"] = ch["revenue_fen"] // ch["order_count"] if ch["order_count"] > 0 else 0
            ch["margin_rate"] = round(
                ch["net_profit_fen"] / ch["revenue_fen"] if ch["revenue_fen"] > 0 else 0.0,
                4,
            )

        # 汇总
        total_revenue = sum(ch["revenue_fen"] for ch in channels.values())
        total_profit = sum(ch["net_profit_fen"] for ch in channels.values())
        total_orders = sum(ch["order_count"] for ch in channels.values())
        total_guests = sum(ch["guest_count"] for ch in channels.values())

        return {
            "store_id": store_id,
            "biz_date": biz_date.isoformat(),
            "channels": channels,
            "totals": {
                "total_revenue_fen": total_revenue,
                "total_profit_fen": total_profit,
                "total_orders": total_orders,
                "total_guests": total_guests,
                "avg_check_fen": total_revenue // total_orders if total_orders > 0 else 0,
                "overall_margin_rate": round(total_profit / total_revenue if total_revenue > 0 else 0.0, 4),
            },
        }

    def get_channel_trend(
        self,
        daily_summaries: list[dict],
        store_id: str,
        days: int = 30,
    ) -> list[dict]:
        """渠道趋势分析

        Args:
            daily_summaries: [{biz_date, channels: {...}}] 按日期排序
            store_id: 门店ID
            days: 天数

        Returns:
            [{date, channel_data: {channel: {revenue_fen, orders, margin_rate}}}]
        """
        trend: list[dict] = []

        for summary in daily_summaries[-days:]:
            day_data = {
                "date": summary.get("biz_date"),
                "channel_data": {},
            }

            channels = summary.get("channels", {})
            for channel, ch_data in channels.items():
                day_data["channel_data"][channel] = {
                    "revenue_fen": ch_data.get("revenue_fen", 0),
                    "order_count": ch_data.get("order_count", 0),
                    "margin_rate": ch_data.get("margin_rate", 0),
                    "avg_check_fen": ch_data.get("avg_check_fen", 0),
                }

            trend.append(day_data)

        return trend

    def compare_channel_margins(
        self,
        orders_by_channel: dict[str, list[dict]],
    ) -> list[dict]:
        """跨渠道毛利对比

        Args:
            orders_by_channel: {channel: [orders]}

        Returns:
            [{channel, channel_name, avg_margin_rate, total_revenue_fen,
              total_profit_fen, order_count, commission_impact_fen}]
        """
        comparisons: list[dict] = []

        for channel, orders in orders_by_channel.items():
            if not orders:
                continue

            total_revenue = 0
            total_profit = 0
            total_commission = 0

            for order in orders:
                profit = self.calculate_channel_profit(
                    order,
                    channel,
                    order.get("payment_method", "wechat"),
                )
                total_revenue += profit["gross_revenue_fen"]
                total_profit += profit["net_profit_fen"]
                total_commission += profit["platform_commission_fen"]

            comparisons.append(
                {
                    "channel": channel,
                    "channel_name": self.CHANNELS.get(channel, {}).get("name", channel),
                    "order_count": len(orders),
                    "total_revenue_fen": total_revenue,
                    "total_profit_fen": total_profit,
                    "avg_margin_rate": round(total_profit / total_revenue if total_revenue > 0 else 0.0, 4),
                    "commission_impact_fen": total_commission,
                }
            )

        # 按毛利率降序排列
        comparisons.sort(key=lambda x: x["avg_margin_rate"], reverse=True)
        return comparisons
