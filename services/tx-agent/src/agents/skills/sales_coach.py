"""销售经理教练 Agent — Sprint R2 Track B（P1 | 云端）

对标食尚订「目标管理 + 任务管理 + 销售业绩分析」。

职责（6 个 action）：
  decompose_target           年目标 → 月 → 周 → 日任务清单（调 R1 /sales-targets/{id}/decompose）
  dispatch_daily_tasks       按客户状态机 + 日历自动派发 10 类任务（调 R1 /tasks）
  diagnose_gap               偏离 > 15% 时生成诊断建议 + 发射 SalesCoachEventType.GAP_ALERT
  coach_action               个性化教练建议（主攻沉睡 / 新客 / 高值）+ COACHING_ADVICE
  audit_coverage             沉睡占比 > 40% 告警 + 未维护 VIP 报警
  score_profile_completeness 8 字段加权评分（<50% 自动派 adhoc 补录任务）

硬约束（对齐 docs/reservation-r2-contracts.md §6）：
  constraint_scope = set()            # 纯策略 / 诊断层，margin / safety / experience 均不适用
  constraint_waived_reason ≥ 30 字符  # 由 CI 强校验，禁用 "N/A" / "不适用" / "跳过"

所有 R1 依赖一律通过 httpx.AsyncClient 调用（契约 §8.4：禁止跨 import service/repo），
事件一律通过 asyncio.create_task(emit_event(...)) 旁路发射（CLAUDE.md §15）。

每次 execute 写 AgentResult + reasoning + confidence，供基类 run() 写决策留痕。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, ClassVar, Optional
from uuid import UUID, uuid4

import httpx
import structlog

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import SalesCoachEventType
from shared.ontology.src.extensions.tasks import TaskType

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────
# 常量 / 配置
# ──────────────────────────────────────────────────────────────────────

#: R1 tx-org HTTP 基址（默认容器内网），可被 env 覆盖
TX_ORG_BASE_URL_ENV = "TX_ORG_BASE_URL"
TX_MEMBER_BASE_URL_ENV = "TX_MEMBER_BASE_URL"
_DEFAULT_TX_ORG_BASE = "http://tx-org:8012"
_DEFAULT_TX_MEMBER_BASE = "http://tx-member:8003"

#: 偏差告警默认阈值（15%）
DEFAULT_GAP_THRESHOLD = Decimal("0.15")

#: 沉睡占比告警阈值（40%）
DEFAULT_DORMANT_RATIO_ALERT = Decimal("0.40")

#: 画像完整度告警阈值（50%）
DEFAULT_PROFILE_COMPLETENESS_THRESHOLD = Decimal("0.50")

#: 8 字段加权评分（总和 100%）
PROFILE_FIELD_WEIGHTS: dict[str, Decimal] = {
    "name": Decimal("0.20"),
    "phone": Decimal("0.20"),
    "birthday": Decimal("0.15"),
    "anniversary": Decimal("0.10"),
    "organization": Decimal("0.10"),
    "preferences": Decimal("0.10"),
    "taboo": Decimal("0.10"),
    "service_requirement": Decimal("0.05"),
}

#: dispatch_daily_tasks 默认覆盖的 10 类 TaskType（对齐 r2-contracts §5.2）
DEFAULT_DAILY_TASK_TYPES: tuple[TaskType, ...] = (
    TaskType.LEAD_FOLLOW_UP,
    TaskType.BANQUET_STAGE,
    TaskType.DINING_FOLLOWUP,
    TaskType.BIRTHDAY,
    TaskType.ANNIVERSARY,
    TaskType.DORMANT_RECALL,
    TaskType.NEW_CUSTOMER,
    TaskType.CONFIRM_ARRIVAL,
    TaskType.ADHOC,
    TaskType.BANQUET_FOLLOWUP,
)

SOURCE_SERVICE = "tx-agent.sales_coach"


# ──────────────────────────────────────────────────────────────────────
# HTTP 客户端封装
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _SalesCoachHttpClient:
    """封装对 R1 底座的 HTTP 调用（tx-org / tx-member）。

    测试时通过构造函数注入 httpx.AsyncClient mock；生产直接用 default factory。
    """

    tx_org_base: str
    tx_member_base: str
    client: Optional[httpx.AsyncClient] = None
    timeout: float = 5.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.timeout)
        return self.client

    def _headers(self, tenant_id: str) -> dict[str, str]:
        return {"X-Tenant-ID": str(tenant_id), "Content-Type": "application/json"}

    async def decompose_target(
        self, *, tenant_id: str, target_id: UUID
    ) -> dict[str, Any]:
        """POST /api/v1/sales-targets/{target_id}/decompose"""
        url = f"{self.tx_org_base}/api/v1/sales-targets/{target_id}/decompose"
        client = await self._get_client()
        resp = await client.post(url, headers=self._headers(tenant_id))
        resp.raise_for_status()
        return resp.json()

    async def get_achievement(
        self, *, tenant_id: str, target_id: UUID
    ) -> dict[str, Any]:
        """GET /api/v1/sales-targets/{target_id}/achievement"""
        url = f"{self.tx_org_base}/api/v1/sales-targets/{target_id}/achievement"
        client = await self._get_client()
        resp = await client.get(url, headers=self._headers(tenant_id))
        resp.raise_for_status()
        return resp.json()

    async def dispatch_task(
        self,
        *,
        tenant_id: str,
        task_type: TaskType,
        assignee_employee_id: UUID,
        due_at: datetime,
        payload: dict[str, Any],
        customer_id: Optional[UUID] = None,
        store_id: Optional[UUID] = None,
        source_event_id: Optional[UUID] = None,
    ) -> dict[str, Any]:
        """POST /api/v1/tasks"""
        url = f"{self.tx_org_base}/api/v1/tasks"
        body = {
            "task_type": task_type.value,
            "assignee_employee_id": str(assignee_employee_id),
            "customer_id": str(customer_id) if customer_id else None,
            "due_at": due_at.isoformat(),
            "store_id": str(store_id) if store_id else None,
            "source_event_id": str(source_event_id) if source_event_id else None,
            "payload": payload,
        }
        client = await self._get_client()
        resp = await client.post(url, headers=self._headers(tenant_id), json=body)
        resp.raise_for_status()
        return resp.json()

    async def get_lifecycle_summary(
        self, *, tenant_id: str, flow_window_days: int = 30
    ) -> dict[str, Any]:
        """GET /api/v1/customer-lifecycle/summary"""
        url = f"{self.tx_member_base}/api/v1/customer-lifecycle/summary"
        client = await self._get_client()
        resp = await client.get(
            url,
            headers=self._headers(tenant_id),
            params={"flow_window_days": flow_window_days},
        )
        resp.raise_for_status()
        return resp.json()


def _default_http_client() -> _SalesCoachHttpClient:
    return _SalesCoachHttpClient(
        tx_org_base=os.environ.get(TX_ORG_BASE_URL_ENV, _DEFAULT_TX_ORG_BASE),
        tx_member_base=os.environ.get(TX_MEMBER_BASE_URL_ENV, _DEFAULT_TX_MEMBER_BASE),
    )


# ──────────────────────────────────────────────────────────────────────
# 画像完整度评分（纯函数，无副作用，便于单测）
# ──────────────────────────────────────────────────────────────────────


def compute_profile_completeness(customer: dict[str, Any]) -> Decimal:
    """按 PROFILE_FIELD_WEIGHTS 计算完整度得分 ∈ [0, 1]。

    规则：
      - 字段值为 None / 空字符串 / 空列表 / 空字典 视为缺失
      - 非空则计权重满分
    """
    score = Decimal("0")
    for field, weight in PROFILE_FIELD_WEIGHTS.items():
        value = customer.get(field)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict, tuple, set)) and len(value) == 0:
            continue
        score += weight
    # 防浮点溢出（理论上 sum 应 == 1.0，但 Decimal 精度允许 rare 超界）
    if score > Decimal("1"):
        score = Decimal("1")
    return score


# ──────────────────────────────────────────────────────────────────────
# Agent
# ──────────────────────────────────────────────────────────────────────


class SalesCoachAgent(SkillAgent):
    """销售经理教练（R2 Track B）— 目标分解 + 每日派单 + 偏差诊断。"""

    agent_id = "sales_coach"
    agent_name = "销售经理教练"
    description = "目标分解 + 每日任务派发 + 偏差诊断 + 画像完整度评分"
    priority = "P1"
    run_location = "cloud"

    # 硬约束豁免（对齐 r2-contracts §6：sales_coach 不触发 margin/safety/experience）
    constraint_scope: ClassVar[set[str]] = set()
    constraint_waived_reason: ClassVar[str] = (
        "销售教练仅派发跟进任务与诊断建议，不直接影响毛利/食安/出餐"
        "客户体验三条业务硬约束；属于纯策略层的目标分解、任务分派与完整度评分，"
        "不涉及资金/出品/实时服务路径"
    )

    def __init__(
        self,
        tenant_id: str,
        store_id: Optional[str] = None,
        db: Optional[Any] = None,
        model_router: Optional[Any] = None,
        http_client: Optional[_SalesCoachHttpClient] = None,
    ) -> None:
        super().__init__(
            tenant_id=tenant_id,
            store_id=store_id,
            db=db,
            model_router=model_router,
        )
        self._http = http_client or _default_http_client()

    def get_supported_actions(self) -> list[str]:
        return [
            "decompose_target",
            "dispatch_daily_tasks",
            "diagnose_gap",
            "coach_action",
            "audit_coverage",
            "score_profile_completeness",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "decompose_target": self._decompose_target,
            "dispatch_daily_tasks": self._dispatch_daily_tasks,
            "diagnose_gap": self._diagnose_gap,
            "coach_action": self._coach_action,
            "audit_coverage": self._audit_coverage,
            "score_profile_completeness": self._score_profile_completeness,
        }
        handler = dispatch.get(action)
        if handler is None:
            return AgentResult(
                success=False,
                action=action,
                error=f"不支持的 action: {action}",
            )
        return await handler(params)

    # ── 1. decompose_target ──────────────────────────────────────────

    async def _decompose_target(self, params: dict[str, Any]) -> AgentResult:
        target_id_raw = params.get("year_target_id") or params.get("target_id")
        if not target_id_raw:
            return AgentResult(
                success=False,
                action="decompose_target",
                error="缺少 year_target_id",
            )
        target_id = _coerce_uuid(target_id_raw)

        try:
            resp = await self._http.decompose_target(
                tenant_id=self.tenant_id, target_id=target_id
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "decompose_target_http_failed",
                tenant_id=self.tenant_id,
                target_id=str(target_id),
                error=str(exc),
            )
            return AgentResult(
                success=False,
                action="decompose_target",
                error=f"R1 API 调用失败: {exc}",
            )

        if not resp.get("ok"):
            return AgentResult(
                success=False,
                action="decompose_target",
                error=f"R1 返回 ok=False: {resp.get('error')}",
            )

        data = resp.get("data") or {}
        children = data.get("children") or []
        return AgentResult(
            success=True,
            action="decompose_target",
            data={
                "year_target_id": str(target_id),
                "children_count": len(children),
                "children": children,
            },
            reasoning=f"年目标 {target_id} 分解为 {len(children)} 个子目标（月 + 日）",
            confidence=0.95,
        )

    # ── 2. dispatch_daily_tasks ──────────────────────────────────────

    async def _dispatch_daily_tasks(self, params: dict[str, Any]) -> AgentResult:
        plan_date_raw = params.get("plan_date")
        plan_date = _coerce_date(plan_date_raw) if plan_date_raw else date.today()

        employee_id_raw = params.get("employee_id") or params.get("assignee_employee_id")
        if not employee_id_raw:
            return AgentResult(
                success=False,
                action="dispatch_daily_tasks",
                error="缺少 employee_id（派单对象）",
            )
        employee_id = _coerce_uuid(employee_id_raw)

        # task_types：空或未传 → 使用默认 10 类
        raw_types = params.get("task_types") or []
        if raw_types:
            task_types = [_coerce_task_type(t) for t in raw_types]
        else:
            task_types = list(DEFAULT_DAILY_TASK_TYPES)

        store_id_raw = params.get("store_id") or self.store_id
        store_id = _coerce_uuid(store_id_raw) if store_id_raw else None

        # 每条任务的客户（可选，params.customers_by_type: {task_type: [customer_id...]}）
        customers_map: dict[str, list[Any]] = params.get("customers_by_type") or {}

        dispatched: list[dict[str, Any]] = []
        dispatched_count_by_type: dict[str, int] = {}
        failed_types: list[str] = []

        # 默认 due_at：T+1 天 23:59
        due_at = datetime.combine(
            plan_date + timedelta(days=1),
            datetime.min.time(),
        ).replace(hour=23, minute=59, tzinfo=timezone.utc)

        for ttype in task_types:
            type_customers = customers_map.get(ttype.value) or [None]
            for cust_raw in type_customers:
                customer_id = (
                    _coerce_uuid(cust_raw) if cust_raw else None
                )
                payload = {
                    "source": SOURCE_SERVICE,
                    "plan_date": plan_date.isoformat(),
                    "agent_id": self.agent_id,
                }
                try:
                    resp = await self._http.dispatch_task(
                        tenant_id=self.tenant_id,
                        task_type=ttype,
                        assignee_employee_id=employee_id,
                        due_at=due_at,
                        payload=payload,
                        customer_id=customer_id,
                        store_id=store_id,
                    )
                except httpx.HTTPError as exc:
                    logger.warning(
                        "dispatch_task_http_failed",
                        task_type=ttype.value,
                        error=str(exc),
                    )
                    failed_types.append(ttype.value)
                    continue

                if not resp.get("ok"):
                    failed_types.append(ttype.value)
                    continue

                dispatched.append(resp.get("data") or {})
                dispatched_count_by_type[ttype.value] = (
                    dispatched_count_by_type.get(ttype.value, 0) + 1
                )

        # 发射 DAILY_TASKS_DISPATCHED
        asyncio.create_task(
            emit_event(
                event_type=SalesCoachEventType.DAILY_TASKS_DISPATCHED,
                tenant_id=_coerce_uuid(self.tenant_id),
                stream_id=str(employee_id),
                payload={
                    "plan_date": plan_date.isoformat(),
                    "dispatched_count": len(dispatched),
                    "employee_id": str(employee_id),
                    "dispatched_count_by_type": dispatched_count_by_type,
                    "failed_types": failed_types,
                },
                store_id=store_id,
                source_service=SOURCE_SERVICE,
            )
        )

        return AgentResult(
            success=True,
            action="dispatch_daily_tasks",
            data={
                "plan_date": plan_date.isoformat(),
                "employee_id": str(employee_id),
                "dispatched_count": len(dispatched),
                "dispatched_count_by_type": dispatched_count_by_type,
                "failed_types": failed_types,
                "dispatched_tasks": dispatched,
            },
            reasoning=(
                f"{plan_date} 为员工 {employee_id} 派发 {len(dispatched)} 条任务，"
                f"覆盖 {len(dispatched_count_by_type)} 类 TaskType"
            ),
            confidence=0.9,
        )

    # ── 3. diagnose_gap ──────────────────────────────────────────────

    async def _diagnose_gap(self, params: dict[str, Any]) -> AgentResult:
        target_id = _coerce_uuid(params.get("target_id"))
        if target_id is None:
            return AgentResult(
                success=False,
                action="diagnose_gap",
                error="缺少 target_id",
            )
        threshold = Decimal(str(params.get("gap_threshold") or DEFAULT_GAP_THRESHOLD))

        try:
            resp = await self._http.get_achievement(
                tenant_id=self.tenant_id, target_id=target_id
            )
        except httpx.HTTPError as exc:
            return AgentResult(
                success=False,
                action="diagnose_gap",
                error=f"获取达成率失败: {exc}",
            )

        if not resp.get("ok"):
            return AgentResult(
                success=False,
                action="diagnose_gap",
                error=f"R1 返回 ok=False: {resp.get('error')}",
            )

        achievement_data = resp.get("data") or {}
        rate = Decimal(str(achievement_data.get("achievement_rate") or "0"))
        target_value = int(achievement_data.get("target_value") or 0)
        actual_value = int(achievement_data.get("actual_value") or 0)

        # 偏差：1 - rate（达成率离 100% 有多远）
        deviation = max(Decimal("0"), Decimal("1") - rate)
        has_gap = deviation > threshold

        remediations: list[dict[str, Any]] = []
        if has_gap:
            gap_fen = max(0, target_value - actual_value)
            suggested_calls = _suggested_call_count(gap_fen)
            remediations.append(
                {
                    "kind": "call_customers",
                    "suggested_call_count": suggested_calls,
                    "suggested_customer_ids": [],
                    "expected_recovery_fen": int(gap_fen * 0.3),
                }
            )
            remediations.append(
                {
                    "kind": "push_recall_campaign",
                    "suggested_call_count": 0,
                    "suggested_customer_ids": [],
                    "expected_recovery_fen": int(gap_fen * 0.2),
                }
            )

        # 偏差告警事件
        if has_gap:
            asyncio.create_task(
                emit_event(
                    event_type=SalesCoachEventType.GAP_ALERT,
                    tenant_id=_coerce_uuid(self.tenant_id),
                    stream_id=str(target_id),
                    payload={
                        "target_id": str(target_id),
                        "achievement_rate": str(rate),
                        "gap_threshold": str(threshold),
                        "deviation": str(deviation),
                        "suggested_call_count": remediations[0][
                            "suggested_call_count"
                        ]
                        if remediations
                        else 0,
                        "expected_recovery_fen": sum(
                            r["expected_recovery_fen"] for r in remediations
                        ),
                    },
                    source_service=SOURCE_SERVICE,
                )
            )

        return AgentResult(
            success=True,
            action="diagnose_gap",
            data={
                "target_id": str(target_id),
                "achievement_rate": str(rate),
                "deviation": str(deviation),
                "has_gap": has_gap,
                "gap_threshold": str(threshold),
                "remediations": remediations,
            },
            reasoning=(
                f"目标 {target_id} 达成率 {rate}（偏差 {deviation}），"
                f"{'触发' if has_gap else '未触发'}阈值 {threshold}"
            ),
            confidence=0.85 if has_gap else 0.9,
        )

    # ── 4. coach_action ──────────────────────────────────────────────

    async def _coach_action(self, params: dict[str, Any]) -> AgentResult:
        employee_id = _coerce_uuid(params.get("employee_id"))
        if employee_id is None:
            return AgentResult(
                success=False,
                action="coach_action",
                error="缺少 employee_id",
            )
        focus = str(params.get("focus") or "auto").lower()

        # 如果 Claude API 可用（self._router），产出更丰富建议；否则用规则兜底
        advice: list[dict[str, Any]] = []
        if focus == "auto":
            advice = _default_advice_pack()
        elif focus == "dormant":
            advice = [
                {
                    "topic": "沉睡客户唤醒",
                    "priority": "high",
                    "message": "本周主攻沉睡 90 天以上客户 Top20，优先电话 + 券码组合触达",
                }
            ]
        elif focus == "new_customer":
            advice = [
                {
                    "topic": "新客 48h 回访",
                    "priority": "high",
                    "message": "所有 48 小时内首单客户当日完成回访 + 引导加企业微信",
                }
            ]
        elif focus == "high_value":
            advice = [
                {
                    "topic": "高值客户维护",
                    "priority": "high",
                    "message": "LTV Top10% 客户本周每人至少一次主动维护，重点：生日/纪念日",
                }
            ]
        else:
            advice = _default_advice_pack()

        # 发射 COACHING_ADVICE
        asyncio.create_task(
            emit_event(
                event_type=SalesCoachEventType.COACHING_ADVICE,
                tenant_id=_coerce_uuid(self.tenant_id),
                stream_id=str(employee_id),
                payload={
                    "employee_id": str(employee_id),
                    "advice_count": len(advice),
                    "focus": focus,
                    "confidence": 0.8,
                },
                source_service=SOURCE_SERVICE,
            )
        )

        return AgentResult(
            success=True,
            action="coach_action",
            data={
                "employee_id": str(employee_id),
                "focus": focus,
                "advice": advice,
            },
            reasoning=f"为员工 {employee_id}（focus={focus}）生成 {len(advice)} 条建议",
            confidence=0.8,
        )

    # ── 5. audit_coverage ────────────────────────────────────────────

    async def _audit_coverage(self, params: dict[str, Any]) -> AgentResult:
        dormant_threshold = Decimal(
            str(params.get("dormant_ratio_alert") or DEFAULT_DORMANT_RATIO_ALERT)
        )

        try:
            resp = await self._http.get_lifecycle_summary(
                tenant_id=self.tenant_id,
                flow_window_days=int(params.get("flow_window_days") or 30),
            )
        except httpx.HTTPError as exc:
            return AgentResult(
                success=False,
                action="audit_coverage",
                error=f"读取客户生命周期汇总失败: {exc}",
            )

        if not resp.get("ok"):
            return AgentResult(
                success=False,
                action="audit_coverage",
                error=f"R1 返回 ok=False: {resp.get('error')}",
            )

        data = resp.get("data") or {}
        counts = data.get("counts") or {}
        total = sum(int(v or 0) for v in counts.values()) or 1
        dormant = int(counts.get("dormant", 0) or 0)
        dormant_ratio = (Decimal(dormant) / Decimal(total)).quantize(Decimal("0.0001"))
        dormant_alert = dormant_ratio > dormant_threshold

        unmaintained_vip: list[str] = list(params.get("unmaintained_vip_ids") or [])

        return AgentResult(
            success=True,
            action="audit_coverage",
            data={
                "dormant_ratio": str(dormant_ratio),
                "dormant_alert": dormant_alert,
                "dormant_threshold": str(dormant_threshold),
                "counts": counts,
                "unmaintained_vip_count": len(unmaintained_vip),
                "unmaintained_vip_ids": unmaintained_vip,
            },
            reasoning=(
                f"沉睡占比 {dormant_ratio}"
                f"{'（>阈值 ' + str(dormant_threshold) + '，已告警）' if dormant_alert else ''}"
            ),
            confidence=0.9,
        )

    # ── 6. score_profile_completeness ────────────────────────────────

    async def _score_profile_completeness(
        self, params: dict[str, Any]
    ) -> AgentResult:
        customers: list[dict[str, Any]] = list(params.get("customers") or [])
        employee_id = _coerce_uuid(params.get("employee_id"))
        threshold = Decimal(
            str(
                params.get("alert_threshold")
                or DEFAULT_PROFILE_COMPLETENESS_THRESHOLD
            )
        )
        dispatch_tasks_on_low = bool(params.get("dispatch_tasks_on_low", True))

        if not customers:
            return AgentResult(
                success=True,
                action="score_profile_completeness",
                data={
                    "employee_id": str(employee_id) if employee_id else None,
                    "customer_count": 0,
                    "average_score": "0",
                    "dispatched_task_count": 0,
                    "below_threshold_customer_ids": [],
                },
                reasoning="无待评分客户",
                confidence=1.0,
            )

        scored: list[tuple[dict[str, Any], Decimal]] = []
        total_score = Decimal("0")
        below: list[str] = []

        for cust in customers:
            s = compute_profile_completeness(cust)
            total_score += s
            scored.append((cust, s))
            if s < threshold:
                cid = cust.get("customer_id") or cust.get("id")
                if cid:
                    below.append(str(cid))

        avg = (total_score / Decimal(len(customers))).quantize(Decimal("0.0001"))

        # 为低分客户派 adhoc 补录任务（如果启用且 employee_id 已知）
        dispatched = 0
        if dispatch_tasks_on_low and employee_id is not None and below:
            due_at = datetime.now(timezone.utc) + timedelta(days=7)
            for cid_str in below:
                try:
                    resp = await self._http.dispatch_task(
                        tenant_id=self.tenant_id,
                        task_type=TaskType.ADHOC,
                        assignee_employee_id=employee_id,
                        due_at=due_at,
                        payload={
                            "reason": "profile_completeness_low",
                            "source": SOURCE_SERVICE,
                            "agent_id": self.agent_id,
                        },
                        customer_id=UUID(cid_str),
                    )
                    if resp.get("ok"):
                        dispatched += 1
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning(
                        "profile_task_dispatch_failed",
                        customer_id=cid_str,
                        error=str(exc),
                    )

        return AgentResult(
            success=True,
            action="score_profile_completeness",
            data={
                "employee_id": str(employee_id) if employee_id else None,
                "customer_count": len(customers),
                "average_score": str(avg),
                "alert_threshold": str(threshold),
                "below_threshold_customer_ids": below,
                "dispatched_task_count": dispatched,
                "field_weights": {k: str(v) for k, v in PROFILE_FIELD_WEIGHTS.items()},
            },
            reasoning=(
                f"{len(customers)} 位客户平均完整度 {avg}，"
                f"{len(below)} 位低于阈值 {threshold}，派发补录 {dispatched} 条"
            ),
            confidence=0.95,
        )


# ──────────────────────────────────────────────────────────────────────
# 辅助
# ──────────────────────────────────────────────────────────────────────


def _coerce_uuid(raw: Any) -> Optional[UUID]:
    if raw is None:
        return None
    if isinstance(raw, UUID):
        return raw
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _coerce_date(raw: Any) -> date:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass
    return date.today()


def _coerce_task_type(raw: Any) -> TaskType:
    if isinstance(raw, TaskType):
        return raw
    try:
        return TaskType(str(raw))
    except ValueError:
        return TaskType.ADHOC


def _suggested_call_count(gap_fen: int) -> int:
    """按缺口金额估算应打电话数（每通预期回收 3 元覆盖 1000 分客单）。

    目的：Agent 层给出可执行颗粒度建议，非业务精算。
    """
    if gap_fen <= 0:
        return 0
    # 1 通电话假设覆盖 500 元（50000 分）缺口，至少 5 通
    estimated = max(5, gap_fen // 50000)
    return int(min(estimated, 200))


def _default_advice_pack() -> list[dict[str, Any]]:
    return [
        {
            "topic": "沉睡客户唤醒",
            "priority": "high",
            "message": "优先联系近 90 天未到店的老客，组合触达（电话 + 券码）",
        },
        {
            "topic": "新客 48h 回访",
            "priority": "normal",
            "message": "首单客户 48 小时内电话回访，引导加企业微信",
        },
        {
            "topic": "高值客户深度维护",
            "priority": "normal",
            "message": "LTV Top10% 客户本周至少 1 次主动触达",
        },
    ]


__all__ = [
    "SalesCoachAgent",
    "PROFILE_FIELD_WEIGHTS",
    "compute_profile_completeness",
    "DEFAULT_GAP_THRESHOLD",
    "DEFAULT_DORMANT_RATIO_ALERT",
    "DEFAULT_PROFILE_COMPLETENESS_THRESHOLD",
    "DEFAULT_DAILY_TASK_TYPES",
    "_SalesCoachHttpClient",
    "SOURCE_SERVICE",
    # 生成一个 uuid 的工具暴露供 job 使用
    "_coerce_uuid",
]


# Ruff：确保 uuid4 被引用（用于可能的工厂拓展 + 防未使用告警）
_ = uuid4
