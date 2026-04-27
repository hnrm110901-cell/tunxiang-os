"""经营诊断 Agent — 每日 07:00 自动运行

分析前一日经营数据，发现异常，通过 Claude API 生成自然语言摘要，
写入 DB 并推送给店长。

诊断规则（6 条）：
  1. 营业额异常     — 今日营业额 < 近 7 日均值 × 0.7
  2. 翻台率下滑     — 今日翻台率 < 历史均值 × 0.8
  3. 菜品滞销       — 今日 0 销量但上周日均 > 3 份
  4. 退菜率异常     — 退菜率 > 5%
  5. 员工绩效异常   — 某员工接单量 < 团队均值 × 0.5
  6. 食材浪费       — 今日食材损耗 > 近 7 日均值 × 1.5
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Optional

import httpx
import structlog
from pydantic import BaseModel, Field
from sqlalchemy import text

logger = structlog.get_logger()

# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_SYSTEM_PROMPT = (
    "你是一位经验丰富的餐饮经营顾问，请根据以下数据异常生成简洁的经营诊断报告，重点突出问题和改进建议"
)
ANALYTICS_API_BASE = "http://localhost:8000/api/v1/analytics"
MAC_STATION_BASE = "http://localhost:9000"


# ─────────────────────────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────────────────────────
class AnomalySeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Anomaly(BaseModel):
    rule_id: str
    rule_name: str
    severity: AnomalySeverity
    description: str
    actual_value: Optional[float] = None
    threshold_value: Optional[float] = None
    context: dict[str, Any] = Field(default_factory=dict)


class DiagnosisReport(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    store_id: str
    report_date: date
    anomalies: list[Anomaly]
    summary_text: str = ""
    raw_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DailySummary(BaseModel):
    """从 tx-analytics 拉取的日汇总数据结构（字段缺失时安全降级为 None）"""

    revenue_today: Optional[float] = None
    revenue_7d_avg: Optional[float] = None
    table_turn_rate_today: Optional[float] = None
    table_turn_rate_history_avg: Optional[float] = None
    dish_sales_today: dict[str, float] = Field(default_factory=dict)
    dish_sales_last_week_daily_avg: dict[str, float] = Field(default_factory=dict)
    return_dish_rate: Optional[float] = None
    employee_order_count: dict[str, int] = Field(default_factory=dict)
    ingredient_waste_today: Optional[float] = None
    ingredient_waste_7d_avg: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────────
# BusinessDiagnosisAgent
# ─────────────────────────────────────────────────────────────────────────────
class BusinessDiagnosisAgent:
    """
    经营诊断Agent - 每日07:00自动运行
    分析前一日经营数据，发现异常，生成诊断报告
    """

    def __init__(
        self,
        tenant_id: str,
        store_id: str,
        claude_api_key: Optional[str] = None,
        analytics_base_url: str = ANALYTICS_API_BASE,
        mac_station_base_url: str = MAC_STATION_BASE,
    ) -> None:
        self.tenant_id = tenant_id
        self.store_id = store_id
        self._claude_api_key = claude_api_key
        self._analytics_base_url = analytics_base_url
        self._mac_station_base_url = mac_station_base_url

    # ──────────────────────────────────────────────
    # 公开入口
    # ──────────────────────────────────────────────
    async def run(self, target_date: Optional[date] = None) -> DiagnosisReport:
        """执行完整诊断流程，返回 DiagnosisReport。

        Args:
            target_date: 诊断日期，默认为昨天。
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)

        log = logger.bind(
            tenant_id=self.tenant_id,
            store_id=self.store_id,
            target_date=str(target_date),
        )
        log.info("diagnosis_started")

        try:
            raw_data = await self._fetch_daily_summary(target_date)
            summary = self._parse_summary(raw_data)
            anomalies = self._detect_anomalies(summary)

            summary_text = ""
            if anomalies:
                summary_text = await self._generate_summary(anomalies)

            report = DiagnosisReport(
                tenant_id=self.tenant_id,
                store_id=self.store_id,
                report_date=target_date,
                anomalies=anomalies,
                summary_text=summary_text,
                raw_data=raw_data,
            )

            await self._save_report(report)
            await self._push_to_manager(report)

            log.info(
                "diagnosis_completed",
                anomaly_count=len(anomalies),
                has_summary=bool(summary_text),
            )
            return report

        except Exception as exc:  # noqa: BLE001 — Agent执行兜底，需捕获所有异常避免崩溃
            log.error("diagnosis_failed", error=str(exc), exc_info=True)
            raise

    # ──────────────────────────────────────────────
    # 数据获取
    # ──────────────────────────────────────────────
    async def _fetch_daily_summary(self, target_date: date) -> dict[str, Any]:
        """从 tx-analytics 拉取日汇总数据。"""
        url = f"{self._analytics_base_url}/daily-summary"
        params = {
            "date": str(target_date),
            "store_id": self.store_id,
        }
        headers = {"X-Tenant-ID": self.tenant_id}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                body = resp.json()
                return body.get("data", body)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "analytics_fetch_http_error",
                status=exc.response.status_code,
                url=url,
            )
            return {}
        except httpx.RequestError as exc:
            logger.warning("analytics_fetch_request_error", error=str(exc), url=url)
            return {}

    @staticmethod
    def _parse_summary(raw: dict[str, Any]) -> DailySummary:
        """将原始字典安全解析为 DailySummary，缺字段时返回 None 而非抛错。"""
        try:
            return DailySummary.model_validate(raw)
        except ValueError:
            logger.warning("daily_summary_parse_error", raw_keys=list(raw.keys()))
            return DailySummary()

    # ──────────────────────────────────────────────
    # 诊断规则（6 条）
    # ──────────────────────────────────────────────
    def _detect_anomalies(self, s: DailySummary) -> list[Anomaly]:
        anomalies: list[Anomaly] = []
        anomalies.extend(self._rule_revenue_drop(s))
        anomalies.extend(self._rule_table_turn_rate(s))
        anomalies.extend(self._rule_dish_unsold(s))
        anomalies.extend(self._rule_return_dish_rate(s))
        anomalies.extend(self._rule_employee_performance(s))
        anomalies.extend(self._rule_ingredient_waste(s))
        return anomalies

    @staticmethod
    def _rule_revenue_drop(s: DailySummary) -> list[Anomaly]:
        """规则 1：今日营业额 < 近 7 日均值 × 0.7"""
        if s.revenue_today is None or s.revenue_7d_avg is None or s.revenue_7d_avg == 0:
            return []
        threshold = s.revenue_7d_avg * 0.7
        if s.revenue_today < threshold:
            return [
                Anomaly(
                    rule_id="R01",
                    rule_name="营业额异常",
                    severity=AnomalySeverity.WARNING,
                    description=(
                        f"今日营业额 ¥{s.revenue_today:.0f} 低于近7日均值 "
                        f"¥{s.revenue_7d_avg:.0f} 的 70%（阈值 ¥{threshold:.0f}）"
                    ),
                    actual_value=s.revenue_today,
                    threshold_value=threshold,
                    context={"revenue_7d_avg": s.revenue_7d_avg},
                )
            ]
        return []

    @staticmethod
    def _rule_table_turn_rate(s: DailySummary) -> list[Anomaly]:
        """规则 2：今日翻台率 < 历史均值 × 0.8"""
        if (
            s.table_turn_rate_today is None
            or s.table_turn_rate_history_avg is None
            or s.table_turn_rate_history_avg == 0
        ):
            return []
        threshold = s.table_turn_rate_history_avg * 0.8
        if s.table_turn_rate_today < threshold:
            return [
                Anomaly(
                    rule_id="R02",
                    rule_name="翻台率下滑",
                    severity=AnomalySeverity.WARNING,
                    description=(
                        f"今日翻台率 {s.table_turn_rate_today:.2f} 低于历史均值 "
                        f"{s.table_turn_rate_history_avg:.2f} 的 80%（阈值 {threshold:.2f}）"
                    ),
                    actual_value=s.table_turn_rate_today,
                    threshold_value=threshold,
                    context={"history_avg": s.table_turn_rate_history_avg},
                )
            ]
        return []

    @staticmethod
    def _rule_dish_unsold(s: DailySummary) -> list[Anomaly]:
        """规则 3：今日 0 销量但上周日均 > 3 份"""
        anomalies: list[Anomaly] = []
        for dish_id, last_week_avg in s.dish_sales_last_week_daily_avg.items():
            if last_week_avg > 3 and s.dish_sales_today.get(dish_id, 0) == 0:
                anomalies.append(
                    Anomaly(
                        rule_id="R03",
                        rule_name="菜品滞销",
                        severity=AnomalySeverity.WARNING,
                        description=(f"菜品 {dish_id} 今日零销量，但上周日均售出 {last_week_avg:.1f} 份"),
                        actual_value=0.0,
                        threshold_value=last_week_avg,
                        context={"dish_id": dish_id, "last_week_daily_avg": last_week_avg},
                    )
                )
        return anomalies

    @staticmethod
    def _rule_return_dish_rate(s: DailySummary) -> list[Anomaly]:
        """规则 4：退菜率 > 5%"""
        if s.return_dish_rate is None:
            return []
        if s.return_dish_rate > 0.05:
            return [
                Anomaly(
                    rule_id="R04",
                    rule_name="退菜率异常",
                    severity=AnomalySeverity.CRITICAL,
                    description=(f"今日退菜率 {s.return_dish_rate * 100:.1f}% 超过警戒线 5%，请立即排查品控和服务问题"),
                    actual_value=s.return_dish_rate * 100,
                    threshold_value=5.0,
                )
            ]
        return []

    @staticmethod
    def _rule_employee_performance(s: DailySummary) -> list[Anomaly]:
        """规则 5：某员工接单量 < 团队均值 × 0.5"""
        if not s.employee_order_count or len(s.employee_order_count) < 2:
            return []
        counts = list(s.employee_order_count.values())
        team_avg = sum(counts) / len(counts)
        threshold = team_avg * 0.5
        anomalies: list[Anomaly] = []
        for emp_id, count in s.employee_order_count.items():
            if count < threshold:
                anomalies.append(
                    Anomaly(
                        rule_id="R05",
                        rule_name="员工绩效异常",
                        severity=AnomalySeverity.INFO,
                        description=(
                            f"员工 {emp_id} 今日接单 {count} 单，"
                            f"低于团队均值 {team_avg:.1f} 单的 50%（阈值 {threshold:.1f} 单）"
                        ),
                        actual_value=float(count),
                        threshold_value=threshold,
                        context={"employee_id": emp_id, "team_avg": team_avg},
                    )
                )
        return anomalies

    @staticmethod
    def _rule_ingredient_waste(s: DailySummary) -> list[Anomaly]:
        """规则 6：今日食材损耗 > 近 7 日均值 × 1.5"""
        if s.ingredient_waste_today is None or s.ingredient_waste_7d_avg is None or s.ingredient_waste_7d_avg == 0:
            return []
        threshold = s.ingredient_waste_7d_avg * 1.5
        if s.ingredient_waste_today > threshold:
            return [
                Anomaly(
                    rule_id="R06",
                    rule_name="食材浪费",
                    severity=AnomalySeverity.WARNING,
                    description=(
                        f"今日食材损耗 ¥{s.ingredient_waste_today:.0f} 超过近7日均值 "
                        f"¥{s.ingredient_waste_7d_avg:.0f} 的 1.5 倍（阈值 ¥{threshold:.0f}）"
                    ),
                    actual_value=s.ingredient_waste_today,
                    threshold_value=threshold,
                    context={"waste_7d_avg": s.ingredient_waste_7d_avg},
                )
            ]
        return []

    # ──────────────────────────────────────────────
    # Claude API 摘要生成
    # ──────────────────────────────────────────────
    async def _generate_summary(self, anomalies: list[Anomaly]) -> str:
        """调用 Claude API 生成三段式自然语言诊断报告。"""
        if not self._claude_api_key:
            import os

            self._claude_api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        if not self._claude_api_key:
            logger.warning("claude_api_key_missing", action="skip_summary_generation")
            return ""

        anomaly_text = "\n".join(f"[{a.severity.value.upper()}] {a.rule_name}：{a.description}" for a in anomalies)
        user_message = (
            f"以下是今日经营异常数据（共 {len(anomalies)} 条）：\n\n"
            f"{anomaly_text}\n\n"
            "请生成 3 段文字诊断报告（总结/问题/建议），每段不超过 100 字。"
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self._claude_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": CLAUDE_MODEL,
                        "max_tokens": 600,
                        "system": CLAUDE_SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": user_message}],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["content"][0]["text"].strip()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "claude_api_http_error",
                status=exc.response.status_code,
                exc_info=True,
            )
            return ""
        except httpx.RequestError as exc:
            logger.error("claude_api_request_error", error=str(exc), exc_info=True)
            return ""

    # ──────────────────────────────────────────────
    # 持久化 & 推送
    # ──────────────────────────────────────────────
    async def _save_report(self, report: DiagnosisReport) -> None:
        """将诊断报告写入 business_diagnosis_reports 表。"""
        from shared.ontology.src.database import get_db_with_tenant

        anomalies_json = json.dumps([a.model_dump() for a in report.anomalies], ensure_ascii=False, default=str)
        raw_data_json = json.dumps(report.raw_data, ensure_ascii=False, default=str)

        async for db in get_db_with_tenant(self.tenant_id):
            await db.execute(
                text(
                    "INSERT INTO business_diagnosis_reports "
                    "(id, tenant_id, store_id, report_date, anomalies, summary_text, raw_data) "
                    "VALUES (:id::uuid, :tenant_id::uuid, :store_id::uuid, :report_date, "
                    ":anomalies::jsonb, :summary_text, :raw_data::jsonb) "
                    "ON CONFLICT (tenant_id, store_id, report_date) DO UPDATE SET "
                    "anomalies = EXCLUDED.anomalies, summary_text = EXCLUDED.summary_text, "
                    "raw_data = EXCLUDED.raw_data"
                ),
                {
                    "id": report.id,
                    "tenant_id": self.tenant_id,
                    "store_id": self.store_id,
                    "report_date": str(report.report_date),
                    "anomalies": anomalies_json,
                    "summary_text": report.summary_text,
                    "raw_data": raw_data_json,
                },
            )
        logger.info(
            "report_saved",
            report_id=report.id,
            anomaly_count=len(report.anomalies),
        )

    async def _push_to_manager(self, report: DiagnosisReport) -> None:
        """通过 mac-station 推送预警到店长手机端。"""
        if not report.anomalies:
            return

        critical_count = sum(1 for a in report.anomalies if a.severity == AnomalySeverity.CRITICAL)
        payload = {
            "tenant_id": report.tenant_id,
            "store_id": report.store_id,
            "report_id": report.id,
            "report_date": str(report.report_date),
            "anomaly_count": len(report.anomalies),
            "critical_count": critical_count,
            "summary_text": report.summary_text,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self._mac_station_base_url}/push/manager-alert",
                    json=payload,
                    headers={"X-Tenant-ID": self.tenant_id},
                )
                resp.raise_for_status()
                logger.info("manager_alert_pushed", report_id=report.id)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "push_http_error",
                status=exc.response.status_code,
                report_id=report.id,
            )
        except httpx.RequestError as exc:
            logger.warning(
                "push_request_error",
                error=str(exc),
                report_id=report.id,
            )

        await self._notify_wecom(report)
        await self._notify_dingtalk(report)

    # ──────────────────────────────────────────────
    # Stub：第三方通知（待实现）
    # ──────────────────────────────────────────────
    async def _notify_wecom(self, report: DiagnosisReport) -> None:
        """发送企业微信群机器人通知。

        配置：WECOM_ROBOT_WEBHOOK_URL 环境变量（群机器人 Webhook URL）。
        """
        webhook_url = os.getenv("WECOM_ROBOT_WEBHOOK_URL")
        if not webhook_url:
            return
        critical_count = sum(1 for a in report.anomalies if a.severity == AnomalySeverity.CRITICAL)
        content = (
            f"【经营诊断预警】{report.report_date}\n"
            f"门店ID：{report.store_id}\n"
            f"发现异常：{len(report.anomalies)} 条（其中严重 {critical_count} 条）\n"
            f"{report.summary_text[:200]}"
        )
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    webhook_url,
                    json={"msgtype": "text", "text": {"content": content}},
                )
                logger.info("wecom_notification_sent", report_id=report.id)
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("wecom_notification_failed", error=str(exc), report_id=report.id)

    async def _notify_dingtalk(self, report: DiagnosisReport) -> None:
        """发送钉钉自定义机器人通知。

        配置：DINGTALK_ROBOT_WEBHOOK_URL 环境变量（自定义机器人 Webhook URL）。
        """
        webhook_url = os.getenv("DINGTALK_ROBOT_WEBHOOK_URL")
        if not webhook_url:
            return
        critical_count = sum(1 for a in report.anomalies if a.severity == AnomalySeverity.CRITICAL)
        content = (
            f"【经营诊断预警】{report.report_date}\n"
            f"门店ID：{report.store_id}\n"
            f"发现异常：{len(report.anomalies)} 条（其中严重 {critical_count} 条）\n"
            f"{report.summary_text[:200]}"
        )
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    webhook_url,
                    json={"msgtype": "text", "text": {"content": content}},
                )
                logger.info("dingtalk_notification_sent", report_id=report.id)
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("dingtalk_notification_failed", error=str(exc), report_id=report.id)
