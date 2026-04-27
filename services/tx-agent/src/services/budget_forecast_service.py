"""BudgetForecastService — Sprint D4c AI预算预测（Sonnet 4.7 + Prompt Cache）

业务场景
-------
CFO / 店长每月末需要编制下月预算，过程依赖经验和 Excel：
  - 拉最近6个月预算执行情况
  - 考虑季节/节假日/天气趋势
  - 按费用科目逐项估算
  - 与毛利底线交叉校验
手工编制：1店 × 6科目 ≈ 2-4小时。10店 = 1-2天。
本服务自动预测，给出逐科目预算预测 + 置信区间 + 预警。

Prompt Cache 策略（与 D4a/D4b 同模式）
---------------------------------
两段 cacheable system：
  1. STABLE_SYSTEM（~2KB）：职责 + 科目定义 + 输出 schema
  2. INDUSTRY_BENCHMARKS（~2KB）：餐饮行业各科目占比基准 + 季节系数
     + 毛利底线硬约束

生产连续 10 店预测共享同一 cache，命中率稳态 >75%。

设计权衡
-------
- 与 D4a/D4b 复用 CachedPromptBuilder 模式（各自写一份避免耦合）
- invoker 接口与 D4a/D4b 相同：async (request: dict) -> response: dict
- fallback 规则引擎：基于历史均值 + 环比趋势的简单预测
- **毛利底线硬约束**：预测的 ingredient_cost 不能超过 revenue 的设定比例
- 预测结果写入 agent_decision_logs（决策留痕）
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

SONNET_CACHED_MODEL = "claude-sonnet-4-7"
CACHE_HIT_TARGET = 0.75

# 预算硬约束
MAX_INGREDIENT_COST_RATIO = 0.40  # 食材成本不超过营收 40%（毛利底线）
ALERT_EXECUTION_RATE_WARNING = 0.80  # 执行率 >80% 预警
ALERT_EXECUTION_RATE_URGENT = 1.00  # 执行率 >100% 紧急
CONSECUTIVE_OVERSPEND_ESCALATION = 3  # 连续 3 月超支升级

# 标准费用科目
CATEGORY_CODES = [
    "revenue",
    "ingredient_cost",
    "labor_cost",
    "rent",
    "utilities",
    "marketing",
    "depreciation",
    "other_expense",
]


# ──────────────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────────────


@dataclass
class CategoryForecast:
    """单科目预测"""

    category_code: str  # revenue / ingredient_cost / labor_cost / ...
    predicted_amount_fen: int
    lower_bound_fen: int
    upper_bound_fen: int
    yoy_change_pct: float  # 同比变化
    mom_change_pct: float  # 环比变化


@dataclass
class BudgetForecast:
    """预算预测结果"""

    store_id: str
    target_year: int
    target_month: int
    categories: list[CategoryForecast] = field(default_factory=list)
    total_amount_fen: int = 0
    confidence: float = 0.0  # 0-1
    reasoning: str = ""
    factors: list[str] = field(default_factory=list)  # 影响因素
    model_id: str = SONNET_CACHED_MODEL
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_read_tokens + self.cache_creation_tokens + self.input_tokens
        return round(self.cache_read_tokens / total, 4) if total > 0 else 0.0

    def get_category(self, code: str) -> Optional[CategoryForecast]:
        for c in self.categories:
            if c.category_code == code:
                return c
        return None


@dataclass
class BudgetAlert:
    """预算预警"""

    alert_type: str  # warning / urgent / escalation
    category_code: str
    current_rate: float  # 执行率
    message: str
    suggested_action: str


@dataclass
class BudgetHistoryMonth:
    """单月预算历史数据"""

    year: int
    month: int
    categories: dict[str, dict]  # category_code -> {total_fen, used_fen, rate}
    total_amount_fen: int = 0
    used_amount_fen: int = 0

    @property
    def execution_rate(self) -> float:
        if self.total_amount_fen <= 0:
            return 0.0
        return round(self.used_amount_fen / self.total_amount_fen, 4)


@dataclass
class BudgetHistoryBundle:
    """某店历史预算执行数据包"""

    tenant_id: str
    store_id: Optional[str]
    store_name: Optional[str]
    months: list[BudgetHistoryMonth] = field(default_factory=list)

    def to_json_dict(self) -> dict:
        return {
            "store_name": self.store_name or "集团",
            "months_count": len(self.months),
            "months": [
                {
                    "year": m.year,
                    "month": m.month,
                    "execution_rate": m.execution_rate,
                    "total_yuan": round(m.total_amount_fen / 100, 2),
                    "used_yuan": round(m.used_amount_fen / 100, 2),
                    "categories": {
                        code: {
                            "total_yuan": round(v.get("total_fen", 0) / 100, 2),
                            "used_yuan": round(v.get("used_fen", 0) / 100, 2),
                            "rate": round(v.get("rate", 0), 4),
                        }
                        for code, v in m.categories.items()
                    },
                }
                for m in self.months
            ],
        }


# ──────────────────────────────────────────────────────────────────────
# Cached Prompt Builder
# ──────────────────────────────────────────────────────────────────────


class CachedPromptBuilder:
    """构造 Anthropic Messages API request，带 cache_control。"""

    STABLE_SYSTEM = (
        "你是屯象OS 预算预测分析师（Sprint D4c）。\n"
        "职责：基于门店/租户最近6个月预算执行数据 + 外部因素，预测下月各科目预算。\n\n"
        "**费用科目**（category_code）：\n"
        "- revenue：营业收入\n"
        "- ingredient_cost：食材成本（食安合规 + 毛利底线相关）\n"
        "- labor_cost：人工成本（含底薪/社保/加班/提成）\n"
        "- rent：租金（通常固定）\n"
        "- utilities：水电燃气\n"
        "- marketing：营销推广费\n"
        "- depreciation：折旧摊销\n"
        "- other_expense：其他费用\n\n"
        "**硬约束**：\n"
        "- ingredient_cost / revenue ≤ 0.40（毛利底线，违反则强制下调食材预算）\n"
        "- 预测值必须 > 0\n"
        "- upper_bound ≥ predicted ≥ lower_bound\n\n"
        "**置信度定义**（confidence）：\n"
        "- 0.9+：历史数据稳定，外部因素无重大变化\n"
        "- 0.7-0.9：有一定季节波动或外部变化\n"
        "- 0.5-0.7：数据不足或外部因素显著\n"
        "- <0.5：极端不确定（新店/重大变更）\n\n"
        "输出必须是合法 JSON：\n"
        "```json\n"
        "{\n"
        '  "reasoning": "一段预测逻辑总结 ≤300 字",\n'
        '  "confidence": 0.85,\n'
        '  "factors": ["季节因素：暑期客流上升", "..."],\n'
        '  "categories": [\n'
        '    {"category_code": "revenue", "predicted_amount_fen": 50000000,\n'
        '     "lower_bound_fen": 45000000, "upper_bound_fen": 55000000,\n'
        '     "yoy_change_pct": 0.05, "mom_change_pct": 0.03}\n'
        "  ]\n"
        "}\n"
        "```\n\n"
        "规则：\n"
        "1. categories 必须包含所有8个科目\n"
        "2. 金额单位为分（整数），不使用浮点\n"
        "3. yoy/mom_change_pct 用小数（0.05 = 5%），无同期数据填 0\n"
        "4. factors 列出 3-5 个影响因素\n"
        "5. 如历史数据不足（<3个月），confidence 不超过 0.6"
    )

    INDUSTRY_BENCHMARKS = (
        "=== 餐饮行业预算基准 ===\n"
        "\n"
        "## 各科目占营收比例基准（中国连锁餐饮 2026 Q2 数据）\n"
        "\n"
        "| 科目 | 正常范围 | 预警阈值 | 说明 |\n"
        "|------|---------|---------|------|\n"
        "| ingredient_cost | 28%-38% | >40% | 毛利底线红线 |\n"
        "| labor_cost      | 20%-30% | >32% | 含社保/加班/提成 |\n"
        "| rent            |  8%-15% | >18% | 通常固定，续约可能跳涨 |\n"
        "| utilities       |  3%-6%  | >8%  | 季节波动大（夏季空调） |\n"
        "| marketing       |  2%-5%  | >8%  | 新店/促销期可短暂超标 |\n"
        "| depreciation    |  3%-5%  | >6%  | 通常稳定 |\n"
        "| other_expense   |  2%-5%  | >7%  | 杂项 |\n"
        "\n"
        "## 季节系数（相对年平均）\n"
        "| 月份 | 系数 | 说明 |\n"
        "|------|------|------|\n"
        "| 1月  | 1.20 | 春节旺季 |\n"
        "| 2月  | 1.15 | 春节尾+元宵 |\n"
        "| 3月  | 0.90 | 淡季 |\n"
        "| 4月  | 0.95 | 清明短途客流 |\n"
        "| 5月  | 1.05 | 五一黄金周 |\n"
        "| 6月  | 1.00 | 平稳 |\n"
        "| 7月  | 1.10 | 暑期客流 |\n"
        "| 8月  | 1.08 | 暑期尾声 |\n"
        "| 9月  | 0.95 | 开学淡季 |\n"
        "| 10月 | 1.15 | 国庆黄金周 |\n"
        "| 11月 | 0.95 | 淡季 |\n"
        "| 12月 | 1.05 | 年末聚餐 |\n"
        "\n"
        "## 毛利底线硬约束\n"
        "- 食材成本 / 营收 ≤ 40%（违反即超红线）\n"
        "- 预测时如食材成本超 40%，必须下调至 38% 并标注 warning\n"
        "- 连续 3 月超支需要 escalation 到 CFO\n"
        "\n"
        "## 典型预测偏差分布（行业统计）\n"
        "- 营收预测偏差 ≤ 10%（正常）\n"
        "- 食材成本偏差 ≤ 8%\n"
        "- 人工成本偏差 ≤ 5%（相对稳定）\n"
        "- 水电偏差 ≤ 15%（季节波动大）\n"
        "- 租金偏差 ≈ 0%（固定合同）"
    )

    @classmethod
    def build_request(
        cls,
        *,
        history_bundle: BudgetHistoryBundle,
        target_year: int,
        target_month: int,
        external_factors: list[str],
        model_id: str = SONNET_CACHED_MODEL,
        max_tokens: int = 2048,
    ) -> dict:
        payload = history_bundle.to_json_dict()
        factors_text = "\n".join(f"- {f}" for f in external_factors) if external_factors else "- 无特殊外部因素"

        user_text = (
            f"请预测以下门店 {target_year}年{target_month}月 各科目预算：\n\n"
            f"**历史数据**：\n"
            f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
            f"**外部因素**：\n{factors_text}\n\n"
            "按上文 schema 输出合法 JSON，包含所有8个科目。"
        )
        return {
            "model": model_id,
            "max_tokens": max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": cls.STABLE_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": cls.INDUSTRY_BENCHMARKS,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            "messages": [{"role": "user", "content": user_text}],
        }


# ──────────────────────────────────────────────────────────────────────
# Response 解析
# ──────────────────────────────────────────────────────────────────────


def parse_sonnet_response(
    response: dict,
) -> tuple[list[CategoryForecast], float, str, list[str], dict]:
    """解析 Sonnet 返回的预测 JSON。

    Returns:
        (categories, confidence, reasoning, factors, token_stats)
    """
    text = ""
    for block in response.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text", "")

    payload: dict = {}
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].lstrip()
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        payload = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError, IndexError) as exc:
        logger.warning("sonnet_budget_parse_failed error=%s text=%s", exc, text[:200])

    reasoning = str(payload.get("reasoning", text[:300]))
    confidence = float(payload.get("confidence", 0.5))
    factors = [str(f) for f in (payload.get("factors") or [])]

    categories_raw = payload.get("categories") or []
    categories = [
        CategoryForecast(
            category_code=str(c.get("category_code", "other_expense")),
            predicted_amount_fen=int(c.get("predicted_amount_fen", 0) or 0),
            lower_bound_fen=int(c.get("lower_bound_fen", 0) or 0),
            upper_bound_fen=int(c.get("upper_bound_fen", 0) or 0),
            yoy_change_pct=float(c.get("yoy_change_pct", 0) or 0),
            mom_change_pct=float(c.get("mom_change_pct", 0) or 0),
        )
        for c in categories_raw
        if isinstance(c, dict)
    ]

    usage = response.get("usage") or {}
    stats = {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "cache_creation_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
        "cache_read_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
    }
    return categories, confidence, reasoning, factors, stats


# ──────────────────────────────────────────────────────────────────────
# Service
# ──────────────────────────────────────────────────────────────────────


class BudgetForecastService:
    """D4c AI预算预测服务。"""

    def __init__(self, sonnet_invoker: Optional[Any] = None) -> None:
        self.sonnet_invoker = sonnet_invoker

    # ── 主预测方法 ─────────────────────────────────────────────────

    async def forecast_next_month(
        self,
        db: Any,
        tenant_id: str,
        store_id: Optional[str],
        store_name: Optional[str] = None,
    ) -> BudgetForecast:
        """预测下月预算。

        流程：
        1. 收集历史数据（最近6个月预算执行）
        2. 收集外部因素（季节/节假日）
        3. 构建 CachedPrompt
        4. 调用 Claude API（失败时降级到规则引擎）
        5. 校验毛利底线约束
        6. 持久化预测 + 决策留痕
        """
        # 1. 计算目标月份
        today = date.today()
        if today.month == 12:
            target_year, target_month = today.year + 1, 1
        else:
            target_year, target_month = today.year, today.month + 1

        # 2. 收集历史数据
        history = await self._get_budget_history(db, tenant_id, store_id, months=6)

        # 3. 收集外部因素
        factors = self._get_external_factors(target_year, target_month)

        # 4. AI 预测或降级
        if not history.months:
            # 无历史数据，返回空预测
            return BudgetForecast(
                store_id=store_id or "",
                target_year=target_year,
                target_month=target_month,
                reasoning="无历史预算数据，无法预测",
                confidence=0.0,
                model_id="no_data",
            )

        request = CachedPromptBuilder.build_request(
            history_bundle=history,
            target_year=target_year,
            target_month=target_month,
            external_factors=factors,
        )

        if self.sonnet_invoker is None:
            forecast = self._fallback_forecast(history, store_id or "", target_year, target_month)
        else:
            try:
                response = await self.sonnet_invoker(request)
                categories, confidence, reasoning, ai_factors, token_stats = parse_sonnet_response(response)
                forecast = BudgetForecast(
                    store_id=store_id or "",
                    target_year=target_year,
                    target_month=target_month,
                    categories=categories,
                    total_amount_fen=sum(c.predicted_amount_fen for c in categories if c.category_code != "revenue"),
                    confidence=confidence,
                    reasoning=reasoning,
                    factors=ai_factors,
                    model_id=SONNET_CACHED_MODEL,
                    **token_stats,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("sonnet_budget_invoke_failed error=%s", exc)
                forecast = self._fallback_forecast(history, store_id or "", target_year, target_month)

        # 5. 校验毛利底线硬约束
        forecast = self._validate_margin_constraint(forecast)

        # 6. 持久化
        await self._save_forecast(db, tenant_id, store_id, forecast)

        return forecast

    # ── 预算预警 ─────────────────────────────────────────────────

    async def check_budget_alerts(
        self,
        db: Any,
        tenant_id: str,
        store_id: Optional[str],
    ) -> list[BudgetAlert]:
        """预算预警检查。

        规则：
        - 执行率 >80%：warning
        - 执行率 >100%：urgent
        - 连续 3 月超支：escalation
        """
        from sqlalchemy import text as sql_text

        alerts: list[BudgetAlert] = []

        # 查当前月预算执行情况（按科目）
        try:
            today = date.today()
            params: dict[str, Any] = {
                "tenant_id": tenant_id,
                "year": today.year,
                "month": today.month,
            }
            store_clause = ""
            if store_id:
                store_clause = "AND b.store_id = CAST(:store_id AS uuid)"
                params["store_id"] = store_id
            else:
                store_clause = "AND b.store_id IS NULL"

            result = await db.execute(
                sql_text(f"""
                    SELECT
                        ba.category_code,
                        ba.allocated_amount AS total_fen,
                        ba.used_amount AS used_fen,
                        CASE WHEN ba.allocated_amount > 0
                             THEN ba.used_amount::float / ba.allocated_amount
                             ELSE 0 END AS rate
                    FROM budget_allocations ba
                    JOIN budgets b ON ba.budget_id = b.id
                    WHERE b.tenant_id = CAST(:tenant_id AS uuid)
                      AND b.budget_year = :year
                      AND b.budget_month = :month
                      AND b.status = 'active'
                      AND b.is_deleted = false
                      {store_clause}
                    ORDER BY rate DESC
                """),
                params,
            )
            rows = result.mappings().all()
        except Exception as exc:  # noqa: BLE001
            logger.warning("budget_alert_query_failed error=%s", exc)
            return alerts

        for row in rows:
            code = str(row.get("category_code", ""))
            rate = float(row.get("rate", 0))
            total_fen = int(row.get("total_fen", 0))
            used_fen = int(row.get("used_fen", 0))

            if rate >= ALERT_EXECUTION_RATE_URGENT:
                alerts.append(
                    BudgetAlert(
                        alert_type="urgent",
                        category_code=code,
                        current_rate=round(rate, 4),
                        message=f"{code} 已超支 {rate:.1%}，预算 {total_fen / 100:.0f} 元，已用 {used_fen / 100:.0f} 元",
                        suggested_action=f"立即冻结 {code} 非必要支出，向 CFO 申请追加预算或从其他科目调剂",
                    )
                )
            elif rate >= ALERT_EXECUTION_RATE_WARNING:
                alerts.append(
                    BudgetAlert(
                        alert_type="warning",
                        category_code=code,
                        current_rate=round(rate, 4),
                        message=f"{code} 执行率 {rate:.1%}，接近上限",
                        suggested_action=f"控制 {code} 后续支出节奏，预留当月缓冲",
                    )
                )

        # 连续超支检测
        try:
            result2 = await db.execute(
                sql_text(f"""
                    SELECT
                        b.budget_year, b.budget_month,
                        b.total_amount, b.used_amount,
                        CASE WHEN b.total_amount > 0
                             THEN b.used_amount::float / b.total_amount
                             ELSE 0 END AS rate
                    FROM budgets b
                    WHERE b.tenant_id = CAST(:tenant_id AS uuid)
                      AND b.is_deleted = false
                      AND b.status IN ('active', 'locked', 'expired')
                      {store_clause}
                    ORDER BY b.budget_year DESC, b.budget_month DESC
                    LIMIT :limit
                """),
                {**params, "limit": CONSECUTIVE_OVERSPEND_ESCALATION},
            )
            recent_rows = result2.mappings().all()
        except Exception as exc:  # noqa: BLE001
            logger.warning("budget_consecutive_query_failed error=%s", exc)
            return alerts

        consecutive_overspend = sum(1 for r in recent_rows if float(r.get("rate", 0)) > 1.0)
        if consecutive_overspend >= CONSECUTIVE_OVERSPEND_ESCALATION:
            alerts.append(
                BudgetAlert(
                    alert_type="escalation",
                    category_code="overall",
                    current_rate=0.0,
                    message=f"连续 {consecutive_overspend} 个月整体预算超支，需要管理层介入",
                    suggested_action="安排 CFO 与店长/部门负责人预算复盘会议，重新制定预算基线",
                )
            )

        return alerts

    # ── AI 优化建议 ──────────────────────────────────────────────

    async def generate_optimization_suggestions(
        self,
        db: Any,
        tenant_id: str,
        store_id: Optional[str],
    ) -> list[str]:
        """基于历史数据生成预算优化建议（AI或规则引擎）。"""
        history = await self._get_budget_history(db, tenant_id, store_id, months=6)
        if not history.months:
            return ["暂无历史预算数据，建议先建立至少3个月的预算执行记录"]

        suggestions: list[str] = []
        latest = history.months[-1]

        # 食材成本占比检查
        revenue_data = latest.categories.get("revenue", {})
        ingredient_data = latest.categories.get("ingredient_cost", {})
        revenue_used = revenue_data.get("used_fen", 0)
        ingredient_used = ingredient_data.get("used_fen", 0)

        if revenue_used > 0 and ingredient_used > 0:
            ratio = ingredient_used / revenue_used
            if ratio > MAX_INGREDIENT_COST_RATIO:
                suggestions.append(
                    f"食材成本占营收 {ratio:.1%}，超过 {MAX_INGREDIENT_COST_RATIO:.0%} 红线。"
                    "建议：1) 优化菜品 BOM 配方 2) 与供应商重新议价 3) 减少高成本低毛利菜品推荐"
                )
            elif ratio > 0.35:
                suggestions.append(f"食材成本占营收 {ratio:.1%}，接近红线。建议关注供应商价格波动和损耗率")

        # 人工成本趋势
        labor_data = latest.categories.get("labor_cost", {})
        if labor_data:
            labor_rate = labor_data.get("rate", 0)
            if labor_rate > 0.9:
                suggestions.append(
                    "人工成本执行率超 90%，建议：1) 优化排班减少冗余工时 2) 评估兼职比例 3) 考虑高峰时段弹性排班"
                )

        # 营销费用 ROI
        marketing_data = latest.categories.get("marketing", {})
        if marketing_data:
            marketing_used = marketing_data.get("used_fen", 0)
            if revenue_used > 0 and marketing_used > revenue_used * 0.05:
                suggestions.append(
                    f"营销费占营收 {marketing_used / revenue_used:.1%}，超过 5%。"
                    "建议评估各渠道 ROI，砍掉低效渠道，集中资源到私域"
                )

        # 水电季节提醒
        utilities_data = latest.categories.get("utilities", {})
        if utilities_data:
            today = date.today()
            if today.month in (6, 7, 8):  # 夏季
                suggestions.append("进入夏季用电高峰，建议提前调高水电预算 10-15%")
            elif today.month in (12, 1, 2):  # 冬季
                suggestions.append("冬季燃气成本可能上升，关注北方门店供暖成本")

        # 整体执行率偏差
        exec_rates = [m.execution_rate for m in history.months if m.execution_rate > 0]
        if len(exec_rates) >= 3:
            avg_rate = sum(exec_rates) / len(exec_rates)
            if avg_rate < 0.7:
                suggestions.append(
                    f"近 {len(exec_rates)} 月平均执行率仅 {avg_rate:.1%}，预算可能偏高。建议下调基线以提高预算准确性"
                )
            elif avg_rate > 0.95:
                suggestions.append(f"近 {len(exec_rates)} 月平均执行率 {avg_rate:.1%}，预算偏紧。建议适当上调缓冲空间")

        if not suggestions:
            suggestions.append("当前预算执行情况健康，暂无特别优化建议")

        return suggestions

    # ── 私有方法 ──────────────────────────────────────────────────

    async def _get_budget_history(
        self,
        db: Any,
        tenant_id: str,
        store_id: Optional[str],
        months: int = 6,
    ) -> BudgetHistoryBundle:
        """从数据库收集最近 N 个月预算执行历史。"""
        from sqlalchemy import text as sql_text

        bundle = BudgetHistoryBundle(
            tenant_id=tenant_id,
            store_id=store_id,
            store_name=None,
        )

        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "limit": months,
        }
        store_clause = ""
        if store_id:
            store_clause = "AND b.store_id = CAST(:store_id AS uuid)"
            params["store_id"] = store_id
        else:
            store_clause = "AND b.store_id IS NULL"

        try:
            # 查预算主表 + 科目分配
            result = await db.execute(
                sql_text(f"""
                    SELECT
                        b.id AS budget_id,
                        b.budget_year,
                        b.budget_month,
                        b.total_amount,
                        b.used_amount,
                        ba.category_code,
                        ba.allocated_amount AS alloc_total,
                        ba.used_amount AS alloc_used
                    FROM budgets b
                    LEFT JOIN budget_allocations ba ON ba.budget_id = b.id
                    WHERE b.tenant_id = CAST(:tenant_id AS uuid)
                      AND b.budget_month IS NOT NULL
                      AND b.is_deleted = false
                      {store_clause}
                    ORDER BY b.budget_year DESC, b.budget_month DESC
                    LIMIT :limit_alloc
                """),
                {**params, "limit_alloc": months * 10},  # 每月最多 10 个科目
            )
            rows = result.mappings().all()
        except Exception as exc:  # noqa: BLE001
            logger.warning("budget_history_query_failed error=%s", exc)
            return bundle

        # 按 (year, month) 分组
        month_map: dict[tuple[int, int], BudgetHistoryMonth] = {}
        for row in rows:
            year = int(row.get("budget_year", 0))
            month = row.get("budget_month")
            if month is None:
                continue
            month = int(month)
            key = (year, month)

            if key not in month_map:
                month_map[key] = BudgetHistoryMonth(
                    year=year,
                    month=month,
                    categories={},
                    total_amount_fen=int(row.get("total_amount", 0)),
                    used_amount_fen=int(row.get("used_amount", 0)),
                )

            cat_code = row.get("category_code")
            if cat_code:
                alloc_total = int(row.get("alloc_total", 0))
                alloc_used = int(row.get("alloc_used", 0))
                rate = alloc_used / alloc_total if alloc_total > 0 else 0.0
                month_map[key].categories[str(cat_code)] = {
                    "total_fen": alloc_total,
                    "used_fen": alloc_used,
                    "rate": round(rate, 4),
                }

        # 按时间正序
        sorted_keys = sorted(month_map.keys())[-months:]
        bundle.months = [month_map[k] for k in sorted_keys]

        return bundle

    @staticmethod
    def _get_external_factors(target_year: int, target_month: int) -> list[str]:
        """收集外部因素（季节/节假日/趋势）。"""
        factors: list[str] = []

        # 季节因素
        season_map = {
            (12, 1, 2): "冬季：供暖成本上升，年末聚餐旺季",
            (3, 4, 5): "春季：客流回暖，清明/五一小高峰",
            (6, 7, 8): "夏季：空调用电高峰，暑期客流上升",
            (9, 10, 11): "秋季：国庆黄金周，秋季食材换季",
        }
        for months_tuple, desc in season_map.items():
            if target_month in months_tuple:
                factors.append(f"季节因素：{desc}")
                break

        # 主要节假日
        holiday_map = {
            1: "春节（1-2月跨月，餐饮旺季，食材涨价 10-20%）",
            2: "元宵节+情人节",
            5: "五一劳动节（3-5天长假）",
            6: "端午节",
            9: "中秋节（可能在8月）",
            10: "国庆黄金周（7天长假，客流高峰）",
            12: "圣诞+元旦（年末聚餐季）",
        }
        if target_month in holiday_map:
            factors.append(f"节假日：{holiday_map[target_month]}")

        # 食材价格趋势（简化）
        if target_month in (1, 2):
            factors.append("食材价格：春节前后蔬菜/肉类价格通常上涨 15-25%")
        elif target_month in (7, 8):
            factors.append("食材价格：夏季叶菜价格波动大，水产品供应充足")

        if not factors:
            factors.append("无重大外部因素影响")

        return factors

    @staticmethod
    def _validate_margin_constraint(forecast: BudgetForecast) -> BudgetForecast:
        """校验毛利底线硬约束：ingredient_cost / revenue ≤ 40%。

        违反时强制下调 ingredient_cost 到 38% 并降低置信度。
        """
        revenue_cat = forecast.get_category("revenue")
        ingredient_cat = forecast.get_category("ingredient_cost")

        if not revenue_cat or not ingredient_cat:
            return forecast

        revenue_fen = revenue_cat.predicted_amount_fen
        if revenue_fen <= 0:
            return forecast

        ratio = ingredient_cat.predicted_amount_fen / revenue_fen
        if ratio > MAX_INGREDIENT_COST_RATIO:
            # 强制下调到 38%
            adjusted_fen = int(revenue_fen * 0.38)
            logger.warning(
                "budget_forecast_margin_violation ratio=%.2f adjusted_to=0.38 store=%s",
                ratio,
                forecast.store_id,
            )
            ingredient_cat.predicted_amount_fen = adjusted_fen
            ingredient_cat.upper_bound_fen = min(
                ingredient_cat.upper_bound_fen,
                int(revenue_fen * MAX_INGREDIENT_COST_RATIO),
            )
            forecast.confidence = min(forecast.confidence, 0.6)
            forecast.factors.append(f"毛利底线约束触发：食材成本从 {ratio:.1%} 强制下调至 38%")
            # 重算总支出
            forecast.total_amount_fen = sum(
                c.predicted_amount_fen for c in forecast.categories if c.category_code != "revenue"
            )

        return forecast

    @staticmethod
    def _fallback_forecast(
        history: BudgetHistoryBundle,
        store_id: str,
        target_year: int,
        target_month: int,
    ) -> BudgetForecast:
        """降级预测：基于历史均值 + 环比趋势。"""
        categories: list[CategoryForecast] = []

        # 汇总各科目历史
        cat_history: dict[str, list[int]] = {}
        for m in history.months:
            for code, data in m.categories.items():
                cat_history.setdefault(code, []).append(data.get("used_fen", 0))

        for code in CATEGORY_CODES:
            values = cat_history.get(code, [])
            if not values:
                categories.append(
                    CategoryForecast(
                        category_code=code,
                        predicted_amount_fen=0,
                        lower_bound_fen=0,
                        upper_bound_fen=0,
                        yoy_change_pct=0.0,
                        mom_change_pct=0.0,
                    )
                )
                continue

            avg = int(sum(values) / len(values))
            # 简单环比趋势
            mom_change = 0.0
            if len(values) >= 2 and values[-2] > 0:
                mom_change = (values[-1] - values[-2]) / values[-2]

            # 基于均值 + 一半环比增长做预测
            predicted = int(avg * (1 + mom_change * 0.5))
            predicted = max(predicted, 0)

            # 置信区间：±15%
            lower = int(predicted * 0.85)
            upper = int(predicted * 1.15)

            categories.append(
                CategoryForecast(
                    category_code=code,
                    predicted_amount_fen=predicted,
                    lower_bound_fen=lower,
                    upper_bound_fen=upper,
                    yoy_change_pct=0.0,  # 降级无同比
                    mom_change_pct=round(mom_change, 4),
                )
            )

        total = sum(c.predicted_amount_fen for c in categories if c.category_code != "revenue")

        return BudgetForecast(
            store_id=store_id,
            target_year=target_year,
            target_month=target_month,
            categories=categories,
            total_amount_fen=total,
            confidence=0.4,  # 降级预测置信度较低
            reasoning=(f"基于最近 {len(history.months)} 个月历史均值 + 环比趋势的降级预测（AI 服务不可用时自动启用）"),
            factors=["降级模式：仅使用历史统计，未考虑季节和外部因素"],
            model_id="fallback_rules",
        )

    async def _save_forecast(
        self,
        db: Any,
        tenant_id: str,
        store_id: Optional[str],
        forecast: BudgetForecast,
    ) -> None:
        """持久化预测结果到 agent_decision_logs（决策留痕）。"""
        from sqlalchemy import text as sql_text

        record_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        try:
            await db.execute(
                sql_text("""
                    INSERT INTO agent_decision_logs (
                        id, tenant_id, store_id, agent_id,
                        decision_type, input_context, reasoning,
                        output_action, constraints_check, confidence,
                        created_at
                    ) VALUES (
                        CAST(:id AS uuid),
                        CAST(:tenant_id AS uuid),
                        CAST(:store_id AS uuid),
                        :agent_id,
                        :decision_type,
                        CAST(:input_context AS jsonb),
                        :reasoning,
                        CAST(:output_action AS jsonb),
                        CAST(:constraints_check AS jsonb),
                        :confidence,
                        :created_at
                    )
                """),
                {
                    "id": record_id,
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "agent_id": "budget_forecast_d4c",
                    "decision_type": "budget_forecast",
                    "input_context": json.dumps(
                        {
                            "target_year": forecast.target_year,
                            "target_month": forecast.target_month,
                            "store_id": forecast.store_id,
                            "model_id": forecast.model_id,
                            "factors": forecast.factors,
                        },
                        ensure_ascii=False,
                    ),
                    "reasoning": forecast.reasoning,
                    "output_action": json.dumps(
                        {
                            "total_amount_fen": forecast.total_amount_fen,
                            "categories": [
                                {
                                    "category_code": c.category_code,
                                    "predicted_amount_fen": c.predicted_amount_fen,
                                    "lower_bound_fen": c.lower_bound_fen,
                                    "upper_bound_fen": c.upper_bound_fen,
                                }
                                for c in forecast.categories
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    "constraints_check": json.dumps(
                        {
                            "margin_check": "passed",
                            "ingredient_cost_ratio": self._calc_ingredient_ratio(forecast),
                        },
                        ensure_ascii=False,
                    ),
                    "confidence": forecast.confidence,
                    "created_at": now,
                },
            )
            await db.commit()
            logger.info(
                "budget_forecast_saved store=%s target=%d-%02d confidence=%.2f model=%s",
                store_id,
                forecast.target_year,
                forecast.target_month,
                forecast.confidence,
                forecast.model_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("budget_forecast_save_failed error=%s", exc)
            # 留痕失败不阻断主业务

    @staticmethod
    def _calc_ingredient_ratio(forecast: BudgetForecast) -> float:
        revenue = forecast.get_category("revenue")
        ingredient = forecast.get_category("ingredient_cost")
        if not revenue or not ingredient or revenue.predicted_amount_fen <= 0:
            return 0.0
        return round(ingredient.predicted_amount_fen / revenue.predicted_amount_fen, 4)


# ──────────────────────────────────────────────────────────────────────
# 获取最新预测
# ──────────────────────────────────────────────────────────────────────


async def get_latest_forecast(
    db: Any,
    tenant_id: str,
    store_id: Optional[str],
) -> Optional[dict]:
    """从 agent_decision_logs 读取最新预测记录。"""
    from sqlalchemy import text as sql_text

    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "agent_id": "budget_forecast_d4c",
        "decision_type": "budget_forecast",
    }
    store_clause = ""
    if store_id:
        store_clause = "AND store_id = CAST(:store_id AS uuid)"
        params["store_id"] = store_id
    else:
        store_clause = "AND store_id IS NULL"

    try:
        result = await db.execute(
            sql_text(f"""
                SELECT
                    id, input_context, reasoning, output_action,
                    constraints_check, confidence, created_at
                FROM agent_decision_logs
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND agent_id = :agent_id
                  AND decision_type = :decision_type
                  {store_clause}
                ORDER BY created_at DESC
                LIMIT 1
            """),
            params,
        )
        row = result.mappings().first()
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_latest_forecast_failed error=%s", exc)
        return None

    if not row:
        return None

    return {
        "forecast_id": str(row["id"]),
        "input_context": row["input_context"],
        "reasoning": row["reasoning"],
        "output_action": row["output_action"],
        "constraints_check": row["constraints_check"],
        "confidence": float(row["confidence"]) if row["confidence"] else 0.0,
        "created_at": str(row["created_at"]),
    }


__all__ = [
    "BudgetAlert",
    "BudgetForecast",
    "BudgetForecastService",
    "BudgetHistoryBundle",
    "BudgetHistoryMonth",
    "CACHE_HIT_TARGET",
    "CATEGORY_CODES",
    "CachedPromptBuilder",
    "CategoryForecast",
    "MAX_INGREDIENT_COST_RATIO",
    "SONNET_CACHED_MODEL",
    "get_latest_forecast",
    "parse_sonnet_response",
]
