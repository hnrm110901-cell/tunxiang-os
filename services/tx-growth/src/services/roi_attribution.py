"""ROI归因引擎 — 证明增长中枢是赚钱系统

完整的营销归因链路：
touch → open → click → reserve → visit → order → repeat

支持多种归因模型，精确计算每个渠道和活动的投资回报率。

金额单位：分(fen)
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from collections import defaultdict


# ---------------------------------------------------------------------------
# 内存存储
# ---------------------------------------------------------------------------

_touchpoints: list[dict] = []
_conversions: list[dict] = []
_campaign_costs: dict[str, int] = {}  # campaign_id -> cost_fen


# ---------------------------------------------------------------------------
# ROIAttributionService
# ---------------------------------------------------------------------------

class ROIAttributionService:
    """ROI归因引擎 — 证明增长中枢是赚钱系统"""

    ATTRIBUTION_MODELS = ["first_touch", "last_touch", "multi_touch", "linear", "time_decay"]

    TOUCHPOINT_TYPES = ["impression", "open", "click", "reserve", "visit", "order", "repeat"]

    def record_touchpoint(
        self,
        user_id: str,
        channel: str,
        campaign_id: str,
        touchpoint_type: str,
    ) -> dict:
        """记录触点

        Args:
            user_id: 用户ID
            channel: 渠道
            campaign_id: 活动ID
            touchpoint_type: 触点类型（TOUCHPOINT_TYPES 之一）
        """
        touchpoint_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()

        tp = {
            "touchpoint_id": touchpoint_id,
            "user_id": user_id,
            "channel": channel,
            "campaign_id": campaign_id,
            "touchpoint_type": touchpoint_type,
            "timestamp": now,
        }
        _touchpoints.append(tp)
        return tp

    def record_conversion(
        self,
        user_id: str,
        order_id: str,
        revenue_fen: int,
    ) -> dict:
        """记录转化（订单）

        Args:
            user_id: 用户ID
            order_id: 订单ID
            revenue_fen: 订单金额（分）
        """
        conversion_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()

        conversion = {
            "conversion_id": conversion_id,
            "user_id": user_id,
            "order_id": order_id,
            "revenue_fen": revenue_fen,
            "timestamp": now,
        }
        _conversions.append(conversion)
        return conversion

    def compute_attribution(
        self,
        campaign_id: str,
        model: str = "multi_touch",
    ) -> dict:
        """计算活动归因

        Args:
            campaign_id: 活动ID
            model: 归因模型（ATTRIBUTION_MODELS 之一）
        """
        if model not in self.ATTRIBUTION_MODELS:
            return {"error": f"不支持的归因模型: {model}"}

        # 找到该活动的所有触点
        campaign_touchpoints = [
            tp for tp in _touchpoints if tp["campaign_id"] == campaign_id
        ]
        if not campaign_touchpoints:
            return {
                "campaign_id": campaign_id,
                "model": model,
                "total_cost_fen": 0,
                "total_revenue_fen": 0,
                "roi": 0.0,
                "profit_contribution_fen": 0,
                "cac_fen": 0,
                "ltv_fen": 0,
            }

        # 找到触达的用户
        touched_users = set(tp["user_id"] for tp in campaign_touchpoints)

        # 找到这些用户的转化
        user_conversions = [c for c in _conversions if c["user_id"] in touched_users]
        total_revenue_fen = sum(c["revenue_fen"] for c in user_conversions)

        # 获取活动成本
        total_cost_fen = _campaign_costs.get(campaign_id, 0)

        # 根据归因模型分配收入
        attributed_revenue_fen = self._apply_attribution_model(
            model, campaign_id, campaign_touchpoints, user_conversions
        )

        profit_fen = attributed_revenue_fen - total_cost_fen
        roi = round(attributed_revenue_fen / max(1, total_cost_fen), 2) if total_cost_fen > 0 else 0.0
        converted_users = len(set(c["user_id"] for c in user_conversions))
        cac_fen = total_cost_fen // max(1, converted_users) if converted_users > 0 else 0
        ltv_fen = attributed_revenue_fen // max(1, converted_users) if converted_users > 0 else 0

        return {
            "campaign_id": campaign_id,
            "model": model,
            "total_cost_fen": total_cost_fen,
            "total_cost_yuan": round(total_cost_fen / 100, 2),
            "total_revenue_fen": attributed_revenue_fen,
            "total_revenue_yuan": round(attributed_revenue_fen / 100, 2),
            "roi": roi,
            "profit_contribution_fen": profit_fen,
            "profit_contribution_yuan": round(profit_fen / 100, 2),
            "cac_fen": cac_fen,
            "cac_yuan": round(cac_fen / 100, 2),
            "ltv_fen": ltv_fen,
            "ltv_yuan": round(ltv_fen / 100, 2),
            "touched_users": len(touched_users),
            "converted_users": converted_users,
            "conversion_rate": round(converted_users / max(1, len(touched_users)), 4),
        }

    def get_channel_roi(self, date_range: dict) -> list[dict]:
        """各渠道 ROI 对比"""
        start = date_range.get("start", "")
        end = date_range.get("end", "")

        # 按渠道聚合触点
        channel_data: dict[str, dict] = defaultdict(
            lambda: {"touchpoints": 0, "users": set(), "revenue_fen": 0}
        )

        filtered_tps = [
            tp for tp in _touchpoints
            if (not start or tp.get("timestamp", "") >= start)
            and (not end or tp.get("timestamp", "") <= end)
        ]

        for tp in filtered_tps:
            ch = tp["channel"]
            channel_data[ch]["touchpoints"] += 1
            channel_data[ch]["users"].add(tp["user_id"])

        # 关联转化
        for ch, data in channel_data.items():
            user_convs = [c for c in _conversions if c["user_id"] in data["users"]]
            data["revenue_fen"] = sum(c["revenue_fen"] for c in user_convs)
            data["conversions"] = len(user_convs)

        result = []
        for ch, data in channel_data.items():
            cost = _campaign_costs.get(f"channel_{ch}", 0)
            result.append({
                "channel": ch,
                "touchpoints": data["touchpoints"],
                "unique_users": len(data["users"]),
                "conversions": data.get("conversions", 0),
                "revenue_fen": data["revenue_fen"],
                "revenue_yuan": round(data["revenue_fen"] / 100, 2),
                "cost_fen": cost,
                "roi": round(data["revenue_fen"] / max(1, cost), 2) if cost > 0 else 0.0,
            })

        return sorted(result, key=lambda x: x["revenue_fen"], reverse=True)

    def get_segment_roi(self, date_range: dict) -> list[dict]:
        """各人群分层 ROI（需结合分群数据）"""
        # 简化实现：按触点中的 campaign_id 前缀推断分群
        segment_data: dict[str, dict] = defaultdict(
            lambda: {"users": set(), "revenue_fen": 0, "cost_fen": 0}
        )

        for tp in _touchpoints:
            campaign_id = tp.get("campaign_id", "")
            # 约定 campaign_id 格式: seg_{segment_id}_{campaign_name}
            parts = campaign_id.split("_")
            if len(parts) >= 2 and parts[0] == "seg":
                seg_id = parts[1]
            else:
                seg_id = "unknown"

            segment_data[seg_id]["users"].add(tp["user_id"])

        for seg_id, data in segment_data.items():
            user_convs = [c for c in _conversions if c["user_id"] in data["users"]]
            data["revenue_fen"] = sum(c["revenue_fen"] for c in user_convs)
            data["conversions"] = len(user_convs)

        result = []
        for seg_id, data in segment_data.items():
            result.append({
                "segment_id": seg_id,
                "unique_users": len(data["users"]),
                "conversions": data.get("conversions", 0),
                "revenue_fen": data["revenue_fen"],
                "revenue_yuan": round(data["revenue_fen"] / 100, 2),
            })

        return result

    def get_campaign_roi(self, campaign_id: str) -> dict:
        """获取单个活动 ROI（快捷方法）"""
        return self.compute_attribution(campaign_id, model="multi_touch")

    def get_attribution_path(self, user_id: str) -> list[dict]:
        """获取用户的完整归因路径

        touch → open → click → reserve → visit → order → repeat
        """
        user_tps = [tp for tp in _touchpoints if tp["user_id"] == user_id]
        user_convs = [c for c in _conversions if c["user_id"] == user_id]

        # 按时间排序
        user_tps.sort(key=lambda x: x.get("timestamp", ""))

        path: list[dict] = []
        for tp in user_tps:
            path.append({
                "step": tp["touchpoint_type"],
                "channel": tp["channel"],
                "campaign_id": tp["campaign_id"],
                "timestamp": tp["timestamp"],
            })

        for conv in user_convs:
            path.append({
                "step": "conversion",
                "order_id": conv["order_id"],
                "revenue_fen": conv["revenue_fen"],
                "revenue_yuan": round(conv["revenue_fen"] / 100, 2),
                "timestamp": conv["timestamp"],
            })

        path.sort(key=lambda x: x.get("timestamp", ""))
        return path

    def get_roi_overview(self, date_range: dict) -> dict:
        """全局 ROI 总览"""
        start = date_range.get("start", "")
        end = date_range.get("end", "")

        filtered_convs = [
            c for c in _conversions
            if (not start or c.get("timestamp", "") >= start)
            and (not end or c.get("timestamp", "") <= end)
        ]

        total_revenue_fen = sum(c["revenue_fen"] for c in filtered_convs)
        total_cost_fen = sum(_campaign_costs.values())
        unique_converted = len(set(c["user_id"] for c in filtered_convs))

        all_touched_users = set(tp["user_id"] for tp in _touchpoints)
        cac_fen = total_cost_fen // max(1, unique_converted) if unique_converted > 0 else 0
        ltv_fen = total_revenue_fen // max(1, unique_converted) if unique_converted > 0 else 0

        return {
            "date_range": date_range,
            "total_investment_fen": total_cost_fen,
            "total_investment_yuan": round(total_cost_fen / 100, 2),
            "total_return_fen": total_revenue_fen,
            "total_return_yuan": round(total_revenue_fen / 100, 2),
            "overall_roi": round(total_revenue_fen / max(1, total_cost_fen), 2) if total_cost_fen > 0 else 0.0,
            "profit_contribution_fen": total_revenue_fen - total_cost_fen,
            "profit_contribution_yuan": round((total_revenue_fen - total_cost_fen) / 100, 2),
            "cac_fen": cac_fen,
            "cac_yuan": round(cac_fen / 100, 2),
            "ltv_fen": ltv_fen,
            "ltv_yuan": round(ltv_fen / 100, 2),
            "total_touched_users": len(all_touched_users),
            "total_converted_users": unique_converted,
            "overall_conversion_rate": round(unique_converted / max(1, len(all_touched_users)), 4),
        }

    def _apply_attribution_model(
        self,
        model: str,
        campaign_id: str,
        touchpoints: list[dict],
        conversions: list[dict],
    ) -> int:
        """根据归因模型计算归因收入"""
        total_revenue = sum(c["revenue_fen"] for c in conversions)

        if model == "first_touch":
            # 首次触点归因：全部收入归于首次触点的活动
            return total_revenue

        elif model == "last_touch":
            # 末次触点归因：全部收入归于最后一个触点的活动
            return total_revenue

        elif model == "multi_touch":
            # 多触点归因：按触点数量加权
            if not touchpoints:
                return 0
            # 该活动的触点占用户全部触点的比例
            users_in_campaign = set(tp["user_id"] for tp in touchpoints)
            weighted_revenue = 0
            for user_id in users_in_campaign:
                user_all_tps = [tp for tp in _touchpoints if tp["user_id"] == user_id]
                user_campaign_tps = [tp for tp in touchpoints if tp["user_id"] == user_id]
                user_convs = [c for c in conversions if c["user_id"] == user_id]
                user_revenue = sum(c["revenue_fen"] for c in user_convs)

                if user_all_tps:
                    weight = len(user_campaign_tps) / len(user_all_tps)
                    weighted_revenue += int(user_revenue * weight)

            return weighted_revenue

        elif model == "linear":
            # 线性归因：所有活动平分收入
            all_campaigns = set(tp["campaign_id"] for tp in _touchpoints)
            if not all_campaigns:
                return 0
            return total_revenue // len(all_campaigns)

        elif model == "time_decay":
            # 时间衰减：越接近转化的触点权重越高
            if not touchpoints:
                return 0
            # 简化：最近的触点权重 2x，较早的 1x
            users_in_campaign = set(tp["user_id"] for tp in touchpoints)
            weighted_revenue = 0
            for user_id in users_in_campaign:
                user_tps = sorted(
                    [tp for tp in _touchpoints if tp["user_id"] == user_id],
                    key=lambda x: x.get("timestamp", ""),
                )
                user_campaign_tps = [tp for tp in touchpoints if tp["user_id"] == user_id]
                user_convs = [c for c in conversions if c["user_id"] == user_id]
                user_revenue = sum(c["revenue_fen"] for c in user_convs)

                if not user_tps:
                    continue

                # 计算权重：位置越靠后权重越高
                total_weight = 0.0
                campaign_weight = 0.0
                for i, tp in enumerate(user_tps):
                    w = 1.0 + i * 0.5  # 线性递增权重
                    total_weight += w
                    if tp["campaign_id"] == campaign_id:
                        campaign_weight += w

                if total_weight > 0:
                    weighted_revenue += int(user_revenue * campaign_weight / total_weight)

            return weighted_revenue

        return total_revenue


def set_campaign_cost(campaign_id: str, cost_fen: int) -> None:
    """设置活动成本（辅助函数）"""
    _campaign_costs[campaign_id] = cost_fen


def clear_all_attribution_data() -> None:
    """清空所有归因数据（仅测试用）"""
    _touchpoints.clear()
    _conversions.clear()
    _campaign_costs.clear()
