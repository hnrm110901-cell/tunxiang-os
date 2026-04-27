"""shared/vector_store — Qdrant向量库集成模块

提供供各Agent使用的向量存储与检索能力：
- QdrantClient: 向量CRUD、健康检查
- EmbeddingService: 文本向量化（Claude API + TF-IDF fallback）
- KnowledgeRetrievalService: 租户隔离的知识检索
- COLLECTIONS: 预定义业务collection配置
"""

from shared.vector_store.client import QdrantClient
from shared.vector_store.embeddings import EmbeddingService
from shared.vector_store.indexes import COLLECTIONS

__all__ = ["QdrantClient", "EmbeddingService", "COLLECTIONS"]
