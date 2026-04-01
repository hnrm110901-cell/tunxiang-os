"""OperationPlanner — 高风险操作安全审批层（Plan Mode）

对以下操作强制要求：
1. 影响分析（AI生成，展示受影响范围）
2. 人工确认（操作者明确确认）
3. 执行留痕（写入 operation_plans 表）

触发条件：
- 菜品批量改价：影响门店数 >= 3
- 薪资重算：始终触发
- 会员积分调整：影响会员数 >= 100
- 快速开店克隆：始终触发
- 角色批量变更：影响员工数 >= 10
- 食材价格调整：变动幅度 >= 20%
"""
from __future__ import annotations

import dataclasses
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import String, Boolean, DateTime, Text, func, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

logger = structlog.get_logger()


# ── ORM Model ────────────────────────────────────────────────────────────────

class OperationPlanModel(TenantBase):
    """operation_plans 表 ORM 映射（TenantBase 已包含 id/tenant_id/created_at/updated_at/is_deleted）"""
    __tablename__ = "operation_plans"

    operation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    operation_params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    impact_analysis: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_confirm")
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    operator_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OperationStatus(str, Enum):
    PENDING_CONFIRM = "pending_confirm"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXECUTED = "executed"
    FAILED = "failed"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ImpactAnalysis:
    """操作影响分析"""
    affected_stores: int = 0
    affected_employees: int = 0
    affected_members: int = 0
    financial_impact_fen: int = 0      # 预估财务影响（分）
    risk_level: RiskLevel = RiskLevel.LOW
    impact_summary: str = ""           # AI生成的影响摘要
    warnings: list[str] = field(default_factory=list)  # 需特别注意的风险点
    reversible: bool = True            # 操作是否可逆


@dataclass
class OperationPlan:
    """待确认的操作计划"""
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    operation_type: str = ""           # 操作类型标识
    operation_params: dict = field(default_factory=dict)
    impact: ImpactAnalysis = field(default_factory=ImpactAnalysis)
    status: OperationStatus = OperationStatus.PENDING_CONFIRM
    operator_id: str = ""              # 发起人
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None  # 确认超时时间（默认30分钟）


# 触发 Plan Mode 的阈值配置
PLAN_MODE_RULES: dict[str, dict[str, Any]] = {
    "menu.price.bulk_update": {
        "threshold_field": "store_count",
        "threshold_value": 3,
        "description": "菜品批量改价影响门店数 >= 3",
    },
    "payroll.recalculate": {
        "threshold_field": "always",
        "threshold_value": 0,
        "description": "薪资重算始终需要确认",
    },
    "member.points.bulk_adjust": {
        "threshold_field": "member_count",
        "threshold_value": 100,
        "description": "会员积分调整影响会员数 >= 100",
    },
    "store.clone": {
        "threshold_field": "always",
        "threshold_value": 0,
        "description": "快速开店克隆始终需要确认",
    },
    "org.role.bulk_change": {
        "threshold_field": "employee_count",
        "threshold_value": 10,
        "description": "角色批量变更影响员工数 >= 10",
    },
    "supply.price.bulk_update": {
        "threshold_field": "price_change_pct",
        "threshold_value": 20,
        "description": "食材价格调整幅度 >= 20%",
    },
}


