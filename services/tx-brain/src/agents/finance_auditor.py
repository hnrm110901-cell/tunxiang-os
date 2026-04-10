"""财务稽核Agent — 检测门店财务异常，保护经营健康

工作流程：
1. 接收门店财务快照（营收/成本/折扣/作废单/现金盘点）
2. Python预计算关键指标（毛利率/作废率/现金差异/折扣率）
3. 调用Claude进行深度异常模式识别
4. 记录决策日志（AgentDecisionLog）
5. 返回：风险评级 + 异常项列表 + 审计建议
"""
from __future__ import annotations

import json
import re

import anthropic
import structlog

from ..services.model_router import chat as model_chat

logger = structlog.get_logger()

# ─── 阈值常量 ──────────────────────────────────────────────────────
MARGIN_THRESHOLD = 0.65        # 成本率上限（cost/revenue > 65% 触发告警）
VOID_RATE_THRESHOLD = 0.05     # 作废率上限（void/total > 5% 触发告警）
CASH_DIFF_THRESHOLD_FEN = 10_000   # 现金差异阈值（100元=10000分）
DISCOUNT_RATE_THRESHOLD = 0.20  # 折扣率上限（discount/revenue > 20% 触发告警）

# Fallback 分级阈值
CASH_DIFF_CRITICAL_FEN = 50_000    # 现金差异 > 500元 → critical
VOID_RATE_CRITICAL = 0.10          # 作废率 > 10% → critical
DISCOUNT_RATE_HIGH = 0.25          # 折扣率 > 25% → high
MARGIN_HIGH = 0.65                 # 成本率 > 65% → high
MARGIN_MEDIUM = 0.55               # 成本率 > 55% → medium


