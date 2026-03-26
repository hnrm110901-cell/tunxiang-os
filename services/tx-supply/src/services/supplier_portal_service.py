"""供应链深度管理 — 从进销存到供应链协同网络 (U2.4)

核心能力：
- 供应商管理（注册/评分/排名）
- 自动比价（RFQ → 报价对比 → 推荐）
- 合同管理（创建/到期预警/合规评估）
- 价格情报（趋势/异常/预测）
- 供应商评分（五维度加权）
- 供应链风险评估与缓解建议

金额单位统一为"分"（fen），与 V2.x 保持一致。
"""

from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  数据模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SUPPLIER_CATEGORIES = {"seafood", "meat", "vegetable", "seasoning", "frozen", "dry_goods", "beverage", "other"}
SUPPLIER_STATUSES = {"active", "inactive", "suspended", "blacklisted"}
RECOMMENDATION_LEVELS = {"preferred", "approved", "probation", "blacklist"}

# 评分维度权重
SCORE_WEIGHTS = {
    "quality": 0.30,
    "delivery": 0.25,
    "price": 0.20,
    "service": 0.15,
    "compliance": 0.10,
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  供应链深度服务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class SupplierPortalService:
    """供应链深度管理 — 从进销存到供应链协同网络"""

    def __init__(self) -> None:
        self._suppliers: Dict[str, dict] = {}
        self._rfqs: Dict[str, dict] = {}
        self._contracts: Dict[str, dict] = {}
        self._price_history: Dict[str, list] = {}  # {ingredient: [{date, supplier_id, price_fen}]}
        self._delivery_records: Dict[str, list] = {}  # {supplier_id: [{on_time, quality, date}]}
        self._store_suppliers: Dict[str, list] = {}  # {store_id: [supplier_id]}
        self._last_risk_assessment: Dict[str, dict] = {}  # cache: {store_id: assessment}

    # ──────────────────────────────────────────────────────
    #  1. Supplier Management（供应商管理）
    # ──────────────────────────────────────────────────────

    def register_supplier(
        self,
        name: str,
        category: str,
        contact: dict,
        certifications: list[str],
        payment_terms: str = "net30",
    ) -> dict:
        """注册供应商

        Args:
            name: 供应商名称
            category: 供应商类别 (seafood/meat/vegetable/seasoning/frozen/dry_goods/beverage/other)
            contact: 联系信息 {"person": "张三", "phone": "138xxx", "address": "长沙市xxx"}
            certifications: 资质认证列表 ["食品经营许可证", "ISO22000", ...]
            payment_terms: 付款条件 (net30/net60/cod)

        Returns:
            供应商字典
        """
        if category not in SUPPLIER_CATEGORIES:
            raise ValueError(f"无效供应商类别: {category}，可选: {SUPPLIER_CATEGORIES}")

        supplier_id = f"sup_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        supplier = {
            "supplier_id": supplier_id,
            "name": name,
            "category": category,
            "contact": contact,
            "certifications": certifications,
            "payment_terms": payment_terms,
            "status": "active",
            "overall_score": 0.0,
            "order_count": 0,
            "registered_at": now,
        }
        self._suppliers[supplier_id] = supplier
        return supplier

    def list_suppliers(
        self,
        category: Optional[str] = None,
        rating_min: Optional[float] = None,
    ) -> list[dict]:
        """列出供应商

        Args:
            category: 筛选类别
            rating_min: 最低评分筛选

        Returns:
            供应商列表
        """
        result = list(self._suppliers.values())

        if category:
            result = [s for s in result if s["category"] == category]
        if rating_min is not None:
            result = [s for s in result if s.get("overall_score", 0) >= rating_min]

        result.sort(key=lambda s: s.get("overall_score", 0), reverse=True)
        return result

    def get_supplier_profile(self, supplier_id: str) -> dict:
        """获取供应商详情"""
        supplier = self._suppliers.get(supplier_id)
        if not supplier:
            raise ValueError(f"供应商不存在: {supplier_id}")

        # 附加交付记录统计
        records = self._delivery_records.get(supplier_id, [])
        total_deliveries = len(records)
        on_time = sum(1 for r in records if r.get("on_time", False))
        quality_pass = sum(1 for r in records if r.get("quality") == "pass")

        profile = dict(supplier)
        profile["total_deliveries"] = total_deliveries
        profile["on_time_rate"] = round(on_time / total_deliveries, 4) if total_deliveries else 0.0
        profile["quality_pass_rate"] = round(quality_pass / total_deliveries, 4) if total_deliveries else 0.0
        profile["active_contracts"] = sum(
            1 for c in self._contracts.values()
            if c.get("supplier_id") == supplier_id and c.get("status") == "active"
        )

        return profile

    # ──────────────────────────────────────────────────────
    #  2. Auto Bidding（自动比价）
    # ──────────────────────────────────────────────────────

    def request_quotes(
        self,
        item_name: str,
        quantity: float,
        delivery_date: str,
        supplier_ids: Optional[list[str]] = None,
    ) -> dict:
        """发起询价 (RFQ)

        Args:
            item_name: 物料名称
            quantity: 数量
            delivery_date: 期望交付日期
            supplier_ids: 指定供应商列表（None 则向所有该品类供应商询价）

        Returns:
            RFQ 字典
        """
        rfq_id = f"rfq_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        # 如果未指定供应商，选择所有活跃供应商
        if supplier_ids is None:
            supplier_ids = [
                s["supplier_id"] for s in self._suppliers.values()
                if s.get("status") == "active"
            ]

        rfq = {
            "rfq_id": rfq_id,
            "item_name": item_name,
            "quantity": quantity,
            "delivery_date": delivery_date,
            "supplier_ids": supplier_ids,
            "quotes": {},  # {supplier_id: {unit_price_fen, delivery_days, notes}}
            "status": "open",
            "created_at": now,
        }
        self._rfqs[rfq_id] = rfq
        return rfq

    def _submit_quote(
        self,
        rfq_id: str,
        supplier_id: str,
        unit_price_fen: int,
        delivery_days: int,
        notes: str = "",
    ) -> None:
        """供应商提交报价（内部/测试用）"""
        rfq = self._rfqs.get(rfq_id)
        if not rfq:
            raise ValueError(f"RFQ不存在: {rfq_id}")

        rfq["quotes"][supplier_id] = {
            "supplier_id": supplier_id,
            "supplier_name": self._suppliers.get(supplier_id, {}).get("name", ""),
            "unit_price_fen": unit_price_fen,
            "delivery_days": delivery_days,
            "total_price_fen": int(unit_price_fen * rfq["quantity"]),
            "notes": notes,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }

    def compare_quotes(self, rfq_id: str) -> dict:
        """对比报价并推荐最佳供应商

        综合评分 = 价格竞争力(40%) + 交付速度(30%) + 历史可靠性(30%)

        Args:
            rfq_id: RFQ ID

        Returns:
            对比结果及推荐
        """
        rfq = self._rfqs.get(rfq_id)
        if not rfq:
            raise ValueError(f"RFQ不存在: {rfq_id}")

        quotes = rfq.get("quotes", {})
        if not quotes:
            return {
                "rfq_id": rfq_id,
                "item_name": rfq["item_name"],
                "quotes": [],
                "recommended": None,
                "reason": "无供应商报价",
            }

        # 收集所有报价数据
        quote_list = list(quotes.values())

        # 计算价格范围（用于归一化）
        prices = [q["unit_price_fen"] for q in quote_list]
        min_price = min(prices)
        max_price = max(prices)
        price_range = max_price - min_price if max_price > min_price else 1

        # 交付天数范围
        days_list = [q["delivery_days"] for q in quote_list]
        min_days = min(days_list)
        max_days = max(days_list)
        days_range = max_days - min_days if max_days > min_days else 1

        scored_quotes = []
        for q in quote_list:
            sid = q["supplier_id"]

            # 价格分（越低越好）: 100 * (max - current) / range
            price_score = 100 * (max_price - q["unit_price_fen"]) / price_range if price_range > 0 else 100

            # 交付分（越快越好）
            delivery_score = 100 * (max_days - q["delivery_days"]) / days_range if days_range > 0 else 100

            # 历史可靠性
            records = self._delivery_records.get(sid, [])
            if records:
                on_time_rate = sum(1 for r in records if r.get("on_time")) / len(records)
                quality_rate = sum(1 for r in records if r.get("quality") == "pass") / len(records)
                reliability_score = (on_time_rate * 50 + quality_rate * 50)
            else:
                reliability_score = 50  # 新供应商给中等分

            # 综合评分
            composite = (price_score * 0.4 + delivery_score * 0.3 + reliability_score * 0.3)

            scored_quotes.append({
                **q,
                "price_score": round(price_score, 1),
                "delivery_score": round(delivery_score, 1),
                "reliability_score": round(reliability_score, 1),
                "composite_score": round(composite, 1),
            })

        scored_quotes.sort(key=lambda x: x["composite_score"], reverse=True)
        best = scored_quotes[0]

        reasons = []
        if best["price_score"] >= 80:
            reasons.append("价格最优")
        if best["delivery_score"] >= 80:
            reasons.append("交付最快")
        if best["reliability_score"] >= 80:
            reasons.append("历史可靠性高")

        return {
            "rfq_id": rfq_id,
            "item_name": rfq["item_name"],
            "quantity": rfq["quantity"],
            "quotes": scored_quotes,
            "recommended": {
                "supplier_id": best["supplier_id"],
                "supplier_name": best["supplier_name"],
                "unit_price_fen": best["unit_price_fen"],
                "composite_score": best["composite_score"],
            },
            "reason": "、".join(reasons) if reasons else "综合评分最高",
        }

    def accept_quote(self, rfq_id: str, supplier_id: str) -> dict:
        """接受报价

        Args:
            rfq_id: RFQ ID
            supplier_id: 选中的供应商ID

        Returns:
            确认记录
        """
        rfq = self._rfqs.get(rfq_id)
        if not rfq:
            raise ValueError(f"RFQ不存在: {rfq_id}")

        quote = rfq["quotes"].get(supplier_id)
        if not quote:
            raise ValueError(f"供应商 {supplier_id} 未在此RFQ中报价")

        rfq["status"] = "accepted"
        rfq["accepted_supplier"] = supplier_id

        return {
            "rfq_id": rfq_id,
            "status": "accepted",
            "supplier_id": supplier_id,
            "supplier_name": quote["supplier_name"],
            "unit_price_fen": quote["unit_price_fen"],
            "total_price_fen": quote["total_price_fen"],
            "accepted_at": datetime.now(timezone.utc).isoformat(),
        }

    # ──────────────────────────────────────────────────────
    #  3. Contract Management（合同管理）
    # ──────────────────────────────────────────────────────

    def create_contract(
        self,
        supplier_id: str,
        items: list[dict],
        start_date: str,
        end_date: str,
        pricing_terms: str,
        payment_terms: str,
        penalties: dict,
    ) -> dict:
        """创建采购合同

        Args:
            supplier_id: 供应商ID
            items: 合同物料列表
                [{"ingredient_id": "i1", "name": "鲈鱼", "agreed_price_fen": 3500,
                  "min_quantity": 100, "unit": "kg"}]
            start_date: 合同开始日期
            end_date: 合同结束日期
            pricing_terms: 定价条款描述
            payment_terms: 付款条款 (net30/net60/cod)
            penalties: 违约条款
                {"late_delivery_pct": 5, "quality_failure_pct": 10,
                 "max_penalty_pct": 30}

        Returns:
            合同字典
        """
        if supplier_id not in self._suppliers:
            raise ValueError(f"供应商不存在: {supplier_id}")

        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        if end <= start:
            raise ValueError("合同结束日期必须晚于开始日期")

        contract_id = f"ct_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        contract = {
            "contract_id": contract_id,
            "supplier_id": supplier_id,
            "supplier_name": self._suppliers[supplier_id]["name"],
            "items": items,
            "item_count": len(items),
            "start_date": start_date,
            "end_date": end_date,
            "duration_days": (end - start).days,
            "pricing_terms": pricing_terms,
            "payment_terms": payment_terms,
            "penalties": penalties,
            "status": "active",
            "created_at": now,
        }
        self._contracts[contract_id] = contract
        return contract

    def check_contract_expiry(self, days_ahead: int = 30) -> list[dict]:
        """检查即将到期的合同

        Args:
            days_ahead: 提前天数预警

        Returns:
            即将到期的合同列表
        """
        today = date.today()
        deadline = today + timedelta(days=days_ahead)
        expiring = []

        for contract in self._contracts.values():
            if contract.get("status") != "active":
                continue

            end = date.fromisoformat(contract["end_date"])
            if today <= end <= deadline:
                days_remaining = (end - today).days
                expiring.append({
                    "contract_id": contract["contract_id"],
                    "supplier_id": contract["supplier_id"],
                    "supplier_name": contract["supplier_name"],
                    "end_date": contract["end_date"],
                    "days_remaining": days_remaining,
                    "item_count": contract["item_count"],
                    "urgency": "critical" if days_remaining <= 7 else "warning",
                })

        expiring.sort(key=lambda x: x["days_remaining"])
        return expiring

    def evaluate_contract_compliance(self, contract_id: str) -> dict:
        """评估合同执行合规度

        Args:
            contract_id: 合同ID

        Returns:
            合规评估结果
        """
        contract = self._contracts.get(contract_id)
        if not contract:
            raise ValueError(f"合同不存在: {contract_id}")

        supplier_id = contract["supplier_id"]
        records = self._delivery_records.get(supplier_id, [])

        # 筛选合同期内的交付记录
        start = date.fromisoformat(contract["start_date"])
        end = date.fromisoformat(contract["end_date"])

        contract_records = [
            r for r in records
            if start <= date.fromisoformat(r.get("date", "2000-01-01")) <= end
        ]

        total = len(contract_records)
        if total == 0:
            return {
                "contract_id": contract_id,
                "supplier_name": contract["supplier_name"],
                "total_deliveries": 0,
                "on_time_delivery_rate": 0.0,
                "quality_pass_rate": 0.0,
                "price_adherence": 0.0,
                "overall_compliance": 0.0,
                "status": "no_data",
            }

        on_time = sum(1 for r in contract_records if r.get("on_time", False))
        quality_pass = sum(1 for r in contract_records if r.get("quality") == "pass")
        price_ok = sum(1 for r in contract_records if r.get("price_adherence", True))

        on_time_rate = round(on_time / total, 4)
        quality_rate = round(quality_pass / total, 4)
        price_rate = round(price_ok / total, 4)
        overall = round((on_time_rate * 0.4 + quality_rate * 0.4 + price_rate * 0.2), 4)

        return {
            "contract_id": contract_id,
            "supplier_name": contract["supplier_name"],
            "total_deliveries": total,
            "on_time_delivery_rate": on_time_rate,
            "quality_pass_rate": quality_rate,
            "price_adherence": price_rate,
            "overall_compliance": overall,
            "status": "good" if overall >= 0.8 else "needs_attention" if overall >= 0.6 else "poor",
        }

    # ──────────────────────────────────────────────────────
    #  4. Price Intelligence（价格情报）
    # ──────────────────────────────────────────────────────

    def get_price_trend(self, ingredient: str, days: int = 180) -> dict:
        """获取食材价格趋势

        Args:
            ingredient: 食材名称
            days: 查看天数

        Returns:
            价格趋势数据
        """
        history = self._price_history.get(ingredient, [])
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        filtered = [
            h for h in history
            if h.get("date", "") >= cutoff
        ]

        if not filtered:
            return {
                "ingredient": ingredient,
                "days": days,
                "data_points": 0,
                "trend": "no_data",
                "prices": [],
            }

        prices = [h["price_fen"] for h in filtered]
        avg_price = round(sum(prices) / len(prices))
        min_price = min(prices)
        max_price = max(prices)
        latest = prices[-1]
        earliest = prices[0]

        # 趋势判断
        if len(prices) >= 2:
            change_pct = (latest - earliest) / earliest * 100 if earliest > 0 else 0
            if change_pct > 10:
                trend = "rising"
            elif change_pct < -10:
                trend = "falling"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"
            change_pct = 0

        return {
            "ingredient": ingredient,
            "days": days,
            "data_points": len(filtered),
            "avg_price_fen": avg_price,
            "min_price_fen": min_price,
            "max_price_fen": max_price,
            "latest_price_fen": latest,
            "change_pct": round(change_pct, 1),
            "trend": trend,
            "volatility": round((max_price - min_price) / avg_price * 100, 1) if avg_price > 0 else 0,
            "prices": filtered,
        }

    def detect_price_anomaly(
        self,
        supplier_id: str,
        item: str,
        proposed_price: int,
    ) -> dict:
        """检测价格异常（报价是否显著高于市场价）

        Args:
            supplier_id: 供应商ID
            item: 食材名称
            proposed_price: 报价（分）

        Returns:
            异常检测结果
        """
        history = self._price_history.get(item, [])

        if not history:
            return {
                "supplier_id": supplier_id,
                "item": item,
                "proposed_price_fen": proposed_price,
                "is_anomaly": False,
                "reason": "无历史价格数据，无法判断",
                "confidence": 0.0,
            }

        # 计算最近价格的统计特征
        recent_prices = [h["price_fen"] for h in history[-30:]]  # 最近30条
        avg = sum(recent_prices) / len(recent_prices)
        variance = sum((p - avg) ** 2 for p in recent_prices) / len(recent_prices)
        std_dev = math.sqrt(variance) if variance > 0 else 0

        # 异常判断：超过平均值 + 2个标准差
        threshold = avg + 2 * std_dev if std_dev > 0 else avg * 1.3
        deviation_pct = (proposed_price - avg) / avg * 100 if avg > 0 else 0

        is_anomaly = proposed_price > threshold

        if is_anomaly:
            reason = f"报价 {proposed_price}分 高于市场均价 {round(avg)}分 的 {round(deviation_pct, 1)}%"
            confidence = min(0.95, 0.5 + deviation_pct / 100)
        else:
            reason = "报价在合理范围内"
            confidence = 0.9 if len(recent_prices) >= 10 else 0.5

        return {
            "supplier_id": supplier_id,
            "item": item,
            "proposed_price_fen": proposed_price,
            "market_avg_fen": round(avg),
            "market_std_dev": round(std_dev),
            "threshold_fen": round(threshold),
            "deviation_pct": round(deviation_pct, 1),
            "is_anomaly": is_anomaly,
            "reason": reason,
            "confidence": round(confidence, 2),
        }

    def predict_price(
        self,
        ingredient: str,
        days_ahead: int = 30,
    ) -> dict:
        """价格预测（基于历史趋势 + 季节性因子）

        使用简单线性回归 + 季节性修正

        Args:
            ingredient: 食材名称
            days_ahead: 预测未来天数

        Returns:
            价格预测结果
        """
        history = self._price_history.get(ingredient, [])

        if len(history) < 5:
            return {
                "ingredient": ingredient,
                "days_ahead": days_ahead,
                "predicted_price_fen": 0,
                "confidence": 0.0,
                "method": "insufficient_data",
                "data_points": len(history),
            }

        prices = [h["price_fen"] for h in history]
        n = len(prices)

        # 简单线性回归: y = a + b*x
        x_mean = (n - 1) / 2.0
        y_mean = sum(prices) / n

        numerator = sum((i - x_mean) * (prices[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            slope = 0
        else:
            slope = numerator / denominator
        intercept = y_mean - slope * x_mean

        # 预测值
        future_x = n + days_ahead - 1
        predicted = intercept + slope * future_x

        # 季节性修正（简化：Q1/Q4 食材价格偏高 5-10%）
        target_date = datetime.now(timezone.utc) + timedelta(days=days_ahead)
        month = target_date.month
        seasonal_factor = 1.0
        if month in (1, 2, 12):  # 冬季/春节
            seasonal_factor = 1.08
        elif month in (7, 8):  # 夏季高温
            seasonal_factor = 1.05

        adjusted = int(predicted * seasonal_factor)
        adjusted = max(adjusted, 1)  # 不允许负价

        # 信心度（数据越多越高）
        confidence = min(0.85, 0.3 + n * 0.02)

        # R-squared
        ss_res = sum((prices[i] - (intercept + slope * i)) ** 2 for i in range(n))
        ss_tot = sum((prices[i] - y_mean) ** 2 for i in range(n))
        r_squared = round(1 - ss_res / ss_tot, 4) if ss_tot > 0 else 0

        return {
            "ingredient": ingredient,
            "days_ahead": days_ahead,
            "current_price_fen": prices[-1],
            "predicted_price_fen": adjusted,
            "change_fen": adjusted - prices[-1],
            "change_pct": round((adjusted - prices[-1]) / prices[-1] * 100, 1) if prices[-1] > 0 else 0,
            "seasonal_factor": seasonal_factor,
            "confidence": round(confidence, 2),
            "r_squared": r_squared,
            "method": "linear_regression_seasonal",
            "data_points": n,
        }

    # ──────────────────────────────────────────────────────
    #  5. Supplier Scoring（供应商评分）
    # ──────────────────────────────────────────────────────

    def calculate_supplier_score(self, supplier_id: str) -> dict:
        """计算供应商综合评分

        五维度加权:
            质量(30%) + 交付(25%) + 价格(20%) + 服务(15%) + 合规(10%)

        Args:
            supplier_id: 供应商ID

        Returns:
            评分详情
        """
        supplier = self._suppliers.get(supplier_id)
        if not supplier:
            raise ValueError(f"供应商不存在: {supplier_id}")

        records = self._delivery_records.get(supplier_id, [])

        if not records:
            return {
                "supplier_id": supplier_id,
                "supplier_name": supplier["name"],
                "overall_score": 0.0,
                "quality_score": 0.0,
                "delivery_score": 0.0,
                "price_score": 0.0,
                "service_score": 0.0,
                "compliance_score": 0.0,
                "trend": "no_data",
                "recommendation": "approved",
                "evaluation_period": "no_records",
                "record_count": 0,
            }

        total = len(records)

        # 质量分：验收合格率 * 100
        quality_pass = sum(1 for r in records if r.get("quality") == "pass")
        quality_score = round(quality_pass / total * 100, 1)

        # 交付分：准时交付率 * 100
        on_time = sum(1 for r in records if r.get("on_time", False))
        delivery_score = round(on_time / total * 100, 1)

        # 价格分：价格竞争力（与市场均价对比）
        price_scores = [r.get("price_competitiveness", 70) for r in records]
        price_score = round(sum(price_scores) / len(price_scores), 1)

        # 服务分：响应速度、问题解决
        service_scores = [r.get("service_rating", 70) for r in records]
        service_score = round(sum(service_scores) / len(service_scores), 1)

        # 合规分：资质有效性
        certs = supplier.get("certifications", [])
        compliance_score = min(100, len(certs) * 25)  # 每项资质25分，最高100

        # 综合加权
        overall = round(
            quality_score * SCORE_WEIGHTS["quality"]
            + delivery_score * SCORE_WEIGHTS["delivery"]
            + price_score * SCORE_WEIGHTS["price"]
            + service_score * SCORE_WEIGHTS["service"]
            + compliance_score * SCORE_WEIGHTS["compliance"],
            1,
        )

        # 更新供应商记录中的评分
        self._suppliers[supplier_id]["overall_score"] = overall

        # 趋势判断（对比前半段与后半段）
        if total >= 6:
            mid = total // 2
            early_on_time = sum(1 for r in records[:mid] if r.get("on_time")) / mid
            late_on_time = sum(1 for r in records[mid:] if r.get("on_time")) / (total - mid)
            if late_on_time > early_on_time + 0.1:
                trend = "improving"
            elif late_on_time < early_on_time - 0.1:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        # 推荐级别
        if overall >= 85:
            recommendation = "preferred"
        elif overall >= 60:
            recommendation = "approved"
        elif overall >= 40:
            recommendation = "probation"
        else:
            recommendation = "blacklist"

        return {
            "supplier_id": supplier_id,
            "supplier_name": supplier["name"],
            "overall_score": overall,
            "quality_score": quality_score,
            "delivery_score": delivery_score,
            "price_score": price_score,
            "service_score": service_score,
            "compliance_score": compliance_score,
            "trend": trend,
            "recommendation": recommendation,
            "evaluation_period": f"based on {total} deliveries",
            "record_count": total,
        }

    def get_supplier_ranking(self, category: str) -> list[dict]:
        """获取品类下供应商排名

        Args:
            category: 供应商类别

        Returns:
            排名列表
        """
        suppliers = [s for s in self._suppliers.values() if s["category"] == category]
        ranked = []

        for s in suppliers:
            score_data = self.calculate_supplier_score(s["supplier_id"])
            ranked.append({
                "supplier_id": s["supplier_id"],
                "name": s["name"],
                "overall_score": score_data["overall_score"],
                "recommendation": score_data["recommendation"],
                "trend": score_data["trend"],
            })

        ranked.sort(key=lambda x: x["overall_score"], reverse=True)
        for i, item in enumerate(ranked):
            item["rank"] = i + 1

        return ranked

    def flag_underperforming_suppliers(self) -> list[dict]:
        """标记低绩效供应商

        Returns:
            低绩效供应商列表（评分低于60或趋势下降）
        """
        flagged = []

        for sid, supplier in self._suppliers.items():
            if supplier.get("status") == "blacklisted":
                continue

            records = self._delivery_records.get(sid, [])
            if not records:
                continue

            score_data = self.calculate_supplier_score(sid)
            reasons = []

            if score_data["overall_score"] < 60:
                reasons.append(f"综合评分 {score_data['overall_score']} 低于60分")
            if score_data["quality_score"] < 70:
                reasons.append(f"质量评分 {score_data['quality_score']} 低于70分")
            if score_data["delivery_score"] < 70:
                reasons.append(f"交付评分 {score_data['delivery_score']} 低于70分")
            if score_data["trend"] == "declining":
                reasons.append("绩效趋势下降")

            if reasons:
                flagged.append({
                    "supplier_id": sid,
                    "name": supplier["name"],
                    "category": supplier["category"],
                    "overall_score": score_data["overall_score"],
                    "recommendation": score_data["recommendation"],
                    "reasons": reasons,
                    "suggested_action": "blacklist" if score_data["overall_score"] < 40 else "probation",
                })

        flagged.sort(key=lambda x: x["overall_score"])
        return flagged

    # ──────────────────────────────────────────────────────
    #  6. Supply Chain Risk（供应链风险）
    # ──────────────────────────────────────────────────────

    def assess_risk(self, store_id: str) -> dict:
        """评估门店供应链风险

        Args:
            store_id: 门店ID

        Returns:
            风险评估报告
        """
        supplier_ids = self._store_suppliers.get(store_id, [])
        risks = []
        risk_score = 0  # 累计风险分

        # 1. 单一来源依赖
        ingredient_suppliers: Dict[str, list] = {}
        for sid in supplier_ids:
            records = self._delivery_records.get(sid, [])
            for r in records:
                ing = r.get("ingredient", "")
                if ing:
                    if ing not in ingredient_suppliers:
                        ingredient_suppliers[ing] = set()
                    ingredient_suppliers[ing].add(sid)

        single_source = [
            ing for ing, sups in ingredient_suppliers.items()
            if len(sups) == 1
        ]
        if single_source:
            risks.append({
                "risk_id": f"risk_{uuid.uuid4().hex[:6]}",
                "type": "single_source_dependency",
                "severity": "high",
                "description": f"{len(single_source)} 种食材仅有单一供应商",
                "affected_items": single_source[:10],
                "impact": "供应商故障将导致断供",
            })
            risk_score += len(single_source) * 10

        # 2. 价格波动
        volatile_items = []
        for ingredient, history in self._price_history.items():
            if len(history) < 3:
                continue
            prices = [h["price_fen"] for h in history[-20:]]
            avg = sum(prices) / len(prices)
            if avg > 0:
                volatility = (max(prices) - min(prices)) / avg * 100
                if volatility > 30:
                    volatile_items.append({
                        "ingredient": ingredient,
                        "volatility_pct": round(volatility, 1),
                    })

        if volatile_items:
            risks.append({
                "risk_id": f"risk_{uuid.uuid4().hex[:6]}",
                "type": "price_volatility",
                "severity": "medium",
                "description": f"{len(volatile_items)} 种食材价格波动超30%",
                "affected_items": volatile_items[:10],
                "impact": "成本不可控，影响利润",
            })
            risk_score += len(volatile_items) * 5

        # 3. 交付失败率
        poor_delivery_suppliers = []
        for sid in supplier_ids:
            records = self._delivery_records.get(sid, [])
            if not records:
                continue
            on_time = sum(1 for r in records if r.get("on_time", False))
            rate = on_time / len(records)
            if rate < 0.8:
                poor_delivery_suppliers.append({
                    "supplier_id": sid,
                    "name": self._suppliers.get(sid, {}).get("name", ""),
                    "on_time_rate": round(rate, 2),
                })

        if poor_delivery_suppliers:
            risks.append({
                "risk_id": f"risk_{uuid.uuid4().hex[:6]}",
                "type": "delivery_failure_rate",
                "severity": "high" if any(s["on_time_rate"] < 0.6 for s in poor_delivery_suppliers) else "medium",
                "description": f"{len(poor_delivery_suppliers)} 个供应商准时交付率低于80%",
                "affected_suppliers": poor_delivery_suppliers,
                "impact": "影响出品和运营",
            })
            risk_score += len(poor_delivery_suppliers) * 8

        # 4. 合同缺口
        expiring = self.check_contract_expiry(days_ahead=30)
        if expiring:
            risks.append({
                "risk_id": f"risk_{uuid.uuid4().hex[:6]}",
                "type": "contract_gaps",
                "severity": "medium",
                "description": f"{len(expiring)} 份合同将在30天内到期",
                "affected_contracts": expiring,
                "impact": "失去价格锁定和供货保障",
            })
            risk_score += len(expiring) * 5

        # 5. 集中度风险
        if supplier_ids:
            # 计算各供应商的采购占比
            supplier_spend: Dict[str, int] = {}
            total_spend = 0
            for sid in supplier_ids:
                records = self._delivery_records.get(sid, [])
                spend = sum(r.get("total_fen", 0) for r in records)
                supplier_spend[sid] = spend
                total_spend += spend

            if total_spend > 0:
                concentrated = [
                    {
                        "supplier_id": sid,
                        "name": self._suppliers.get(sid, {}).get("name", ""),
                        "spend_ratio": round(spend / total_spend, 2),
                    }
                    for sid, spend in supplier_spend.items()
                    if spend / total_spend > 0.5
                ]
                if concentrated:
                    risks.append({
                        "risk_id": f"risk_{uuid.uuid4().hex[:6]}",
                        "type": "concentration_risk",
                        "severity": "high",
                        "description": "超过50%采购额集中在单一供应商",
                        "affected_suppliers": concentrated,
                        "impact": "供应商议价能力过强，风险集中",
                    })
                    risk_score += 20

        # 风险等级
        if risk_score >= 50:
            risk_level = "high"
        elif risk_score >= 20:
            risk_level = "medium"
        else:
            risk_level = "low"

        result = {
            "store_id": store_id,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "risk_count": len(risks),
            "risks": risks,
            "assessed_at": datetime.now(timezone.utc).isoformat(),
        }
        # Cache for suggest_mitigation lookup
        self._last_risk_assessment[store_id] = result
        return result

    def suggest_mitigation(self, risk_id: str) -> dict:
        """为风险提供缓解建议

        Args:
            risk_id: 风险ID（来自 assess_risk 的结果）

        Returns:
            缓解建议
        """
        # 查找风险 — 先从缓存查，再重新评估
        risk = None
        for store_id, cached in self._last_risk_assessment.items():
            for r in cached.get("risks", []):
                if r.get("risk_id") == risk_id:
                    risk = r
                    break
            if risk:
                break
        if risk is None:
            for store_id in self._store_suppliers:
                assessment = self.assess_risk(store_id)
                for r in assessment.get("risks", []):
                    if r.get("risk_id") == risk_id:
                        risk = r
                        break
                if risk:
                    break

        # 根据风险类型给出建议（即使找不到也提供通用建议）
        risk_type = risk.get("type", "unknown") if risk else "unknown"

        mitigation_map = {
            "single_source_dependency": {
                "actions": [
                    "为单一来源食材发展至少1个备选供应商",
                    "与现有供应商签订长期保供协议",
                    "建立关键食材的安全库存（7天用量）",
                    "评估可替代食材方案",
                ],
                "priority": "high",
                "timeline": "30天内完成备选供应商对接",
            },
            "price_volatility": {
                "actions": [
                    "与供应商签订价格锁定协议（季度/半年）",
                    "建立期货采购机制，低价时提前锁量",
                    "开发替代食材配方，降低对高波动食材依赖",
                    "定期监控市场价格，设置预警阈值",
                ],
                "priority": "medium",
                "timeline": "60天内签订价格保护协议",
            },
            "delivery_failure_rate": {
                "actions": [
                    "约谈供应商，制定交付改善计划",
                    "设置交付KPI考核及违约扣款条款",
                    "发展备选供应商分散交付风险",
                    "对关键食材实施安全库存策略",
                ],
                "priority": "high",
                "timeline": "15天内完成供应商约谈",
            },
            "contract_gaps": {
                "actions": [
                    "立即启动合同续签谈判",
                    "对比市场价格，评估续签条款合理性",
                    "为到期合同准备备选供应商方案",
                    "更新合同到期提醒机制（提前60天）",
                ],
                "priority": "medium",
                "timeline": "7天内启动续签流程",
            },
            "concentration_risk": {
                "actions": [
                    "制定供应商多元化策略，单一供应商占比不超过40%",
                    "逐步引入新供应商分摊采购量",
                    "与集中供应商谈判更有利的价格条款（利用规模优势）",
                    "建立供应商淘汰与引入机制",
                ],
                "priority": "high",
                "timeline": "90天内将集中度降至50%以下",
            },
        }

        suggestion = mitigation_map.get(risk_type, {
            "actions": [
                "定期审查供应链风险",
                "建立供应链风险应急预案",
                "加强供应商绩效监控",
            ],
            "priority": "medium",
            "timeline": "持续改进",
        })

        return {
            "risk_id": risk_id,
            "risk_type": risk_type,
            "description": risk.get("description", "") if risk else "未知风险",
            "severity": risk.get("severity", "unknown") if risk else "unknown",
            "mitigation": suggestion,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ──────────────────────────────────────────────────────
    #  内部辅助：注入模拟数据（测试用）
    # ──────────────────────────────────────────────────────

    def _add_delivery_record(
        self,
        supplier_id: str,
        record: dict,
    ) -> None:
        """添加交付记录（测试辅助方法）"""
        if supplier_id not in self._delivery_records:
            self._delivery_records[supplier_id] = []
        self._delivery_records[supplier_id].append(record)

    def _add_price_history(self, ingredient: str, entries: list[dict]) -> None:
        """添加价格历史（测试辅助方法）"""
        if ingredient not in self._price_history:
            self._price_history[ingredient] = []
        self._price_history[ingredient].extend(entries)

    def _link_store_supplier(self, store_id: str, supplier_id: str) -> None:
        """关联门店与供应商（测试辅助方法）"""
        if store_id not in self._store_suppliers:
            self._store_suppliers[store_id] = []
        if supplier_id not in self._store_suppliers[store_id]:
            self._store_suppliers[store_id].append(supplier_id)
