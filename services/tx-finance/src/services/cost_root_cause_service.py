"""CostRootCauseService —— Sprint D4a 成本根因分析（Sonnet 4.7 + Prompt Cache）

业务问题
-------
月底店长发现 food_cost_rate 超预算 5%，需翻多张表定位原因：
  - 原料采购涨价？
  - 某批次损耗异常？
  - BOM 实际用量偏差？
  - 供应商切换价格变动？

手工排查平均 2-3 小时/店/月，10 店链月耗 30 小时。
本服务把这个流程自动化：Agent 收集 → Sonnet 分析 → 输出排名根因 + 治理建议。

Prompt Cache 策略
----------------
system prompt 固定 ~3000 tokens（BOM 行业基准 + 成本分析 SOP + 输出 schema），
首次写入 cache 后 5 分钟 TTL 内命中。生产典型 10 店连续分析：

  call 1: cache write 3000 tokens
  call 2-10: cache read 3000 tokens each → 总 cache_read = 27K

命中率 = cache_read / (cache_read + cache_write + input)
       = 27000 / (27000 + 3000 + 10000) = 67.5%

设计稿目标 ≥75%。本 PR 预留 cache_read_tokens / cache_creation_tokens
字段供实际调用后统计；测试环境 invoker=None 时 cache_* = 0。

设计权衡
-------
- **Sonnet 4.7 而非 Opus**：成本 1/3，思考深度足够成本归因任务
- **prompt 分 3 段**：system（cacheable）+ BOM/基准（cacheable 大块）+
  user（每店独立，不 cacheable）
- **invoker 接口稳定**：`async (request: dict) -> response: dict`，request 含
  messages/system/cache_control 完整结构，便于生产 wire Anthropic SDK
- **降级**：invoker=None → 规则引擎生成 top-3 cause，不阻塞流程
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Sprint D4 所有任务走 Sonnet 4.7（prompt cache beta 加持）
SONNET_CACHED_MODEL = "claude-sonnet-4-7"
CACHE_HIT_TARGET = 0.75  # 设计稿"缓存命中 ≥75%"
COST_OVERRUN_TRIGGER_PCT = 0.05  # 超预算 5% 触发


# ──────────────────────────────────────────────────────────────────────
# 成本信号数据结构（从多域拉取）
# ──────────────────────────────────────────────────────────────────────

@dataclass
class RawMaterialPriceChange:
    """原料采购价格变动（近 30 天）"""
    ingredient_name: str
    old_price_fen: int
    new_price_fen: int
    change_pct: float
    supplier: Optional[str] = None


@dataclass
class WasteEvent:
    """浪费登记"""
    ingredient_name: str
    quantity: float
    unit: str
    loss_fen: int
    reason: str        # expired / prep_waste / customer_waste / other
    recorded_at: datetime


@dataclass
class BOMDeviation:
    """BOM 实际用量偏差"""
    dish_name: str
    ingredient_name: str
    standard_qty: float
    actual_qty: float
    deviation_pct: float    # (actual - standard) / standard


@dataclass
class CostSignalBundle:
    """某店某月的成本异常信号包（喂给 Sonnet 的 user prompt 数据）"""
    store_id: str
    store_name: str
    analysis_month: date
    food_cost_fen: int
    food_cost_budget_fen: int
    cost_overrun_pct: float
    price_changes: list[RawMaterialPriceChange] = field(default_factory=list)
    waste_events: list[WasteEvent] = field(default_factory=list)
    bom_deviations: list[BOMDeviation] = field(default_factory=list)
    supplier_changes: list[dict] = field(default_factory=list)

    def to_json_dict(self) -> dict:
        """序列化为 JSON（prompt 用）"""
        return {
            "store_name": self.store_name,
            "analysis_month": self.analysis_month.isoformat(),
            "food_cost_yuan": round(self.food_cost_fen / 100, 2),
            "food_cost_budget_yuan": round(self.food_cost_budget_fen / 100, 2),
            "cost_overrun_pct": round(self.cost_overrun_pct, 4),
            "price_changes": [
                {
                    "ingredient": p.ingredient_name,
                    "old_price_yuan": round(p.old_price_fen / 100, 2),
                    "new_price_yuan": round(p.new_price_fen / 100, 2),
                    "change_pct": round(p.change_pct, 4),
                    "supplier": p.supplier,
                }
                for p in self.price_changes
            ],
            "waste_events_summary": {
                "total_count": len(self.waste_events),
                "total_loss_yuan": round(
                    sum(w.loss_fen for w in self.waste_events) / 100, 2
                ),
                "by_reason": self._group_waste_by_reason(),
            },
            "bom_deviations": [
                {
                    "dish": d.dish_name,
                    "ingredient": d.ingredient_name,
                    "deviation_pct": round(d.deviation_pct, 4),
                }
                for d in self.bom_deviations if abs(d.deviation_pct) > 0.05
            ],
            "supplier_changes": self.supplier_changes,
        }

    def _group_waste_by_reason(self) -> dict:
        groups: dict[str, dict] = {}
        for w in self.waste_events:
            g = groups.setdefault(w.reason, {"count": 0, "loss_fen": 0})
            g["count"] += 1
            g["loss_fen"] += w.loss_fen
        return {
            r: {"count": v["count"], "loss_yuan": round(v["loss_fen"] / 100, 2)}
            for r, v in groups.items()
        }


@dataclass
class RootCause:
    cause_type: str       # price_hike / waste_spike / bom_deviation / supplier_switch / other
    confidence: float     # 0-1
    evidence: str
    impact_fen: int       # 此原因贡献的成本超支金额
    priority: str         # high / medium / low


@dataclass
class RemediationAction:
    action: str
    owner_role: str       # store_manager / supply_chain / head_chef
    deadline_days: int
    expected_savings_fen: int


@dataclass
class RootCauseAnalysisResult:
    ranked_causes: list[RootCause] = field(default_factory=list)
    remediation_actions: list[RemediationAction] = field(default_factory=list)
    sonnet_analysis: str = ""
    # Prompt Cache 统计
    model_id: str = SONNET_CACHED_MODEL
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cache_hit_rate(self) -> float:
        """cache_read / (cache_read + cache_create + non_cached_input)"""
        total_input = (
            self.cache_read_tokens
            + self.cache_creation_tokens
            + self.input_tokens
        )
        if total_input == 0:
            return 0.0
        return round(self.cache_read_tokens / total_input, 4)


# ──────────────────────────────────────────────────────────────────────
# Cached Prompt Builder（核心）
# ──────────────────────────────────────────────────────────────────────

class CachedPromptBuilder:
    """构造 Anthropic Messages API 的 request，带 cache_control 标记。

    标准结构：
      {
        "model": "claude-sonnet-4-7",
        "max_tokens": 1024,
        "system": [
          {"type": "text", "text": STABLE_SYSTEM, "cache_control": {"type": "ephemeral"}},
          {"type": "text", "text": LARGE_CONTEXT, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [
          {"role": "user", "content": DYNAMIC_USER_TEXT}
        ]
      }

    生产调用方需加 `extra_headers = {"anthropic-beta": "prompt-caching-2024-07-31"}`。
    """

    # === 稳定 system prompt（cacheable 1：职责 + 输出 schema）===
    STABLE_SYSTEM = (
        "你是屯象OS 成本根因分析师（Sprint D4a）。\n"
        "职责：基于门店近 30 天成本信号，定位 food_cost_rate 超预算的根因，"
        "按影响金额降序排名，给出治理建议。\n\n"
        "输出必须是合法 JSON，结构如下：\n"
        "```json\n"
        "{\n"
        '  "analysis": "一段自然语言总结（≤200 字）",\n'
        '  "ranked_causes": [\n'
        '    {"cause_type": "price_hike|waste_spike|bom_deviation|supplier_switch|other",\n'
        '     "confidence": 0.0-1.0,\n'
        '     "evidence": "具体证据（引用信号包数据）",\n'
        '     "impact_fen": 12345,\n'
        '     "priority": "high|medium|low"}\n'
        "  ],\n"
        '  "remediation_actions": [\n'
        '    {"action": "具体动作", "owner_role": "store_manager|supply_chain|head_chef",\n'
        '     "deadline_days": 3-30, "expected_savings_fen": 12345}\n'
        "  ]\n"
        "}\n"
        "```\n\n"
        "规则：\n"
        "1. confidence 是你对结论的信心，非数据完整度\n"
        "2. impact_fen 必须与 cost_overrun 可调账（≤ food_cost_fen - budget_fen）\n"
        "3. remediation_actions 至少 1 条，每条 expected_savings_fen > 0\n"
        "4. 若信号稀疏无法判断，ranked_causes 返回空数组，action 改成 '补齐数据'"
    )

    # === 行业基准（cacheable 2：大块，10 店共享）===
    INDUSTRY_BENCHMARKS = (
        "=== 餐饮行业成本基准参考 ===\n"
        "\n"
        "## food_cost_rate（食材成本率）\n"
        "- 快餐/小吃：20-25% 优秀 / 25-30% 正常 / >32% 预警\n"
        "- 中餐正餐：28-32% 优秀 / 32-36% 正常 / >38% 预警\n"
        "- 海鲜/活鲜：35-42% 优秀 / 42-48% 正常 / >50% 预警\n"
        "- 火锅/自助：28-34% 优秀 / 34-40% 正常 / >42% 预警\n"
        "\n"
        "## 浪费率基准（loss_fen / food_cost_fen）\n"
        "- <3% 优秀 / 3-5% 正常 / 5-8% 预警 / >8% 严重\n"
        "\n"
        "## BOM 偏差容忍\n"
        "- ±5% 为正常（人工操作误差）\n"
        "- ±5%~15% 为关注（配方/培训问题）\n"
        "- >±15% 为严重（作假/损耗/称重问题）\n"
        "\n"
        "## 典型根因分布（行业统计）\n"
        "- 原料涨价 35%\n"
        "- 浪费升高 25%\n"
        "- BOM 偏差 20%\n"
        "- 供应商切换 10%\n"
        "- 其他 10%\n"
        "\n"
        "## 治理动作示例\n"
        "- 原料涨价 → 切换备选供应商 / 调整菜单价 / 改配方降本\n"
        "- 浪费升高 → 培训备料 SOP / 临期食材特价清 / 盘点周期加密\n"
        "- BOM 偏差 → 培训标准做法 / 电子秤校准 / 抽查后厨操作\n"
        "- 供应商切换 → 谈判价格回调 / 找第二来源 / 锁定季度合同"
    )

    @classmethod
    def build_request(
        cls,
        *,
        signal_bundle: CostSignalBundle,
        model_id: str = SONNET_CACHED_MODEL,
        max_tokens: int = 1024,
    ) -> dict:
        """构造完整的 Anthropic Messages API request（带 cache_control）。"""
        user_payload = signal_bundle.to_json_dict()
        user_text = (
            "请为以下门店的成本超支做根因分析：\n\n"
            f"```json\n{json.dumps(user_payload, ensure_ascii=False, indent=2)}\n```\n\n"
            "按上文 schema 输出合法 JSON。"
        )

        return {
            "model": model_id,
            "max_tokens": max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": cls.STABLE_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": cls.INDUSTRY_BENCHMARKS,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            "messages": [
                {"role": "user", "content": user_text},
            ],
        }


# ──────────────────────────────────────────────────────────────────────
# 响应解析
# ──────────────────────────────────────────────────────────────────────

def parse_sonnet_response(
    response: dict,
) -> tuple[str, list[RootCause], list[RemediationAction], dict]:
    """从 Anthropic response 抽出 analysis / causes / actions + token stats。

    response 期望结构：
      {
        "content": [{"type": "text", "text": "... json ..."}],
        "usage": {
          "input_tokens": ...,
          "output_tokens": ...,
          "cache_creation_input_tokens": ...,
          "cache_read_input_tokens": ...
        }
      }
    """
    # 1. 提取文本
    text = ""
    for block in response.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text", "")

    # 2. 解析 JSON（允许 ```json ... ``` 包裹）
    payload: dict = {}
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            # strip code fence
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].lstrip()
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        payload = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError, IndexError) as exc:
        logger.warning("sonnet_response_parse_failed error=%s text=%s", exc, text[:200])

    # 3. 结构化
    analysis = str(payload.get("analysis", text[:200]))
    causes_raw = payload.get("ranked_causes", []) or []
    actions_raw = payload.get("remediation_actions", []) or []

    causes = [
        RootCause(
            cause_type=str(c.get("cause_type", "other")),
            confidence=float(c.get("confidence", 0.0) or 0.0),
            evidence=str(c.get("evidence", "")),
            impact_fen=int(c.get("impact_fen", 0) or 0),
            priority=str(c.get("priority", "medium")),
        )
        for c in causes_raw
        if isinstance(c, dict)
    ]
    actions = [
        RemediationAction(
            action=str(a.get("action", "")),
            owner_role=str(a.get("owner_role", "store_manager")),
            deadline_days=int(a.get("deadline_days", 14) or 14),
            expected_savings_fen=int(a.get("expected_savings_fen", 0) or 0),
        )
        for a in actions_raw
        if isinstance(a, dict)
    ]

    # 4. Token 统计（Prompt Cache 统计核心）
    usage = response.get("usage") or {}
    stats = {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "cache_creation_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
        "cache_read_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
    }
    return analysis, causes, actions, stats


# ──────────────────────────────────────────────────────────────────────
# Service
# ──────────────────────────────────────────────────────────────────────

class CostRootCauseService:
    """D4a 成本根因分析服务。

    依赖注入：
      sonnet_invoker: async (request: dict) -> response: dict
                      生产接 Anthropic SDK，测试传 mock
    """

    def __init__(self, sonnet_invoker: Optional[Any] = None) -> None:
        self.sonnet_invoker = sonnet_invoker

    async def analyze(
        self,
        signal_bundle: CostSignalBundle,
    ) -> RootCauseAnalysisResult:
        """基于信号包生成分析结果。"""
        if not self._should_trigger(signal_bundle):
            # 未触发预警（成本未超 5%），直接返空结果
            return RootCauseAnalysisResult(
                sonnet_analysis=f"{signal_bundle.store_name} 成本在预算内，未触发分析",
            )

        request = CachedPromptBuilder.build_request(signal_bundle=signal_bundle)

        if self.sonnet_invoker is None:
            return self._fallback_analyze(signal_bundle)

        try:
            response = await self.sonnet_invoker(request)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sonnet_invoke_failed error=%s", exc)
            return self._fallback_analyze(signal_bundle)

        analysis, causes, actions, token_stats = parse_sonnet_response(response)
        return RootCauseAnalysisResult(
            ranked_causes=causes,
            remediation_actions=actions,
            sonnet_analysis=analysis,
            model_id=SONNET_CACHED_MODEL,
            **token_stats,
        )

    # ── 降级：规则引擎生成 top-3 cause ──

    @staticmethod
    def _should_trigger(b: CostSignalBundle) -> bool:
        """成本超支 ≥ COST_OVERRUN_TRIGGER_PCT 才启动分析"""
        return b.cost_overrun_pct >= COST_OVERRUN_TRIGGER_PCT

    @staticmethod
    def _fallback_analyze(b: CostSignalBundle) -> RootCauseAnalysisResult:
        """Sonnet 不可用的降级：基于信号量的简单排名。"""
        causes: list[RootCause] = []
        actions: list[RemediationAction] = []

        # 1. 原料涨价
        hikes = [p for p in b.price_changes if p.change_pct > 0.05]
        if hikes:
            total_hike_impact = sum(
                int((p.new_price_fen - p.old_price_fen) * 100)  # 粗估
                for p in hikes
            )
            causes.append(RootCause(
                cause_type="price_hike",
                confidence=0.55,
                evidence=f"{len(hikes)} 项原料涨价 ≥5%，影响估算 {total_hike_impact / 100:.0f} 元",
                impact_fen=total_hike_impact,
                priority="high" if len(hikes) >= 3 else "medium",
            ))
            actions.append(RemediationAction(
                action="谈判价格 / 切换备选供应商",
                owner_role="supply_chain",
                deadline_days=14,
                expected_savings_fen=int(total_hike_impact * 0.5),
            ))

        # 2. 浪费
        total_waste_fen = sum(w.loss_fen for w in b.waste_events)
        if total_waste_fen > 0 and b.food_cost_fen > 0:
            waste_rate = total_waste_fen / b.food_cost_fen
            if waste_rate > 0.05:
                causes.append(RootCause(
                    cause_type="waste_spike",
                    confidence=0.60,
                    evidence=f"浪费率 {waste_rate:.1%} 超 5% 预警线",
                    impact_fen=total_waste_fen,
                    priority="high" if waste_rate > 0.08 else "medium",
                ))
                actions.append(RemediationAction(
                    action="培训备料 SOP + 加密临期盘点",
                    owner_role="head_chef",
                    deadline_days=7,
                    expected_savings_fen=int(total_waste_fen * 0.6),
                ))

        # 3. BOM 偏差
        big_dev = [d for d in b.bom_deviations if abs(d.deviation_pct) > 0.05]
        if big_dev:
            causes.append(RootCause(
                cause_type="bom_deviation",
                confidence=0.50,
                evidence=f"{len(big_dev)} 道菜 BOM 偏差 >±5%",
                impact_fen=int(b.food_cost_fen * 0.02),
                priority="medium",
            ))
            actions.append(RemediationAction(
                action="校准电子秤 / 后厨抽查标准做法",
                owner_role="head_chef",
                deadline_days=10,
                expected_savings_fen=int(b.food_cost_fen * 0.01),
            ))

        # 排名
        causes.sort(key=lambda c: c.impact_fen, reverse=True)

        if not causes:
            causes = [RootCause(
                cause_type="other",
                confidence=0.3,
                evidence="信号稀疏，无法定位具体原因",
                impact_fen=0,
                priority="low",
            )]
            actions = [RemediationAction(
                action="补齐 30 天原料采购/浪费/BOM 数据",
                owner_role="store_manager",
                deadline_days=14,
                expected_savings_fen=0,
            )]

        text = (
            f"{b.store_name} {b.analysis_month.isoformat()[:7]} 成本超预算 "
            f"{b.cost_overrun_pct:.1%}，规则引擎定位 {len(causes)} 个主要原因。"
        )
        return RootCauseAnalysisResult(
            ranked_causes=causes[:5],
            remediation_actions=actions[:5],
            sonnet_analysis=text,
            model_id="fallback_rules",
        )


# ──────────────────────────────────────────────────────────────────────
# DB 持久化
# ──────────────────────────────────────────────────────────────────────

async def save_analysis_to_db(
    db: Any,
    *,
    tenant_id: str,
    signal_bundle: CostSignalBundle,
    result: RootCauseAnalysisResult,
    analysis_type: str = "monthly_cost_overrun",
) -> str:
    from sqlalchemy import text

    record_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO cost_root_cause_analyses (
            id, tenant_id, store_id, analysis_month, analysis_type,
            food_cost_fen, food_cost_budget_fen, cost_overrun_pct,
            signals_snapshot, ranked_causes, remediation_actions,
            sonnet_analysis, model_id,
            cache_read_tokens, cache_creation_tokens, input_tokens, output_tokens,
            status
        ) VALUES (
            CAST(:id AS uuid),
            CAST(:tenant_id AS uuid),
            CAST(:store_id AS uuid),
            :analysis_month, :analysis_type,
            :food_cost_fen, :food_cost_budget_fen, :cost_overrun_pct,
            CAST(:signals AS jsonb), CAST(:causes AS jsonb), CAST(:actions AS jsonb),
            :sonnet_analysis, :model_id,
            :cache_read, :cache_creation, :input_tokens, :output_tokens,
            'analyzed'
        )
        ON CONFLICT ON CONSTRAINT ux_cost_root_cause_monthly
        DO UPDATE SET
            food_cost_fen = EXCLUDED.food_cost_fen,
            food_cost_budget_fen = EXCLUDED.food_cost_budget_fen,
            cost_overrun_pct = EXCLUDED.cost_overrun_pct,
            signals_snapshot = EXCLUDED.signals_snapshot,
            ranked_causes = EXCLUDED.ranked_causes,
            remediation_actions = EXCLUDED.remediation_actions,
            sonnet_analysis = EXCLUDED.sonnet_analysis,
            cache_read_tokens = EXCLUDED.cache_read_tokens,
            cache_creation_tokens = EXCLUDED.cache_creation_tokens,
            input_tokens = EXCLUDED.input_tokens,
            output_tokens = EXCLUDED.output_tokens,
            updated_at = NOW()
        RETURNING id
    """), {
        "id": record_id,
        "tenant_id": tenant_id,
        "store_id": signal_bundle.store_id,
        "analysis_month": signal_bundle.analysis_month,
        "analysis_type": analysis_type,
        "food_cost_fen": signal_bundle.food_cost_fen,
        "food_cost_budget_fen": signal_bundle.food_cost_budget_fen,
        "cost_overrun_pct": signal_bundle.cost_overrun_pct,
        "signals": json.dumps(signal_bundle.to_json_dict(), ensure_ascii=False),
        "causes": json.dumps(
            [
                {
                    "cause_type": c.cause_type,
                    "confidence": c.confidence,
                    "evidence": c.evidence,
                    "impact_fen": c.impact_fen,
                    "priority": c.priority,
                }
                for c in result.ranked_causes
            ],
            ensure_ascii=False,
        ),
        "actions": json.dumps(
            [
                {
                    "action": a.action,
                    "owner_role": a.owner_role,
                    "deadline_days": a.deadline_days,
                    "expected_savings_fen": a.expected_savings_fen,
                }
                for a in result.remediation_actions
            ],
            ensure_ascii=False,
        ),
        "sonnet_analysis": result.sonnet_analysis,
        "model_id": result.model_id,
        "cache_read": result.cache_read_tokens,
        "cache_creation": result.cache_creation_tokens,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    })
    await db.commit()
    logger.info(
        "cost_root_cause_saved store=%s month=%s causes=%d cache_hit=%.2f",
        signal_bundle.store_id,
        signal_bundle.analysis_month,
        len(result.ranked_causes),
        result.cache_hit_rate,
    )
    return record_id


__all__ = [
    "CachedPromptBuilder",
    "CostRootCauseService",
    "CostSignalBundle",
    "RawMaterialPriceChange",
    "WasteEvent",
    "BOMDeviation",
    "RootCause",
    "RemediationAction",
    "RootCauseAnalysisResult",
    "parse_sonnet_response",
    "save_analysis_to_db",
    "SONNET_CACHED_MODEL",
    "CACHE_HIT_TARGET",
    "COST_OVERRUN_TRIGGER_PCT",
]
