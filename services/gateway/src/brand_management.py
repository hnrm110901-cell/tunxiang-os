"""多品牌经营中台 — 集团级统一管理 (U2.3)

核心能力：
- 品牌注册与管理
- 菜单模板继承（集团 → 品牌 → 门店 三级覆盖）
- 跨品牌会员通兑
- 集团统一采购与成本分摊
- 品牌经营对比分析
- 集团驾驶舱

金额单位统一为"分"（fen），与 V2.x 保持一致。
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  数据模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


BUSINESS_TYPES = {"fine_dining", "casual", "fast_food", "takeaway", "banquet"}
BRAND_STATUSES = {"active", "inactive", "launching"}
TEMPLATE_TIERS = {"Pro", "Standard", "Lite"}


@dataclass
class Brand:
    brand_id: str
    group_id: str
    brand_name: str
    business_type: str  # fine_dining/casual/fast_food/takeaway/banquet
    store_count: int
    status: str  # active/inactive/launching
    template_tier: str  # Pro/Standard/Lite
    description: str = ""
    logo_url: str = ""
    theme_colors: dict = field(default_factory=dict)
    created_at: str = ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  多品牌管理服务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class BrandManagementService:
    """多品牌经营中台 — 集团级统一管理"""

    def __init__(self) -> None:
        # 内存存储（纯函数风格，生产环境接 DB）
        self._brands: Dict[str, dict] = {}
        self._master_menus: Dict[str, dict] = {}
        self._brand_menus: Dict[str, dict] = {}
        self._store_menus: Dict[str, dict] = {}
        self._members: Dict[str, dict] = {}
        self._procurement_plans: Dict[str, dict] = {}
        # 模拟门店数据
        self._stores: Dict[str, dict] = {}
        # 模拟经营数据
        self._brand_metrics: Dict[str, dict] = {}

    # ──────────────────────────────────────────────────────
    #  1. Brand Registry（品牌注册）
    # ──────────────────────────────────────────────────────

    def create_brand(
        self,
        group_id: str,
        brand_name: str,
        business_type: str,
        description: str = "",
        logo_url: str = "",
        theme_colors: Optional[dict] = None,
    ) -> dict:
        """创建品牌

        Args:
            group_id: 集团ID
            brand_name: 品牌名称
            business_type: 业态 (fine_dining/casual/fast_food/takeaway/banquet)
            description: 品牌描述
            logo_url: Logo URL
            theme_colors: 主题色 {"primary": "#xxx", "secondary": "#xxx"}

        Returns:
            品牌详情字典
        """
        if business_type not in BUSINESS_TYPES:
            raise ValueError(f"无效业态: {business_type}，可选: {BUSINESS_TYPES}")

        brand_id = f"brand_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        brand_data = {
            "brand_id": brand_id,
            "group_id": group_id,
            "brand_name": brand_name,
            "business_type": business_type,
            "store_count": 0,
            "status": "launching",
            "template_tier": "Standard",
            "description": description,
            "logo_url": logo_url,
            "theme_colors": theme_colors or {},
            "created_at": now,
        }
        self._brands[brand_id] = brand_data
        return brand_data

    def list_brands(self, group_id: str) -> list[dict]:
        """列出集团下所有品牌"""
        return [b for b in self._brands.values() if b["group_id"] == group_id]

    def get_brand_detail(self, brand_id: str) -> dict:
        """获取品牌详情"""
        brand = self._brands.get(brand_id)
        if not brand:
            raise ValueError(f"品牌不存在: {brand_id}")
        return brand

    # ──────────────────────────────────────────────────────
    #  2. Menu Template Inheritance（菜单模板继承）
    # ──────────────────────────────────────────────────────

    def create_master_menu(
        self,
        group_id: str,
        menu_name: str,
        items: list[dict],
    ) -> dict:
        """创建集团主菜单

        Args:
            group_id: 集团ID
            menu_name: 菜单名称
            items: 菜品列表
                [{"dish_id": "d1", "name": "红烧肉", "price_fen": 6800,
                  "category": "热菜", "description": "..."}]

        Returns:
            主菜单字典
        """
        menu_id = f"mm_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        # 为每个菜品添加标识
        processed_items = []
        for item in items:
            processed = dict(item)
            processed.setdefault("dish_id", f"dish_{uuid.uuid4().hex[:6]}")
            processed.setdefault("status", "active")
            processed_items.append(processed)

        menu = {
            "menu_id": menu_id,
            "group_id": group_id,
            "menu_name": menu_name,
            "menu_level": "master",
            "items": processed_items,
            "item_count": len(processed_items),
            "created_at": now,
            "updated_at": now,
        }
        self._master_menus[menu_id] = menu
        return menu

    def create_brand_menu(
        self,
        brand_id: str,
        parent_menu_id: str,
        overrides: list[dict],
    ) -> dict:
        """创建品牌菜单（继承集团主菜单）

        Args:
            brand_id: 品牌ID
            parent_menu_id: 父菜单ID（集团主菜单）
            overrides: 覆盖配置列表
                [{"dish_id": "d1", "action": "override", "price_fen": 7800},
                 {"dish_id": "d_new", "action": "add", "name": "龙虾", "price_fen": 38800},
                 {"dish_id": "d2", "action": "remove"}]

        Returns:
            品牌菜单字典
        """
        parent = self._master_menus.get(parent_menu_id)
        if not parent:
            raise ValueError(f"父菜单不存在: {parent_menu_id}")

        menu_id = f"bm_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        menu = {
            "menu_id": menu_id,
            "brand_id": brand_id,
            "parent_menu_id": parent_menu_id,
            "menu_level": "brand",
            "overrides": overrides,
            "created_at": now,
            "updated_at": now,
        }
        self._brand_menus[menu_id] = menu
        return menu

    def create_store_menu(
        self,
        store_id: str,
        parent_brand_menu_id: str,
        overrides: list[dict],
    ) -> dict:
        """创建门店菜单（继承品牌菜单）

        Args:
            store_id: 门店ID
            parent_brand_menu_id: 父菜单ID（品牌菜单）
            overrides: 覆盖配置列表（同 create_brand_menu）

        Returns:
            门店菜单字典
        """
        parent = self._brand_menus.get(parent_brand_menu_id)
        if not parent:
            raise ValueError(f"品牌菜单不存在: {parent_brand_menu_id}")

        menu_id = f"sm_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        menu = {
            "menu_id": menu_id,
            "store_id": store_id,
            "parent_brand_menu_id": parent_brand_menu_id,
            "menu_level": "store",
            "overrides": overrides,
            "created_at": now,
            "updated_at": now,
        }
        self._store_menus[menu_id] = menu
        return menu

    def resolve_effective_menu(self, store_id: str) -> list[dict]:
        """解析门店最终有效菜单

        合并链路: master → brand overrides → store overrides
        返回门店实际使用的完整菜品列表

        Args:
            store_id: 门店ID

        Returns:
            最终菜品列表（已合并所有层级覆盖）
        """
        # 找到该门店的门店菜单
        store_menu = None
        for sm in self._store_menus.values():
            if sm["store_id"] == store_id:
                store_menu = sm
                break

        if not store_menu:
            raise ValueError(f"门店 {store_id} 无菜单配置")

        # 找到品牌菜单
        brand_menu = self._brand_menus.get(store_menu["parent_brand_menu_id"])
        if not brand_menu:
            raise ValueError(f"品牌菜单不存在: {store_menu['parent_brand_menu_id']}")

        # 找到主菜单
        master_menu = self._master_menus.get(brand_menu["parent_menu_id"])
        if not master_menu:
            raise ValueError(f"主菜单不存在: {brand_menu['parent_menu_id']}")

        # 1. 从主菜单开始，建立 dish_id → item 映射
        items_map: Dict[str, dict] = {}
        for item in master_menu["items"]:
            items_map[item["dish_id"]] = deepcopy(item)
            items_map[item["dish_id"]]["source"] = "master"

        # 2. 应用品牌级覆盖
        items_map = self._apply_overrides(items_map, brand_menu.get("overrides", []), "brand")

        # 3. 应用门店级覆盖
        items_map = self._apply_overrides(items_map, store_menu.get("overrides", []), "store")

        # 返回有效菜品（排除已移除的）
        return sorted(items_map.values(), key=lambda x: x.get("dish_id", ""))

    @staticmethod
    def _apply_overrides(
        items_map: Dict[str, dict],
        overrides: list[dict],
        level: str,
    ) -> Dict[str, dict]:
        """应用覆盖规则到菜品映射

        Args:
            items_map: 当前菜品映射 {dish_id: item_dict}
            overrides: 覆盖规则列表
            level: 覆盖层级标识 (brand/store)

        Returns:
            更新后的菜品映射
        """
        for override in overrides:
            action = override.get("action", "override")
            dish_id = override.get("dish_id")

            if action == "remove":
                # 移除菜品
                items_map.pop(dish_id, None)

            elif action == "add":
                # 新增菜品
                new_item = {k: v for k, v in override.items() if k != "action"}
                new_item["source"] = level
                items_map[dish_id] = new_item

            elif action == "override":
                # 覆盖现有菜品属性
                if dish_id in items_map:
                    for k, v in override.items():
                        if k not in ("action", "dish_id"):
                            items_map[dish_id][k] = v
                    items_map[dish_id]["source"] = level

        return items_map

    # ──────────────────────────────────────────────────────
    #  3. Cross-brand Member（跨品牌会员通兑）
    # ──────────────────────────────────────────────────────

    def link_member_across_brands(
        self,
        member_id: str,
        brand_ids: list[str],
    ) -> dict:
        """关联会员到多个品牌

        Args:
            member_id: 会员ID
            brand_ids: 品牌ID列表

        Returns:
            会员跨品牌档案
        """
        if len(brand_ids) < 2:
            raise ValueError("至少需要关联2个品牌")

        # 验证品牌存在
        for bid in brand_ids:
            if bid not in self._brands:
                raise ValueError(f"品牌不存在: {bid}")

        now = datetime.now(timezone.utc).isoformat()

        member_profile = self._members.get(member_id, {
            "member_id": member_id,
            "linked_brands": [],
            "points_by_brand": {},
            "visit_count_by_brand": {},
            "spend_by_brand_fen": {},
            "total_points": 0,
            "total_spend_fen": 0,
            "linked_at": now,
        })

        # 合并品牌关联
        existing_brands = set(member_profile.get("linked_brands", []))
        new_brands = existing_brands | set(brand_ids)
        member_profile["linked_brands"] = sorted(new_brands)

        # 初始化新品牌的数据
        for bid in brand_ids:
            if bid not in member_profile["points_by_brand"]:
                member_profile["points_by_brand"][bid] = 0
            if bid not in member_profile["visit_count_by_brand"]:
                member_profile["visit_count_by_brand"][bid] = 0
            if bid not in member_profile["spend_by_brand_fen"]:
                member_profile["spend_by_brand_fen"][bid] = 0

        member_profile["updated_at"] = now
        self._members[member_id] = member_profile
        return member_profile

    def transfer_points(
        self,
        member_id: str,
        from_brand: str,
        to_brand: str,
        points: int,
        exchange_rate: float = 1.0,
    ) -> dict:
        """跨品牌积分转移

        Args:
            member_id: 会员ID
            from_brand: 源品牌ID
            to_brand: 目标品牌ID
            points: 转出积分数
            exchange_rate: 兑换比例（默认1:1）

        Returns:
            转移记录字典
        """
        profile = self._members.get(member_id)
        if not profile:
            raise ValueError(f"会员不存在: {member_id}")

        if from_brand not in profile.get("linked_brands", []):
            raise ValueError(f"会员未关联品牌: {from_brand}")
        if to_brand not in profile.get("linked_brands", []):
            raise ValueError(f"会员未关联品牌: {to_brand}")
        if from_brand == to_brand:
            raise ValueError("源品牌和目标品牌不能相同")

        available = profile["points_by_brand"].get(from_brand, 0)
        if available < points:
            raise ValueError(f"积分不足: 可用 {available}，需转 {points}")

        converted = int(points * exchange_rate)

        # 执行转移
        profile["points_by_brand"][from_brand] -= points
        profile["points_by_brand"][to_brand] += converted
        profile["total_points"] = sum(profile["points_by_brand"].values())

        now = datetime.now(timezone.utc).isoformat()
        transfer_record = {
            "transfer_id": f"pt_{uuid.uuid4().hex[:8]}",
            "member_id": member_id,
            "from_brand": from_brand,
            "to_brand": to_brand,
            "points_out": points,
            "points_in": converted,
            "exchange_rate": exchange_rate,
            "transferred_at": now,
        }
        return transfer_record

    def get_member_cross_brand_profile(self, member_id: str) -> dict:
        """获取会员跨品牌汇总档案

        Returns:
            total_points, points_by_brand, visit_count_by_brand, total_spend_fen
        """
        profile = self._members.get(member_id)
        if not profile:
            raise ValueError(f"会员不存在: {member_id}")

        return {
            "member_id": member_id,
            "linked_brands": profile["linked_brands"],
            "total_points": profile["total_points"],
            "points_by_brand": profile["points_by_brand"],
            "visit_count_by_brand": profile["visit_count_by_brand"],
            "total_spend_fen": profile["total_spend_fen"],
            "spend_by_brand_fen": profile["spend_by_brand_fen"],
        }

    # ──────────────────────────────────────────────────────
    #  4. Unified Procurement（集团统一采购）
    # ──────────────────────────────────────────────────────

    def create_group_procurement_plan(
        self,
        group_id: str,
        items: list[dict],
    ) -> dict:
        """创建集团统一采购计划

        汇总所有品牌/门店需求 → 统一采购订单

        Args:
            group_id: 集团ID
            items: 采购项列表
                [{"ingredient_id": "ing1", "name": "鲈鱼", "unit": "kg",
                  "demands": [
                      {"brand_id": "b1", "store_id": "s1", "quantity": 50},
                      {"brand_id": "b1", "store_id": "s2", "quantity": 30},
                      {"brand_id": "b2", "store_id": "s3", "quantity": 40},
                  ],
                  "estimated_unit_price_fen": 3500}]

        Returns:
            集团采购计划字典
        """
        plan_id = f"gpp_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        processed_items = []
        total_fen = 0

        for item in items:
            demands = item.get("demands", [])
            total_qty = sum(d.get("quantity", 0) for d in demands)
            unit_price = item.get("estimated_unit_price_fen", 0)
            line_total = int(total_qty * unit_price)
            total_fen += line_total

            processed_items.append({
                "ingredient_id": item.get("ingredient_id"),
                "name": item.get("name"),
                "unit": item.get("unit", "kg"),
                "total_quantity": total_qty,
                "demands": demands,
                "demand_count": len(demands),
                "estimated_unit_price_fen": unit_price,
                "line_total_fen": line_total,
            })

        plan = {
            "plan_id": plan_id,
            "group_id": group_id,
            "status": "draft",
            "items": processed_items,
            "item_count": len(processed_items),
            "total_estimated_fen": total_fen,
            "created_at": now,
        }
        self._procurement_plans[plan_id] = plan
        return plan

    def split_delivery(self, procurement_id: str) -> list[dict]:
        """拆分统一采购订单为各门店配送单

        Args:
            procurement_id: 采购计划ID

        Returns:
            门店配送单列表
        """
        plan = self._procurement_plans.get(procurement_id)
        if not plan:
            raise ValueError(f"采购计划不存在: {procurement_id}")

        # 按门店聚合
        store_deliveries: Dict[str, dict] = {}

        for item in plan.get("items", []):
            for demand in item.get("demands", []):
                store_id = demand["store_id"]
                brand_id = demand.get("brand_id", "")

                if store_id not in store_deliveries:
                    store_deliveries[store_id] = {
                        "delivery_id": f"dlv_{uuid.uuid4().hex[:8]}",
                        "procurement_plan_id": procurement_id,
                        "store_id": store_id,
                        "brand_id": brand_id,
                        "items": [],
                        "total_fen": 0,
                    }

                line_fen = int(demand["quantity"] * item.get("estimated_unit_price_fen", 0))
                store_deliveries[store_id]["items"].append({
                    "ingredient_id": item["ingredient_id"],
                    "name": item["name"],
                    "unit": item.get("unit", "kg"),
                    "quantity": demand["quantity"],
                    "unit_price_fen": item.get("estimated_unit_price_fen", 0),
                    "line_total_fen": line_fen,
                })
                store_deliveries[store_id]["total_fen"] += line_fen

        return list(store_deliveries.values())

    def allocate_cost(self, procurement_id: str) -> dict:
        """按品牌/门店比例分摊采购成本

        Args:
            procurement_id: 采购计划ID

        Returns:
            成本分摊明细
        """
        plan = self._procurement_plans.get(procurement_id)
        if not plan:
            raise ValueError(f"采购计划不存在: {procurement_id}")

        total_fen = plan["total_estimated_fen"]
        brand_cost: Dict[str, int] = {}
        store_cost: Dict[str, int] = {}

        for item in plan.get("items", []):
            unit_price = item.get("estimated_unit_price_fen", 0)
            for demand in item.get("demands", []):
                cost = int(demand["quantity"] * unit_price)
                brand_id = demand.get("brand_id", "unknown")
                store_id = demand["store_id"]

                brand_cost[brand_id] = brand_cost.get(brand_id, 0) + cost
                store_cost[store_id] = store_cost.get(store_id, 0) + cost

        # 计算比率
        brand_allocation = {}
        for bid, cost in brand_cost.items():
            brand_allocation[bid] = {
                "cost_fen": cost,
                "ratio": round(cost / total_fen, 4) if total_fen > 0 else 0,
            }

        store_allocation = {}
        for sid, cost in store_cost.items():
            store_allocation[sid] = {
                "cost_fen": cost,
                "ratio": round(cost / total_fen, 4) if total_fen > 0 else 0,
            }

        return {
            "procurement_plan_id": procurement_id,
            "total_cost_fen": total_fen,
            "brand_allocation": brand_allocation,
            "store_allocation": store_allocation,
        }

    # ──────────────────────────────────────────────────────
    #  5. Brand Comparison Analytics（品牌经营对比）
    # ──────────────────────────────────────────────────────

    def compare_brands(
        self,
        group_id: str,
        metrics: list[str],
        date_range: dict,
    ) -> dict:
        """多品牌经营指标对比

        Args:
            group_id: 集团ID
            metrics: 对比指标列表
                可选: revenue, profit_margin, table_turnover,
                      customer_satisfaction, labor_efficiency, waste_rate
            date_range: {"start": "2026-01-01", "end": "2026-03-31"}

        Returns:
            品牌对比结果
        """
        brands = self.list_brands(group_id)
        if not brands:
            return {"group_id": group_id, "brands": [], "date_range": date_range}

        comparison = []
        for brand in brands:
            bid = brand["brand_id"]
            brand_data = self._brand_metrics.get(bid, {})

            metric_values = {}
            for m in metrics:
                metric_values[m] = brand_data.get(m, 0)

            comparison.append({
                "brand_id": bid,
                "brand_name": brand["brand_name"],
                "business_type": brand["business_type"],
                "store_count": brand.get("store_count", 0),
                "metrics": metric_values,
            })

        # 计算集团平均值
        group_avg = {}
        for m in metrics:
            values = [c["metrics"].get(m, 0) for c in comparison]
            group_avg[m] = round(sum(values) / len(values), 2) if values else 0

        return {
            "group_id": group_id,
            "date_range": date_range,
            "brands": comparison,
            "group_average": group_avg,
        }

    def get_brand_ranking(
        self,
        group_id: str,
        metric: str,
        period: str = "month",
    ) -> list[dict]:
        """品牌排行榜

        Args:
            group_id: 集团ID
            metric: 排序指标
            period: 时间周期 (day/week/month/quarter/year)

        Returns:
            按指标排名的品牌列表
        """
        brands = self.list_brands(group_id)
        ranked = []

        for brand in brands:
            bid = brand["brand_id"]
            brand_data = self._brand_metrics.get(bid, {})
            value = brand_data.get(metric, 0)

            ranked.append({
                "brand_id": bid,
                "brand_name": brand["brand_name"],
                "metric": metric,
                "value": value,
                "period": period,
            })

        ranked.sort(key=lambda x: x["value"], reverse=True)

        for i, item in enumerate(ranked):
            item["rank"] = i + 1

        return ranked

    def detect_brand_anomaly(self, group_id: str) -> list[dict]:
        """检测品牌异常（显著低于集团平均值的指标）

        对每个品牌检查关键指标，如果某指标低于集团平均值的70%，视为异常。

        Args:
            group_id: 集团ID

        Returns:
            异常列表
        """
        KEY_METRICS = ["revenue", "profit_margin", "customer_satisfaction", "table_turnover"]
        ANOMALY_THRESHOLD = 0.7  # 低于平均值70%视为异常

        brands = self.list_brands(group_id)
        if len(brands) < 2:
            return []

        anomalies = []

        for metric in KEY_METRICS:
            values = []
            for brand in brands:
                bid = brand["brand_id"]
                val = self._brand_metrics.get(bid, {}).get(metric, 0)
                values.append((brand, val))

            avg = sum(v for _, v in values) / len(values) if values else 0
            if avg <= 0:
                continue

            threshold = avg * ANOMALY_THRESHOLD

            for brand, val in values:
                if val < threshold and val > 0:
                    deviation = round((avg - val) / avg * 100, 1)
                    anomalies.append({
                        "brand_id": brand["brand_id"],
                        "brand_name": brand["brand_name"],
                        "metric": metric,
                        "value": val,
                        "group_average": round(avg, 2),
                        "deviation_pct": deviation,
                        "severity": "critical" if val < avg * 0.5 else "warning",
                        "suggestion": f"品牌 {brand['brand_name']} 的 {metric} "
                                      f"低于集团平均 {deviation}%，建议重点关注",
                    })

        anomalies.sort(key=lambda x: x["deviation_pct"], reverse=True)
        return anomalies

    # ──────────────────────────────────────────────────────
    #  6. Group Dashboard（集团驾驶舱）
    # ──────────────────────────────────────────────────────

    def get_group_overview(self, group_id: str) -> dict:
        """集团驾驶舱概览

        Args:
            group_id: 集团ID

        Returns:
            集团全局汇总数据
        """
        brands = self.list_brands(group_id)

        total_revenue_fen = 0
        total_stores = 0
        total_employees = 0
        total_members = 0
        brand_breakdown = []
        risk_alerts = []

        for brand in brands:
            bid = brand["brand_id"]
            metrics = self._brand_metrics.get(bid, {})

            revenue = metrics.get("revenue_fen", 0)
            stores = brand.get("store_count", 0)
            employees = metrics.get("employee_count", 0)
            members = metrics.get("member_count", 0)

            total_revenue_fen += revenue
            total_stores += stores
            total_employees += employees
            total_members += members

            brand_breakdown.append({
                "brand_id": bid,
                "brand_name": brand["brand_name"],
                "revenue_fen": revenue,
                "store_count": stores,
                "employee_count": employees,
                "member_count": members,
                "profit_margin": metrics.get("profit_margin", 0),
            })

            # 风险提示
            if metrics.get("profit_margin", 100) < 15:
                risk_alerts.append({
                    "brand_id": bid,
                    "brand_name": brand["brand_name"],
                    "alert_type": "low_profit_margin",
                    "message": f"{brand['brand_name']} 毛利率 {metrics.get('profit_margin', 0)}% 低于15%警戒线",
                })

        # 排名：按营收排序前5
        brand_breakdown.sort(key=lambda x: x["revenue_fen"], reverse=True)
        top_brands = brand_breakdown[:5]

        return {
            "group_id": group_id,
            "total_revenue_fen": total_revenue_fen,
            "total_stores": total_stores,
            "total_employees": total_employees,
            "total_members": total_members,
            "brand_count": len(brands),
            "brand_breakdown": brand_breakdown,
            "top_brands": top_brands,
            "risk_alerts": risk_alerts,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ──────────────────────────────────────────────────────
    #  内部辅助：注入模拟数据（测试用）
    # ──────────────────────────────────────────────────────

    def _set_brand_metrics(self, brand_id: str, metrics: dict) -> None:
        """注入品牌经营数据（测试辅助方法）"""
        self._brand_metrics[brand_id] = metrics

    def _set_member_points(self, member_id: str, brand_id: str, points: int) -> None:
        """设置会员积分（测试辅助方法）"""
        if member_id in self._members:
            self._members[member_id]["points_by_brand"][brand_id] = points
            self._members[member_id]["total_points"] = sum(
                self._members[member_id]["points_by_brand"].values()
            )
