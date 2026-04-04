"""巡店质检Agent — 分析门店巡检数据，自动识别违规项，生成整改建议

工作流程：
1. Python预计算业务规则（食安/消防/综合评分）
2. 调用Claude Haiku分析检查清单，识别违规，生成整改建议
3. Claude失败时降级为纯Python规则兜底
4. 结构化返回风险等级、违规明细、整改建议
"""
from __future__ import annotations

import json
import re

import anthropic
import structlog

logger = structlog.get_logger()
client = anthropic.AsyncAnthropic()  # 从环境变量 ANTHROPIC_API_KEY 读取

# 各类别中文名
CATEGORY_FOOD_SAFETY = "食安"
CATEGORY_FIRE_SAFETY = "消防"
CATEGORY_HYGIENE = "卫生"

# 整改期限（天）
DEADLINE_CRITICAL = 1
DEADLINE_MAJOR = 3
DEADLINE_MINOR = 7

# 评分阈值
SCORE_CRITICAL = 60.0
SCORE_HIGH = 75.0
SCORE_DECLINE_THRESHOLD = 10.0

# 卫生通过率阈值
HYGIENE_PASS_RATE_MIN = 0.8


class PatrolInspector:
    """巡店质检Agent：分析门店巡检数据，自动识别违规，生成整改建议

    关键业务规则（Python预计算后传给Claude）：
    - 食安类有任何fail → auto_alert_required=True，risk_level至少为high
    - 消防类有任何fail → auto_alert_required=True，critical违规
    - overall_score < 60 → risk_level=critical
    - overall_score < 75 → risk_level=high
    - 与上次相比下降>10分 → score_trend=declining，触发预警
    """

    SYSTEM_PROMPT = """你是专业餐饮连锁巡店督导专家。分析门店巡检清单，识别违规项，给出具体整改建议。

核心规则：
- 食安类（category=="食安"）违规：必须标记为critical级别，整改期限1天
- 消防类（category=="消防"）违规：必须标记为critical级别，整改期限1天
- 卫生类违规：根据严重程度标记为major或minor
- 服务/设备类违规：根据实际情况判断

返回JSON（仅JSON，不含其他文字）：
{
  "violations": [
    {
      "category": "类别名",
      "item": "检查项名称",
      "severity": "minor|major|critical",
      "description": "违规具体描述（不超过50字）",
      "required_action": "整改行动建议（具体可执行，不超过60字）",
      "deadline_days": 1
    }
  ],
  "improvement_suggestions": [
    "整体改进建议1（不超过50字）",
    "整体改进建议2"
  ]
}

注意：
- violations只包含result=="fail"的项目
- improvement_suggestions聚焦系统性问题，不重复列举单项违规
- 建议具体可落地，避免泛泛而谈"""

    async def analyze(self, payload: dict) -> dict:
        """分析巡店检查数据。

        Args:
            payload: 巡店数据，包含以下字段：
                - tenant_id: 租户ID
                - store_id: 门店ID
                - patrol_date: 巡检日期（YYYY-MM-DD）
                - inspector_name: 巡检员姓名
                - checklist_items: 检查清单列表
                - overall_score: 本次综合评分（0-100）
                - previous_score: 上次综合评分（对比用）

        Returns:
            包含 risk_level/violations/improvement_suggestions/score_trend/
            constraints_check/auto_alert_required/source 的字典
        """
        tenant_id = payload.get("tenant_id", "")
        store_id = payload.get("store_id", "")
        overall_score = float(payload.get("overall_score", 100.0))
        previous_score = float(payload.get("previous_score", overall_score))
        checklist_items = payload.get("checklist_items", [])

        # Python预计算业务规则
        pre_calc = self._pre_calculate(checklist_items, overall_score, previous_score)

        # 调用Claude Haiku分析
        fail_items = [item for item in checklist_items if item.get("result") == "fail"]

        if not fail_items:
            # 无违规项，无需调用Claude
            logger.info(
                "patrol_inspector_no_violations",
                store_id=store_id,
                tenant_id=tenant_id,
                overall_score=overall_score,
            )
            result = self._build_result(
                violations=[],
                improvement_suggestions=["本次巡检无违规项，继续保持良好状态"],
                pre_calc=pre_calc,
                source="fallback",
            )
            self._log_decision(tenant_id, store_id, overall_score, result)
            return result

        context = self._build_context(payload, pre_calc, fail_items)

        try:
            message = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context}],
            )
            response_text = message.content[0].text
            claude_result = self._parse_claude_response(response_text)

            if claude_result is not None:
                result = self._build_result(
                    violations=claude_result.get("violations", []),
                    improvement_suggestions=claude_result.get("improvement_suggestions", []),
                    pre_calc=pre_calc,
                    source="claude",
                )
            else:
                result = self._fallback_result(fail_items, pre_calc)

        except (anthropic.APIConnectionError, anthropic.APIError) as exc:
            logger.warning(
                "patrol_inspector_claude_error",
                store_id=store_id,
                error=str(exc),
            )
            result = self._fallback_result(fail_items, pre_calc)

        self._log_decision(tenant_id, store_id, overall_score, result)
        return result

    def _pre_calculate(
        self, checklist_items: list[dict], overall_score: float, previous_score: float
    ) -> dict:
        """Python预计算业务规则，生成约束校验和预警标志。"""
        food_safety_fails = [
            item for item in checklist_items
            if item.get("category") == CATEGORY_FOOD_SAFETY and item.get("result") == "fail"
        ]
        fire_safety_fails = [
            item for item in checklist_items
            if item.get("category") == CATEGORY_FIRE_SAFETY and item.get("result") == "fail"
        ]

        # 卫生通过率
        hygiene_items = [
            item for item in checklist_items
            if item.get("category") == CATEGORY_HYGIENE and item.get("result") != "na"
        ]
        hygiene_pass = [item for item in hygiene_items if item.get("result") == "pass"]
        hygiene_pass_rate = (
            len(hygiene_pass) / len(hygiene_items) if hygiene_items else 1.0
        )

        # 约束校验
        food_safety_ok = len(food_safety_fails) == 0
        fire_safety_ok = len(fire_safety_fails) == 0
        hygiene_ok = hygiene_pass_rate >= HYGIENE_PASS_RATE_MIN

        # 自动预警判断
        auto_alert_required = not food_safety_ok or not fire_safety_ok

        # 风险等级（评分优先）
        if overall_score < SCORE_CRITICAL:
            risk_level = "critical"
            auto_alert_required = True
        elif overall_score < SCORE_HIGH or not food_safety_ok:
            risk_level = "high"
            auto_alert_required = True
        else:
            fail_items = [item for item in checklist_items if item.get("result") == "fail"]
            fail_count = len(fail_items)
            total_valid = len([i for i in checklist_items if i.get("result") != "na"])
            fail_rate = fail_count / total_valid if total_valid > 0 else 0.0
            if fail_rate >= 0.3:
                risk_level = "medium"
            elif fail_count > 0:
                risk_level = "low"
            else:
                risk_level = "low"

        # 分数趋势
        score_diff = overall_score - previous_score
        if score_diff < -SCORE_DECLINE_THRESHOLD:
            score_trend = "declining"
            auto_alert_required = True
        elif score_diff > SCORE_DECLINE_THRESHOLD:
            score_trend = "improving"
        else:
            score_trend = "stable"

        return {
            "food_safety_ok": food_safety_ok,
            "fire_safety_ok": fire_safety_ok,
            "hygiene_ok": hygiene_ok,
            "risk_level": risk_level,
            "score_trend": score_trend,
            "auto_alert_required": auto_alert_required,
            "food_safety_fails": food_safety_fails,
            "fire_safety_fails": fire_safety_fails,
        }

    def _build_context(
        self, payload: dict, pre_calc: dict, fail_items: list[dict]
    ) -> str:
        store_id = payload.get("store_id", "")
        patrol_date = payload.get("patrol_date", "")
        inspector_name = payload.get("inspector_name", "")
        overall_score = payload.get("overall_score", 0)
        previous_score = payload.get("previous_score", overall_score)
        checklist_items = payload.get("checklist_items", [])

        total_items = len([i for i in checklist_items if i.get("result") != "na"])
        fail_count = len(fail_items)

        # 按类别汇总失败项
        fail_lines = []
        for item in fail_items:
            notes = item.get("notes", "")
            notes_str = f"（备注：{notes}）" if notes else ""
            fail_lines.append(
                f"  [{item.get('category', '')}] {item.get('item_name', '')} "
                f"评分{item.get('score', 0)}/10 "
                f"照片{item.get('photo_count', 0)}张{notes_str}"
            )

        pre_warnings = []
        if not pre_calc["food_safety_ok"]:
            pre_warnings.append(f"⚠️ 食安违规{len(pre_calc['food_safety_fails'])}项，系统已触发自动预警")
        if not pre_calc["fire_safety_ok"]:
            pre_warnings.append(f"⚠️ 消防违规{len(pre_calc['fire_safety_fails'])}项，系统已触发自动预警")

        warnings_str = "\n".join(pre_warnings) if pre_warnings else "无自动预警触发"

        # 附加舆情摘要（由 analyze_from_mv 注入）
        opinion_ctx = payload.get("public_opinion", {})
        if opinion_ctx:
            opinion_lines = [
                f"- 近4周负面评价总数：{opinion_ctx.get('total_negative', 0)}条",
                f"- 最差平台：{opinion_ctx.get('worst_platform', '未知')}",
                f"- 平均情感评分：{opinion_ctx.get('avg_sentiment', 'N/A')}",
            ]
            opinion_section = "\n舆情背景（近4周）：\n" + "\n".join(opinion_lines)
        else:
            opinion_section = ""

        return f"""门店巡检报告分析请求：

基本信息：
- 门店ID：{store_id}
- 巡检日期：{patrol_date}
- 巡检员：{inspector_name}
- 本次综合评分：{overall_score:.1f}分
- 上次综合评分：{previous_score:.1f}分（{pre_calc['score_trend']}）
- 风险等级（系统预判）：{pre_calc['risk_level']}

检查概况：
- 有效检查项：{total_items}项
- 不合格项：{fail_count}项

不合格明细：
{chr(10).join(fail_lines)}

系统预警：
{warnings_str}{opinion_section}

请根据以上不合格项，分析每项违规的严重程度，给出具体整改建议。食安和消防违规必须标记为critical。"""

    def _parse_claude_response(self, response_text: str) -> dict | None:
        """解析Claude响应，提取JSON。失败返回None触发fallback。"""
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        logger.warning(
            "patrol_inspector_parse_failed",
            response_preview=response_text[:200],
        )
        return None

    def _build_result(
        self,
        violations: list[dict],
        improvement_suggestions: list[str],
        pre_calc: dict,
        source: str,
    ) -> dict:
        """组装最终返回结果，以Python预计算的业务规则为准。"""
        return {
            "risk_level": pre_calc["risk_level"],
            "violations": violations,
            "improvement_suggestions": improvement_suggestions,
            "score_trend": pre_calc["score_trend"],
            "constraints_check": {
                "food_safety_ok": pre_calc["food_safety_ok"],
                "fire_safety_ok": pre_calc["fire_safety_ok"],
                "hygiene_ok": pre_calc["hygiene_ok"],
            },
            "auto_alert_required": pre_calc["auto_alert_required"],
            "source": source,
        }

    def _fallback_result(self, fail_items: list[dict], pre_calc: dict) -> dict:
        """Claude失败时的纯Python规则兜底。"""
        violations = []
        for item in fail_items:
            category = item.get("category", "")
            item_name = item.get("item_name", "")

            if category in (CATEGORY_FOOD_SAFETY, CATEGORY_FIRE_SAFETY):
                severity = "critical"
                deadline_days = DEADLINE_CRITICAL
            elif item.get("score", 5) <= 3:
                severity = "major"
                deadline_days = DEADLINE_MAJOR
            else:
                severity = "minor"
                deadline_days = DEADLINE_MINOR

            violations.append({
                "category": category,
                "item": item_name,
                "severity": severity,
                "description": f"{item_name}检查不达标，请整改",
                "required_action": f"针对{item_name}进行整改，确保达到标准要求",
                "deadline_days": deadline_days,
            })

        fail_count = len(fail_items)
        improvement_suggestions = [
            f"本次巡检发现{fail_count}项不合格，请按期整改并复查",
        ]
        if not pre_calc["food_safety_ok"]:
            improvement_suggestions.append("食品安全问题须优先整改，建议立即启动食安专项检查")
        if not pre_calc["fire_safety_ok"]:
            improvement_suggestions.append("消防安全问题须立即整改，确保人员和财产安全")
        if not pre_calc["hygiene_ok"]:
            improvement_suggestions.append("卫生通过率不达标，建议加强日常清洁管理和员工培训")

        return self._build_result(
            violations=violations,
            improvement_suggestions=improvement_suggestions,
            pre_calc=pre_calc,
            source="fallback",
        )

    def _log_decision(
        self, tenant_id: str, store_id: str, overall_score: float, result: dict
    ) -> None:
        """记录决策留痕。"""
        logger.info(
            "patrol_inspector_decision",
            tenant_id=tenant_id,
            store_id=store_id,
            overall_score=overall_score,
            risk_level=result.get("risk_level"),
            violation_count=len(result.get("violations", [])),
            auto_alert_required=result.get("auto_alert_required"),
            score_trend=result.get("score_trend"),
            food_safety_ok=result.get("constraints_check", {}).get("food_safety_ok"),
            fire_safety_ok=result.get("constraints_check", {}).get("fire_safety_ok"),
            hygiene_ok=result.get("constraints_check", {}).get("hygiene_ok"),
            source=result.get("source"),
        )


    async def analyze_from_mv(self, payload: dict, db) -> dict:
        """基于物化视图的增强分析入口。

        在调用标准 analyze() 之前，从 mv_public_opinion 读取近4周舆情摘要，
        附加到 input_context 中，丰富 Claude 的分析背景。
        """
        tenant_id = payload.get("tenant_id", "")
        store_id = payload.get("store_id", "")

        opinion_ctx = await self.get_opinion_context(tenant_id, store_id, db)

        # 将舆情数据附加到 payload，供 _build_context 使用
        enriched_payload = dict(payload)
        enriched_payload["public_opinion"] = opinion_ctx

        return await self.analyze(enriched_payload)

    async def get_opinion_context(self, tenant_id: str, store_id: str, db) -> dict:
        """从 mv_public_opinion 读取近4周舆情摘要，供 analyze_from_mv() 增强上下文。

        查询 mv_public_opinion 最近4周，按 platform 聚合。
        无数据或查询失败时返回 {}。
        """
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError

        try:
            result = await db.execute(
                text("""
                    SELECT platform,
                           SUM(total_mentions) as total,
                           SUM(negative_count) as negative,
                           AVG(avg_sentiment_score) as avg_sentiment
                    FROM mv_public_opinion
                    WHERE tenant_id = :tenant_id AND store_id = :store_id
                      AND stat_week >= (CURRENT_DATE - INTERVAL '28 days')::DATE
                    GROUP BY platform
                    ORDER BY negative DESC
                """),
                {"tenant_id": tenant_id, "store_id": store_id},
            )
            rows = result.mappings().all()
            if not rows:
                return {}

            total_negative = sum(int(r["negative"] or 0) for r in rows)
            worst_platform = rows[0]["platform"] if rows else None
            avg_sentiments = [float(r["avg_sentiment"]) for r in rows if r["avg_sentiment"] is not None]
            avg_sentiment = round(sum(avg_sentiments) / len(avg_sentiments), 4) if avg_sentiments else None

            return {
                "total_negative": total_negative,
                "worst_platform": worst_platform,
                "avg_sentiment": avg_sentiment,
                "platform_breakdown": [
                    {
                        "platform": r["platform"],
                        "total": int(r["total"] or 0),
                        "negative": int(r["negative"] or 0),
                        "avg_sentiment": float(r["avg_sentiment"]) if r["avg_sentiment"] is not None else None,
                    }
                    for r in rows
                ],
            }
        except SQLAlchemyError as exc:
            logger.warning(
                "patrol_inspector_opinion_ctx_error",
                tenant_id=tenant_id,
                store_id=store_id,
                error=str(exc),
            )
            return {}


patrol_inspector = PatrolInspector()
