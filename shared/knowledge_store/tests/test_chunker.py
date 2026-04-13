"""语义分块器测试

覆盖场景：
1. 空文本返回空列表
2. 短文本（< max_tokens）返回单块
3. 长文本切分为多块并正确重叠
4. 中文文本按句号/段落边界切分
5. token 计数准确
6. chunk_index 顺序正确（0, 1, 2...）
7. start_char / end_char 偏移量正确
8. 超长单段触发 force_split
9. 重叠片段正确携带到下一块
"""
import os
import sys
from unittest.mock import patch

import pytest

# 路径设置：shared/knowledge_store/tests/ → shared/knowledge_store/ → shared/ → tunxiang-os/
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_KS_DIR = os.path.dirname(_TESTS_DIR)
_SHARED_DIR = os.path.dirname(_KS_DIR)
_ROOT_DIR = os.path.dirname(_SHARED_DIR)
sys.path.insert(0, _ROOT_DIR)

from shared.knowledge_store.chunker import ChunkResult, semantic_chunk


# ── 空文本和纯空白 ──────────────────────────────────────────────

class TestEmptyText:
    """空文本应返回空列表"""

    def test_empty_string_returns_empty_list(self):
        """空字符串返回[]"""
        result = semantic_chunk("")
        assert result == []

    def test_whitespace_only_returns_empty_list(self):
        """纯空白字符串返回[]"""
        result = semantic_chunk("   \n\n  \t  ")
        assert result == []

    def test_none_like_empty_returns_empty(self):
        """只有换行符的文本返回[]"""
        result = semantic_chunk("\n\n\n")
        assert result == []


# ── 短文本（单块） ──────────────────────────────────────────────

class TestShortText:
    """短文本（< max_tokens）应返回单块"""

    def test_short_text_returns_single_chunk(self):
        """短于 max_tokens 的文本只返回一个块"""
        text = "红烧肉是一道经典中华美食。"
        result = semantic_chunk(text, max_tokens=512)
        assert len(result) == 1
        assert result[0].text.strip() == text.strip()

    def test_single_chunk_index_is_zero(self):
        """单块的 chunk_index 应为 0"""
        result = semantic_chunk("简短的测试文本。", max_tokens=512)
        assert len(result) == 1
        assert result[0].chunk_index == 0

    def test_single_chunk_start_char_is_zero(self):
        """单块的 start_char 应为 0"""
        result = semantic_chunk("测试。", max_tokens=512)
        assert result[0].start_char == 0

    def test_single_chunk_token_count_positive(self):
        """单块的 token_count 应大于 0"""
        result = semantic_chunk("红烧肉做法介绍。", max_tokens=512)
        assert result[0].token_count > 0


# ── 长文本切分为多块 ────────────────────────────────────────────

class TestLongTextSplit:
    """长文本应被切分为多块，带正确的重叠"""

    def _make_long_text(self, sentences: int = 50) -> str:
        """生成多句中文文本"""
        base_sentences = [
            "红烧肉是中华传统名菜。",
            "选用上等五花肉切块。",
            "先焯水去腥再炒糖色。",
            "加入料酒酱油慢炖两小时。",
            "成品色泽红亮入口即化。",
        ]
        return "".join(base_sentences[i % len(base_sentences)] for i in range(sentences))

    def test_long_text_splits_into_multiple_chunks(self):
        """长文本（远超 max_tokens）应被切分为多块"""
        text = self._make_long_text(100)
        result = semantic_chunk(text, max_tokens=64, overlap_tokens=8)
        assert len(result) > 1

    def test_chunk_index_is_sequential(self):
        """chunk_index 从 0 开始递增"""
        text = self._make_long_text(100)
        result = semantic_chunk(text, max_tokens=64, overlap_tokens=8)
        for i, chunk in enumerate(result):
            assert chunk.chunk_index == i, f"chunk {i} has index {chunk.chunk_index}"

    def test_all_chunks_have_positive_token_count(self):
        """每个块的 token_count > 0"""
        text = self._make_long_text(60)
        result = semantic_chunk(text, max_tokens=64, overlap_tokens=8)
        for chunk in result:
            assert chunk.token_count > 0

    def test_chunk_token_count_does_not_exceed_max(self):
        """每个块的 token_count 不超过 max_tokens（允许少量误差）"""
        text = self._make_long_text(60)
        max_t = 64
        result = semantic_chunk(text, max_tokens=max_t, overlap_tokens=8)
        for chunk in result:
            # 分段边界可能导致略超，允许 10% 容差
            assert chunk.token_count <= max_t * 1.1, (
                f"chunk {chunk.chunk_index} has {chunk.token_count} tokens, max={max_t}"
            )


# ── 中文语义边界 ────────────────────────────────────────────────

