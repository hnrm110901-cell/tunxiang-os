"""RFMOutreachService —— Sprint D3a RFM 触达规划服务（Haiku 4.5 + CF）

职责
----
1. **RFM 分层**：基于 recency / frequency / monetary 三维度把客户分 S1-S5
   （S1 最活跃 7 天内复购 / S5 沉睡 180+ 天未到店）
2. **CF 打分**：item-item 协同过滤，用客户历史订单的菜品相似度为每位
   沉睡客户打召回分（0-1），同时推荐 top_items
3. **Haiku 触达文案**：通过 ModelRouter.get_model("rfm_outreach_message")
   调用 Haiku 4.5 生成个性化召回消息（品牌语气 + top_items + 权益）
4. **持久化 campaign**：写入 rfm_outreach_campaigns 表，状态机 plan_generated
   → human_confirmed → sent → attributed

预期效果
-------
设计稿目标：复购率 +5pp（相对于基线）。归因由独立归因任务回写
`attributed_order_ids` 后按 campaign 聚合计算真实 lift。

设计权衡
-------
- CF 选用 item-item 相似度（而非矩阵分解）：数据量小（单店订单 ~1k-10k/天），
  item-item 矩阵 O(N²) 可接受，且结果可解释（top_items 直接可用）
- Haiku 4.5 生成文案而非 Sonnet：RFM 召回文案格式相对固定，Haiku 够用
  且成本 1/3，符合 sprint-plan 中"模型成本月上限 ¥12,000"约束
- 人工确认（plan_generated → human_confirmed）：对触达数量 > 50 时强制
  人工审核，避免 Agent 自作主张群发骚扰客户
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# RFM 分层阈值（与 tx-agent/agents/skills/member_insight.py RFM_THRESHOLDS 对齐）
# ──────────────────────────────────────────────────────────────────────

# Recency：距最近一次到店的天数
R_BUCKETS = [7, 30, 90, 180]           # ≤7(S1) ≤30(S2) ≤90(S3) ≤180(S4) >180(S5)
# Frequency：最近 12 个月到店次数
F_BUCKETS = [12, 6, 3, 1]              # ≥12(S1) ≥6(S2) ≥3(S3) ≥1(S4) 0(S5)
# Monetary：最近 12 个月累计消费（分）
M_BUCKETS = [500000, 200000, 80000, 20000]  # ≥5000元(S1) ≥2000(S2) ≥800(S3) ≥200(S4) <200(S5)


# ──────────────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────────────

@dataclass
class CustomerSnapshot:
    """单客户的 RFM + 消费偏好快照"""
    customer_id: str
    recency_days: int               # 距上次到店天数
    frequency: int                  # 最近 12 月次数
    monetary_fen: int               # 最近 12 月总消费（分）
    preferred_items: list[str] = field(default_factory=list)
    name: Optional[str] = None


@dataclass
class OutreachCandidate:
    """CF + 文案生成后的触达候选（1 客户 1 条）"""
    customer_id: str
    segment: str                    # S1-S5
    cf_score: float                 # 0-1，召回倾向
    top_items: list[str] = field(default_factory=list)
    outreach_message: Optional[str] = None
    estimated_uplift_fen: int = 0   # 预估增量消费


@dataclass
class OutreachPlan:
    """完整的一次触达规划（一条 rfm_outreach_campaigns 记录）"""
    campaign_id: str
    tenant_id: str
    store_id: Optional[str]
    segment: str
    candidates: list[OutreachCandidate]
    campaign_name: str
    model_id: str = "claude-haiku-4-5"

    @property
    def target_count(self) -> int:
        return len(self.candidates)

    @property
    def estimated_revenue_fen(self) -> int:
        return sum(c.estimated_uplift_fen for c in self.candidates)


# ──────────────────────────────────────────────────────────────────────
# RFM 分层
# ──────────────────────────────────────────────────────────────────────

def score_rfm(value: int, buckets: list[int], higher_better: bool) -> int:
    """单维度 RFM 打分：返回 1-5（1 最差/5 最好）。

    Args:
        value:         测量值
        buckets:       阈值（按 higher_better 方向降序/升序排列）
        higher_better: True = 值越大越好（F/M）；False = 值越小越好（R）
    """
    if higher_better:
        for i, threshold in enumerate(buckets):
            if value >= threshold:
                return 5 - i
        return 1
    # R：值越小越好，buckets 升序
    for i, threshold in enumerate(buckets):
        if value <= threshold:
            return 5 - i
    return 1


def segment_for(snap: CustomerSnapshot) -> str:
    """根据 RFM 三维打分计算 S1-S5 分层标签。

    策略：取三维度最小分（最弱维度主导）→ 1→S5, 5→S1。
    示例：R=5/F=5/M=3 → min=3 → S3
    """
    r = score_rfm(snap.recency_days, R_BUCKETS, higher_better=False)
    f = score_rfm(snap.frequency, F_BUCKETS, higher_better=True)
    m = score_rfm(snap.monetary_fen, M_BUCKETS, higher_better=True)
    worst = min(r, f, m)
    return f"S{6 - worst}"   # 分数 5 → S1 / 分数 1 → S5


# ──────────────────────────────────────────────────────────────────────
# CF 协同过滤（item-item）
# ──────────────────────────────────────────────────────────────────────

def cosine_similarity(a: set[str], b: set[str]) -> float:
    """集合版 cosine：|A∩B| / sqrt(|A|*|B|)。空集返回 0。"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    denom = (len(a) * len(b)) ** 0.5
    return inter / denom


