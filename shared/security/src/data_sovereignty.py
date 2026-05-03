"""数据主权路由层 — 多国家/地区数据合规路由

PDPA (Malaysia Personal Data Protection Act 2010) 要求:
  - 个人数据不得跨境传输至未达到同等保护水平的国家
  - 数据主体必须同意数据跨境传输
  - 敏感个人数据（健康信息/生物特征/基因数据/犯罪记录等）禁止出境

当前为配置层实现，实际多 PG 路由需要基础设施配合改造。
"""

from __future__ import annotations

from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# ── 数据主权配置 ────────────────────────────────────────────────

# 每个国家/地区对应的 PG 实例配置
# 实际部署时需要从环境变量或配置中心读取
COUNTRY_DB_ROUTING: dict[str, dict[str, str]] = {
    "CN": {"region": "china", "pg_instance": "default", "label": "腾讯云上海"},
    "MY": {"region": "malaysia", "pg_instance": "kl", "label": "吉隆坡"},
    "SG": {"region": "singapore", "pg_instance": "sg", "label": "新加坡"},
    "HK": {"region": "hong_kong", "pg_instance": "hk", "label": "香港"},
}

# 马来西亚 PDPA：禁止出境的敏感数据类型
# PDPA 2010 第 2 部分第 4 条 — 敏感个人数据定义
RESTRICTED_DATA_TYPES_MY: frozenset[str] = frozenset([
    "health_information",
    "biometric_data",
    "genetic_data",
    "criminal_record",
    "political_opinion",
    "religious_belief",
    "financial_transaction_detail",
    "child_data",
])

# 跨境传输合规规则矩阵
# source_country → frozenset(allowed_target_countries)
# 不在列表中的目标 = 禁止传输
CROSS_BORDER_RULES: dict[str, frozenset[str]] = {
    "MY": frozenset({"CN", "SG", "HK", "MY"}),  # MY→非MY: 需数据主体同意
    "CN": frozenset({"MY", "SG", "HK", "CN"}),  # CN→其他: 一般允许
    "SG": frozenset({"MY", "CN", "HK", "SG"}),  # SG→其他: 一般允许
    "HK": frozenset({"MY", "CN", "SG", "HK"}),  # HK→其他: 一般允许
}


class DataSovereigntyRouter:
    """数据主权路由层

    职责:
      1. 根据 tenant country_code 返回对应 PG 连接配置
      2. 校验跨境数据传输是否合规（PDPA 约束）
      3. 记录不合规操作到日志（审计追踪）

    用法:
        router = DataSovereigntyRouter()
        config = router.get_pg_config("MY")
        valid, reason = router.validate_cross_border_transfer("MY", "CN", "customer_profile", has_consent=True)
    """

    # ── PG 路由 ──────────────────────────────────────────────

    @staticmethod
    def get_pg_config(country_code: str) -> dict[str, str]:
        """获取对应国家的 PG 连接配置

        Args:
            country_code: 国家/地区代码（CN/MY/SG/HK）

        Returns:
            PG 连接配置字典，包含 region/pg_instance/label
            未知国家代码默认路由到中国
        """
        config = COUNTRY_DB_ROUTING.get(country_code)
        if config is None:
            logger.warning(
                "data_sovereignty.unknown_country_code",
                country_code=country_code,
                fallback="CN",
            )
            return dict(COUNTRY_DB_ROUTING["CN"])
        return dict(config)

    @staticmethod
    def get_supported_countries() -> list[dict[str, str]]:
        """返回所有受支持的国家/地区列表"""
        return [
            {"code": code, **info}
            for code, info in COUNTRY_DB_ROUTING.items()
        ]

    # ── 跨境传输校验 ─────────────────────────────────────────

    @staticmethod
    def validate_cross_border_transfer(
        from_country: str,
        to_country: str,
        data_type: str,
        has_consent: bool = False,
    ) -> tuple[bool, Optional[str]]:
        """校验跨境数据传输是否合规

        PDPA 合规规则:
          1. 同一国家内传输 — 总是允许
          2. 马来西亚 -> 马来西亚 — 总是允许
          3. 马来西亚 -> 外国 — 需数据主体明确同意
          4. 马来西亚敏感个人数据 — 禁止出境（无论是否同意）
          5. 中国 -> 马来西亚 — 一般允许（无额外限制）
          6. 未知来源国家 — 拒绝

        Args:
            from_country: 数据来源国家/地区代码
            to_country: 数据目标国家/地区代码
            data_type: 数据类型（如 customer_profile / order / health_information）
            has_consent: 是否已获得数据主体同意

        Returns:
            (is_valid: bool, reason: Optional[str])
            - (True, None)  — 传输合规
            - (False, msg)  — 传输被拒绝，msg 为原因
        """
        # 同一国家内传输 always OK
        if from_country == to_country:
            return True, None

        # 未知来源国家
        if from_country not in CROSS_BORDER_RULES:
            reason = f"未知来源国家/地区: {from_country}，无法校验跨境传输合规性"
            logger.warning(
                "data_sovereignty.unknown_source",
                from_country=from_country,
                to_country=to_country,
                data_type=data_type,
            )
            return False, reason

        # 目标国家是否在允许列表中
        allowed = CROSS_BORDER_RULES[from_country]
        if to_country not in allowed:
            reason = f"禁止从 {from_country} 向 {to_country} 传输数据（不在跨境传输许可列表）"
            logger.warning(
                "data_sovereignty.transfer_denied",
                from_country=from_country,
                to_country=to_country,
                data_type=data_type,
                reason="country_not_in_allow_list",
            )
            return False, reason

        # 马来西亚敏感数据出境检查（PDPA 第 4 条）
        if from_country == "MY" and data_type in RESTRICTED_DATA_TYPES_MY:
            reason = (
                f"马来西亚 PDPA 禁止敏感个人数据出境: {data_type} "
                f"（Personal Data Protection Act 2010, Part 2, Section 4）"
            )
            logger.warning(
                "data_sovereignty.restricted_data_export_blocked",
                from_country=from_country,
                to_country=to_country,
                data_type=data_type,
            )
            return False, reason

        # MY → 非MY：需要数据主体同意
        if from_country == "MY":
            if not has_consent:
                reason = (
                    "马来西亚 PDPA 要求跨境传输个人数据必须获得数据主体明确同意 "
                    "（Personal Data Protection Act 2010, Section 129）"
                )
                logger.warning(
                    "data_sovereignty.consent_required",
                    from_country=from_country,
                    to_country=to_country,
                    data_type=data_type,
                )
                return False, reason

            logger.info(
                "data_sovereignty.transfer_allowed_with_consent",
                from_country=from_country,
                to_country=to_country,
                data_type=data_type,
            )
            return True, None

        # 其他情况：允许
        logger.info(
            "data_sovereignty.transfer_allowed",
            from_country=from_country,
            to_country=to_country,
            data_type=data_type,
        )
        return True, None

    @staticmethod
    def get_restricted_data_types(country_code: str = "MY") -> list[str]:
        """获取指定国家禁止出境的敏感数据类型"""
        if country_code == "MY":
            return sorted(RESTRICTED_DATA_TYPES_MY)
        return []
