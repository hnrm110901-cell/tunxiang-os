"""能耗监控Agent — Phase 3 物化视图集成

工作流程：
1. analyze_from_mv()（快速路径）：从 mv_energy_efficiency 读取，<5ms
2. 无数据或 DB 异常时 fallback 到 analyze()（Claude Haiku 推理）

mv_energy_efficiency 字段：
  tenant_id, store_id, stat_date,
  electricity_kwh, gas_m3, water_ton,
  energy_cost_fen, revenue_fen,
  energy_revenue_ratio, anomaly_count,
  off_hours_anomalies, last_event_id, updated_at
"""
from __future__ import annotations

import json
import re
from datetime import date

import anthropic
import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..services.model_router import chat as model_chat

logger = structlog.get_logger()

# 能耗效率评级阈值
RATIO_EXCELLENT = 0.05   # ≤5% — 优秀
RATIO_GOOD = 0.08        # ≤8% — 良好
RATIO_WARNING = 0.12     # ≤12% — 警告；>12% — 超标


class EnergyMonitorAgent:
    """能耗监控Agent：分析门店能耗效率，识别异常，给出节能建议

    三条硬约束校验：
    - 食安合规：不影响（能耗与食安无直接关联）
    - 毛利底线：节能措施不能影响正常营业和出品质量
    - 客户体验：节能不能以牺牲顾客体验为代价（如空调温度）
    """

    SYSTEM_PROMPT = """你是屯象OS的能耗监控智能体。你的职责是分析餐厅的能耗数据，识别异常消耗，给出具体可行的节能建议。

分析维度：
1. 能耗/营收比（energy_revenue_ratio）：衡量经营效率的核心指标
   - ≤5%：优秀
   - 5%-8%：良好
   - 8%-12%：警告，需关注
   - >12%：超标，需立即干预

2. 异常检测（anomaly_count + off_hours_anomalies）：
   - 非营业时段能耗异常往往意味着设备未关闭或存在安全隐患
   - 突增可能意味着设备故障

3. 分项能耗（电/气/水）：根据餐厅类型判断各项是否合理

返回严格的JSON格式（无其他文字）：
{
  "efficiency_level": "优秀|良好|警告|超标",
  "anomaly_summary": "异常摘要（不超过50字）",
  "top_issues": ["问题1", "问题2"],
  "action_items": [
    {"priority": "high|medium|low", "action": "具体行动（不超过60字）"}
  ],
  "estimated_saving_pct": 0.05,
  "constraints_check": {
    "margin_ok": true,
    "food_safety_ok": true,
    "experience_ok": true
  }
}"""

    async def analyze(self, payload: dict) -> dict:
        """分析能耗数据（标准路径，调用 Claude Haiku）。

        Args:
            payload: 能耗数据，包含以下字段：
                - tenant_id: 租户ID
                - store_id: 门店ID
                - stat_date: 统计日期（YYYY-MM-DD 或 date 对象）
                - electricity_kwh: 当日用电量（kWh）
                - gas_m3: 当日用气量（m³）
                - water_ton: 当日用水量（吨）
                - energy_cost_fen: 能耗总费用（分）
                - revenue_fen: 当日营业收入（分）
                - energy_revenue_ratio: 能耗/营收比
                - anomaly_count: 异常次数
                - off_hours_anomalies: 非营业时段异常列表（JSON）

        Returns:
            包含 efficiency_level/anomaly_summary/top_issues/action_items/
            estimated_saving_pct/constraints_check/source 的字典
        """
        tenant_id = payload.get("tenant_id", "")
        store_id = payload.get("store_id", "")

        # Python 预计算效率等级
        ratio = float(payload.get("energy_revenue_ratio") or 0)
        efficiency_level = self._calc_efficiency_level(ratio)
        anomaly_count = int(payload.get("anomaly_count") or 0)

        # 无异常且能耗优秀，无需调用 Claude
        if anomaly_count == 0 and efficiency_level == "优秀":
            result = self._build_simple_result(payload, efficiency_level, source="fallback")
            self._log_decision(tenant_id, store_id, ratio, anomaly_count, result)
            return result

        context = self._build_context(payload, efficiency_level)

        try:
            message = await model_chat(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context}],
                agent_id="energy_monitor",
                tenant_id=tenant_id,
            )
            response_text = message.content[0].text
            parsed = self._parse_response(response_text)

            if parsed is not None:
                parsed["source"] = "claude"
                result = parsed
            else:
                result = self._fallback_result(payload, efficiency_level)

        except (anthropic.APIConnectionError, anthropic.APIError) as exc:
            logger.warning(
                "energy_monitor_claude_error",
                store_id=store_id,
                error=str(exc),
            )
            result = self._fallback_result(payload, efficiency_level)

        self._log_decision(tenant_id, store_id, ratio, anomaly_count, result)
        return result

    async def analyze_from_mv(self, tenant_id: str, store_id: str | None = None) -> dict:
        """Phase 3 快速路径：从 mv_energy_efficiency 读取，<5ms。

        字段：tenant_id, store_id, stat_date,
              electricity_kwh, gas_m3, water_ton,
              energy_cost_fen, revenue_fen,
              energy_revenue_ratio, anomaly_count,
              off_hours_anomalies, last_event_id, updated_at

        无数据时 fallback 到 analyze()；DB 异常也 graceful fallback。
        """
        from ..db import get_db  # 延迟导入避免循环依赖

        try:
            async with get_db() as db:
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tenant_id},
                )

                params: dict = {"tid": tenant_id}
                store_clause = ""
                if store_id:
                    store_clause = "AND store_id = :sid"
                    params["sid"] = store_id

                result = await db.execute(
                    text(f"""
                        SELECT tenant_id, store_id, stat_date,
                               electricity_kwh, gas_m3, water_ton,
                               energy_cost_fen, revenue_fen,
                               energy_revenue_ratio, anomaly_count,
                               off_hours_anomalies, updated_at
                        FROM mv_energy_efficiency
                        WHERE tenant_id = :tid {store_clause}
                        ORDER BY stat_date DESC
                        LIMIT 1
                    """),
                    params,
                )

                row = result.fetchone()
                if not row:
                    logger.info(
                        "energy_monitor_mv_empty_fallback",
                        tenant_id=tenant_id,
                        store_id=store_id,
                    )
                    return await self.analyze(
                        {"tenant_id": tenant_id, "store_id": store_id}
                    )

                return {
                    "inference_layer": "mv_fast_path",
                    "data": dict(row._mapping),
                    "agent": self.__class__.__name__,
                }

        except SQLAlchemyError as exc:
            logger.warning(
                "energy_monitor_mv_db_error",
                tenant_id=tenant_id,
                store_id=store_id,
                error=str(exc),
            )
            return await self.analyze(
                {"tenant_id": tenant_id, "store_id": store_id}
            )

    # ─── 内部辅助方法 ──────────────────────────────────────────────────────────

    @staticmethod
    def _calc_efficiency_level(ratio: float) -> str:
        if ratio <= RATIO_EXCELLENT:
            return "优秀"
        if ratio <= RATIO_GOOD:
            return "良好"
        if ratio <= RATIO_WARNING:
            return "警告"
        return "超标"

    def _build_context(self, payload: dict, efficiency_level: str) -> str:
        store_id = payload.get("store_id", "")
        stat_date = payload.get("stat_date", date.today().isoformat())
        electricity_kwh = payload.get("electricity_kwh", 0)
        gas_m3 = payload.get("gas_m3", 0)
        water_ton = payload.get("water_ton", 0)
        energy_cost_fen = int(payload.get("energy_cost_fen") or 0)
        revenue_fen = int(payload.get("revenue_fen") or 0)
        ratio = float(payload.get("energy_revenue_ratio") or 0)
        anomaly_count = int(payload.get("anomaly_count") or 0)

        off_hours = payload.get("off_hours_anomalies", [])
        if isinstance(off_hours, str):
            try:
                off_hours = json.loads(off_hours)
            except (json.JSONDecodeError, ValueError):
                off_hours = []

        off_hours_lines = (
            "\n".join(f"  - {a}" for a in off_hours[:5])
            if off_hours
            else "  无非营业时段异常"
        )

        return f"""门店能耗分析请求：

基本信息：
- 门店ID：{store_id}
- 统计日期：{stat_date}
- 效率等级（系统预判）：{efficiency_level}

分项能耗：
- 用电量：{electricity_kwh} kWh
- 用气量：{gas_m3} m³
- 用水量：{water_ton} 吨
- 能耗总费用：{energy_cost_fen / 100:.2f} 元
- 当日营业收入：{revenue_fen / 100:.2f} 元
- 能耗/营收比：{ratio:.2%}

异常信息：
- 异常总次数：{anomaly_count}
- 非营业时段异常明细：
{off_hours_lines}

请分析以上能耗数据，识别主要问题，给出优先级排序的节能行动建议。"""

    def _parse_response(self, response_text: str) -> dict | None:
        """解析 Claude 响应，提取 JSON。失败返回 None 触发 fallback。"""
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        logger.warning(
            "energy_monitor_parse_failed",
            response_preview=response_text[:200],
        )
        return None

    def _build_simple_result(self, payload: dict, efficiency_level: str, source: str) -> dict:
        """无异常时的简洁返回（跳过 Claude 调用）。"""
        return {
            "efficiency_level": efficiency_level,
            "anomaly_summary": "本日能耗正常，无异常记录",
            "top_issues": [],
            "action_items": [],
            "estimated_saving_pct": 0.0,
            "constraints_check": {
                "margin_ok": True,
                "food_safety_ok": True,
                "experience_ok": True,
            },
            "source": source,
        }

    def _fallback_result(self, payload: dict, efficiency_level: str) -> dict:
        """Claude 失败时的纯规则兜底。"""
        ratio = float(payload.get("energy_revenue_ratio") or 0)
        anomaly_count = int(payload.get("anomaly_count") or 0)

        off_hours = payload.get("off_hours_anomalies", [])
        if isinstance(off_hours, str):
            try:
                off_hours = json.loads(off_hours)
            except (json.JSONDecodeError, ValueError):
                off_hours = []

        top_issues = []
        action_items = []

        if ratio > RATIO_WARNING:
            top_issues.append(f"能耗/营收比 {ratio:.1%} 严重超标，需立即排查")
            action_items.append({"priority": "high", "action": "立即排查高耗能设备，关闭非必要电源"})
        elif ratio > RATIO_GOOD:
            top_issues.append(f"能耗/营收比 {ratio:.1%} 超过良好阈值，建议优化")
            action_items.append({"priority": "medium", "action": "检查空调、冰柜等主要用电设备运行状态"})

        if anomaly_count > 0:
            top_issues.append(f"发现 {anomaly_count} 次能耗异常")
            action_items.append({"priority": "high", "action": f"排查 {anomaly_count} 次异常读数，确认是否设备故障"})

        if off_hours:
            top_issues.append(f"非营业时段有 {len(off_hours)} 次异常，可能存在设备未关闭")
            action_items.append({"priority": "medium", "action": "检查非营业时段设备关闭流程，制定下班前检查清单"})

        if not top_issues:
            top_issues.append("能耗整体正常，持续关注趋势变化")

        return {
            "efficiency_level": efficiency_level,
            "anomaly_summary": "、".join(top_issues[:2]) if top_issues else "能耗正常",
            "top_issues": top_issues,
            "action_items": action_items,
            "estimated_saving_pct": max(0.0, round(ratio - RATIO_GOOD, 3)) if ratio > RATIO_GOOD else 0.0,
            "constraints_check": {
                "margin_ok": True,
                "food_safety_ok": True,
                "experience_ok": True,
            },
            "source": "fallback",
        }

    def _log_decision(
        self,
        tenant_id: str,
        store_id: str | None,
        ratio: float,
        anomaly_count: int,
        result: dict,
    ) -> None:
        """记录决策留痕。"""
        logger.info(
            "energy_monitor_decision",
            tenant_id=tenant_id,
            store_id=store_id,
            energy_revenue_ratio=ratio,
            anomaly_count=anomaly_count,
            efficiency_level=result.get("efficiency_level"),
            source=result.get("source"),
        )


energy_monitor = EnergyMonitorAgent()
