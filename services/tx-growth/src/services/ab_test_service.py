"""AB测试服务 — 实验创建/分组/转化记录/统计显著性检验/自动结论

分组算法：
  random:     hash(str(customer_id) + str(test_id)) % 100 < weight_A → A，否则 B
  rfm_based:  rfm_level in {"S1", "S2"} → A，否则 B
  store_based: hash(str(store_id)) % 2 == 0 → A，否则 B

统计检验：
  双比例 Z 检验（Two-proportion Z-test）
  p_value = 2 * (1 - Φ(|z|))
  is_significant = p_value < (1 - confidence_level)

金额单位：分(fen)
"""
import hashlib
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from models.ab_test import ABTest, ABTestAssignment
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 合法状态转换
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft":     ["running"],
    "running":   ["paused", "completed"],
    "paused":    ["running", "completed"],
    "completed": [],
}

# rfm_based 分流：这些等级走 A 组（高价值客户）
_RFM_GROUP_A: frozenset[str] = frozenset({"S1", "S2"})


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _stable_hash(value: str) -> int:
    """对字符串取 MD5 前8字节，转为无符号整数（用于稳定幂等分组）。"""
    digest = hashlib.md5(value.encode("utf-8")).digest()  # noqa: S324
    return int.from_bytes(digest[:8], "big")


def _norm_cdf(z: float) -> float:
    """标准正态累积分布函数 Φ(z)，使用 math.erfc 近似。

    Φ(z) = 0.5 * erfc(-z / sqrt(2))
    精度在 |z| ≤ 8 时优于 1e-7。
    """
    return 0.5 * math.erfc(-z / math.sqrt(2))


def _two_proportion_z_test(
    n1: int, conv1: int, n2: int, conv2: int
) -> tuple[float, float]:
    """双比例 Z 检验，返回 (z_value, p_value)。

    Args:
        n1:    A 组样本量
        conv1: A 组转化数
        n2:    B 组样本量
        conv2: B 组转化数

    Returns:
        (z, p_value)
        p_value 为双尾检验 p 值。
        若标准误差为 0（两组转化率相同或样本量不足），返回 (0.0, 1.0)。
    """
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0

    p1 = conv1 / n1
    p2 = conv2 / n2

    # 池化比例
    p_pool = (conv1 + conv2) / (n1 + n2)
    variance = p_pool * (1.0 - p_pool) * (1.0 / n1 + 1.0 / n2)

    if variance <= 0:
        return 0.0, 1.0

    se = math.sqrt(variance)
    z = (p2 - p1) / se
    # 双尾 p 值
    p_value = 2.0 * (1.0 - _norm_cdf(abs(z)))
    return z, p_value


# ---------------------------------------------------------------------------
# ABTestService
# ---------------------------------------------------------------------------

