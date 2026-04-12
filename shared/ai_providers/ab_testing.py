"""模型质量 A/B 测试和自动评估框架。

屯象OS 接入 7 个模型提供商，本模块提供：
1. A/B 测试配置与流量分配（按 tenant_id hash 确定性分配）
2. 结果收集与统计汇总
3. 基于 z-test 的显著性检验与自动胜出判定
4. LLM-as-Judge 自动质量评估（餐饮场景定制）
5. 预设测试场景
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from .types import ProviderName

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 数据类型
# ---------------------------------------------------------------------------

@dataclass
class ABVariant:
    """A/B 测试中的一个模型变体。"""
    variant_id: str                          # 变体标识
    provider: str                            # Provider 名称（对应 ProviderName.value）
    model: str                               # 模型 ID（对应 MODEL_REGISTRY key）
    system_prompt_override: str | None = None  # 可选的 prompt 变体


@dataclass
class ABTestConfig:
    """A/B 测试配置。"""
    test_id: str                             # 测试标识
    task_type: str                           # 任务类型（lite/standard/premium 等）
    variants: list[ABVariant]                # 参与测试的模型变体
    traffic_split: dict[str, float]          # 流量分配 {"variant_a": 0.5, ...}
    sample_size: int = 100                   # 目标样本量（每变体）
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        total = sum(self.traffic_split.values())
        if not (0.99 <= total <= 1.01):
            raise ValueError(
                f"traffic_split 总和必须为 1.0, 当前: {total:.4f}"
            )
        variant_ids = {v.variant_id for v in self.variants}
        split_ids = set(self.traffic_split.keys())
        if variant_ids != split_ids:
            raise ValueError(
                f"traffic_split keys {split_ids} 与 variants {variant_ids} 不匹配"
            )


@dataclass
class ABTestResult:
    """单次调用的测试结果。"""
    variant_id: str
    latency_ms: int
    cost_rmb: float
    success: bool
    quality_score: float | None = None       # 0-1 手动/自动评分
    error_type: str | None = None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class VariantStats:
    """某个变体的汇总统计。"""
    sample_count: int
    success_rate: float
    avg_latency_ms: float
    avg_cost_rmb: float
    avg_quality_score: float | None
    p95_latency_ms: float


@dataclass
class ABTestSummary:
    """测试汇总报告。"""
    test_id: str
    task_type: str
    variants: dict[str, VariantStats]        # variant_id -> stats
    total_samples: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# 统计工具（z-test，不依赖 scipy）
# ---------------------------------------------------------------------------

def _normal_cdf(x: float) -> float:
    """标准正态分布 CDF 近似（Abramowitz & Stegun 7.1.26）。"""
    sign = 1.0 if x >= 0 else -1.0
    x = abs(x)
    t = 1.0 / (1.0 + 0.2316419 * x)
    poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937
            + t * (-1.821255978 + t * 1.330274429))))
    return 0.5 + sign * 0.5 * (1.0 - poly * math.exp(-0.5 * x * x))


def _z_test_proportions(
    successes_a: int, n_a: int,
    successes_b: int, n_b: int,
) -> tuple[float, float]:
    """双样本比例 z 检验。返回 (z_stat, p_value)。"""
    if n_a == 0 or n_b == 0:
        return 0.0, 1.0
    p_a = successes_a / n_a
    p_b = successes_b / n_b
    p_pool = (successes_a + successes_b) / (n_a + n_b)
    if p_pool == 0.0 or p_pool == 1.0:
        return 0.0, 1.0
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    if se == 0:
        return 0.0, 1.0
    z = (p_a - p_b) / se
    p_value = 2.0 * (1.0 - _normal_cdf(abs(z)))
    return z, p_value


def _z_test_means(
    mean_a: float, var_a: float, n_a: int,
    mean_b: float, var_b: float, n_b: int,
) -> tuple[float, float]:
    """双样本均值 z 检验（大样本近似）。返回 (z_stat, p_value)。"""
    if n_a < 2 or n_b < 2:
        return 0.0, 1.0
    se = math.sqrt(var_a / n_a + var_b / n_b)
    if se == 0:
        return 0.0, 1.0
    z = (mean_a - mean_b) / se
    p_value = 2.0 * (1.0 - _normal_cdf(abs(z)))
    return z, p_value


# ---------------------------------------------------------------------------
# 内存结果存储（Redis 不可用时的降级方案）
# ---------------------------------------------------------------------------

class _InMemoryResultStore:
    """纯内存结果存储，用于单进程或 Redis 不可用时。"""

    def __init__(self) -> None:
        self._results: dict[str, list[ABTestResult]] = {}  # test_id -> results

    async def append(self, test_id: str, result: ABTestResult) -> None:
        self._results.setdefault(test_id, []).append(result)

    async def get_all(self, test_id: str) -> list[ABTestResult]:
        return list(self._results.get(test_id, []))

    async def count(self, test_id: str) -> int:
        return len(self._results.get(test_id, []))

    async def clear(self, test_id: str) -> None:
        self._results.pop(test_id, None)


class _RedisResultStore:
    """Redis List 结果存储，支持多进程共享。"""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis: Any = None

    async def _get_redis(self) -> Any:
        if self._redis is None:
            try:
                import redis.asyncio as aioredis  # noqa: F811
                self._redis = aioredis.from_url(
                    self._redis_url, decode_responses=True,
                )
            except ImportError:
                raise ImportError(
                    "需要 redis 包: pip install redis"
                )
        return self._redis

    def _key(self, test_id: str) -> str:
        return f"tx:ab_test:results:{test_id}"

    async def append(self, test_id: str, result: ABTestResult) -> None:
        r = await self._get_redis()
        payload = json.dumps({
            "variant_id": result.variant_id,
            "latency_ms": result.latency_ms,
            "cost_rmb": result.cost_rmb,
            "success": result.success,
            "quality_score": result.quality_score,
            "error_type": result.error_type,
            "recorded_at": result.recorded_at.isoformat(),
        })
        await r.rpush(self._key(test_id), payload)

    async def get_all(self, test_id: str) -> list[ABTestResult]:
        r = await self._get_redis()
        raw_list = await r.lrange(self._key(test_id), 0, -1)
        results: list[ABTestResult] = []
        for raw in raw_list:
            d = json.loads(raw)
            results.append(ABTestResult(
                variant_id=d["variant_id"],
                latency_ms=d["latency_ms"],
                cost_rmb=d["cost_rmb"],
                success=d["success"],
                quality_score=d.get("quality_score"),
                error_type=d.get("error_type"),
                recorded_at=datetime.fromisoformat(d["recorded_at"]),
            ))
        return results

    async def count(self, test_id: str) -> int:
        r = await self._get_redis()
        return await r.llen(self._key(test_id))

    async def clear(self, test_id: str) -> None:
        r = await self._get_redis()
        await r.delete(self._key(test_id))


# ---------------------------------------------------------------------------
# ABTestManager
# ---------------------------------------------------------------------------

class ABTestManager:
    """A/B 测试管理器。

    支持：
    1. 创建/激活/停止测试
    2. 流量分配（按 tenant_id hash 确保同租户一致分配）
    3. 结果收集和统计
    4. 自动胜出判定（z-test 显著性检验）
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._tests: dict[str, ABTestConfig] = {}
        if redis_url:
            self._store: _InMemoryResultStore | _RedisResultStore = (
                _RedisResultStore(redis_url)
            )
            logger.info("ab_test.store_init", backend="redis")
        else:
            self._store = _InMemoryResultStore()
            logger.info("ab_test.store_init", backend="in_memory")

    # -- 测试生命周期 --------------------------------------------------------

    def register_test(self, config: ABTestConfig) -> None:
        """注册一个 A/B 测试配置。"""
        self._tests[config.test_id] = config
        logger.info(
            "ab_test.registered",
            test_id=config.test_id,
            task_type=config.task_type,
            variants=[v.variant_id for v in config.variants],
        )

    def activate_test(self, test_id: str) -> None:
        """激活一个已注册的测试。"""
        cfg = self._get_config(test_id)
        cfg.enabled = True
        logger.info("ab_test.activated", test_id=test_id)

    def stop_test(self, test_id: str) -> None:
        """停止一个测试（保留数据）。"""
        cfg = self._get_config(test_id)
        cfg.enabled = False
        logger.info("ab_test.stopped", test_id=test_id)

    def get_test(self, test_id: str) -> ABTestConfig:
        """获取测试配置。"""
        return self._get_config(test_id)

    def list_tests(self, only_active: bool = False) -> list[ABTestConfig]:
        """列出所有测试。"""
        tests = list(self._tests.values())
        if only_active:
            tests = [t for t in tests if t.enabled]
        return tests

    # -- 流量分配 ------------------------------------------------------------

    def assign_variant(self, test_id: str, tenant_id: str) -> ABVariant:
        """根据 tenant_id 确定性分配变体。

        使用 MD5 hash 对 (test_id, tenant_id) 取模，保证同一租户
        在同一测试中始终分到同一变体。
        """
        cfg = self._get_config(test_id)
        if not cfg.enabled:
            raise RuntimeError(f"测试 {test_id} 未激活")

        hash_input = f"{test_id}:{tenant_id}"
        hash_val = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
        bucket = (hash_val % 10000) / 10000.0  # 0 ~ 0.9999

        cumulative = 0.0
        for variant in cfg.variants:
            cumulative += cfg.traffic_split[variant.variant_id]
            if bucket < cumulative:
                logger.debug(
                    "ab_test.assigned",
                    test_id=test_id,
                    tenant_id=tenant_id,
                    variant_id=variant.variant_id,
                    bucket=f"{bucket:.4f}",
                )
                return variant

        # 浮点精度兜底：返回最后一个变体
        return cfg.variants[-1]

    # -- 结果收集 ------------------------------------------------------------

    async def record_result(
        self, test_id: str, variant_id: str, result: ABTestResult,
    ) -> None:
        """记录一次测试结果。"""
        self._get_config(test_id)  # 确认 test 存在
        await self._store.append(test_id, result)
        logger.debug(
            "ab_test.result_recorded",
            test_id=test_id,
            variant_id=variant_id,
            success=result.success,
            latency_ms=result.latency_ms,
        )

    # -- 统计汇总 ------------------------------------------------------------

    async def get_test_summary(self, test_id: str) -> ABTestSummary:
        """生成测试的统计汇总。"""
        cfg = self._get_config(test_id)
        all_results = await self._store.get_all(test_id)

        # 按 variant 分组
        grouped: dict[str, list[ABTestResult]] = {
            v.variant_id: [] for v in cfg.variants
        }
        for r in all_results:
            if r.variant_id in grouped:
                grouped[r.variant_id].append(r)

        variant_stats: dict[str, VariantStats] = {}
        for vid, results in grouped.items():
            variant_stats[vid] = self._compute_variant_stats(results)

        return ABTestSummary(
            test_id=test_id,
            task_type=cfg.task_type,
            variants=variant_stats,
            total_samples=len(all_results),
        )

    # -- 胜出判定 ------------------------------------------------------------

    def check_winner(
        self, summary: ABTestSummary, confidence: float = 0.95,
    ) -> str | None:
        """统计显著性检验，返回胜出 variant_id 或 None。

        综合比较成功率和质量评分：
        - 先比较成功率（z-test for proportions）
        - 若成功率无显著差异且有质量评分，再比较质量评分（z-test for means）
        - 要求显著性水平达到 confidence（默认 0.95）
        """
        variant_ids = list(summary.variants.keys())
        if len(variant_ids) != 2:
            logger.warning(
                "ab_test.check_winner_unsupported",
                reason="仅支持双变体对比",
                variant_count=len(variant_ids),
            )
            return None

        alpha = 1.0 - confidence
        va_id, vb_id = variant_ids
        va, vb = summary.variants[va_id], summary.variants[vb_id]

        if va.sample_count < 10 or vb.sample_count < 10:
            logger.info(
                "ab_test.insufficient_samples",
                test_id=summary.test_id,
                samples_a=va.sample_count,
                samples_b=vb.sample_count,
            )
            return None

        # 1. 成功率检验
        successes_a = round(va.success_rate * va.sample_count)
        successes_b = round(vb.success_rate * vb.sample_count)
        z_sr, p_sr = _z_test_proportions(
            successes_a, va.sample_count,
            successes_b, vb.sample_count,
        )

        if p_sr < alpha:
            winner = va_id if va.success_rate > vb.success_rate else vb_id
            logger.info(
                "ab_test.winner_found",
                test_id=summary.test_id,
                metric="success_rate",
                winner=winner,
                z_stat=f"{z_sr:.3f}",
                p_value=f"{p_sr:.4f}",
            )
            return winner

        # 2. 质量评分检验（若有数据）
        if va.avg_quality_score is not None and vb.avg_quality_score is not None:
            var_a = self._quality_variance_from_stats(va)
            var_b = self._quality_variance_from_stats(vb)
            z_qs, p_qs = _z_test_means(
                va.avg_quality_score, var_a, va.sample_count,
                vb.avg_quality_score, var_b, vb.sample_count,
            )
            if p_qs < alpha:
                winner = va_id if va.avg_quality_score > vb.avg_quality_score else vb_id
                logger.info(
                    "ab_test.winner_found",
                    test_id=summary.test_id,
                    metric="quality_score",
                    winner=winner,
                    z_stat=f"{z_qs:.3f}",
                    p_value=f"{p_qs:.4f}",
                )
                return winner

        logger.info(
            "ab_test.no_winner_yet",
            test_id=summary.test_id,
            p_success_rate=f"{p_sr:.4f}",
        )
        return None

    # -- 内部方法 ------------------------------------------------------------

    def _get_config(self, test_id: str) -> ABTestConfig:
        if test_id not in self._tests:
            raise KeyError(f"未注册的测试: {test_id}")
        return self._tests[test_id]

    @staticmethod
    def _compute_variant_stats(results: list[ABTestResult]) -> VariantStats:
        n = len(results)
        if n == 0:
            return VariantStats(
                sample_count=0,
                success_rate=0.0,
                avg_latency_ms=0.0,
                avg_cost_rmb=0.0,
                avg_quality_score=None,
                p95_latency_ms=0.0,
            )

        successes = sum(1 for r in results if r.success)
        latencies = [r.latency_ms for r in results]
        costs = [r.cost_rmb for r in results]
        quality_scores = [r.quality_score for r in results if r.quality_score is not None]

        sorted_latencies = sorted(latencies)
        p95_idx = min(int(math.ceil(n * 0.95)) - 1, n - 1)

        return VariantStats(
            sample_count=n,
            success_rate=successes / n,
            avg_latency_ms=sum(latencies) / n,
            avg_cost_rmb=sum(costs) / n,
            avg_quality_score=(
                sum(quality_scores) / len(quality_scores)
                if quality_scores else None
            ),
            p95_latency_ms=float(sorted_latencies[p95_idx]),
        )

    @staticmethod
    def _quality_variance_from_stats(stats: VariantStats) -> float:
        """质量评分方差估计。

        由于 VariantStats 只存均值不存原始数据，使用保守估计：
        评分范围 [0, 1] 的最大方差为 0.25（伯努利分布），
        此处用 0.05 作为合理默认值。
        """
        return 0.05


