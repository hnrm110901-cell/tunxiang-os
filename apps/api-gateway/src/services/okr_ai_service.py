"""
OKR AI 辅助服务 — LLM 推荐 SMART KR + 分析对齐合理性
容错：LLM 失败返回空数组，不阻塞主流程
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class OKRAIService:
    """基于 LLMGateway 的 OKR 辅助建议"""

    def __init__(self, llm_gateway: Any = None):
        self.llm = llm_gateway  # 延迟注入

    async def _chat(self, system: str, user: str) -> str:
        """调用 LLM，失败返回空字符串"""
        if self.llm is None:
            try:
                from src.services.llm_gateway.gateway import LLMGateway
                from src.services.llm_gateway.factory import build_gateway_from_config  # type: ignore

                self.llm = build_gateway_from_config()
            except Exception:
                try:
                    from src.services.llm_gateway import gateway as _gw  # noqa: F401

                    self.llm = _gw.LLMGateway()  # best effort
                except Exception as e:
                    logger.warning("okr_ai_llm_init_failed", exc_info=e)
                    return ""
        try:
            resp = await self.llm.chat(
                messages=[{"role": "user", "content": user}],
                system=system,
                temperature=0.3,
                max_tokens=800,
            )
            return resp.get("text", "") if isinstance(resp, dict) else str(resp or "")
        except Exception as e:
            logger.warning("okr_ai_llm_chat_failed", exc_info=e)
            return ""

    @staticmethod
    def _extract_json_array(text: str) -> List[Dict[str, Any]]:
        """从 LLM 文本里提取 JSON 数组"""
        if not text:
            return []
        # 优先找 ```json ... ``` 代码块
        m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if not m:
            m = re.search(r"(\[[\s\S]*\])", text)
        if not m:
            return []
        try:
            data = json.loads(m.group(1))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    # ─── 推荐 KR ────────────────────────────────
    async def suggest_key_results(self, objective_title: str, context: str = "") -> List[Dict[str, Any]]:
        """基于目标标题推荐 3-5 个 SMART KR"""
        system = (
            "你是连锁餐饮 OKR 教练。对目标拆解 3-5 个 SMART 关键结果 (KR)，"
            "要求具体/可衡量/可达成/相关/有时限。返回严格 JSON 数组，不加解释。"
            "每项字段: title, metric_type (numeric|percentage|boolean|milestone), "
            "start_value, target_value, unit, weight (整数 0-100，权重总和=100)。"
        )
        user = f"目标：{objective_title}\n背景：{context}\n输出 JSON 数组。"
        text = await self._chat(system, user)
        items = self._extract_json_array(text)
        # 基本校验
        clean: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict) or "title" not in it:
                continue
            clean.append(
                {
                    "title": str(it.get("title", "")),
                    "metric_type": it.get("metric_type", "numeric"),
                    "start_value": float(it.get("start_value", 0) or 0),
                    "target_value": float(it.get("target_value", 0) or 0),
                    "unit": it.get("unit"),
                    "weight": int(it.get("weight", 20) or 20),
                }
            )
        return clean[:5]

    # ─── 对齐合理性分析 ─────────────────────────
    async def analyze_alignment(
        self, parent_title: str, child_titles: List[str]
    ) -> Dict[str, Any]:
        """判断子目标是否真正支撑父目标"""
        system = (
            "你是 OKR 对齐审计师。给定一个父目标和一组子目标，判断每个子目标是否真正支撑父目标。"
            "返回严格 JSON 数组，每项: {child: str, supports: true/false, reason: str, suggestion: str}。"
        )
        user = (
            f"父目标：{parent_title}\n子目标：\n"
            + "\n".join(f"- {t}" for t in child_titles)
        )
        text = await self._chat(system, user)
        items = self._extract_json_array(text)
        return {"items": items}


okr_ai_service = OKRAIService()