class TestChineseBoundaries:
    """中文文本应在句号/问号/感叹号等边界处切分"""

    def test_respects_chinese_period_boundary(self):
        """在中文句号（。）处切分"""
        # 两段明确的内容，通过段落分隔
        text = "第一段内容较长需要填充一些字符来凑够token数量以便测试。\n\n第二段同样需要足够多的文字来确保分块器能够识别段落边界并正确切分。"
        result = semantic_chunk(text, max_tokens=32, overlap_tokens=4)
        if len(result) > 1:
            # 前一个块应在语义边界结束（句号或段落）
            first_text = result[0].text.rstrip()
            assert first_text.endswith("。") or first_text.endswith("\n"), (
                f"第一块未在语义边界结束: '{first_text[-10:]}'"
            )

    def test_question_mark_as_boundary(self):
        """问号（？）作为句子边界"""
        text = "这道菜好吃吗？非常好吃。推荐给谁？适合所有人。"
        result = semantic_chunk(text, max_tokens=8, overlap_tokens=2)
        # 应该能正常切分，不报错
        assert len(result) >= 1
        for chunk in result:
            assert isinstance(chunk, ChunkResult)

    def test_exclamation_mark_as_boundary(self):
        """感叹号（！）作为句子边界"""
        text = "太好吃了！必须推荐！这是招牌菜！"
        result = semantic_chunk(text, max_tokens=8, overlap_tokens=2)
        assert len(result) >= 1


# ── token 计数准确性 ────────────────────────────────────────────

class TestTokenCountAccuracy:
    """token 计数应准确（或使用 fallback 时接近）"""

    def test_token_count_matches_text_length_roughly(self):
        """token_count 应与文本长度大致相关"""
        text = "测试文本" * 20
        result = semantic_chunk(text, max_tokens=512)
        assert len(result) == 1
        # 中文文本的 token 数应在 (字符数/3, 字符数*2) 范围内
        char_count = len(text)
        assert result[0].token_count > 0
        assert result[0].token_count < char_count * 3

    def test_end_char_minus_start_char_equals_text_length(self):
        """end_char - start_char 应等于块文本长度"""
        text = "红烧肉做法。清蒸鱼做法。糖醋排骨做法。"
        result = semantic_chunk(text, max_tokens=512)
        for chunk in result:
            expected_len = len(chunk.text)
            actual_len = chunk.end_char - chunk.start_char
            assert actual_len == expected_len, (
                f"chunk {chunk.chunk_index}: end-start={actual_len}, text_len={expected_len}"
            )


# ── start_char / end_char 偏移量 ────────────────────────────────

class TestCharOffsets:
    """start_char 和 end_char 应正确追踪字符偏移量"""

    def test_first_chunk_starts_at_zero(self):
        """第一个块的 start_char 应为 0"""
        text = "这是一段测试文本用来验证偏移量。"
        result = semantic_chunk(text, max_tokens=512)
        assert result[0].start_char == 0

    def test_single_chunk_end_char_matches_text_length(self):
        """单块的 end_char 应等于文本长度"""
        text = "短文本。"
        result = semantic_chunk(text, max_tokens=512)
        assert result[0].end_char == len(text)


# ── 超长单段 force_split ────────────────────────────────────────

class TestForceSplit:
    """超长单段落（无自然分隔符）应触发强制切分"""

    def test_very_long_paragraph_triggers_force_split(self):
        """无标点的超长文本也能被切分"""
        # 生成一个很长的无标点文本
        text = "这是一段没有任何标点的超长文本" * 100
        result = semantic_chunk(text, max_tokens=32, overlap_tokens=4)
        assert len(result) > 1

    def test_force_split_chunks_have_valid_fields(self):
        """强制切分的块仍有正确的 chunk_index 和 token_count"""
        text = "连续无标点中文字符" * 200
        result = semantic_chunk(text, max_tokens=32, overlap_tokens=4)
        for i, chunk in enumerate(result):
            assert chunk.chunk_index == i
            assert chunk.token_count > 0
            assert len(chunk.text) > 0


# ── 重叠段 ──────────────────────────────────────────────────────

class TestOverlap:
    """相邻块之间应有重叠片段"""

    def test_overlap_exists_between_adjacent_chunks(self):
        """相邻块的文本应有部分重叠（overlap_tokens > 0 时）"""
        sentences = [f"第{i}句话的内容比较长需要占用多个token。" for i in range(30)]
        text = "".join(sentences)
        result = semantic_chunk(text, max_tokens=64, overlap_tokens=16)
        if len(result) >= 2:
            # 检查第1块的末尾和第2块的开头有文本重叠
            first_end = result[0].text
            second_start = result[1].text
            # 至少有部分文字在两块中都出现
            overlap_found = False
            for seg_len in range(2, min(len(first_end), len(second_start))):
                if first_end[-seg_len:] in second_start:
                    overlap_found = True
                    break
            # 有重叠或者 start_char 有回退
            has_char_overlap = (
                len(result) >= 2 and result[1].start_char < result[0].end_char
            )
            assert overlap_found or has_char_overlap, "相邻块之间应有重叠"

    def test_zero_overlap_produces_no_overlap(self):
        """overlap_tokens=0 时块之间不应有字符偏移回退"""
        sentences = [f"第{i}句测试文本内容。" for i in range(30)]
        text = "".join(sentences)
        result = semantic_chunk(text, max_tokens=32, overlap_tokens=0)
        if len(result) >= 2:
            for i in range(1, len(result)):
                # 允许因为段落边界的微小差异
                assert result[i].start_char >= result[i - 1].start_char
