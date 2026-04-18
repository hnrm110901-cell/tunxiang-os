"""OntologyEvent 基类 — 所有 ontology 事件 payload 的共同祖先.

演进规则 "只加不改":
  - 新增字段必须 Optional 或带默认值
  - 不删字段 (弃用字段保留 + 文档标注 deprecated)
  - 字段类型不可变更
  - 破坏性变更必须改 schema_version 主版本并启用新 topic
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class OntologyEvent(BaseModel):
    """Ontology 事件 payload 的基类.

    默认约束:
    - frozen=True  -> 实例不可变, 防止总线传输中被篡改
    - extra='forbid' -> 拒绝额外字段, 保证 schema 演进可控

    子类应通过 ClassVar schema_version 声明版本; 缺省为 '1.0'.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: ClassVar[str] = "1.0"
