"""屯象OS Skill Registry — 技能注册表（三级渐进加载）"""
from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Optional

import yaml

from .schemas import EventTrigger, SkillManifest

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    扫描指定目录下所有 SKILL.yaml，建立技能注册表。

    三级渐进加载（对标Claude的skill加载机制）：
      L1: meta + triggers  — 常驻内存，路由判定
      L2: 按需加载 SPEC.md — 业务规则（占位，未来扩展）
      L3: 运行时加载 handlers/ — 代码执行（占位，未来扩展）
    """

    def __init__(self, skills_root_dirs: list[str]) -> None:
        """
        Args:
            skills_root_dirs: 一组根目录路径，每个微服务目录下都可以有 skills/ 子目录。
        """
        self._root_dirs = [Path(d) for d in skills_root_dirs]
        # L1 缓存：skill_name -> SkillManifest（仅 meta + triggers）
        self._manifests: dict[str, SkillManifest] = {}
        # 完整 manifest 缓存（含 data/dependencies 等）
        self._full_manifests: dict[str, SkillManifest] = {}

    # ─────────────────────────────────────────
    # 公开接口
    # ─────────────────────────────────────────

    def scan(self) -> dict[str, SkillManifest]:
        """
        递归扫描所有目录下的 SKILL.yaml，缓存 meta + triggers（L1）。

        Returns:
            {skill_name: SkillManifest} 字典（包含完整字段）
        """
        self._manifests.clear()
        self._full_manifests.clear()

        for root_dir in self._root_dirs:
            if not root_dir.exists():
                logger.warning("skill_root_dir_not_found: %s", root_dir)
                continue
            for yaml_path in root_dir.rglob("SKILL.yaml"):
                self._load_skill_yaml(yaml_path)

        logger.info("skill_registry_scanned: %d skills loaded", len(self._manifests))
        return dict(self._manifests)

    def get(self, skill_name: str) -> Optional[SkillManifest]:
        """按名称获取 SkillManifest（L1 + 完整字段）"""
        return self._full_manifests.get(skill_name)

    def list_skills(self) -> list[SkillManifest]:
        """返回所有已注册 SkillManifest 列表"""
        return list(self._full_manifests.values())

    def find_by_event_type(
        self, event_type: str
    ) -> list[tuple[SkillManifest, EventTrigger]]:
        """
        找到所有声明订阅该事件类型的 Skill。

        支持通配符：如 "order.*" 匹配 "order.paid"。
        先用精确匹配，再用技能声明的通配符 trigger 类型匹配。

        Args:
            event_type: 具体事件类型，如 "order.paid"

        Returns:
            [(SkillManifest, EventTrigger), ...] 按 priority 降序排列
        """
        results: list[tuple[SkillManifest, EventTrigger]] = []

        for manifest in self._full_manifests.values():
            for trigger in manifest.triggers.events:
                # 技能声明的 trigger.type 可能含通配符（如 "cron.*"）
                if self._match_event_type(pattern=trigger.type, event_type=event_type):
                    results.append((manifest, trigger))

        # 按 priority 降序
        results.sort(key=lambda x: x[1].priority, reverse=True)
        return results

    def find_by_category(self, category: str) -> list[SkillManifest]:
        """按 category 过滤技能列表"""
        return [
            m for m in self._full_manifests.values()
            if m.meta.category == category
        ]

    def get_all_owned_entities(self) -> dict[str, str]:
        """
        返回 {entity_name: skill_name} 映射，用于 Ontology 冲突检测。
        如果同一实体被多个技能声明拥有，后加载的会覆盖（冲突由 OntologyRegistry 检测）。
        """
        result: dict[str, str] = {}
        for manifest in self._full_manifests.values():
            if manifest.data is None:
                continue
            for entity in manifest.data.owned_entities:
                result[entity.name] = manifest.meta.name
        return result

    def get_emitted_events(self) -> dict[str, str]:
        """
        返回 {event_type: skill_name} 映射。
        如果同一事件被多个技能发射，后加载的会覆盖。
        """
        result: dict[str, str] = {}
        for manifest in self._full_manifests.values():
            if manifest.data is None:
                continue
            for event in manifest.data.emitted_events:
                result[event.type] = manifest.meta.name
        return result

    # ─────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────

    def _load_skill_yaml(self, yaml_path: Path) -> None:
        """加载单个 SKILL.yaml 文件并缓存。"""
        try:
            with yaml_path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            if not isinstance(raw, dict):
                logger.warning("skill_yaml_invalid_format: %s", yaml_path)
                return

            manifest = SkillManifest.model_validate(raw)
            skill_name = manifest.meta.name

            if skill_name in self._full_manifests:
                logger.warning(
                    "skill_name_conflict: %s already registered, overwriting with %s",
                    skill_name,
                    yaml_path,
                )

            self._full_manifests[skill_name] = manifest
            # L1 缓存（仅 meta + triggers，逻辑上相同对象，后续可做精简）
            self._manifests[skill_name] = manifest
            logger.debug("skill_loaded: %s v%s from %s", skill_name, manifest.meta.version, yaml_path)

        except yaml.YAMLError as exc:
            logger.error("skill_yaml_parse_error: %s — %s", yaml_path, exc)
        except ValueError as exc:
            logger.error("skill_manifest_validation_error: %s — %s", yaml_path, exc)

    @staticmethod
    def _match_event_type(pattern: str, event_type: str) -> bool:
        """
        判断 event_type 是否匹配 trigger 的 pattern。

        支持两种方向的通配符：
        - trigger.type 含通配符（如 "cron.*"）→ 用于匹配传入的具体事件
        - 传入的 event_type 含通配符（如 "order.*"）→ 用于批量查找（未来扩展）

        使用 fnmatch 实现 glob 风格匹配（* 匹配任意字符，不含 /）。
        """
        if pattern == event_type:
            return True
        # 技能声明的 pattern 含通配符，匹配传入的具体 event_type
        if fnmatch.fnmatch(event_type, pattern):
            return True
        # 传入的 event_type 含通配符，匹配技能声明的 pattern
        if fnmatch.fnmatch(pattern, event_type):
            return True
        return False
