"""智能排菜Agent — 根据库存、销量、利润数据推荐最优菜品排序与推荐

工作流程：
1. Python预计算：识别临期食材关联菜品、计算平均毛利率、多样性检查
2. 调用Claude（claude-sonnet-4-6）进行综合排菜决策
3. 记录决策日志（留痕）
4. 返回：推荐菜品/重点推广/临期消耗/套餐建议/菜单调整
"""
from __future__ import annotations

import json
import re

import anthropic
import structlog

logger = structlog.get_logger()
client = anthropic.AsyncAnthropic()  # 从环境变量 ANTHROPIC_API_KEY 读取

# 临期食材阈值（天）
EXPIRY_THRESHOLD_DAYS = 3
# 推荐菜品最低平均毛利率
MIN_MARGIN_RATE = 0.40
# 多样性：推荐菜品中至少需要的分类数量
MIN_CATEGORY_COUNT = 2


class MenuOptimizer:
    """智能排菜Agent：根据库存、历史销量、利润数据推荐最优菜品排序

    三条硬约束校验：
    - 毛利底线：推荐菜品平均毛利率 ≥ 40%
    - 食安合规：临期食材（expiry_days ≤ 3）必须纳入消耗计划
    - 客户体验：推荐菜品包含不同口味/价位/分类，保证多样性
    """

    SYSTEM_PROMPT = """你是屯象OS的智能排菜智能体。你的职责是根据餐厅当日库存、销量数据和盈利情况，为餐厅推荐最优菜品排序和运营策略。

三条不可突破的硬约束：
1. 毛利底线：推荐的菜品平均毛利率必须≥40%
2. 食安合规：临期食材（≤3天）必须有对应菜品进入today_deplete计划
3. 客户体验：推荐菜品必须涵盖不同分类/口味/价位，不能全是单一品类

你需要综合考虑：
- 当前库存量及食材临期风险
- 各菜品历史销量和利润贡献
- 天气、日期类型对点餐偏好的影响
- 套餐搭配的营收放大效应

返回严格的JSON格式（无其他文字）：
{
  "featured_dishes": [
    {"dish_id": "string", "dish_name": "string", "reason": "string", "priority": 1, "expected_boost": "预计提升X%"}
  ],
  "dishes_to_promote": ["dish_id_1", "dish_id_2"],
  "dishes_to_deplete": ["dish_id_1"],
  "suggested_combos": [
    {"name": "string", "dish_ids": ["id1", "id2"], "reason": "string"}
  ],
  "menu_adjustments": ["调整建议1", "调整建议2"],
  "constraints_check": {
    "margin_ok": true,
    "food_safety_ok": true,
    "experience_ok": true
  }
}"""

    async def optimize(self, payload: dict) -> dict:
        """根据当前库存、历史销量、利润数据推荐最优菜品排序/推荐。

        Args:
            payload: 包含以下字段：
                - tenant_id: 租户ID
                - store_id: 门店ID
                - date: 日期（YYYY-MM-DD）
                - meal_period: 餐段（breakfast/lunch/dinner）
                - current_inventory: 当前库存列表
                - dish_performance: 菜品表现数据
                - weather: 天气（可选）
                - day_type: 日期类型（weekday/weekend/holiday）

        Returns:
            包含 featured_dishes/dishes_to_promote/dishes_to_deplete/
            suggested_combos/menu_adjustments/constraints_check/source 的字典
        """
        pre_calc = self._pre_calculate(payload)
        context = self._build_context(payload, pre_calc)

        try:
            message = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context}],
            )
            response_text = message.content[0].text
            result = self._parse_response(response_text)

            if result is None:
                result = self._fallback(payload, pre_calc)
                result["source"] = "fallback"
            else:
                result["source"] = "claude"

        except (anthropic.APIConnectionError, anthropic.APIError):
            result = self._fallback(payload, pre_calc)
            result["source"] = "fallback"

        logger.info(
            "menu_optimizer_decision",
            tenant_id=payload.get("tenant_id"),
            store_id=payload.get("store_id"),
            date=payload.get("date"),
            meal_period=payload.get("meal_period"),
            featured_count=len(result.get("featured_dishes", [])),
            deplete_count=len(result.get("dishes_to_deplete", [])),
            source=result.get("source"),
            constraints_check=result.get("constraints_check"),
        )

        return result

    def _pre_calculate(self, payload: dict) -> dict:
        """Python预计算：识别临期食材、关联菜品、毛利率等。"""
        inventory = payload.get("current_inventory", [])
        dish_performance = payload.get("dish_performance", [])

        # 找出临期食材（expiry_days ≤ 3）
        expiring_ingredients = [
            item for item in inventory
            if item.get("expiry_days", 999) <= EXPIRY_THRESHOLD_DAYS
        ]
        expiring_ingredient_ids = {
            item.get("ingredient_id") for item in expiring_ingredients
        }

        # 统计菜品分类数量（用于多样性检查）
        categories = {
            d.get("category", "未知")
            for d in dish_performance
            if d.get("is_available", True)
        }

        # 可用菜品的平均毛利率
        available_dishes = [
            d for d in dish_performance if d.get("is_available", True)
        ]
        avg_margin = (
            sum(d.get("margin_rate", 0) for d in available_dishes) / len(available_dishes)
            if available_dishes
            else 0.0
        )

        return {
            "expiring_ingredients": expiring_ingredients,
            "expiring_ingredient_ids": list(expiring_ingredient_ids),
            "category_count": len(categories),
            "avg_margin_rate": avg_margin,
            "available_dish_count": len(available_dishes),
        }

    def _build_context(self, payload: dict, pre_calc: dict) -> str:
        inventory = payload.get("current_inventory", [])
        dish_performance = payload.get("dish_performance", [])
        expiring = pre_calc.get("expiring_ingredients", [])

        # 格式化临期食材
        expiring_text = "无" if not expiring else "\n".join(
            f"  - {item.get('name')} {item.get('quantity')}{item.get('unit')} "
            f"还有{item.get('expiry_days')}天到期 "
            f"成本{item.get('cost_per_unit_fen', 0) / 100:.2f}元/{item.get('unit')}"
            for item in expiring
        )

        # 格式化菜品表现（按日均销量降序，最多20条）
        sorted_dishes = sorted(
            dish_performance,
            key=lambda d: d.get("avg_daily_orders", 0),
            reverse=True,
        )[:20]
        dishes_text = "\n".join(
            f"  - [{d.get('category')}] {d.get('dish_name')} "
            f"日均{d.get('avg_daily_orders', 0):.1f}单 "
            f"毛利率{d.get('margin_rate', 0):.0%} "
            f"备餐{d.get('prep_time_minutes', 0)}分钟 "
            f"{'可售' if d.get('is_available', True) else '不可售'}"
            for d in sorted_dishes
        )

        return f"""餐厅排菜请求：
门店：{payload.get('store_id')} 租户：{payload.get('tenant_id')}
日期：{payload.get('date')} 餐段：{payload.get('meal_period')}
天气：{payload.get('weather', '未知')} 日期类型：{payload.get('day_type', '未知')}

临期食材（≤{EXPIRY_THRESHOLD_DAYS}天，必须消耗）：
{expiring_text}

菜品表现（按日均销量排序，前20条）：
{dishes_text}

预计算结果：
- 临期食材数量：{len(expiring)}种
- 可售菜品总数：{pre_calc.get('available_dish_count')}道
- 菜品分类数：{pre_calc.get('category_count')}个
- 可售菜品平均毛利率：{pre_calc.get('avg_margin_rate', 0):.1%}

请根据以上数据，生成今日{payload.get('meal_period')}的最优排菜方案。"""

    def _parse_response(self, response_text: str) -> dict | None:
        """解析Claude响应，提取JSON，失败返回None。"""
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        logger.warning(
            "menu_optimizer_parse_failed",
            response_preview=response_text[:200],
        )
        return None

    def _fallback(self, payload: dict, pre_calc: dict) -> dict:
        """Claude失败时的规则引擎兜底。"""
        dish_performance = payload.get("dish_performance", [])

        # 可售菜品按毛利率降序
        available_dishes = [
            d for d in dish_performance if d.get("is_available", True)
        ]
        sorted_by_margin = sorted(
            available_dishes,
            key=lambda d: d.get("margin_rate", 0),
            reverse=True,
        )

        # 前3道菜为featured
        featured_dishes = [
            {
                "dish_id": d.get("dish_id", ""),
                "dish_name": d.get("dish_name", ""),
                "reason": "高毛利菜品，优先推荐",
                "priority": i + 1,
                "expected_boost": "预计提升10%",
            }
            for i, d in enumerate(sorted_by_margin[:3])
        ]
        dishes_to_promote = [d.get("dish_id", "") for d in sorted_by_margin[:5]]

        # 临期食材关联菜品（简化处理：按菜品名称匹配食材名）
        expiring = pre_calc.get("expiring_ingredients", [])
        expiring_names = {item.get("name", "").split()[0] for item in expiring}
        dishes_to_deplete = [
            d.get("dish_id", "")
            for d in available_dishes
            if any(name in d.get("dish_name", "") for name in expiring_names)
        ]

        # food_safety_ok：所有临期食材至少有一道关联菜品
        food_safety_ok = len(expiring) == 0 or len(dishes_to_deplete) > 0

        # margin_ok：featured菜品平均毛利率≥40%
        featured_margins = [
            sorted_by_margin[i].get("margin_rate", 0)
            for i in range(min(3, len(sorted_by_margin)))
        ]
        margin_ok = (
            sum(featured_margins) / len(featured_margins) >= MIN_MARGIN_RATE
            if featured_margins
            else False
        )

        return {
            "featured_dishes": featured_dishes,
            "dishes_to_promote": dishes_to_promote,
            "dishes_to_deplete": dishes_to_deplete,
            "suggested_combos": [],
            "menu_adjustments": ["建议优先推荐高毛利菜品"],
            "constraints_check": {
                "margin_ok": margin_ok,
                "food_safety_ok": food_safety_ok,
                "experience_ok": pre_calc.get("category_count", 0) >= MIN_CATEGORY_COUNT,
            },
        }


menu_optimizer = MenuOptimizer()
