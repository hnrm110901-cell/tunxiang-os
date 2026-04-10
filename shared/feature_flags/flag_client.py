"""
屯象OS Feature Flag Client

支持多维度评估：tenant_id / brand_id / region_id / store_id / role_code / app_version / edge_node_group

在 Harness Feature Flags SDK 接入前，先用环境变量 + YAML 配置驱动。

优先级：环境变量 > YAML targeting_rules > YAML 环境默认值 > defaultValue

使用示例：
    from shared.feature_flags import is_enabled, FlagContext
    from shared.feature_flags.flag_names import GrowthFlags

    ctx = FlagContext(tenant_id="t_001", brand_id="brand_001", role_code="L3")
    if is_enabled(GrowthFlags.JOURNEY_V2, ctx):
        run_v2_logic()
"""
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class FlagContext:
    """Feature Flag 评估上下文，包含所有支持的评估维度。"""
    tenant_id: Optional[str] = None
    brand_id: Optional[str] = None
    region_id: Optional[str] = None
    store_id: Optional[str] = None
    role_code: Optional[str] = None
    app_version: Optional[str] = None
    edge_node_group: Optional[str] = None

    def get_dimension_value(self, dimension: str) -> Optional[str]:
        """按维度名称获取对应的值。"""
        return getattr(self, dimension, None)


# 支持的 targeting_rules 维度列表（与 FlagContext 字段对应）
_SUPPORTED_DIMENSIONS = {
    "tenant_id",
    "brand_id",
    "region_id",
    "store_id",
    "role_code",
    "app_version",
    "edge_node_group",
}


