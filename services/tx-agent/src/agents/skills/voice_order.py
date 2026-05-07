"""语音点菜 Agent — P1 | 边缘+云端

能力：语音转文字、点菜意图解析、菜品模糊匹配、确认下单、语音点餐统计
语音转文字使用 mock 接口（真实环境接入 Whisper/讯飞）。
菜品匹配支持拼音模糊搜索（duojiaoyutou→剁椒鱼头）。
"""

from typing import Any, Optional

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger()


# ── 拼音工具（简易版，无外部依赖） ──────────────────────────
# 常用餐饮汉字→拼音映射（生产环境应使用 pypinyin 库）
_PINYIN_MAP: dict[str, str] = {
    "剁": "duo",
    "椒": "jiao",
    "鱼": "yu",
    "头": "tou",
    "啤": "pi",
    "酒": "jiu",
    "米": "mi",
    "饭": "fan",
    "红": "hong",
    "烧": "shao",
    "肉": "rou",
    "宫": "gong",
    "保": "bao",
    "鸡": "ji",
    "丁": "ding",
    "麻": "ma",
    "婆": "po",
    "豆": "dou",
    "腐": "fu",
    "水": "shui",
    "煮": "zhu",
    "片": "pian",
    "白": "bai",
    "切": "qie",
    "回": "hui",
    "锅": "guo",
    "辣": "la",
    "子": "zi",
    "蛋": "dan",
    "炒": "chao",
    "饭": "fan",
    "面": "mian",
    "汤": "tang",
    "粉": "fen",
    "虾": "xia",
    "蟹": "xie",
    "龙": "long",
    "清": "qing",
    "蒸": "zheng",
    "炸": "zha",
    "烤": "kao",
    "煎": "jian",
    "焖": "men",
    "炖": "dun",
    "凉": "liang",
    "拌": "ban",
    "青": "qing",
    "菜": "cai",
    "猪": "zhu",
    "牛": "niu",
    "羊": "yang",
    "排": "pai",
    "骨": "gu",
    "翅": "chi",
    "腿": "tui",
    "肚": "du",
    "肝": "gan",
    "肠": "chang",
    "血": "xue",
    "花": "hua",
    "藕": "ou",
    "笋": "sun",
    "菌": "jun",
    "蘑": "mo",
    "菇": "gu",
    "茄": "qie",
    "椒": "jiao",
    "葱": "cong",
    "姜": "jiang",
    "蒜": "suan",
    "醋": "cu",
    "糖": "tang",
    "盐": "yan",
    "油": "you",
    "酱": "jiang",
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
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "半": 0.5,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
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

    # Sprint D1 / PR H 批次 2：语音点菜影响点单速度体验
    constraint_scope = {"experience"}

    def get_supported_actions(self) -> list[str]:
        return [
            "transcribe",
            "parse_order_intent",
            "match_dishes",
            "confirm_and_order",
            "process_voice_order",
            "get_stats",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "transcribe": self._transcribe,
            "parse_order_intent": self._parse_order_intent,
            "match_dishes": self._match_dishes,
            "confirm_and_order": self._confirm_and_order,
            "process_voice_order": self._process_voice_order,
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
                success=False,
                action="transcribe",
                error="缺少 audio_data 参数",
            )
        result = await transcribe(audio_data)
        logger.info(
            "voice_transcribe_done", tenant_id=self.tenant_id, text=result["text"], confidence=result["confidence"]
        )
        return AgentResult(
            success=True,
            action="transcribe",
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
                success=False,
                action="parse_order_intent",
                error="缺少 text 参数",
            )

        intent = self._extract_intent(text)
        logger.info("voice_intent_parsed", tenant_id=self.tenant_id, text=text, intent=intent)

        return AgentResult(
            success=True,
            action="parse_order_intent",
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
            intents.append(
                {
                    "action": "modify",
                    "modifier": modifiers[0],
                }
            )
            return intents

        # 检测动作
        action = "add"
        for act, keywords in _ACTION_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    action = act
                    break

        # 检测数量（regex 优先，兼容 "100 份" / "三份" / "两瓶"）
        quantity: float = 1
        unit = "份"
        import re as _re
        qty_match = _re.search(r"(\d+)", text)
        if qty_match:
            quantity = int(qty_match.group(1))
        else:
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

        # 提取菜名（移除数量词、动作词、单位词、阿拉伯数字、语气填充词后的核心词）
        dish_text = text
        # 先 strip 阿拉伯数字（兼容 100 / 50 / 3 等）
        import re as _re2
        dish_text = _re2.sub(r"\d+", "", dish_text)
        for kw_list in _ACTION_KEYWORDS.values():
            for kw in kw_list:
                dish_text = dish_text.replace(kw, "")
        for q_word in _QUANTITY_WORDS:
            dish_text = dish_text.replace(q_word, "")
        for u in _UNIT_KEYWORDS:
            dish_text = dish_text.replace(u, "")
        for filler in ["的", "了", "啊", "呢", "吧", "嘛", "哦", "呀", "那", "个", "这", " "]:
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
                success=False,
                action="match_dishes",
                error="缺少 dish 参数",
            )

        matches = self._fuzzy_match(dish_query, menu_items, top_n)

        logger.info("voice_dish_matched", tenant_id=self.tenant_id, query=dish_query, match_count=len(matches))

        return AgentResult(
            success=True,
            action="match_dishes",
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
        """模糊匹配菜品（精确 → 包含 → 拼音 → 字符 overlap 多层 fallback）"""
        scored: list[dict] = []
        # 字符 overlap 用：去除指代/语气词
        FILLER_CHARS = set("那个的了啊呢吧嘛哦呀这一二三 ")
        query_chars = set(query) - FILLER_CHARS

        for item in menu_items:
            name = item.get("name", "")
            score = 0.0
            match_type = "pinyin"

            # 精确匹配
            if query == name:
                score = 1.0
                match_type = "exact"
            # 包含匹配
            elif query in name or name in query:
                score = 0.85
                match_type = "contains"
            else:
                # 拼音 similarity
                pinyin_score = _pinyin_similarity(query, name)
                # 字符 overlap fallback（处理 "辣的鱼" / "那个鱼" 等含有原菜名 1-2 字符的指代）
                name_chars = set(name)
                char_overlap = (
                    len(query_chars & name_chars) / max(1, len(query_chars))
                    if query_chars else 0.0
                )
                score = max(pinyin_score, char_overlap)
                match_type = "char" if char_overlap > pinyin_score else "pinyin"

            if score > 0.15:
                scored.append({
                    **item,
                    "score": round(score, 3),
                    "match_type": match_type,
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
                success=False,
                action="confirm_and_order",
                error="没有待确认的菜品",
            )
        if not table_id:
            return AgentResult(
                success=False,
                action="confirm_and_order",
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
            order_items.append(
                {
                    "dish_id": item.get("dish_id", ""),
                    "dish_name": item.get("name", item.get("dish_name", "")),
                    "quantity": qty,
                    "unit": item.get("unit", "份"),
                    "price_fen": price,
                    "subtotal_fen": subtotal,
                    "modifiers": item.get("modifiers", []),
                }
            )

        import uuid

        order_id = f"VO-{uuid.uuid4().hex[:8].upper()}"

        logger.info(
            "voice_order_confirmed",
            tenant_id=self.tenant_id,
            table_id=table_id,
            order_id=order_id,
            item_count=len(order_items),
            total_fen=total_fen,
        )

        return AgentResult(
            success=True,
            action="confirm_and_order",
            data={
                "order_id": order_id,
                "table_id": table_id,
                "items": order_items,
                "total_fen": total_fen,
                "total_yuan": round(total_fen / 100, 2),
                "status": "confirmed",
                "order_type": "voice",
            },
            reasoning=f"语音点餐已确认: {len(order_items)} 道菜，合计 ¥{total_fen / 100:.2f}",
            confidence=0.95,
        )

    # ── Action: 端到端语音点餐处理（v1.0 Tier 1） ──────────────────
    async def _process_voice_order(self, params: dict) -> AgentResult:
        """端到端处理语音点餐：解析 → 匹配 → 沽清/数量校验 → 输出 A2UI Surface

        三条硬约束 UI 表达（v1.0 宪法 §1.4）：
          - 食安合规：沽清菜拒绝 + 推荐替代
          - 客户体验：模糊匹配返回候选让用户确认
          - 毛利底线：数量异常二次确认（防误点）
        """
        import uuid as _uuid
        text: str = params.get("text", "").strip()
        menu_items: list[dict] = params.get("menu_items", [])
        table_id: str = params.get("table_id", "")
        EXCESSIVE_QTY = 10  # 数量异常阈值

        if not text or not menu_items or not table_id:
            return AgentResult(
                success=False,
                action="process_voice_order",
                error="缺少必填参数（text / menu_items / table_id）",
                reasoning="参数校验失败",
            )

        # Step 1: 解析意图
        intents = self._extract_intent(text)
        if not intents:
            return self._build_error_surface(
                action="process_voice_order",
                title="无法识别点菜意图",
                message=f"'{text}' 未匹配到点菜动作，请再说一次",
            )

        # Step 2: 对每个意图项做匹配 + 沽清/数量检查
        sold_out_items = []
        excessive_qty_items = []
        ambiguous_items = []
        confirmed_items = []
        warnings = []

        for intent in intents:
            if intent.get("action") != "add":
                continue
            dish_query = intent.get("dish", "")
            quantity = intent.get("quantity", 1)
            if not dish_query:
                continue

            matches = self._fuzzy_match(dish_query, menu_items, top_n=3)
            if not matches:
                warnings.append(f"未找到匹配菜品：{dish_query}")
                continue

            best = matches[0]

            # 食安合规：沽清菜
            if best.get("sold_out"):
                # 推荐同类替代（非沽清）
                same_cat = [m for m in menu_items
                            if m.get("category") == best.get("category")
                            and not m.get("sold_out")
                            and m.get("dish_id") != best.get("dish_id")]
                alternatives = same_cat[:3] if same_cat else [
                    m for m in menu_items if not m.get("sold_out")
                ][:3]
                sold_out_items.append({
                    "requested": best,
                    "alternatives": alternatives,
                })
                continue

            # 客户体验：弱匹配（score < 0.85）→ 弹候选确认
            if best["score"] < 0.85:
                ambiguous_items.append({
                    "query": dish_query,
                    "candidates": matches[:3],
                })
                continue

            # 毛利底线：数量异常
            if quantity > EXCESSIVE_QTY:
                excessive_qty_items.append({
                    "dish": best,
                    "quantity": quantity,
                })
                warnings.append(f"数量异常：'{best['name']}' 请求 {quantity} 份（>{EXCESSIVE_QTY}），需经理确认")
                continue

            confirmed_items.append({
                **best,
                "quantity": quantity,
                "unit": intent.get("unit", "份"),
                "modifiers": intent.get("modifiers", []),
            })

        # Step 3: 决定路径并构造 A2UI Surface
        requires_confirmation = bool(sold_out_items or ambiguous_items or excessive_qty_items)

        if sold_out_items:
            # 沽清：警告 + 推荐替代
            so = sold_out_items[0]
            alternatives = so["alternatives"]
            surface = self._build_sold_out_surface(so["requested"], alternatives)
            return AgentResult(
                success=True,
                action="process_voice_order",
                data={
                    "a2ui_surface": surface,
                    "rejected": True,
                    "reason": "sold_out",
                    "requested_dish": so["requested"]["name"],
                    "alternatives": alternatives,
                    "warnings": warnings,
                    "requires_confirmation": True,
                },
                reasoning=f"食安合规：'{so['requested']['name']}' 已沽清，推荐 {len(alternatives)} 个替代菜",
                confidence=0.92,
                inference_layer="edge",
            )

        if ambiguous_items:
            ai = ambiguous_items[0]
            surface = self._build_candidate_surface(ai["query"], ai["candidates"])
            return AgentResult(
                success=True,
                action="process_voice_order",
                data={
                    "a2ui_surface": surface,
                    "candidates": ai["candidates"],
                    "candidate_count": len(ai["candidates"]),
                    "warnings": warnings,
                    "requires_confirmation": True,
                },
                reasoning=f"客户体验：'{ai['query']}' 匹配多个候选 {len(ai['candidates'])} 项，需用户确认",
                confidence=ai["candidates"][0]["score"],
                inference_layer="edge",
            )

        if excessive_qty_items:
            eq = excessive_qty_items[0]
            surface = self._build_excessive_qty_surface(eq["dish"], eq["quantity"])
            return AgentResult(
                success=True,
                action="process_voice_order",
                data={
                    "a2ui_surface": surface,
                    "excessive": True,
                    "dish": eq["dish"]["name"],
                    "requested_quantity": eq["quantity"],
                    "warnings": warnings,
                    "requires_confirmation": True,
                },
                reasoning=f"客户体验/毛利保护：'{eq['dish']['name']}' 数量 {eq['quantity']} 异常，需二次确认",
                confidence=0.88,
                inference_layer="edge",
            )

        # 标准路径：构造 OrderConfirm 卡片
        total_fen = sum(int(it.get("price_fen", 0) * it.get("quantity", 1)) for it in confirmed_items)
        surface = self._build_order_confirm_surface(confirmed_items, total_fen)
        return AgentResult(
            success=True,
            action="process_voice_order",
            data={
                "a2ui_surface": surface,
                "items": confirmed_items,
                "total_fen": total_fen,
                "table_id": table_id,
                "warnings": warnings,
                "requires_confirmation": False,
            },
            reasoning=f"标准点餐：解析 {len(confirmed_items)} 道菜，合计 ¥{total_fen / 100:.2f}，三条硬约束通过",
            confidence=0.95,
            inference_layer="edge",
        )

    # ── A2UI Surface 构造器 ──────────────────────────────
    @staticmethod
    def _surface_id() -> str:
        import uuid as _uuid
        return f"voice-order-{_uuid.uuid4().hex[:8]}"

    def _build_order_confirm_surface(self, items: list[dict], total_fen: int) -> dict:
        sid = self._surface_id()
        return {
            "surfaceId": sid,
            "components": [
                {"id": f"{sid}-card", "type": "card",
                 "properties": {"severity": "info", "title": "确认点餐"}},
                {"id": f"{sid}-list", "type": "list", "parent": f"{sid}-card",
                 "properties": {"items": [
                     {"label": f"{it['name']} ×{it['quantity']}",
                      "value": f"¥{it.get('price_fen', 0) * it.get('quantity', 1) / 100:.2f}"}
                     for it in items
                 ]}},
                {"id": f"{sid}-total", "type": "text", "parent": f"{sid}-card",
                 "properties": {"content": f"合计 ¥{total_fen / 100:.2f}", "size": "lg"}},
                {"id": f"{sid}-cancel", "type": "button",
                 "properties": {"label": "取消", "variant": "ghost", "action": "voice_order.cancel"}},
                {"id": f"{sid}-confirm", "type": "button",
                 "properties": {"label": "确认下单", "variant": "primary", "action": "voice_order.confirm"}},
            ],
        }

    def _build_sold_out_surface(self, requested: dict, alternatives: list[dict]) -> dict:
        sid = self._surface_id()
        return {
            "surfaceId": sid,
            "components": [
                {"id": f"{sid}-card", "type": "card",
                 "properties": {"severity": "warning", "title": f"⚠ {requested['name']} 已沽清"}},
                {"id": f"{sid}-msg", "type": "text", "parent": f"{sid}-card",
                 "properties": {"content": f"很抱歉，{requested['name']} 已售完。为您推荐："}},
                {"id": f"{sid}-alts", "type": "list", "parent": f"{sid}-card",
                 "properties": {"items": [
                     {"label": alt["name"],
                      "value": f"¥{alt.get('price_fen', 0) / 100:.2f}",
                      "action": f"voice_order.choose:{alt['dish_id']}"}
                     for alt in alternatives
                 ]}},
                {"id": f"{sid}-cancel", "type": "button",
                 "properties": {"label": "取消", "variant": "ghost", "action": "voice_order.cancel"}},
            ],
        }

    def _build_candidate_surface(self, query: str, candidates: list[dict]) -> dict:
        sid = self._surface_id()
        return {
            "surfaceId": sid,
            "components": [
                {"id": f"{sid}-card", "type": "card",
                 "properties": {"severity": "info", "title": f"请选择您要的菜品（来自 '{query}'）"}},
                {"id": f"{sid}-list", "type": "list", "parent": f"{sid}-card",
                 "properties": {"items": [
                     {"label": c["name"],
                      "value": f"¥{c.get('price_fen', 0) / 100:.2f}",
                      "action": f"voice_order.choose:{c['dish_id']}"}
                     for c in candidates
                 ]}},
                {"id": f"{sid}-cancel", "type": "button",
                 "properties": {"label": "取消", "variant": "ghost", "action": "voice_order.cancel"}},
            ],
        }

    def _build_excessive_qty_surface(self, dish: dict, quantity: int) -> dict:
        sid = self._surface_id()
        return {
            "surfaceId": sid,
            "components": [
                {"id": f"{sid}-card", "type": "card",
                 "properties": {"severity": "warning", "title": f"⚠ 数量异常确认"}},
                {"id": f"{sid}-msg", "type": "text", "parent": f"{sid}-card",
                 "properties": {
                     "content": f"您要点 {dish['name']} ×{quantity}（合计 ¥{dish.get('price_fen', 0) * quantity / 100:.2f}），数量较多，请确认是否正确",
                 }},
                {"id": f"{sid}-cancel", "type": "button",
                 "properties": {"label": "取消", "variant": "ghost", "action": "voice_order.cancel"}},
                {"id": f"{sid}-confirm", "type": "button",
                 "properties": {"label": f"确认 ×{quantity}", "variant": "danger", "action": "voice_order.confirm"}},
            ],
        }

    def _build_error_surface(self, *, action: str, title: str, message: str) -> AgentResult:
        sid = self._surface_id()
        surface = {
            "surfaceId": sid,
            "components": [
                {"id": f"{sid}-card", "type": "card",
                 "properties": {"severity": "warning", "title": title}},
                {"id": f"{sid}-msg", "type": "text", "parent": f"{sid}-card",
                 "properties": {"content": message}},
                {"id": f"{sid}-cancel", "type": "button",
                 "properties": {"label": "取消", "variant": "ghost", "action": "voice_order.cancel"}},
            ],
        }
        return AgentResult(
            success=True,  # Agent 调度成功，只是结果是"无法处理"
            action=action,
            data={"a2ui_surface": surface, "warnings": [message], "requires_confirmation": True},
            reasoning=f"识别失败：{title} — {message}",
            confidence=0.3,
            inference_layer="edge",
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
            success=True,
            action="get_stats",
            data=stats,
            reasoning=f"门店 {store_id} 语音点餐占比 {stats['voice_order_rate']:.1%}",
            confidence=0.9,
        )
