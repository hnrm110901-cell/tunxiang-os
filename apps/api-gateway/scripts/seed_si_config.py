"""
D12 合规 — 社保公积金区域配置种子数据
------------------------------------------------
写入 2025 年度 长沙 / 北京 / 上海 / 深圳 四城市费率与上下限。

使用:
  python scripts/seed_si_config.py

数据说明（均按 2025 年主流缴费费率，**财务需复核后正式使用**）：
  - 基数上下限以当地社平工资×60%/300% 为准（此处采用四舍五入到分的保守估算）
  - 工伤按"一类行业基准费率"0.2%；生育在湖北/广东等已并入医疗的地区为 0%
  - 公积金默认单位 12% + 个人 12%，部分企业采用 5-7%；种子取 12% 作为上限基准
"""

import asyncio
import sys
from pathlib import Path

# 允许脚本独立运行：将项目根加入 PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from decimal import Decimal

from sqlalchemy import and_, select

from src.core.database import async_session_maker
from src.models.social_insurance import SocialInsuranceConfig


# ── 2025 年度区域配置（分；费率%）──────────────────────────────
SEED_DATA = [
    {
        "region_code": "430100",
        "region_name": "长沙市",
        "effective_year": 2025,
        "base_floor_fen": 414_200,       # 4142元 ≈ 2024湖南社平60%
        "base_ceiling_fen": 2_071_000,   # 20710元 ≈ 社平300%
        "pension_employer_pct": Decimal("16.00"),
        "pension_employee_pct": Decimal("8.00"),
        "medical_employer_pct": Decimal("8.00"),
        "medical_employee_pct": Decimal("2.00"),
        "unemployment_employer_pct": Decimal("0.70"),
        "unemployment_employee_pct": Decimal("0.30"),
        "injury_employer_pct": Decimal("0.20"),
        "maternity_employer_pct": Decimal("0.70"),
        "housing_fund_employer_pct": Decimal("12.00"),
        "housing_fund_employee_pct": Decimal("12.00"),
        "remark": "2025年长沙市 — 参考湖南人社厅公告，基数范围含公积金统一口径。",
    },
    {
        "region_code": "110000",
        "region_name": "北京市",
        "effective_year": 2025,
        "base_floor_fen": 657_500,
        "base_ceiling_fen": 3_361_300,
        "pension_employer_pct": Decimal("16.00"),
        "pension_employee_pct": Decimal("8.00"),
        "medical_employer_pct": Decimal("9.80"),
        "medical_employee_pct": Decimal("2.00"),
        "unemployment_employer_pct": Decimal("0.80"),
        "unemployment_employee_pct": Decimal("0.20"),
        "injury_employer_pct": Decimal("0.20"),
        "maternity_employer_pct": Decimal("0.80"),
        "housing_fund_employer_pct": Decimal("12.00"),
        "housing_fund_employee_pct": Decimal("12.00"),
        "remark": "2025年北京市 — 医疗含大病互助；公积金按12%上限。",
    },
    {
        "region_code": "310000",
        "region_name": "上海市",
        "effective_year": 2025,
        "base_floor_fen": 728_400,
        "base_ceiling_fen": 3_642_000,
        "pension_employer_pct": Decimal("16.00"),
        "pension_employee_pct": Decimal("8.00"),
        "medical_employer_pct": Decimal("10.00"),
        "medical_employee_pct": Decimal("2.00"),
        "unemployment_employer_pct": Decimal("0.50"),
        "unemployment_employee_pct": Decimal("0.50"),
        "injury_employer_pct": Decimal("0.20"),
        "maternity_employer_pct": Decimal("1.00"),
        "housing_fund_employer_pct": Decimal("7.00"),
        "housing_fund_employee_pct": Decimal("7.00"),
        "remark": "2025年上海市 — 公积金基础7%，补充公积金另计。",
    },
    {
        "region_code": "440300",
        "region_name": "深圳市",
        "effective_year": 2025,
        "base_floor_fen": 244_600,       # 深圳最低工资口径
        "base_ceiling_fen": 3_831_000,
        "pension_employer_pct": Decimal("14.00"),
        "pension_employee_pct": Decimal("8.00"),
        "medical_employer_pct": Decimal("5.20"),   # 深圳二档
        "medical_employee_pct": Decimal("2.00"),
        "unemployment_employer_pct": Decimal("0.70"),
        "unemployment_employee_pct": Decimal("0.30"),
        "injury_employer_pct": Decimal("0.14"),
        "maternity_employer_pct": Decimal("0.45"),
        "housing_fund_employer_pct": Decimal("5.00"),
        "housing_fund_employee_pct": Decimal("5.00"),
        "remark": "2025年深圳市 — 社保分基本/地方补充档，此处取基本档。",
    },
]


async def _upsert(session, data: dict) -> SocialInsuranceConfig:
    existing = await session.execute(
        select(SocialInsuranceConfig).where(
            and_(
                SocialInsuranceConfig.region_code == data["region_code"],
                SocialInsuranceConfig.effective_year == data["effective_year"],
            )
        )
    )
    record = existing.scalar_one_or_none()
    if record is None:
        record = SocialInsuranceConfig(**data)
        session.add(record)
    else:
        for k, v in data.items():
            setattr(record, k, v)
    return record


async def seed() -> None:
    async with async_session_maker() as session:
        for item in SEED_DATA:
            rec = await _upsert(session, item)
            print(
                f"[seed] {rec.region_name}({rec.region_code}) {rec.effective_year} "
                f"floor={rec.base_floor_fen/100:.0f}元 ceiling={rec.base_ceiling_fen/100:.0f}元"
            )
        await session.commit()
    print("✅ 社保公积金区域配置种子完成（长沙/北京/上海/深圳 2025）")


if __name__ == "__main__":
    asyncio.run(seed())
