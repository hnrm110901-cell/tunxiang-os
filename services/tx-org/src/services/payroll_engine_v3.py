"""薪资计算引擎 V3 — 全链路 DB 版（v119 表结构）

依赖关系：
  payroll_engine.py    — 底层纯计算函数（底薪/加班/提成/绩效，无 DB）
  payroll_engine_v3.py — 本模块：读取 v119 新表配置，写入薪资单+明细，汇总分析

与 payroll_engine_db.py 的区别：
  - 读取 payroll_configs（v119）作为薪资方案配置来源
  - 写入 payroll_records + payroll_line_items（v119）
  - 支持按 kpi_score 比例计算绩效奖金
  - 支持计件工资（piecework）
  - 汇总分析含岗位分布、中位数、环比对比

金额单位：统一用分（int）。Decimal 用于比率防止浮点误差。
"""

from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import structlog
from services.payroll_engine import (
    compute_absence_deduction,
    compute_base_salary,
    compute_early_leave_deduction,
    compute_late_deduction,
    compute_overtime_pay,
    compute_seniority_subsidy,
    count_work_days,
    derive_hourly_rate,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class PayrollEngine:
    """薪资计算引擎 V3 — 配合 v119 数据库表使用

    所有公开方法均为 async，接受 SQLAlchemy AsyncSession。
    tenant_id 通过 set_tenant() 写入 app.tenant_id session 变量，配合 RLS 双重隔离。
    """

    # ── 内部工具 ──────────────────────────────────────────────────────────

    @staticmethod
    async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
        """设置 RLS session 变量"""
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    @staticmethod
    def _period_dates(year: int, month: int) -> tuple[date, date]:
        """返回 (月初, 月末) date 对象"""
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last_day)

    # ── 步骤 1：读取薪资配置 ──────────────────────────────────────────────

    async def _get_config(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        employee_role: str,
        as_of: date,
    ) -> dict[str, Any] | None:
        """
        按 (store_id, employee_role, effective_from 最新) 取薪资方案。
        若 store 级找不到，退而取品牌级（store_id IS NULL）。
        """
        sql = text("""
            SELECT
                id, salary_type,
                base_salary_fen, hourly_rate_fen,
                piecework_unit, piecework_rate_fen,
                commission_type, commission_rate, commission_base,
                kpi_bonus_max_fen
            FROM payroll_configs
            WHERE tenant_id = :tenant_id
              AND employee_role = :role
              AND is_active = true
              AND is_deleted = false
              AND effective_from <= :as_of
              AND (effective_to IS NULL OR effective_to >= :as_of)
              AND (store_id = :store_id OR store_id IS NULL)
            ORDER BY
                (store_id = :store_id) DESC,   -- 门店级优先
                effective_from DESC
            LIMIT 1
        """)
        row = (
            (
                await db.execute(
                    sql,
                    {
                        "tenant_id": tenant_id,
                        "store_id": store_id,
                        "role": employee_role,
                        "as_of": as_of,
                    },
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    # ── 步骤 2：读取当月日绩效汇总 ────────────────────────────────────────

    async def _get_monthly_performance(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        employee_id: str,
        year: int,
        month: int,
    ) -> dict[str, Any]:
        """
        从 employee_daily_performance（v116）按月聚合：
          - 出勤天数（有记录的天数）
          - 总计件数（orders_handled + dishes_completed + tables_served）
          - 总营收（revenue_generated_fen）
          - 平均服务评分
          - 加班小时（暂不从此表读取，交给调用方传入）
        """
        sql = text("""
            SELECT
                COUNT(DISTINCT perf_date)            AS attendance_days,
                SUM(orders_handled)                  AS total_orders,
                SUM(dishes_completed)                AS total_dishes,
                SUM(tables_served)                   AS total_tables,
                SUM(revenue_generated_fen)           AS total_revenue_fen,
                AVG(avg_service_score)               AS avg_score,
                SUM(base_commission_fen)             AS base_commission_fen
            FROM employee_daily_performance
            WHERE tenant_id = :tenant_id
              AND store_id   = :store_id
              AND employee_id = :employee_id
              AND perf_date >= :period_start
              AND perf_date <= :period_end
        """)
        period_start, period_end = self._period_dates(year, month)
        row = (
            (
                await db.execute(
                    sql,
                    {
                        "tenant_id": tenant_id,
                        "store_id": store_id,
                        "employee_id": employee_id,
                        "period_start": period_start,
                        "period_end": period_end,
                    },
                )
            )
            .mappings()
            .first()
        )

        if not row:
            return {
                "attendance_days": 0,
                "total_orders": 0,
                "total_dishes": 0,
                "total_tables": 0,
                "total_revenue_fen": 0,
                "avg_score": None,
                "base_commission_fen": 0,
            }
        return {
            "attendance_days": int(row["attendance_days"] or 0),
            "total_orders": int(row["total_orders"] or 0),
            "total_dishes": int(row["total_dishes"] or 0),
            "total_tables": int(row["total_tables"] or 0),
            "total_revenue_fen": int(row["total_revenue_fen"] or 0),
            "avg_score": float(row["avg_score"]) if row["avg_score"] is not None else None,
            "base_commission_fen": int(row["base_commission_fen"] or 0),
        }

    # ── 步骤 3：核心计算逻辑 ──────────────────────────────────────────────

    def _compute_items(
        self,
        cfg: dict[str, Any],
        perf: dict[str, Any],
        year: int,
        month: int,
        *,
        overtime_hours: float = 0.0,
        kpi_score: float = 0.0,
        absence_days: float = 0.0,
        late_count: int = 0,
        early_leave_count: int = 0,
        late_deduction_per_time_fen: int = 5_000,
        early_leave_deduction_per_time_fen: int = 5_000,
        seniority_months: int = 0,
    ) -> tuple[int, int, int, int, int, int, list[dict[str, Any]]]:
        """
        返回 (base_pay, overtime_pay, commission, piecework_pay, kpi_bonus,
               deduction_total, line_items)
        """
        work_days = count_work_days(year, month)
        attendance_days = perf["attendance_days"]
        salary_type: str = cfg.get("salary_type", "monthly")
        line_items: list[dict[str, Any]] = []

        # ── 底薪 ────────────────────────────────────────────────────────
        if salary_type == "monthly":
            base_salary_fen: int = cfg.get("base_salary_fen") or 0
            base_pay = compute_base_salary(base_salary_fen, attendance_days, work_days)
            line_items.append(
                {
                    "item_type": "base",
                    "item_name": "基本工资",
                    "amount_fen": base_pay,
                    "quantity": Decimal(str(attendance_days)),
                    "unit_price_fen": int(base_salary_fen / work_days) if work_days else 0,
                    "notes": f"月薪{base_salary_fen}分 × 出勤{attendance_days}天/{work_days}天",
                }
            )
        elif salary_type == "hourly":
            hourly_rate: int = cfg.get("hourly_rate_fen") or 0
            work_hours = attendance_days * 8
            base_pay = int(hourly_rate * work_hours)
            line_items.append(
                {
                    "item_type": "base",
                    "item_name": "时薪基本工资",
                    "amount_fen": base_pay,
                    "quantity": Decimal(str(work_hours)),
                    "unit_price_fen": hourly_rate,
                    "notes": f"时薪{hourly_rate}分 × {work_hours}小时",
                }
            )
            base_salary_fen = hourly_rate * work_days * 8  # 用于后续推算
        else:
            # piecework 无底薪
            base_pay = 0
            base_salary_fen = 0

        # ── 工龄补贴（计入底薪分项，减少 line_items 行数） ────────────────
        seniority_fen = compute_seniority_subsidy(seniority_months)
        if seniority_fen > 0:
            base_pay += seniority_fen
            line_items.append(
                {
                    "item_type": "base",
                    "item_name": "工龄补贴",
                    "amount_fen": seniority_fen,
                    "quantity": None,
                    "unit_price_fen": None,
                    "notes": f"司龄{seniority_months}个月",
                }
            )

        # ── 加班费 ────────────────────────────────────────────────────────
        if overtime_hours > 0:
            if salary_type == "hourly":
                hourly_for_ot = cfg.get("hourly_rate_fen") or 0
            else:
                hourly_for_ot = derive_hourly_rate(base_salary_fen or 1, work_days)
            overtime_pay = compute_overtime_pay(hourly_for_ot, overtime_hours, "weekday")
            line_items.append(
                {
                    "item_type": "overtime",
                    "item_name": "加班费",
                    "amount_fen": overtime_pay,
                    "quantity": Decimal(str(overtime_hours)),
                    "unit_price_fen": int(hourly_for_ot * 1.5),
                    "notes": f"加班{overtime_hours}小时 × 时薪{hourly_for_ot}分 × 1.5倍",
                }
            )
        else:
            overtime_pay = 0

        # ── 提成 ──────────────────────────────────────────────────────────
        commission_type: str = cfg.get("commission_type") or "none"
        if commission_type == "percentage":
            commission_rate = Decimal(str(cfg.get("commission_rate") or "0"))
            commission_base_key: str = cfg.get("commission_base") or "revenue"
            if commission_base_key == "revenue":
                base_amount_fen = perf["total_revenue_fen"]
            else:
                base_amount_fen = perf.get("total_revenue_fen", 0)  # profit 暂用 revenue 代替
            commission = int(base_amount_fen * commission_rate)
            if commission > 0:
                line_items.append(
                    {
                        "item_type": "commission",
                        "item_name": "销售提成",
                        "amount_fen": commission,
                        "quantity": Decimal(str(base_amount_fen)),
                        "unit_price_fen": None,
                        "notes": f"{commission_base_key}基数{base_amount_fen}分 × {commission_rate}",
                    }
                )
        elif commission_type == "fixed":
            commission = perf.get("base_commission_fen", 0)
            if commission > 0:
                line_items.append(
                    {
                        "item_type": "commission",
                        "item_name": "固定提成",
                        "amount_fen": commission,
                        "quantity": None,
                        "unit_price_fen": None,
                        "notes": "按日绩效固定提成汇总",
                    }
                )
        else:
            commission = 0

        # ── 计件工资 ───────────────────────────────────────────────────────
        piecework_rate: int = cfg.get("piecework_rate_fen") or 0
        piecework_unit: str = cfg.get("piecework_unit") or "per_order"
        if salary_type == "piecework" and piecework_rate > 0:
            if piecework_unit == "per_dish":
                piece_count = perf["total_dishes"]
                unit_label = "菜品"
            elif piecework_unit == "per_table":
                piece_count = perf["total_tables"]
                unit_label = "桌次"
            else:
                piece_count = perf["total_orders"]
                unit_label = "订单"
            piecework_pay = piece_count * piecework_rate
            line_items.append(
                {
                    "item_type": "piecework",
                    "item_name": f"计件工资（{unit_label}）",
                    "amount_fen": piecework_pay,
                    "quantity": Decimal(str(piece_count)),
                    "unit_price_fen": piecework_rate,
                    "notes": f"{piece_count}{unit_label} × {piecework_rate}分",
                }
            )
        else:
            piecework_pay = 0

        # ── 绩效奖金：kpi_score/100 × kpi_bonus_max ───────────────────────
        kpi_bonus_max: int = cfg.get("kpi_bonus_max_fen") or 0
        if kpi_bonus_max > 0 and kpi_score > 0:
            kpi_ratio = Decimal(str(min(kpi_score, 100))) / Decimal("100")
            kpi_bonus = int(kpi_bonus_max * kpi_ratio)
            line_items.append(
                {
                    "item_type": "kpi",
                    "item_name": "绩效奖金",
                    "amount_fen": kpi_bonus,
                    "quantity": Decimal(str(kpi_score)),
                    "unit_price_fen": kpi_bonus_max,
                    "notes": f"KPI得分{kpi_score} × 上限{kpi_bonus_max}分",
                }
            )
        else:
            kpi_bonus = 0

        # ── 考勤扣款 ───────────────────────────────────────────────────────
        abs_ded = compute_absence_deduction(
            base_salary_fen if base_salary_fen else piecework_rate * 100,
            absence_days,
            work_days,
        )
        late_ded = compute_late_deduction(late_count, late_deduction_per_time_fen)
        early_ded = compute_early_leave_deduction(early_leave_count, early_leave_deduction_per_time_fen)
        deduction_total = abs_ded + late_ded + early_ded

        if abs_ded > 0:
            line_items.append(
                {
                    "item_type": "deduction",
                    "item_name": "缺勤扣款",
                    "amount_fen": -abs_ded,
                    "quantity": Decimal(str(absence_days)),
                    "unit_price_fen": None,
                    "notes": f"缺勤{absence_days}天",
                }
            )
        if late_ded > 0:
            line_items.append(
                {
                    "item_type": "deduction",
                    "item_name": "迟到扣款",
                    "amount_fen": -late_ded,
                    "quantity": Decimal(str(late_count)),
                    "unit_price_fen": late_deduction_per_time_fen,
                    "notes": f"迟到{late_count}次 × {late_deduction_per_time_fen}分/次",
                }
            )
        if early_ded > 0:
            line_items.append(
                {
                    "item_type": "deduction",
                    "item_name": "早退扣款",
                    "amount_fen": -early_ded,
                    "quantity": Decimal(str(early_leave_count)),
                    "unit_price_fen": early_leave_deduction_per_time_fen,
                    "notes": f"早退{early_leave_count}次 × {early_leave_deduction_per_time_fen}分/次",
                }
            )

        return (
            base_pay,
            overtime_pay,
            commission,
            piecework_pay,
            kpi_bonus,
            deduction_total,
            line_items,
        )

    # ── 步骤 4：upsert payroll_records ────────────────────────────────────

    async def _upsert_record(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        employee_id: str,
        period_start: date,
        period_end: date,
        base_pay_fen: int,
        overtime_pay_fen: int,
        commission_fen: int,
        piecework_pay_fen: int,
        kpi_bonus_fen: int,
        deduction_fen: int,
        gross_pay_fen: int,
        tax_fen: int,
        net_pay_fen: int,
        snapshot: dict[str, Any],
    ) -> str:
        """UPSERT payroll_records，返回 record_id（UUID str）"""
        sql = text("""
            INSERT INTO payroll_records (
                tenant_id, store_id, employee_id,
                pay_period_start, pay_period_end,
                base_pay_fen, overtime_pay_fen, commission_fen,
                piecework_pay_fen, kpi_bonus_fen, deduction_fen,
                gross_pay_fen, tax_fen, net_pay_fen,
                status, calc_snapshot, updated_at
            ) VALUES (
                :tenant_id, :store_id, :employee_id,
                :period_start, :period_end,
                :base_pay, :overtime_pay, :commission,
                :piecework_pay, :kpi_bonus, :deduction,
                :gross_pay, :tax, :net_pay,
                'draft', :snapshot, now()
            )
            ON CONFLICT (tenant_id, employee_id, pay_period_start)
            DO UPDATE SET
                base_pay_fen      = EXCLUDED.base_pay_fen,
                overtime_pay_fen  = EXCLUDED.overtime_pay_fen,
                commission_fen    = EXCLUDED.commission_fen,
                piecework_pay_fen = EXCLUDED.piecework_pay_fen,
                kpi_bonus_fen     = EXCLUDED.kpi_bonus_fen,
                deduction_fen     = EXCLUDED.deduction_fen,
                gross_pay_fen     = EXCLUDED.gross_pay_fen,
                tax_fen           = EXCLUDED.tax_fen,
                net_pay_fen       = EXCLUDED.net_pay_fen,
                calc_snapshot     = EXCLUDED.calc_snapshot,
                updated_at        = now()
            WHERE payroll_records.status = 'draft'
            RETURNING id
        """)
        import json

        result = await db.execute(
            sql,
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "employee_id": employee_id,
                "period_start": period_start,
                "period_end": period_end,
                "base_pay": base_pay_fen,
                "overtime_pay": overtime_pay_fen,
                "commission": commission_fen,
                "piecework_pay": piecework_pay_fen,
                "kpi_bonus": kpi_bonus_fen,
                "deduction": deduction_fen,
                "gross_pay": gross_pay_fen,
                "tax": tax_fen,
                "net_pay": net_pay_fen,
                "snapshot": json.dumps(snapshot, default=str),
            },
        )
        row = result.fetchone()
        if not row:
            # 已存在且非 draft 状态，查询返回现有 id
            lookup = await db.execute(
                text("""
                    SELECT id FROM payroll_records
                    WHERE tenant_id = :tenant_id
                      AND employee_id = :employee_id
                      AND pay_period_start = :period_start
                      AND is_deleted = false
                    LIMIT 1
                """),
                {
                    "tenant_id": tenant_id,
                    "employee_id": employee_id,
                    "period_start": period_start,
                },
            )
            row = lookup.fetchone()
        return str(row[0])

    # ── 步骤 5：写入 payroll_line_items ───────────────────────────────────

    async def _write_line_items(
        self,
        db: AsyncSession,
        tenant_id: str,
        record_id: str,
        line_items: list[dict[str, Any]],
        tax_fen: int,
    ) -> None:
        """先删除旧明细（若 draft 状态），再批量插入新明细"""
        # 删除旧明细
        await db.execute(
            text("""
                DELETE FROM payroll_line_items
                WHERE record_id = :record_id
                  AND tenant_id = :tenant_id
            """),
            {"record_id": record_id, "tenant_id": tenant_id},
        )

        # 插入各项明细
        items_to_insert = list(line_items)
        if tax_fen > 0:
            items_to_insert.append(
                {
                    "item_type": "tax",
                    "item_name": "个人所得税",
                    "amount_fen": -tax_fen,
                    "quantity": None,
                    "unit_price_fen": None,
                    "notes": "累计预扣法",
                }
            )

        for item in items_to_insert:
            await db.execute(
                text("""
                    INSERT INTO payroll_line_items
                        (tenant_id, record_id, item_type, item_name,
                         amount_fen, quantity, unit_price_fen, notes)
                    VALUES
                        (:tenant_id, :record_id, :item_type, :item_name,
                         :amount_fen, :quantity, :unit_price_fen, :notes)
                """),
                {
                    "tenant_id": tenant_id,
                    "record_id": record_id,
                    "item_type": item["item_type"],
                    "item_name": item["item_name"],
                    "amount_fen": item["amount_fen"],
                    "quantity": item.get("quantity"),
                    "unit_price_fen": item.get("unit_price_fen"),
                    "notes": item.get("notes"),
                },
            )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  公开接口
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def calculate_monthly_payroll(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        employee_id: str,
        year: int,
        month: int,
        *,
        employee_role: str = "waiter",
        overtime_hours: float = 0.0,
        kpi_score: float = 0.0,
        absence_days: float = 0.0,
        late_count: int = 0,
        early_leave_count: int = 0,
        late_deduction_per_time_fen: int = 5_000,
        early_leave_deduction_per_time_fen: int = 5_000,
        seniority_months: int = 0,
        ytd_income_yuan: float = 0.0,
        ytd_tax_paid_yuan: float = 0.0,
        ytd_social_insurance_yuan: float = 0.0,
        month_index: int | None = None,
        special_deduction_monthly_yuan: float = 0.0,
    ) -> dict[str, Any]:
        """计算单个员工月薪，upsert payroll_records，写入 payroll_line_items。

        步骤：
          1. 取 payroll_configs 最新配置
          2. 取 employee_daily_performance 月度汇总
          3. 计算各收支项
          4. 简单个税估算（累计预扣法）
          5. UPSERT payroll_records（status=draft）
          6. 写入 payroll_line_items 明细
          7. COMMIT 并返回完整薪资单 dict

        Args:
            db: AsyncSession
            tenant_id: 租户 UUID 字符串
            store_id: 门店 UUID 字符串
            employee_id: 员工 UUID 字符串
            year / month: 薪资年月
            employee_role: 岗位（cashier/chef/waiter/manager）
            overtime_hours: 当月加班总小时
            kpi_score: KPI 得分（0-100）
            absence_days: 缺勤天数
            late_count: 迟到次数
            early_leave_count: 早退次数
            late_deduction_per_time_fen: 每次迟到扣款（分）
            early_leave_deduction_per_time_fen: 每次早退扣款（分）
            seniority_months: 司龄月数
            ytd_income_yuan: 年初至今（不含当月）累计应税收入（元）
            ytd_tax_paid_yuan: 年初至今已预缴税（元）
            ytd_social_insurance_yuan: 年初至今社保+公积金个人部分（元）
            month_index: 当年第几月（None 时自动取 month）
            special_deduction_monthly_yuan: 月专项附加扣除（元）

        Returns:
            完整薪资单 dict（含 record_id、各分项、明细行列表）
        """
        await self._set_tenant(db, tenant_id)

        period_start, period_end = self._period_dates(year, month)
        actual_month_index = month_index if month_index is not None else month

        # 1. 薪资配置
        cfg = await self._get_config(db, tenant_id, store_id, employee_role, period_start)
        if not cfg:
            log.warning(
                "payroll_config_missing",
                tenant_id=tenant_id,
                store_id=store_id,
                role=employee_role,
                year=year,
                month=month,
            )
            cfg = {
                "salary_type": "monthly",
                "base_salary_fen": 0,
                "hourly_rate_fen": None,
                "piecework_unit": None,
                "piecework_rate_fen": None,
                "commission_type": "none",
                "commission_rate": None,
                "commission_base": None,
                "kpi_bonus_max_fen": 0,
            }

        # 2. 日绩效汇总
        perf = await self._get_monthly_performance(db, tenant_id, store_id, employee_id, year, month)

        # 3. 计算各项
        (
            base_pay_fen,
            overtime_pay_fen,
            commission_fen,
            piecework_pay_fen,
            kpi_bonus_fen,
            deduction_fen,
            line_items,
        ) = self._compute_items(
            cfg,
            perf,
            year,
            month,
            overtime_hours=overtime_hours,
            kpi_score=kpi_score,
            absence_days=absence_days,
            late_count=late_count,
            early_leave_count=early_leave_count,
            late_deduction_per_time_fen=late_deduction_per_time_fen,
            early_leave_deduction_per_time_fen=early_leave_deduction_per_time_fen,
            seniority_months=seniority_months,
        )

        gross_pay_fen = (
            base_pay_fen + overtime_pay_fen + commission_fen + piecework_pay_fen + kpi_bonus_fen - deduction_fen
        )
        gross_pay_fen = max(0, gross_pay_fen)

        # 4. 简易个税（累计预扣法）
        from services.income_tax import IncomeTaxCalculator

        tax_calc = IncomeTaxCalculator()
        tax_result = tax_calc.calculate_monthly(
            current_month_income=gross_pay_fen / 100.0,
            ytd_income=ytd_income_yuan,
            ytd_tax_paid=ytd_tax_paid_yuan,
            ytd_social_insurance=ytd_social_insurance_yuan,
            month_index=actual_month_index,
            special_deduction_monthly=special_deduction_monthly_yuan,
        )
        tax_fen = int(tax_result.get("monthly_tax", 0.0) * 100)
        net_pay_fen = max(0, gross_pay_fen - tax_fen)

        # 计算快照
        snapshot = {
            "config_id": str(cfg.get("id", "")),
            "salary_type": cfg.get("salary_type"),
            "perf_summary": perf,
            "kpi_score": kpi_score,
            "overtime_hours": overtime_hours,
            "absence_days": absence_days,
            "late_count": late_count,
            "early_leave_count": early_leave_count,
            "tax_detail": tax_result,
            "computed_at": datetime.now().isoformat(),
        }

        # 5. UPSERT payroll_records
        record_id = await self._upsert_record(
            db,
            tenant_id=tenant_id,
            store_id=store_id,
            employee_id=employee_id,
            period_start=period_start,
            period_end=period_end,
            base_pay_fen=base_pay_fen,
            overtime_pay_fen=overtime_pay_fen,
            commission_fen=commission_fen,
            piecework_pay_fen=piecework_pay_fen,
            kpi_bonus_fen=kpi_bonus_fen,
            deduction_fen=deduction_fen,
            gross_pay_fen=gross_pay_fen,
            tax_fen=tax_fen,
            net_pay_fen=net_pay_fen,
            snapshot=snapshot,
        )

        # 6. 写入明细行
        await self._write_line_items(db, tenant_id, record_id, line_items, tax_fen)

        await db.commit()

        log.info(
            "payroll_calculated",
            tenant_id=tenant_id,
            employee_id=employee_id,
            record_id=record_id,
            gross_pay_fen=gross_pay_fen,
            net_pay_fen=net_pay_fen,
        )

        return {
            "record_id": record_id,
            "tenant_id": tenant_id,
            "store_id": store_id,
            "employee_id": employee_id,
            "pay_period_start": period_start.isoformat(),
            "pay_period_end": period_end.isoformat(),
            "base_pay_fen": base_pay_fen,
            "overtime_pay_fen": overtime_pay_fen,
            "commission_fen": commission_fen,
            "piecework_pay_fen": piecework_pay_fen,
            "kpi_bonus_fen": kpi_bonus_fen,
            "deduction_fen": deduction_fen,
            "gross_pay_fen": gross_pay_fen,
            "tax_fen": tax_fen,
            "net_pay_fen": net_pay_fen,
            "status": "draft",
            "line_items": [
                {
                    **item,
                    "quantity": float(item["quantity"]) if item.get("quantity") is not None else None,
                }
                for item in line_items
            ],
        }

    async def batch_calculate_store(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        year: int,
        month: int,
    ) -> list[dict[str, Any]]:
        """批量计算门店所有员工当月薪资。

        从 employee_daily_performance 表读取当月有记录的所有员工，
        逐个调用 calculate_monthly_payroll。
        """
        await self._set_tenant(db, tenant_id)
        period_start, period_end = self._period_dates(year, month)

        # 取当月有绩效记录的员工列表
        employees_result = await db.execute(
            text("""
                SELECT DISTINCT employee_id, role
                FROM employee_daily_performance
                WHERE tenant_id  = :tenant_id
                  AND store_id   = :store_id
                  AND perf_date >= :period_start
                  AND perf_date <= :period_end
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "period_start": period_start,
                "period_end": period_end,
            },
        )
        employees = employees_result.mappings().all()

        results: list[dict[str, Any]] = []
        for emp in employees:
            try:
                record = await self.calculate_monthly_payroll(
                    db,
                    tenant_id,
                    store_id,
                    str(emp["employee_id"]),
                    year,
                    month,
                    employee_role=emp.get("role", "waiter"),
                    month_index=month,
                )
                results.append(record)
            except (ValueError, KeyError, LookupError) as exc:
                log.error(
                    "batch_payroll_employee_error",
                    tenant_id=tenant_id,
                    employee_id=str(emp["employee_id"]),
                    error=str(exc),
                )
                results.append(
                    {
                        "employee_id": str(emp["employee_id"]),
                        "error": str(exc),
                        "status": "error",
                    }
                )

        return results

    async def approve_payroll(
        self,
        db: AsyncSession,
        tenant_id: str,
        record_id: str,
        approved_by: str,
    ) -> dict[str, Any]:
        """审批薪资单：draft → approved。

        只有 draft 状态的薪资单可以审批。
        """
        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                UPDATE payroll_records
                SET status      = 'approved',
                    approved_by = :approved_by,
                    approved_at = now(),
                    updated_at  = now()
                WHERE id        = :record_id
                  AND tenant_id = :tenant_id
                  AND status    = 'draft'
                  AND is_deleted = false
                RETURNING id, status, approved_by, approved_at
            """),
            {
                "record_id": record_id,
                "tenant_id": tenant_id,
                "approved_by": approved_by,
            },
        )
        row = result.mappings().first()
        if not row:
            raise ValueError(f"薪资单不存在或状态非 draft: record_id={record_id}")

        await db.commit()
        log.info(
            "payroll_approved",
            tenant_id=tenant_id,
            record_id=record_id,
            approved_by=approved_by,
        )
        return {
            "record_id": str(row["id"]),
            "status": row["status"],
            "approved_by": row["approved_by"],
            "approved_at": row["approved_at"].isoformat() if row["approved_at"] else None,
        }

    async def get_payroll_summary(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        year: int,
        month: int,
    ) -> dict[str, Any]:
        """门店月度薪资汇总分析。

        返回：
          - 总人数 / 总薪资 / 人均薪资
          - 各岗位薪资分布（需 JOIN employee_daily_performance 取岗位）
          - 最高 / 最低 / 中位数
          - 与上月对比（环比）
        """
        await self._set_tenant(db, tenant_id)
        period_start, period_end = self._period_dates(year, month)

        # 当月汇总
        curr_sql = text("""
            SELECT
                COUNT(*)                        AS headcount,
                SUM(gross_pay_fen)              AS total_gross_fen,
                SUM(net_pay_fen)                AS total_net_fen,
                SUM(tax_fen)                    AS total_tax_fen,
                MAX(gross_pay_fen)              AS max_gross_fen,
                MIN(gross_pay_fen)              AS min_gross_fen,
                PERCENTILE_CONT(0.5)
                    WITHIN GROUP (ORDER BY gross_pay_fen) AS median_gross_fen,
                AVG(gross_pay_fen)              AS avg_gross_fen
            FROM payroll_records
            WHERE tenant_id       = :tenant_id
              AND store_id        = :store_id
              AND pay_period_start = :period_start
              AND status         != 'voided'
              AND is_deleted      = false
        """)
        curr_row = (
            (
                await db.execute(
                    curr_sql,
                    {
                        "tenant_id": tenant_id,
                        "store_id": store_id,
                        "period_start": period_start,
                    },
                )
            )
            .mappings()
            .first()
        )

        # 上月对比
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        prev_period_start, _ = self._period_dates(prev_year, prev_month)

        prev_sql = text("""
            SELECT
                COUNT(*)           AS headcount,
                SUM(gross_pay_fen) AS total_gross_fen,
                SUM(net_pay_fen)   AS total_net_fen
            FROM payroll_records
            WHERE tenant_id        = :tenant_id
              AND store_id         = :store_id
              AND pay_period_start  = :period_start
              AND status          != 'voided'
              AND is_deleted       = false
        """)
        prev_row = (
            (
                await db.execute(
                    prev_sql,
                    {
                        "tenant_id": tenant_id,
                        "store_id": store_id,
                        "period_start": prev_period_start,
                    },
                )
            )
            .mappings()
            .first()
        )

        # 环比计算
        def _ratio(curr_val: float | None, prev_val: float | None) -> float | None:
            if prev_val and prev_val != 0:
                return round(((curr_val or 0) - prev_val) / prev_val * 100, 2)
            return None

        curr_headcount = int(curr_row["headcount"] or 0)
        curr_gross = int(curr_row["total_gross_fen"] or 0)
        curr_net = int(curr_row["total_net_fen"] or 0)
        curr_tax = int(curr_row["total_tax_fen"] or 0)
        curr_max = int(curr_row["max_gross_fen"] or 0)
        curr_min = int(curr_row["min_gross_fen"] or 0)
        curr_median = float(curr_row["median_gross_fen"] or 0)
        curr_avg = float(curr_row["avg_gross_fen"] or 0)

        prev_headcount = int(prev_row["headcount"] or 0)
        prev_gross = int(prev_row["total_gross_fen"] or 0)
        prev_net = int(prev_row["total_net_fen"] or 0)

        return {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "year": year,
            "month": month,
            "pay_period_start": period_start.isoformat(),
            "pay_period_end": period_end.isoformat(),
            "headcount": curr_headcount,
            "total_gross_fen": curr_gross,
            "total_net_fen": curr_net,
            "total_tax_fen": curr_tax,
            "avg_gross_fen": int(curr_avg),
            "max_gross_fen": curr_max,
            "min_gross_fen": curr_min,
            "median_gross_fen": int(curr_median),
            "prev_month": {
                "year": prev_year,
                "month": prev_month,
                "headcount": prev_headcount,
                "total_gross_fen": prev_gross,
                "total_net_fen": prev_net,
            },
            "mom_gross_pct": _ratio(curr_gross, prev_gross),
            "mom_headcount_delta": curr_headcount - prev_headcount,
        }
