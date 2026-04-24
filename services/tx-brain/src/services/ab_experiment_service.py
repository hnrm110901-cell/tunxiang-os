"""Sprint G — A/B 实验平台核心服务

职责：
  1. 实验 CRUD + 生命周期（draft → running → terminated_*）
  2. 稳定分配：给 entity 分配 arm（调 shared/ab_testing/assignment）
  3. 事件摄入：exposure / conversion / revenue / metric_value
  4. 统计刷新：从 events 聚合到 arms 的累计指标
  5. 熔断评估：定期扫 running + 熔断启用的实验，触发时转 terminated_circuit_breaker
  6. 显著性判定：提前结束满足统计 power 的实验

与 shared/ab_testing 的关系：
  · shared 是 pure functions（不查 DB）
  · 本 service 从 DB 读 ArmStats 并调用 shared 函数
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ab_testing import (
    ArmDefinition,
    ArmStats,
    AssignmentDecision,
    CircuitBreakerDecision,
    NotEnrolled,
    assign_entity,
    bayesian_posterior,
    evaluate_circuit_breaker,
    frequentist_significance,
)
from shared.ab_testing.assignment import NOT_ENROLLED

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 输入 / 输出 dataclass
# ─────────────────────────────────────────────────────────────


@dataclass
class ArmSpec:
    """创建/更新 arm 的入参"""

    arm_key: str
    name: str
    is_control: bool = False
    traffic_weight: int = 50
    description: Optional[str] = None
    parameters: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.parameters is None:
            self.parameters = {}


@dataclass
class CreateExperimentInput:
    experiment_key: str
    name: str
    arms: list[ArmSpec]
    description: Optional[str] = None
    primary_metric: str = "conversion_rate"
    primary_metric_goal: str = "maximize"
    assignment_strategy: str = "deterministic_hash"
    entity_type: str = "customer"
    traffic_percentage: float = 100.0
    minimum_sample_size: int = 1000
    significance_level: float = 0.05
    power: float = 0.80
    min_detectable_effect: float = 0.05
    circuit_breaker_enabled: bool = True
    circuit_breaker_threshold: float = 0.20
    circuit_breaker_min_samples: int = 200
    created_by: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.arms:
            raise DisputeValidationError("arms 不能为空")
        control_count = sum(1 for a in self.arms if a.is_control)
        if control_count != 1:
            raise DisputeValidationError(
                f"arms 必须有且只有 1 个 control，当前 {control_count} 个"
            )
        if len({a.arm_key for a in self.arms}) != len(self.arms):
            raise DisputeValidationError("arms 的 arm_key 不能重复")


class DisputeValidationError(ValueError):
    """业务校验错误（命名借用 E4 风格，但独立类避免 import）"""


@dataclass
class AssignResult:
    enrolled: bool
    arm_key: Optional[str]
    arm_id: Optional[str]
    arm_parameters: dict[str, Any]
    assignment_id: Optional[str]  # DB row id（首次分配时才有）
    was_new: bool  # 是否首次分配
    experiment_id: str
    experiment_status: str


@dataclass
class RecordEventInput:
    entity_id: str
    event_type: str
    revenue_fen: Optional[int] = None
    numeric_value: Optional[float] = None
    metadata: Optional[dict[str, Any]] = None
    event_at: Optional[datetime] = None
    idempotency_key: Optional[str] = None

    def __post_init__(self) -> None:
        if self.event_type not in (
            "exposure", "conversion", "revenue", "metric_value", "error"
        ):
            raise DisputeValidationError(
                f"event_type 非法: {self.event_type!r}"
            )
        if self.metadata is None:
            self.metadata = {}
        if self.event_at is None:
            self.event_at = datetime.now(tz=timezone.utc)


# ─────────────────────────────────────────────────────────────
# 服务
# ─────────────────────────────────────────────────────────────


class ABExperimentService:
    """A/B 实验平台核心服务"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id

    # ── 1. 创建实验 ──

    async def create_experiment(
        self, inp: CreateExperimentInput
    ) -> dict[str, Any]:
        """创建新实验（draft 状态）"""
        # 1. 插入主表
        row = await self._db.execute(
            text("""
                INSERT INTO ab_experiments (
                    tenant_id, experiment_key, name, description,
                    primary_metric, primary_metric_goal,
                    assignment_strategy, entity_type, traffic_percentage,
                    minimum_sample_size, significance_level, power,
                    min_detectable_effect,
                    circuit_breaker_enabled, circuit_breaker_threshold,
                    circuit_breaker_min_samples,
                    status, created_by
                ) VALUES (
                    CAST(:tenant_id AS uuid), :experiment_key, :name, :description,
                    :primary_metric, :primary_metric_goal,
                    :assignment_strategy, :entity_type, :traffic_pct,
                    :min_sample, :sig_level, :power, :mde,
                    :cb_enabled, :cb_threshold, :cb_min_samples,
                    'draft', CAST(:created_by AS uuid)
                )
                RETURNING id
            """),
            {
                "tenant_id": self._tenant_id,
                "experiment_key": inp.experiment_key,
                "name": inp.name,
                "description": inp.description,
                "primary_metric": inp.primary_metric,
                "primary_metric_goal": inp.primary_metric_goal,
                "assignment_strategy": inp.assignment_strategy,
                "entity_type": inp.entity_type,
                "traffic_pct": inp.traffic_percentage,
                "min_sample": inp.minimum_sample_size,
                "sig_level": inp.significance_level,
                "power": inp.power,
                "mde": inp.min_detectable_effect,
                "cb_enabled": inp.circuit_breaker_enabled,
                "cb_threshold": inp.circuit_breaker_threshold,
                "cb_min_samples": inp.circuit_breaker_min_samples,
                "created_by": inp.created_by,
            },
        )
        experiment_id = str(row.scalar_one())

        # 2. 插入 arms
        arm_ids: list[str] = []
        for arm in inp.arms:
            arm_row = await self._db.execute(
                text("""
                    INSERT INTO ab_experiment_arms (
                        tenant_id, experiment_id, arm_key, name, description,
                        is_control, traffic_weight, parameters
                    ) VALUES (
                        CAST(:tenant_id AS uuid), CAST(:experiment_id AS uuid),
                        :arm_key, :name, :description,
                        :is_control, :traffic_weight, CAST(:parameters AS jsonb)
                    )
                    RETURNING id
                """),
                {
                    "tenant_id": self._tenant_id,
                    "experiment_id": experiment_id,
                    "arm_key": arm.arm_key,
                    "name": arm.name,
                    "description": arm.description,
                    "is_control": arm.is_control,
                    "traffic_weight": arm.traffic_weight,
                    "parameters": json.dumps(arm.parameters, ensure_ascii=False),
                },
            )
            arm_ids.append(str(arm_row.scalar_one()))

        await self._db.commit()

        return {
            "experiment_id": experiment_id,
            "experiment_key": inp.experiment_key,
            "status": "draft",
            "arm_ids": arm_ids,
        }

    # ── 2. 生命周期转换 ──

    async def start_experiment(
        self, experiment_id: str, started_by: Optional[str] = None
    ) -> dict[str, Any]:
        """draft → running"""
        return await self._transition_status(
            experiment_id,
            expected=["draft", "paused"],
            target="running",
            extra_columns={"started_at": "NOW()"},
        )

    async def pause_experiment(
        self, experiment_id: str
    ) -> dict[str, Any]:
        return await self._transition_status(
            experiment_id, expected=["running"], target="paused",
        )

    async def terminate_experiment(
        self,
        experiment_id: str,
        *,
        reason: str,
        winner_arm_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """手动终止，target 依 reason 决定"""
        target = (
            "terminated_winner" if winner_arm_id else "terminated_no_winner"
        )
        return await self._transition_status(
            experiment_id,
            expected=["running", "paused"],
            target=target,
            extra_columns={"ended_at": "NOW()"},
            extra_params={"winner_arm_id": winner_arm_id},
            extra_sets="winner_arm_id = CAST(:winner_arm_id AS uuid)"
            if winner_arm_id else "",
        )

    # ── 3. Assignment ──

    async def assign(
        self, *, experiment_key: str, entity_id: str
    ) -> AssignResult:
        """稳定分配 entity 到 arm；幂等"""
        exp = await self._fetch_experiment_by_key(experiment_key)
        if exp is None:
            raise DisputeValidationError(
                f"找不到实验 experiment_key={experiment_key!r}"
            )

        if exp["status"] != "running":
            return AssignResult(
                enrolled=False,
                arm_key=None,
                arm_id=None,
                arm_parameters={},
                assignment_id=None,
                was_new=False,
                experiment_id=str(exp["id"]),
                experiment_status=exp["status"],
            )

        # 先查是否已分配
        existing = await self._fetch_existing_assignment(
            experiment_id=str(exp["id"]),
            entity_type=exp["entity_type"],
            entity_id=entity_id,
        )
        if existing:
            return AssignResult(
                enrolled=True,
                arm_key=existing["arm_key"],
                arm_id=str(existing["arm_id"]),
                arm_parameters=existing.get("parameters") or {},
                assignment_id=str(existing["id"]),
                was_new=False,
                experiment_id=str(exp["id"]),
                experiment_status=exp["status"],
            )

        # 加载 arms + 运行分配算法
        arms_db = await self._fetch_arms(str(exp["id"]))
        arm_defs = [
            ArmDefinition(
                arm_key=a["arm_key"],
                traffic_weight=a["traffic_weight"],
                is_control=a["is_control"],
                parameters=a["parameters"] or {},
            )
            for a in arms_db
        ]

        decision = assign_entity(
            entity_id=entity_id,
            experiment_key=experiment_key,
            arms=arm_defs,
            traffic_percentage=float(exp["traffic_percentage"]),
        )

        if isinstance(decision, NotEnrolled) or decision is NOT_ENROLLED:
            return AssignResult(
                enrolled=False,
                arm_key=None,
                arm_id=None,
                arm_parameters={},
                assignment_id=None,
                was_new=False,
                experiment_id=str(exp["id"]),
                experiment_status=exp["status"],
            )

        assert isinstance(decision, AssignmentDecision)

        # 找到对应 arm 的 DB id
        arm_db = next(a for a in arms_db if a["arm_key"] == decision.arm_key)
        arm_id = str(arm_db["id"])

        # 持久化
        row = await self._db.execute(
            text("""
                INSERT INTO ab_experiment_assignments (
                    tenant_id, experiment_id, arm_id, entity_type, entity_id,
                    assignment_hash
                ) VALUES (
                    CAST(:tenant_id AS uuid), CAST(:experiment_id AS uuid),
                    CAST(:arm_id AS uuid), :entity_type, :entity_id,
                    :assignment_hash
                )
                ON CONFLICT (tenant_id, experiment_id, entity_type, entity_id)
                DO UPDATE SET assigned_at = ab_experiment_assignments.assigned_at
                RETURNING id, (xmax = 0) AS was_new
            """),
            {
                "tenant_id": self._tenant_id,
                "experiment_id": str(exp["id"]),
                "arm_id": arm_id,
                "entity_type": exp["entity_type"],
                "entity_id": entity_id,
                "assignment_hash": decision.hash_value & 0x7FFFFFFF,  # INTEGER 范围
            },
        )
        rec = row.mappings().first()
        await self._db.commit()

        return AssignResult(
            enrolled=True,
            arm_key=decision.arm_key,
            arm_id=arm_id,
            arm_parameters=arm_db["parameters"] or {},
            assignment_id=str(rec["id"]),
            was_new=bool(rec["was_new"]),
            experiment_id=str(exp["id"]),
            experiment_status=exp["status"],
        )

    # ── 4. 事件摄入 ──

    async def record_event(
        self, *, experiment_key: str, inp: RecordEventInput
    ) -> dict[str, Any]:
        """按 entity_id 找 assignment + 写事件 + 增量更新 arm 累计"""
        exp = await self._fetch_experiment_by_key(experiment_key)
        if exp is None:
            raise DisputeValidationError(
                f"找不到实验 experiment_key={experiment_key!r}"
            )

        assignment = await self._fetch_existing_assignment(
            experiment_id=str(exp["id"]),
            entity_type=exp["entity_type"],
            entity_id=inp.entity_id,
        )
        if not assignment:
            # entity 未入组，不记事件
            return {
                "recorded": False,
                "reason": "entity 未分配 arm",
            }

        # 插入事件（幂等）
        row = await self._db.execute(
            text("""
                INSERT INTO ab_experiment_events (
                    tenant_id, experiment_id, arm_id, entity_type, entity_id,
                    event_type, revenue_fen, numeric_value, metadata,
                    event_at, idempotency_key
                ) VALUES (
                    CAST(:tenant_id AS uuid), CAST(:experiment_id AS uuid),
                    CAST(:arm_id AS uuid), :entity_type, :entity_id,
                    :event_type, :revenue_fen, :numeric_value,
                    CAST(:metadata AS jsonb), :event_at, :idempotency_key
                )
                ON CONFLICT (experiment_id, entity_id, event_type, idempotency_key)
                WHERE idempotency_key IS NOT NULL
                DO NOTHING
                RETURNING id
            """),
            {
                "tenant_id": self._tenant_id,
                "experiment_id": str(exp["id"]),
                "arm_id": str(assignment["arm_id"]),
                "entity_type": exp["entity_type"],
                "entity_id": inp.entity_id,
                "event_type": inp.event_type,
                "revenue_fen": inp.revenue_fen,
                "numeric_value": inp.numeric_value,
                "metadata": json.dumps(inp.metadata, ensure_ascii=False),
                "event_at": inp.event_at,
                "idempotency_key": inp.idempotency_key,
            },
        )
        event_rec = row.mappings().first()
        if event_rec is None:
            # 幂等冲突，事件已存在
            await self._db.commit()
            return {"recorded": False, "reason": "idempotent duplicate"}

        event_id = str(event_rec["id"])

        # 增量更新 arm 累计指标
        await self._increment_arm_stats(
            arm_id=str(assignment["arm_id"]),
            event_type=inp.event_type,
            revenue_fen=inp.revenue_fen,
            numeric_value=inp.numeric_value,
        )

        # 若 assignment.first_exposed_at 为空且 event_type=exposure，回填
        if inp.event_type == "exposure":
            await self._db.execute(
                text("""
                    UPDATE ab_experiment_assignments
                    SET first_exposed_at = COALESCE(first_exposed_at, NOW())
                    WHERE id = CAST(:id AS uuid)
                """),
                {"id": str(assignment["id"])},
            )

        await self._db.commit()
        return {
            "recorded": True,
            "event_id": event_id,
            "arm_id": str(assignment["arm_id"]),
        }

    # ── 5. 显著性评估 ──

    async def evaluate_significance(
        self, experiment_id: str, *, use_bayesian: bool = False
    ) -> dict[str, Any]:
        """评估实验当前显著性（不改 status，仅返回）"""
        exp = await self._fetch_experiment_by_id(experiment_id)
        if exp is None:
            raise DisputeValidationError(f"experiment {experiment_id} 不存在")

        arms = await self._fetch_arms(experiment_id)
        control = next((a for a in arms if a["is_control"]), None)
        if control is None:
            raise DisputeValidationError("实验无 control arm")

        control_stats = _db_row_to_arm_stats(control, is_control=True)
        results: list[dict[str, Any]] = []

        for arm in arms:
            if arm["is_control"]:
                continue
            treatment_stats = _db_row_to_arm_stats(arm)
            sig = frequentist_significance(
                control_stats, treatment_stats,
                metric=exp["primary_metric"],
                alpha=float(exp["significance_level"]),
            )
            arm_result: dict[str, Any] = {
                "arm_key": arm["arm_key"],
                "exposure": treatment_stats.exposure,
                "conversion": treatment_stats.conversion,
                "conversion_rate": treatment_stats.conversion_rate,
                "p_value": sig.p_value,
                "significant": sig.significant,
                "effect_size": sig.effect_size,
                "effect_size_pct": sig.effect_size_pct,
            }
            if use_bayesian and exp["primary_metric"] == "conversion_rate":
                bayes = bayesian_posterior(control_stats, treatment_stats)
                arm_result["bayesian_prob_beats_control"] = (
                    bayes.prob_treatment_beats_control
                )
                arm_result["bayesian_expected_loss"] = (
                    bayes.expected_loss_pct
                )
            results.append(arm_result)

        return {
            "experiment_id": experiment_id,
            "primary_metric": exp["primary_metric"],
            "control": {
                "arm_key": control["arm_key"],
                "exposure": control_stats.exposure,
                "conversion": control_stats.conversion,
                "conversion_rate": control_stats.conversion_rate,
            },
            "treatments": results,
        }

    # ── 6. 熔断评估（cron） ──

    async def evaluate_circuit_breakers(
        self,
    ) -> list[dict[str, Any]]:
        """扫所有 running + 熔断启用的实验，触发熔断时转 terminated_circuit_breaker"""
        rows = await self._db.execute(
            text("""
                SELECT id, experiment_key, primary_metric, primary_metric_goal,
                       circuit_breaker_threshold, circuit_breaker_min_samples
                FROM ab_experiments
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND is_deleted = false
                  AND status = 'running'
                  AND circuit_breaker_enabled = true
                  AND circuit_breaker_tripped = false
            """),
            {"tenant_id": self._tenant_id},
        )
        experiments = [dict(r) for r in rows.mappings()]

        results: list[dict[str, Any]] = []
        for exp in experiments:
            decision = await self._evaluate_single_circuit_breaker(exp)
            result = {
                "experiment_id": str(exp["id"]),
                "experiment_key": exp["experiment_key"],
                "should_trip": decision.should_trip,
                "tripped_arm_keys": decision.tripped_arm_keys,
                "reason": decision.reason,
            }
            if decision.should_trip:
                await self._trip_circuit_breaker(
                    str(exp["id"]), reason=decision.reason or "auto-trip",
                )
            results.append(result)

        return results

    async def _evaluate_single_circuit_breaker(
        self, exp: dict[str, Any]
    ) -> CircuitBreakerDecision:
        arms = await self._fetch_arms(str(exp["id"]))
        control = next((a for a in arms if a["is_control"]), None)
        if control is None:
            return CircuitBreakerDecision(should_trip=False)
        control_stats = _db_row_to_arm_stats(control, is_control=True)
        treatments = [
            (a["arm_key"], _db_row_to_arm_stats(a))
            for a in arms
            if not a["is_control"]
        ]
        return evaluate_circuit_breaker(
            control_stats,
            treatments,
            metric=exp["primary_metric"],
            goal=exp["primary_metric_goal"],
            threshold_pct=float(exp["circuit_breaker_threshold"]),
            min_samples=int(exp["circuit_breaker_min_samples"]),
        )

    # ─────────────────────────────────────────────────────────────
    # 内部工具
    # ─────────────────────────────────────────────────────────────

    async def _fetch_experiment_by_key(
        self, experiment_key: str
    ) -> Optional[dict[str, Any]]:
        row = await self._db.execute(
            text("""
                SELECT id, experiment_key, name, status, entity_type,
                       traffic_percentage, primary_metric, primary_metric_goal,
                       significance_level
                FROM ab_experiments
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND experiment_key = :key
                  AND is_deleted = false
                LIMIT 1
            """),
            {"tenant_id": self._tenant_id, "key": experiment_key},
        )
        rec = row.mappings().first()
        return dict(rec) if rec else None

    async def _fetch_experiment_by_id(
        self, experiment_id: str
    ) -> Optional[dict[str, Any]]:
        row = await self._db.execute(
            text("""
                SELECT * FROM ab_experiments
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                  AND is_deleted = false
            """),
            {"id": experiment_id, "tenant_id": self._tenant_id},
        )
        rec = row.mappings().first()
        return dict(rec) if rec else None

    async def _fetch_arms(self, experiment_id: str) -> list[dict[str, Any]]:
        row = await self._db.execute(
            text("""
                SELECT id, arm_key, name, is_control, traffic_weight,
                       parameters, exposure_count, conversion_count,
                       revenue_sum_fen, numeric_metric_sum, numeric_metric_ssq
                FROM ab_experiment_arms
                WHERE experiment_id = CAST(:experiment_id AS uuid)
                  AND is_deleted = false
                ORDER BY is_control DESC, arm_key
            """),
            {"experiment_id": experiment_id},
        )
        return [dict(r) for r in row.mappings()]

    async def _fetch_existing_assignment(
        self, *, experiment_id: str, entity_type: str, entity_id: str
    ) -> Optional[dict[str, Any]]:
        row = await self._db.execute(
            text("""
                SELECT a.id, a.arm_id, a.assigned_at, a.first_exposed_at,
                       arm.arm_key, arm.parameters
                FROM ab_experiment_assignments a
                JOIN ab_experiment_arms arm ON arm.id = a.arm_id
                WHERE a.experiment_id = CAST(:experiment_id AS uuid)
                  AND a.entity_type = :entity_type
                  AND a.entity_id = :entity_id
                LIMIT 1
            """),
            {
                "experiment_id": experiment_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
            },
        )
        rec = row.mappings().first()
        return dict(rec) if rec else None

    async def _transition_status(
        self,
        experiment_id: str,
        *,
        expected: list[str],
        target: str,
        extra_columns: Optional[dict[str, str]] = None,
        extra_sets: str = "",
        extra_params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        set_clauses = ["status = :target", "updated_at = NOW()"]
        if extra_columns:
            for col, expr in extra_columns.items():
                set_clauses.append(f"{col} = {expr}")
        if extra_sets:
            set_clauses.append(extra_sets)

        params: dict[str, Any] = {
            "id": experiment_id,
            "tenant_id": self._tenant_id,
            "target": target,
            "expected": expected,
        }
        if extra_params:
            params.update(extra_params)

        row = await self._db.execute(
            text(f"""
                UPDATE ab_experiments SET
                    {', '.join(set_clauses)}
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                  AND is_deleted = false
                  AND status = ANY(:expected)
                RETURNING id, status
            """),
            params,
        )
        rec = row.mappings().first()
        await self._db.commit()
        if not rec:
            raise DisputeValidationError(
                f"状态转换失败：实验不存在或状态不在 {expected}"
            )
        return {"experiment_id": experiment_id, "status": target}

    async def _increment_arm_stats(
        self,
        *,
        arm_id: str,
        event_type: str,
        revenue_fen: Optional[int],
        numeric_value: Optional[float],
    ) -> None:
        updates: list[str] = ["updated_at = NOW()"]
        params: dict[str, Any] = {"arm_id": arm_id}

        if event_type == "exposure":
            updates.append("exposure_count = exposure_count + 1")
        elif event_type == "conversion":
            updates.append("conversion_count = conversion_count + 1")
            if revenue_fen:
                updates.append("revenue_sum_fen = revenue_sum_fen + :rev")
                params["rev"] = revenue_fen
        elif event_type == "revenue":
            if revenue_fen:
                updates.append("revenue_sum_fen = revenue_sum_fen + :rev")
                params["rev"] = revenue_fen
        elif event_type == "metric_value":
            if numeric_value is not None:
                updates.append("numeric_metric_sum = numeric_metric_sum + :nv")
                updates.append(
                    "numeric_metric_ssq = numeric_metric_ssq + (:nv * :nv)"
                )
                params["nv"] = numeric_value
        # error 事件不增计数

        if len(updates) == 1:
            return  # 只有 updated_at 则不动

        await self._db.execute(
            text(f"""
                UPDATE ab_experiment_arms SET
                    {', '.join(updates)},
                    last_stats_refreshed_at = NOW()
                WHERE id = CAST(:arm_id AS uuid)
            """),
            params,
        )

    async def _trip_circuit_breaker(
        self, experiment_id: str, *, reason: str
    ) -> None:
        await self._db.execute(
            text("""
                UPDATE ab_experiments SET
                    status = 'terminated_circuit_breaker',
                    circuit_breaker_tripped = true,
                    circuit_breaker_tripped_at = NOW(),
                    circuit_breaker_tripped_reason = :reason,
                    ended_at = NOW(),
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
            """),
            {
                "id": experiment_id,
                "tenant_id": self._tenant_id,
                "reason": reason,
            },
        )
        await self._db.commit()


# ─────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────


def _db_row_to_arm_stats(
    row: dict[str, Any], *, is_control: bool = False
) -> ArmStats:
    return ArmStats(
        exposure=int(row.get("exposure_count") or 0),
        conversion=int(row.get("conversion_count") or 0),
        revenue_sum_fen=int(row.get("revenue_sum_fen") or 0),
        numeric_metric_sum=float(row.get("numeric_metric_sum") or 0),
        numeric_metric_ssq=float(row.get("numeric_metric_ssq") or 0),
        is_control=is_control or bool(row.get("is_control")),
    )
