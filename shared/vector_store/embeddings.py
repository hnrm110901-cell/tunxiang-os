"""文本向量化服务

优先使用Claude API embedding（通过ModelRouter/httpx调用Anthropic API）。
fallback：简单的TF-IDF向量（离线/降级模式），维度固定为1536。

API KEY通过环境变量 ANTHROPIC_API_KEY 配置。
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from collections import Counter
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger()

_ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_EMBEDDING_MODEL = "voyage-3"  # Anthropic推荐的embedding模型（通过voyage）
_VECTOR_SIZE = 1536
_TIMEOUT = 10.0


class EmbeddingService:
    """文本向量化服务（无状态，方法均为async）"""

    # ── 公开API ───────────────────────────────────────────────

    @staticmethod
    async def embed_text(text: str) -> list[float]:
        """单文本向量化。

        优先调用Claude/Voyage API，失败时fallback到TF-IDF向量。
        始终返回长度为1536的float列表，不抛异常。
        """
        result = await EmbeddingService._try_api_embed([text])
        if result:
            return result[0]
        return EmbeddingService._tfidf_embed(text)

    @staticmethod
    async def embed_batch(texts: list[str]) -> list[list[float]]:
        """批量向量化。

        优先调用API批量接口，失败时逐条fallback到TF-IDF。
        始终返回与输入等长的列表，不抛异常。
        """
        if not texts:
            return []

        result = await EmbeddingService._try_api_embed(texts)
        if result and len(result) == len(texts):
            return result

        # Fallback：对每条文本单独做TF-IDF
        logger.warning("embedding_api_fallback", count=len(texts))
        return [EmbeddingService._tfidf_embed(t) for t in texts]

    # ── 内部：API调用 ────────────────────────────────────────

    @staticmethod
    async def _try_api_embed(texts: list[str]) -> Optional[list[list[float]]]:
        """尝试调用Voyage API（Anthropic托管的embedding服务）。

        成功返回向量列表，失败返回None。
        """
        if not _ANTHROPIC_API_KEY:
            logger.debug("embedding_api_key_missing_use_fallback")
            return None

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    "https://api.voyageai.com/v1/embeddings",
                    json={
                        "model": _EMBEDDING_MODEL,
                        "input": texts,
                    },
                    headers={
                        "Authorization": f"Bearer {_ANTHROPIC_API_KEY}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code != 200:
                    logger.warning(
                        "embedding_api_error",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
                    return None

                data = resp.json()
                embeddings = [item["embedding"] for item in data.get("data", [])]

                # 维度对齐：如果API返回维度与预期不同，截断或补零
                aligned = [_align_vector(e, _VECTOR_SIZE) for e in embeddings]
                return aligned if aligned else None

        except Exception as exc:
            logger.warning("embedding_api_exception", error=str(exc))
            return None

    # ── 内部：TF-IDF fallback ────────────────────────────────

    @staticmethod
    def _tfidf_embed(text: str) -> list[float]:
        """简单TF-IDF向量（离线/降级模式）。

        基于字符n-gram（中英文通用），输出固定1536维归一化向量。
        """
        tokens = _tokenize(text)
        if not tokens:
            return [0.0] * _VECTOR_SIZE

        tf = Counter(tokens)
        total = sum(tf.values())

        vec = [0.0] * _VECTOR_SIZE
        for token, count in tf.items():
            tf_score = count / total
            # 用token的hash映射到向量槽位（多个槽位避免碰撞）
            for seed in range(3):
                idx = _hash_slot(token, seed, _VECTOR_SIZE)
                vec[idx] += tf_score

        return _l2_normalize(vec)


# ── 工具函数 ─────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """简单分词：英文按空格/标点分词，中文按字符切分"""
    text = text.lower().strip()
    # 中文字符单独成token
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    # 英文单词
    english = re.findall(r"[a-z0-9]+", text)
    return chinese + english


def _hash_slot(token: str, seed: int, size: int) -> int:
    """将token哈希映射到[0, size)的槽位"""
    raw = hashlib.md5(f"{seed}:{token}".encode()).hexdigest()
    return int(raw, 16) % size


def _l2_normalize(vec: list[float]) -> list[float]:
    """L2归一化"""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm < 1e-10:
        return vec
    return [x / norm for x in vec]


def _align_vector(vec: list[float], target_size: int) -> list[float]:
    """对齐向量维度：截断或补零"""
    if len(vec) >= target_size:
        return vec[:target_size]
    return vec + [0.0] * (target_size - len(vec))