# ---------------------------------------------------------------------------
# AutoQualityEvaluator -- LLM-as-Judge
# ---------------------------------------------------------------------------

class AutoQualityEvaluator:
    """使用另一个 LLM 自动评估响应质量。

    评估维度（针对餐饮场景）：
    - 准确性：数据和计算是否正确
    - 专业性：是否使用正确的餐饮术语
    - 可操作性：建议是否可直接执行
    - 安全性：是否遵守三条硬约束（毛利底线/食安合规/客户体验）
    """

    JUDGE_PROMPT = (
        "你是餐饮AI质量评估专家。请对以下AI回复进行评分。\n\n"
        "## 评估维度\n"
        "1. 准确性(0-1): 数据引用和计算是否正确\n"
        "2. 专业性(0-1): 是否使用正确的餐饮行业术语和知识\n"
        "3. 可操作性(0-1): 建议是否具体、可直接执行\n"
        "4. 安全性(0-1): 是否遵守毛利底线、食安合规、客户体验三条硬约束\n\n"
        "## 任务类型\n{task_type}\n\n"
        "## 用户输入\n{input_text}\n\n"
        "## AI 回复\n{response_text}\n\n"
        "请仅返回一个JSON对象，格式如下（不要返回其他内容）：\n"
        '{{"accuracy": 0.0, "professionalism": 0.0, '
        '"actionability": 0.0, "safety": 0.0, "overall": 0.0, '
        '"reason": "一句话评价"}}'
    )

    def __init__(
        self,
        judge_provider: str = "deepseek",
        judge_model: str = "deepseek-chat",
    ) -> None:
        """初始化评估器。

        Args:
            judge_provider: 用作评审的 Provider 名称。
            judge_model: 用作评审的模型 ID。
        """
        self._judge_provider = judge_provider
        self._judge_model = judge_model

    async def evaluate(
        self,
        task_type: str,
        input_messages: list[dict[str, str]],
        response: str,
        *,
        adapter: Any | None = None,
    ) -> float:
        """评估一个 AI 回复的质量，返回 0-1 综合评分。

        Args:
            task_type: 任务类型描述。
            input_messages: 用户输入消息列表。
            response: AI 回复文本。
            adapter: ProviderAdapter 实例。若为 None，返回 -1 表示无法评估。

        Returns:
            0-1 之间的综合质量评分。无法评估时返回 -1.0。
        """
        if adapter is None:
            logger.warning("ab_test.evaluator_no_adapter")
            return -1.0

        input_text = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}"
            for m in input_messages
        )
        prompt = self.JUDGE_PROMPT.format(
            task_type=task_type,
            input_text=input_text,
            response_text=response,
        )

        try:
            judge_response = await adapter.complete(
                messages=[{"role": "user", "content": prompt}],
                model=self._judge_model,
                temperature=0.0,
                max_tokens=512,
                timeout_s=15,
            )
            score_data = json.loads(judge_response.text)
            overall = float(score_data.get("overall", 0.0))
            overall = max(0.0, min(1.0, overall))
            logger.info(
                "ab_test.quality_evaluated",
                task_type=task_type,
                overall=overall,
                reason=score_data.get("reason", ""),
            )
            return overall
        except json.JSONDecodeError:
            logger.error("ab_test.judge_parse_error", raw=judge_response.text[:200])
            return -1.0
        except TimeoutError:
            logger.error("ab_test.judge_timeout")
            return -1.0
        except ConnectionError as exc:
            logger.error("ab_test.judge_connection_error", error=str(exc))
            return -1.0


