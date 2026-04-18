"""
D12 z66 — 种子薪资项目库（移植自 tunxiang-os tx-org.salary_item_library）

覆盖 7 大分类、共 40 项核心薪资项目（对标 i人事 138 项精简版）：
  - 出勤(8)  attendance
  - 假期(4)  leave
  - 绩效(6)  performance
  - 提成(5)  commission
  - 补贴(7)  subsidy
  - 扣款(5)  deduction
  - 社保(5)  social + 其他公积金

所有项目均带 tax_attribute 标识：
  - pre_tax_add:     税前加项（应税收入）
  - pre_tax_deduct:  税前扣项（社保公积金个人）
  - after_tax_deduct: 税后扣项（罚款/借支）
  - non_tax:         免税/非税补贴

用法：
  cd apps/api-gateway
  python -m scripts.seed_salary_items --brand-id BRAND001
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from typing import Any, Dict, List

import structlog
from sqlalchemy import text

# 允许从 apps/api-gateway 根运行
sys.path.insert(0, ".")

from src.core.database import get_db_session  # noqa: E402

logger = structlog.get_logger(__name__)


# ── 薪资项目定义：(code, name, category, tax_attribute, formula_type, formula, calc_order, remark) ──
SEED_ITEMS: List[Dict[str, Any]] = [
    # ── 出勤类（8项） ──
    ("ATT_001", "基本工资", "attendance", "pre_tax_add", "fixed", "", 10, "月薪标准"),
    ("ATT_002", "岗位工资", "attendance", "pre_tax_add", "fixed", "", 11, "岗位等级工资"),
    ("ATT_005", "出勤工资", "attendance", "pre_tax_add", "formula",
     "base_salary_fen * attendance_days / work_days_in_month", 12, "按出勤比例折算"),
    ("ATT_008", "计件工资", "attendance", "pre_tax_add", "formula",
     "piece_count * piece_rate_fen", 13, "按件计薪"),
    ("ATT_010", "试用期工资", "attendance", "pre_tax_add", "formula",
     "base_salary_fen * 0.8", 14, "试用期按80%"),
    ("ATT_013", "兼职日薪", "attendance", "pre_tax_add", "manual", "", 15, "兼职按天计薪"),
    ("ATT_014", "小时工时薪", "attendance", "pre_tax_add", "formula",
     "hourly_rate_fen * overtime_hours", 16, "小时工"),
    ("OT_001", "加班费", "attendance", "pre_tax_add", "formula",
     "hourly_rate_fen * overtime_hours * 1.5", 17, "平时加班1.5倍"),

    # ── 假期类（4项） ──
    ("LV_001", "年假工资", "leave", "pre_tax_add", "manual", "", 20, "带薪年假工资"),
    ("LV_002", "病假工资", "leave", "pre_tax_add", "manual", "", 21, "病假60%日薪"),
    ("LV_004", "产假工资", "leave", "pre_tax_add", "manual", "", 22, "产假全薪"),
    ("LV_007", "工伤假工资", "leave", "pre_tax_add", "manual", "", 23, "工伤假全薪"),

    # ── 绩效类（6项） ──
    ("PERF_002", "月度绩效", "performance", "pre_tax_add", "manual", "", 30, "月度绩效奖金"),
    ("PERF_003", "季度绩效", "performance", "pre_tax_add", "manual", "", 31, "季度绩效奖金"),
    ("PERF_004", "年终奖", "performance", "pre_tax_add", "manual", "", 32, "年度绩效奖金"),
    ("PERF_008", "安全生产奖", "performance", "pre_tax_add", "fixed", "", 33, "无事故奖"),
    ("PERF_010", "全勤奖", "performance", "pre_tax_add", "fixed", "", 34, "无缺勤发放，默认300元"),
    ("PERF_011", "优秀员工奖", "performance", "pre_tax_add", "manual", "", 35, "月度/季度优秀员工"),

    # ── 提成类（5项） ──
    ("COMM_001", "营业额提成", "commission", "pre_tax_add", "formula",
     "sales_amount_fen * commission_rate", 40, "按营业额比例"),
    ("COMM_003", "推菜提成", "commission", "pre_tax_add", "manual", "", 41, "主推菜提成"),
    ("COMM_004", "酒水提成", "commission", "pre_tax_add", "manual", "", 42, "酒水销售提成"),
    ("COMM_006", "会员开卡提成", "commission", "pre_tax_add", "manual", "", 43, "开卡奖励"),
    ("COMM_010", "宴席提成", "commission", "pre_tax_add", "manual", "", 44, "宴席订单提成"),

    # ── 补贴类（7项） ──
    ("SUB_001", "工龄补贴", "subsidy", "pre_tax_add", "formula",
     "seniority_subsidy(seniority_months)", 50, "按工龄阶梯"),
    ("SUB_002", "交通补贴", "subsidy", "pre_tax_add", "fixed", "", 51, "默认200元"),
    ("SUB_003", "餐补", "subsidy", "non_tax", "fixed", "", 52,
     "员工餐补贴，按国税【2012】15号可视为非税"),
    ("SUB_004", "住房补贴", "subsidy", "pre_tax_add", "fixed", "", 53, "宿舍以外的住宿补贴"),
    ("SUB_005", "高温补贴", "subsidy", "pre_tax_add", "fixed", "", 54, "6-9月高温岗位"),
    ("SUB_007", "技能补贴", "subsidy", "pre_tax_add", "fixed", "", 55, "持证补贴"),
    ("SUB_009", "通讯补贴", "subsidy", "pre_tax_add", "fixed", "", 56, "手机通讯补贴"),

    # ── 扣款类（5项） ──
    ("DED_001", "迟到扣款", "deduction", "pre_tax_deduct", "formula",
     "late_count * late_deduction_per_time_fen", 60, "迟到次数x每次扣款"),
    ("DED_003", "旷工扣款", "deduction", "pre_tax_deduct", "formula",
     "base_salary_fen / work_days_in_month * absent_days * 3", 61, "旷工按日薪3倍"),
    ("DED_005", "违规罚款", "deduction", "after_tax_deduct", "manual", "", 62,
     "税后扣罚款（个税计算后扣）"),
    ("DED_006", "赔偿扣款", "deduction", "after_tax_deduct", "manual", "", 63,
     "餐具/设备损坏赔偿"),
    ("DED_007", "借支扣回", "deduction", "after_tax_deduct", "manual", "", 64, "预借工资扣回"),

    # ── 社保类（5项，均税前扣除） ──
    ("SOC_001", "养老保险(个人)", "social", "pre_tax_deduct", "formula",
     "social_base_fen * 0.08", 70, "个人8%"),
    ("SOC_002", "医疗保险(个人)", "social", "pre_tax_deduct", "formula",
     "social_base_fen * 0.02", 71, "个人2%"),
    ("SOC_003", "失业保险(个人)", "social", "pre_tax_deduct", "formula",
     "social_base_fen * 0.005", 72, "个人0.5%"),
    ("SOC_004", "住房公积金(个人)", "social", "pre_tax_deduct", "formula",
     "housing_fund_base_fen * housing_fund_rate", 73, "个人5%-12%"),
    ("SOC_006", "企业年金(个人)", "social", "pre_tax_deduct", "fixed", "", 74, "补充养老"),
]


async def run(brand_id: str, store_id: str | None = None) -> None:
    async with get_db_session(enable_tenant_isolation=False) as db:
        inserted = 0
        skipped = 0
        for (code, name, category, tax_attr, ftype, formula, order, remark) in SEED_ITEMS:
            # 幂等：按 (brand_id, item_code) 判重
            existing = await db.execute(
                text(
                    "SELECT 1 FROM salary_item_definitions "
                    "WHERE brand_id = :b AND item_code = :c LIMIT 1"
                ),
                {"b": brand_id, "c": code},
            )
            if existing.first():
                skipped += 1
                continue
            await db.execute(
                text(
                    """
                    INSERT INTO salary_item_definitions
                    (id, brand_id, store_id, item_name, item_code, item_category,
                     tax_attribute, calc_order, formula, formula_type, decimal_places,
                     is_active, remark)
                    VALUES
                    (:id, :brand_id, :store_id, :name, :code, :cat,
                     :tax_attr, :ord, :formula, :ftype, 2,
                     TRUE, :remark)
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "brand_id": brand_id,
                    "store_id": store_id,
                    "name": name,
                    "code": code,
                    "cat": category,
                    "tax_attr": tax_attr,
                    "ord": order,
                    "formula": formula,
                    "ftype": ftype,
                    "remark": remark,
                },
            )
            inserted += 1
        await db.commit()
        logger.info(
            "seed_salary_items_done",
            brand_id=brand_id,
            total=len(SEED_ITEMS),
            inserted=inserted,
            skipped=skipped,
        )
        print(f"[seed_salary_items] brand={brand_id} inserted={inserted} skipped={skipped}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed salary items for a brand")
    parser.add_argument("--brand-id", required=True)
    parser.add_argument("--store-id", default=None, help="可选，NULL表示品牌通用")
    args = parser.parse_args()
    asyncio.run(run(args.brand_id, args.store_id))


if __name__ == "__main__":
    main()
