"""
绩效专家 Agent — 低绩效门店归因 + 改进建议

输入：若干门店的核心指标（营业额/翻台率/客单价/人效/OKR 达成率/9 宫格位置）
输出：对每家门店给出 Top-3 归因 + 改进动作 + 预期影响

LLM 失败时回退到规则判断。
"""

from __future__ import annotations

from typing import Any, Dict, List

import structlog

from ..llm_gateway import get_llm_gateway

logger = structlog.get_logger()


class PerformanceExpertAgent:
    """绩效专家 Agent — 对外可售（企业版）"""

    async def analyze(
        self,
        stores: List[Dict[str, Any]],
        peer_avg: Dict[str, float] | None = None,
    ) -> Dict[str, Any]:
        """
        stores 示例：
          [{store_id, name, revenue_fen, turnover_rate, avg_ticket_fen,
            labor_efficiency, okr_completion, nine_grid}]
        """
        peer = peer_avg or {}
        results: List[Dict[str, Any]] = []
        for s in stores:
            reasons = self._rule_based_reasons(s, peer)
            actions = self._rule_based_actions(reasons)
            impact_yuan = self._estimate_impact(s, reasons)

            narrative = await self._llm_narrative(s, reasons, actions, impact_yuan)
            results.append({
                "store_id": s.get("store_id"),
                "store_name": s.get("name"),
                "reasons": reasons,
                "actions": actions,
                "expected_monthly_impact_fen": int(impact_yuan * 100),
                "expected_monthly_impact_yuan": round(impact_yuan, 2),
                "narrative": narrative,
            })
        # 低绩效排序
        results.sort(key=lambda x: x["expected_monthly_impact_yuan"], reverse=True)
        return {
            "total_stores": len(results),
            "results": results,
        }

    # ───────────────────── 规则库 ─────────────────────
    def _rule_based_reasons(
        self, s: Dict[str, Any], peer: Dict[str, float],
    ) -> List[str]:
        reasons: List[str] = []
        turnover = float(s.get("turnover_rate") or 0)
        ticket = float(s.get("avg_ticket_fen") or 0) / 100
        labor = float(s.get("labor_efficiency") or 0)
        okr = float(s.get("okr_completion") or 0)

        if turnover < peer.get("turnover_rate", 3.0):
            reasons.append(f"翻台率 {turnover:.1f} 低于同行均值 {peer.get('turnover_rate', 3.0):.1f}")
        if ticket < peer.get("avg_ticket_yuan", 80.0):
            reasons.append(f"客单价 ¥{ticket:.0f} 低于同行均值 ¥{peer.get('avg_ticket_yuan', 80.0):.0f}")
        if labor and labor < peer.get("labor_efficiency", 3000.0):
            reasons.append(f"人效 {labor:.0f} 低于同行均值 {peer.get('labor_efficiency', 3000.0):.0f}")
        if okr and okr < 0.6:
            reasons.append(f"OKR 达成率仅 {okr*100:.0f}%")
        if not reasons:
            reasons.append("整体指标处于同行平均线附近，未出现显著短板")
        return reasons[:3]

    def _rule_based_actions(self, reasons: List[str]) -> List[str]:
        actions: List[str] = []
        for r in reasons:
            if "翻台率" in r:
                actions.append("优化排队叫号 + 压缩结账等待，目标 +0.3 翻台")
            elif "客单价" in r:
                actions.append("上架 2 道套餐/推荐套餐话术培训，目标 +¥8 客单价")
            elif "人效" in r:
                actions.append("重排高峰段班次 + 启用兼职灵活工，目标 -8% 人力成本")
            elif "OKR" in r:
                actions.append("月度 1v1 拆解障碍项 + 每周进度复核")
        if not actions:
            actions.append("保持现有节奏，关注同行变化")
        return actions[:3]

    def _estimate_impact(self, s: Dict[str, Any], reasons: List[str]) -> float:
        """估算月度 ¥ 影响：按营业额 × 修复系数"""
        revenue_yuan = float(s.get("revenue_fen") or 0) / 100
        factor = 0.0
        for r in reasons:
            if "翻台率" in r:
                factor += 0.06
            elif "客单价" in r:
                factor += 0.08
            elif "人效" in r:
                factor += 0.04
            elif "OKR" in r:
                factor += 0.03
        return round(revenue_yuan * factor, 2)

    async def _llm_narrative(
        self,
        s: Dict[str, Any],
        reasons: List[str],
        actions: List[str],
        impact_yuan: float,
    ) -> str:
        prompt = (
            f"门店【{s.get('name')}】核心短板：" + "；".join(reasons) +
            "。建议动作：" + "；".join(actions) +
            f"。预计月度改善 ¥{impact_yuan:.0f}。请用 1 句中文给老板说人话。"
        )
        try:
            gw = get_llm_gateway()
            resp = await gw.chat(messages=[{"role": "user", "content": prompt}], max_tokens=150)
            if isinstance(resp, dict):
                return resp.get("content") or prompt
            return str(resp)
        except Exception:
            # 回退：拼接自然语言
            return (
                f"{s.get('name')} 主要问题：{reasons[0]}。"
                f"建议：{actions[0] if actions else '-'}。"
                f"预计月度改善 ¥{impact_yuan:.0f}。"
            )
