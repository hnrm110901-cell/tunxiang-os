"""预定义各业务场景的Qdrant collection配置

所有collection统一使用1536维Cosine相似度向量。
tenant隔离通过payload中的tenant_id字段过滤实现。
"""

from __future__ import annotations

# 预定义collection配置
COLLECTIONS: dict[str, dict[str, object]] = {
    "menu_knowledge": {
        "vector_size": 1536,
        "description": "菜品描述、搭配建议、营养信息",
        "payload_schema": {
            "tenant_id": "string",  # 租户隔离
            "brand_id": "string",  # 品牌
            "doc_id": "string",  # 文档唯一标识
            "category": "string",  # 菜品分类
            "updated_at": "string",  # ISO8601时间戳
        },
    },
    "ops_procedures": {
        "vector_size": 1536,
        "description": "标准作业程序、操作规范",
        "payload_schema": {
            "tenant_id": "string",
            "store_id": "string",  # 门店（可选，跨门店SOP留空）
            "doc_id": "string",
            "procedure_type": "string",  # opening/closing/safety/service等
            "updated_at": "string",
        },
    },
    "customer_insights": {
        "vector_size": 1536,
        "description": "客户反馈、偏好、行为模式",
        "payload_schema": {
            "tenant_id": "string",
            "store_id": "string",
            "doc_id": "string",
            "insight_type": "string",  # feedback/preference/behavior
            "period": "string",  # 数据周期，如 2026-03
            "updated_at": "string",
        },
    },
    "decision_history": {
        "vector_size": 1536,
        "description": "历史决策案例，用于few-shot推理",
        "payload_schema": {
            "tenant_id": "string",
            "agent_id": "string",  # 做出决策的Agent
            "doc_id": "string",
            "action": "string",  # 决策动作类型
            "outcome": "string",  # accepted/rejected/rolled_back
            "confidence": "float",  # 决策置信度
            "created_at": "string",
        },
    },
}


def get_vector_size(collection: str) -> int:
    """获取指定collection的向量维度，未知collection返回默认1536"""
    cfg = COLLECTIONS.get(collection, {})
    return int(cfg.get("vector_size", 1536))


def list_collections() -> list[str]:
    """返回所有预定义collection名称"""
    return list(COLLECTIONS.keys())
