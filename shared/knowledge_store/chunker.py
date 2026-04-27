"""语义分块器 — 将长文本按语义边界切分为固定大小的块

特点：
- 中文段落边界感知（句号+换行、换行符分段）
- tiktoken 精确 token 计数（cl100k_base，与 Claude 一致）
- 可配置块大小和重叠
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()

# tiktoken 延迟加载（允许 import 不依赖 tiktoken）
_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        try:
            import tiktoken

            _encoder = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            logger.warning("tiktoken_not_installed_fallback_to_char_count")
            _encoder = _FallbackEncoder()
    return _encoder


class _FallbackEncoder:
    """tiktoken 不可用时的降级编码器（按字符估算 token）"""

    def encode(self, text: str) -> list[int]:
        # 粗略估算：中文 1 字 ≈ 1.5 token，英文 4 字符 ≈ 1 token
        return list(range(len(text) // 2))


@dataclass
class ChunkResult:
    """分块结果"""

    text: str
    chunk_index: int
    token_count: int
    start_char: int
    end_char: int


def semantic_chunk(
    text: str,
    max_tokens: int = 512,
    overlap_tokens: int = 64,
) -> list[ChunkResult]:
    """将文本按语义边界分块。

    Args:
        text: 待分块的文本
        max_tokens: 每块最大 token 数
        overlap_tokens: 相邻块之间的重叠 token 数

    Returns:
        分块结果列表，每块包含文本、索引、token 计数和字符偏移
    """
    if not text or not text.strip():
        return []

    text = text.strip()
    encoder = _get_encoder()

    # 按段落/句子边界切分文本为片段
    segments = _split_into_segments(text)

    chunks: list[ChunkResult] = []
    current_segments: list[str] = []
    current_tokens = 0
    chunk_start_char = 0
    char_offset = 0

    for segment in segments:
        seg_tokens = len(encoder.encode(segment))

        # 单个片段超过 max_tokens：强制按字符切分
        if seg_tokens > max_tokens:
            # 先保存当前积累的块
            if current_segments:
                chunk_text = "".join(current_segments)
                chunks.append(
                    ChunkResult(
                        text=chunk_text,
                        chunk_index=len(chunks),
                        token_count=current_tokens,
                        start_char=chunk_start_char,
                        end_char=chunk_start_char + len(chunk_text),
                    )
                )
                current_segments = []
                current_tokens = 0

            # 对超长片段强制切分
            sub_chunks = _force_split(segment, max_tokens, overlap_tokens, encoder)
            for sc in sub_chunks:
                chunks.append(
                    ChunkResult(
                        text=sc,
                        chunk_index=len(chunks),
                        token_count=len(encoder.encode(sc)),
                        start_char=char_offset,
                        end_char=char_offset + len(sc),
                    )
                )
            char_offset += len(segment)
            chunk_start_char = char_offset
            continue

        # 加入当前片段后是否超限
        if current_tokens + seg_tokens > max_tokens and current_segments:
            # 保存当前块
            chunk_text = "".join(current_segments)
            chunks.append(
                ChunkResult(
                    text=chunk_text,
                    chunk_index=len(chunks),
                    token_count=current_tokens,
                    start_char=chunk_start_char,
                    end_char=chunk_start_char + len(chunk_text),
                )
            )

            # 计算重叠：从已有片段尾部取 overlap_tokens
            overlap_segments, overlap_token_count = _compute_overlap(
                current_segments,
                overlap_tokens,
                encoder,
            )
            current_segments = overlap_segments
            current_tokens = overlap_token_count
            chunk_start_char = char_offset - sum(len(s) for s in overlap_segments)

        current_segments.append(segment)
        current_tokens += seg_tokens
        char_offset += len(segment)

    # 处理最后一个块
    if current_segments:
        chunk_text = "".join(current_segments)
        if chunk_text.strip():
            chunks.append(
                ChunkResult(
                    text=chunk_text,
                    chunk_index=len(chunks),
                    token_count=current_tokens,
                    start_char=chunk_start_char,
                    end_char=chunk_start_char + len(chunk_text),
                )
            )

    return chunks


def _split_into_segments(text: str) -> list[str]:
    """按语义边界切分文本为片段。

    优先级：段落（双换行）> 句号换行 > 句号 > 分号 > 逗号
    保留分隔符在片段末尾。
    """
    # 先按段落分
    paragraphs = re.split(r"(\n\n+)", text)
    segments: list[str] = []

    for para in paragraphs:
        if not para.strip():
            segments.append(para)
            continue

        # 段落内按句号切分（中文句号、英文句号+空格、感叹号、问号）
        sentences = re.split(r"((?<=[。！？.!?])\s*)", para)
        segments.extend(s for s in sentences if s)

    return segments


def _force_split(
    text: str,
    max_tokens: int,
    overlap_tokens: int,
    encoder: object,
) -> list[str]:
    """对超长文本强制按 token 边界切分"""
    tokens = encoder.encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        # 解码 token 区间对应的文本
        chunk_tokens = tokens[start:end]
        if hasattr(encoder, "decode"):
            chunk_text = encoder.decode(chunk_tokens)
        else:
            # FallbackEncoder
            ratio = len(text) / max(len(tokens), 1)
            s = int(start * ratio)
            e = int(end * ratio)
            chunk_text = text[s:e]
        chunks.append(chunk_text)
        start = end - overlap_tokens if end < len(tokens) else end
    return chunks


def _compute_overlap(
    segments: list[str],
    overlap_tokens: int,
    encoder: object,
) -> tuple[list[str], int]:
    """从片段列表尾部取出不超过 overlap_tokens 的片段作为重叠"""
    overlap_segs: list[str] = []
    token_count = 0
    for seg in reversed(segments):
        seg_tokens = len(encoder.encode(seg))
        if token_count + seg_tokens > overlap_tokens:
            break
        overlap_segs.insert(0, seg)
        token_count += seg_tokens
    return overlap_segs, token_count
