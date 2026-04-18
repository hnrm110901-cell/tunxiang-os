"""
HRAssistantAgent —— 员工数字人 HR 助手主类

流水线：
  1. 意图识别（规则优先，miss → LLM tool selection）
  2. 槽位提取（月份/周/课程 id 等）
  3. 权限 / 二次确认门槛
  4. 工具执行（强制注入 current_user_id）
  5. 结果格式化
  6. 上下文持久化
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import structlog

from .context_manager import ConversationContext, publish_to_memory_bus
from .intent_classifier import (
    INTENT_RULES,
    classify_intent,
    extract_month_slot,
    extract_week_slot,
)
from .response_formatter import confirm_prompt, format_tool_result
from .tools import TOOL_REGISTRY, invoke_tool, tool_schemas_for_llm

logger = structlog.get_logger()


SYSTEM_PROMPT = """你是智链OS 的 HR 数字人助手。你只能通过调用工具查询当前登录员工的数据。
- 所有查询都仅限当前员工本人，禁止跨员工查询。
- 金额默认显示"元"并保留 2 位小数。
- 涉及请假/换班/报名等写入操作必须先请用户二次确认。
- 工具失败时回复"暂时查不到 XX，稍后再试"，不要编造数据。
- 回答尽量精简，关键信息放最上面。
"""


class HRAssistantAgent:
    """HR 助手主 Agent"""

    def __init__(self):
        self._llm_gateway = None  # 懒加载

    async def _get_llm(self):
        if self._llm_gateway is None:
            try:
                from ..llm_gateway import get_llm_gateway
                self._llm_gateway = get_llm_gateway()
            except Exception as exc:
                logger.warning("hr_agent.llm_init_failed", error=str(exc))
        return self._llm_gateway

    # ───────────────────────────────────────────────────────
    # 主入口
    # ───────────────────────────────────────────────────────
    async def chat(
        self,
        *,
        current_user_id: str,
        message: str,
        conversation_id: str,
        confirm_token: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Returns:
            {
              "reply": str,
              "tool_invocations": [...],
              "suggested_actions": [...],
              "pending_confirm": {tool, args, prompt} | None,
              "ok": bool,
            }
        """
        ctx = ConversationContext(conversation_id, current_user_id)
        ctx.append("user", message)

        # 二次确认通道：用户点了"确认" → 直接执行 pending_tool
        if confirm_token:
            result = await self._execute_tool(
                current_user_id=current_user_id,
                tool_name=confirm_token["tool"],
                args=confirm_token.get("args") or {},
            )
            reply = format_tool_result(confirm_token["tool"], result)
            ctx.append("assistant", reply, tool_calls=[{"name": confirm_token["tool"], "result": result}])
            return {
                "reply": reply,
                "tool_invocations": [{"name": confirm_token["tool"], "ok": result.get("ok")}],
                "suggested_actions": [],
                "pending_confirm": None,
                "ok": result.get("ok", False),
            }

        # ── 1. 意图识别（规则优先）──
        intent_hit = classify_intent(message)
        tool_name: Optional[str] = None
        args: Dict[str, Any] = {}

        if intent_hit:
            _, tool_name = intent_hit
            args = self._extract_slots(message, tool_name)
        else:
            # 兜底：LLM tool selection
            llm_choice = await self._llm_select_tool(message, ctx)
            if llm_choice:
                tool_name = llm_choice.get("tool")
                args = llm_choice.get("args") or {}

        # ── 2. 命中失败：LLM 自然语言回答（不调工具）──
        if tool_name is None or tool_name not in TOOL_REGISTRY:
            reply = await self._fallback_reply(message, ctx)
            ctx.append("assistant", reply)
            return {
                "reply": reply,
                "tool_invocations": [],
                "suggested_actions": self._default_suggestions(),
                "pending_confirm": None,
                "ok": True,
            }

        # ── 3. 二次确认门槛（写入类）──
        tool = TOOL_REGISTRY[tool_name]
        if tool.requires_confirm:
            missing = [k for k, v in tool.parameters.items() if v.get("required") and k not in args]
            if missing:
                reply = f"请补充以下信息后我帮您提交：{', '.join(missing)}"
                ctx.append("assistant", reply)
                return {
                    "reply": reply,
                    "tool_invocations": [],
                    "suggested_actions": [],
                    "pending_confirm": None,
                    "ok": True,
                }
            prompt = confirm_prompt(tool_name, args)
            ctx.append("assistant", prompt)
            return {
                "reply": prompt,
                "tool_invocations": [],
                "suggested_actions": [],
                "pending_confirm": {"tool": tool_name, "args": args, "prompt": prompt},
                "ok": True,
            }

        # ── 4. 执行工具 ──
        result = await self._execute_tool(
            current_user_id=current_user_id, tool_name=tool_name, args=args
        )
        reply = format_tool_result(tool_name, result)
        ctx.append("assistant", reply, tool_calls=[{"name": tool_name, "args": args, "result": result}])

        # ── 5. 异步摘要推送记忆总线（不阻塞）──
        try:
            await publish_to_memory_bus(current_user_id, f"{tool_name}: {reply[:80]}")
        except Exception:
            pass

        return {
            "reply": reply,
            "tool_invocations": [{"name": tool_name, "ok": result.get("ok"), "args": args}],
            "suggested_actions": [],
            "pending_confirm": None,
            "ok": result.get("ok", True),
        }

    # ───────────────────────────────────────────────────────
    # 内部辅助
    # ───────────────────────────────────────────────────────

    def _extract_slots(self, message: str, tool_name: str) -> Dict[str, Any]:
        """从自然语言抽取工具参数"""
        args: Dict[str, Any] = {}
        if tool_name in ("get_my_salary", "get_my_social_insurance", "request_payslip_email"):
            m = extract_month_slot(message)
            if m:
                args["pay_month"] = m
        if tool_name == "get_my_schedule":
            w = extract_week_slot(message)
            if w:
                args["week"] = w
        if tool_name == "get_my_attendance":
            if "今天" in message or "今日" in message:
                args["date_range"] = "today"
            elif "本月" in message or "这个月" in message:
                args["date_range"] = "this_month"
            elif "本周" in message or "这周" in message:
                args["date_range"] = "this_week"
        return args

    async def _execute_tool(
        self, *, current_user_id: str, tool_name: str, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await invoke_tool(tool_name, current_user_id=current_user_id, **args)

    async def _llm_select_tool(
        self, message: str, ctx: ConversationContext
    ) -> Optional[Dict[str, Any]]:
        """LLM 兜底：让模型在工具列表中选一个"""
        gateway = await self._get_llm()
        if gateway is None:
            return None
        try:
            tools_desc = "\n".join(
                f"- {t['name']}: {t['description']}" for t in tool_schemas_for_llm()
            )
            prompt = (
                f"用户问：{message}\n\n"
                f"可用工具：\n{tools_desc}\n\n"
                "请判断用户意图最匹配哪个工具，并以 JSON 返回："
                '{"tool": "工具名", "args": {}}；'
                "若没有合适工具，返回 {\"tool\": null}。"
            )
            resp = await gateway.chat(
                messages=[{"role": "user", "content": prompt}],
                system=SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=200,
                user_id=ctx.employee_id,
            )
            content = (resp.get("content") or "").strip()
            # 尝试提取 JSON
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start : end + 1])
        except Exception as exc:
            logger.debug("hr_agent.llm_select_failed", error=str(exc))
        return None

    async def _fallback_reply(self, message: str, ctx: ConversationContext) -> str:
        """纯自然语言兜底（无工具命中）"""
        gateway = await self._get_llm()
        if gateway is None:
            return "我暂时没能识别您的问题，您可以试试问：我这个月工资多少？我的排班？"
        try:
            resp = await gateway.chat(
                messages=ctx.as_llm_messages() or [{"role": "user", "content": message}],
                system=SYSTEM_PROMPT + "\n若无法用工具回答，请给出礼貌的引导性提示，建议用户改问法。",
                temperature=0.3,
                max_tokens=300,
                user_id=ctx.employee_id,
            )
            return (resp.get("content") or "我暂时没能理解，请换个问法").strip()
        except Exception:
            return "我暂时没能理解，您可以试试：'我这个月工资多少？' 或 '我下周排几个班？'"

    def _default_suggestions(self) -> List[str]:
        return [
            "我这个月工资多少？",
            "我这周的排班？",
            "我的健康证什么时候过期？",
            "我的请假余额",
            "我能报哪些课？",
        ]

    # ─── 公共：推荐问题（首屏）────────
    def suggested_questions(self) -> List[str]:
        return [
            "我这个月工资多少？",
            "我的考勤有没有异常？",
            "我下周排几个班？",
            "我的请假余额还剩多少？",
            "我的健康证什么时候过期？",
            "我的培训进度？",
            "我能参加哪些培训？",
            "帮我申请明天请假",
        ]
