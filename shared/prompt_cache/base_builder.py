"""BaseCachedPromptBuilder — Anthropic Prompt Cache 构造器骨架

封装 D4a/D4b/D4c 三份 builder 共用的逻辑：

  1. 两段 system block：
     · 第 1 段：STABLE_SYSTEM（输出 schema，跨租户稳定）
     · 第 2 段：DOMAIN_BENCHMARKS（行业 benchmark，跨分析共享）
  2. cache_control 都标 ephemeral（5 分钟 TTL）
  3. messages 单 user turn，内容按 bundle 动态生成

子类只需实现三个 classmethod：
  · stable_system() — 返回第 1 段文本
  · domain_benchmarks() — 返回第 2 段文本
  · serialize_user_context(bundle) — 把业务 bundle 序列化为 user 消息

可选覆盖：
  · MODEL_ID — 默认 'claude-sonnet-4-7'（走 Prompt Cache beta）
  · MAX_TOKENS — 默认 2048
  · USER_PROMPT_PREFIX — 默认 "请分析以下输入："
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping


class BaseCachedPromptBuilder(ABC):
    """屯象OS 统一 Prompt Cache 构造器基类。

    子类示例：见 shared/prompt_cache/__init__.py 的 docstring。
    """

    MODEL_ID: str = "claude-sonnet-4-7"
    MAX_TOKENS: int = 2048
    USER_PROMPT_PREFIX: str = "请分析以下输入："

    # ─────────────────────────────────────────────────────────────
    # 子类必须实现
    # ─────────────────────────────────────────────────────────────

    @classmethod
    @abstractmethod
    def stable_system(cls) -> str:
        """第 1 段 cacheable system：输出 JSON schema + 全局规则。

        要求：
          · 跨租户稳定（不含租户/时间/门店等变量）
          · 明确输出 JSON schema + 各字段类型
          · 约束输出不含 markdown 代码块，直接 JSON
        """
        ...

    @classmethod
    @abstractmethod
    def domain_benchmarks(cls) -> str:
        """第 2 段 cacheable system：业务域基准（行业 / 法规 / 阈值）。

        要求：
          · 跨分析共享（同业态多店多月分析复用同一段 cache）
          · 内容稳定，只在季度或版本发布时更新
          · 含阈值和合规红线，便于 Sonnet 做 severity 判定
        """
        ...

    @classmethod
    @abstractmethod
    def serialize_user_context(cls, bundle: Any) -> str:
        """把业务 bundle 序列化为 user 消息内容（每次分析独立）。

        典型实现：
            return json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2)
        """
        ...

    # ─────────────────────────────────────────────────────────────
    # 公共 API
    # ─────────────────────────────────────────────────────────────

    @classmethod
    def build_messages(cls, bundle: Any) -> dict[str, Any]:
        """返回 Anthropic messages API 入参（含两段 cache_control）。

        结构：
            {
              "model": "claude-sonnet-4-7",
              "max_tokens": 2048,
              "system": [
                {"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": benchmarks, "cache_control": {"type": "ephemeral"}},
              ],
              "messages": [{"role": "user", "content": "请分析以下输入：\n{user_ctx}"}]
            }
        """
        stable = cls.stable_system()
        benchmarks = cls.domain_benchmarks()
        user_ctx = cls.serialize_user_context(bundle)

        return {
            "model": cls.MODEL_ID,
            "max_tokens": cls.MAX_TOKENS,
            "system": [
                {
                    "type": "text",
                    "text": stable,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": benchmarks,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            "messages": [
                {
                    "role": "user",
                    "content": f"{cls.USER_PROMPT_PREFIX}\n{user_ctx}",
                }
            ],
        }

    @classmethod
    def expected_cache_read_tokens(cls) -> int:
        """粗略估算两段 cacheable system 的 token 数（基于 UTF-8 字符数 / 2）。

        Anthropic 的 tokenizer 对中文约 1.8 字符/token，英文约 4 字符/token。
        混合内容折中估计 2 字符/token。仅用于监控 cache block 是否过小
        （< 1024 tokens 无法缓存）。
        """
        text_len = len(cls.stable_system()) + len(cls.domain_benchmarks())
        return text_len // 2

    @classmethod
    def validate_cache_size(cls) -> tuple[bool, str]:
        """检查两段 system block 是否达到最低可缓存门槛。

        Anthropic Prompt Cache 要求：每段至少 1024 tokens 才会被 cache。
        返回 (is_valid, message)。
        """
        estimated = cls.expected_cache_read_tokens()
        if estimated < 1024:
            return (
                False,
                f"估算 cacheable system tokens ~{estimated}，低于 Anthropic 1024 最低门槛；"
                f"建议在 domain_benchmarks 中补充更多示例或规则",
            )
        return (True, f"估算 cacheable system tokens ~{estimated}，达标")

    @classmethod
    def extract_usage(cls, response: Mapping[str, Any]) -> dict[str, int]:
        """从 Anthropic 响应中提取 usage 字段，统一映射到 4 个命名。

        返回：
            {"cache_read_tokens", "cache_creation_tokens", "input_tokens", "output_tokens"}
        """
        usage = response.get("usage") or {}
        return {
            "cache_read_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
            "cache_creation_tokens": int(
                usage.get("cache_creation_input_tokens", 0) or 0
            ),
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
        }
