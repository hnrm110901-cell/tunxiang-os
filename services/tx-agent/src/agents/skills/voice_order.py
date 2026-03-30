"""语音点菜 Agent — P1 | 边缘+云端

能力：语音转文字、点菜意图解析、菜品模糊匹配、确认下单、语音点餐统计
语音转文字使用 mock 接口（真实环境接入 Whisper/讯飞）。
菜品匹配支持拼音模糊搜索（duojiaoyutou→剁椒鱼头）。
"""
from typing import Any, Optional

import structlog

from ..base import SkillAgent, AgentResult

logger = structlog.get_logger()


# ── 拼音工具（简易版，无外部依赖） ──────────────────────────
# 常用餐饮汉字→拼音映射（生产环境应使用 pypinyin 库）
_PINYIN_MAP: dict[str, str] = {
    "剁": "duo", "椒": "jiao", "鱼": "yu", "头": "tou",
    "啤": "pi", "酒": "jiu", "米": "mi", "饭": "fan",
    "红": "hong", "烧": "shao", "肉": "rou", "宫": "gong",
    "保": "bao", "鸡": "ji", "丁": "ding", "麻": "ma",
    "婆": "po", "豆": "dou", "腐": "fu", "水": "shui",
    "煮": "zhu", "片": "pian", "白": "bai", "切": "qie",
    "回": "hui", "锅": "guo", "辣": "la", "子": "zi",
    "蛋": "dan", "炒": "chao", "饭": "fan", "面": "mian",
    "汤": "tang", "粉": "fen", "虾": "xia", "蟹": "xie",
    "龙": "long", "清": "qing", "蒸": "zheng", "炸": "zha",
    "烤": "kao", "煎": "jian", "焖": "men", "炖": "dun",
    "凉": "liang", "拌": "ban", "青": "qing", "菜": "cai",
    "猪": "zhu", "牛": "niu", "羊": "yang", "排": "pai",
    "骨": "gu", "翅": "chi", "腿": "tui", "肚": "du",
    "肝": "gan", "肠": "chang", "血": "xue", "花": "hua",
    "藕": "ou", "笋": "sun", "菌": "jun", "蘑": "mo",
    "菇": "gu", "茄": "qie", "椒": "jiao", "葱": "cong",
    "姜": "jiang", "蒜": "suan", "醋": "cu", "糖": "tang",
    "盐": "yan", "油": "you", "酱": "jiang",
}


def _to_pinyin(text: str) -> str:
    """汉字→拼音（简易版）"""
    return "".join(_PINYIN_MAP.get(ch, ch) for ch in text)