class ABTestService:
    """AB测试服务 — 实验全生命周期管理"""

    # ------------------------------------------------------------------
    # 创建实验
    # ------------------------------------------------------------------

    async def create_test(
        self,
        test_data: dict[str, Any],
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> ABTest:
        """创建AB测试实验。

        Args:
            test_data: {
                name: str,
                campaign_id: str | None,
                journey_id: str | None,
                split_type: str,       # random | rfm_based | store_based
                variants: list,        # [{variant, name, weight, content}]
                primary_metric: str,   # conversion_rate | revenue | click_rate
                min_sample_size: int,  # 默认 100
                confidence_level: float, # 默认 0.95
            }
            tenant_id: 租户 UUID
            db: AsyncSession

        Raises:
            ValueError: 变体权重之和不等于100，或变体数量不合法
        """
        variants: list[dict] = test_data.get("variants", [])
        if len(variants) < 2:
            raise ValueError("AB测试至少需要两个变体（A 和 B）")

        total_weight = sum(v.get("weight", 0) for v in variants)
        if total_weight != 100:
            raise ValueError(
                f"变体权重之和必须为 100，当前为 {total_weight}"
            )

        # 验证每个变体都有 variant 字段
        for v in variants:
            if "variant" not in v:
                raise ValueError(f"变体缺少 variant 字段: {v}")

        split_type = test_data.get("split_type", "random")
        if split_type not in ("random", "rfm_based", "store_based"):
            raise ValueError(
                f"不支持的分流类型: {split_type}，支持: random | rfm_based | store_based"
            )

        test = ABTest(
            tenant_id=tenant_id,
            name=test_data["name"],
            campaign_id=test_data.get("campaign_id"),
            journey_id=test_data.get("journey_id"),
            status="draft",
            split_type=split_type,
            variants=variants,
            primary_metric=test_data.get("primary_metric", "conversion_rate"),
            min_sample_size=test_data.get("min_sample_size", 100),
            confidence_level=test_data.get("confidence_level", 0.95),
        )
        db.add(test)
        await db.flush()

        log.info(
            "ab_test.created",
            test_id=str(test.id),
            name=test.name,
            split_type=split_type,
            tenant_id=str(tenant_id),
        )
        return test

    # ------------------------------------------------------------------
    # 用户分组（幂等）
    # ------------------------------------------------------------------

    async def assign_variant(
        self,
        test_id: uuid.UUID,
        customer_id: uuid.UUID,
        customer_data: dict[str, Any],
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> str:
        """为用户分配测试变体（幂等：同一用户同一测试始终分到同一组）。

        分配策略：
          random:     hash(str(customer_id) + str(test_id)) % 100 < weight_A → A，否则 B
          rfm_based:  rfm_level in {"S1", "S2"} → A，否则 B
          store_based: hash(str(store_id)) % 2 == 0 → A，否则 B

        使用 INSERT ON CONFLICT DO NOTHING 保证并发安全的幂等性。
        若记录已存在，读取并返回已有分组。

        Args:
            test_id:       AB测试 UUID
            customer_id:   客户 UUID
            customer_data: {"rfm_level": "S1", "store_id": "store_abc"}
            tenant_id:     租户 UUID
            db:            AsyncSession

        Returns:
            "A" 或 "B"

        Raises:
            ValueError: 测试不存在、状态不是 running、或未找到合适变体
        """
        # 1. 查询测试配置
        stmt = select(ABTest).where(
            ABTest.tenant_id == tenant_id,
            ABTest.id == test_id,
            ABTest.is_deleted.is_(False),
        )
        result = await db.execute(stmt)
        test: Optional[ABTest] = result.scalar_one_or_none()

        if test is None:
            raise ValueError(f"AB测试不存在: {test_id}")
        if test.status != "running":
            raise ValueError(
                f"AB测试未在运行中（当前状态: {test.status}），无法分配变体"
            )

        # 2. 检查是否已有分配记录
        existing_stmt = select(ABTestAssignment).where(
            ABTestAssignment.tenant_id == tenant_id,
            ABTestAssignment.test_id == test_id,
            ABTestAssignment.customer_id == customer_id,
        )
        existing_result = await db.execute(existing_stmt)
        existing: Optional[ABTestAssignment] = existing_result.scalar_one_or_none()

        if existing is not None:
            log.debug(
                "ab_test.assign_variant.cached",
                test_id=str(test_id),
                customer_id=str(customer_id),
                variant=existing.variant,
            )
            return existing.variant

        # 3. 按分流策略计算变体
        variant = self._compute_variant(
            test_id=test_id,
            customer_id=customer_id,
            customer_data=customer_data,
            split_type=test.split_type,
            variants=test.variants,
        )

        # 4. 幂等写入（INSERT ON CONFLICT DO NOTHING）
        now = datetime.now(timezone.utc)
        insert_stmt = (
            pg_insert(ABTestAssignment)
            .values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                test_id=test_id,
                customer_id=customer_id,
                variant=variant,
                is_converted=False,
                order_id=None,
                order_amount_fen=None,
                converted_at=None,
                assigned_at=now,
                created_at=now,
                updated_at=now,
                is_deleted=False,
            )
            .on_conflict_do_nothing(
                constraint="uq_ab_test_assignments_test_customer"
            )
        )
        await db.execute(insert_stmt)

        # 若 ON CONFLICT 触发，重新读取实际记录
        re_check = await db.execute(existing_stmt)
        final: Optional[ABTestAssignment] = re_check.scalar_one_or_none()
        actual_variant = final.variant if final else variant

        log.info(
            "ab_test.assign_variant",
            test_id=str(test_id),
            customer_id=str(customer_id),
            variant=actual_variant,
            split_type=test.split_type,
            tenant_id=str(tenant_id),
        )
        return actual_variant

    def _compute_variant(
        self,
        test_id: uuid.UUID,
        customer_id: uuid.UUID,
        customer_data: dict[str, Any],
        split_type: str,
        variants: list[dict],
    ) -> str:
        """根据分流策略计算变体（纯函数，不访问 DB）。

        variants 按 weight 降序视为 A、B……顺序分配。
        weight_A 即第一个变体的权重。
        """
        if split_type == "rfm_based":
            rfm_level: str = customer_data.get("rfm_level", "")
            return "A" if rfm_level in _RFM_GROUP_A else "B"

        if split_type == "store_based":
            store_id: str = str(customer_data.get("store_id", ""))
            return "A" if _stable_hash(store_id) % 2 == 0 else "B"

        # random（默认）
        hash_key = str(customer_id) + str(test_id)
        bucket = _stable_hash(hash_key) % 100

        # 按权重顺序分配变体
        cumulative = 0
        for v in variants:
            cumulative += v.get("weight", 0)
            if bucket < cumulative:
                return v["variant"]

        # 兜底（权重配置问题）
        return variants[-1]["variant"]

    # ------------------------------------------------------------------
    # 记录转化
    # ------------------------------------------------------------------

    async def record_conversion(
        self,
        test_id: uuid.UUID,
        customer_id: uuid.UUID,
        order_id: uuid.UUID,
        order_amount_fen: int,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """记录 AB 测试转化结果。

        若该用户在该测试中有分配记录，则更新转化字段。
        若未找到分配记录（用户未参与），静默忽略（无须创建记录）。

        Args:
            test_id:           AB测试 UUID
            customer_id:       客户 UUID
            order_id:          订单 UUID
            order_amount_fen:  订单金额（分）
            tenant_id:         租户 UUID
            db:                AsyncSession
        """
        now = datetime.now(timezone.utc)
        stmt = (
            update(ABTestAssignment)
            .where(
                ABTestAssignment.tenant_id == tenant_id,
                ABTestAssignment.test_id == test_id,
                ABTestAssignment.customer_id == customer_id,
                ABTestAssignment.is_converted.is_(False),
            )
            .values(
                is_converted=True,
                order_id=order_id,
                order_amount_fen=order_amount_fen,
                converted_at=now,
                updated_at=now,
            )
        )
        await db.execute(stmt)

        log.info(
            "ab_test.conversion_recorded",
            test_id=str(test_id),
            customer_id=str(customer_id),
            order_id=str(order_id),
            order_amount_fen=order_amount_fen,
            tenant_id=str(tenant_id),
        )

    # ------------------------------------------------------------------
    # 计算结果（含统计显著性）
    # ------------------------------------------------------------------

    async def calculate_results(
        self,
        test_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """计算AB测试结果，包含双比例 Z 检验统计显著性。

        Returns:
            {
                test_id: str,
                status: str,
                variants: [
                    {
                        variant: "A",
                        sample_size: int,
                        conversions: int,
                        conversion_rate: float,
                        avg_order_amount_fen: int,
                        total_revenue_fen: int,
                    }
                ],
                is_significant: bool,
                confidence: float,
                winner: "A" | "B" | None,
                p_value: float,
                z_value: float,
                recommendation: str,
            }
        """
        # 查询测试配置
        test_stmt = select(ABTest).where(
            ABTest.tenant_id == tenant_id,
            ABTest.id == test_id,
            ABTest.is_deleted.is_(False),
        )
        test_result = await db.execute(test_stmt)
        test: Optional[ABTest] = test_result.scalar_one_or_none()

        if test is None:
            raise ValueError(f"AB测试不存在: {test_id}")

        # 查询所有分配记录
        assignments_stmt = select(ABTestAssignment).where(
            ABTestAssignment.tenant_id == tenant_id,
            ABTestAssignment.test_id == test_id,
            ABTestAssignment.is_deleted.is_(False),
        )
        assignments_result = await db.execute(assignments_stmt)
        assignments: list[ABTestAssignment] = list(assignments_result.scalars().all())

        # 按变体分组统计
        variant_stats: dict[str, dict[str, Any]] = {}
        for v in test.variants:
            vname = v["variant"]
            variant_stats[vname] = {
                "variant": vname,
                "sample_size": 0,
                "conversions": 0,
                "total_revenue_fen": 0,
            }

        for assignment in assignments:
            vname = assignment.variant
            if vname not in variant_stats:
                variant_stats[vname] = {
                    "variant": vname,
                    "sample_size": 0,
                    "conversions": 0,
                    "total_revenue_fen": 0,
                }
            variant_stats[vname]["sample_size"] += 1
            if assignment.is_converted:
                variant_stats[vname]["conversions"] += 1
                variant_stats[vname]["total_revenue_fen"] += (
                    assignment.order_amount_fen or 0
                )

        # 计算派生指标
        variants_output: list[dict[str, Any]] = []
        for vname, stats in variant_stats.items():
            n = stats["sample_size"]
            conv = stats["conversions"]
            rev = stats["total_revenue_fen"]
            conversion_rate = round(conv / n, 4) if n > 0 else 0.0
            avg_order = rev // conv if conv > 0 else 0
            variants_output.append({
                "variant": vname,
                "sample_size": n,
                "conversions": conv,
                "conversion_rate": conversion_rate,
                "avg_order_amount_fen": avg_order,
                "total_revenue_fen": rev,
            })

        # 对有序变体排列（A 在前）
        variants_output.sort(key=lambda x: x["variant"])

        # 统计显著性检验（仅支持 A/B 两组）
        z_value = 0.0
        p_value = 1.0
        is_significant = False
        winner: Optional[str] = None
        recommendation = "样本量不足，继续收集数据"

        if len(variants_output) >= 2:
            va = next((v for v in variants_output if v["variant"] == "A"), None)
            vb = next((v for v in variants_output if v["variant"] == "B"), None)

            if va and vb:
                n1, conv1 = va["sample_size"], va["conversions"]
                n2, conv2 = vb["sample_size"], vb["conversions"]

                # 检查最小样本量
                if n1 >= test.min_sample_size and n2 >= test.min_sample_size:
                    z_value, p_value = _two_proportion_z_test(n1, conv1, n2, conv2)
                    alpha = 1.0 - test.confidence_level
                    is_significant = p_value < alpha

                    if is_significant:
                        # 按转化率决定胜者
                        if va["conversion_rate"] >= vb["conversion_rate"]:
                            winner = "A"
                            lift_pct = round(
                                (va["conversion_rate"] - vb["conversion_rate"])
                                / max(vb["conversion_rate"], 1e-9) * 100, 1
                            )
                            recommendation = (
                                f"A组转化率高于B组 {lift_pct}%，建议全量推广A版本"
                            )
                        else:
                            winner = "B"
                            lift_pct = round(
                                (vb["conversion_rate"] - va["conversion_rate"])
                                / max(va["conversion_rate"], 1e-9) * 100, 1
                            )
                            recommendation = (
                                f"B组转化率提升 {lift_pct}%，建议全量推广B版本"
                            )
                    else:
                        confidence_pct = round((1.0 - p_value) * 100, 1)
                        recommendation = (
                            f"差异尚未达到统计显著性（当前置信度 {confidence_pct}%，"
                            f"目标 {int(test.confidence_level * 100)}%），继续收集数据"
                        )
                else:
                    min_needed = test.min_sample_size
                    recommendation = (
                        f"样本量不足（需每组至少 {min_needed}，"
                        f"当前 A={n1}, B={n2}），继续收集数据"
                    )

        return {
            "test_id": str(test_id),
            "status": test.status,
            "variants": variants_output,
            "is_significant": is_significant,
            "confidence": round(1.0 - p_value, 4),
            "winner": winner,
            "p_value": round(p_value, 4),
            "z_value": round(z_value, 4),
            "recommendation": recommendation,
        }

    # ------------------------------------------------------------------
    # 自动结论
    # ------------------------------------------------------------------

    async def auto_conclude(
        self,
        test_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """自动结论：当满足最小样本量且达到统计显著性时，自动标记 winner。

        更新：test.status = "completed", test.winner_variant, test.ended_at

        Returns:
            {concluded: bool, winner: str | None, reason: str, results: dict}
        """
        results = await self.calculate_results(test_id, tenant_id, db)

        if not results["is_significant"]:
            return {
                "concluded": False,
                "winner": None,
                "reason": results["recommendation"],
                "results": results,
            }

        winner = results["winner"]
        now = datetime.now(timezone.utc)

        await db.execute(
            update(ABTest)
            .where(
                ABTest.tenant_id == tenant_id,
                ABTest.id == test_id,
            )
            .values(
                status="completed",
                winner_variant=winner,
                ended_at=now,
                updated_at=now,
            )
        )

        log.info(
            "ab_test.auto_concluded",
            test_id=str(test_id),
            winner=winner,
            p_value=results["p_value"],
            tenant_id=str(tenant_id),
        )
        return {
            "concluded": True,
            "winner": winner,
            "reason": results["recommendation"],
            "results": results,
        }

    # ------------------------------------------------------------------
    # 应用获胜变体
    # ------------------------------------------------------------------

    async def apply_winner(
        self,
        test_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """将获胜变体的内容应用到关联的活动/旅程。

        若测试尚未 completed 或未设置 winner_variant，先调用 auto_conclude()。

        Returns:
            {applied: bool, winner: str, content: dict, campaign_id, journey_id}
        """
        test_stmt = select(ABTest).where(
            ABTest.tenant_id == tenant_id,
            ABTest.id == test_id,
            ABTest.is_deleted.is_(False),
        )
        test_result = await db.execute(test_stmt)
        test: Optional[ABTest] = test_result.scalar_one_or_none()

        if test is None:
            raise ValueError(f"AB测试不存在: {test_id}")

        # 若未完成，先尝试自动结论
        if test.status != "completed" or test.winner_variant is None:
            conclude_result = await self.auto_conclude(test_id, tenant_id, db)
            if not conclude_result["concluded"]:
                return {
                    "applied": False,
                    "winner": None,
                    "reason": conclude_result["reason"],
                }
            # 重新加载 test
            await db.refresh(test)

        winner_variant = test.winner_variant
        winning_content: dict[str, Any] = {}

        for v in test.variants:
            if v["variant"] == winner_variant:
                winning_content = v.get("content", {})
                break

        # 此处可扩展为实际更新 campaign/journey 内容；
        # 目前返回获胜内容供调用方使用
        log.info(
            "ab_test.winner_applied",
            test_id=str(test_id),
            winner_variant=winner_variant,
            campaign_id=test.campaign_id,
            journey_id=test.journey_id,
            tenant_id=str(tenant_id),
        )
        return {
            "applied": True,
            "winner": winner_variant,
            "content": winning_content,
            "campaign_id": test.campaign_id,
            "journey_id": test.journey_id,
        }

    # ------------------------------------------------------------------
    # 列出所有测试
    # ------------------------------------------------------------------

    async def list_tests(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """列出当前租户所有 AB 测试（附实时结果摘要）。

        Returns:
            list of {test_id, name, status, split_type, primary_metric,
                     started_at, ended_at, winner_variant,
                     total_assignments, summary}
        """
        stmt = (
            select(ABTest)
            .where(
                ABTest.tenant_id == tenant_id,
                ABTest.is_deleted.is_(False),
            )
            .order_by(ABTest.created_at.desc())
        )
        result = await db.execute(stmt)
        tests: list[ABTest] = list(result.scalars().all())

        output: list[dict[str, Any]] = []
        for test in tests:
            # 快速统计分配人数（不做完整 Z 检验）
            count_stmt = select(ABTestAssignment).where(
                ABTestAssignment.tenant_id == tenant_id,
                ABTestAssignment.test_id == test.id,
                ABTestAssignment.is_deleted.is_(False),
            )
            count_result = await db.execute(count_stmt)
            assignments: list[ABTestAssignment] = list(count_result.scalars().all())

            total = len(assignments)
            converted = sum(1 for a in assignments if a.is_converted)

            output.append({
                "test_id": str(test.id),
                "name": test.name,
                "status": test.status,
                "split_type": test.split_type,
                "primary_metric": test.primary_metric,
                "campaign_id": test.campaign_id,
                "journey_id": test.journey_id,
                "started_at": test.started_at.isoformat() if test.started_at else None,
                "ended_at": test.ended_at.isoformat() if test.ended_at else None,
                "winner_variant": test.winner_variant,
                "total_assignments": total,
                "total_conversions": converted,
                "overall_conversion_rate": round(converted / total, 4) if total > 0 else 0.0,
                "created_at": test.created_at.isoformat(),
            })

        return output

    # ------------------------------------------------------------------
    # 状态变更辅助
    # ------------------------------------------------------------------

    async def _transition_status(
        self,
        test_id: uuid.UUID,
        tenant_id: uuid.UUID,
        new_status: str,
        db: AsyncSession,
        extra_values: Optional[dict[str, Any]] = None,
    ) -> ABTest:
        """通用状态转换，附带合法性检查。

        Raises:
            ValueError: 测试不存在 / 状态转换非法
        """
        stmt = select(ABTest).where(
            ABTest.tenant_id == tenant_id,
            ABTest.id == test_id,
            ABTest.is_deleted.is_(False),
        )
        result = await db.execute(stmt)
        test: Optional[ABTest] = result.scalar_one_or_none()

        if test is None:
            raise ValueError(f"AB测试不存在: {test_id}")

        allowed = _VALID_TRANSITIONS.get(test.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"状态 {test.status} 不允许转换为 {new_status}（允许: {allowed}）"
            )

        values: dict[str, Any] = {
            "status": new_status,
            "updated_at": datetime.now(timezone.utc),
        }
        if extra_values:
            values.update(extra_values)

        await db.execute(
            update(ABTest)
            .where(ABTest.tenant_id == tenant_id, ABTest.id == test_id)
            .values(**values)
        )
        await db.refresh(test)

        log.info(
            "ab_test.status_changed",
            test_id=str(test_id),
            from_status=test.status,
            to_status=new_status,
            tenant_id=str(tenant_id),
        )
        return test

    async def start_test(
        self,
        test_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> ABTest:
        """启动测试（draft → running）。"""
        now = datetime.now(timezone.utc)
        return await self._transition_status(
            test_id, tenant_id, "running", db,
            extra_values={"started_at": now},
        )

    async def pause_test(
        self,
        test_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> ABTest:
        """暂停测试（running → paused）。"""
        return await self._transition_status(test_id, tenant_id, "paused", db)

    async def conclude_test(
        self,
        test_id: uuid.UUID,
        tenant_id: uuid.UUID,
        winner_variant: Optional[str],
        db: AsyncSession,
    ) -> ABTest:
        """手动结论（running/paused → completed）。

        Args:
            winner_variant: 手动指定的获胜变体（可为 None，表示无结论）
        """
        now = datetime.now(timezone.utc)
        return await self._transition_status(
            test_id, tenant_id, "completed", db,
            extra_values={
                "winner_variant": winner_variant,
                "ended_at": now,
            },
        )
