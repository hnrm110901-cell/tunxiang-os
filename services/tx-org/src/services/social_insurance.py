"""五险一金计算器

支持各城市费率配置，2026年标准。
费率可通过城市配置字典覆盖，满足不同城市差异化需求。
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


# ── 默认费率（2026年标准） ──────────────────────────────────────────────────
# 可通过城市配置或环境变量覆盖

_DEFAULT_RATES: Dict[str, Dict[str, float]] = {
    # 养老保险
    "pension_personal": float(os.getenv("SI_PENSION_PERSONAL", "0.08")),
    "pension_company": float(os.getenv("SI_PENSION_COMPANY", "0.16")),
    # 医疗保险
    "medical_personal": float(os.getenv("SI_MEDICAL_PERSONAL", "0.02")),
    "medical_company": float(os.getenv("SI_MEDICAL_COMPANY", "0.08")),
    # 失业保险
    "unemployment_personal": float(os.getenv("SI_UNEMPLOYMENT_PERSONAL", "0.005")),
    "unemployment_company": float(os.getenv("SI_UNEMPLOYMENT_COMPANY", "0.005")),
    # 工伤保险（餐饮业，仅公司承担）
    "work_injury_personal": 0.0,
    "work_injury_company": float(os.getenv("SI_WORK_INJURY_COMPANY", "0.005")),
    # 生育保险（仅公司承担）
    "maternity_personal": 0.0,
    "maternity_company": float(os.getenv("SI_MATERNITY_COMPANY", "0.007")),
    # 住房公积金
    "housing_fund_personal": float(os.getenv("SI_HOUSING_FUND_PERSONAL", "0.12")),
    "housing_fund_company": float(os.getenv("SI_HOUSING_FUND_COMPANY", "0.12")),
}

# 城市预设配置（各城市费率差异）
CITY_RATES: Dict[str, Dict[str, float]] = {
    "changsha": {
        "pension_personal": 0.08,
        "pension_company": 0.16,
        "medical_personal": 0.02,
        "medical_company": 0.08,
        "unemployment_personal": 0.003,
        "unemployment_company": 0.007,
        "work_injury_personal": 0.0,
        "work_injury_company": 0.005,
        "maternity_personal": 0.0,
        "maternity_company": 0.007,
        "housing_fund_personal": 0.08,
        "housing_fund_company": 0.08,
        # 社保基数下限/上限（分）
        "si_base_floor_fen": 374_700,
        "si_base_ceiling_fen": 2_124_300,
        "hf_base_floor_fen": 197_000,
        "hf_base_ceiling_fen": 2_890_800,
    },
    "beijing": {
        "pension_personal": 0.08,
        "pension_company": 0.16,
        "medical_personal": 0.02,
        "medical_company": 0.10,
        "unemployment_personal": 0.005,
        "unemployment_company": 0.005,
        "work_injury_personal": 0.0,
        "work_injury_company": 0.004,
        "maternity_personal": 0.0,
        "maternity_company": 0.008,
        "housing_fund_personal": 0.12,
        "housing_fund_company": 0.12,
        "si_base_floor_fen": 592_200,
        "si_base_ceiling_fen": 3_397_200,
        "hf_base_floor_fen": 233_300,
        "hf_base_ceiling_fen": 3_397_200,
    },
    "shanghai": {
        "pension_personal": 0.08,
        "pension_company": 0.16,
        "medical_personal": 0.02,
        "medical_company": 0.10,
        "unemployment_personal": 0.005,
        "unemployment_company": 0.005,
        "work_injury_personal": 0.0,
        "work_injury_company": 0.004,
        "maternity_personal": 0.0,
        "maternity_company": 0.008,
        "housing_fund_personal": 0.07,
        "housing_fund_company": 0.07,
        "si_base_floor_fen": 624_000,
        "si_base_ceiling_fen": 3_690_000,
        "hf_base_floor_fen": 240_000,
        "hf_base_ceiling_fen": 3_690_000,
    },
}


class SocialInsuranceCalculator:
    """五险一金计算器

    支持多城市费率配置，城市配置覆盖默认比例。
    住房公积金缴存比例可按员工级别独立配置（5%~12%）。
    """

    # 默认费率（环境变量可覆盖）
    DEFAULT_RATES = _DEFAULT_RATES

    def __init__(self, city: str = "changsha") -> None:
        self.city = city
        self._city_config = CITY_RATES.get(city, {})

    def _get_rate(self, key: str) -> float:
        """获取费率：城市配置 > 环境变量默认值"""
        return self._city_config.get(key, self.DEFAULT_RATES.get(key, 0.0))

    def _clamp_base(self, base_fen: int, floor_key: str, ceiling_key: str) -> int:
        """将缴费基数限制在上下限内"""
        floor_fen = int(self._city_config.get(floor_key, 0))
        ceiling_fen = int(self._city_config.get(ceiling_key, base_fen))
        if ceiling_fen <= 0:
            ceiling_fen = base_fen
        return max(floor_fen, min(base_fen, ceiling_fen))

    def calculate(
        self,
        gross_salary_fen: int,
        city_config: Optional[Dict[str, Any]] = None,
        housing_fund_rate_override: Optional[float] = None,
    ) -> Dict[str, Any]:
        """计算五险一金

        Args:
            gross_salary_fen: 应发工资（分），作为社保缴费基数
            city_config: 额外城市配置，覆盖默认值（用于特殊费率场景）
            housing_fund_rate_override: 公积金比例覆盖（如员工选5%，公司仍8%）

        Returns:
            {
                personal_total: 个人合计（分）,
                company_total: 公司合计（分）,
                breakdown: {
                    pension: {personal_fen, company_fen, personal_rate, company_rate},
                    medical: {...},
                    unemployment: {...},
                    work_injury: {...},
                    maternity: {...},
                    housing_fund: {personal_fen, company_fen, rate},
                },
                si_base_fen: 社保缴费基数（分）,
                hf_base_fen: 公积金缴费基数（分）,
            }
        """
        # 合并城市配置覆盖
        if city_config:
            merged_config = {**self._city_config, **city_config}
        else:
            merged_config = self._city_config

        # 计算缴费基数（限上下限）
        si_base_fen = self._apply_clamp(
            gross_salary_fen,
            int(merged_config.get("si_base_floor_fen", 0)),
            int(merged_config.get("si_base_ceiling_fen", gross_salary_fen)) or gross_salary_fen,
        )
        hf_base_fen = self._apply_clamp(
            gross_salary_fen,
            int(merged_config.get("hf_base_floor_fen", 0)),
            int(merged_config.get("hf_base_ceiling_fen", gross_salary_fen)) or gross_salary_fen,
        )

        def _rate(key: str) -> float:
            return merged_config.get(key, self.DEFAULT_RATES.get(key, 0.0))

        # 住房公积金比例
        hf_personal_rate = housing_fund_rate_override or _rate("housing_fund_personal")
        hf_company_rate = _rate("housing_fund_company")
        # 限制在合法范围
        hf_personal_rate = max(0.05, min(hf_personal_rate, 0.12))
        hf_company_rate = max(0.05, min(hf_company_rate, 0.12))

        # 各险种计算
        pension_personal = int(si_base_fen * _rate("pension_personal"))
        pension_company = int(si_base_fen * _rate("pension_company"))

        medical_personal = int(si_base_fen * _rate("medical_personal"))
        medical_company = int(si_base_fen * _rate("medical_company"))

        unemployment_personal = int(si_base_fen * _rate("unemployment_personal"))
        unemployment_company = int(si_base_fen * _rate("unemployment_company"))

        work_injury_personal = 0  # 工伤保险个人不缴
        work_injury_company = int(si_base_fen * _rate("work_injury_company"))

        maternity_personal = 0  # 生育保险个人不缴
        maternity_company = int(si_base_fen * _rate("maternity_company"))

        housing_fund_personal = int(hf_base_fen * hf_personal_rate)
        housing_fund_company = int(hf_base_fen * hf_company_rate)

        personal_total = (
            pension_personal
            + medical_personal
            + unemployment_personal
            + work_injury_personal
            + maternity_personal
            + housing_fund_personal
        )
        company_total = (
            pension_company
            + medical_company
            + unemployment_company
            + work_injury_company
            + maternity_company
            + housing_fund_company
        )

        return {
            "personal_total": personal_total,
            "company_total": company_total,
            "si_base_fen": si_base_fen,
            "hf_base_fen": hf_base_fen,
            "breakdown": {
                "pension": {
                    "personal_fen": pension_personal,
                    "company_fen": pension_company,
                    "personal_rate": _rate("pension_personal"),
                    "company_rate": _rate("pension_company"),
                },
                "medical": {
                    "personal_fen": medical_personal,
                    "company_fen": medical_company,
                    "personal_rate": _rate("medical_personal"),
                    "company_rate": _rate("medical_company"),
                },
                "unemployment": {
                    "personal_fen": unemployment_personal,
                    "company_fen": unemployment_company,
                    "personal_rate": _rate("unemployment_personal"),
                    "company_rate": _rate("unemployment_company"),
                },
                "work_injury": {
                    "personal_fen": work_injury_personal,
                    "company_fen": work_injury_company,
                    "personal_rate": 0.0,
                    "company_rate": _rate("work_injury_company"),
                },
                "maternity": {
                    "personal_fen": maternity_personal,
                    "company_fen": maternity_company,
                    "personal_rate": 0.0,
                    "company_rate": _rate("maternity_company"),
                },
                "housing_fund": {
                    "personal_fen": housing_fund_personal,
                    "company_fen": housing_fund_company,
                    "personal_rate": hf_personal_rate,
                    "company_rate": hf_company_rate,
                },
            },
        }

    @staticmethod
    def _apply_clamp(value: int, floor: int, ceiling: int) -> int:
        return max(floor, min(value, ceiling))