def score_cf_candidate(
    candidate: CustomerSnapshot,
    active_peers: list[CustomerSnapshot],
    top_k_peers: int = 20,
    top_n_items: int = 3,
) -> tuple[float, list[str]]:
    """用活跃同店客户（S1-S2）的偏好菜品给候选人打 CF 分。

    算法：
      1. 计算候选 vs 每位活跃客户的 preferred_items 交集相似度
      2. 取 top_k 相邻客户，汇总他们的高频菜品
      3. 输出 cf_score = 平均相似度，top_items = top_n 热门菜
    """
    if not candidate.preferred_items or not active_peers:
        return 0.0, []

    cand_set = set(candidate.preferred_items)
    scored_peers: list[tuple[float, CustomerSnapshot]] = []
    for peer in active_peers:
        sim = cosine_similarity(cand_set, set(peer.preferred_items))
        if sim > 0:
            scored_peers.append((sim, peer))

    if not scored_peers:
        return 0.0, []

    scored_peers.sort(key=lambda x: x[0], reverse=True)
    top = scored_peers[:top_k_peers]
    avg_sim = sum(s for s, _ in top) / len(top)

    # 推荐候选人未点过的菜（活跃客户爱点的）
    item_votes: dict[str, float] = {}
    for sim, peer in top:
        for item in peer.preferred_items:
            if item in cand_set:
                continue  # 候选人已点过，跳过
            item_votes[item] = item_votes.get(item, 0.0) + sim

    top_items = sorted(item_votes.items(), key=lambda x: x[1], reverse=True)[:top_n_items]
    return round(avg_sim, 4), [item for item, _ in top_items]


# ──────────────────────────────────────────────────────────────────────
# 服务主体
# ──────────────────────────────────────────────────────────────────────

