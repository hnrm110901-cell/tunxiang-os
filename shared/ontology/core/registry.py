"""
Ontology Registry — 对标 Palantir Ontology Metadata Service (OMS)

功能:
  - 注册 Object Types + 元数据
  - 定义 Link Types (实体间关系)
  - 注册 Action Types (带约束检查)
  - 注册 Functions (业务逻辑/只读查询)
  - 查询 Ontology schema

Palantir 映射:
  Palantir OMS          → OntologyRegistry
  Object Type metadata  → ObjectTypeMeta
  Link Type             → LinkDefinition
  Action Type           → ActionTypeMeta
  Function              → FunctionTypeMeta
"""

from __future__ import annotations

import enum
from typing import Any, Callable

import structlog
from pydantic import BaseModel, Field

from .types import TenantEntity

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────
# Link Cardinality
# ─────────────────────────────────────────────


class LinkCardinality(str, enum.Enum):
    """实体间关系基数"""

    one_to_one = "one_to_one"
    one_to_many = "one_to_many"
    many_to_one = "many_to_one"
    many_to_many = "many_to_many"


# ─────────────────────────────────────────────
# Metadata Descriptors
# ─────────────────────────────────────────────


class ObjectTypeMeta(BaseModel):
    """Object Type 元数据 — 描述一个 Ontology 实体类型"""

    api_name: str = Field(..., description="程序标识, e.g. 'Customer'")
    display_name: str = Field(..., description="展示名, e.g. '顾客'")
    description: str = ""
    plural_name: str = ""
    icon: str = ""
    primary_key: str = "id"
    model_class: type[TenantEntity] | None = Field(
        default=None,
        exclude=True,
        description="对应的 Pydantic 模型类",
    )
    properties: list[str] = Field(
        default_factory=list,
        description="属性名列表 (从 model_class 自动提取)",
    )
    tags: list[str] = Field(default_factory=list)


class LinkDefinition(BaseModel):
    """Link Type 定义 — 描述两个 Object Type 之间的关系"""

    api_name: str = Field(..., description="链接标识, e.g. 'order_customer'")
    display_name: str = ""
    source_type: str = Field(..., description="源 Object Type api_name")
    target_type: str = Field(..., description="目标 Object Type api_name")
    cardinality: LinkCardinality
    foreign_key: str | None = Field(
        default=None,
        description="源实体上的外键字段",
    )
    through_type: str | None = Field(
        default=None,
        description="多对多中间表 Object Type api_name",
    )
    description: str = ""
    is_bidirectional: bool = True


class ActionTypeMeta(BaseModel):
    """Action Type 元数据 — 描述一个可执行的业务操作"""

    api_name: str = Field(..., description="操作标识, e.g. 'create_order'")
    display_name: str = ""
    description: str = ""
    target_type: str = Field(..., description="目标 Object Type api_name")
    required_constraints: list[str] = Field(
        default_factory=list,
        description="必须通过的硬约束类型",
    )
    requires_agent_log: bool = Field(
        default=False,
        description="是否需要 Agent 决策留痕",
    )
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class FunctionTypeMeta(BaseModel):
    """Function 元数据 — 描述一个只读查询/计算函数"""

    api_name: str = Field(..., description="函数标识, e.g. 'get_dish_margin'")
    display_name: str = ""
    description: str = ""
    input_types: list[str] = Field(
        default_factory=list,
        description="输入 Object Type api_names",
    )
    output_type: str | None = None
    is_aggregation: bool = False
    tags: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────
# Ontology Registry
# ─────────────────────────────────────────────


