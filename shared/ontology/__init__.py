"""shared.ontology — 屯象OS Ontology 层（实体定义 + 数据库会话工厂）

子模块：
  src.database  — async_session_factory + init_db + get_db
  src.base      — TenantBase（所有业务实体的基类）
  src.entities  — 6 大核心实体（Customer/Dish/Store/Order/Ingredient/Employee）
  src.enums     — 域共享枚举
  src.amount_convention — 金额单位约定（统一以分计）
  src.sales_channel     — 销售渠道枚举
"""
