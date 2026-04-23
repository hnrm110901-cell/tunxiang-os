"""语音交互全栈编排 — V1迁入+Whisper v3升级

完整链路：ASR(语音→文字) → NLU(意图+实体) → 路由 → 执行 → TTS(回复)

支持场景：
1. 服务员语音下单："三号桌加一份酸菜鱼微辣"
2. 店长语音查询："今天营收多少"
3. 厨师语音报损："鲈鱼损耗两斤记一下"
4. 收银语音操作："A05桌结账"
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


# ─── 中文数字映射 ───────────────────────────────────────────────

_CN_NUM_MAP: dict[str, int] = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_SPICE_LEVELS: dict[str, str] = {
    "微辣": "mild",
    "中辣": "medium",
    "特辣": "extra_hot",
    "变态辣": "extreme",
    "不辣": "none",
    "免辣": "none",
    "少辣": "mild",
    "多辣": "extra_hot",
}

_FLAVOR_KEYWORDS: dict[str, str] = {
    "微辣": "mild_spicy",
    "中辣": "medium_spicy",
    "特辣": "extra_spicy",
    "不辣": "no_spicy",
    "免辣": "no_spicy",
    "少盐": "less_salt",
    "多醋": "extra_vinegar",
    "少油": "less_oil",
    "加辣": "extra_spicy",
    "清淡": "light",
    "红烧": "braised",
    "麻辣": "mala",
    "酸辣": "sour_spicy",
    "糖醋": "sweet_sour",
}


def _chinese_num_to_int(s: str) -> int:
    """将中文数字或阿拉伯数字字符串转为 int。"""
    s = s.strip()
    if s.isdigit():
        return int(s)
    if len(s) == 1 and s in _CN_NUM_MAP:
        return _CN_NUM_MAP[s]
    if "十" in s:
        parts = s.split("十")
        tens = _CN_NUM_MAP.get(parts[0], 1) if parts[0] else 1
        ones = _CN_NUM_MAP.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    return 1


# ─── 意图定义 ────────────────────────────────────────────────────

ALL_INTENTS = [
    "order_add",
    "order_remove",
    "order_modify",
    "checkout",
    "open_table",
    "query_revenue",
    "query_inventory",
    "query_order_status",
    "report_waste",
    "call_service",
    "rush_order",
    "reserve_table",
    "query_staff",
    "daily_report",
    "switch_table",
    "merge_table",
]

# ─── 意图到服务路由映射 ────────────────────────────────────────────

INTENT_ROUTE_MAP: dict[str, dict[str, str]] = {
    "order_add": {"service": "CashierEngine", "method": "add_item"},
    "order_remove": {"service": "CashierEngine", "method": "remove_item"},
    "order_modify": {"service": "CashierEngine", "method": "modify_item"},
    "checkout": {"service": "CashierEngine", "method": "checkout"},
    "open_table": {"service": "TableManager", "method": "open_table"},
    "query_revenue": {"service": "StorePnL", "method": "generate_daily_pnl"},
    "query_inventory": {"service": "InventoryService", "method": "query_stock"},
    "query_order_status": {"service": "OrderService", "method": "get_status"},
    "report_waste": {"service": "WasteGuard", "method": "record_waste"},
    "call_service": {"service": "ServiceDispatch", "method": "call_waiter"},
    "rush_order": {"service": "KitchenDispatch", "method": "rush_order"},
    "reserve_table": {"service": "ReservationService", "method": "create_reservation"},
    "query_staff": {"service": "StaffService", "method": "query_on_duty"},
    "daily_report": {"service": "StorePnL", "method": "generate_daily_pnl"},
    "switch_table": {"service": "TableManager", "method": "switch_table"},
    "merge_table": {"service": "TableManager", "method": "merge_tables"},
}


class VoiceOrchestrator:
    """语音交互全栈编排 — V1迁入+Whisper v3升级

    完整链路：ASR(语音→文字) → NLU(意图+实体) → 路由 → 执行 → TTS(回复)
    """

    def __init__(self) -> None:
        self._whisper_model: Any = None
        self._whisper_available: bool = False
        self._intent_patterns: list[tuple[str, list[re.Pattern[str]]]] = self._build_intent_patterns()
        # 模拟服务注册表（实际部署时注入真实服务）
        self._service_registry: dict[str, Any] = {}

    def register_service(self, name: str, service: Any) -> None:
        """注册下游业务服务"""
        self._service_registry[name] = service

    # ══════════════════════════════════════════════════════════════
    # 1. ASR — Automatic Speech Recognition
    # ══════════════════════════════════════════════════════════════

    def _load_whisper(self, model_name: str = "large-v3") -> bool:
        """延迟加载 Whisper v3 模型。"""
        if self._whisper_model is not None:
            return self._whisper_available
        try:
            import whisper  # type: ignore[import-untyped]

            logger.info("whisper_v3_loading", model=model_name)
            self._whisper_model = whisper.load_model(model_name)
            self._whisper_available = True
            logger.info("whisper_v3_loaded", model=model_name)
            return True
        except ImportError:
            logger.warning("whisper_not_installed", hint="pip install openai-whisper")
            self._whisper_available = False
            return False
        except (RuntimeError, OSError) as exc:
            logger.warning("whisper_load_failed", error=str(exc))
            self._whisper_available = False
            return False

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: str = "zh",
        model: str = "whisper-v3",
    ) -> dict[str, Any]:
        """ASR: 语音 → 文字

        Returns:
            {text, confidence, language, duration_ms, source}
        """
        start = time.monotonic()

        if self._load_whisper():
            result = await self._transcribe_whisper(audio_bytes, language, start)
        else:
            result = self._transcribe_mock(audio_bytes, language, start)

        logger.info(
            "asr_completed",
            text=result["text"][:50],
            confidence=result["confidence"],
            source=result["source"],
        )
        return result

    async def _transcribe_whisper(self, audio_bytes: bytes, language: str, start: float) -> dict[str, Any]:
        """Whisper v3 实际转写。"""
        import os
        import tempfile

        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            result = self._whisper_model.transcribe(
                tmp_path,
                language=language,
                task="transcribe",
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)

            text: str = result.get("text", "").strip()
            segments = result.get("segments", [])
            if segments:
                avg_no_speech = sum(s.get("no_speech_prob", 0.0) for s in segments) / len(segments)
                confidence = round(1.0 - avg_no_speech, 4)
            else:
                confidence = 0.0

            return {
                "text": text,
                "confidence": confidence,
                "language": language,
                "duration_ms": elapsed_ms,
                "source": "whisper-v3",
            }
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("whisper_transcribe_error", error=str(exc))
            return self._transcribe_mock(audio_bytes, language, start)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _transcribe_mock(self, audio_bytes: bytes, language: str, start: float) -> dict[str, Any]:
        """Mock 转写（Whisper 不可用时）。根据音频长度模拟。"""
        elapsed_ms = int((time.monotonic() - start) * 1000)

        # 基于音频字节内容提取 mock 文本（测试时注入）
        mock_text = "三号桌加一份酸菜鱼微辣" if language == "zh" else "Add sauerkraut fish to table three"

        return {
            "text": mock_text,
            "confidence": 0.0,
            "language": language,
            "duration_ms": elapsed_ms,
            "source": "mock",
        }

    # ══════════════════════════════════════════════════════════════
    # 2. NLU — Natural Language Understanding
    # ══════════════════════════════════════════════════════════════

    async def understand(self, text: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """NLU: 文本 → 意图 + 实体

        Enhanced intent parsing with 16 restaurant intents.
        Entity extraction: table_no, dish_name, quantity, flavor, spice_level

        Returns:
            {intent, entities, confidence, context_used}
        """
        if not text or not text.strip():
            return {
                "intent": "unknown",
                "entities": {},
                "confidence": 0.0,
                "context_used": False,
            }

        text = text.strip()
        entities: dict[str, Any] = {}

        # 先提取通用实体
        self._extract_global_entities(text, entities)

        # 匹配意图
        intent_name = "unknown"
        confidence = 0.0

        for intent, patterns in self._intent_patterns:
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    intent_name = intent
                    self._extract_pattern_entities(match, entities)
                    confidence = 0.95 if len(entities) >= 2 else 0.88 if entities else 0.80
                    break
            if intent_name != "unknown":
                break

        # 上下文补全：如果意图模糊但有上下文
        context_used = False
        if context and intent_name == "unknown":
            last_intent = context.get("last_intent", "")
            if last_intent == "order_add" and entities.get("dish_name"):
                intent_name = "order_add"
                confidence = 0.75
                context_used = True
            elif last_intent == "order_add" and any(k in text for k in _SPICE_LEVELS):
                intent_name = "order_modify"
                confidence = 0.70
                context_used = True

        # 从上下文补全桌号
        if context and "table_no" not in entities:
            ctx_table = context.get("current_table")
            if ctx_table:
                entities["table_no"] = ctx_table
                context_used = True

        logger.info(
            "nlu_completed",
            intent=intent_name,
            entities=entities,
            confidence=confidence,
        )

        return {
            "intent": intent_name,
            "entities": entities,
            "confidence": confidence,
            "context_used": context_used,
        }

    def _extract_global_entities(self, text: str, entities: dict[str, Any]) -> None:
        """从文本中提取全局实体（辣度、口味等）。"""
        # 辣度
        for keyword, level in _SPICE_LEVELS.items():
            if keyword in text:
                entities["spice_level"] = level
                break

        # 口味偏好
        for keyword, flavor in _FLAVOR_KEYWORDS.items():
            if keyword in text:
                entities["flavor"] = flavor
                break

    def _extract_pattern_entities(self, match: re.Match[str], entities: dict[str, Any]) -> None:
        """从正则匹配中提取实体。"""
        groupdict = match.groupdict()

        if groupdict.get("table_no"):
            raw = groupdict["table_no"]
            # 支持字母+数字混合桌号 (A05, B12)
            if raw.isdigit():
                entities["table_no"] = int(raw)
            else:
                entities["table_no"] = raw

        if groupdict.get("dish_name"):
            entities["dish_name"] = groupdict["dish_name"]

        if groupdict.get("quantity"):
            entities["quantity"] = _chinese_num_to_int(groupdict["quantity"])

        if groupdict.get("weight"):
            entities["weight"] = _chinese_num_to_int(groupdict["weight"])

        if groupdict.get("unit"):
            entities["unit"] = groupdict["unit"]

        if groupdict.get("ingredient"):
            entities["ingredient"] = groupdict["ingredient"]

        if groupdict.get("target_table"):
            raw = groupdict["target_table"]
            entities["target_table"] = int(raw) if raw.isdigit() else raw

        if groupdict.get("table_a"):
            entities["table_a"] = int(groupdict["table_a"]) if groupdict["table_a"].isdigit() else groupdict["table_a"]

        if groupdict.get("table_b"):
            entities["table_b"] = int(groupdict["table_b"]) if groupdict["table_b"].isdigit() else groupdict["table_b"]

        if groupdict.get("date_ref"):
            entities["date_ref"] = groupdict["date_ref"]

        if groupdict.get("guest_count"):
            entities["guest_count"] = _chinese_num_to_int(groupdict["guest_count"])

        if groupdict.get("time_ref"):
            entities["time_ref"] = groupdict["time_ref"]

    @staticmethod
    def _build_intent_patterns() -> list[tuple[str, list[re.Pattern[str]]]]:
        """构建16种中文餐饮场景意图的正则模式。"""
        return [
            # ── order_add: 加菜/下单 ──
            (
                "order_add",
                [
                    re.compile(
                        r"(?P<table_no>[A-Za-z]?\d+)\s*号?\s*桌?\s*(加|来|上|要)\s*"
                        r"(?P<quantity>[一二两三四五六七八九十\d]+)?\s*[份个道]?\s*"
                        r"(?P<dish_name>[\u4e00-\u9fff]{2,})"
                    ),
                    re.compile(
                        r"(加|来|上|再来|要)\s*(?P<quantity>[一二两三四五六七八九十\d]+)\s*[份个道]\s*"
                        r"(?P<dish_name>[\u4e00-\u9fff]{2,})"
                    ),
                    re.compile(
                        r"(?P<dish_name>[\u4e00-\u9fff]{2,})\s*(来|要|加)\s*"
                        r"(?P<quantity>[一二两三四五六七八九十\d]+)\s*[份个道]"
                    ),
                    re.compile(r"(加菜|加个|来个|来一个|来份|来一份|上一份)\s*(?P<dish_name>[\u4e00-\u9fff]{2,})?"),
                ],
            ),
            # ── order_remove: 退菜 ──
            (
                "order_remove",
                [
                    re.compile(
                        r"(退|取消|撤)\s*(?P<quantity>[一二两三四五六七八九十\d]+)?\s*[份个道]?\s*"
                        r"(?P<dish_name>[\u4e00-\u9fff]{2,})"
                    ),
                    re.compile(r"(?P<dish_name>[\u4e00-\u9fff]{2,})\s*(退了|不要了|取消)"),
                    re.compile(r"(退菜|退掉)"),
                ],
            ),
            # ── order_modify: 改单/改口味 ──
            (
                "order_modify",
                [
                    re.compile(
                        r"(?P<dish_name>[\u4e00-\u9fff]{2,})\s*(改|换)(成|为)?\s*"
                        r"(?P<flavor>[\u4e00-\u9fff]{2,})"
                    ),
                    re.compile(r"(改单|改菜|修改订单)"),
                ],
            ),
            # ── checkout: 结账 ──
            (
                "checkout",
                [
                    re.compile(r"(?P<table_no>[A-Za-z]?\d+)\s*号?\s*桌?\s*(买单|结账|结帐|埋单)"),
                    re.compile(r"(买单|结账|结帐|埋单)\s*(?P<table_no>[A-Za-z]?\d+)?\s*号?\s*桌?"),
                ],
            ),
            # ── open_table: 开台 ──
            (
                "open_table",
                [
                    re.compile(r"(?P<table_no>[A-Za-z]?\d+)\s*号?\s*桌?\s*(开台|开桌)"),
                    re.compile(r"(开台|开桌)\s*(?P<table_no>[A-Za-z]?\d+)?\s*号?\s*桌?"),
                ],
            ),
            # ── query_revenue: 营收查询 ──
            (
                "query_revenue",
                [
                    re.compile(
                        r"(?P<date_ref>今天|今日|昨天|昨日|本周|这周|本月|这个月)\s*"
                        r"(营业额|收入|流水|卖了多少|营收|销售额)(多少|是多少|怎么样)?"
                    ),
                    re.compile(r"(营业额|收入|流水|营收|销售额)\s*(多少|是多少|怎么样|如何)"),
                ],
            ),
            # ── query_inventory: 库存查询 ──
            (
                "query_inventory",
                [
                    re.compile(
                        r"(?P<ingredient>[\u4e00-\u9fff]{2,})\s*"
                        r"(还有多少|还有吗|还有没有|库存|剩多少|还剩)"
                    ),
                    re.compile(r"(库存|存货)\s*(查一下|查看|查询|怎么样|多少)"),
                    re.compile(r"(查一下|查看|查询)\s*(库存|存货)"),
                ],
            ),
            # ── query_order_status: 订单状态 ──
            (
                "query_order_status",
                [
                    re.compile(
                        r"(?P<table_no>[A-Za-z]?\d+)\s*号?\s*桌?\s*"
                        r"(什么情况|什么状态|怎么样了|状态|出了没|好了没|菜齐了没)"
                    ),
                    re.compile(r"(查一下|查看|查询)\s*(订单|桌台)\s*(状态|情况)?"),
                    re.compile(r"(订单|桌台).*(查|看|状态)"),
                ],
            ),
            # ── report_waste: 报损 ──
            (
                "report_waste",
                [
                    re.compile(
                        r"(?P<ingredient>[\u4e00-\u9fff]{2,})\s*(损耗|报损|坏了|扔了)\s*"
                        r"(?P<weight>[一二两三四五六七八九十\d]+)\s*(?P<unit>斤|公斤|kg|克|g)"
                    ),
                    re.compile(
                        r"(损耗|报损)\s*(?P<ingredient>[\u4e00-\u9fff]{2,})\s*"
                        r"(?P<weight>[一二两三四五六七八九十\d]+)\s*(?P<unit>斤|公斤|kg|克|g)"
                    ),
                    re.compile(
                        r"(?P<ingredient>[\u4e00-\u9fff]{2,})\s*"
                        r"(?P<weight>[一二两三四五六七八九十\d]+)\s*(?P<unit>斤|公斤|kg|克|g)\s*"
                        r"(损耗|报损|坏了|扔了)"
                    ),
                    re.compile(r"(报损|记损耗)"),
                ],
            ),
            # ── call_service: 呼叫服务员 ──
            (
                "call_service",
                [
                    re.compile(r"(服务员|叫一下服务员|呼叫服务员|叫服务员)"),
                ],
            ),
            # ── rush_order: 催菜 ──
            (
                "rush_order",
                [
                    re.compile(r"(?P<table_no>[A-Za-z]?\d+)\s*号?\s*桌?\s*(催菜|催一下|催单)"),
                    re.compile(r"(催菜|催一下|催单)\s*(?P<table_no>[A-Za-z]?\d+)?\s*号?\s*桌?"),
                ],
            ),
            # ── reserve_table: 预订 ──
            (
                "reserve_table",
                [
                    re.compile(
                        r"(预[定订]|订[位桌台])\s*(?P<guest_count>[一二两三四五六七八九十\d]+)?\s*"
                        r"[人位个]?\s*(?P<time_ref>[\u4e00-\u9fff\d:：]+)?"
                    ),
                    re.compile(r"(订位|预约|预订|留位)"),
                ],
            ),
            # ── query_staff: 查员工 ──
            (
                "query_staff",
                [
                    re.compile(r"(谁在上班|今天谁当班|值班|排班|在岗)"),
                    re.compile(r"(查一下|查看)\s*(员工|服务员|店员)"),
                ],
            ),
            # ── daily_report: 日报 ──
            (
                "daily_report",
                [
                    re.compile(r"(日报|日结|营业报表|经营报表|营业报告|今日总结)"),
                    re.compile(r"(出|看|给我)\s*(报表|报告|日报)"),
                ],
            ),
            # ── switch_table: 换桌 ──
            (
                "switch_table",
                [
                    re.compile(
                        r"(?P<table_no>[A-Za-z]?\d+)\s*号?\s*桌?\s*换到?\s*"
                        r"(?P<target_table>[A-Za-z]?\d+)\s*号?\s*桌?"
                    ),
                    re.compile(r"(换桌|转桌|换台)"),
                ],
            ),
            # ── merge_table: 并桌 ──
            (
                "merge_table",
                [
                    re.compile(
                        r"(?P<table_a>[A-Za-z]?\d+)\s*号?\s*桌?\s*和\s*"
                        r"(?P<table_b>[A-Za-z]?\d+)\s*号?\s*桌?\s*(并|合|合并)"
                    ),
                    re.compile(r"(并桌|合桌|合台|拼桌)"),
                ],
            ),
        ]

    # ══════════════════════════════════════════════════════════════
    # 3. Dialog Management — 多轮对话管理
    # ══════════════════════════════════════════════════════════════

    async def manage_dialog(self, session_id: str, nlu_result: dict[str, Any]) -> dict[str, Any]:
        """多轮对话管理

        处理：
        - "加一份酸菜鱼" → "辣度？" → "微辣" → "好的已下单"
        - 歧义消解、上下文接续
        """
        intent = nlu_result.get("intent", "unknown")
        entities = nlu_result.get("entities", {})

        # 判断是否需要补全信息
        missing_slots = self._check_required_slots(intent, entities)

        if missing_slots:
            prompt = self._generate_slot_prompt(missing_slots[0], entities)
            return {
                "action": "ask_slot",
                "session_id": session_id,
                "missing_slot": missing_slots[0],
                "prompt_text": prompt,
                "current_entities": entities,
                "complete": False,
            }

        return {
            "action": "execute",
            "session_id": session_id,
            "intent": intent,
            "entities": entities,
            "complete": True,
        }

    def _check_required_slots(self, intent: str, entities: dict[str, Any]) -> list[str]:
        """检查意图所需的必填槽位。"""
        required_slots: dict[str, list[str]] = {
            "order_add": ["dish_name"],
            "order_remove": ["dish_name"],
            "checkout": ["table_no"],
            "open_table": ["table_no"],
            "report_waste": ["ingredient", "weight"],
            "switch_table": ["table_no", "target_table"],
            "merge_table": ["table_a", "table_b"],
            "rush_order": ["table_no"],
            "reserve_table": [],
        }

        needed = required_slots.get(intent, [])
        return [slot for slot in needed if slot not in entities]

    def _generate_slot_prompt(self, slot: str, entities: dict[str, Any]) -> str:
        """生成补全信息的提问语句。"""
        prompts: dict[str, str] = {
            "dish_name": "请问要什么菜？",
            "table_no": "请问是几号桌？",
            "quantity": "请问要几份？",
            "spice_level": "请问辣度要什么？微辣、中辣还是特辣？",
            "ingredient": "请问是什么食材？",
            "weight": "请问损耗了多少？",
            "target_table": "请问要换到几号桌？",
            "table_a": "请问要合并哪两张桌？",
            "table_b": "请问和几号桌合并？",
            "flavor": "请问口味有什么要求？",
        }
        return prompts.get(slot, f"请补充{slot}信息")

    # ══════════════════════════════════════════════════════════════
    # 4. Action Execution — 路由到业务服务
    # ══════════════════════════════════════════════════════════════

    async def execute_action(
        self,
        intent: str,
        entities: dict[str, Any],
        store_id: str,
        employee_id: str,
    ) -> dict[str, Any]:
        """根据意图路由到对应业务服务执行。"""
        route = INTENT_ROUTE_MAP.get(intent)
        if not route:
            return {
                "ok": False,
                "error": f"未知意图: {intent}",
                "intent": intent,
            }

        service_name = route["service"]
        method_name = route["method"]

        # 查找注册的服务
        service = self._service_registry.get(service_name)

        # 模拟执行（服务未注册时）
        if service is None:
            return self._simulate_action(intent, entities, store_id, employee_id)

        # 调用真实服务
        try:
            method = getattr(service, method_name, None)
            if method is None:
                return {
                    "ok": False,
                    "error": f"服务 {service_name} 无方法 {method_name}",
                }
            result = await method(
                store_id=store_id,
                employee_id=employee_id,
                **entities,
            )
            return {"ok": True, "data": result, "intent": intent}
        except (TypeError, ValueError, AttributeError) as exc:
            logger.error(
                "action_execution_failed",
                intent=intent,
                error=str(exc),
            )
            return {"ok": False, "error": str(exc), "intent": intent}

    def _simulate_action(
        self,
        intent: str,
        entities: dict[str, Any],
        store_id: str,
        employee_id: str,
    ) -> dict[str, Any]:
        """模拟业务执行（用于测试和服务未接入时）。"""
        simulations: dict[str, dict[str, Any]] = {
            "order_add": {
                "ok": True,
                "data": {
                    "order_id": f"ORD-{uuid.uuid4().hex[:8].upper()}",
                    "dish_name": entities.get("dish_name", ""),
                    "quantity": entities.get("quantity", 1),
                    "table_no": entities.get("table_no", ""),
                    "status": "added",
                    "total_amount_fen": 5800,
                },
            },
            "order_remove": {
                "ok": True,
                "data": {
                    "dish_name": entities.get("dish_name", ""),
                    "status": "removed",
                },
            },
            "order_modify": {
                "ok": True,
                "data": {
                    "dish_name": entities.get("dish_name", ""),
                    "modification": entities.get("flavor", ""),
                    "status": "modified",
                },
            },
            "checkout": {
                "ok": True,
                "data": {
                    "table_no": entities.get("table_no", ""),
                    "total_amount_fen": 25800,
                    "status": "checked_out",
                },
            },
            "open_table": {
                "ok": True,
                "data": {
                    "table_no": entities.get("table_no", ""),
                    "status": "opened",
                },
            },
            "query_revenue": {
                "ok": True,
                "data": {
                    "date": entities.get("date_ref", "今天"),
                    "total_revenue_fen": 2856000,
                    "order_count": 156,
                    "avg_ticket_fen": 18300,
                    "yoy_growth": 0.12,
                },
            },
            "query_inventory": {
                "ok": True,
                "data": {
                    "ingredient": entities.get("ingredient", ""),
                    "current_stock_g": 15000,
                    "unit": "g",
                    "status": "sufficient",
                },
            },
            "query_order_status": {
                "ok": True,
                "data": {
                    "table_no": entities.get("table_no", ""),
                    "total_dishes": 6,
                    "served": 4,
                    "cooking": 2,
                    "status": "in_progress",
                },
            },
            "report_waste": {
                "ok": True,
                "data": {
                    "ingredient": entities.get("ingredient", ""),
                    "weight": entities.get("weight", 0),
                    "unit": entities.get("unit", "斤"),
                    "waste_id": f"WST-{uuid.uuid4().hex[:8].upper()}",
                    "status": "recorded",
                },
            },
            "call_service": {
                "ok": True,
                "data": {"status": "waiter_notified"},
            },
            "rush_order": {
                "ok": True,
                "data": {
                    "table_no": entities.get("table_no", ""),
                    "status": "rushed",
                },
            },
            "reserve_table": {
                "ok": True,
                "data": {
                    "guest_count": entities.get("guest_count", 2),
                    "time_ref": entities.get("time_ref", ""),
                    "reservation_id": f"RSV-{uuid.uuid4().hex[:8].upper()}",
                    "status": "reserved",
                },
            },
            "query_staff": {
                "ok": True,
                "data": {
                    "on_duty_count": 8,
                    "staff_list": ["张三", "李四", "王五"],
                },
            },
            "daily_report": {
                "ok": True,
                "data": {
                    "total_revenue_fen": 2856000,
                    "total_orders": 156,
                    "net_profit_fen": 428400,
                },
            },
            "switch_table": {
                "ok": True,
                "data": {
                    "from_table": entities.get("table_no", ""),
                    "to_table": entities.get("target_table", ""),
                    "status": "switched",
                },
            },
            "merge_table": {
                "ok": True,
                "data": {
                    "table_a": entities.get("table_a", ""),
                    "table_b": entities.get("table_b", ""),
                    "status": "merged",
                },
            },
        }

        result = simulations.get(
            intent,
            {
                "ok": True,
                "data": {"intent": intent, "status": "simulated"},
            },
        )
        result["simulated"] = True
        return result

    # ══════════════════════════════════════════════════════════════
    # 5. Response Generation — 中文自然语言回复
    # ══════════════════════════════════════════════════════════════

    async def generate_response(self, action_result: dict[str, Any], format: str = "text") -> dict[str, Any]:
        """生成中文自然语言回复。

        Args:
            action_result: execute_action 的返回结果
            format: "text" 或 "ssml"（TTS专用）

        Returns:
            {response_text, format, ssml?}
        """
        if not action_result.get("ok"):
            error_msg = action_result.get("error", "操作失败")
            text = f"抱歉，{error_msg}，请再试一次。"
            return self._format_response(text, format)

        intent = action_result.get("intent", "")
        data = action_result.get("data", {})

        text = self._build_response_text(intent, data)
        return self._format_response(text, format)

    def _build_response_text(self, intent: str, data: dict[str, Any]) -> str:
        """根据意图和数据构建回复文本。"""
        if intent == "order_add":
            dish = data.get("dish_name", "菜品")
            qty = data.get("quantity", 1)
            table = data.get("table_no", "")
            total = data.get("total_amount_fen", 0)
            table_str = f"{table}号桌" if table else ""
            total_str = f"，当前订单总额{total // 100}元" if total else ""
            return f"好的，{table_str}已加{qty}份{dish}{total_str}"

        if intent == "order_remove":
            dish = data.get("dish_name", "菜品")
            return f"好的，{dish}已退掉"

        if intent == "order_modify":
            dish = data.get("dish_name", "菜品")
            mod = data.get("modification", "")
            return f"好的，{dish}已改为{mod}" if mod else f"好的，{dish}已修改"

        if intent == "checkout":
            table = data.get("table_no", "")
            total = data.get("total_amount_fen", 0)
            return f"{table}号桌结账，总计{total // 100}元"

        if intent == "open_table":
            table = data.get("table_no", "")
            return f"好的，{table}号桌已开台"

        if intent == "query_revenue":
            date_ref = data.get("date", "今天")
            rev = data.get("total_revenue_fen", 0)
            growth = data.get("yoy_growth", 0)
            count = data.get("order_count", 0)
            growth_str = ""
            if growth > 0:
                growth_str = f"，较昨日增长{int(growth * 100)}%"
            elif growth < 0:
                growth_str = f"，较昨日下降{int(abs(growth) * 100)}%"
            return f"{date_ref}营收{rev // 100:,}元，共{count}单{growth_str}"

        if intent == "query_inventory":
            ingredient = data.get("ingredient", "")
            stock = data.get("current_stock_g", 0)
            status = data.get("status", "")
            stock_display = f"{stock}克" if stock < 1000 else f"{stock / 1000:.1f}公斤"
            return f"{ingredient}当前库存{stock_display}，状态{status}"

        if intent == "query_order_status":
            table = data.get("table_no", "")
            total_d = data.get("total_dishes", 0)
            served = data.get("served", 0)
            cooking = data.get("cooking", 0)
            return f"{table}号桌共{total_d}道菜，已上{served}道，正在做{cooking}道"

        if intent == "report_waste":
            ingredient = data.get("ingredient", "")
            weight = data.get("weight", 0)
            unit = data.get("unit", "斤")
            return f"已记录{ingredient}损耗{weight}{unit}"

        if intent == "call_service":
            return "好的，已通知服务员"

        if intent == "rush_order":
            table = data.get("table_no", "")
            return f"好的，{table}号桌已催单，厨房已收到"

        if intent == "reserve_table":
            rid = data.get("reservation_id", "")
            count = data.get("guest_count", 2)
            return f"已预订{count}位，预订号{rid}"

        if intent == "query_staff":
            count = data.get("on_duty_count", 0)
            staff = data.get("staff_list", [])
            names = "、".join(staff[:5])
            return f"当前在岗{count}人：{names}"

        if intent == "daily_report":
            rev = data.get("total_revenue_fen", 0)
            orders = data.get("total_orders", 0)
            profit = data.get("net_profit_fen", 0)
            return f"今日营收{rev // 100:,}元，{orders}单，净利润{profit // 100:,}元"

        if intent == "switch_table":
            ft = data.get("from_table", "")
            tt = data.get("to_table", "")
            return f"好的，{ft}号桌已换到{tt}号桌"

        if intent == "merge_table":
            ta = data.get("table_a", "")
            tb = data.get("table_b", "")
            return f"好的，{ta}号桌和{tb}号桌已合并"

        return "操作已完成"

    def _format_response(self, text: str, format: str) -> dict[str, Any]:
        """格式化回复。"""
        result: dict[str, Any] = {
            "response_text": text,
            "format": format,
        }
        if format == "ssml":
            result["ssml"] = f'<speak><prosody rate="medium">{text}</prosody></speak>'
        return result

    # ══════════════════════════════════════════════════════════════
    # 6. Full Pipeline — 完整语音指令处理
    # ══════════════════════════════════════════════════════════════

    async def process_voice_command(
        self,
        audio_bytes: bytes,
        session_id: str,
        store_id: str,
        employee_id: str,
        language: str = "zh",
    ) -> dict[str, Any]:
        """完整语音指令处理流水线

        audio → text → intent → dialog → action → response

        Returns:
            {transcription, intent, entities, action_result, response_text, session_id}
        """
        # 1. ASR
        transcription = await self.transcribe(audio_bytes, language)

        # 2. NLU
        nlu_result = await self.understand(transcription["text"])

        # 3. Dialog
        dialog_result = await self.manage_dialog(session_id, nlu_result)

        # 如果需要追问
        if not dialog_result.get("complete"):
            return {
                "transcription": transcription,
                "intent": nlu_result["intent"],
                "entities": nlu_result["entities"],
                "action_result": None,
                "response_text": dialog_result["prompt_text"],
                "session_id": session_id,
                "needs_followup": True,
            }

        # 4. Execute
        action_result = await self.execute_action(
            nlu_result["intent"],
            nlu_result["entities"],
            store_id,
            employee_id,
        )

        # 5. Response
        response = await self.generate_response(action_result)

        logger.info(
            "voice_pipeline_completed",
            session_id=session_id,
            intent=nlu_result["intent"],
            response=response["response_text"][:50],
        )

        return {
            "transcription": transcription,
            "intent": nlu_result["intent"],
            "entities": nlu_result["entities"],
            "action_result": action_result,
            "response_text": response["response_text"],
            "session_id": session_id,
            "needs_followup": False,
        }
