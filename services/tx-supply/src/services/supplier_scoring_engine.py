"""供应商评分引擎 — 规则评分 + AI 洞察（DB 持久化版）

设计原则：
  - 评分数据来源：从 purchasing_orders / receiving_orders 表 SQL 聚合（不依赖内存缓存）
  - AI 洞察是可选的：composite_score < 70 或首次月报才触发（控成本）
  - 如果相关表不存在（迁移未运行），优雅降级并记录 WARNING
  - Repository 模式：Engine → DB（直接通过 AsyncSession）
  - 所有 AI 调用必须通过 ModelRouter（禁止直接调用 API）

五维度对应 v064 supplier_score_history 表结构：
  delivery_rate    — 交货率（0-1）
  quality_rate     — 品质合格率（0-1）
  price_stability  — 价格稳定性（0-1）
  response_speed   — 响应速度（0-1）
  compliance_rate  — 合规率（0-1）
  composite_score  — 加权综合分（0-100）
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

log = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

SCORE_WEIGHTS: dict[str, float] = {
    "delivery_rate": 0.30,      # 交货率（最重要）
    "quality_rate": 0.25,       # 品质合格率
    "price_stability": 0.20,    # 价格稳定性
    "response_speed": 0.15,     # 响应速度
    "compliance_rate": 0.10,    # 合规率
}

TIER_THRESHOLDS: dict[str, int] = {
    "premium": 85,    # 优质供应商
    "qualified": 70,  # 合格
    "watch": 55,      # 观察期
    "eliminate": 0,   # 淘汰候选
}

# AI 洞察触发阈值：低于此分数才触发（或首次月报）
_AI_TRIGGER_SCORE_THRESHOLD = 70.0

# AI 洞察 Prompt 系统角色
_AI_SYSTEM_PROMPT = (
    "你是屯象OS供应链风险分析师。"
    "请根据供应商五维度评分数据，生成简洁、可操作的洞察报告，"
    "重点说明风险点与改进建议，文字不超过200字。"
)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic 数据模型
# ─────────────────────────────────────────────────────────────────────────────

class DimensionScores(BaseModel):
    """五维度原始评分（均为 0-1 小数）"""
    delivery_rate: float = Field(ge=0.0, le=1.0, description="交货率")
    quality_rate: float = Field(ge=0.0, le=1.0, description="品质合格率")
    price_stability: float = Field(ge=0.0, le=1.0, description="价格稳定性")
    response_speed: float = Field(ge=0.0, le=1.0, description="响应速度")
    compliance_rate: float = Field(ge=0.0, le=1.0, description="合规率")


class SupplierScoreResult(BaseModel):
    """calculate_period_score 返回值"""
    supplier_id: str
    tenant_id: str
    period_start: date
    period_end: date
    dimensions: DimensionScores
    composite_score: float = Field(ge=0.0, le=100.0)
    tier: str  # premium / qualified / watch / eliminate
    ai_insight: Optional[str] = None
    history_id: Optional[str] = None  # 写入 DB 后的 UUID


# ─────────────────────────────────────────────────────────────────────────────
# SupplierScoringEngine
# ─────────────────────────────────────────────────────────────────────────────

class SupplierScoringEngine:
    """供应商评分引擎：规则评分 + AI 洞察

    公式：composite_score = sum(维度值 × 权重) × 100，范围 0-100
    AI 触发策略：composite_score < 70 或 is_first_monthly=True 时才调用 ModelRouter
    """

    # ──────────────────────────────────────────────────────────────────────
    # 核心计算方法（纯函数，无副作用，便于单元测试）
    # ──────────────────────────────────────────────────────────────────────

    def _compute_composite(self, dims: DimensionScores) -> float:
        """加权计算综合分，结果为 0-100 浮点数。"""
        raw = (
            dims.delivery_rate    * SCORE_WEIGHTS["delivery_rate"]
            + dims.quality_rate   * SCORE_WEIGHTS["quality_rate"]
            + dims.price_stability * SCORE_WEIGHTS["price_stability"]
            + dims.response_speed * SCORE_WEIGHTS["response_speed"]
            + dims.compliance_rate * SCORE_WEIGHTS["compliance_rate"]
        )
        # 乘以 100 并钳位到 [0, 100]
        return round(min(100.0, max(0.0, raw * 100)), 2)

    def _should_trigger_ai(self, composite_score: float, is_first_monthly: bool) -> bool:
        """判断是否需要调用 AI 洞察（控成本）。

        条件：
          - composite_score < 70（高风险供应商）
          - 或 is_first_monthly（首次月报，建立基线）
        """
        return composite_score < _AI_TRIGGER_SCORE_THRESHOLD or is_first_monthly

    def _build_score_history_record(
        self,
        supplier_id: str,
        tenant_id: str,
        period_start: date,
        period_end: date,
        dimensions: DimensionScores,
        composite_score: float,
        ai_insight: Optional[str],
    ) -> dict[str, Any]:
        """构建符合 supplier_score_history 表结构的字典（用于 SQL INSERT）。"""
        return {
            "tenant_id": tenant_id,
            "supplier_id": supplier_id,
            "period_start": period_start,
            "period_end": period_end,
            "delivery_rate": dimensions.delivery_rate,
            "quality_rate": dimensions.quality_rate,
            "price_stability": dimensions.price_stability,
            "response_speed": dimensions.response_speed,
            "compliance_rate": dimensions.compliance_rate,
            "composite_score": composite_score,
            "ai_insight": ai_insight,
        }

    # ──────────────────────────────────────────────────────────────────────
    # 供应商分级
    # ──────────────────────────────────────────────────────────────────────

    async def get_supplier_tier(self, composite_score: float) -> str:
        """根据综合分返回供应商分级（premium/qualified/watch/eliminate）。"""
        if composite_score >= TIER_THRESHOLDS["premium"]:
            return "premium"
        if composite_score >= TIER_THRESHOLDS["qualified"]:
            return "qualified"
        if composite_score >= TIER_THRESHOLDS["watch"]:
            return "watch"
        return "eliminate"

    # ──────────────────────────────────────────────────────────────────────
    # AI 洞察生成（通过 ModelRouter）
    # ──────────────────────────────────────────────────────────────────────

    async def generate_ai_insight(
        self,
        supplier_name: str,
        scores: dict[str, Any],
        history: list[dict[str, Any]],
        model_router: Any,
    ) -> str:
        """调用 ModelRouter 生成 AI 洞察文本。

        Args:
            supplier_name: 供应商名称
            scores: 当期五维度分及综合分 dict
            history: 近期历史评分列表（最多3期）
            model_router: ModelRouter 实例，通过其 complete() 调用 AI

        Returns:
            AI 生成的洞察文字；调用失败时返回空字符串（优雅降级）

        注意：
            必须通过 model_router.complete(task_type, prompt, system_prompt)
            禁止直接调用 anthropic API。
        """
        # 构建 prompt
        current_text = (
            f"供应商：{supplier_name}\n"
            f"当期综合分：{scores.get('composite_score', 'N/A')}\n"
            f"交货率：{scores.get('delivery_rate', 'N/A')}\n"
            f"品质合格率：{scores.get('quality_rate', 'N/A')}\n"
            f"价格稳定性：{scores.get('price_stability', 'N/A')}\n"
            f"响应速度：{scores.get('response_speed', 'N/A')}\n"
            f"合规率：{scores.get('compliance_rate', 'N/A')}\n"
        )

        if history:
            history_lines = []
            for h in history[-3:]:  # 最近3期
                line = (
                    f"  {h.get('period_start', '')} ~ {h.get('period_end', '')}："
                    f"综合分 {h.get('composite_score', 'N/A')}"
                )
                history_lines.append(line)
            current_text += "历史评分：\n" + "\n".join(history_lines) + "\n"

        # 风险提示
        risk_dims = []
        for dim, threshold in [
            ("delivery_rate", 0.80),
            ("quality_rate", 0.80),
            ("compliance_rate", 0.85),
        ]:
            val = scores.get(dim)
            if val is not None and val < threshold:
                risk_dims.append(f"{dim}={val:.2f}（低于基准 {threshold}）")
        if risk_dims:
            current_text += "主要风险：" + "，".join(risk_dims) + "\n"

        current_text += "\n请生成简洁的供应商洞察报告（不超过200字）。"

        try:
            insight = await model_router.complete(
                "supplier_insight",
                current_text,
                _AI_SYSTEM_PROMPT,
            )
            return insight or ""
        except Exception as exc:  # noqa: BLE001 — AI 调用失败优雅降级，必须兜底
            log.warning(
                "supplier_scoring.ai_insight_failed",
                supplier_name=supplier_name,
                error=str(exc),
                exc_info=True,
            )
            return ""

    # ──────────────────────────────────────────────────────────────────────
    # 从 DB 聚合五维度数据
    # ──────────────────────────────────────────────────────────────────────

    async def _aggregate_dimensions_from_db(
        self,
        supplier_id: str,
        tenant_id: str,
        period_start: date,
        period_end: date,
        db: Any,  # AsyncSession
    ) -> Optional[DimensionScores]:
        """从 purchasing_orders / receiving_orders 聚合五维度原始数据。

        如果相关表不存在（迁移未运行），返回 None 并记录 WARNING。
        """
        # ── 1. delivery_rate：按时交货率 ──────────────────────────────────
        # purchasing_orders: status='received', actual_delivery_date <= promised_date
        delivery_sql = text("""
            SELECT
                COUNT(*) FILTER (WHERE actual_delivery_date <= promised_date) AS on_time_cnt,
                COUNT(*) AS total_cnt
            FROM purchasing_orders
            WHERE tenant_id = :tenant_id
              AND supplier_id = :supplier_id::TEXT
              AND created_at::DATE BETWEEN :start AND :end
              AND is_deleted = FALSE
        """)

        # ── 2. quality_rate：收货验收合格率 ──────────────────────────────
        quality_sql = text("""
            SELECT
                COUNT(*) FILTER (WHERE quality_status = 'passed') AS passed_cnt,
                COUNT(*) AS total_cnt
            FROM receiving_orders
            WHERE tenant_id = :tenant_id
              AND supplier_id = :supplier_id::TEXT
              AND received_at::DATE BETWEEN :start AND :end
              AND is_deleted = FALSE
        """)

        # ── 3. price_stability：价格波动率（低波动 = 高稳定性）────────────
        price_sql = text("""
            SELECT
                STDDEV(unit_price_fen) / NULLIF(AVG(unit_price_fen), 0) AS price_cv
            FROM purchasing_orders
            WHERE tenant_id = :tenant_id
              AND supplier_id = :supplier_id::TEXT
              AND created_at::DATE BETWEEN :start AND :end
              AND is_deleted = FALSE
              AND unit_price_fen > 0
        """)

        # ── 4. response_speed：平均响应天数（需求到确认单）─────────────────
        response_sql = text("""
            SELECT
                AVG(EXTRACT(EPOCH FROM (confirmed_at - created_at)) / 86400.0) AS avg_response_days
            FROM purchasing_orders
            WHERE tenant_id = :tenant_id
              AND supplier_id = :supplier_id::TEXT
              AND created_at::DATE BETWEEN :start AND :end
              AND is_deleted = FALSE
              AND confirmed_at IS NOT NULL
        """)

        # ── 5. compliance_rate：合规文件提交率 ──────────────────────────
        compliance_sql = text("""
            SELECT
                COUNT(*) FILTER (WHERE compliance_docs_submitted = TRUE) AS compliant_cnt,
                COUNT(*) AS total_cnt
            FROM receiving_orders
            WHERE tenant_id = :tenant_id
              AND supplier_id = :supplier_id::TEXT
              AND received_at::DATE BETWEEN :start AND :end
              AND is_deleted = FALSE
        """)

        params = {
            "tenant_id": tenant_id,
            "supplier_id": supplier_id,
            "start": period_start,
            "end": period_end,
        }

        try:
            # ── delivery_rate ──
            row = (await db.execute(delivery_sql, params)).fetchone()
            total = row.total_cnt if row and row.total_cnt else 0
            delivery_rate = (row.on_time_cnt / total) if total > 0 else 0.0

            # ── quality_rate ──
            row = (await db.execute(quality_sql, params)).fetchone()
            total = row.total_cnt if row and row.total_cnt else 0
            quality_rate = (row.passed_cnt / total) if total > 0 else 0.0

            # ── price_stability：CV=0 表示完全稳定=1.0，CV 越高分越低 ──
            row = (await db.execute(price_sql, params)).fetchone()
            price_cv = float(row.price_cv) if row and row.price_cv is not None else 0.0
            price_stability = max(0.0, min(1.0, 1.0 - price_cv))

            # ── response_speed：3天以内为满分，超过7天为0分 ──
            row = (await db.execute(response_sql, params)).fetchone()
            avg_days = float(row.avg_response_days) if row and row.avg_response_days is not None else 3.0
            response_speed = max(0.0, min(1.0, (7.0 - avg_days) / 4.0))

            # ── compliance_rate ──
            row = (await db.execute(compliance_sql, params)).fetchone()
            total = row.total_cnt if row and row.total_cnt else 0
            compliance_rate = (row.compliant_cnt / total) if total > 0 else 1.0  # 无数据默认合规

            return DimensionScores(
                delivery_rate=round(delivery_rate, 4),
                quality_rate=round(quality_rate, 4),
                price_stability=round(price_stability, 4),
                response_speed=round(response_speed, 4),
                compliance_rate=round(compliance_rate, 4),
            )

        except (ProgrammingError, OperationalError) as exc:
            log.warning(
                "supplier_scoring.db_aggregate_failed",
                reason="相关表可能不存在，请检查迁移是否已运行（purchasing_orders/receiving_orders）",
                supplier_id=supplier_id,
                error=str(exc),
            )
            return None

    # ──────────────────────────────────────────────────────────────────────
    # 写入 supplier_score_history
    # ──────────────────────────────────────────────────────────────────────

    async def _persist_score(
        self,
        record: dict[str, Any],
        db: Any,  # AsyncSession
    ) -> Optional[str]:
        """将评分记录写入 supplier_score_history，返回新行的 UUID。"""
        insert_sql = text("""
            INSERT INTO supplier_score_history (
                tenant_id, supplier_id,
                period_start, period_end,
                delivery_rate, quality_rate, price_stability,
                response_speed, compliance_rate,
                composite_score, ai_insight
            ) VALUES (
                :tenant_id, :supplier_id::UUID,
                :period_start, :period_end,
                :delivery_rate, :quality_rate, :price_stability,
                :response_speed, :compliance_rate,
                :composite_score, :ai_insight
            )
            RETURNING id::TEXT
        """)
        try:
            result = await db.execute(insert_sql, record)
            row = result.fetchone()
            return row[0] if row else None
        except (ProgrammingError, OperationalError) as exc:
            log.warning(
                "supplier_scoring.persist_failed",
                reason="supplier_score_history 表可能不存在，请运行 v064 迁移",
                error=str(exc),
            )
            return None

    # ──────────────────────────────────────────────────────────────────────
    # 查询历史评分（用于 AI 对比）
    # ──────────────────────────────────────────────────────────────────────

    async def _fetch_recent_history(
        self,
        supplier_id: str,
        tenant_id: str,
        limit: int,
        db: Any,
    ) -> list[dict[str, Any]]:
        """查询供应商最近 N 期历史评分。"""
        sql = text("""
            SELECT
                id::TEXT, period_start, period_end, composite_score,
                delivery_rate, quality_rate, price_stability,
                response_speed, compliance_rate
            FROM supplier_score_history
            WHERE tenant_id = :tenant_id
              AND supplier_id = :supplier_id::UUID
              AND is_deleted = FALSE
            ORDER BY period_start DESC
            LIMIT :limit
        """)
        try:
            rows = (await db.execute(sql, {
                "tenant_id": tenant_id,
                "supplier_id": supplier_id,
                "limit": limit,
            })).fetchall()
            return [dict(r._mapping) for r in rows]
        except (ProgrammingError, OperationalError) as exc:
            log.warning(
                "supplier_scoring.history_fetch_failed",
                error=str(exc),
            )
            return []

    async def _is_first_monthly_score(
        self,
        supplier_id: str,
        tenant_id: str,
        period_start: date,
        db: Any,
    ) -> bool:
        """判断是否为当月首次评分（用于决定是否触发 AI 洞察月报）。"""
        sql = text("""
            SELECT COUNT(*) AS cnt
            FROM supplier_score_history
            WHERE tenant_id = :tenant_id
              AND supplier_id = :supplier_id::UUID
              AND DATE_TRUNC('month', period_start) = DATE_TRUNC('month', :period_start)
              AND is_deleted = FALSE
        """)
        try:
            row = (await db.execute(sql, {
                "tenant_id": tenant_id,
                "supplier_id": supplier_id,
                "period_start": period_start,
            })).fetchone()
            return (row.cnt == 0) if row else True
        except (ProgrammingError, OperationalError):
            return True  # 无法查询时默认触发

    # ──────────────────────────────────────────────────────────────────────
    # 主入口：计算指定周期的供应商综合评分
    # ──────────────────────────────────────────────────────────────────────

    async def calculate_period_score(
        self,
        supplier_id: str,
        supplier_name: str,
        tenant_id: str,
        period_start: date,
        period_end: date,
        db: Any,  # AsyncSession
        model_router: Optional[Any] = None,
    ) -> SupplierScoreResult:
        """计算指定周期的供应商综合评分。

        流程：
          1. 设置租户 RLS 上下文
          2. 从 DB 采购/收货记录聚合五维度原始数据
          3. 加权计算综合分
          4. 写入 supplier_score_history
          5. 仅当 composite_score < 70 或首次月报时触发 AI 洞察（控成本）

        Args:
            supplier_id: 供应商 UUID（对应 supplier_profiles.id）
            supplier_name: 供应商名称（用于 AI prompt）
            tenant_id: 租户 UUID
            period_start: 评分周期开始日期
            period_end: 评分周期结束日期
            db: AsyncSession
            model_router: ModelRouter 实例（可选，None 时跳过 AI 洞察）

        Returns:
            SupplierScoreResult
        """
        log.info(
            "supplier_scoring.calculate_started",
            supplier_id=supplier_id,
            period_start=str(period_start),
            period_end=str(period_end),
        )

        # ── 1. 设置 RLS 租户上下文 ──
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        # ── 2. 聚合五维度原始数据 ──
        dims = await self._aggregate_dimensions_from_db(
            supplier_id, tenant_id, period_start, period_end, db
        )
        if dims is None:
            # 优雅降级：DB 聚合失败，使用 0 值（表示无数据）
            log.warning(
                "supplier_scoring.using_zero_fallback",
                supplier_id=supplier_id,
                reason="DB 聚合失败，使用零值降级",
            )
            dims = DimensionScores(
                delivery_rate=0.0,
                quality_rate=0.0,
                price_stability=0.0,
                response_speed=0.0,
                compliance_rate=0.0,
            )

        # ── 3. 计算综合分 ──
        composite_score = self._compute_composite(dims)
        tier = await self.get_supplier_tier(composite_score)

        # ── 4. 判断是否触发 AI 洞察 ──
        ai_insight: Optional[str] = None
        if model_router is not None:
            is_first_monthly = await self._is_first_monthly_score(
                supplier_id, tenant_id, period_start, db
            )
            if self._should_trigger_ai(composite_score, is_first_monthly):
                history = await self._fetch_recent_history(supplier_id, tenant_id, 3, db)
                ai_insight = await self.generate_ai_insight(
                    supplier_name=supplier_name,
                    scores={
                        "composite_score": composite_score,
                        "delivery_rate": dims.delivery_rate,
                        "quality_rate": dims.quality_rate,
                        "price_stability": dims.price_stability,
                        "response_speed": dims.response_speed,
                        "compliance_rate": dims.compliance_rate,
                    },
                    history=history,
                    model_router=model_router,
                )
                log.info(
                    "supplier_scoring.ai_insight_generated",
                    supplier_id=supplier_id,
                    has_insight=bool(ai_insight),
                )
            else:
                log.info(
                    "supplier_scoring.ai_insight_skipped",
                    supplier_id=supplier_id,
                    composite_score=composite_score,
                    reason="分数达标且非首次月报，跳过 AI 调用（控成本）",
                )

        # ── 5. 写入 supplier_score_history ──
        record = self._build_score_history_record(
            supplier_id=supplier_id,
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            dimensions=dims,
            composite_score=composite_score,
            ai_insight=ai_insight,
        )
        history_id = await self._persist_score(record, db)

        log.info(
            "supplier_scoring.calculate_completed",
            supplier_id=supplier_id,
            composite_score=composite_score,
            tier=tier,
            history_id=history_id,
        )

        return SupplierScoreResult(
            supplier_id=supplier_id,
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            dimensions=dims,
            composite_score=composite_score,
            tier=tier,
            ai_insight=ai_insight,
            history_id=history_id,
        )
