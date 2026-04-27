"""屯象OS Ontology Registry — 实体所有权注册表"""

from __future__ import annotations

import logging
from typing import Optional

from .registry import SkillRegistry

logger = logging.getLogger(__name__)


class OntologyRegistry:
    """
    实体所有权注册表。
    确保每张表有且仅有一个 Skill 声明拥有它。
    同时跟踪事件发射权归属。
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry
        self._entity_owner: dict[str, str] = {}  # {entity_name: skill_name}
        self._event_emitter: dict[str, str] = {}  # {event_type: skill_name}
        self._conflicts: list[str] = []
        self._warnings: list[str] = []
        self._build()

    # ─────────────────────────────────────────
    # 公开接口
    # ─────────────────────────────────────────

    def get_entity_owner(self, entity_name: str) -> Optional[str]:
        """返回实体的所属 skill 名称，未注册则返回 None。"""
        return self._entity_owner.get(entity_name)

    def get_event_emitter(self, event_type: str) -> Optional[str]:
        """返回事件的发射 skill 名称，未注册则返回 None。"""
        return self._event_emitter.get(event_type)

    def validate(self) -> list[str]:
        """
        返回所有冲突和警告信息列表。
        空列表表示 Ontology 一致。
        """
        return list(self._conflicts + self._warnings)

    def generate_report(self) -> str:
        """生成类似 ontology-report.md 格式的文字报告。"""
        manifests = self.registry.list_skills()
        lines: list[str] = []

        lines.append("# 屯象OS Ontology 报告")
        lines.append(f"\n共注册 **{len(manifests)}** 个 Skill\n")

        # 实体所有权
        lines.append("## 实体所有权")
        lines.append("")
        lines.append("| 实体名 | 所属 Skill | 数据表 |")
        lines.append("|--------|-----------|--------|")
        for manifest in manifests:
            if manifest.data is None:
                continue
            for entity in manifest.data.owned_entities:
                lines.append(f"| {entity.name} | {manifest.meta.name} | {entity.table} |")
        lines.append("")

        # 事件发射
        lines.append("## 事件发射权归属")
        lines.append("")
        lines.append("| 事件类型 | 发射 Skill |")
        lines.append("|---------|-----------|")
        for event_type, skill_name in sorted(self._event_emitter.items()):
            lines.append(f"| {event_type} | {skill_name} |")
        lines.append("")

        # 依赖图
        lines.append("## 依赖关系")
        lines.append("")
        for manifest in manifests:
            if manifest.dependencies is None:
                continue
            required = manifest.dependencies.required
            optional = manifest.dependencies.optional
            if required or optional:
                lines.append(f"### {manifest.meta.name}")
                for dep in required:
                    lines.append(f"  - [强依赖] {dep.skill} >= {dep.min_version} — {dep.reason}")
                for dep in optional:
                    lines.append(f"  - [弱依赖] {dep.skill} >= {dep.min_version} — {dep.reason}")
                lines.append("")

        # 冲突与警告
        issues = self.validate()
        if issues:
            lines.append("## 冲突与警告")
            lines.append("")
            for issue in issues:
                lines.append(f"- {issue}")
            lines.append("")
        else:
            lines.append("## 验证结果")
            lines.append("")
            lines.append("✅ 无冲突，Ontology 一致。")
            lines.append("")

        return "\n".join(lines)

    # ─────────────────────────────────────────
    # 内部构建
    # ─────────────────────────────────────────

    def _build(self) -> None:
        """从所有 Skill 的 data.owned_entities / emitted_events 构建映射并检测冲突。"""
        self._entity_owner.clear()
        self._event_emitter.clear()
        self._conflicts.clear()
        self._warnings.clear()

        for manifest in self.registry.list_skills():
            skill_name = manifest.meta.name

            if manifest.data is None:
                continue

            # 实体所有权
            for entity in manifest.data.owned_entities:
                existing_owner = self._entity_owner.get(entity.name)
                if existing_owner is not None and existing_owner != skill_name:
                    conflict_msg = (
                        f"[CONFLICT] 实体 '{entity.name}' 被多个 Skill 声明拥有: '{existing_owner}' vs '{skill_name}'"
                    )
                    self._conflicts.append(conflict_msg)
                    logger.error(conflict_msg)
                else:
                    self._entity_owner[entity.name] = skill_name

            # 事件发射权（多个 skill 发射同类事件视为警告，不是冲突）
            for event in manifest.data.emitted_events:
                existing_emitter = self._event_emitter.get(event.type)
                if existing_emitter is not None and existing_emitter != skill_name:
                    warn_msg = (
                        f"[WARNING] 事件 '{event.type}' 被多个 Skill 发射: '{existing_emitter}' vs '{skill_name}'"
                    )
                    self._warnings.append(warn_msg)
                    logger.warning(warn_msg)
                else:
                    self._event_emitter[event.type] = skill_name

        logger.info(
            "ontology_built: %d entities, %d event_types, %d conflicts, %d warnings",
            len(self._entity_owner),
            len(self._event_emitter),
            len(self._conflicts),
            len(self._warnings),
        )
