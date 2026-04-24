"""2030可演进性基础设施

提供：
1. Feature Flags — 多业态功能集（大店Pro/小店Lite/宴席/外卖）
2. Multi-region — 区域联邦（华中/华东/华南等）
3. Multi-currency — 国际化预留（CNY/HKD/SGD/USD）
4. Agent Level Registry — 放权追踪（Level 0-3 自主等级）
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog

logger = structlog.get_logger()

# ─── 默认功能集 ──────────────────────────────────────────────────

# 业态功能集定义
STORE_TYPE_FEATURES: dict[str, dict[str, bool]] = {
    "大店Pro": {
        "voice_ordering": True,
        "ai_menu_recommendation": True,
        "smart_kitchen_dispatch": True,
        "vip_room_management": True,
        "banquet_module": True,
        "multi_floor_management": True,
        "chef_at_home": False,
        "delivery_module": True,
        "inventory_auto_order": True,
        "staff_scheduling_ai": True,
    },
    "小店Lite": {
        "voice_ordering": True,
        "ai_menu_recommendation": True,
        "smart_kitchen_dispatch": False,
        "vip_room_management": False,
        "banquet_module": False,
        "multi_floor_management": False,
        "chef_at_home": False,
        "delivery_module": True,
        "inventory_auto_order": False,
        "staff_scheduling_ai": False,
    },
    "宴席": {
        "voice_ordering": False,
        "ai_menu_recommendation": True,
        "smart_kitchen_dispatch": True,
        "vip_room_management": True,
        "banquet_module": True,
        "multi_floor_management": True,
        "chef_at_home": False,
        "delivery_module": False,
        "inventory_auto_order": True,
        "staff_scheduling_ai": True,
    },
    "外卖": {
        "voice_ordering": False,
        "ai_menu_recommendation": True,
        "smart_kitchen_dispatch": True,
        "vip_room_management": False,
        "banquet_module": False,
        "multi_floor_management": False,
        "chef_at_home": True,
        "delivery_module": True,
        "inventory_auto_order": True,
        "staff_scheduling_ai": False,
    },
}

# ─── 汇率表（基准: CNY分） ─────────────────────────────────────────

EXCHANGE_RATES: dict[str, float] = {
    "CNY": 1.0,
    "HKD": 1.0806,  # 1 CNY = 1.0806 HKD
    "SGD": 0.1867,  # 1 CNY = 0.1867 SGD
    "USD": 0.1389,  # 1 CNY = 0.1389 USD
    "JPY": 21.41,  # 1 CNY = 21.41 JPY
    "THB": 4.861,  # 1 CNY = 4.861 THB
    "MYR": 0.6234,  # 1 CNY = 0.6234 MYR
}

# ─── Agent自主等级定义 ──────────────────────────────────────────────

AGENT_LEVELS = {
    0: {"name": "通知", "description": "Agent仅发通知，所有操作需人工确认"},
    1: {"name": "建议", "description": "Agent给出建议+理由，人工一键确认或驳回"},
    2: {"name": "自主+事后审计", "description": "Agent自主执行，人工事后审查异常"},
    3: {"name": "全自主", "description": "Agent全自主运行，仅极端异常告警人工"},
}


class Evolution2030Service:
    """2030可演进性基础设施"""

    def __init__(self) -> None:
        # 门店功能标志存储
        self._store_features: dict[str, dict[str, bool]] = {}
        # 区域配置存储
        self._region_configs: dict[str, dict[str, Any]] = {}
        # Agent等级历史
        self._agent_level_history: dict[str, list[dict[str, Any]]] = {}
        # 当前Agent等级
        self._agent_levels: dict[str, int] = {}

    # ══════════════════════════════════════════════════════════════
    # 1. Feature Flags — 多业态功能集
    # ══════════════════════════════════════════════════════════════

    def get_feature_flags(self, store_id: str) -> dict[str, Any]:
        """获取门店功能标志。

        Args:
            store_id: 门店ID

        Returns:
            {store_id, features: {feature_name: bool}, store_type}
        """
        if store_id in self._store_features:
            features = self._store_features[store_id]
        else:
            # 默认给大店Pro功能集
            features = dict(STORE_TYPE_FEATURES.get("大店Pro", {}))
            self._store_features[store_id] = features

        # 推断业态类型
        store_type = self._infer_store_type(features)

        return {
            "store_id": store_id,
            "features": features,
            "store_type": store_type,
            "feature_count": sum(1 for v in features.values() if v),
            "total_features": len(features),
        }

    def set_feature_flag(self, store_id: str, feature: str, enabled: bool) -> dict[str, Any]:
        """设置门店功能标志。

        Args:
            store_id: 门店ID
            feature: 功能名称
            enabled: 启用/禁用

        Returns:
            {ok, store_id, feature, enabled, previous}
        """
        if store_id not in self._store_features:
            self._store_features[store_id] = dict(STORE_TYPE_FEATURES.get("大店Pro", {}))

        previous = self._store_features[store_id].get(feature)
        self._store_features[store_id][feature] = enabled

        logger.info(
            "feature_flag_set",
            store_id=store_id,
            feature=feature,
            enabled=enabled,
            previous=previous,
        )

        return {
            "ok": True,
            "store_id": store_id,
            "feature": feature,
            "enabled": enabled,
            "previous": previous,
        }

    def init_store_by_type(self, store_id: str, store_type: str) -> dict[str, Any]:
        """按业态初始化门店功能集。

        Args:
            store_id: 门店ID
            store_type: 业态类型（大店Pro/小店Lite/宴席/外卖）

        Returns:
            初始化结果
        """
        template = STORE_TYPE_FEATURES.get(store_type)
        if template is None:
            return {
                "ok": False,
                "error": f"未知业态: {store_type}，可选: {list(STORE_TYPE_FEATURES.keys())}",
            }

        self._store_features[store_id] = dict(template)

        return {
            "ok": True,
            "store_id": store_id,
            "store_type": store_type,
            "features": dict(template),
        }

    def _infer_store_type(self, features: dict[str, bool]) -> str:
        """从功能标志推断业态类型。"""
        best_match = "大店Pro"
        best_score = -1

        for stype, template in STORE_TYPE_FEATURES.items():
            score = sum(1 for k, v in template.items() if features.get(k) == v)
            if score > best_score:
                best_score = score
                best_match = stype

        return best_match

    # ══════════════════════════════════════════════════════════════
    # 2. Multi-region — 区域联邦
    # ══════════════════════════════════════════════════════════════

    def get_region_config(self, region_id: str) -> dict[str, Any]:
        """获取区域配置。

        Returns:
            区域配置信息
        """
        config = self._region_configs.get(region_id)
        if config is None:
            # 返回默认华中区域配置
            config = {
                "region_id": region_id,
                "name": region_id,
                "timezone": "Asia/Shanghai",
                "currency": "CNY",
                "language": "zh-CN",
                "tax_region": "mainland_china",
                "data_residency": "cn-changsha",
                "sync_interval_seconds": 300,
                "regulatory": {
                    "food_safety_standard": "GB_14881",
                    "receipt_format": "国标",
                    "tax_invoice_type": "增值税普通发票",
                },
            }
            self._region_configs[region_id] = config

        return config

    def set_region_policy(self, region_id: str, policy: dict[str, Any]) -> dict[str, Any]:
        """设置区域策略。

        Args:
            region_id: 区域ID
            policy: 策略字典

        Returns:
            更新结果
        """
        if region_id not in self._region_configs:
            self.get_region_config(region_id)  # 初始化默认

        config = self._region_configs[region_id]
        config.update(policy)
        config["updated_at"] = time.time()

        logger.info(
            "region_policy_set",
            region_id=region_id,
            policy_keys=list(policy.keys()),
        )

        return {
            "ok": True,
            "region_id": region_id,
            "updated_fields": list(policy.keys()),
            "config": config,
        }

    # ══════════════════════════════════════════════════════════════
    # 3. Multi-currency — 国际化预留
    # ══════════════════════════════════════════════════════════════

    def convert_currency(
        self,
        amount_fen: int,
        from_currency: str,
        to_currency: str,
    ) -> dict[str, Any]:
        """货币转换。

        Args:
            amount_fen: 金额（源币种最小单位）
            from_currency: 源币种 (CNY/HKD/SGD/USD/JPY/THB/MYR)
            to_currency: 目标币种

        Returns:
            {amount_fen, from_currency, to_currency, converted_amount, rate}
        """
        from_rate = EXCHANGE_RATES.get(from_currency)
        to_rate = EXCHANGE_RATES.get(to_currency)

        if from_rate is None:
            return {
                "ok": False,
                "error": f"不支持的币种: {from_currency}",
                "supported": list(EXCHANGE_RATES.keys()),
            }
        if to_rate is None:
            return {
                "ok": False,
                "error": f"不支持的币种: {to_currency}",
                "supported": list(EXCHANGE_RATES.keys()),
            }

        # 先转为 CNY，再转为目标币种
        cny_amount = amount_fen / from_rate
        converted = cny_amount * to_rate
        rate = to_rate / from_rate

        return {
            "ok": True,
            "amount_fen": amount_fen,
            "from_currency": from_currency,
            "to_currency": to_currency,
            "converted_amount": round(converted, 2),
            "rate": round(rate, 6),
            "rate_date": "2026-03-27",
        }

    def get_exchange_rates(self) -> dict[str, Any]:
        """获取所有汇率。

        Returns:
            {base: "CNY", rates: {...}, updated_at}
        """
        return {
            "base": "CNY",
            "rates": dict(EXCHANGE_RATES),
            "updated_at": "2026-03-27T00:00:00+08:00",
            "source": "manual",
        }

    # ══════════════════════════════════════════════════════════════
    # 4. Agent Level Registry — 放权追踪
    # ══════════════════════════════════════════════════════════════

    def get_agent_level(self, agent_id: str) -> dict[str, Any]:
        """获取Agent当前自主等级。"""
        level = self._agent_levels.get(agent_id, 0)
        level_info = AGENT_LEVELS.get(level, AGENT_LEVELS[0])

        return {
            "agent_id": agent_id,
            "level": level,
            "level_name": level_info["name"],
            "description": level_info["description"],
        }

    def set_agent_level(self, agent_id: str, level: int, reason: str = "") -> dict[str, Any]:
        """设置Agent自主等级（含历史记录）。

        Args:
            agent_id: Agent ID
            level: 目标等级 (0-3)
            reason: 变更原因

        Returns:
            {ok, agent_id, previous_level, new_level}
        """
        if level not in AGENT_LEVELS:
            return {
                "ok": False,
                "error": f"无效等级: {level}，有效范围0-3",
            }

        previous = self._agent_levels.get(agent_id, 0)
        self._agent_levels[agent_id] = level

        # 记录历史
        if agent_id not in self._agent_level_history:
            self._agent_level_history[agent_id] = []

        self._agent_level_history[agent_id].append(
            {
                "timestamp": time.time(),
                "previous_level": previous,
                "new_level": level,
                "reason": reason,
                "change_id": f"ALC-{uuid.uuid4().hex[:8].upper()}",
            }
        )

        logger.info(
            "agent_level_changed",
            agent_id=agent_id,
            previous=previous,
            new_level=level,
            reason=reason,
        )

        return {
            "ok": True,
            "agent_id": agent_id,
            "previous_level": previous,
            "new_level": level,
            "level_name": AGENT_LEVELS[level]["name"],
        }

    def get_agent_level_history(self, agent_id: str) -> list[dict[str, Any]]:
        """获取Agent等级变更历史。"""
        return list(self._agent_level_history.get(agent_id, []))

    def get_system_maturity_score(self) -> dict[str, Any]:
        """计算系统成熟度评分 — 距离Level 3全自主有多远？

        评估维度：
        - Agent平均等级
        - 功能覆盖率
        - 数据完整度
        - 自动化率

        Returns:
            {score, max_score, level, breakdown}
        """
        # Agent等级维度 (满分40)
        if self._agent_levels:
            avg_level = sum(self._agent_levels.values()) / len(self._agent_levels)
            agent_score = round(avg_level / 3 * 40, 1)
            agent_count = len(self._agent_levels)
        else:
            avg_level = 0
            agent_score = 0
            agent_count = 0

        # 功能覆盖维度 (满分20)
        total_features_enabled = 0
        total_features_possible = 0
        for store_features in self._store_features.values():
            total_features_enabled += sum(1 for v in store_features.values() if v)
            total_features_possible += len(store_features)
        # 已由外层 `total_features_possible > 0` 守护，直接除即可（无需 _safe_ratio helper）
        feature_coverage = total_features_enabled / total_features_possible if total_features_possible > 0 else 0.5
        feature_score = round(feature_coverage * 20, 1)

        # 区域覆盖维度 (满分20)
        region_count = len(self._region_configs)
        region_score = min(20.0, region_count * 5.0)

        # 国际化维度 (满分20)
        # 基于支持的币种数量
        currency_count = len(EXCHANGE_RATES)
        intl_score = min(20.0, currency_count * 3.0)

        total_score = agent_score + feature_score + region_score + intl_score
        max_score = 100.0

        # 整体等级
        if total_score >= 80:
            maturity_level = "高成熟度"
        elif total_score >= 50:
            maturity_level = "中等成熟度"
        elif total_score >= 20:
            maturity_level = "初级"
        else:
            maturity_level = "起步阶段"

        return {
            "score": round(total_score, 1),
            "max_score": max_score,
            "level": maturity_level,
            "breakdown": {
                "agent_autonomy": {
                    "score": agent_score,
                    "max": 40,
                    "avg_level": round(avg_level, 2),
                    "agent_count": agent_count,
                },
                "feature_coverage": {
                    "score": feature_score,
                    "max": 20,
                    "coverage_ratio": feature_coverage,
                },
                "regional_expansion": {
                    "score": region_score,
                    "max": 20,
                    "region_count": region_count,
                },
                "internationalization": {
                    "score": intl_score,
                    "max": 20,
                    "currency_count": currency_count,
                },
            },
        }
