"""损耗告警 -- 理论vs实际超标自动告警 + 班次归因

每日22:00扫描当日所有门店:
  理论用量(BOM x 订单) vs 实际出库 -> 差异率
  差异率 > 8%  -> warning
  差异率 > 15% -> critical

班次归因: 按 inventory_transactions.created_at 划分班次
  morning:   06:00-14:00
  afternoon: 14:00-22:00
  evening:   22:00-06:00

定位到: 原料 + 班次 + 操作员
推送消息: "猪肉今日超标12%, 晚班王师傅领料37kg(理论29kg)"

金额单位: 分(fen)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  告警阈值 (可通过 API 调整)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WARNING_THRESHOLD_PCT = 8.0
CRITICAL_THRESHOLD_PCT = 15.0

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  班次定义
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SHIFTS = {
    "morning":   {"label": "早班", "start_hour": 6,  "end_hour": 14},
    "afternoon": {"label": "午班", "start_hour": 14, "end_hour": 22},
    "evening":   {"label": "晚班", "start_hour": 22, "end_hour": 6},
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  根因分类
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ROOT_CAUSES = {
    "staff_error":    "操作失误（领料/切配不规范）",
    "over_prep":      "备餐过量",
    "spoilage":       "食材变质/过期",
    "bom_deviation":  "BOM配方与实际操作偏差",
    "theft":          "盗损嫌疑",
    "equipment":      "设备故障导致损耗",
    "unknown":        "原因待排查",
}


def _classify_severity(variance_pct: float) -> str | None:
    """根据差异率判定告警等级

    Returns:
        'critical' / 'warning' / None(正常)
    """
    abs_pct = abs(variance_pct)
    if abs_pct >= CRITICAL_THRESHOLD_PCT:
        return "critical"
    if abs_pct >= WARNING_THRESHOLD_PCT:
        return "warning"
    return None


def _infer_root_cause(
    variance_pct: float,
    shift_data: list[dict[str, Any]] | None = None,
) -> str:
    """根据差异率和班次数据推断根因

    简单规则引擎:
    - 差异 > 30%: 可能盗损
    - 差异集中在单一班次且 > 15%: 操作失误
    - 差异均匀分布: BOM偏差
    - 默认: unknown
    """
    abs_pct = abs(variance_pct)

    if abs_pct > 30:
        return "theft"

    if shift_data:
        # 检查是否集中在单一班次
        max_shift_pct = max(
            (abs(s.get("variance_pct", 0)) for s in shift_data),
            default=0,
        )
        if max_shift_pct > CRITICAL_THRESHOLD_PCT:
            return "staff_error"

    if abs_pct > CRITICAL_THRESHOLD_PCT:
        return "over_prep"

    return "bom_deviation"


class YieldAlertService:
    """损耗告警服务

    职责:
    - 扫描门店当日损耗 (理论 vs 实际)
    - 按班次拆分理论 vs 实际
    - 生成告警记录 (warning / critical)
    - 告警确认和解决
    - 损耗趋势分析
    """

    def __init__(
        self,
        warning_threshold: float = WARNING_THRESHOLD_PCT,
        critical_threshold: float = CRITICAL_THRESHOLD_PCT,
    ) -> None:
        self._warning_threshold = warning_threshold
        self._critical_threshold = critical_threshold

    # ──────────────────────────────────────────────────────
    #  RLS set_config
    # ──────────────────────────────────────────────────────

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    # ──────────────────────────────────────────────────────
    #  扫描单店当日损耗
    # ──────────────────────────────────────────────────────

    async def scan_daily_yield(
        self,
        store_id: str,
        target_date: date,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """扫描单店当日所有原料的理论vs实际用量

        增强 scm_yield_comparison 的逻辑, 加入班次维度。

        Args:
            store_id: 门店ID
            target_date: 扫描日期
            tenant_id: 租户ID
            db: 数据库会话

        Returns:
            原料差异列表 (含班次明细)
        """
        await self._set_tenant(db, tenant_id)

        # 理论用量: BOM x 当日订单
        sql_theory = text("""
            SELECT
                bd.ingredient_id,
                i.name AS ingredient_name,
                i.category AS ingredient_category,
                SUM(bd.standard_qty * oi.quantity) AS theory_qty
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id AND o.tenant_id = oi.tenant_id
            JOIN bom_details bd ON bd.dish_id = oi.dish_id AND bd.tenant_id = oi.tenant_id
                AND bd.is_active = TRUE
            JOIN ingredients i ON i.id = bd.ingredient_id AND i.tenant_id = bd.tenant_id
            WHERE o.tenant_id = :tenant_id
              AND o.store_id = :store_id::UUID
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
              AND o.status IN ('completed', 'paid')
              AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
            GROUP BY bd.ingredient_id, i.name, i.category
        """)

        # 实际用量: inventory_transactions (usage)
        sql_actual = text("""
            SELECT
                it.ingredient_id,
                SUM(it.qty) AS actual_qty
            FROM inventory_transactions it
            WHERE it.tenant_id = :tenant_id
              AND it.store_id = :store_id::UUID
              AND it.is_deleted = FALSE
              AND it.tx_type = 'usage'
              AND it.tx_date = :target_date
            GROUP BY it.ingredient_id
        """)

        params = {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "target_date": target_date,
        }

        theory_result = await db.execute(sql_theory, params)
        theory_rows = theory_result.fetchall()

        actual_result = await db.execute(sql_actual, params)
        actual_rows = actual_result.fetchall()

        # 构建实际用量字典
        actual_map: dict[str, float] = {}
        for row in actual_rows:
            actual_map[str(row.ingredient_id)] = float(row.actual_qty or 0)

        # 对比
        yield_items: list[dict[str, Any]] = []
        for row in theory_rows:
            ing_id = str(row.ingredient_id)
            theory_qty = float(row.theory_qty or 0)
            actual_qty = actual_map.get(ing_id, 0.0)
            variance_qty = actual_qty - theory_qty
            variance_pct = (
                round(variance_qty / theory_qty * 100, 2)
                if theory_qty > 0 else 0.0
            )

            severity = _classify_severity(variance_pct)

            yield_items.append({
                "ingredient_id": ing_id,
                "ingredient_name": str(row.ingredient_name),
                "ingredient_category": str(row.ingredient_category or ""),
                "theory_qty": round(theory_qty, 2),
                "actual_qty": round(actual_qty, 2),
                "variance_qty": round(variance_qty, 2),
                "variance_pct": variance_pct,
                "severity": severity,
            })

        # 排序: critical 优先, 然后 warning, 然后按差异率绝对值降序
        severity_order = {"critical": 0, "warning": 1, None: 2}
        yield_items.sort(
            key=lambda x: (severity_order.get(x["severity"], 2), -abs(x["variance_pct"])),
        )

        log.info(
            "yield_alert.scan_daily",
            store_id=store_id,
            target_date=target_date.isoformat(),
            total_ingredients=len(yield_items),
            warning_count=sum(1 for x in yield_items if x["severity"] == "warning"),
            critical_count=sum(1 for x in yield_items if x["severity"] == "critical"),
        )
        return yield_items

    # ──────────────────────────────────────────────────────
    #  按班次拆分理论 vs 实际
    # ──────────────────────────────────────────────────────

    async def attribute_to_shift(
        self,
        ingredient_id: str,
        store_id: str,
        target_date: date,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """按班次拆分某原料的理论vs实际用量

        班次划分:
          morning:   06:00-14:00
          afternoon: 14:00-22:00
          evening:   22:00-06:00 (跨日)

        Args:
            ingredient_id: 原料ID
            store_id: 门店ID
            target_date: 目标日期
            tenant_id: 租户ID
            db: 数据库会话

        Returns:
            班次对比列表
        """
        await self._set_tenant(db, tenant_id)

        # 实际用量按班次分组
        sql_actual_by_shift = text("""
            SELECT
                CASE
                    WHEN EXTRACT(HOUR FROM it.created_at) >= 6
                         AND EXTRACT(HOUR FROM it.created_at) < 14 THEN 'morning'
                    WHEN EXTRACT(HOUR FROM it.created_at) >= 14
                         AND EXTRACT(HOUR FROM it.created_at) < 22 THEN 'afternoon'
                    ELSE 'evening'
                END AS shift_id,
                SUM(it.qty) AS actual_qty,
                ARRAY_AGG(DISTINCT it.operator_id) FILTER (
                    WHERE it.operator_id IS NOT NULL
                ) AS operator_ids
            FROM inventory_transactions it
            WHERE it.tenant_id = :tenant_id
              AND it.store_id = :store_id::UUID
              AND it.ingredient_id = :ingredient_id::UUID
              AND it.is_deleted = FALSE
              AND it.tx_type = 'usage'
              AND it.tx_date = :target_date
            GROUP BY shift_id
        """)

        # 理论用量按班次分组 (按订单时间划分)
        sql_theory_by_shift = text("""
            SELECT
                CASE
                    WHEN EXTRACT(HOUR FROM o.created_at) >= 6
                         AND EXTRACT(HOUR FROM o.created_at) < 14 THEN 'morning'
                    WHEN EXTRACT(HOUR FROM o.created_at) >= 14
                         AND EXTRACT(HOUR FROM o.created_at) < 22 THEN 'afternoon'
                    ELSE 'evening'
                END AS shift_id,
                SUM(bd.standard_qty * oi.quantity) AS theory_qty
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id AND o.tenant_id = oi.tenant_id
            JOIN bom_details bd ON bd.dish_id = oi.dish_id AND bd.tenant_id = oi.tenant_id
                AND bd.is_active = TRUE
            WHERE o.tenant_id = :tenant_id
              AND o.store_id = :store_id::UUID
              AND bd.ingredient_id = :ingredient_id::UUID
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
              AND o.status IN ('completed', 'paid')
              AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
            GROUP BY shift_id
        """)

        params = {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "ingredient_id": ingredient_id,
            "target_date": target_date,
        }

        actual_result = await db.execute(sql_actual_by_shift, params)
        actual_rows = actual_result.fetchall()

        theory_result = await db.execute(sql_theory_by_shift, params)
        theory_rows = theory_result.fetchall()

        # 构建字典
        actual_by_shift: dict[str, dict[str, Any]] = {}
        for row in actual_rows:
            shift = str(row.shift_id)
            actual_by_shift[shift] = {
                "actual_qty": float(row.actual_qty or 0),
                "operator_ids": list(row.operator_ids) if row.operator_ids else [],
            }

        theory_by_shift: dict[str, float] = {}
        for row in theory_rows:
            theory_by_shift[str(row.shift_id)] = float(row.theory_qty or 0)

        # 组合所有班次
        all_shifts = set(list(actual_by_shift.keys()) + list(theory_by_shift.keys()))
        shift_comparisons: list[dict[str, Any]] = []

        for shift_id in ["morning", "afternoon", "evening"]:
            if shift_id not in all_shifts:
                continue

            theory_qty = theory_by_shift.get(shift_id, 0.0)
            actual_data = actual_by_shift.get(shift_id, {"actual_qty": 0.0, "operator_ids": []})
            actual_qty = actual_data["actual_qty"]
            operator_ids = actual_data["operator_ids"]

            variance_qty = actual_qty - theory_qty
            variance_pct = (
                round(variance_qty / theory_qty * 100, 2)
                if theory_qty > 0 else 0.0
            )

            shift_info = SHIFTS.get(shift_id, {})
            shift_comparisons.append({
                "shift_id": shift_id,
                "shift_label": shift_info.get("label", shift_id),
                "theory_qty": round(theory_qty, 2),
                "actual_qty": round(actual_qty, 2),
                "variance_qty": round(variance_qty, 2),
                "variance_pct": variance_pct,
                "operator_ids": operator_ids,
                "severity": _classify_severity(variance_pct),
            })

        log.info(
            "yield_alert.shift_attribution",
            ingredient_id=ingredient_id,
            store_id=store_id,
            target_date=target_date.isoformat(),
            shifts=len(shift_comparisons),
        )
        return shift_comparisons

    # ──────────────────────────────────────────────────────
    #  生成告警记录
    # ──────────────────────────────────────────────────────

    async def generate_alerts(
        self,
        store_id: str,
        target_date: date,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """扫描并生成告警记录

        流程:
          1. 扫描当日所有原料的理论vs实际
          2. 过滤出超标的 (variance_pct > 8%)
          3. 对每个超标原料做班次归因
          4. 写入 yield_alerts 表
          5. 返回生成的告警列表

        Args:
            store_id: 门店ID
            target_date: 目标日期
            tenant_id: 租户ID
            db: 数据库会话

        Returns:
            告警记录列表
        """
        await self._set_tenant(db, tenant_id)

        # 1. 扫描
        yield_items = await self.scan_daily_yield(
            store_id, target_date, tenant_id, db,
        )

        # 2. 过滤超标原料
        alerts_to_create: list[dict[str, Any]] = []
        for item in yield_items:
            if item["severity"] is None:
                continue

            # 3. 班次归因
            shift_data = await self.attribute_to_shift(
                ingredient_id=item["ingredient_id"],
                store_id=store_id,
                target_date=target_date,
                tenant_id=tenant_id,
                db=db,
            )

            # 找到差异最大的班次
            worst_shift: dict[str, Any] | None = None
            all_operator_ids: list[str] = []
            if shift_data:
                worst_shift = max(
                    shift_data,
                    key=lambda s: abs(s.get("variance_pct", 0)),
                )
                for s in shift_data:
                    all_operator_ids.extend(s.get("operator_ids", []))

            # 推断根因
            root_cause = _infer_root_cause(
                item["variance_pct"],
                shift_data,
            )

            alert_id = str(uuid.uuid4())
            alert_record = {
                "id": alert_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "alert_date": target_date,
                "ingredient_id": item["ingredient_id"],
                "ingredient_name": item["ingredient_name"],
                "theory_qty": item["theory_qty"],
                "actual_qty": item["actual_qty"],
                "variance_qty": item["variance_qty"],
                "variance_pct": item["variance_pct"],
                "shift_id": worst_shift["shift_id"] if worst_shift else None,
                "operator_ids": list(set(all_operator_ids)),
                "root_cause": root_cause,
                "severity": item["severity"],
                "status": "open",
            }

            # 4. 写入 DB
            sql_insert = text("""
                INSERT INTO yield_alerts (
                    id, tenant_id, store_id, alert_date,
                    ingredient_id, ingredient_name,
                    theory_qty, actual_qty, variance_qty, variance_pct,
                    shift_id, operator_ids, root_cause,
                    severity, status
                ) VALUES (
                    :id, :tenant_id, :store_id::UUID, :alert_date,
                    :ingredient_id::UUID, :ingredient_name,
                    :theory_qty, :actual_qty, :variance_qty, :variance_pct,
                    :shift_id, :operator_ids::JSONB, :root_cause,
                    :severity, :status
                )
                ON CONFLICT DO NOTHING
            """)

            import json
            await db.execute(
                sql_insert,
                {
                    **alert_record,
                    "operator_ids": json.dumps(alert_record["operator_ids"]),
                    "alert_date": target_date,
                },
            )

            # 加入返回列表 (含班次详情)
            alert_record["shift_breakdown"] = shift_data
            alert_record["root_cause_label"] = ROOT_CAUSES.get(root_cause, root_cause)
            alerts_to_create.append(alert_record)

        await db.commit()

        log.info(
            "yield_alert.alerts_generated",
            store_id=store_id,
            target_date=target_date.isoformat(),
            total_alerts=len(alerts_to_create),
            critical=sum(1 for a in alerts_to_create if a["severity"] == "critical"),
            warning=sum(1 for a in alerts_to_create if a["severity"] == "warning"),
        )
        return alerts_to_create

    # ──────────────────────────────────────────────────────
    #  获取告警列表
    # ──────────────────────────────────────────────────────

    async def get_alerts(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        *,
        status: str | None = None,
        severity: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """获取告警列表 (支持过滤和分页)

        Args:
            store_id: 门店ID
            tenant_id: 租户ID
            db: 数据库会话
            status: 状态过滤 (open/acknowledged/resolved)
            severity: 严重程度过滤 (warning/critical)
            start_date: 开始日期
            end_date: 结束日期
            page: 页码
            size: 每页大小

        Returns:
            分页告警列表
        """
        await self._set_tenant(db, tenant_id)

        # 构建动态 WHERE 条件
        conditions = [
            "tenant_id = :tenant_id",
            "store_id = :store_id::UUID",
            "is_deleted = FALSE",
        ]
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "store_id": store_id,
        }

        if status:
            conditions.append("status = :status")
            params["status"] = status
        if severity:
            conditions.append("severity = :severity")
            params["severity"] = severity
        if start_date:
            conditions.append("alert_date >= :start_date")
            params["start_date"] = start_date
        if end_date:
            conditions.append("alert_date <= :end_date")
            params["end_date"] = end_date

        where_clause = " AND ".join(conditions)

        # 总数
        count_sql = text(f"SELECT COUNT(*) FROM yield_alerts WHERE {where_clause}")
        count_result = await db.execute(count_sql, params)
        total = int(count_result.scalar() or 0)

        # 分页查询
        offset = (page - 1) * size
        data_sql = text(f"""
            SELECT
                id, store_id, alert_date, ingredient_id, ingredient_name,
                theory_qty, actual_qty, variance_qty, variance_pct,
                shift_id, operator_ids, root_cause,
                severity, status, resolved_by, resolved_at, resolution_note,
                created_at
            FROM yield_alerts
            WHERE {where_clause}
            ORDER BY alert_date DESC, severity ASC, ABS(variance_pct) DESC
            LIMIT :limit OFFSET :offset
        """)
        params["limit"] = size
        params["offset"] = offset

        result = await db.execute(data_sql, params)
        rows = result.fetchall()

        items = [
            {
                "id": str(row.id),
                "store_id": str(row.store_id),
                "alert_date": row.alert_date.isoformat() if row.alert_date else None,
                "ingredient_id": str(row.ingredient_id),
                "ingredient_name": row.ingredient_name,
                "theory_qty": float(row.theory_qty),
                "actual_qty": float(row.actual_qty),
                "variance_qty": float(row.variance_qty),
                "variance_pct": float(row.variance_pct),
                "shift_id": row.shift_id,
                "operator_ids": row.operator_ids or [],
                "root_cause": row.root_cause,
                "root_cause_label": ROOT_CAUSES.get(row.root_cause, row.root_cause),
                "severity": row.severity,
                "status": row.status,
                "resolved_by": str(row.resolved_by) if row.resolved_by else None,
                "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
                "resolution_note": row.resolution_note,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        }

    # ──────────────────────────────────────────────────────
    #  确认告警
    # ──────────────────────────────────────────────────────

    async def acknowledge_alert(
        self,
        alert_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """确认告警 (open -> acknowledged)

        Args:
            alert_id: 告警ID
            tenant_id: 租户ID
            db: 数据库会话

        Returns:
            更新结果
        """
        await self._set_tenant(db, tenant_id)

        sql = text("""
            UPDATE yield_alerts
            SET status = 'acknowledged'
            WHERE id = :alert_id::UUID
              AND tenant_id = :tenant_id
              AND status = 'open'
              AND is_deleted = FALSE
            RETURNING id, status
        """)

        result = await db.execute(
            sql,
            {"alert_id": alert_id, "tenant_id": tenant_id},
        )
        row = result.fetchone()
        await db.commit()

        if not row:
            log.warning(
                "yield_alert.acknowledge_failed",
                alert_id=alert_id,
                reason="not_found_or_wrong_status",
            )
            return {"ok": False, "error": "告警不存在或状态不是 open"}

        log.info("yield_alert.acknowledged", alert_id=alert_id)
        return {"ok": True, "alert_id": alert_id, "status": "acknowledged"}

    # ──────────────────────────────────────────────────────
    #  解决告警
    # ──────────────────────────────────────────────────────

    async def resolve_alert(
        self,
        alert_id: str,
        resolved_by: str,
        note: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """解决告警 (open/acknowledged -> resolved)

        Args:
            alert_id: 告警ID
            resolved_by: 解决人ID
            note: 解决说明
            tenant_id: 租户ID
            db: 数据库会话

        Returns:
            更新结果
        """
        await self._set_tenant(db, tenant_id)

        now = datetime.now(timezone.utc)
        sql = text("""
            UPDATE yield_alerts
            SET status = 'resolved',
                resolved_by = :resolved_by::UUID,
                resolved_at = :resolved_at,
                resolution_note = :note
            WHERE id = :alert_id::UUID
              AND tenant_id = :tenant_id
              AND status IN ('open', 'acknowledged')
              AND is_deleted = FALSE
            RETURNING id, status
        """)

        result = await db.execute(
            sql,
            {
                "alert_id": alert_id,
                "resolved_by": resolved_by,
                "resolved_at": now,
                "note": note,
                "tenant_id": tenant_id,
            },
        )
        row = result.fetchone()
        await db.commit()

        if not row:
            log.warning(
                "yield_alert.resolve_failed",
                alert_id=alert_id,
                reason="not_found_or_already_resolved",
            )
            return {"ok": False, "error": "告警不存在或已解决"}

        log.info(
            "yield_alert.resolved",
            alert_id=alert_id,
            resolved_by=resolved_by,
        )
        return {
            "ok": True,
            "alert_id": alert_id,
            "status": "resolved",
            "resolved_by": resolved_by,
            "resolved_at": now.isoformat(),
        }

    # ──────────────────────────────────────────────────────
    #  损耗趋势
    # ──────────────────────────────────────────────────────

    async def get_yield_trend(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        *,
        ingredient_id: str | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        """损耗趋势分析

        按日汇总 variance_pct, 返回趋势数据 + 统计摘要。

        Args:
            store_id: 门店ID
            tenant_id: 租户ID
            db: 数据库会话
            ingredient_id: 原料ID (None=全部原料)
            days: 回溯天数

        Returns:
            趋势数据字典
        """
        await self._set_tenant(db, tenant_id)

        since_date = date.today() - timedelta(days=days)

        conditions = [
            "tenant_id = :tenant_id",
            "store_id = :store_id::UUID",
            "alert_date >= :since_date",
            "is_deleted = FALSE",
        ]
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "since_date": since_date,
        }

        if ingredient_id:
            conditions.append("ingredient_id = :ingredient_id::UUID")
            params["ingredient_id"] = ingredient_id

        where_clause = " AND ".join(conditions)

        # 按日汇总
        sql_daily = text(f"""
            SELECT
                alert_date,
                COUNT(*) AS alert_count,
                AVG(ABS(variance_pct)) AS avg_variance_pct,
                MAX(ABS(variance_pct)) AS max_variance_pct,
                SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) AS critical_count,
                SUM(CASE WHEN severity = 'warning' THEN 1 ELSE 0 END) AS warning_count,
                SUM(ABS(variance_qty)) AS total_variance_qty
            FROM yield_alerts
            WHERE {where_clause}
            GROUP BY alert_date
            ORDER BY alert_date ASC
        """)

        result = await db.execute(sql_daily, params)
        daily_rows = result.fetchall()

        daily_trend = [
            {
                "date": row.alert_date.isoformat(),
                "alert_count": int(row.alert_count),
                "avg_variance_pct": round(float(row.avg_variance_pct or 0), 2),
                "max_variance_pct": round(float(row.max_variance_pct or 0), 2),
                "critical_count": int(row.critical_count),
                "warning_count": int(row.warning_count),
                "total_variance_qty": round(float(row.total_variance_qty or 0), 2),
            }
            for row in daily_rows
        ]

        # TOP5 超标原料
        sql_top = text(f"""
            SELECT
                ingredient_id,
                ingredient_name,
                COUNT(*) AS alert_count,
                AVG(ABS(variance_pct)) AS avg_variance_pct,
                SUM(ABS(variance_qty)) AS total_variance_qty
            FROM yield_alerts
            WHERE {where_clause}
            GROUP BY ingredient_id, ingredient_name
            ORDER BY AVG(ABS(variance_pct)) DESC
            LIMIT 5
        """)

        top_result = await db.execute(sql_top, params)
        top_rows = top_result.fetchall()

        top_ingredients = [
            {
                "ingredient_id": str(row.ingredient_id),
                "ingredient_name": row.ingredient_name,
                "alert_count": int(row.alert_count),
                "avg_variance_pct": round(float(row.avg_variance_pct or 0), 2),
                "total_variance_qty": round(float(row.total_variance_qty or 0), 2),
            }
            for row in top_rows
        ]

        # 统计摘要
        total_alerts = sum(d["alert_count"] for d in daily_trend)
        total_critical = sum(d["critical_count"] for d in daily_trend)
        total_warning = sum(d["warning_count"] for d in daily_trend)
        avg_daily_variance = (
            sum(d["avg_variance_pct"] for d in daily_trend) / len(daily_trend)
            if daily_trend else 0.0
        )

        trend_data = {
            "store_id": store_id,
            "ingredient_id": ingredient_id,
            "period_days": days,
            "summary": {
                "total_alerts": total_alerts,
                "total_critical": total_critical,
                "total_warning": total_warning,
                "avg_daily_variance_pct": round(avg_daily_variance, 2),
                "days_with_alerts": len(daily_trend),
            },
            "daily_trend": daily_trend,
            "top_ingredients": top_ingredients,
        }

        log.info(
            "yield_alert.trend",
            store_id=store_id,
            ingredient_id=ingredient_id,
            days=days,
            total_alerts=total_alerts,
        )
        return trend_data

    # ──────────────────────────────────────────────────────
    #  更新告警阈值
    # ──────────────────────────────────────────────────────

    def update_thresholds(
        self,
        warning_pct: float | None = None,
        critical_pct: float | None = None,
    ) -> dict[str, float]:
        """更新告警阈值

        Args:
            warning_pct: 警告阈值 (%)
            critical_pct: 严重阈值 (%)

        Returns:
            当前阈值配置
        """
        if warning_pct is not None:
            if warning_pct < 1 or warning_pct > 50:
                raise ValueError("warning_pct 应在 1~50 范围内")
            self._warning_threshold = warning_pct

        if critical_pct is not None:
            if critical_pct < 5 or critical_pct > 80:
                raise ValueError("critical_pct 应在 5~80 范围内")
            self._critical_threshold = critical_pct

        if self._warning_threshold >= self._critical_threshold:
            raise ValueError("warning_pct 必须小于 critical_pct")

        log.info(
            "yield_alert.thresholds_updated",
            warning=self._warning_threshold,
            critical=self._critical_threshold,
        )
        return {
            "warning_pct": self._warning_threshold,
            "critical_pct": self._critical_threshold,
        }