# ---------------------------------------------------------------------------
# 便捷装饰器 -- 自动记录 A/B 测试结果
# ---------------------------------------------------------------------------

def ab_test_wrapper(
    manager: ABTestManager,
    test_id: str,
    tenant_id: str,
    evaluator: AutoQualityEvaluator | None = None,
):
    """装饰器工厂：自动为 LLM 调用记录 A/B 测试结果。

    用法::

        @ab_test_wrapper(manager, "discount-ds-vs-qwen", tenant_id)
        async def analyze_discount(adapter, model, messages):
            return await adapter.complete(messages, model)
    """
    import functools

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            variant = manager.assign_variant(test_id, tenant_id)
            start = time.monotonic()
            success = True
            error_type: str | None = None
            cost_rmb = 0.0
            response_text = ""

            try:
                result = await func(
                    *args,
                    _variant=variant,
                    **kwargs,
                )
                if hasattr(result, "cost_rmb"):
                    cost_rmb = result.cost_rmb
                if hasattr(result, "text"):
                    response_text = result.text
                return result
            except Exception as exc:
                success = False
                error_type = type(exc).__name__
                raise
            finally:
                elapsed_ms = int((time.monotonic() - start) * 1000)

                quality_score: float | None = None
                if success and evaluator and response_text:
                    input_msgs = kwargs.get("messages", [])
                    score = await evaluator.evaluate(
                        task_type=manager.get_test(test_id).task_type,
                        input_messages=input_msgs,
                        response=response_text,
                    )
                    if score >= 0:
                        quality_score = score

                test_result = ABTestResult(
                    variant_id=variant.variant_id,
                    latency_ms=elapsed_ms,
                    cost_rmb=cost_rmb,
                    success=success,
                    quality_score=quality_score,
                    error_type=error_type,
                )
                await manager.record_result(
                    test_id, variant.variant_id, test_result,
                )

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 预设测试场景
# ---------------------------------------------------------------------------

