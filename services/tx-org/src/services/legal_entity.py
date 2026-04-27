"""
法人/公司管理服务

核心能力：
- 创建法人实体（法人企业 corporation / 非法人企业 non_corporation）
- 创建公司（隶属于某法人实体）
- 门店归属公司
- 集团法人架构树
- 公司下属门店查询

治理层级：集团 → 法人实体 → 公司 → 门店
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LEGAL_ENTITY_TYPES = ("corporation", "non_corporation")

# 内存存储（纯函数实现，无 DB 依赖）
_legal_entities: Dict[str, Dict[str, Any]] = {}
_companies: Dict[str, Dict[str, Any]] = {}
_store_assignments: Dict[str, str] = {}  # store_id -> company_id


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  法人实体
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def create_legal_entity(
    name: str,
    tax_id: str,
    type: str,
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """创建法人实体。

    Args:
        name: 法人名称
        tax_id: 税号（统一社会信用代码）
        type: 法人类型，corporation（法人企业）或 non_corporation（非法人企业）
        tenant_id: 租户ID
        db: 数据库会话（预留）

    Returns:
        创建的法人实体数据

    Raises:
        ValueError: 参数校验失败
    """
    log = logger.bind(tenant_id=tenant_id, entity_name=name)
    log.info("legal_entity.create_requested")

    if not name or not name.strip():
        raise ValueError("法人名称不能为空")
    if not tax_id or not tax_id.strip():
        raise ValueError("税号不能为空")
    if type not in LEGAL_ENTITY_TYPES:
        raise ValueError(f"法人类型必须为 {LEGAL_ENTITY_TYPES} 之一，当前值: {type}")

    # 检查税号唯一性
    for entity in _legal_entities.values():
        if entity["tax_id"] == tax_id and entity["tenant_id"] == tenant_id:
            raise ValueError(f"税号 {tax_id} 已存在")

    entity_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    entity = {
        "id": entity_id,
        "name": name.strip(),
        "tax_id": tax_id.strip(),
        "type": type,
        "tenant_id": tenant_id,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }

    _legal_entities[entity_id] = entity
    log.info("legal_entity.created", entity_id=entity_id, type=type)
    return entity


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  公司
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def create_company(
    name: str,
    legal_entity_id: str,
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """创建公司（隶属于某法人实体）。

    Args:
        name: 公司名称
        legal_entity_id: 所属法人实体ID
        tenant_id: 租户ID
        db: 数据库会话（预留）

    Returns:
        创建的公司数据

    Raises:
        ValueError: 参数校验失败或法人实体不存在
    """
    log = logger.bind(tenant_id=tenant_id, company_name=name)
    log.info("company.create_requested")

    if not name or not name.strip():
        raise ValueError("公司名称不能为空")

    entity = _legal_entities.get(legal_entity_id)
    if not entity:
        raise ValueError(f"法人实体 {legal_entity_id} 不存在")
    if entity["tenant_id"] != tenant_id:
        raise ValueError("无权操作该法人实体")

    company_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    company = {
        "id": company_id,
        "name": name.strip(),
        "legal_entity_id": legal_entity_id,
        "tenant_id": tenant_id,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }

    _companies[company_id] = company
    log.info("company.created", company_id=company_id, legal_entity_id=legal_entity_id)
    return company


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  门店归属
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def assign_store_to_company(
    store_id: str,
    company_id: str,
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """将门店归属到指定公司。

    Args:
        store_id: 门店ID
        company_id: 公司ID
        tenant_id: 租户ID
        db: 数据库会话（预留）

    Returns:
        归属结果

    Raises:
        ValueError: 公司不存在或无权操作
    """
    log = logger.bind(tenant_id=tenant_id, store_id=store_id, company_id=company_id)
    log.info("store_assignment.requested")

    if not store_id or not store_id.strip():
        raise ValueError("门店ID不能为空")

    company = _companies.get(company_id)
    if not company:
        raise ValueError(f"公司 {company_id} 不存在")
    if company["tenant_id"] != tenant_id:
        raise ValueError("无权操作该公司")

    old_company_id = _store_assignments.get(store_id)
    _store_assignments[store_id] = company_id

    log.info(
        "store_assignment.completed",
        store_id=store_id,
        old_company_id=old_company_id,
        new_company_id=company_id,
    )

    return {
        "store_id": store_id,
        "company_id": company_id,
        "company_name": company["name"],
        "previous_company_id": old_company_id,
        "assigned_at": datetime.now().isoformat(),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  架构查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_entity_structure(
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """获取集团法人架构树。

    返回结构：
    {
        "tenant_id": "xxx",
        "entities": [
            {
                "id": "entity_1",
                "name": "xxx",
                "type": "corporation",
                "companies": [
                    {
                        "id": "company_1",
                        "name": "xxx",
                        "store_ids": ["s1", "s2"]
                    }
                ]
            }
        ]
    }

    Args:
        tenant_id: 租户ID
        db: 数据库会话（预留）

    Returns:
        完整的法人架构树
    """
    log = logger.bind(tenant_id=tenant_id)
    log.info("entity_structure.requested")

    # 筛选该租户的法人实体
    tenant_entities = [e for e in _legal_entities.values() if e["tenant_id"] == tenant_id]

    # 构建公司到门店的映射
    company_stores: Dict[str, List[str]] = {}
    for store_id, company_id in _store_assignments.items():
        if company_id not in company_stores:
            company_stores[company_id] = []
        company_stores[company_id].append(store_id)

    entities_tree = []
    for entity in tenant_entities:
        # 该法人实体下的公司
        entity_companies = [
            c for c in _companies.values() if c["legal_entity_id"] == entity["id"] and c["tenant_id"] == tenant_id
        ]

        companies_data = []
        for company in entity_companies:
            companies_data.append(
                {
                    "id": company["id"],
                    "name": company["name"],
                    "status": company["status"],
                    "store_ids": company_stores.get(company["id"], []),
                    "store_count": len(company_stores.get(company["id"], [])),
                }
            )

        entities_tree.append(
            {
                "id": entity["id"],
                "name": entity["name"],
                "tax_id": entity["tax_id"],
                "type": entity["type"],
                "status": entity["status"],
                "companies": companies_data,
                "company_count": len(companies_data),
            }
        )

    log.info("entity_structure.generated", entity_count=len(entities_tree))

    return {
        "tenant_id": tenant_id,
        "entities": entities_tree,
        "total_entities": len(entities_tree),
    }


def get_company_stores(
    company_id: str,
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """获取公司下属门店列表。

    Args:
        company_id: 公司ID
        tenant_id: 租户ID
        db: 数据库会话（预留）

    Returns:
        公司信息及其下属门店ID列表
    """
    log = logger.bind(tenant_id=tenant_id, company_id=company_id)
    log.info("company_stores.requested")

    company = _companies.get(company_id)
    if not company:
        raise ValueError(f"公司 {company_id} 不存在")
    if company["tenant_id"] != tenant_id:
        raise ValueError("无权查询该公司")

    store_ids = [sid for sid, cid in _store_assignments.items() if cid == company_id]

    log.info("company_stores.found", store_count=len(store_ids))

    return {
        "company_id": company_id,
        "company_name": company["name"],
        "legal_entity_id": company["legal_entity_id"],
        "store_ids": store_ids,
        "store_count": len(store_ids),
    }


def reset_storage() -> None:
    """重置内存存储（仅用于测试）。"""
    _legal_entities.clear()
    _companies.clear()
    _store_assignments.clear()