class RFMOutreachService:
    """D3a RFM 触达规划服务。

    依赖注入：
      model_router:    ModelRouter 实例（None 时走降级模板文案）
      haiku_invoker:   async (prompt:str, model_id:str) -> str，封装实际 LLM 调用
                       为 None 时走降级模板，便于测试
    """

    def __init__(
        self,
        model_router: Any = None,
        haiku_invoker: Optional[Any] = None,
    ) -> None:
        self.model_router = model_router
        self.haiku_invoker = haiku_invoker

    async def build_plan(
        self,
        *,
        tenant_id: str,
        store_id: Optional[str],
        candidates: list[CustomerSnapshot],
        active_peers: list[CustomerSnapshot],
        target_segments: Optional[list[str]] = None,
        campaign_name: Optional[str] = None,
    ) -> OutreachPlan:
        """规划一次 RFM 触达。

        Args:
            candidates:     待评估客户池（通常是 S4/S5 沉睡客户）
            active_peers:   用作 CF 相似度源的活跃客户（S1/S2）
            target_segments: 仅保留这些分层的客户，默认 ["S4", "S5"]
            campaign_name:  为空时用 "S4-S5 召回 YYYY-MM-DD"

        Returns:
            OutreachPlan 实例（尚未写 DB，调用方决定是否持久化）
        """
        segments = target_segments or ["S4", "S5"]

        filtered: list[OutreachCandidate] = []
        for cand in candidates:
            seg = segment_for(cand)
            if seg not in segments:
                continue
            cf_score, top_items = score_cf_candidate(cand, active_peers)
            # 预估增量：cf_score × 人均客单 20000 分（200元），保守估计
            est_uplift = int(cf_score * 20000)
            filtered.append(OutreachCandidate(
                customer_id=cand.customer_id,
                segment=seg,
                cf_score=cf_score,
                top_items=top_items,
                estimated_uplift_fen=est_uplift,
            ))

        # 为 cf_score > 0 的候选生成 Haiku 文案
        for outreach in filtered:
            if outreach.cf_score <= 0:
                continue
            outreach.outreach_message = await self._generate_message(
                segment=outreach.segment,
                top_items=outreach.top_items,
                customer_id=outreach.customer_id,
            )

        # 排序：cf_score 高优先
        filtered.sort(key=lambda c: c.cf_score, reverse=True)

        model_id = "claude-haiku-4-5"
        if self.model_router and hasattr(self.model_router, "get_model"):
            try:
                model_id = self.model_router.get_model("rfm_outreach_message")
            except Exception as exc:  # noqa: BLE001
                logger.warning("model_router_resolve_failed: %s", exc)

        return OutreachPlan(
            campaign_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            store_id=store_id,
            segment="+".join(segments),
            candidates=filtered,
            campaign_name=campaign_name or self._default_name(segments),
            model_id=model_id,
        )

    async def _generate_message(
        self,
        *,
        segment: str,
        top_items: list[str],
        customer_id: str,
    ) -> str:
        """调用 Haiku 生成召回文案；invoker 为 None 时走降级模板。"""
        prompt = self._build_prompt(segment=segment, top_items=top_items)

        if self.haiku_invoker is None:
            return self._fallback_message(segment=segment, top_items=top_items)

        try:
            return await self.haiku_invoker(prompt, "claude-haiku-4-5")
        except Exception as exc:  # noqa: BLE001 — LLM 失败不应阻断规划
            logger.warning(
                "haiku_invoke_failed customer=%s error=%s", customer_id, exc,
            )
            return self._fallback_message(segment=segment, top_items=top_items)

    # ── 内部辅助 ─────────────────────────────────────────────────

    @staticmethod
    def _build_prompt(*, segment: str, top_items: list[str]) -> str:
        """构造 Haiku prompt，让模型生成一条 ≤80 字的召回短信。"""
        items_str = "、".join(top_items[:3]) if top_items else "我们的招牌菜"
        if segment in ("S4", "S5"):
            urgency = "好久不见，特地为您准备了"
        else:
            urgency = "为您新品推荐"
        return (
            f"你是餐厅品牌文案，生成一条 ≤80 字的微信召回短信。"
            f"场景：{urgency}顾客偏爱的 {items_str}。"
            f"语气温暖不强迫。无需称呼顾客姓名。只输出文案本身，不加解释。"
        )

    @staticmethod
    def _fallback_message(*, segment: str, top_items: list[str]) -> str:
        """Haiku 不可用时的降级模板，确保流程不中断。"""
        items_str = "、".join(top_items[:3]) if top_items else "新菜"
        if segment == "S5":
            return f"好久不见，{items_str} 为您准备好了，期待与您重聚。"
        if segment == "S4":
            return f"想念您了！{items_str} 今日上新，欢迎回店品尝。"
        return f"为您推荐 {items_str}，欢迎再次光临。"

    @staticmethod
    def _default_name(segments: list[str]) -> str:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        seg_label = "-".join(segments)
        return f"{seg_label} 召回 {today}"