class OntologyRegistry:
    """Ontology 注册中心 — 单例管理所有 Object Types, Links, Actions, Functions

    对标 Palantir Ontology Metadata Service (OMS):
      - register_object_type: 注册实体类型
      - register_link: 注册实体间关系
      - register_action: 注册业务操作
      - register_function: 注册查询/计算函数
      - get_*: 查询已注册的元数据
      - schema: 导出完整 Ontology schema
    """

    def __init__(self) -> None:
        self._object_types: dict[str, ObjectTypeMeta] = {}
        self._links: dict[str, LinkDefinition] = {}
        self._actions: dict[str, ActionTypeMeta] = {}
        self._functions: dict[str, FunctionTypeMeta] = {}
        self._action_handlers: dict[str, Any] = {}
        self._function_handlers: dict[str, Callable[..., Any]] = {}

    # ── Object Types ──────────────────────────

    def register_object_type(
        self,
        meta: ObjectTypeMeta,
    ) -> None:
        """注册一个 Object Type"""
        if meta.model_class is not None and not meta.properties:
            meta.properties = list(meta.model_class.model_fields.keys())
        self._object_types[meta.api_name] = meta
        logger.info(
            "ontology.object_type.registered",
            api_name=meta.api_name,
            display_name=meta.display_name,
            property_count=len(meta.properties),
        )

    def get_object_type(self, api_name: str) -> ObjectTypeMeta | None:
        """查询 Object Type 元数据"""
        return self._object_types.get(api_name)

    def list_object_types(self) -> list[ObjectTypeMeta]:
        """列出所有 Object Types"""
        return list(self._object_types.values())

    # ── Links ─────────────────────────────────

    def register_link(self, link: LinkDefinition) -> None:
        """注册一个 Link Type"""
        if link.source_type not in self._object_types:
            logger.warning(
                "ontology.link.source_not_registered",
                link=link.api_name,
                source=link.source_type,
            )
        if link.target_type not in self._object_types:
            logger.warning(
                "ontology.link.target_not_registered",
                link=link.api_name,
                target=link.target_type,
            )
        self._links[link.api_name] = link
        logger.info(
            "ontology.link.registered",
            api_name=link.api_name,
            source=link.source_type,
            target=link.target_type,
            cardinality=link.cardinality.value,
        )

    def get_link(self, api_name: str) -> LinkDefinition | None:
        """查询 Link Type"""
        return self._links.get(api_name)

    def get_links_for_type(self, object_type: str) -> list[LinkDefinition]:
        """查询某个 Object Type 参与的所有 Links"""
        return [
            link
            for link in self._links.values()
            if link.source_type == object_type or link.target_type == object_type
        ]

    def list_links(self) -> list[LinkDefinition]:
        """列出所有 Link Types"""
        return list(self._links.values())

    # ── Actions ───────────────────────────────

    def register_action(
        self,
        meta: ActionTypeMeta,
        handler: Any | None = None,
    ) -> None:
        """注册一个 Action Type (可选绑定 handler)"""
        self._actions[meta.api_name] = meta
        if handler is not None:
            self._action_handlers[meta.api_name] = handler
        logger.info(
            "ontology.action.registered",
            api_name=meta.api_name,
            target=meta.target_type,
            constraints=meta.required_constraints,
            has_handler=handler is not None,
        )

    def get_action(self, api_name: str) -> ActionTypeMeta | None:
        """查询 Action Type 元数据"""
        return self._actions.get(api_name)

    def get_action_handler(self, api_name: str) -> Any | None:
        """获取 Action handler"""
        return self._action_handlers.get(api_name)

    def list_actions(self) -> list[ActionTypeMeta]:
        """列出所有 Action Types"""
        return list(self._actions.values())

    # ── Functions ─────────────────────────────

    def register_function(
        self,
        meta: FunctionTypeMeta,
        handler: Callable[..., Any] | None = None,
    ) -> None:
        """注册一个 Function"""
        self._functions[meta.api_name] = meta
        if handler is not None:
            self._function_handlers[meta.api_name] = handler
        logger.info(
            "ontology.function.registered",
            api_name=meta.api_name,
            has_handler=handler is not None,
        )

    def get_function(self, api_name: str) -> FunctionTypeMeta | None:
        """查询 Function 元数据"""
        return self._functions.get(api_name)

    def get_function_handler(self, api_name: str) -> Callable[..., Any] | None:
        """获取 Function handler"""
        return self._function_handlers.get(api_name)

    def list_functions(self) -> list[FunctionTypeMeta]:
        """列出所有 Functions"""
        return list(self._functions.values())

    # ── Schema Export ─────────────────────────

    def schema(self) -> dict[str, Any]:
        """导出完整 Ontology schema (JSON-serializable)"""
        return {
            "object_types": {
                k: v.model_dump(exclude={"model_class"})
                for k, v in self._object_types.items()
            },
            "links": {
                k: v.model_dump() for k, v in self._links.items()
            },
            "actions": {
                k: v.model_dump() for k, v in self._actions.items()
            },
            "functions": {
                k: v.model_dump() for k, v in self._functions.items()
            },
        }

    def __repr__(self) -> str:
        return (
            f"OntologyRegistry("
            f"objects={len(self._object_types)}, "
            f"links={len(self._links)}, "
            f"actions={len(self._actions)}, "
            f"functions={len(self._functions)})"
        )


