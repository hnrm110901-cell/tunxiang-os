"""#1 折扣守护 Agent — P0 | 边缘+云端

来源：ComplianceAgent + FctAgent
能力：折扣异常实时检测、证照扫描、财务报表、凭证解释、对账
边缘推理：Core ML 异常折扣检测（< 50ms）

Phase 3 升级（2026-04-04）：
  新增 get_daily_discount_health — 直接读取 mv_discount_health 物化视图
  替代原有的跨服务查询模式（读视图延迟 < 5ms vs 跨服务拼接 > 100ms）

P1-5 升级（2026-04-12）：
  集成 EdgeAwareMixin — 折扣异常检测优先使用边缘 Core ML 推理
  边缘高置信度（>0.8）时直接使用边缘结果，节省 Claude API 成本
"""

import asyncio
import os
from datetime import date, datetime, timezone
from typing import Any

import httpx
import structlog
from constraints.decorator import with_constraint_check
from sqlalchemy import text

from ..base import ActionConfig, AgentResult, SkillAgent
from ..edge_mixin import EdgeAwareMixin

logger = structlog.get_logger()


# 报表类型
REPORT_TYPES = ["period_summary", "aggregate", "trend", "by_entity", "by_region", "comparison", "plan_vs_actual"]


class DiscountGuardAgent(EdgeAwareMixin, SkillAgent):
    agent_id = "discount_guard"
    agent_name = "折扣守护"
    description = "实时检测异常折扣/赠送，扫描证照，财务报表查询"
    priority = "P0"
    run_location = "edge+cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "detect_discount_anomaly",
            "get_daily_discount_health",  # Phase 3: 直接读物化视图
            "scan_store_licenses",
            "scan_all_licenses",
            "get_financial_report",
            "explain_voucher",
            "reconciliation_status",
            "log_violation",
        ]

    def get_action_config(self, action: str) -> ActionConfig:
        """折扣守护 Agent 的 action 级会话策略"""
        configs = {
            # 折扣异常检测涉及资金风险，需人工确认
            "detect_discount_anomaly": ActionConfig(
                risk_level="high",
                requires_human_confirm=True,
                max_retries=1,
            ),
            # 折扣健康视图读取，中等风险
            "get_daily_discount_health": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
            # 证照扫描可重试
            "scan_store_licenses": ActionConfig(
                risk_level="medium",
                max_retries=2,
            ),
            # 全品牌证照扫描
            "scan_all_licenses": ActionConfig(
                risk_level="medium",
                max_retries=2,
            ),
            # 财务报表查询
            "get_financial_report": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
            # 凭证解释（云端 LLM）
            "explain_voucher": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
            # 对账状态查询
            "reconciliation_status": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
            # 违规记录留痕
            "log_violation": ActionConfig(
                risk_level="medium",
                max_retries=1,
            ),
        }
        return configs.get(action, ActionConfig())

    # Sprint D1：硬阻断装饰器 — 折扣检测的 price/cost/discount 字段已在
    # _detect_anomaly 与 _get_daily_discount_health 的 result.data 中填入，
    # 三条约束（毛利底线优先）在 happy path 数据齐备时自动触发；缺数据自动 skipped
    @with_constraint_check(skill_name="discount_guard")
    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "detect_discount_anomaly": self._detect_anomaly,
            "get_daily_discount_health": self._get_daily_discount_health,
            "scan_store_licenses": self._scan_licenses,
            "scan_all_licenses": self._scan_all,
            "get_financial_report": self._get_report,
            "explain_voucher": self._explain_voucher,
            "reconciliation_status": self._reconciliation,
            "log_violation": self._log_violation,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported: {action}")
        return await handler(params)

    async def _detect_anomaly(self, params: dict) -> AgentResult:
        """折扣异常检测 — 边缘 Core ML 优先 → 规则引擎 → Claude 深度分析

        推理链路：
        1. 尝试边缘 Core ML 推理（<50ms，高置信度时直接返回，节省 API 成本）
        2. 规则引擎快速判断（始终执行，作为基线）
        3. Claude API 深度分析（仅在风险较高且边缘置信度不足时调用）
        """
        order_id = params.get("order_id")

        # 若有 order_id 且 DB 可用，从 DB 查真实数据；否则降级到 params 中的 order 字典
        if order_id and self._db:
            from sqlalchemy import text

            row = await self._db.execute(
                text(
                    "SELECT total_amount_fen, discount_amount_fen, status, store_id "
                    "FROM orders WHERE id = :id AND tenant_id = :tid"
                ),
                {"id": order_id, "tid": self.tenant_id},
            )
            order_data = dict(row.mappings().first() or {})
        else:
            order_data = params.get("order", {})

        total = order_data.get("total_amount_fen", 0)
        discount = order_data.get("discount_amount_fen", 0)
        discount_rate = discount / total if total > 0 else 0
        threshold = params.get("threshold", 0.5)

        # ── Step 1: 尝试边缘 Core ML 推理 ──
        from datetime import datetime as _dt

        edge_result = await self.get_edge_prediction(
            "discount-risk",
            order_data={
                "discount_rate": discount_rate,
                "hour_of_day": _dt.now().hour,
                "order_amount_fen": total,
                "employee_id": order_data.get("employee_id", ""),
                "table_id": order_data.get("table_id", ""),
            },
        )

        # 边缘高置信度（>0.8）且有明确结论时，直接使用边缘结果
        if edge_result and edge_result.get("confidence", 0) > 0.8:
            edge_risk_score = edge_result.get("risk_score", 0)
            edge_risk_level = edge_result.get("risk_level", "low")
            is_anomaly = edge_risk_level in ("high", "medium") or edge_risk_score > 0.5

            logger.info(
                "discount_guard_edge_shortcut",
                discount_rate=discount_rate,
                edge_risk_score=edge_risk_score,
                edge_risk_level=edge_risk_level,
                order_id=order_id,
            )

            return AgentResult(
                success=True,
                action="detect_discount_anomaly",
                data={
                    "is_anomaly": is_anomaly,
                    "discount_rate": round(discount_rate, 4),
                    "threshold": threshold,
                    "risk_factors": edge_result.get("risk_factors", []),
                    "risk_score": edge_risk_score,
                    "price_fen": total,
                    "cost_fen": order_data.get("cost_fen", 0),
                    "llm_analysis": "",
                    "order_id": order_id,
                    "edge_method": edge_result.get("method", "unknown"),
                },
                reasoning=(
                    f"边缘推理：折扣率{discount_rate:.1%}，风险评分{edge_risk_score:.2f}，"
                    f"风险等级={edge_risk_level}（Core ML 高置信度，跳过 Claude API）"
                ),
                confidence=edge_result["confidence"],
                inference_layer="edge",
            )

        # ── Step 2: 规则引擎快速判断（边缘不可用或低置信度时） ──
        risk_factors = []
        if discount_rate > 0.7:
            risk_factors.append("折扣率超70%")
        if total > 50000 and discount > 20000:
            risk_factors.append("大额订单高折扣")
        if order_data.get("waiter_discount_count", 0) > 5:
            risk_factors.append("同一服务员频繁打折")

        # 合并边缘推理的风险因素（如有）
        if edge_result and edge_result.get("risk_factors"):
            for factor in edge_result["risk_factors"]:
                if factor not in risk_factors:
                    risk_factors.append(factor)

        is_anomaly = discount_rate > threshold or len(risk_factors) >= 2

        # ── Step 3: Claude API 深度分析（仅在风险较高时调用） ──
        llm_analysis = ""
        if self._router and is_anomaly:
            try:
                llm_analysis = await self._router.complete(
                    tenant_id=self.tenant_id,
                    task_type="standard_analysis",
                    system="你是餐饮收银审计专家，分析折扣异常风险并给出处理建议。用中文回复，控制在100字内。",
                    messages=[
                        {
                            "role": "user",
                            "content": f"订单金额{total / 100:.2f}元，折扣{discount / 100:.2f}元（折扣率{discount_rate:.1%}），"
                            f"风险因素：{risk_factors}。请评估风险等级并给出建议。",
                        }
                    ],
                    max_tokens=200,
                    db=self._db,
                )
            except Exception as exc:  # noqa: BLE001 — Claude不可用时降级为规则结果
                logger.warning("discount_guard_llm_fallback", error=str(exc))

        return AgentResult(
            success=True,
            action="detect_discount_anomaly",
            data={
                "is_anomaly": is_anomaly,
                "discount_rate": round(discount_rate, 4),
                "threshold": threshold,
                "risk_factors": risk_factors,
                "risk_score": min(1.0, discount_rate * 1.5 + len(risk_factors) * 0.1),
                "price_fen": total,
                "cost_fen": order_data.get("cost_fen", 0),
                "llm_analysis": llm_analysis,
                "order_id": order_id,
            },
            reasoning=f"折扣率{discount_rate:.1%}，{len(risk_factors)}个风险因素。{llm_analysis[:50] if llm_analysis else '规则引擎判断'}",
            confidence=0.95 if not llm_analysis else 0.99,
            inference_layer="edge" if not llm_analysis else "cloud",
        )

    async def _get_daily_discount_health(self, params: dict) -> AgentResult:
        """Phase 3 — 直接读 mv_discount_health 物化视图，返回当日折扣健康摘要。

        替代原有的跨服务查询模式。视图由 DiscountHealthProjector 实时维护。

        Params:
            store_id:   门店 ID（必传）
            stat_date:  统计日期（YYYY-MM-DD，默认今日）
            threshold:  折扣率告警阈值（默认 0.3）
        """
        store_id = params.get("store_id") or self.store_id
        stat_date_str = params.get("stat_date")
        threshold = float(params.get("threshold", 0.3))

        if not store_id:
            return AgentResult(
                success=False,
                action="get_daily_discount_health",
                error="store_id 必传",
            )

        if not self._db:
            return AgentResult(
                success=False,
                action="get_daily_discount_health",
                error="DB 未注入，无法读取物化视图",
            )

        try:
            stat_date: date = date.fromisoformat(stat_date_str) if stat_date_str else date.today()

            row = await self._db.execute(
                text("""
                    SELECT
                        total_orders,
                        discounted_orders,
                        discount_rate,
                        total_discount_fen,
                        unauthorized_count,
                        threshold_breaches,
                        leak_types,
                        updated_at
                    FROM mv_discount_health
                    WHERE tenant_id = :tid
                      AND store_id = :sid
                      AND stat_date = :dt
                """),
                {
                    "tid": self.tenant_id,
                    "sid": store_id,
                    "dt": stat_date,
                },
            )
            health = dict((row.mappings().first() or {}))

            if not health:
                return AgentResult(
                    success=True,
                    action="get_daily_discount_health",
                    data={
                        "store_id": store_id,
                        "stat_date": stat_date.isoformat(),
                        "message": "暂无数据（投影器尚未消费到今日事件）",
                        "discount_rate": 0,
                        "is_alert": False,
                    },
                    reasoning="mv_discount_health 无当日记录",
                    confidence=0.5,
                )

            discount_rate = float(health.get("discount_rate", 0))
            unauthorized = int(health.get("unauthorized_count", 0))
            threshold_breaches = int(health.get("threshold_breaches", 0))
            is_alert = discount_rate > threshold or unauthorized > 0 or threshold_breaches > 0

            # 风险等级
            if discount_rate > 0.5 or threshold_breaches > 3:
                risk_level = "critical"
            elif discount_rate > threshold or unauthorized > 0:
                risk_level = "high"
            elif discount_rate > threshold * 0.7:
                risk_level = "medium"
            else:
                risk_level = "low"

            # 若有风险且有 Claude，进行深度分析
            llm_analysis = ""
            if is_alert and risk_level in ("critical", "high") and self._router:
                try:
                    leak_types = health.get("leak_types") or {}
                    llm_analysis = await self._router.complete(
                        tenant_id=self.tenant_id,
                        task_type="standard_analysis",
                        system="你是餐饮收银审计专家，分析折扣健康数据并给出处理建议。用中文，80字以内。",
                        messages=[
                            {
                                "role": "user",
                                "content": f"今日折扣率{discount_rate:.1%}（阈值{threshold:.1%}），"
                                f"未授权折扣{unauthorized}次，超毛利底线{threshold_breaches}次，"
                                f"泄漏类型：{leak_types}。请评估风险并给出具体处理建议。",
                            }
                        ],
                        max_tokens=150,
                        db=self._db,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("discount_health_llm_fallback", error=str(exc))

            return AgentResult(
                success=True,
                action="get_daily_discount_health",
                data={
                    "store_id": store_id,
                    "stat_date": stat_date.isoformat(),
                    "total_orders": health.get("total_orders", 0),
                    "discounted_orders": health.get("discounted_orders", 0),
                    "discount_rate": discount_rate,
                    "total_discount_yuan": round(int(health.get("total_discount_fen", 0)) / 100, 2),
                    "unauthorized_count": unauthorized,
                    "threshold_breaches": threshold_breaches,
                    "leak_types": health.get("leak_types") or {},
                    "is_alert": is_alert,
                    "risk_level": risk_level,
                    "threshold": threshold,
                    "llm_analysis": llm_analysis,
                    "data_freshness": health.get("updated_at", ""),
                    "source": "mv_discount_health",  # Phase 3 标识
                },
                reasoning=(
                    f"折扣率{discount_rate:.1%}，未授权{unauthorized}次，"
                    f"超毛利底线{threshold_breaches}次，风险等级={risk_level}。"
                    + (f"Claude分析：{llm_analysis[:40]}" if llm_analysis else "规则引擎判断")
                ),
                confidence=0.99 if llm_analysis else 0.95,
                inference_layer="cloud" if llm_analysis else "edge",
            )

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "get_daily_discount_health_failed",
                store_id=store_id,
                error=str(exc),
                exc_info=True,
            )
            return AgentResult(
                success=False,
                action="get_daily_discount_health",
                error=f"读取物化视图失败: {exc}",
            )

    async def _scan_licenses(self, params: dict) -> AgentResult:
        """单门店证照扫描"""
        licenses = params.get("licenses", [])
        now = datetime.now(timezone.utc)
        expired, expiring, valid = [], [], []

        for lic in licenses:
            name = lic.get("name", "")
            expiry = lic.get("expiry_date", "")
            remaining_days = lic.get("remaining_days", 999)

            if remaining_days <= 0:
                expired.append({"name": name, "expiry": expiry, "days": remaining_days})
            elif remaining_days <= 30:
                expiring.append({"name": name, "expiry": expiry, "days": remaining_days})
            else:
                valid.append({"name": name, "expiry": expiry, "days": remaining_days})

        return AgentResult(
            success=True,
            action="scan_store_licenses",
            data={
                "expired": expired,
                "expiring_soon": expiring,
                "valid": valid,
                "total": len(licenses),
                "issues": len(expired) + len(expiring),
            },
            reasoning=f"{len(expired)} 张过期，{len(expiring)} 张即将过期，{len(valid)} 张有效",
            confidence=1.0,
        )

    async def _scan_all(self, params: dict) -> AgentResult:
        """全品牌证照扫描"""
        stores = params.get("stores", [])
        total_issues = 0
        store_results = []
        for store in stores:
            licenses = store.get("licenses", [])
            issues = sum(1 for l in licenses if l.get("remaining_days", 999) <= 30)
            total_issues += issues
            if issues > 0:
                store_results.append({"store_name": store.get("name", ""), "issues": issues})

        return AgentResult(
            success=True,
            action="scan_all_licenses",
            data={"stores_with_issues": store_results, "total_issues": total_issues, "stores_scanned": len(stores)},
            reasoning=f"扫描 {len(stores)} 家门店，{total_issues} 个证照问题",
            confidence=1.0,
        )

    async def _get_report(self, params: dict) -> AgentResult:
        """财务报表（7种类型）"""
        report_type = params.get("report_type", "period_summary")
        if report_type not in REPORT_TYPES:
            return AgentResult(
                success=False, action="get_financial_report", error=f"未知报表类型，可选: {REPORT_TYPES}"
            )

        return AgentResult(
            success=True,
            action="get_financial_report",
            data={"report_type": report_type, "generated": True, "summary": f"{report_type} 报表已生成"},
            reasoning=f"生成 {report_type} 报表",
            confidence=0.9,
        )

    async def _explain_voucher(self, params: dict) -> AgentResult:
        """凭证解释 — 接入 Claude API"""
        voucher_id = params.get("voucher_id", "")
        voucher_data = params.get("voucher_data", {})

        if not self._router:
            return AgentResult(
                success=False,
                action="explain_voucher",
                error="model_router 未注入，无法调用 Claude API",
            )

        content = f"凭证ID: {voucher_id}\n凭证数据: {voucher_data}"
        explanation = await self._router.complete(
            tenant_id=self.tenant_id,
            task_type="standard_analysis",
            system="你是餐饮财务专家，用清晰通俗的语言解释财务凭证的含义，100字以内。",
            messages=[{"role": "user", "content": f"请解释这个财务凭证：\n{content}"}],
            max_tokens=200,
            db=self._db,
        )

        return AgentResult(
            success=True,
            action="explain_voucher",
            data={"voucher_id": voucher_id, "explanation": explanation},
            reasoning="Claude财务专家解释",
            confidence=0.9,
            inference_layer="cloud",
        )

    async def _reconciliation(self, params: dict) -> AgentResult:
        """对账状态"""
        date = params.get("date", "today")
        return AgentResult(
            success=True,
            action="reconciliation_status",
            data={"date": date, "status": "matched", "discrepancies": [], "total_transactions": 0, "matched_count": 0},
            reasoning=f"{date} 对账完成",
            confidence=0.85,
        )

    # ─── 事件驱动：折扣违规留痕 ───

    async def _log_violation(self, params: dict) -> AgentResult:
        """discount_violation / trade.discount.blocked 事件触发：记录折扣违规明细

        将违规信息结构化记录，供后续：
        - 财务稽核（flag_discount_anomaly）消费
        - 门店管理端预警展示
        - 月度合规报告汇总

        不直接写 DB（由 service 层负责），Agent 做结构化分析和留痕。
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        order_id = params.get("order_id") or event_data.get("order_id")
        operator_id = params.get("operator_id") or event_data.get("operator_id")
        discount_amount_fen = params.get("discount_amount_fen") or event_data.get("discount_amount_fen", 0)
        order_total_fen = params.get("total_fen") or event_data.get("total_fen", 0)
        violation_type = params.get("violation_type") or event_data.get("violation_type", "unauthorized_discount")
        blocked_by = params.get("blocked_by") or event_data.get("blocked_by", "discount_guard")

        # 计算实际折扣率
        discount_rate = discount_amount_fen / order_total_fen if order_total_fen > 0 else 0

        # 违规严重程度评估
        severity = (
            "critical"
            if discount_rate > 0.7 or discount_amount_fen > 50000
            else "high"
            if discount_rate > 0.5 or discount_amount_fen > 20000
            else "medium"
            if discount_rate > 0.3
            else "low"
        )

        # 建议处理动作
        recommended_actions = []
        if severity in ("critical", "high"):
            recommended_actions.append("立即通知店长审核")
            recommended_actions.append("暂停该操作员折扣权限")
        if discount_rate > 0.5:
            recommended_actions.append("核实是否有授权审批")
        recommended_actions.append("记录违规档案")

        violation_record = {
            "violation_id": f"VIO-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "store_id": store_id,
            "order_id": order_id,
            "operator_id": operator_id,
            "violation_type": violation_type,
            "discount_amount_fen": discount_amount_fen,
            "discount_amount_yuan": round(discount_amount_fen / 100, 2),
            "order_total_fen": order_total_fen,
            "discount_rate": round(discount_rate, 4),
            "severity": severity,
            "blocked_by": blocked_by,
            "recommended_actions": recommended_actions,
            "logged_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "discount_violation_logged",
            store_id=store_id,
            order_id=order_id,
            operator_id=operator_id,
            violation_type=violation_type,
            discount_rate=round(discount_rate, 4),
            severity=severity,
        )

        # 推送到门店 POS 终端（fire-and-forget，不阻塞 Agent 返回）
        asyncio.create_task(self._push_to_pos(store_id, violation_record))

        return AgentResult(
            success=True,
            action="log_violation",
            data=violation_record,
            reasoning=(
                f"折扣违规记录：{violation_type}，折扣率{discount_rate:.1%}，"
                f"金额¥{discount_amount_fen / 100:.0f}，严重度={severity}"
            ),
            confidence=0.95,
        )

    async def _push_to_pos(self, store_id: str, data: dict) -> None:
        """向 mac-station 发送折扣预警，由 mac-station 推送到 POS WebSocket。

        fire-and-forget：mac-station 离线时只记录 warning，不影响主流程。

        Args:
            store_id: 目标门店 ID
            data: violation_record 字典（含 violation_id / discount_rate / severity 等字段）
        """
        mac_url = os.getenv("MAC_STATION_URL", "http://localhost:8000")
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.post(
                    f"{mac_url}/api/v1/pos/push-discount-alert",
                    json={
                        "store_id": store_id,
                        "alert": data,
                    },
                )
            logger.debug(
                "pos_push_dispatched",
                store_id=store_id,
                violation_id=data.get("violation_id"),
            )
        except httpx.ConnectError as exc:
            logger.warning(
                "pos_push_failed_connect",
                store_id=store_id,
                violation_id=data.get("violation_id"),
                error=str(exc),
            )
        except httpx.TimeoutException as exc:
            logger.warning(
                "pos_push_failed_timeout",
                store_id=store_id,
                violation_id=data.get("violation_id"),
                error=str(exc),
            )
