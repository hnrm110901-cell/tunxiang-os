"""
屯象OS Ontology Core — 对标 Palantir Foundry Ontology 服务层

提供:
  - types: Pydantic V2 模型 (Object Types + Properties)
  - registry: Ontology 注册中心 (Object Types + Links + Actions + Functions)
  - actions: Action 框架 (带三条硬约束校验 + Agent 决策留痕)

Palantir 映射:
  Palantir Ontology → 屯象 Ontology Core
  Object Type       → Pydantic BaseModel (6大实体 DTO)
  Properties        → Model fields
  Link Types        → LinkDefinition (实体间关系)
  Actions           → OntologyAction (带约束检查的业务操作)
  Functions         → OntologyFunction (只读查询/计算)
"""
from .types import (
    # Base
    TenantEntity,
    # 6 Core Entities
    CustomerObject,
    DishObject,
    StoreObject,
    OrderObject,
    IngredientObject,
    EmployeeObject,
    # Supporting
    OrderItemObject,
    BOMEntry,
    # Enums
    RFMTier,
    LifecycleStage,
    DishQuadrant,
    OrderChannel,
    FulfillmentStatus,
    # Constraints
    HardConstraintResult,
    ConstraintType,
)
from .registry import (
    OntologyRegistry,
    ObjectTypeMeta,
    LinkDefinition,
    LinkCardinality,
    ActionTypeMeta,
    FunctionTypeMeta,
)
from .actions import (
    OntologyAction,
    ActionContext,
    ActionResult,
    AgentDecisionLog,
    # Concrete actions
    CreateOrderAction,
    ApplyDiscountAction,
    MarkSoldOutAction,
    TransferStockAction,
    CheckFoodSafetyAction,
    PredictDemandAction,
    # Registry instance
    default_registry,
)

__all__ = [
    # Types
    "TenantEntity",
    "CustomerObject",
    "DishObject",
    "StoreObject",
    "OrderObject",
    "IngredientObject",
    "EmployeeObject",
    "OrderItemObject",
    "BOMEntry",
    "RFMTier",
    "LifecycleStage",
    "DishQuadrant",
    "OrderChannel",
    "FulfillmentStatus",
    "HardConstraintResult",
    "ConstraintType",
    # Registry
    "OntologyRegistry",
    "ObjectTypeMeta",
    "LinkDefinition",
    "LinkCardinality",
    "ActionTypeMeta",
    "FunctionTypeMeta",
    # Actions
    "OntologyAction",
    "ActionContext",
    "ActionResult",
    "AgentDecisionLog",
    "CreateOrderAction",
    "ApplyDiscountAction",
    "MarkSoldOutAction",
    "TransferStockAction",
    "CheckFoodSafetyAction",
    "PredictDemandAction",
    "default_registry",
]
