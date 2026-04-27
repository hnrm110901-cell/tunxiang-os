"""Campaign自优化服务 — AB测试评估→自动调整/人类审批闭环

核心流程：
  1. 为营销任务创建AB测试变体（内容/渠道/时段）
  2. 定期评估变体效果（双比例z检验）
  3. 显著性达标→自动应用优胜变体 或 提交人类审批
  4. 记录每轮优化日志(campaign_optimization_logs)

集成点：
  - AB测试框架(ab_test_service) — 创建/评估AB测试
  - 审批服务(approval_service) — 高预算变更需人工审批
  - 营销任务(marketing_task_service) — 应用优化结果到任务
  - ROI归因(roi_attribution) — 读取转化数据计算ROI
"""

import json
import math
import uuid
from typing import Any, Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)


class CampaignOptimizationError(Exception):
    """Campaign自优化业务异常"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------

# AB测试最小样本量（每组至少30次送达才有统计意义）
MIN_SAMPLE_SIZE = 30

# 默认p-value阈值：低于此值认为差异显著
DEFAULT_P_VALUE_THRESHOLD = 0.05

# 高预算变更阈值：超过此百分比需要人工审批
HIGH_BUDGET_SHIFT_THRESHOLD = 30  # percent

# 自动应用的最大预算偏移
AUTO_APPLY_MAX_BUDGET_SHIFT = 20  # percent


class CampaignOptimizer:
    """Campaign自优化引擎

    职责：
      - create_optimization: 为Campaign创建优化计划（含AB测试）
      - evaluate_round: 评估当前优化轮次的AB测试结果
      - apply_optimization: 应用优化结果到营销任务
      - get_optimization_history: 查询Campaign的优化历史
    """

    # ===================================================================
    # 创建优化
    # ===================================================================

    async def create_optimization(
        self,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        db: Any,
        *,
        marketing_task_id: Optional[uuid.UUID] = None,
        ab_test_id: Optional[uuid.UUID] = None,
        auto_apply_threshold: float = DEFAULT_P_VALUE_THRESHOLD,
    ) -> dict:
        """为Campaign创建优化记录（第1轮）"""
        opt_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO campaign_optimization_logs (
                    id, tenant_id, campaign_id, marketing_task_id,
                    ab_test_id, optimization_round, status,
                    auto_apply_threshold
                ) VALUES (
                    :id, :tenant_id, :campaign_id, :marketing_task_id,
                    :ab_test_id, 1, 'evaluating',
                    :auto_apply_threshold
                )
            """),
            {
                "id": str(opt_id),
                "tenant_id": str(tenant_id),
                "campaign_id": str(campaign_id),
                "marketing_task_id": str(marketing_task_id) if marketing_task_id else None,
                "ab_test_id": str(ab_test_id) if ab_test_id else None,
                "auto_apply_threshold": auto_apply_threshold,
            },
        )
        log.info(
            "optimization_created",
            opt_id=str(opt_id),
            campaign_id=str(campaign_id),
        )
        return {"optimization_id": str(opt_id), "round": 1}

    # ===================================================================
    # 评估优化轮次
    # ===================================================================

    async def evaluate_round(
        self,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        db: Any,
        *,
        variant_a_metrics: dict[str, Any],
        variant_b_metrics: dict[str, Any],
    ) -> dict:
        """评估当前优化轮次的AB测试结果

        1. 获取最新evaluating状态的优化记录
        2. 计算双比例z检验p-value
        3. 根据p-value和预算偏移量决定：auto_applied / pending_approval / inconclusive
        """
        # 获取当前优化记录
        result = await db.execute(
            text("""
                SELECT * FROM campaign_optimization_logs
                WHERE tenant_id = :tenant_id
                  AND campaign_id = :campaign_id
                  AND status = 'evaluating'
                  AND is_deleted = FALSE
                ORDER BY optimization_round DESC
                LIMIT 1
            """),
            {"tenant_id": str(tenant_id), "campaign_id": str(campaign_id)},
        )
        row = result.mappings().first()
        if row is None:
            raise CampaignOptimizationError("NOT_FOUND", f"Campaign {campaign_id} 无进行中的优化轮次")

        opt_id = row["id"]
        current_round = row["optimization_round"]
        threshold = row["auto_apply_threshold"] or DEFAULT_P_VALUE_THRESHOLD

        # 提取样本量和转化率
        sample_a = variant_a_metrics.get("send_count", 0)
        sample_b = variant_b_metrics.get("send_count", 0)
        conv_a = variant_a_metrics.get("conversion_rate", 0.0)
        conv_b = variant_b_metrics.get("conversion_rate", 0.0)

        # 样本量不足 → 保持evaluating
        if sample_a < MIN_SAMPLE_SIZE or sample_b < MIN_SAMPLE_SIZE:
            await db.execute(
                text("""
                    UPDATE campaign_optimization_logs
                    SET variant_a_metrics = :va::jsonb,
                        variant_b_metrics = :vb::jsonb,
                        sample_size_a = :sa,
                        sample_size_b = :sb,
                        updated_at = NOW()
                    WHERE id = :id
                """),
                {
                    "id": str(opt_id),
                    "va": json.dumps(variant_a_metrics),
                    "vb": json.dumps(variant_b_metrics),
                    "sa": sample_a,
                    "sb": sample_b,
                },
            )
            log.info(
                "optimization_insufficient_sample",
                opt_id=str(opt_id),
                sample_a=sample_a,
                sample_b=sample_b,
                min_required=MIN_SAMPLE_SIZE,
            )
            return {
                "optimization_id": str(opt_id),
                "round": current_round,
                "status": "evaluating",
                "reason": f"样本量不足(A:{sample_a}, B:{sample_b}, 最小:{MIN_SAMPLE_SIZE})",
            }

        # 双比例z检验
        p_value = self._two_proportion_z_test(conv_a, sample_a, conv_b, sample_b)

        # 判定赢家
        if p_value < threshold:
            winner = "a" if conv_a > conv_b else "b"
            # 计算建议的预算偏移
            lift_pct = abs(conv_a - conv_b) / max(min(conv_a, conv_b), 0.001) * 100
            budget_shift = min(int(lift_pct * 2), 100)  # lift越大偏移越多，上限100%
        else:
            winner = "inconclusive"
            budget_shift = 0

        # 决定是自动应用还是需要人工审批
        if winner == "inconclusive":
            new_status = "evaluating"  # 继续观察
        elif budget_shift <= AUTO_APPLY_MAX_BUDGET_SHIFT:
            new_status = "auto_applied"
        else:
            new_status = "pending_approval"

        adjustment_action = {
            "type": "shift_budget",
            "winner": winner,
            "budget_shift_pct": budget_shift,
            "lift_pct": round(lift_pct, 2) if winner != "inconclusive" else 0,
            "recommendation": (
                f"变体{winner.upper()}转化率更高({conv_a:.2%} vs {conv_b:.2%})，"
                f"建议将{budget_shift}%预算偏向变体{winner.upper()}"
            )
            if winner != "inconclusive"
            else "差异不显著，继续观察",
        }

        await db.execute(
            text("""
                UPDATE campaign_optimization_logs
                SET variant_a_metrics = :va::jsonb,
                    variant_b_metrics = :vb::jsonb,
                    sample_size_a = :sa,
                    sample_size_b = :sb,
                    winner = :winner,
                    p_value = :p_value,
                    adjustment_action = :adj::jsonb,
                    status = :status,
                    budget_shift_pct = :budget_shift,
                    applied_at = CASE WHEN :status = 'auto_applied' THEN NOW() ELSE NULL END,
                    updated_at = NOW()
                WHERE id = :id
            """),
            {
                "id": str(opt_id),
                "va": json.dumps(variant_a_metrics),
                "vb": json.dumps(variant_b_metrics),
                "sa": sample_a,
                "sb": sample_b,
                "winner": winner,
                "p_value": p_value,
                "adj": json.dumps(adjustment_action),
                "status": new_status,
                "budget_shift": budget_shift,
            },
        )

        log.info(
            "optimization_evaluated",
            opt_id=str(opt_id),
            round=current_round,
            winner=winner,
            p_value=round(p_value, 4),
            status=new_status,
            budget_shift=budget_shift,
        )

        return {
            "optimization_id": str(opt_id),
            "round": current_round,
            "status": new_status,
            "winner": winner,
            "p_value": round(p_value, 4),
            "adjustment": adjustment_action,
            "budget_shift_pct": budget_shift,
        }

    # ===================================================================
    # 审批 & 应用
    # ===================================================================

    async def approve_optimization(
        self,
        tenant_id: uuid.UUID,
        optimization_id: uuid.UUID,
        approved_by: uuid.UUID,
        db: Any,
    ) -> dict:
        """审批并应用优化结果"""
        result = await db.execute(
            text("""
                SELECT * FROM campaign_optimization_logs
                WHERE tenant_id = :tenant_id
                  AND id = :opt_id
                  AND status = 'pending_approval'
                  AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "opt_id": str(optimization_id)},
        )
        row = result.mappings().first()
        if row is None:
            raise CampaignOptimizationError("NOT_FOUND", "优化记录不存在或非待审批状态")

        await db.execute(
            text("""
                UPDATE campaign_optimization_logs
                SET status = 'approved',
                    approved_by = :approved_by,
                    approved_at = NOW(),
                    updated_at = NOW()
                WHERE id = :opt_id
            """),
            {"opt_id": str(optimization_id), "approved_by": str(approved_by)},
        )

        log.info(
            "optimization_approved",
            opt_id=str(optimization_id),
            approved_by=str(approved_by),
        )
        return {"optimization_id": str(optimization_id), "status": "approved"}

    async def reject_optimization(
        self,
        tenant_id: uuid.UUID,
        optimization_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """拒绝优化建议"""
        await db.execute(
            text("""
                UPDATE campaign_optimization_logs
                SET status = 'rejected', updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :opt_id
                  AND status = 'pending_approval'
                  AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "opt_id": str(optimization_id)},
        )
        log.info("optimization_rejected", opt_id=str(optimization_id))
        return {"optimization_id": str(optimization_id), "status": "rejected"}

    async def apply_optimization(
        self,
        tenant_id: uuid.UUID,
        optimization_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """应用已审批的优化结果

        将budget_shift_pct写入营销任务配置，并启动下一轮优化
        """
        result = await db.execute(
            text("""
                SELECT * FROM campaign_optimization_logs
                WHERE tenant_id = :tenant_id
                  AND id = :opt_id
                  AND status IN ('approved', 'auto_applied')
                  AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "opt_id": str(optimization_id)},
        )
        row = result.mappings().first()
        if row is None:
            raise CampaignOptimizationError("NOT_FOUND", "优化记录不存在或未审批")

        # 标记已应用
        await db.execute(
            text("""
                UPDATE campaign_optimization_logs
                SET status = 'applied',
                    applied_at = NOW(),
                    updated_at = NOW()
                WHERE id = :opt_id
            """),
            {"opt_id": str(optimization_id)},
        )

        # 创建下一轮优化记录
        next_round = row["optimization_round"] + 1
        next_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO campaign_optimization_logs (
                    id, tenant_id, campaign_id, marketing_task_id,
                    ab_test_id, optimization_round, status,
                    auto_apply_threshold
                ) VALUES (
                    :id, :tenant_id, :campaign_id, :marketing_task_id,
                    :ab_test_id, :round, 'evaluating',
                    :threshold
                )
            """),
            {
                "id": str(next_id),
                "tenant_id": str(tenant_id),
                "campaign_id": str(row["campaign_id"]),
                "marketing_task_id": str(row["marketing_task_id"]) if row["marketing_task_id"] else None,
                "ab_test_id": str(row["ab_test_id"]) if row["ab_test_id"] else None,
                "round": next_round,
                "threshold": row["auto_apply_threshold"],
            },
        )

        log.info(
            "optimization_applied",
            opt_id=str(optimization_id),
            next_round=next_round,
            next_id=str(next_id),
            budget_shift=row["budget_shift_pct"],
        )

        return {
            "optimization_id": str(optimization_id),
            "status": "applied",
            "budget_shift_pct": row["budget_shift_pct"],
            "winner": row["winner"],
            "next_round": next_round,
            "next_optimization_id": str(next_id),
        }

    # ===================================================================
    # 查询
    # ===================================================================

    async def get_optimization_history(
        self,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        db: Any,
        *,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """查询Campaign的全部优化轮次"""
        offset = (page - 1) * size

        count_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM campaign_optimization_logs
                WHERE tenant_id = :tenant_id
                  AND campaign_id = :campaign_id
                  AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "campaign_id": str(campaign_id)},
        )
        total = count_result.scalar() or 0

        result = await db.execute(
            text("""
                SELECT * FROM campaign_optimization_logs
                WHERE tenant_id = :tenant_id
                  AND campaign_id = :campaign_id
                  AND is_deleted = FALSE
                ORDER BY optimization_round DESC
                LIMIT :size OFFSET :offset
            """),
            {
                "tenant_id": str(tenant_id),
                "campaign_id": str(campaign_id),
                "size": size,
                "offset": offset,
            },
        )
        rows = [dict(r) for r in result.mappings().all()]

        return {"items": rows, "total": total, "page": page, "size": size}

    async def get_latest_optimization(
        self,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        db: Any,
    ) -> Optional[dict]:
        """获取Campaign最新一轮优化状态"""
        result = await db.execute(
            text("""
                SELECT * FROM campaign_optimization_logs
                WHERE tenant_id = :tenant_id
                  AND campaign_id = :campaign_id
                  AND is_deleted = FALSE
                ORDER BY optimization_round DESC
                LIMIT 1
            """),
            {"tenant_id": str(tenant_id), "campaign_id": str(campaign_id)},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    # ===================================================================
    # 统计
    # ===================================================================

    async def get_optimization_dashboard(
        self,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """获取租户维度的优化大盘数据"""
        result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_rounds,
                    COUNT(*) FILTER (WHERE status = 'applied' OR status = 'auto_applied') AS applied_count,
                    COUNT(*) FILTER (WHERE status = 'rejected') AS rejected_count,
                    COUNT(*) FILTER (WHERE status = 'evaluating') AS evaluating_count,
                    COUNT(*) FILTER (WHERE status = 'pending_approval') AS pending_count,
                    AVG(budget_shift_pct) FILTER (WHERE status IN ('applied', 'auto_applied')) AS avg_budget_shift,
                    AVG(p_value) FILTER (WHERE p_value IS NOT NULL) AS avg_p_value,
                    COUNT(DISTINCT campaign_id) AS campaigns_optimized
                FROM campaign_optimization_logs
                WHERE tenant_id = :tenant_id AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id)},
        )
        row = result.mappings().first()
        return {
            "total_rounds": row["total_rounds"] if row else 0,
            "applied_count": row["applied_count"] if row else 0,
            "rejected_count": row["rejected_count"] if row else 0,
            "evaluating_count": row["evaluating_count"] if row else 0,
            "pending_count": row["pending_count"] if row else 0,
            "avg_budget_shift": round(float(row["avg_budget_shift"] or 0), 1),
            "avg_p_value": round(float(row["avg_p_value"] or 0), 4),
            "campaigns_optimized": row["campaigns_optimized"] if row else 0,
        }

    # ===================================================================
    # 私有方法
    # ===================================================================

    @staticmethod
    def _two_proportion_z_test(p1: float, n1: int, p2: float, n2: int) -> float:
        """双比例z检验 — 计算p-value

        H0: p1 == p2 (两组转化率无差异)
        H1: p1 != p2 (双侧检验)

        Returns: p-value (0-1)
        """
        if n1 == 0 or n2 == 0:
            return 1.0  # 无数据，不显著

        # 合并比例
        p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
        if p_pool == 0 or p_pool == 1:
            return 1.0  # 退化情况

        # z统计量
        se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
        if se == 0:
            return 1.0

        z = abs(p1 - p2) / se

        # 标准正态CDF近似（Abramowitz and Stegun 26.2.17）
        p_value = 2 * (1 - _normal_cdf(z))
        return max(0.0, min(1.0, p_value))


def _normal_cdf(x: float) -> float:
    """标准正态分布CDF（Abramowitz and Stegun近似，精度1.5e-7）"""
    if x < 0:
        return 1 - _normal_cdf(-x)
    b1 = 0.319381530
    b2 = -0.356563782
    b3 = 1.781477937
    b4 = -1.821255978
    b5 = 1.330274429
    p = 0.2316419
    t = 1.0 / (1.0 + p * x)
    t2 = t * t
    t3 = t2 * t
    t4 = t3 * t
    t5 = t4 * t
    pdf = math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
    return 1.0 - pdf * (b1 * t + b2 * t2 + b3 * t3 + b4 * t4 + b5 * t5)