# ─────────────────────────────────────────────
# Default Registry Setup
# ─────────────────────────────────────────────


def build_default_registry() -> OntologyRegistry:
    """构建屯象OS 默认 Ontology Registry

    注册 6 大核心实体 + 5 条核心 Link + Action/Function 元数据。
    """
    from .types import (
        CustomerObject,
        DishObject,
        EmployeeObject,
        IngredientObject,
        OrderObject,
        StoreObject,
    )

    registry = OntologyRegistry()

    # ── 6 大核心 Object Types ──────────────────

    registry.register_object_type(ObjectTypeMeta(
        api_name="Customer",
        display_name="顾客",
        description="CDP 统一消费者身份 — Golden ID, 全渠道画像, RFM 分层, 生命周期",
        plural_name="Customers",
        icon="user",
        model_class=CustomerObject,
        tags=["core", "cdp"],
    ))

    registry.register_object_type(ObjectTypeMeta(
        api_name="Dish",
        display_name="菜品",
        description="菜品主档 — BOM 配方, 各渠道价格, 毛利模型, 四象限分类",
        plural_name="Dishes",
        icon="utensils",
        model_class=DishObject,
        tags=["core", "menu"],
    ))

    registry.register_object_type(ObjectTypeMeta(
        api_name="Store",
        display_name="门店",
        description="门店 — 桌台拓扑, 档口配置, 人效模型, 经营指标",
        plural_name="Stores",
        icon="store",
        model_class=StoreObject,
        tags=["core", "ops"],
    ))

    registry.register_object_type(ObjectTypeMeta(
        api_name="Order",
        display_name="订单",
        description="订单 — 全渠道统一, 折扣明细, 核销记录, 出餐状态",
        plural_name="Orders",
        icon="receipt",
        model_class=OrderObject,
        tags=["core", "trade"],
    ))

    registry.register_object_type(ObjectTypeMeta(
        api_name="Ingredient",
        display_name="食材",
        description="食材 — 库存量, 效期, 采购价, 批次, 供应商",
        plural_name="Ingredients",
        icon="box",
        model_class=IngredientObject,
        tags=["core", "supply"],
    ))

    registry.register_object_type(ObjectTypeMeta(
        api_name="Employee",
        display_name="员工",
        description="员工 — 角色, 技能, 排班, 业绩提成, 效率指标",
        plural_name="Employees",
        icon="id-badge",
        model_class=EmployeeObject,
        tags=["core", "org"],
    ))

    # ── 辅助 Object Types ─────────────────────

    registry.register_object_type(ObjectTypeMeta(
        api_name="OrderItem",
        display_name="订单明细",
        description="订单行项 — 菜品、数量、价格、出餐状态",
        plural_name="OrderItems",
        icon="list",
        tags=["supporting", "trade"],
    ))

    registry.register_object_type(ObjectTypeMeta(
        api_name="BOMEntry",
        display_name="BOM配方条目",
        description="菜品配方 — 食材、用量、成本",
        plural_name="BOMEntries",
        icon="clipboard-list",
        tags=["supporting", "menu"],
    ))

    # ── 5 条核心 Link Types ───────────────────

    registry.register_link(LinkDefinition(
        api_name="order_customer",
        display_name="订单→顾客",
        source_type="Order",
        target_type="Customer",
        cardinality=LinkCardinality.many_to_one,
        foreign_key="customer_id",
        description="每笔订单关联一位顾客 (散客可为空)",
    ))

    registry.register_link(LinkDefinition(
        api_name="order_items",
        display_name="订单→菜品",
        source_type="Order",
        target_type="Dish",
        cardinality=LinkCardinality.many_to_many,
        through_type="OrderItem",
        description="订单包含多个菜品 (通过 OrderItem 中间表)",
    ))

    registry.register_link(LinkDefinition(
        api_name="store_employees",
        display_name="门店→员工",
        source_type="Store",
        target_type="Employee",
        cardinality=LinkCardinality.one_to_many,
        foreign_key="store_id",
        description="门店下属多名员工",
    ))

    registry.register_link(LinkDefinition(
        api_name="dish_ingredients",
        display_name="菜品→食材",
        source_type="Dish",
        target_type="Ingredient",
        cardinality=LinkCardinality.many_to_many,
        through_type="BOMEntry",
        description="菜品 BOM 配方关联多种食材",
    ))

    registry.register_link(LinkDefinition(
        api_name="store_orders",
        display_name="门店→订单",
        source_type="Store",
        target_type="Order",
        cardinality=LinkCardinality.one_to_many,
        foreign_key="store_id",
        description="门店产生多笔订单",
    ))

    # ── Action Types ──────────────────────────

    registry.register_action(ActionTypeMeta(
        api_name="create_order",
        display_name="开单",
        description="创建新订单",
        target_type="Order",
        required_constraints=["customer_experience"],
        tags=["trade"],
    ))

    registry.register_action(ActionTypeMeta(
        api_name="apply_discount",
        display_name="打折",
        description="为订单应用折扣 — 必须校验毛利底线",
        target_type="Order",
        required_constraints=["margin_floor"],
        requires_agent_log=True,
        tags=["trade", "agent"],
    ))

    registry.register_action(ActionTypeMeta(
        api_name="mark_sold_out",
        display_name="标记沽清",
        description="将菜品标记为沽清/恢复供应",
        target_type="Dish",
        required_constraints=[],
        tags=["menu"],
    ))

    registry.register_action(ActionTypeMeta(
        api_name="transfer_stock",
        display_name="门店调拨",
        description="门店间食材调拨",
        target_type="Ingredient",
        required_constraints=["food_safety"],
        tags=["supply"],
    ))

    registry.register_action(ActionTypeMeta(
        api_name="check_food_safety",
        display_name="食安检查",
        description="食材效期及合规检查",
        target_type="Ingredient",
        required_constraints=["food_safety"],
        requires_agent_log=True,
        tags=["supply", "agent", "compliance"],
    ))

    registry.register_action(ActionTypeMeta(
        api_name="predict_demand",
        display_name="需求预测",
        description="基于历史数据预测食材/菜品需求量",
        target_type="Ingredient",
        required_constraints=[],
        requires_agent_log=True,
        tags=["agent", "analytics"],
    ))

    # ── Functions ─────────────────────────────

    registry.register_function(FunctionTypeMeta(
        api_name="get_dish_margin",
        display_name="菜品毛利计算",
        description="计算菜品实际毛利率",
        input_types=["Dish"],
        output_type="float",
        tags=["menu", "finance"],
    ))

    registry.register_function(FunctionTypeMeta(
        api_name="get_store_revenue",
        display_name="门店营收汇总",
        description="查询门店指定时段营收",
        input_types=["Store"],
        output_type="dict",
        is_aggregation=True,
        tags=["analytics"],
    ))

    registry.register_function(FunctionTypeMeta(
        api_name="get_customer_rfm",
        display_name="顾客RFM评分",
        description="计算/查询顾客 RFM 分层",
        input_types=["Customer"],
        output_type="dict",
        tags=["cdp"],
    ))

    registry.register_function(FunctionTypeMeta(
        api_name="get_ingredient_expiry_report",
        display_name="食材效期报告",
        description="查询门店食材临期/过期清单",
        input_types=["Store", "Ingredient"],
        output_type="list",
        is_aggregation=True,
        tags=["supply", "compliance"],
    ))

    logger.info("ontology.registry.built", summary=repr(registry))
    return registry
