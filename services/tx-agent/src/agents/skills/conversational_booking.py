"""对话式预订 Agent — P1 | 云端

对标: Resy (AI推荐) + 客如云 (AI五大智能体)

自然语言预订能力:
  1. parse_booking_intent  — 中文意图解析 (日期/时间/人数/偏好)
  2. check_availability    — 可用性查询
  3. generate_response     — 自然语言回复生成
  4. handle_modification   — 预订修改处理
  5. multi_turn_conversation — 多轮对话状态管理

解决痛点: 73%的预订发生在非营业时间，Bot可7×24小时自动处理。
"""
import re
import uuid
from datetime import date, datetime, timedelta
from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger(__name__)

# ── 中文日期/时间解析映射 ──

WEEKDAY_MAP = {
    "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6, "周天": 6,
    "星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3, "星期五": 4, "星期六": 5, "星期日": 6, "星期天": 6,
    "下周一": 0, "下周二": 1, "下周三": 2, "下周四": 3, "下周五": 4, "下周六": 5, "下周日": 6,
}

RELATIVE_DATE_MAP = {
    "今天": 0, "今日": 0, "今晚": 0,
    "明天": 1, "明日": 1, "明晚": 1,
    "后天": 2, "后日": 2,
    "大后天": 3,
}

TIME_PERIOD_MAP = {
    "中午": "12:00", "午餐": "12:00", "午饭": "12:00",
    "晚上": "18:00", "晚餐": "18:00", "晚饭": "18:00",
    "下午": "14:00",
}

ZONE_KEYWORDS = {
    "包厢": "private_room", "包间": "private_room",
    "靠窗": "window", "窗边": "window",
    "大厅": "hall", "散座": "hall",
    "露台": "terrace", "户外": "terrace",
    "安静": "quiet",
}

# ── 模拟可用性 ──

MOCK_AVAILABLE_SLOTS = {
    "private_room": ["11:30", "12:00", "17:30", "18:00", "19:30"],
    "window": ["11:30", "12:00", "12:30", "17:00", "17:30", "18:30", "19:00", "20:00"],
    "hall": ["11:00", "11:30", "12:00", "12:30", "13:00", "17:00", "17:30", "18:00", "18:30", "19:00", "19:30", "20:00"],
}

MOCK_ROOMS = {
    "private_room": ["梅花厅", "牡丹厅", "芙蓉厅", "兰花厅", "国宾厅"],
    "window": ["A1靠窗", "A3靠窗", "B2靠窗", "C1靠窗"],
}