class OperationPlanner:
    """高风险操作安全审批层"""

    def __init__(self, model_router: Any, db: AsyncSession) -> None:
        self.router = model_router
        self.db = db

    def should_plan(self, operation_type: str, params: dict[str, Any]) -> bool:
        """判断操作是否需要进入 Plan Mode"""
        rule = PLAN_MODE_RULES.get(operation_type)
        if not rule:
            return False

        threshold_field = rule["threshold_field"]
        if threshold_field == "always":
            return True

        actual_value = params.get(threshold_field, 0)
        return actual_value >= rule["threshold_value"]

    async def submit(
        self,
        operation_type: str,
        params: dict[str, Any],
        operator_id: str,
        tenant_id: str,
    ) -> OperationPlan | None:
        """
        提交操作请求。

        Returns:
            OperationPlan: 需要确认的计划（触发了 Plan Mode）
            None: 不需要 Plan Mode，调用方直接执行
        """
        if not self.should_plan(operation_type, params):
            return None

        impact = await self._analyze_impact(operation_type, params, tenant_id)

        record = OperationPlanModel(
            tenant_id=UUID(tenant_id),
            operation_type=operation_type,
            operation_params=params,
            impact_analysis=dataclasses.asdict(impact),
            status=OperationStatus.PENDING_CONFIRM.value,
            risk_level=impact.risk_level.value,
            operator_id=UUID(operator_id),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        self.db.add(record)
        await self.db.flush()

        plan = self._model_to_plan(record)

        logger.info(
            "operation_plan_created",
            plan_id=plan.plan_id,
            operation_type=operation_type,
            risk_level=impact.risk_level,
            operator_id=operator_id,
        )

        # 异步发送通知（企微 + Redis），失败不阻断主业务
        import asyncio
        from .plan_notifier import OperationPlanNotifier
        asyncio.create_task(OperationPlanNotifier.notify(plan))

        return plan

    async def confirm(self, plan_id: str, operator_id: str) -> bool:
        """操作者确认执行（SELECT FOR UPDATE 防并发重复确认）"""
        result = await self.db.execute(
            select(OperationPlanModel)
            .where(
                OperationPlanModel.id == UUID(plan_id),
                OperationPlanModel.is_deleted == False,
            )
            .with_for_update()
        )
        record = result.scalar_one_or_none()

        if not record:
            logger.warning("operation_plan_not_found", plan_id=plan_id)
            return False

        if record.status != OperationStatus.PENDING_CONFIRM.value:
            logger.warning(
                "operation_plan_not_pending",
                plan_id=plan_id,
                status=record.status,
            )
            return False

        now = datetime.now(timezone.utc)
        if record.expires_at and now > record.expires_at:
            record.status = OperationStatus.CANCELLED.value
            logger.warning("operation_plan_expired", plan_id=plan_id)
            return False

        record.status = OperationStatus.CONFIRMED.value
        record.confirmed_by = UUID(operator_id)
        record.confirmed_at = now
        record.updated_at = now

        logger.info(
            "operation_plan_confirmed",
            plan_id=plan_id,
            confirmed_by=operator_id,
        )
        return True

    async def cancel(self, plan_id: str, operator_id: str) -> bool:
        """操作者取消"""
        result = await self.db.execute(
            select(OperationPlanModel)
            .where(
                OperationPlanModel.id == UUID(plan_id),
                OperationPlanModel.is_deleted == False,
            )
            .with_for_update()
        )
        record = result.scalar_one_or_none()

        if not record or record.status != OperationStatus.PENDING_CONFIRM.value:
            return False

        record.status = OperationStatus.CANCELLED.value
        record.updated_at = datetime.now(timezone.utc)

        logger.info(
            "operation_plan_cancelled",
            plan_id=plan_id,
            cancelled_by=operator_id,
        )
        return True

    async def get_plan(self, plan_id: str) -> Optional[OperationPlan]:
        result = await self.db.execute(
            select(OperationPlanModel).where(
                OperationPlanModel.id == UUID(plan_id),
                OperationPlanModel.is_deleted == False,
            )
        )
        record = result.scalar_one_or_none()
        return self._model_to_plan(record) if record else None

    async def get_pending_plans(
        self,
        tenant_id: str,
        operator_id: Optional[str] = None,
    ) -> list[OperationPlan]:
        """获取待确认的操作计划列表"""
        stmt = (
            select(OperationPlanModel)
            .where(
                OperationPlanModel.tenant_id == UUID(tenant_id),
                OperationPlanModel.status == OperationStatus.PENDING_CONFIRM.value,
                OperationPlanModel.is_deleted == False,
            )
            .order_by(OperationPlanModel.created_at.desc())
        )
        if operator_id:
            stmt = stmt.where(OperationPlanModel.operator_id == UUID(operator_id))

        result = await self.db.execute(stmt)
        return [self._model_to_plan(r) for r in result.scalars().all()]

    def _model_to_plan(self, record: OperationPlanModel) -> OperationPlan:
        """将 DB 记录转换为 OperationPlan dataclass"""
        impact_data = record.impact_analysis or {}
        impact = ImpactAnalysis(
            affected_stores=impact_data.get("affected_stores", 0),
            affected_employees=impact_data.get("affected_employees", 0),
            affected_members=impact_data.get("affected_members", 0),
            financial_impact_fen=impact_data.get("financial_impact_fen", 0),
            risk_level=RiskLevel(impact_data.get("risk_level", RiskLevel.MEDIUM.value)),
            impact_summary=impact_data.get("impact_summary", ""),
            warnings=impact_data.get("warnings", []),
            reversible=impact_data.get("reversible", True),
        )
        return OperationPlan(
            plan_id=str(record.id),
            tenant_id=str(record.tenant_id),
            operation_type=record.operation_type,
            operation_params=record.operation_params or {},
            impact=impact,
            status=OperationStatus(record.status),
            operator_id=str(record.operator_id),
            confirmed_by=str(record.confirmed_by) if record.confirmed_by else None,
            confirmed_at=record.confirmed_at,
            executed_at=record.executed_at,
            created_at=record.created_at,
            expires_at=record.expires_at,
        )

    async def _analyze_impact(
        self,
        operation_type: str,
        params: dict[str, Any],
        tenant_id: str,
    ) -> ImpactAnalysis:
        """用 AI 分析操作影响范围"""
        rule_desc = PLAN_MODE_RULES.get(operation_type, {}).get("description", operation_type)

        prompt = f"""分析以下高风险操作的影响范围，给出简洁的风险评估。

操作类型：{operation_type}
操作说明：{rule_desc}
操作参数：{params}

请以JSON格式输出（不要markdown）：
{{
  "affected_stores": 受影响门店数（整数），
  "affected_employees": 受影响员工数（整数），
  "affected_members": 受影响会员数（整数），
  "financial_impact_fen": 预估财务影响金额（分，整数，不确定填0），
  "risk_level": "low/medium/high/critical",
  "impact_summary": "一段话描述影响范围和注意事项",
  "warnings": ["需特别注意的风险点1", "风险点2"],
  "reversible": true或false
}}"""

        try:
            response = await self.router.complete(
                tenant_id=tenant_id,
                task_type="quick_classification",
                messages=[{"role": "user", "content": prompt}],
            )
            data: dict[str, Any] = json.loads(response.content[0].text)
            return ImpactAnalysis(
                affected_stores=data.get("affected_stores", 0),
                affected_employees=data.get("affected_employees", 0),
                affected_members=data.get("affected_members", 0),
                financial_impact_fen=data.get("financial_impact_fen", 0),
                risk_level=RiskLevel(data.get("risk_level", "medium")),
                impact_summary=data.get("impact_summary", ""),
                warnings=data.get("warnings", []),
                reversible=data.get("reversible", True),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("impact_analysis_failed", error=str(exc))
            # 降级：返回保守的高风险估计
            return ImpactAnalysis(
                risk_level=RiskLevel.HIGH,
                impact_summary="影响分析失败，请人工评估后再确认执行。",
                reversible=False,
            )
