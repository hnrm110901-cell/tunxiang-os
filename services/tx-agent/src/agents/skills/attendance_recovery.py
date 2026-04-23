"""屯象OS tx-agent 缺勤补位 Agent：收到缺勤事件后自动创建缺口、匹配候选人、推荐补位。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from uuid import uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger(__name__)


# ── 辅助函数 ─────────────────────────────────────────────────────────────────


def _urgency_level(shift_start: str | None, now: datetime | None = None) -> str:
    """根据距班次开始的时间判断紧急度。"""
    if shift_start is None:
        return "normal"
    now = now or datetime.now()
    try:
        if isinstance(shift_start, str):
            parts = shift_start.split(":")
            hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            shift_dt = now.replace(hour=hour, minute=minute, second=0)
        else:
            shift_dt = now
    except (ValueError, IndexError):
        return "normal"
    diff_minutes = (shift_dt - now).total_seconds() / 60
    if diff_minutes < 60:
        return "critical"
    if diff_minutes < 180:
        return "high"
    return "normal"


def _candidate_score(
    candidate: dict[str, Any],
    target_role: str,
    target_store_id: str,
    reservation_ctx: dict[str, Any] | None = None,
) -> float:
    """候选人匹配评分：角色匹配>同店>距离>可用性 + 预订上下文加分。"""
    score = 50.0
    if str(candidate.get("role") or "").lower() == target_role.lower():
        score += 30.0
    if str(candidate.get("store_id") or "") == target_store_id:
        score += 15.0
    if candidate.get("is_available", True):
        score += 5.0

    # ── 跨域经营数据加分 ──────────────────────────────────────────────────
    if reservation_ctx:
        large_parties = int(reservation_ctx.get("large_parties") or 0)
        vip_count = int(reservation_ctx.get("vip_count") or 0)
        role_lower = str(candidate.get("role") or "").lower()

        # 菜品技能匹配：当天有宴会(大桌)预订，优先掌握宴会菜技能的厨师
        if large_parties > 0 and role_lower in ("chef", "cook", "厨师", "后厨"):
            if candidate.get("has_banquet_skill") or candidate.get("skill_level", 0) >= 3:
                score += 30.0

        # 客户服务经验：有VIP预订时，优先服务评分高的服务员
        if vip_count > 0 and role_lower in ("waiter", "服务员", "前厅"):
            service_rating = float(candidate.get("service_rating") or 0)
            if service_rating >= 4.5:
                score += 20.0
            elif service_rating >= 4.0:
                score += 10.0

    return round(score, 1)


# ── 数据查询 ─────────────────────────────────────────────────────────────────


async def _load_absent_schedule(
    db: Any,
    tenant_id: str,
    employee_id: str,
    absent_date: date,
) -> Optional[dict[str, Any]]:
    """查询缺勤员工当天的排班信息。"""
    q = text("""
        SELECT us.id::text AS schedule_id, us.employee_id::text, us.store_id::text,
               us.shift_date, us.start_time, us.end_time, us.role,
               e.emp_name
        FROM unified_schedules us
        LEFT JOIN employees e
          ON e.id = us.employee_id AND e.tenant_id = us.tenant_id
        WHERE us.tenant_id = CAST(:tenant_id AS uuid)
          AND us.employee_id = CAST(:employee_id AS uuid)
          AND us.shift_date = :absent_date
          AND COALESCE(us.is_deleted, false) = false
        LIMIT 1
    """)
    try:
        result = await db.execute(
            q,
            {
                "tenant_id": tenant_id,
                "employee_id": employee_id,
                "absent_date": absent_date,
            },
        )
        row = result.mappings().first()
        return dict(row) if row else None
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("recovery_load_schedule_failed", error=str(exc))
        return None


async def _create_shift_gap(
    db: Any,
    tenant_id: str,
    schedule: dict[str, Any],
) -> Optional[str]:
    """在 shift_gaps 表插入一条缺口记录。"""
    gap_id = str(uuid4())
    q = text("""
        INSERT INTO shift_gaps (
            id, tenant_id, store_id, gap_date, start_time, end_time,
            role, reason, status, original_employee_id, created_at
        ) VALUES (
            CAST(:gap_id AS uuid), CAST(:tenant_id AS uuid),
            CAST(:store_id AS uuid), :gap_date, :start_time, :end_time,
            :role, 'absent', 'open', CAST(:emp_id AS uuid), NOW()
        )
    """)
    try:
        await db.execute(
            q,
            {
                "gap_id": gap_id,
                "tenant_id": tenant_id,
                "store_id": schedule.get("store_id"),
                "gap_date": schedule.get("shift_date"),
                "start_time": schedule.get("start_time"),
                "end_time": schedule.get("end_time"),
                "role": schedule.get("role"),
                "emp_id": schedule.get("employee_id"),
            },
        )
        await db.commit()
        return gap_id
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("recovery_create_gap_failed", error=str(exc))
        return None


async def _find_available_candidates(
    db: Any,
    tenant_id: str,
    store_id: str,
    gap_date: date,
    role: str,
    exclude_employee_id: str,
) -> list[dict[str, Any]]:
    """查找当天未排班或有空闲的同角色员工。"""
    q = text("""
        SELECT e.id::text AS employee_id, e.emp_name, e.role,
               e.store_id::text AS store_id, e.phone
        FROM employees e
        WHERE e.tenant_id = CAST(:tenant_id AS uuid)
          AND e.is_deleted = false
          AND COALESCE(e.is_active, true) = true
          AND e.id != CAST(:exclude_id AS uuid)
          AND NOT EXISTS (
            SELECT 1 FROM unified_schedules us
            WHERE us.tenant_id = e.tenant_id
              AND us.employee_id = e.id
              AND us.shift_date = :gap_date
              AND COALESCE(us.is_deleted, false) = false
          )
        ORDER BY
          CASE WHEN e.store_id = CAST(:store_id AS uuid) THEN 0 ELSE 1 END,
          CASE WHEN LOWER(e.role) = LOWER(:role) THEN 0 ELSE 1 END
        LIMIT 10
    """)
    try:
        result = await db.execute(
            q,
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "gap_date": gap_date,
                "role": role,
                "exclude_id": exclude_employee_id,
            },
        )
        return [dict(r) for r in result.mappings()]
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("recovery_find_candidates_failed", error=str(exc))
        return []


# ── Agent 类 ─────────────────────────────────────────────────────────────────


class AttendanceRecoveryAgent(SkillAgent):
    """缺勤补位 Skill：检测缺勤 → 创建缺口 → 查找候选 → 推荐补位。"""

    agent_id = "attendance_recovery"
    agent_name = "缺勤补位"
    description = "收到缺勤事件后自动创建排班缺口、匹配候选人并生成补位推荐"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "detect_absence",
            "find_replacements",
            "create_gap_alert",
            "notify_candidates",
        ]

    def _store_scope(self, params: dict[str, Any]) -> Optional[str]:
        sid = params.get("store_id")
        if sid is not None and str(sid).strip():
            return str(sid).strip()
        if self.store_id is not None and str(self.store_id).strip():
            return str(self.store_id).strip()
        return None

    async def _fetch_reservation_context(
        self,
        db: Any,
        tenant_id: str,
        store_id: str,
        target_date: date,
    ) -> dict[str, Any]:
        """从tx-trade查询当天预订数据，用于评估缺勤紧急程度。

        宴会预订(party_size>=8) -> urgency升级为critical
        VIP预订 -> 需要匹配资深员工
        预订总量>日均1.5倍 -> 全店urgency升级

        SQL降级：reservations表不存在时返回空dict
        """
        try:
            sql = text("""
                SELECT COUNT(*) as total_reservations,
                       COALESCE(SUM(party_size), 0) as total_guests,
                       SUM(CASE WHEN party_size >= 8 THEN 1 ELSE 0 END) as large_parties,
                       SUM(CASE WHEN vip_level > 0 THEN 1 ELSE 0 END) as vip_count
                FROM reservations
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND store_id = CAST(:store_id AS TEXT)
                  AND reservation_date = :date
                  AND status IN ('confirmed', 'seated')
            """)
            result = await db.execute(
                sql,
                {
                    "tid": str(tenant_id),
                    "store_id": str(store_id),
                    "date": str(target_date),
                },
            )
            row = result.mappings().first()
            return dict(row) if row else {}
        except (OperationalError, ProgrammingError) as exc:
            logger.debug("recovery_reservation_ctx_unavailable", error=str(exc))
            return {}

    async def _calculate_dynamic_urgency(
        self,
        db: Any,
        tenant_id: str,
        store_id: str,
        target_date: date,
        position: str,
        base_urgency: str,
    ) -> str:
        """动态调整紧急度（基于预订和客流预测）。

        如果有大桌宴会 + 缺的是后厨 -> critical
        如果VIP预订 + 缺的是前厅 -> critical
        如果客流预测>均值1.3倍 + 任何岗位缺勤 -> 至少urgent(high)
        """
        reservation_ctx = await self._fetch_reservation_context(
            db,
            tenant_id,
            store_id,
            target_date,
        )
        if not reservation_ctx:
            return base_urgency

        large_parties = int(reservation_ctx.get("large_parties") or 0)
        vip_count = int(reservation_ctx.get("vip_count") or 0)
        total_reservations = int(reservation_ctx.get("total_reservations") or 0)
        pos_lower = position.lower()

        # 大桌宴会 + 后厨缺勤 -> critical
        if large_parties > 0 and pos_lower in ("chef", "cook", "厨师", "后厨"):
            logger.info(
                "recovery_urgency_upgrade_banquet",
                store_id=store_id,
                large_parties=large_parties,
                position=position,
            )
            return "critical"

        # VIP预订 + 前厅缺勤 -> critical
        if vip_count > 0 and pos_lower in ("waiter", "服务员", "前厅"):
            logger.info(
                "recovery_urgency_upgrade_vip",
                store_id=store_id,
                vip_count=vip_count,
                position=position,
            )
            return "critical"

        # 预订总量偏高(>日均1.3倍近似判断：>5单) -> 至少high
        if total_reservations > 5 and base_urgency == "normal":
            logger.info(
                "recovery_urgency_upgrade_volume",
                store_id=store_id,
                total_reservations=total_reservations,
            )
            return "high"

        return base_urgency

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch: dict[str, Any] = {
            "detect_absence": self._detect_absence,
            "find_replacements": self._find_replacements,
            "create_gap_alert": self._create_gap_alert,
            "notify_candidates": self._notify_candidates,
        }
        handler = dispatch.get(action)
        if handler is None:
            return AgentResult(
                success=False,
                action=action,
                error=f"不支持的操作: {action}",
            )
        return await handler(params)

    async def _detect_absence(self, params: dict[str, Any]) -> AgentResult:
        """检测缺勤：查排班 → 创建缺口 → 查候选 → 返回推荐列表。"""
        employee_id = params.get("employee_id")
        if not employee_id:
            return AgentResult(success=False, action="detect_absence", error="缺少 employee_id")
        absent_date_str = params.get("absent_date")
        absent_date = date.fromisoformat(absent_date_str) if absent_date_str else date.today()

        if not self._db:
            logger.warning("recovery_detect_no_db", tenant_id=self.tenant_id)
            return AgentResult(
                success=False,
                action="detect_absence",
                error="数据库连接不可用",
            )

        # 真实逻辑
        schedule = await _load_absent_schedule(self._db, self.tenant_id, employee_id, absent_date)
        if not schedule:
            return AgentResult(
                success=True,
                action="detect_absence",
                data={"schedule": None, "message": "该员工当天无排班"},
                reasoning="缺勤员工当天无排班记录，无需补位",
                confidence=0.95,
            )

        gap_id = await _create_shift_gap(self._db, self.tenant_id, schedule)
        store_id = str(schedule.get("store_id") or "")
        role = str(schedule.get("role") or "waiter")

        # 获取预订上下文用于动态紧急度和候选人评分
        reservation_ctx = await self._fetch_reservation_context(
            self._db,
            self.tenant_id,
            store_id,
            absent_date,
        )

        candidates_raw = await _find_available_candidates(
            self._db,
            self.tenant_id,
            store_id,
            absent_date,
            role,
            employee_id,
        )
        candidates = []
        for c in candidates_raw:
            score = _candidate_score(c, role, store_id, reservation_ctx)
            c["score"] = score
            reason_parts = []
            if str(c.get("store_id") or "") == store_id:
                reason_parts.append("同店")
            if str(c.get("role") or "").lower() == role.lower():
                reason_parts.append("同岗")
            reason_parts.append("当天无排班")
            c["reason"] = "，".join(reason_parts)
            candidates.append(c)
        candidates.sort(key=lambda x: x["score"], reverse=True)

        base_urgency = _urgency_level(str(schedule.get("start_time") or ""))
        urgency = await self._calculate_dynamic_urgency(
            self._db,
            self.tenant_id,
            store_id,
            absent_date,
            role,
            base_urgency,
        )
        emp_name = schedule.get("emp_name") or employee_id

        return AgentResult(
            success=True,
            action="detect_absence",
            agent_level=2,
            rollback_window_min=30,
            data={
                "schedule": schedule,
                "gap_id": gap_id,
                "urgency": urgency,
                "candidates": candidates,
                "candidate_count": len(candidates),
                "reservation_context": reservation_ctx,
            },
            reasoning=f"检测到{emp_name}缺勤，紧急度{urgency}，已创建缺口并找到{len(candidates)}名候选人",
            confidence=0.88,
        )

    async def _find_replacements(self, params: dict[str, Any]) -> AgentResult:
        """查找替代人员（独立接口，可脱离 detect_absence 调用）。"""
        store_id = self._store_scope(params)
        role = params.get("role", "waiter")
        gap_date_str = params.get("gap_date")
        gap_date = date.fromisoformat(gap_date_str) if gap_date_str else date.today()
        exclude_id = params.get("exclude_employee_id", "00000000-0000-0000-0000-000000000000")

        if not store_id:
            return AgentResult(success=False, action="find_replacements", error="缺少 store_id")

        if not self._db:
            logger.warning("recovery_replacements_no_db", tenant_id=self.tenant_id)
            return AgentResult(
                success=False,
                action="find_replacements",
                error="数据库连接不可用",
            )

        # 获取预订上下文用于候选人评分
        reservation_ctx = await self._fetch_reservation_context(
            self._db,
            self.tenant_id,
            store_id,
            gap_date,
        )

        candidates_raw = await _find_available_candidates(
            self._db, self.tenant_id, store_id, gap_date, role, exclude_id
        )
        candidates = []
        for c in candidates_raw:
            c["score"] = _candidate_score(c, role, store_id, reservation_ctx)
            candidates.append(c)
        candidates.sort(key=lambda x: x["score"], reverse=True)

        return AgentResult(
            success=True,
            action="find_replacements",
            agent_level=2,
            rollback_window_min=30,
            data={"candidates": candidates, "reservation_context": reservation_ctx},
            reasoning=f"找到{len(candidates)}名可补位候选人",
            confidence=0.85,
        )

    async def _create_gap_alert(self, params: dict[str, Any]) -> AgentResult:
        """手动创建缺口预警。"""
        store_id = self._store_scope(params)
        if not store_id:
            return AgentResult(success=False, action="create_gap_alert", error="缺少 store_id")

        gap_date_str = params.get("gap_date")
        gap_date = date.fromisoformat(gap_date_str) if gap_date_str else date.today()
        start_time = params.get("start_time", "09:00")
        end_time = params.get("end_time", "18:00")
        role = params.get("role", "waiter")

        schedule = {
            "store_id": store_id,
            "shift_date": gap_date,
            "start_time": start_time,
            "end_time": end_time,
            "role": role,
            "employee_id": params.get("employee_id"),
        }

        if self._db:
            gap_id = await _create_shift_gap(self._db, self.tenant_id, schedule)
        else:
            gap_id = f"mock-gap-{uuid4().hex[:8]}"

        return AgentResult(
            success=True,
            action="create_gap_alert",
            data={"gap_id": gap_id, "schedule": schedule},
            reasoning=f"已创建缺口预警 {gap_id}",
            confidence=0.92,
        )

    async def _notify_candidates(self, params: dict[str, Any]) -> AgentResult:
        """通知候选人（预留IM接口，当前仅记录日志）。"""
        candidate_ids = params.get("candidate_ids", [])
        gap_id = params.get("gap_id")
        message = params.get("message", "您有一条补班邀请，请确认是否接受。")

        if not candidate_ids:
            return AgentResult(success=False, action="notify_candidates", error="缺少 candidate_ids")

        # TODO: 接入IM通知（企微/钉钉）
        logger.info(
            "recovery_notify_candidates",
            tenant_id=self.tenant_id,
            gap_id=gap_id,
            candidate_count=len(candidate_ids),
        )

        return AgentResult(
            success=True,
            action="notify_candidates",
            data={
                "notified": candidate_ids,
                "gap_id": gap_id,
                "channel": "pending_im",
                "message": message,
            },
            reasoning=f"已标记通知{len(candidate_ids)}名候选人（IM通道待接入）",
            confidence=0.70,
        )