PRESET_TESTS: dict[str, ABTestConfig] = {
    "discount_analysis": ABTestConfig(
        test_id="discount-deepseek-vs-qwen",
        task_type="standard_analysis",
        variants=[
            ABVariant("ds-v3", "deepseek", "deepseek-chat"),
            ABVariant("qwen-max", "qwen", "qwen-max"),
        ],
        traffic_split={"ds-v3": 0.5, "qwen-max": 0.5},
        sample_size=200,
    ),
    "menu_optimization": ABTestConfig(
        test_id="menu-qwen-vs-glm",
        task_type="standard_analysis",
        variants=[
            ABVariant("qwen-plus", "qwen", "qwen-plus"),
            ABVariant("glm-4-plus", "glm", "glm-4-plus"),
        ],
        traffic_split={"qwen-plus": 0.5, "glm-4-plus": 0.5},
        sample_size=150,
    ),
    "member_insight": ABTestConfig(
        test_id="member-deepseek-vs-ernie",
        task_type="standard_analysis",
        variants=[
            ABVariant("ds-v3", "deepseek", "deepseek-chat"),
            ABVariant("ernie-turbo", "ernie", "ernie-4.5-turbo-128k"),
        ],
        traffic_split={"ds-v3": 0.5, "ernie-turbo": 0.5},
        sample_size=200,
    ),
    "complex_reasoning": ABTestConfig(
        test_id="reasoning-claude-vs-deepseek-r1",
        task_type="premium_reasoning",
        variants=[
            ABVariant("claude-sonnet", "anthropic", "claude-sonnet-4-6"),
            ABVariant("ds-r1", "deepseek", "deepseek-reasoner"),
        ],
        traffic_split={"claude-sonnet": 0.5, "ds-r1": 0.5},
        sample_size=100,
    ),
    "long_document": ABTestConfig(
        test_id="longctx-qwen-vs-kimi",
        task_type="long_ctx_analysis",
        variants=[
            ABVariant("qwen-long", "qwen", "qwen-long"),
            ABVariant("kimi-128k", "kimi", "moonshot-v1-128k"),
        ],
        traffic_split={"qwen-long": 0.5, "kimi-128k": 0.5},
        sample_size=100,
    ),
    "lite_classification": ABTestConfig(
        test_id="lite-qwen-turbo-vs-glm-flash",
        task_type="lite_classification",
        variants=[
            ABVariant("qwen-turbo", "qwen", "qwen-turbo"),
            ABVariant("glm-flash", "glm", "glm-4-flash"),
        ],
        traffic_split={"qwen-turbo": 0.5, "glm-flash": 0.5},
        sample_size=500,
    ),
}
