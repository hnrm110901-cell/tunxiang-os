"""屯象OS 知识库存储引擎 V3

替代 Qdrant 的 pgvector 混合检索方案：
- PgVectorStore: pgvector 向量存储
- HybridSearchEngine: 向量 + 关键词混合检索
- RerankerService: Voyage rerank-2 精排
- DocumentProcessor: 文档解析 + 分块 + 向量化管线

Phase 2 — Agentic RAG：
- QueryRouter: 查询复杂度路由（Simple/Medium/Complex）
- CorrectiveRAG: 纠错式检索（低相关度自动重写重试）
- CitationEngine: Claude Citations 引用引擎
- KnowledgeQueryLogger: 检索质量日志

Phase 3 — LightRAG 知识图谱：
- PgGraphRepository: PostgreSQL 知识图谱 CRUD（节点/边/社区）
- GraphExtractor: LLM + 规则双模式实体/关系抽取
- GraphRetriever: 双层图谱检索（Low-level + High-level + Hybrid）
- CommunityDetector: BFS 社区发现 + LLM 摘要生成
- GraphEventHandler: 事件驱动图谱自动维护
"""

from .citation_engine import CitationEngine
from .community_detector import CommunityDetector
from .corrective_rag import CorrectiveRAG
from .document_processor import DocumentProcessor
from .graph_event_handler import GraphEventHandler
from .graph_extractor import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
    GraphExtractor,
)
from .graph_retriever import GraphRetriever
from .hybrid_search import HybridSearchEngine
from .models import AnswerWithCitations, Citation, QueryLogEntry, QueryResult
from .pg_graph_repository import PgGraphRepository
from .pg_vector_store import PgVectorStore
from .query_logger import KnowledgeQueryLogger
from .query_router import QueryComplexity, QueryRouter
from .reranker import RerankerService
from .schemas import (
    ChunkPreview,
    DocumentUploadRequest,
    IndexTextRequest,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)

__all__ = [
    # Phase 1
    "ChunkPreview",
    "DocumentProcessor",
    "DocumentUploadRequest",
    "HybridSearchEngine",
    "IndexTextRequest",
    "KnowledgeSearchRequest",
    "KnowledgeSearchResult",
    "PgVectorStore",
    "RerankerService",
    # Phase 2 — Agentic RAG
    "AnswerWithCitations",
    "Citation",
    "CitationEngine",
    "CorrectiveRAG",
    "KnowledgeQueryLogger",
    "QueryComplexity",
    "QueryLogEntry",
    "QueryResult",
    "QueryRouter",
    # Phase 3 — LightRAG Knowledge Graph
    "CommunityDetector",
    "ExtractedEntity",
    "ExtractedRelationship",
    "ExtractionResult",
    "GraphEventHandler",
    "GraphExtractor",
    "GraphRetriever",
    "PgGraphRepository",
]
