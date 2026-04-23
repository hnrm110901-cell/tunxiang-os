"""
语音指令本地缓存 — 门店网络差时保障语音点餐可用

缓存策略：
- 最近 50 条指令 + 解析结果存 LRU 缓存（内存）
- 常用菜品名 → 菜品ID 映射持久化（JSON文件）
- 网络不可用时：用本地缓存 + 模糊匹配兜底
"""

from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from difflib import SequenceMatcher
from typing import Any, Optional

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_CACHE_PATH = os.environ.get("VOICE_CACHE_PATH", "/tmp/txos_voice_cache.json")
_LRU_MAXSIZE = 50
_FUZZY_THRESHOLD = 0.6  # 相似度阈值，低于此值不采用模糊匹配结果


class _LRUCache:
    """简单 LRU 缓存（maxsize=50）"""

    def __init__(self, maxsize: int = _LRU_MAXSIZE) -> None:
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> Optional[Any]:
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return self._cache[key]

    def put(self, key: str, value: Any) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)

    def __len__(self) -> int:
        return len(self._cache)


class VoiceCommandCache:
    """语音指令本地缓存

    职责：
    1. 音频哈希 → 识别结果 LRU 缓存（内存，maxsize=50）
    2. 菜品名 → 菜品ID 持久化映射（JSON文件）
    3. 模糊匹配兜底（difflib SequenceMatcher）
    4. 命中率统计
    """

    def __init__(self, cache_path: str = _CACHE_PATH) -> None:
        self._lru: _LRUCache = _LRUCache(maxsize=_LRU_MAXSIZE)
        self._dish_map: dict[str, str] = {}  # dish_name → dish_id
        self._cache_path = cache_path
        self._hits = 0
        self._misses = 0
        self._load_persistent_cache()

    # ─── 音频缓存 ─────────────────────────────────────────────────────────────

    def get(self, audio_hash: str) -> Optional[dict[str, Any]]:
        """查询缓存。命中返回结果字典，未命中返回 None。"""
        result = self._lru.get(audio_hash)
        if result is not None:
            self._hits += 1
            log.info("voice_cache_hit", audio_hash=audio_hash[:8])
            return result
        self._misses += 1
        return None

    def put(self, audio_hash: str, result: dict[str, Any]) -> None:
        """写入缓存（自动淘汰最旧条目）"""
        self._lru.put(audio_hash, result)
        log.info("voice_cache_put", audio_hash=audio_hash[:8], cache_size=len(self._lru))

    # ─── 菜品模糊匹配 ─────────────────────────────────────────────────────────

    def fuzzy_match_dish(
        self,
        text: str,
        dish_catalog: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        """用 difflib 对菜品名做模糊匹配

        Args:
            text: 用户说出的菜品名（可能有错字/方言）
            dish_catalog: 菜品列表，每项包含 {"dish_id": str, "name": str}

        Returns:
            最佳匹配项（含相似度分数），或 None（无结果超过阈值）
        """
        if not text or not dish_catalog:
            return None

        best_score = 0.0
        best_item: Optional[dict[str, Any]] = None

        for item in dish_catalog:
            dish_name = item.get("name", "")
            if not dish_name:
                continue
            score = SequenceMatcher(None, text, dish_name).ratio()
            if score > best_score:
                best_score = score
                best_item = item

        if best_score >= _FUZZY_THRESHOLD and best_item is not None:
            log.info(
                "fuzzy_match_found",
                input_text=text,
                matched=best_item.get("name"),
                score=round(best_score, 3),
            )
            return {**best_item, "match_score": round(best_score, 3)}

        log.info("fuzzy_match_no_result", input_text=text, best_score=round(best_score, 3))
        return None

    # ─── 缓存预热 ─────────────────────────────────────────────────────────────

    def warm(self, dish_catalog: list[dict[str, Any]]) -> int:
        """预热菜品名映射缓存

        Args:
            dish_catalog: 菜品列表，每项包含 {"dish_id": str, "name": str}

        Returns:
            预热菜品数量
        """
        count = 0
        for item in dish_catalog:
            dish_id = item.get("dish_id", "")
            name = item.get("name", "")
            if dish_id and name:
                self._dish_map[name] = dish_id
                count += 1

        self._save_persistent_cache()
        log.info("voice_cache_warmed", dish_count=count)
        return count

    # ─── 统计 ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """返回缓存命中率统计"""
        total = self._hits + self._misses
        hit_rate = round(self._hits / total, 4) if total > 0 else 0.0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": total,
            "hit_rate": hit_rate,
            "lru_size": len(self._lru),
            "lru_maxsize": _LRU_MAXSIZE,
            "dish_map_size": len(self._dish_map),
        }

    # ─── 持久化 ──────────────────────────────────────────────────────────────

    def _load_persistent_cache(self) -> None:
        """从 JSON 文件加载菜品名映射"""
        if not os.path.exists(self._cache_path):
            return
        try:
            with open(self._cache_path, encoding="utf-8") as f:
                data = json.load(f)
            self._dish_map = data.get("dish_map", {})
            log.info("voice_cache_loaded", dish_count=len(self._dish_map), path=self._cache_path)
        except (json.JSONDecodeError, OSError, KeyError) as e:
            log.warning("voice_cache_load_failed", error=str(e), path=self._cache_path)

    def _save_persistent_cache(self) -> None:
        """持久化菜品名映射到 JSON 文件"""
        try:
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump({"dish_map": self._dish_map, "updated_at": time.time()}, f, ensure_ascii=False)
        except OSError as e:
            log.warning("voice_cache_save_failed", error=str(e), path=self._cache_path)


# 模块级单例
_cache: Optional[VoiceCommandCache] = None


def get_voice_cache() -> VoiceCommandCache:
    global _cache
    if _cache is None:
        _cache = VoiceCommandCache()
    return _cache