# ──────────────────────────────────────────────────────────────────────
# 数据库工具（供 API 调用）
# ──────────────────────────────────────────────────────────────────────

async def save_plan_to_db(db: Any, plan: OutreachPlan, confirmed_by: Optional[str] = None) -> dict:
    """把 OutreachPlan 写入 rfm_outreach_campaigns 表。

    Args:
        db: AsyncSession（已绑定 RLS）
        plan: OutreachPlan
        confirmed_by: 若已有店长确认 → 直接写 status='human_confirmed'，
                      否则 status='plan_generated'

    Returns:
        {"campaign_id": str, "status": str}

    注：SQL 用 raw text 以避免依赖 ORM 模型（本 PR 不改 entities.py）。
    """
    try:
        from sqlalchemy import text
    except ImportError as exc:
        raise RuntimeError("SQLAlchemy 必需") from exc

    status = "human_confirmed" if confirmed_by else "plan_generated"
    confirmed_at = datetime.now(timezone.utc) if confirmed_by else None

    cf_snapshot = {
        c.customer_id: {
            "score": c.cf_score,
            "top_items": c.top_items,
            "segment": c.segment,
            "estimated_uplift_fen": c.estimated_uplift_fen,
            "message": c.outreach_message,
        }
        for c in plan.candidates
    }

    # 首条候选人的文案作为模板写入
    template = plan.candidates[0].outreach_message if plan.candidates else ""

    await db.execute(text("""
        INSERT INTO rfm_outreach_campaigns (
            id, tenant_id, store_id, campaign_name, rfm_segment,
            target_customer_ids, target_count, cf_scoring_snapshot,
            message_template, message_model, status,
            confirmed_by, confirmed_at,
            estimated_roi_summary
        ) VALUES (
            CAST(:id AS uuid),
            CAST(:tenant_id AS uuid),
            CAST(:store_id AS uuid),
            :campaign_name, :rfm_segment,
            CAST(:target_ids AS uuid[]), :target_count,
            CAST(:cf_snapshot AS jsonb),
            :message_template, :message_model, :status,
            CAST(:confirmed_by AS uuid), :confirmed_at,
            CAST(:roi_summary AS jsonb)
        )
    """), {
        "id": plan.campaign_id,
        "tenant_id": plan.tenant_id,
        "store_id": plan.store_id,
        "campaign_name": plan.campaign_name,
        "rfm_segment": plan.segment,
        "target_ids": [c.customer_id for c in plan.candidates],
        "target_count": plan.target_count,
        "cf_snapshot": _to_json_str(cf_snapshot),
        "message_template": template,
        "message_model": plan.model_id,
        "status": status,
        "confirmed_by": confirmed_by,
        "confirmed_at": confirmed_at,
        "roi_summary": _to_json_str({
            "estimated_revenue_fen": plan.estimated_revenue_fen,
            "candidate_count": plan.target_count,
        }),
    })
    await db.commit()
    logger.info(
        "rfm_outreach_plan_saved campaign_id=%s status=%s count=%d",
        plan.campaign_id, status, plan.target_count,
    )
    return {"campaign_id": plan.campaign_id, "status": status}


def _to_json_str(payload: dict) -> str:
    """dict → JSON string（JSONB 传参需要字符串）。"""
    import json
    return json.dumps(payload, ensure_ascii=False, default=str)


__all__ = [
    "CustomerSnapshot",
    "OutreachCandidate",
    "OutreachPlan",
    "RFMOutreachService",
    "R_BUCKETS",
    "F_BUCKETS",
    "M_BUCKETS",
    "score_rfm",
    "segment_for",
    "cosine_similarity",
    "score_cf_candidate",
    "save_plan_to_db",
]