def _pinyin_similarity(a: str, b: str) -> float:
    """拼音相似度（0~1），使用最长公共子序列"""
    pa, pb = _to_pinyin(a), _to_pinyin(b)
    if not pa or not pb:
        return 0.0
    m, n = len(pa), len(pb)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if pa[i - 1] == pb[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    lcs = dp[m][n]
    return lcs / max(m, n)


# ── 意图解析关键词 ─────────────────────────────────────
_QUANTITY_WORDS = {
    "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "半": 0.5, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5,
}

_ACTION_KEYWORDS = {
    "add": ["来", "加", "要", "上", "点", "再来", "再加", "添"],
    "remove": ["退", "不要了", "撤", "取消", "去掉"],
    "modify": ["换", "改", "不要辣", "少辣", "多辣", "微辣", "不放", "加辣"],
}

_MODIFIER_KEYWORDS = {
    "不辣": ["不要辣", "不辣", "不放辣"],
    "微辣": ["微辣", "一点点辣"],
    "少辣": ["少辣", "少放辣"],
    "多辣": ["多辣", "加辣", "特辣"],
    "不放葱": ["不放葱", "不要葱", "去葱"],
    "不放香菜": ["不放香菜", "不要香菜", "去香菜"],
    "加蛋": ["加蛋", "加个蛋"],
}

_UNIT_KEYWORDS = ["份", "个", "瓶", "杯", "碗", "盘", "斤", "两", "扎", "打"]


# ── Mock 语音转文字 ────────────────────────────────────
async def transcribe(audio_data: bytes) -> dict[str, Any]:
    """语音→文字（mock 接口）

    真实环境调用 Whisper 或讯飞 ASR。
    返回: {"text": "来一份剁椒鱼头", "confidence": 0.95, "language": "zh"}
    """
    logger.info("voice_transcribe", audio_size=len(audio_data))
    # Mock: 返回固定文本（测试用）
    return {
        "text": "来一份剁椒鱼头",
        "confidence": 0.95,
        "language": "zh",
        "duration_ms": 2300,
    }


class VoiceOrderAgent(SkillAgent):
    """语音点菜 Agent

    处理语音点餐的完整流程：
    1. transcribe: 语音→文字
    2. parse_order_intent: 解析点菜意图
    3. match_dishes: 模糊匹配菜品
    4. confirm_and_order: 确认下单
    5. get_stats: 语音点餐统计
    """

    agent_id = "voice_order"
    agent_name = "语音点菜"
    description = "语音转文字、点菜意图解析、菜品模糊匹配（拼音）、确认下单"
    priority = "P1"
    run_location = "edge+cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "transcribe", "parse_order_intent", "match_dishes",
            "confirm_and_order", "get_stats",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "transcribe": self._transcribe,
            "parse_order_intent": self._parse_order_intent,
            "match_dishes": self._match_dishes,
            "confirm_and_order": self._confirm_and_order,
            "get_stats": self._get_stats,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported: {action}")
        return await handler(params)

    # ── Action: 语音转文字 ────────────────────────────────
    async def _transcribe(self, params: dict) -> AgentResult:
        """语音转文字"""
        audio_data: bytes = params.get("audio_data", b"")
        if not audio_data:
            return AgentResult(
                success=False, action="transcribe",
                error="缺少 audio_data 参数",
            )
        result = await transcribe(audio_data)
        logger.info("voice_transcribe_done",
                     tenant_id=self.tenant_id, text=result["text"],
                     confidence=result["confidence"])
        return AgentResult(
            success=True, action="transcribe",
            data=result,
            reasoning=f"语音识别完成: '{result['text']}' (置信度 {result['confidence']})",
            confidence=result["confidence"],
            inference_layer="edge",
        )

    # ── Action: 解析点菜意图 ──────────────────────────────
    async def _parse_order_intent(self, params: dict) -> AgentResult:
        """解析自然语言中的点菜意图

        示例:
        - "来一份剁椒鱼头" → {dish: "剁椒鱼头", quantity: 1, action: "add"}
        - "再加两瓶啤酒" → {dish: "啤酒", quantity: 2, unit: "瓶", action: "add"}
        - "鱼要三斤的" → {dish: "鱼", weight_spec: "3斤", action: "modify"}
        - "不要辣" → {modifier: "不辣", action: "modify"}
        """
        text: str = params.get("text", "").strip()
        if not text:
            return AgentResult(
                success=False, action="parse_order_intent",
                error="缺少 text 参数",
            )

        intent = self._extract_intent(text)
        logger.info("voice_intent_parsed",
                     tenant_id=self.tenant_id, text=text, intent=intent)

        return AgentResult(
            success=True, action="parse_order_intent",
            data={"original_text": text, "intent": intent},
            reasoning=f"从 '{text}' 解析出 {len(intent)} 个意图项",
            confidence=0.85,
        )

    def _extract_intent(self, text: str) -> list[dict[str, Any]]:
        """从文本中提取点菜意图"""
        intents: list[dict[str, Any]] = []

        # 检测修饰语（不辣/加辣/不放葱等）
        modifiers: list[str] = []
        for mod_key, mod_phrases in _MODIFIER_KEYWORDS.items():
            for phrase in mod_phrases:
                if phrase in text:
                    modifiers.append(mod_key)
                    text = text.replace(phrase, "")
                    break

        if modifiers and not any(ch not in "的了啊呢吧嘛哦呀" and ch not in " " for ch in text):
            # 纯修饰语句（如 "不要辣"）
            intents.append({
                "action": "modify",
                "modifier": modifiers[0],
            })
            return intents

        # 检测动作
        action = "add"
        for act, keywords in _ACTION_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    action = act
                    break

        # 检测数量
        quantity = 1
        unit = "份"
        for q_word, q_val in _QUANTITY_WORDS.items():
            if q_word in text:
                quantity = q_val
                break

        for u in _UNIT_KEYWORDS:
            if u in text:
                unit = u
                break

        # 检测重量规格（如 "三斤的"）
        weight_spec: Optional[str] = None
        for q_word, q_val in _QUANTITY_WORDS.items():
            if q_word in text and "斤" in text:
                weight_spec = f"{q_val}斤"
                break

        # 提取菜名（移除数量词、动作词、单位词后的核心词）
        dish_text = text
        for kw_list in _ACTION_KEYWORDS.values():
            for kw in kw_list:
                dish_text = dish_text.replace(kw, "")
        for q_word in _QUANTITY_WORDS:
            dish_text = dish_text.replace(q_word, "")
        for u in _UNIT_KEYWORDS:
            dish_text = dish_text.replace(u, "")
        for filler in ["的", "了", "啊", "呢", "吧", "嘛", "哦", "呀", " "]:
            dish_text = dish_text.replace(filler, "")

        dish_name = dish_text.strip()

        if dish_name:
            item: dict[str, Any] = {
                "action": action,
                "dish": dish_name,
                "quantity": quantity,
                "unit": unit,
            }
            if weight_spec:
                item["weight_spec"] = weight_spec
            if modifiers:
                item["modifiers"] = modifiers
            intents.append(item)
        elif modifiers:
            intents.append({"action": "modify", "modifier": modifiers[0]})

        return intents

    # ── Action: 菜品匹配 ─────────────────────────────────
    async def _match_dishes(self, params: dict) -> AgentResult:
        """根据意图中的菜名进行模糊匹配

        支持：
        - 精确匹配
        - 包含匹配
        - 拼音模糊匹配（duojiaoyutou→剁椒鱼头）
        - 同音字纠错
        """
        dish_query: str = params.get("dish", "")
        menu_items: list[dict] = params.get("menu_items", [])
        top_n: int = params.get("top_n", 3)

        if not dish_query:
            return AgentResult(
                success=False, action="match_dishes",
                error="缺少 dish 参数",
            )

        matches = self._fuzzy_match(dish_query, menu_items, top_n)

        logger.info("voice_dish_matched",
                     tenant_id=self.tenant_id, query=dish_query,
                     match_count=len(matches))

        return AgentResult(
            success=True, action="match_dishes",
            data={
                "query": dish_query,
                "matches": matches,
                "match_count": len(matches),
                "best_match": matches[0] if matches else None,
            },
            reasoning=f"为 '{dish_query}' 找到 {len(matches)} 个匹配菜品",
            confidence=matches[0]["score"] if matches else 0.0,
        )

    def _fuzzy_match(self, query: str, menu_items: list[dict], top_n: int) -> list[dict]:
        """模糊匹配菜品"""
        scored: list[dict] = []

        for item in menu_items:
            name = item.get("name", "")
            score = 0.0

            # 精确匹配
            if query == name:
                score = 1.0
            # 包含匹配
            elif query in name or name in query:
                score = 0.85
            else:
                # 拼音模糊匹配
                score = _pinyin_similarity(query, name)

            if score > 0.3:
                scored.append({
                    **item,
                    "score": round(score, 3),
                    "match_type": "exact" if score == 1.0
                                 else "contains" if score >= 0.85
                                 else "pinyin",
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_n]

    # ── Action: 确认下单 ─────────────────────────────────
    async def _confirm_and_order(self, params: dict) -> AgentResult:
        """确认语音点餐内容并下单"""
        matched_items: list[dict] = params.get("matched_items", [])
        table_id: str = params.get("table_id", "")

        if not matched_items:
            return AgentResult(
                success=False, action="confirm_and_order",
                error="没有待确认的菜品",
            )
        if not table_id:
            return AgentResult(
                success=False, action="confirm_and_order",
                error="缺少 table_id 参数",
            )

        # 计算订单金额
        total_fen = 0
        order_items = []
        for item in matched_items:
            qty = item.get("quantity", 1)
            price = item.get("price_fen", 0)
            subtotal = int(price * qty)
            total_fen += subtotal
            order_items.append({
                "dish_id": item.get("dish_id", ""),
                "dish_name": item.get("name", item.get("dish_name", "")),
                "quantity": qty,
                "unit": item.get("unit", "份"),
                "price_fen": price,
                "subtotal_fen": subtotal,
                "modifiers": item.get("modifiers", []),
            })

        import uuid
        order_id = f"VO-{uuid.uuid4().hex[:8].upper()}"

        logger.info("voice_order_confirmed",
                     tenant_id=self.tenant_id, table_id=table_id,
                     order_id=order_id, item_count=len(order_items),
                     total_fen=total_fen)

        return AgentResult(
            success=True, action="confirm_and_order",
            data={
                "order_id": order_id,
                "table_id": table_id,
                "items": order_items,
                "total_fen": total_fen,
                "total_yuan": round(total_fen / 100, 2),
                "status": "confirmed",
                "order_type": "voice",
            },
            reasoning=f"语音点餐已确认: {len(order_items)} 道菜，合计 ¥{total_fen/100:.2f}",
            confidence=0.95,
        )

    # ── Action: 语音点餐统计 ──────────────────────────────
    async def _get_stats(self, params: dict) -> AgentResult:
        """获取语音点餐统计数据（mock）"""
        store_id = params.get("store_id", self.store_id or "")

        # Mock 统计数据
        stats = {
            "store_id": store_id,
            "period": params.get("period", "today"),
            "total_voice_orders": 47,
            "total_orders": 180,
            "voice_order_rate": 0.261,
            "avg_recognition_confidence": 0.92,
            "avg_intent_parse_success_rate": 0.88,
            "top_voice_dishes": [
                {"name": "剁椒鱼头", "count": 12},
                {"name": "红烧肉", "count": 8},
                {"name": "啤酒", "count": 15},
            ],
            "recognition_errors": 5,
            "error_rate": 0.106,
        }

        return AgentResult(
            success=True, action="get_stats",
            data=stats,
            reasoning=f"门店 {store_id} 语音点餐占比 {stats['voice_order_rate']:.1%}",
            confidence=0.9,
        )