class FinanceAuditor:
    """财务稽核Agent：检测门店财务异常，输出风险评级与审计建议

    三条硬约束校验：
    - 毛利达标：成本率不超过65%（margin_ok）
    - 作废率正常：作废单占比不超过5%（void_rate_ok）
    - 现金差异可控：实际现金与系统预期差异不超过100元（cash_diff_ok）
    """

    SYSTEM_PROMPT = """你是屯象OS的专业餐饮财务稽核专家。你的职责是分析门店每日财务数据，识别异常模式，保护经营健康。

三条不可突破的硬约束：
1. 毛利底线：成本率不可超过65%，否则存在成本管控失效风险
2. 食安合规：不分析此类问题
3. 客户体验：不分析此类问题

你需要识别以下财务异常：
- 异常折扣模式：折扣率过高、高折扣订单集中在特定时段/操作员
- 现金差异：实际盘点与系统预期差异异常，可能涉及收款问题
- 作废异常：作废单数量或金额异常，可能涉及操作规范或套现风险
- 成本偏高：毛利率偏低，可能涉及食材浪费、盗窃或BOM错误

返回严格的JSON格式（不要有任何其他文字）：
{
  "risk_level": "low|medium|high|critical",
  "score": 0-100,
  "anomalies": [
    {
      "type": "异常类型（如：cash_discrepancy/high_void_rate/margin_warning/abnormal_discount）",
      "description": "异常描述（中文，50字以内）",
      "severity": "info|warn|critical",
      "amount_fen": 金额（分，无金额填0）
    }
  ],
  "audit_suggestions": ["审计建议1", "审计建议2"],
  "constraints_check": {
    "margin_ok": true/false,
    "void_rate_ok": true/false,
    "cash_diff_ok": true/false
  }
}"""

    async def analyze(self, payload: dict) -> dict:
        """分析门店财务快照，输出风险评级与审计建议。

        Args:
            payload: 门店财务数据快照，包含以下字段：
                - tenant_id: 租户ID
                - store_id: 门店ID
                - date: 日期（YYYY-MM-DD）
                - revenue_fen: 当日营收（分）
                - cost_fen: 当日成本（分）
                - discount_total_fen: 当日折扣合计（分）
                - void_count: 当日作废单数
                - void_amount_fen: 当日作废金额（分）
                - cash_actual_fen: 实际现金盘点（分）
                - cash_expected_fen: 系统预期现金（分）
                - high_discount_orders: 高折扣订单列表

        Returns:
            包含 risk_level/score/anomalies/audit_suggestions/constraints_check/source 的字典
        """
        # Step 1: Python 预计算关键指标
        metrics = self._calc_metrics(payload)

        # Step 2: 构建 Claude 上下文
        context = self._build_context(payload, metrics)

        # Step 3: 调用 Claude 深度分析
        try:
            message = await model_chat(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context}],
                agent_id="finance_auditor",
                tenant_id=payload.get("tenant_id", "unknown"),
            )
            response_text = message.content[0].text
            result = self._parse_response(response_text)
            result["source"] = "claude"
        except anthropic.APIConnectionError as exc:
            logger.warning(
                "finance_auditor_connection_error",
                store_id=payload.get("store_id"),
                date=payload.get("date"),
                error=str(exc),
            )
            result = self._fallback_result(metrics)
            result["source"] = "fallback"
        except anthropic.APIError as exc:
            logger.warning(
                "finance_auditor_api_error",
                store_id=payload.get("store_id"),
                date=payload.get("date"),
                status_code=getattr(exc, "status_code", None),
                error=str(exc),
            )
            result = self._fallback_result(metrics)
            result["source"] = "fallback"

        # Step 4: 强制对齐 constraints_check（Python计算优先，确保准确性）
        result["constraints_check"] = {
            "margin_ok": metrics["margin_ok"],
            "void_rate_ok": metrics["void_rate_ok"],
            "cash_diff_ok": metrics["cash_diff_ok"],
        }

        # Step 5: 记录决策日志
        logger.info(
            "finance_auditor_decision",
            agent_id="finance_auditor",
            decision_type="daily_audit",
            tenant_id=payload.get("tenant_id"),
            store_id=payload.get("store_id"),
            date=payload.get("date"),
            risk_level=result.get("risk_level"),
            score=result.get("score"),
            source=result.get("source"),
            margin_rate=metrics["margin_rate"],
            void_rate=metrics["void_rate"],
            cash_diff_fen=metrics["cash_diff_fen"],
            discount_rate=metrics["discount_rate"],
            constraints_check=result["constraints_check"],
            anomaly_count=len(result.get("anomalies", [])),
        )

        return result

    def _calc_metrics(self, payload: dict) -> dict:
        """Python 预计算财务关键指标（传入 Claude prompt 前的结构化数据）。"""
        revenue = payload.get("revenue_fen", 0)
        cost = payload.get("cost_fen", 0)
        discount_total = payload.get("discount_total_fen", 0)
        void_count = payload.get("void_count", 0)
        void_amount = payload.get("void_amount_fen", 0)
        cash_actual = payload.get("cash_actual_fen", 0)
        cash_expected = payload.get("cash_expected_fen", 0)
        high_discount_orders = payload.get("high_discount_orders", [])

        # 毛利率（成本率）= cost / revenue
        margin_rate = (cost / revenue) if revenue > 0 else 0.0

        # 折扣率 = discount_total / revenue
        discount_rate = (discount_total / revenue) if revenue > 0 else 0.0

        # 作废率：用 void_count / (void_count + 估算正常单量) 近似
        # 实际应传入 total_order_count，此处用 void_count + 从revenue推算
        # 为兼容当前payload设计，使用 void_count / max(void_count + 1, 1) 保守估算
        # 若payload中有 total_order_count 字段则直接使用
        total_order_count = payload.get("total_order_count", 0)
        if total_order_count > 0:
            void_rate = void_count / total_order_count
        elif void_count > 0:
            # 无总单量时，用作废金额/平均客单价估算（兜底）
            avg_order_fen = revenue // max(1, (revenue // 5000)) if revenue > 0 else 5000
            estimated_total = max(void_count + (revenue // max(avg_order_fen, 1)), void_count)
            void_rate = void_count / max(estimated_total, 1)
        else:
            void_rate = 0.0

        # 现金差异（绝对值）
        cash_diff_fen = abs(cash_actual - cash_expected)

        # 三条硬约束校验
        margin_ok = margin_rate <= MARGIN_THRESHOLD
        void_rate_ok = void_rate <= VOID_RATE_THRESHOLD
        cash_diff_ok = cash_diff_fen <= CASH_DIFF_THRESHOLD_FEN

        return {
            "revenue_yuan": revenue / 100,
            "cost_yuan": cost / 100,
            "margin_rate": round(margin_rate, 4),
            "discount_rate": round(discount_rate, 4),
            "void_rate": round(void_rate, 4),
            "void_count": void_count,
            "void_amount_yuan": void_amount / 100,
            "cash_diff_fen": cash_diff_fen,
            "cash_diff_yuan": cash_diff_fen / 100,
            "cash_actual_yuan": cash_actual / 100,
            "cash_expected_yuan": cash_expected / 100,
            "high_discount_count": len(high_discount_orders),
            "margin_ok": margin_ok,
            "void_rate_ok": void_rate_ok,
            "cash_diff_ok": cash_diff_ok,
            # 触发告警标志
            "margin_alert": not margin_ok,
            "void_rate_alert": not void_rate_ok,
            "cash_diff_alert": not cash_diff_ok,
            "discount_alert": discount_rate > DISCOUNT_RATE_THRESHOLD,
        }

    def _build_context(self, payload: dict, metrics: dict) -> str:
        """构建发送给 Claude 的财务稽核上下文。"""
        high_discount_orders = payload.get("high_discount_orders", [])
        hdo_summary = self._format_high_discount_orders(high_discount_orders)

        alerts = []
        if metrics["margin_alert"]:
            alerts.append(f"⚠️ 成本率偏高：{metrics['margin_rate']:.1%}（阈值{MARGIN_THRESHOLD:.0%}）")
        if metrics["void_rate_alert"]:
            alerts.append(f"⚠️ 作废率偏高：{metrics['void_rate']:.1%}（阈值{VOID_RATE_THRESHOLD:.0%}）")
        if metrics["cash_diff_alert"]:
            alerts.append(f"⚠️ 现金差异异常：¥{metrics['cash_diff_yuan']:.2f}（阈值¥{CASH_DIFF_THRESHOLD_FEN / 100:.0f}）")
        if metrics["discount_alert"]:
            alerts.append(f"⚠️ 折扣率偏高：{metrics['discount_rate']:.1%}（阈值{DISCOUNT_RATE_THRESHOLD:.0%}）")

        alert_text = "\n".join(alerts) if alerts else "无预警触发"

        return f"""门店财务日报稽核请求：
门店：{payload.get('store_id')}  日期：{payload.get('date')}

【核心财务指标】
- 当日营收：¥{metrics['revenue_yuan']:.2f}
- 当日成本：¥{metrics['cost_yuan']:.2f}（成本率：{metrics['margin_rate']:.1%}）
- 当日折扣合计：¥{payload.get('discount_total_fen', 0) / 100:.2f}（折扣率：{metrics['discount_rate']:.1%}）
- 作废单：{metrics['void_count']}笔，金额：¥{metrics['void_amount_yuan']:.2f}（作废率：{metrics['void_rate']:.1%}）
- 现金盘点：实际¥{metrics['cash_actual_yuan']:.2f} / 系统预期¥{metrics['cash_expected_yuan']:.2f}（差异：¥{metrics['cash_diff_yuan']:.2f}）

【规则引擎预警】
{alert_text}

【三条硬约束校验（Python预计算）】
- 毛利达标（成本率≤65%）：{'✅ 达标' if metrics['margin_ok'] else '❌ 未达标'}
- 作废率正常（≤5%）：{'✅ 正常' if metrics['void_rate_ok'] else '❌ 异常'}
- 现金差异可控（≤¥100）：{'✅ 可控' if metrics['cash_diff_ok'] else '❌ 超阈值'}

【高折扣订单明细（共{metrics['high_discount_count']}笔）】
{hdo_summary}

请基于以上数据进行深度财务稽核分析，识别所有异常模式，输出JSON格式结果。"""

    def _format_high_discount_orders(self, orders: list[dict]) -> str:
        if not orders:
            return "无高折扣订单"
        lines = []
        for o in orders[:10]:  # 最多展示10笔
            lines.append(
                f"  - 订单{o.get('order_id', 'N/A')} "
                f"操作员:{o.get('operator_id', 'N/A')} "
                f"折扣率:{o.get('discount_rate', 'N/A')} "
                f"金额:¥{o.get('amount_fen', 0) / 100:.2f} "
                f"时间:{o.get('created_at', 'N/A')}"
            )
        if len(orders) > 10:
            lines.append(f"  ... 还有 {len(orders) - 10} 笔未展示")
        return "\n".join(lines)

    def _parse_response(self, response_text: str) -> dict:
        """解析 Claude 响应，提取 JSON，失败时返回 fallback 结果。"""
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        logger.warning(
            "finance_auditor_parse_failed",
            response_preview=response_text[:200],
        )
        # JSON 解析失败时返回保守的 fallback（不抛出异常）
        return {
            "risk_level": "medium",
            "score": 50.0,
            "anomalies": [
                {
                    "type": "parse_error",
                    "description": "AI响应解析失败，需人工审核",
                    "severity": "warn",
                    "amount_fen": 0,
                }
            ],
            "audit_suggestions": ["AI分析结果解析异常，请人工审核当日财务数据"],
            "constraints_check": {
                "margin_ok": None,
                "void_rate_ok": None,
                "cash_diff_ok": None,
            },
        }

    def _fallback_result(self, metrics: dict) -> dict:
        """Claude 调用失败时，纯Python规则计算风险等级（兜底逻辑）。"""
        cash_diff_fen = metrics["cash_diff_fen"]
        void_rate = metrics["void_rate"]
        margin_rate = metrics["margin_rate"]
        discount_rate = metrics["discount_rate"]

        anomalies = []

        # 确定风险等级
        if cash_diff_fen > CASH_DIFF_CRITICAL_FEN or void_rate > VOID_RATE_CRITICAL:
            risk_level = "critical"
            score = 90.0
        elif margin_rate > MARGIN_HIGH or discount_rate > DISCOUNT_RATE_HIGH:
            risk_level = "high"
            score = 75.0
        elif margin_rate > MARGIN_MEDIUM or cash_diff_fen > CASH_DIFF_THRESHOLD_FEN:
            risk_level = "medium"
            score = 55.0
        else:
            risk_level = "low"
            score = 20.0

        # 生成异常项
        if not metrics["margin_ok"]:
            anomalies.append({
                "type": "margin_warning",
                "description": f"成本率偏高：{metrics['margin_rate']:.1%}，超过65%阈值",
                "severity": "critical" if margin_rate > 0.75 else "warn",
                "amount_fen": 0,
            })

        if not metrics["void_rate_ok"]:
            anomalies.append({
                "type": "high_void_rate",
                "description": f"作废率偏高：{metrics['void_rate']:.1%}，超过5%阈值",
                "severity": "critical" if void_rate > VOID_RATE_CRITICAL else "warn",
                "amount_fen": int(metrics["void_amount_yuan"] * 100),
            })

        if not metrics["cash_diff_ok"]:
            anomalies.append({
                "type": "cash_discrepancy",
                "description": f"现金差异异常：¥{metrics['cash_diff_yuan']:.2f}，超过¥100阈值",
                "severity": "critical" if cash_diff_fen > CASH_DIFF_CRITICAL_FEN else "warn",
                "amount_fen": cash_diff_fen,
            })

        if metrics["discount_alert"]:
            anomalies.append({
                "type": "abnormal_discount",
                "description": f"折扣率偏高：{metrics['discount_rate']:.1%}，超过20%阈值",
                "severity": "warn",
                "amount_fen": 0,
            })

        # 生成审计建议
        suggestions = []
        if not metrics["margin_ok"]:
            suggestions.append("建议核查食材采购价格及损耗记录，排查BOM配方是否准确")
        if not metrics["void_rate_ok"]:
            suggestions.append("建议调取作废订单明细，核查操作员操作记录及授权情况")
        if not metrics["cash_diff_ok"]:
            suggestions.append("建议立即进行现金盘点复核，对照收款记录逐笔核查差异原因")
        if metrics["discount_alert"]:
            suggestions.append("建议审查高折扣订单的审批记录，确认是否符合折扣授权规范")
        if not suggestions:
            suggestions.append("当日财务数据正常，无需特别关注")

        return {
            "risk_level": risk_level,
            "score": score,
            "anomalies": anomalies,
            "audit_suggestions": suggestions,
            "constraints_check": {
                "margin_ok": metrics["margin_ok"],
                "void_rate_ok": metrics["void_rate_ok"],
                "cash_diff_ok": metrics["cash_diff_ok"],
            },
        }


    async def analyze_from_mv(self, tenant_id: str, store_id: str | None = None) -> dict:
        """从 mv_store_pnl + mv_channel_margin 快速读取财务健康数据，<5ms，无 Claude 调用。

        数据来源：因果链④投影视图（StorePnlProjector）+ 因果链②（ChannelMarginProjector）
        返回：P&L摘要 + 渠道毛利分布 + 风险信号
        """
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError
        from shared.ontology.src.database import get_db

        try:
            async for db in get_db():
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(tenant_id)},
                )
                params: dict = {"tenant_id": tenant_id}
                store_clause = ""
                if store_id:
                    store_clause = "AND store_id = :store_id"
                    params["store_id"] = store_id

                # 查询最新 P&L
                pnl_result = await db.execute(
                    text(f"""
                        SELECT
                            store_id,
                            stat_date,
                            gross_revenue_fen,
                            net_revenue_fen,
                            cogs_fen,
                            gross_profit_fen,
                            gross_margin_rate,
                            labor_cost_fen,
                            net_profit_fen,
                            order_count,
                            avg_check_fen
                        FROM mv_store_pnl
                        WHERE tenant_id = :tenant_id
                        {store_clause}
                        ORDER BY stat_date DESC
                        LIMIT 1
                    """),
                    params,
                )
                pnl_row = pnl_result.mappings().one_or_none()

                # 查询渠道毛利（最新日期）
                channel_result = await db.execute(
                    text(f"""
                        SELECT
                            channel,
                            gross_margin_rate,
                            net_revenue_fen,
                            order_count
                        FROM mv_channel_margin
                        WHERE tenant_id = :tenant_id
                        {store_clause}
                        AND stat_date = (
                            SELECT MAX(stat_date) FROM mv_channel_margin
                            WHERE tenant_id = :tenant_id {store_clause}
                        )
                        ORDER BY net_revenue_fen DESC
                    """),
                    params,
                )
                channel_rows = channel_result.mappings().all()

                pnl_data: dict = {}
                risk_signal = "normal"
                if pnl_row:
                    pnl_data = dict(pnl_row._mapping)
                    gm = pnl_data.get("gross_margin_rate")
                    if gm is not None:
                        pnl_data["gross_margin_rate"] = float(gm)
                        # 毛利率 < 35% 触发风险
                        if float(gm) < 0.35:
                            risk_signal = "high"
                        elif float(gm) < 0.45:
                            risk_signal = "medium"

                channels = []
                for r in channel_rows:
                    ch = dict(r._mapping)
                    if ch.get("gross_margin_rate") is not None:
                        ch["gross_margin_rate"] = float(ch["gross_margin_rate"])
                    channels.append(ch)

                return {
                    "inference_layer": "mv_fast_path",
                    "data": {
                        "pnl": pnl_data,
                        "channel_margins": channels,
                    },
                    "agent": self.__class__.__name__,
                    "risk_signal": risk_signal,
                }
        except SQLAlchemyError as exc:
            logger.warning(
                "finance_auditor_mv_db_error",
                tenant_id=tenant_id,
                store_id=store_id,
                error=str(exc),
            )
            return {
                "inference_layer": "mv_fast_path_error",
                "data": {},
                "agent": self.__class__.__name__,
                "error": "数据库查询失败，请使用实时分析",
            }


finance_auditor = FinanceAuditor()
