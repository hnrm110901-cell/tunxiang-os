"""屯象OS Skill Registry — SKILL.yaml 九层结构的 Pydantic V2 模型"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ─────────────────────────────────────────────
# Layer 1: meta
# ─────────────────────────────────────────────


class SkillMeta(BaseModel):
    """技能元数据"""

    name: str
    version: str = "1.0.0"
    display_name: str = ""
    description: str = ""
    category: str = ""
    sub_category: str = ""
    icon: str = ""
    maintainer: str = ""


# ─────────────────────────────────────────────
# Layer 2: triggers
# ─────────────────────────────────────────────


class EventTrigger(BaseModel):
    """事件触发器"""

    type: str
    condition: str = "always"
    priority: int = 50
    description: str = ""


class ApiEndpoint(BaseModel):
    """API 端点声明"""

    method: str
    path: str
    description: str = ""


class TerminalTrigger(BaseModel):
    """终端快捷操作"""

    device: str
    action: str
    shortcut_key: str = ""
    description: str = ""


class TriggersConfig(BaseModel):
    """触发器配置汇总"""

    events: list[EventTrigger] = Field(default_factory=list)
    api: Optional[ApiConfig] = None
    terminal: list[TerminalTrigger] = Field(default_factory=list)


class ApiConfig(BaseModel):
    """API 路由配置"""

    base_path: str = ""
    endpoints: list[ApiEndpoint] = Field(default_factory=list)


# 解决前向引用
TriggersConfig.model_rebuild()


# ─────────────────────────────────────────────
# Layer 3: scope
# ─────────────────────────────────────────────


class ScopeParam(BaseModel):
    """可配置参数"""

    name: str
    type: str = "string"
    default: Any = None
    description: str = ""
    level: str = "store"
    values: list[str] = Field(default_factory=list)


class ScopeLevels(BaseModel):
    """层级列表封装（兼容 YAML 中直接用列表的形式）"""

    items: list[str] = Field(default_factory=list)


class ScopePermission(BaseModel):
    """角色权限声明"""

    role: str
    actions: list[str] = Field(default_factory=list)


class ScopeConfig(BaseModel):
    """作用域与权限配置"""

    levels: list[str] = Field(default_factory=list)
    config_inheritance: str = "override_with_merge"
    configurable_params: list[ScopeParam] = Field(default_factory=list)
    permissions: list[ScopePermission] = Field(default_factory=list)


# ─────────────────────────────────────────────
# Layer 4: data
# ─────────────────────────────────────────────


class EntityField(BaseModel):
    """实体字段定义"""

    name: str
    type: str
    required: bool = False
    ref: str = ""
    description: str = ""
    values: list[str] = Field(default_factory=list)
    precision: list[int] = Field(default_factory=list)


class OwnedEntity(BaseModel):
    """技能拥有的数据实体"""

    name: str
    table: str
    fields: list[EntityField] = Field(default_factory=list)


class ReferencedEntity(BaseModel):
    """技能引用的其他技能实体"""

    entity: str
    skill: str
    fields_used: list[str] = Field(default_factory=list)


class EmittedEvent(BaseModel):
    """技能发射的事件"""

    type: str
    payload_schema: dict[str, Any] = Field(default_factory=dict)


class DataContract(BaseModel):
    """数据契约（拥有实体 + 引用实体 + 发射事件）"""

    owned_entities: list[OwnedEntity] = Field(default_factory=list)
    referenced_entities: list[ReferencedEntity] = Field(default_factory=list)
    emitted_events: list[EmittedEvent] = Field(default_factory=list)


# ─────────────────────────────────────────────
# Layer 5: dependencies
# ─────────────────────────────────────────────


class DependencyRef(BaseModel):
    """依赖的其他技能"""

    skill: str
    min_version: str = "1.0.0"
    reason: str = ""


class DependenciesConfig(BaseModel):
    """依赖配置"""

    required: list[DependencyRef] = Field(default_factory=list)
    optional: list[DependencyRef] = Field(default_factory=list)


# ─────────────────────────────────────────────
# Layer 6: degradation
# ─────────────────────────────────────────────


class DegradationCapability(BaseModel):
    """降级能力条目"""

    action: str
    mode: Literal["full", "limited", "disabled"] = "full"
    limit: str = ""
    fallback_message: str = ""
    local_storage: str = ""
    note: str = ""


class SyncStrategy(BaseModel):
    """离线同步策略"""

    on_reconnect: str = "push_local_then_pull_remote"
    conflict_resolution: str = ""
    max_offline_hours: int = 4


class OfflineConfig(BaseModel):
    """离线运行配置"""

    can_operate: bool = False
    capabilities: list[DegradationCapability] = Field(default_factory=list)
    sync_strategy: Optional[SyncStrategy] = None


class ServiceDownFallback(BaseModel):
    """依赖服务宕机时的降级策略"""

    service: str
    fallback: str = ""
    alert: str = "none"


class ConflictConfig(BaseModel):
    """冲突解决策略"""

    strategy: str = ""
    manual_review_trigger: str = ""
    reason: str = ""


class DegradationConfig(BaseModel):
    """完整降级配置"""

    offline: Optional[OfflineConfig] = None
    service_down: list[ServiceDownFallback] = Field(default_factory=list)
    conflict: Optional[ConflictConfig] = None


# ─────────────────────────────────────────────
# Layer 7: observability
# ─────────────────────────────────────────────


class MetricConfig(BaseModel):
    """可观测性指标"""

    name: str
    type: Literal["counter", "gauge", "histogram", "summary"] = "counter"
    labels: list[str] = Field(default_factory=list)
    description: str = ""
    alert_threshold: Optional[float] = None
    alert_message: str = ""


class HealthCheckConfig(BaseModel):
    """健康检查配置"""

    endpoint: str = "/health"
    interval_seconds: int = 30
    timeout_seconds: int = 5


class AuditConfig(BaseModel):
    """审计配置"""

    log_all_mutations: bool = True
    retention_days: int = 365
    fields_to_mask: list[str] = Field(default_factory=list)


class ObservabilityConfig(BaseModel):
    """可观测性配置"""

    metrics: list[MetricConfig] = Field(default_factory=list)
    health_check: Optional[HealthCheckConfig] = None
    audit: Optional[AuditConfig] = None


# ─────────────────────────────────────────────
# Layer 8: ui
# ─────────────────────────────────────────────


class UISurface(BaseModel):
    """UI 界面声明"""

    terminal: str
    entry_point: str = ""
    component: str = ""
    layout: str = ""
    features: list[str] = Field(default_factory=list)
    behavior: dict[str, Any] = Field(default_factory=dict)


class PrintTemplate(BaseModel):
    """打印模板"""

    name: str
    format: str = ""
    template_file: str = ""


class UIConfig(BaseModel):
    """UI 配置"""

    surfaces: list[UISurface] = Field(default_factory=list)
    print_templates: list[PrintTemplate] = Field(default_factory=list)


# ─────────────────────────────────────────────
# Layer 9: compliance
# ─────────────────────────────────────────────


class GoldenTaxConfig(BaseModel):
    """金税合规配置"""

    applicable: bool = False
    tax_category: str = ""
    invoice_timing: str = ""
    note: str = ""


class RetentionPolicy(BaseModel):
    """数据保留策略"""

    financial_records: str = ""
    order_details: str = ""
    operation_logs: str = ""
    member_profiles: str = ""


class ComplianceConfig(BaseModel):
    """合规配置"""

    golden_tax: Optional[GoldenTaxConfig] = None
    data_residency: str = "cn-mainland"
    pii_fields: list[str] = Field(default_factory=list)
    retention_policy: Optional[RetentionPolicy] = None
    regulations: list[dict[str, Any]] = Field(default_factory=list)


# ─────────────────────────────────────────────
# 顶层: SkillManifest
# ─────────────────────────────────────────────


class SkillManifest(BaseModel):
    """SKILL.yaml 完整顶层结构（九层）"""

    meta: SkillMeta
    triggers: TriggersConfig = Field(default_factory=TriggersConfig)
    scope: Optional[ScopeConfig] = None
    data: Optional[DataContract] = None
    dependencies: Optional[DependenciesConfig] = None
    degradation: Optional[DegradationConfig] = None
    observability: Optional[ObservabilityConfig] = None
    ui: Optional[UIConfig] = None
    compliance: Optional[ComplianceConfig] = None