class FeatureFlagClient:
    """
    Feature Flag 评估客户端。

    优先级: 环境变量 > targeting_rules > YAML 环境默认值 > defaultValue

    环境变量覆盖格式：
        FEATURE_{FLAG_NAME_UPPER_WITH_UNDERSCORE}=true/false/1/0/yes/no

    示例：
        FEATURE_GROWTH_HUB_JOURNEY_V2_ENABLE=true
    """

    def __init__(
        self,
        env: Optional[str] = None,
        flags_dir: Optional[str] = None,
    ) -> None:
        self.env = env or os.getenv("TUNXIANG_ENV", "dev")
        self.flags_dir = Path(
            flags_dir or str(Path(__file__).parent.parent.parent / "flags")
        )
        # flag_name -> flag definition dict
        self._flag_cache: dict[str, dict[str, Any]] = {}
        self._load_flags()

    # ------------------------------------------------------------------
    # 内部：Flag 加载
    # ------------------------------------------------------------------

    def _load_flags(self) -> None:
        """递归扫描 flags_dir 下所有 *.yaml 文件，合并到 _flag_cache。"""
        if not self.flags_dir.exists():
            logger.warning(
                "feature_flags_dir_not_found",
                extra={"flags_dir": str(self.flags_dir)},
            )
            return

        yaml_files = list(self.flags_dir.rglob("*.yaml")) + list(
            self.flags_dir.rglob("*.yml")
        )

        loaded_count = 0
        for yaml_file in sorted(yaml_files):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                if not isinstance(data, dict):
                    continue

                flags = data.get("flags", [])
                if not isinstance(flags, list):
                    continue

                for flag_def in flags:
                    if not isinstance(flag_def, dict):
                        continue
                    name = flag_def.get("name")
                    if not name:
                        continue
                    # 同名 Flag 后加载的覆盖先加载的（支持环境覆盖文件）
                    self._flag_cache[name] = flag_def
                    loaded_count += 1

            except (OSError, yaml.YAMLError) as exc:
                logger.error(
                    "feature_flags_load_error",
                    extra={"file": str(yaml_file), "error": str(exc)},
                )

        logger.info(
            "feature_flags_loaded",
            extra={"count": loaded_count, "env": self.env},
        )

    def reload(self) -> None:
        """重新加载所有 YAML 配置（用于热更新）。"""
        self._flag_cache.clear()
        self._load_flags()

    # ------------------------------------------------------------------
    # 公开：Flag 评估
    # ------------------------------------------------------------------

    def is_enabled(
        self,
        flag_name: str,
        context: Optional[FlagContext] = None,
    ) -> bool:
        """
        评估 Flag 是否对当前 context 开启。

        Args:
            flag_name: Flag 名称，如 "growth.hub.journey_v2.enable"
            context:   评估上下文（tenant / brand / store / role 等维度）

        Returns:
            bool: Flag 是否对当前 context 开启
        """
        # 1. 环境变量最高优先级（用于紧急关停/强制开启）
        env_override = self._check_env_override(flag_name)
        if env_override is not None:
            return env_override

        # 2. 从 YAML 缓存获取 Flag 定义
        flag_def = self._flag_cache.get(flag_name)
        if flag_def is None:
            # 未定义的 Flag 默认关闭，避免意外开启未知功能
            logger.debug(
                "feature_flag_undefined",
                extra={"flag_name": flag_name},
            )
            return False

        # 3. 获取当前环境的基准值
        base_enabled = self._get_base_value(flag_def)

        # 4. 如果基准值为 False，检查 targeting_rules 是否定向开启
        if not base_enabled and context is not None:
            return self._check_targeting_rules(flag_def, context, check_enable=True)

        # 5. 如果基准值为 True，检查 targeting_rules 是否定向关闭（支持灰度回滚）
        if base_enabled and context is not None:
            # targeting_rules 为空时不做限制
            if self._has_targeting_rules(flag_def):
                return self._check_targeting_rules(flag_def, context, check_enable=True)

        return base_enabled

    def get_all_flags(self) -> dict[str, bool]:
        """获取所有 Flag 的当前值（无 context 评估）。"""
        return {name: self.is_enabled(name) for name in self._flag_cache}

    # ------------------------------------------------------------------
    # 内部：评估辅助方法
    # ------------------------------------------------------------------

    def _check_env_override(self, flag_name: str) -> Optional[bool]:
        """检查环境变量覆盖。格式：FEATURE_{FLAG_NAME_UPPER}=true/false。"""
        env_key = "FEATURE_" + flag_name.replace(".", "_").upper()
        env_val = os.getenv(env_key)
        if env_val is None:
            return None
        return env_val.lower() in ("true", "1", "yes")

    def _get_base_value(self, flag_def: dict[str, Any]) -> bool:
        """从 YAML 获取当前环境的基准值。"""
        environments = flag_def.get("environments", {})
        env_val = environments.get(self.env)

        if isinstance(env_val, bool):
            return env_val

        # 当前环境未配置，回退到 defaultValue
        return bool(flag_def.get("defaultValue", False))

    def _has_targeting_rules(self, flag_def: dict[str, Any]) -> bool:
        """检查当前环境是否存在非空 targeting_rules。"""
        targeting = flag_def.get("targeting_rules", {})
        if not isinstance(targeting, dict):
            return False
        env_rules = targeting.get(self.env, [])
        return bool(env_rules)

    def _check_targeting_rules(
        self,
        flag_def: dict[str, Any],
        context: FlagContext,
        check_enable: bool = True,
    ) -> bool:
        """
        评估 targeting_rules 是否匹配当前 context。

        当前环境的 rules 为列表，每条规则包含：
            - dimension: 维度名称（如 brand_id、store_id）
            - values:    允许值列表
            - operator:  "any"（默认）或 "all"

        各规则之间为 OR 关系（任一规则匹配即命中）。

        Args:
            flag_def:      Flag 定义
            context:       评估上下文
            check_enable:  True 表示检查是否应开启（rules 命中 → 开启）
        """
        targeting = flag_def.get("targeting_rules", {})
        if not isinstance(targeting, dict):
            return False

        env_rules: list[dict[str, Any]] = targeting.get(self.env, [])
        if not isinstance(env_rules, list) or not env_rules:
            return False

        # 任一规则匹配即返回 True（OR 语义）
        for rule in env_rules:
            if not isinstance(rule, dict):
                continue
            dimension = rule.get("dimension")
            values = rule.get("values", [])

            if dimension not in _SUPPORTED_DIMENSIONS:
                logger.warning(
                    "feature_flag_unknown_dimension",
                    extra={"dimension": dimension, "flag": flag_def.get("name")},
                )
                continue

            if not isinstance(values, list) or not values:
                # 空 values 列表：不做限制（规则未生效）
                continue

            context_val = context.get_dimension_value(dimension)
            if context_val is not None and context_val in values:
                return True

        return False


# ------------------------------------------------------------------
# 全局单例 + 便捷函数
# ------------------------------------------------------------------

_client: Optional[FeatureFlagClient] = None


def get_flag_client() -> FeatureFlagClient:
    """获取全局单例 FeatureFlagClient（懒加载）。"""
    global _client
    if _client is None:
        _client = FeatureFlagClient()
    return _client


def reset_flag_client() -> None:
    """重置全局单例（主要用于测试环境隔离）。"""
    global _client
    _client = None


def is_enabled(
    flag_name: str,
    context: Optional[FlagContext] = None,
) -> bool:
    """
    便捷函数：评估 Flag 是否开启。

    Args:
        flag_name: Flag 名称，如 "growth.hub.journey_v2.enable"
        context:   评估上下文（可选）

    Returns:
        bool: Flag 是否开启
    """
    return get_flag_client().is_enabled(flag_name, context)
