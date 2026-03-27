"""折扣引擎 — 三条硬约束之毛利底线守护

所有折扣必须通过毛利底线校验。
金额统一存分（fen），展示时 /100 转元。
"""
import math
import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


class DiscountEngine:
    """折扣引擎 — 三条硬约束之毛利底线守护

    所有折扣必须通过毛利底线校验。
    """

    DISCOUNT_TYPES = {
        "percent_off": "整单折扣",      # e.g., 8.8折
        "amount_off": "整单减免",        # e.g., 满200减30
        "item_percent": "单品折扣",      # e.g., 指定菜品7折
        "item_free": "赠送/免单",        # e.g., 赠送甜品
        "member_price": "会员价",        # e.g., 会员专享价
        "coupon": "优惠券核销",          # e.g., 满100减15券
        "manual": "手动改价",            # 需要审批
    }

    # 审批阈值
    APPROVAL_PERCENT_THRESHOLD = 0.30   # 折扣率 > 30% 需审批
    APPROVAL_AMOUNT_THRESHOLD = 10000   # 减免 > ¥100 (10000分) 需审批

    def calculate_discount(
        self,
        order_items: list[dict],
        discount_type: str,
        discount_value: float,
        target_item_id: Optional[str] = None,
    ) -> dict:
        """计算折扣金额

        Args:
            order_items: [{item_id, item_name, quantity, unit_price_fen, subtotal_fen, cost_fen}]
            discount_type: DISCOUNT_TYPES 之一
            discount_value: 折扣值（折扣率为0-1小数，金额为分）
            target_item_id: 单品折扣时的目标菜品ID

        Returns:
            {discount_fen, items_after_discount, new_total_fen}
        """
        if discount_type not in self.DISCOUNT_TYPES:
            raise ValueError(f"未知折扣类型: {discount_type}")

        original_total_fen = sum(item["subtotal_fen"] for item in order_items)
        items_after = [dict(item) for item in order_items]  # deep copy
        discount_fen = 0

        if discount_type == "percent_off":
            # discount_value 是折扣，如 0.88 表示8.8折，实际打折率 = 1 - 0.88 = 0.12
            discount_rate = 1.0 - discount_value
            discount_fen = math.ceil(original_total_fen * discount_rate)
            for item in items_after:
                item["discount_fen"] = math.ceil(item["subtotal_fen"] * discount_rate)
                item["final_fen"] = item["subtotal_fen"] - item["discount_fen"]

        elif discount_type == "amount_off":
            # discount_value 是减免金额(分)
            discount_fen = int(discount_value)
            if discount_fen > original_total_fen:
                raise ValueError(
                    f"减免金额({discount_fen}分)超过订单总额({original_total_fen}分)"
                )
            # 按比例分摊到各菜品
            for item in items_after:
                ratio = item["subtotal_fen"] / original_total_fen if original_total_fen > 0 else 0
                item["discount_fen"] = math.floor(discount_fen * ratio)
                item["final_fen"] = item["subtotal_fen"] - item["discount_fen"]
            # 尾差修正：分摊后的折扣总和可能不等于discount_fen
            allocated = sum(item["discount_fen"] for item in items_after)
            if allocated != discount_fen and items_after:
                items_after[0]["discount_fen"] += (discount_fen - allocated)
                items_after[0]["final_fen"] = items_after[0]["subtotal_fen"] - items_after[0]["discount_fen"]

        elif discount_type == "item_percent":
            # 单品折扣: discount_value 是折扣，如 0.7 表示7折
            if not target_item_id:
                raise ValueError("单品折扣必须指定 target_item_id")
            discount_rate = 1.0 - discount_value
            for item in items_after:
                if item.get("item_id") == target_item_id:
                    item["discount_fen"] = math.ceil(item["subtotal_fen"] * discount_rate)
                    item["final_fen"] = item["subtotal_fen"] - item["discount_fen"]
                    discount_fen += item["discount_fen"]
                else:
                    item["discount_fen"] = 0
                    item["final_fen"] = item["subtotal_fen"]

        elif discount_type == "item_free":
            # 赠送/免单: discount_value 不使用，target_item_id 为赠送菜品
            if not target_item_id:
                raise ValueError("赠送必须指定 target_item_id")
            for item in items_after:
                if item.get("item_id") == target_item_id:
                    item["discount_fen"] = item["subtotal_fen"]
                    item["final_fen"] = 0
                    item["gift_flag"] = True
                    discount_fen += item["subtotal_fen"]
                else:
                    item["discount_fen"] = 0
                    item["final_fen"] = item["subtotal_fen"]

        elif discount_type == "member_price":
            # 会员价: discount_value 是折扣率，如 0.88 表示8.8折
            discount_rate = 1.0 - discount_value
            discount_fen = math.ceil(original_total_fen * discount_rate)
            for item in items_after:
                item["discount_fen"] = math.ceil(item["subtotal_fen"] * discount_rate)
                item["final_fen"] = item["subtotal_fen"] - item["discount_fen"]

        elif discount_type == "coupon":
            # 优惠券核销: discount_value 是优惠券面额(分)
            discount_fen = int(discount_value)
            if discount_fen > original_total_fen:
                discount_fen = original_total_fen
            for item in items_after:
                ratio = item["subtotal_fen"] / original_total_fen if original_total_fen > 0 else 0
                item["discount_fen"] = math.floor(discount_fen * ratio)
                item["final_fen"] = item["subtotal_fen"] - item["discount_fen"]
            allocated = sum(item["discount_fen"] for item in items_after)
            if allocated != discount_fen and items_after:
                items_after[0]["discount_fen"] += (discount_fen - allocated)
                items_after[0]["final_fen"] = items_after[0]["subtotal_fen"] - items_after[0]["discount_fen"]

        elif discount_type == "manual":
            # 手动改价: discount_value 是减免金额(分)
            discount_fen = int(discount_value)
            if discount_fen > original_total_fen:
                raise ValueError(
                    f"手动减免({discount_fen}分)超过订单总额({original_total_fen}分)"
                )
            for item in items_after:
                ratio = item["subtotal_fen"] / original_total_fen if original_total_fen > 0 else 0
                item["discount_fen"] = math.floor(discount_fen * ratio)
                item["final_fen"] = item["subtotal_fen"] - item["discount_fen"]
            allocated = sum(item["discount_fen"] for item in items_after)
            if allocated != discount_fen and items_after:
                items_after[0]["discount_fen"] += (discount_fen - allocated)
                items_after[0]["final_fen"] = items_after[0]["subtotal_fen"] - items_after[0]["discount_fen"]

        new_total_fen = original_total_fen - discount_fen

        logger.info(
            "discount_calculated",
            type=discount_type,
            original_fen=original_total_fen,
            discount_fen=discount_fen,
            new_total_fen=new_total_fen,
        )

        return {
            "discount_fen": discount_fen,
            "items_after_discount": items_after,
            "new_total_fen": new_total_fen,
            "original_total_fen": original_total_fen,
            "discount_type": discount_type,
            "discount_type_label": self.DISCOUNT_TYPES[discount_type],
        }

    def check_margin_floor(
        self,
        order_items: list[dict],
        discount_fen: int,
        margin_floor_rate: float = 0.30,
    ) -> dict:
        """毛利底线校验 — 硬约束#1，无例外

        margin = (revenue - cost) / revenue
        If margin < floor: 拒绝折扣

        Args:
            order_items: [{subtotal_fen, cost_fen, ...}]
            discount_fen: 折扣金额(分)
            margin_floor_rate: 毛利底线(默认30%)

        Returns:
            {passed, current_margin, floor_margin, gap_fen, message}
        """
        total_revenue_fen = sum(item["subtotal_fen"] for item in order_items)
        total_cost_fen = sum(item.get("cost_fen", 0) or 0 for item in order_items)

        revenue_after_discount = total_revenue_fen - discount_fen

        if revenue_after_discount <= 0:
            return {
                "passed": False,
                "current_margin": -1.0,
                "floor_margin": margin_floor_rate,
                "gap_fen": total_cost_fen,
                "message": "折扣后营收为零或负数，毛利底线校验失败",
            }

        current_margin = (revenue_after_discount - total_cost_fen) / revenue_after_discount

        if current_margin < margin_floor_rate:
            # 计算最大可折扣金额
            # (revenue - discount_max - cost) / (revenue - discount_max) >= floor
            # revenue - discount_max - cost >= floor * (revenue - discount_max)
            # revenue - discount_max - cost >= floor*revenue - floor*discount_max
            # (1 - floor)*discount_max <= revenue - cost - floor*revenue
            # discount_max <= (revenue*(1-floor) - cost) / (1-floor)
            # discount_max <= revenue - cost / (1-floor)
            if margin_floor_rate < 1.0:
                max_discount_fen = max(
                    0,
                    math.floor(total_revenue_fen - total_cost_fen / (1.0 - margin_floor_rate)),
                )
            else:
                max_discount_fen = 0

            gap_fen = discount_fen - max_discount_fen

            logger.warning(
                "margin_floor_violated",
                current_margin=round(current_margin, 4),
                floor=margin_floor_rate,
                discount_fen=discount_fen,
                max_discount_fen=max_discount_fen,
            )

            return {
                "passed": False,
                "current_margin": round(current_margin, 4),
                "floor_margin": margin_floor_rate,
                "gap_fen": gap_fen,
                "max_discount_fen": max_discount_fen,
                "message": (
                    f"毛利底线校验失败: 当前毛利{current_margin:.1%} < 底线{margin_floor_rate:.1%}，"
                    f"最大可折扣{max_discount_fen / 100:.2f}元"
                ),
            }

        return {
            "passed": True,
            "current_margin": round(current_margin, 4),
            "floor_margin": margin_floor_rate,
            "gap_fen": 0,
            "message": f"毛利底线校验通过: 当前毛利{current_margin:.1%} >= 底线{margin_floor_rate:.1%}",
        }

    def validate_discount_approval(
        self,
        discount_type: str,
        discount_fen: int,
        order_total_fen: int,
        approval_id: Optional[str] = None,
    ) -> dict:
        """折扣审批校验

        Rules:
        - percent_off > 30%: needs manager approval
        - amount_off > 100元: needs manager approval
        - item_free: always needs approval
        - manual: always needs approval

        Returns:
            {needs_approval, approval_required_role, reason}
        """
        needs_approval = False
        approval_required_role = None
        reason = ""

        discount_rate = discount_fen / order_total_fen if order_total_fen > 0 else 1.0

        if discount_type in ("item_free", "manual"):
            needs_approval = True
            approval_required_role = "manager"
            reason = f"{'赠送/免单' if discount_type == 'item_free' else '手动改价'}必须经理审批"

        elif discount_type in ("percent_off", "member_price"):
            if discount_rate > self.APPROVAL_PERCENT_THRESHOLD:
                needs_approval = True
                approval_required_role = "manager"
                reason = f"折扣率{discount_rate:.1%}超过{self.APPROVAL_PERCENT_THRESHOLD:.0%}阈值，需经理审批"

        elif discount_type in ("amount_off", "coupon"):
            if discount_fen > self.APPROVAL_AMOUNT_THRESHOLD:
                needs_approval = True
                approval_required_role = "manager"
                reason = f"减免{discount_fen / 100:.2f}元超过{self.APPROVAL_AMOUNT_THRESHOLD / 100:.0f}元阈值，需经理审批"

        elif discount_type == "item_percent":
            if discount_rate > self.APPROVAL_PERCENT_THRESHOLD:
                needs_approval = True
                approval_required_role = "manager"
                reason = f"单品折扣率{discount_rate:.1%}超过阈值，需经理审批"

        # 如果需要审批但已有审批ID，视为已审批通过
        if needs_approval and approval_id:
            logger.info(
                "discount_approval_granted",
                approval_id=approval_id,
                discount_type=discount_type,
            )
            return {
                "needs_approval": False,
                "approval_required_role": None,
                "reason": f"已获审批: {approval_id}",
                "approval_id": approval_id,
            }

        return {
            "needs_approval": needs_approval,
            "approval_required_role": approval_required_role,
            "reason": reason,
        }

    def get_discount_summary(
        self,
        orders: list[dict],
        store_id: str,
        biz_date: date,
    ) -> dict:
        """折扣汇总统计

        Args:
            orders: [{order_id, order_no, waiter_id, total_amount_fen, discount_amount_fen,
                      discount_type, final_amount_fen}]
            store_id: 门店ID
            biz_date: 营业日期

        Returns:
            {store_id, biz_date, total_discount_fen, total_revenue_fen,
             discount_rate, by_type, by_waiter, anomaly_flags}
        """
        total_discount_fen = 0
        total_revenue_fen = 0
        by_type: dict[str, dict] = {}
        by_waiter: dict[str, dict] = {}

        for order in orders:
            discount = order.get("discount_amount_fen", 0)
            revenue = order.get("total_amount_fen", 0)
            total_discount_fen += discount
            total_revenue_fen += revenue

            # 按折扣类型
            dtype = order.get("discount_type", "unknown")
            if dtype not in by_type:
                by_type[dtype] = {"count": 0, "total_fen": 0}
            by_type[dtype]["count"] += 1
            by_type[dtype]["total_fen"] += discount

            # 按服务员
            waiter = order.get("waiter_id", "unknown")
            if waiter not in by_waiter:
                by_waiter[waiter] = {"count": 0, "total_discount_fen": 0, "total_revenue_fen": 0}
            if discount > 0:
                by_waiter[waiter]["count"] += 1
            by_waiter[waiter]["total_discount_fen"] += discount
            by_waiter[waiter]["total_revenue_fen"] += revenue

        discount_rate = total_discount_fen / total_revenue_fen if total_revenue_fen > 0 else 0

        anomalies = self.detect_discount_anomaly(orders, store_id, biz_date)

        return {
            "store_id": store_id,
            "biz_date": biz_date.isoformat(),
            "total_discount_fen": total_discount_fen,
            "total_revenue_fen": total_revenue_fen,
            "discount_rate": round(discount_rate, 4),
            "by_type": by_type,
            "by_waiter": by_waiter,
            "anomaly_flags": anomalies,
            "order_count": len(orders),
        }

    def detect_discount_anomaly(
        self,
        orders: list[dict],
        store_id: str,
        biz_date: date,
    ) -> list[dict]:
        """折扣异常检测

        规则:
        - 同一服务员单日折扣 > 5次 → 异常
        - 单笔折扣率 > 30% → 异常
        - 门店当日折扣总额 > 营收10% → 异常

        Returns:
            [{anomaly_type, severity, detail, waiter_id, order_id}]
        """
        anomalies: list[dict] = []

        # 按服务员统计折扣次数
        waiter_discount_counts: dict[str, list[dict]] = {}
        total_discount_fen = 0
        total_revenue_fen = 0

        for order in orders:
            discount = order.get("discount_amount_fen", 0)
            revenue = order.get("total_amount_fen", 0)
            total_discount_fen += discount
            total_revenue_fen += revenue
            waiter_id = order.get("waiter_id", "unknown")

            if discount > 0:
                if waiter_id not in waiter_discount_counts:
                    waiter_discount_counts[waiter_id] = []
                waiter_discount_counts[waiter_id].append(order)

                # 检查单笔折扣率 > 30%
                if revenue > 0 and discount / revenue > 0.30:
                    anomalies.append({
                        "anomaly_type": "high_single_discount",
                        "severity": "warning",
                        "detail": (
                            f"单笔折扣率{discount / revenue:.1%}超过30%阈值，"
                            f"订单金额{revenue / 100:.2f}元，折扣{discount / 100:.2f}元"
                        ),
                        "waiter_id": waiter_id,
                        "order_id": order.get("order_id"),
                        "order_no": order.get("order_no"),
                        "discount_rate": round(discount / revenue, 4),
                    })

        # 检查同一服务员折扣次数 > 5
        for waiter_id, discount_orders in waiter_discount_counts.items():
            if len(discount_orders) > 5:
                anomalies.append({
                    "anomaly_type": "frequent_waiter_discount",
                    "severity": "critical",
                    "detail": (
                        f"服务员{waiter_id}当日折扣{len(discount_orders)}次，超过5次阈值"
                    ),
                    "waiter_id": waiter_id,
                    "order_id": None,
                    "discount_count": len(discount_orders),
                    "total_discount_fen": sum(
                        o.get("discount_amount_fen", 0) for o in discount_orders
                    ),
                })

        # 检查门店当日折扣总额 > 营收10%
        if total_revenue_fen > 0 and total_discount_fen / total_revenue_fen > 0.10:
            anomalies.append({
                "anomaly_type": "high_store_discount_rate",
                "severity": "critical",
                "detail": (
                    f"门店当日折扣率{total_discount_fen / total_revenue_fen:.1%}超过10%阈值，"
                    f"总营收{total_revenue_fen / 100:.2f}元，总折扣{total_discount_fen / 100:.2f}元"
                ),
                "waiter_id": None,
                "order_id": None,
                "store_discount_rate": round(total_discount_fen / total_revenue_fen, 4),
            })

        if anomalies:
            logger.warning(
                "discount_anomalies_detected",
                store_id=store_id,
                biz_date=biz_date.isoformat(),
                anomaly_count=len(anomalies),
            )

        return anomalies

    def apply_stacked_discounts(
        self,
        order_items: list[dict],
        discounts: list[dict],
        margin_floor_rate: float = 0.30,
    ) -> dict:
        """叠加折扣计算 — 会员价 + 优惠券等组合

        Args:
            order_items: [{item_id, item_name, quantity, unit_price_fen, subtotal_fen, cost_fen}]
            discounts: [{discount_type, discount_value, target_item_id}] 按优先级排序
            margin_floor_rate: 毛利底线

        Returns:
            {total_discount_fen, items_after_discount, new_total_fen,
             applied_discounts, margin_check}
        """
        current_items = [dict(item) for item in order_items]
        applied_discounts: list[dict] = []
        total_discount_fen = 0

        for disc in discounts:
            # 用当前已折扣后的价格作为新的基础
            for item in current_items:
                item["subtotal_fen"] = item.get("final_fen", item["subtotal_fen"])

            result = self.calculate_discount(
                current_items,
                disc["discount_type"],
                disc["discount_value"],
                disc.get("target_item_id"),
            )

            total_discount_fen += result["discount_fen"]
            current_items = result["items_after_discount"]

            applied_discounts.append({
                "discount_type": disc["discount_type"],
                "discount_type_label": self.DISCOUNT_TYPES.get(disc["discount_type"], ""),
                "discount_fen": result["discount_fen"],
            })

        # 毛利底线校验（基于原始成本和最终价格）
        margin_check = self.check_margin_floor(order_items, total_discount_fen, margin_floor_rate)

        new_total_fen = sum(item["subtotal_fen"] for item in order_items) - total_discount_fen

        return {
            "total_discount_fen": total_discount_fen,
            "items_after_discount": current_items,
            "new_total_fen": new_total_fen,
            "applied_discounts": applied_discounts,
            "margin_check": margin_check,
        }