class ConversationalBookingAgent(SkillAgent):
    """对话式预订 Agent — 中文自然语言多轮对话预订"""

    agent_id = "conversational_booking"
    agent_name = "对话式预订"
    description = "自然语言预订、多轮对话、意图解析、可用性查询、修改取消"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "parse_booking_intent",
            "check_availability",
            "generate_response",
            "handle_modification",
            "multi_turn_conversation",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "parse_booking_intent": self._parse_intent,
            "check_availability": self._check_availability,
            "generate_response": self._generate_response,
            "handle_modification": self._handle_modification,
            "multi_turn_conversation": self._multi_turn,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    # ─────────────────────────────────────────────
    # 1. 意图解析
    # ─────────────────────────────────────────────

    async def _parse_intent(self, params: dict[str, Any]) -> AgentResult:
        """从中文自然语言中提取预订意图"""
        message = params.get("message", "")
        today = date.today()

        parsed: dict[str, Any] = {
            "date": None,
            "time": None,
            "party_size": None,
            "zone_preference": None,
            "special_requests": [],
        }
        missing: list[str] = []

        # 解析日期
        for keyword, delta in RELATIVE_DATE_MAP.items():
            if keyword in message:
                parsed["date"] = str(today + timedelta(days=delta))
                break

        if parsed["date"] is None:
            for keyword, weekday in WEEKDAY_MAP.items():
                if keyword in message:
                    days_ahead = weekday - today.weekday()
                    if "下周" in keyword:
                        days_ahead += 7
                    elif days_ahead <= 0:
                        days_ahead += 7
                    parsed["date"] = str(today + timedelta(days=days_ahead))
                    break

        # 解析时间
        # 精确时间: "6点", "6点半", "18:00", "下午5点"
        time_match = re.search(r"(\d{1,2})[点时:](\d{2}|半)?", message)
        if time_match:
            hour = int(time_match.group(1))
            minute_raw = time_match.group(2)
            minute = 30 if minute_raw == "半" else (int(minute_raw) if minute_raw else 0)
            # 自动补 PM: 如果是 1-8 点且说了"晚上"或没说具体，默认下午
            if hour < 10 and ("晚" in message or "下午" in message or hour <= 8):
                hour += 12
            parsed["time"] = f"{hour:02d}:{minute:02d}"
        else:
            for keyword, default_time in TIME_PERIOD_MAP.items():
                if keyword in message:
                    parsed["time"] = default_time
                    break

        # 解析人数
        size_match = re.search(r"(\d+)\s*[个位人]", message)
        if size_match:
            parsed["party_size"] = int(size_match.group(1))

        # 解析座位偏好
        for keyword, zone in ZONE_KEYWORDS.items():
            if keyword in message:
                parsed["zone_preference"] = zone
                break

        # 解析特殊要求
        special_keywords = {
            "生日": "生日聚会", "蛋糕": "需准备蛋糕位",
            "儿童": "需要儿童椅", "轮椅": "需无障碍通道",
            "忌辣": "忌辣", "忌海鲜": "忌海鲜", "素食": "素食",
            "安静": "偏好安静环境",
        }
        for kw, desc in special_keywords.items():
            if kw in message:
                parsed["special_requests"].append(desc)

        # 判断缺失字段
        if not parsed["date"]:
            missing.append("date")
        if not parsed["time"]:
            missing.append("time")
        if not parsed["party_size"]:
            missing.append("party_size")

        confidence = 1.0 - len(missing) * 0.2

        return AgentResult(
            success=True, action="parse_booking_intent",
            data={
                "parsed_intent": parsed,
                "missing_fields": missing,
                "original_message": message,
                "parse_confidence": round(confidence, 2),
            },
            reasoning=f"解析出 {sum(1 for v in parsed.values() if v)} 个字段，缺失 {missing}",
            confidence=confidence,
        )

    # ─────────────────────────────────────────────
    # 2. 可用性查询
    # ─────────────────────────────────────────────

    async def _check_availability(self, params: dict[str, Any]) -> AgentResult:
        """检查指定日期/时间/偏好的可用性"""
        target_date = params.get("date", str(date.today() + timedelta(days=1)))
        target_time = params.get("time", "18:00")
        party_size = params.get("party_size", 2)
        zone = params.get("zone_preference", "hall")

        slots = MOCK_AVAILABLE_SLOTS.get(zone, MOCK_AVAILABLE_SLOTS["hall"])
        available = target_time in slots

        # 查找替代时段
        alternatives: list[dict[str, str]] = []
        if not available:
            for s in slots:
                sh = int(s.split(":")[0])
                th = int(target_time.split(":")[0])
                if abs(sh - th) <= 2:  # 前后2小时内
                    alternatives.append({"time": s, "zone": zone})
            if not alternatives and zone == "private_room":
                for s in MOCK_AVAILABLE_SLOTS["window"]:
                    sh = int(s.split(":")[0])
                    th = int(target_time.split(":")[0])
                    if abs(sh - th) <= 1:
                        alternatives.append({"time": s, "zone": "window", "note": "靠窗位（包厢已满）"})

        # 分配具体房间/桌号
        suggested_table = None
        if available and zone in MOCK_ROOMS:
            rooms = MOCK_ROOMS[zone]
            idx = hash(target_date + target_time) % len(rooms)
            suggested_table = rooms[idx]
        elif available:
            suggested_table = f"大厅{'A' if party_size <= 4 else 'B'}{hash(target_time) % 8 + 1}"

        return AgentResult(
            success=True, action="check_availability",
            data={
                "available": available,
                "date": target_date,
                "time": target_time,
                "party_size": party_size,
                "zone_preference": zone,
                "suggested_table": suggested_table,
                "alternatives": alternatives[:3],
                "wait_estimate_min": 0 if available else 15,
            },
            reasoning=f"{'可用' if available else '不可用'}，{len(alternatives)} 个替代方案",
            confidence=0.88,
        )

    # ─────────────────────────────────────────────
    # 3. 回复生成
    # ─────────────────────────────────────────────

    async def _generate_response(self, params: dict[str, Any]) -> AgentResult:
        """生成自然、温暖的中文回复"""
        context = params.get("context", "new")  # new/modify/cancel
        available = params.get("available", True)
        intent = params.get("intent", {})
        alternatives = params.get("alternatives", [])
        suggested_table = params.get("suggested_table", "")
        missing_fields = params.get("missing_fields", [])

        response_text = ""
        next_action = "done"
        requires_input: list[str] = []

        if missing_fields:
            # 需要更多信息
            questions = {
                "date": "请问想订哪天的呢？",
                "time": "请问几点到店？",
                "party_size": "请问几位用餐？有什么座位偏好吗？（包厢/靠窗/大厅）",
            }
            q_parts = [questions[f] for f in missing_fields if f in questions]
            response_text = "好的！" + " ".join(q_parts)
            next_action = "ask_info"
            requires_input = missing_fields

        elif context == "new" and available:
            # 可用 — 确认信息
            dt = intent.get("date", "")
            tm = intent.get("time", "")
            ps = intent.get("party_size", "")
            zone = intent.get("zone_preference", "")
            zone_label = {"private_room": "包厢", "window": "靠窗", "hall": "大厅"}.get(zone, "")

            response_text = (
                f"好的，{self._format_date(dt)} {tm}，{ps}位"
                f"{'，' + zone_label if zone_label else ''}"
                f"{'（' + suggested_table + '）' if suggested_table else ''}已为您预留。"
                f"\n请问预订人姓名和手机号？"
            )
            next_action = "confirm"
            requires_input = ["name", "phone"]

        elif context == "new" and not available:
            # 不可用 — 推荐替代
            if alternatives:
                alt_texts = []
                for a in alternatives[:3]:
                    note = a.get("note", "")
                    alt_texts.append(f"{a['time']}{' (' + note + ')' if note else ''}")
                response_text = (
                    f"抱歉，该时段已满。为您查到以下可用时段：\n"
                    f"{'、'.join(alt_texts)}\n"
                    f"请问选择哪个时段？或者需要换个日期？"
                )
                next_action = "suggest_alternative"
            else:
                response_text = "非常抱歉，该日期已无合适的空位。请问要换一天试试吗？"
                next_action = "suggest_alternative"

        elif context == "cancel":
            response_text = (
                "好的，您的预订已取消。如有押金将在1-3个工作日内原路退回。"
                "\n期待您下次光临！"
            )
            next_action = "done"

        return AgentResult(
            success=True, action="generate_response",
            data={
                "response_text": response_text,
                "next_action": next_action,
                "requires_input": requires_input,
            },
            reasoning=f"生成 {context} 回复，下一步 {next_action}",
            confidence=0.90,
        )

    # ─────────────────────────────────────────────
    # 4. 修改处理
    # ─────────────────────────────────────────────

    async def _handle_modification(self, params: dict[str, Any]) -> AgentResult:
        """解析并处理预订修改请求"""
        message = params.get("message", "")
        reservation_id = params.get("reservation_id", "")

        mod_type = "unknown"
        new_values: dict[str, Any] = {}
        response = ""

        # 时间修改
        time_match = re.search(r"改到?(\d{1,2})[点时:](\d{2}|半)?", message)
        if time_match:
            h = int(time_match.group(1))
            m_raw = time_match.group(2)
            m = 30 if m_raw == "半" else (int(m_raw) if m_raw else 0)
            if h < 10:
                h += 12
            mod_type = "time_change"
            new_values["time"] = f"{h:02d}:{m:02d}"
            response = f"好的，已将您的预订时间改为 {new_values['time']}。其他信息不变。"

        # 人数修改
        size_match = re.search(r"[加改](\d+)[个位人]|(\d+)[个位人]", message)
        if size_match and "加" in message:
            add = int(size_match.group(1) or size_match.group(2))
            mod_type = "party_size_increase"
            new_values["party_size_delta"] = add
            response = f"好的，已为您增加 {add} 位。我确认一下桌位是否够坐..."
        elif size_match:
            new_size = int(size_match.group(1) or size_match.group(2))
            mod_type = "party_size_change"
            new_values["party_size"] = new_size
            response = f"好的，已将人数改为 {new_size} 位。"

        # 取消
        if "取消" in message or "不来了" in message or "不去了" in message:
            mod_type = "cancel"
            response = "确认取消您的预订吗？如有押金将原路退回。回复'确认'取消。"

        # 日期修改
        for keyword, delta in RELATIVE_DATE_MAP.items():
            if keyword in message and "改" in message:
                mod_type = "date_change"
                new_values["date"] = str(date.today() + timedelta(days=delta))
                response = f"好的，已将预订日期改为 {new_values['date']}。"
                break

        if mod_type == "unknown":
            response = "抱歉，我没太理解您要修改什么。您可以说'改到7点'、'加2个人'或'取消预订'。"

        return AgentResult(
            success=True, action="handle_modification",
            data={
                "modification_type": mod_type,
                "new_values": new_values,
                "feasible": mod_type != "unknown",
                "response_text": response,
                "reservation_id": reservation_id,
            },
            reasoning=f"修改类型: {mod_type}",
            confidence=0.85 if mod_type != "unknown" else 0.3,
        )

    # ─────────────────────────────────────────────
    # 5. 多轮对话管理
    # ─────────────────────────────────────────────

    async def _multi_turn(self, params: dict[str, Any]) -> AgentResult:
        """管理多轮对话状态，逐步收集预订信息"""
        history: list[dict[str, str]] = params.get("conversation_history", [])
        new_message = params.get("new_message", "")
        collected: dict[str, Any] = params.get("collected_info", {})

        # 解析新消息中的信息
        parse_result = await self._parse_intent({"message": new_message})
        parsed = parse_result.data.get("parsed_intent", {})

        # 合并到已收集信息
        if parsed.get("date") and not collected.get("date"):
            collected["date"] = parsed["date"]
        if parsed.get("time") and not collected.get("time"):
            collected["time"] = parsed["time"]
        if parsed.get("party_size") and not collected.get("party_size"):
            collected["party_size"] = parsed["party_size"]
        if parsed.get("zone_preference") and not collected.get("zone_preference"):
            collected["zone_preference"] = parsed["zone_preference"]
        if parsed.get("special_requests"):
            existing = collected.get("special_requests", [])
            collected["special_requests"] = list(set(existing + parsed["special_requests"]))

        # 检查是否在提供姓名和手机号
        name_match = re.search(r"([^\d\s]{2,4}(?:先生|女士|总|经理))", new_message)
        if name_match and not collected.get("name"):
            collected["name"] = name_match.group(1)
        phone_match = re.search(r"1[3-9]\d{9}", new_message)
        if phone_match and not collected.get("phone"):
            collected["phone"] = phone_match.group(0)

        # 判断状态
        core_fields = ["date", "time", "party_size"]
        core_missing = [f for f in core_fields if not collected.get(f)]
        contact_missing = [f for f in ["name", "phone"] if not collected.get(f)]

        if not core_missing and not contact_missing:
            # 全部收集完成 — 生成确认
            code = f"TX-{date.today().strftime('%m%d')}-{str(uuid.uuid4())[:3].upper()}"
            zone_label = {
                "private_room": "包厢", "window": "靠窗", "hall": "大厅"
            }.get(collected.get("zone_preference", ""), "")

            phone_masked = collected["phone"][:3] + "****" + collected["phone"][-4:]

            response = (
                f"✅ 预订确认！\n"
                f"📅 {self._format_date(collected['date'])} {collected['time']}\n"
                f"👥 {collected['party_size']}位"
                f"{' · ' + zone_label if zone_label else ''}\n"
                f"📱 {collected['name']} {phone_masked}\n"
                f"🔖 确认码: {code}\n\n"
                f"我们会在到店前2小时发送提醒。期待您的光临！"
            )
            state = "completed"
            booking_ready = True

        elif not core_missing and contact_missing:
            # 核心信息齐全，需要联系方式
            response = (
                f"好的，{self._format_date(collected.get('date', ''))} "
                f"{collected.get('time', '')}，{collected.get('party_size', '')}位"
                f"{'，' + collected.get('zone_preference', '') if collected.get('zone_preference') else ''}"
                f"已为您预留。\n请问预订人姓名和手机号？"
            )
            state = "collecting"
            booking_ready = False

        else:
            # 需要更多核心信息
            gen_result = await self._generate_response({
                "context": "new",
                "available": True,
                "intent": collected,
                "missing_fields": core_missing,
            })
            response = gen_result.data.get("response_text", "请告诉我更多预订信息。")
            state = "collecting"
            booking_ready = False

        return AgentResult(
            success=True, action="multi_turn_conversation",
            data={
                "response": response,
                "collected_info": collected,
                "conversation_state": state,
                "booking_ready": booking_ready,
                "turn_count": len(history) + 1,
            },
            reasoning=f"第 {len(history) + 1} 轮，状态 {state}，"
                      f"已收集 {sum(1 for v in collected.values() if v)}/{len(core_fields) + 2} 个字段",
            confidence=0.88,
        )

    # ── 辅助方法 ──

    @staticmethod
    def _format_date(date_str: str) -> str:
        """将日期字符串格式化为友好中文"""
        if not date_str:
            return ""
        today = date.today()
        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            return date_str
        delta = (d - today).days
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        wd = weekdays[d.weekday()]
        if delta == 0:
            return f"今天({wd})"
        if delta == 1:
            return f"明天({wd})"
        if delta == 2:
            return f"后天({wd})"
        return f"{d.month}月{d.day}日({wd})"
