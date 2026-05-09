"""NLQ SQL Generator — S4-02 PR2.B Tier 1 后端 LLM SQL 生成器。

职责：
  1. 接受用户自然语言问题 + tenant_id，调 LLM（ModelRouterLike）输出 SQL
  2. 解析 LLM 输出（JSON `{"sql": "..."}`）
  3. 防火墙校验（复用 nlq_keyword_firewall.assert_safe_sql）
  4. reports.* 白名单校验（generator 自身职责，沙箱不做）
  5. 透传 LLM 上游异常（TimeoutError 等让 SSE 端点降级）

设计：
  - ModelRouterLike Protocol（与 sonnet_narrator 一致，最小依赖面）
  - LLM 输出 JSON 单字段 `{"sql": "..."}`，便于强校验
  - prompt 列出全部 reports.* 视图（防漂移：迁移加视图 → REPORTS_VIEW_NAMES 同步 → prompt 自动更新）
  - create_default_sql_generator() 工厂 wire MigrationRouter（PR2.B.2）

后续 PR2.C：POST /nlq/query SSE 端点 + sql_sandbox.execute 串联

CLAUDE.md §17 Tier 1：read-only + RLS 不可绕 + 防火墙 + 白名单
Refs: issue #289
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .nlq_keyword_firewall import UnsafeSqlError, assert_safe_sql


# ─── reports schema 视图清单（与 v404/v405/v406 迁移严格对齐） ────────────
# 防漂移：迁移加视图 → 此清单同步 → system prompt + 白名单自动更新
REPORTS_VIEW_NAMES: tuple[str, ...] = (
    "daily_revenue",       # v404 #325 — 日营收聚合
    "member_clv",          # v404 #325 — 会员 CLV 聚合
    "store_pnl",           # v405 #326 — 门店 P&L 日聚合
    "channel_margin",      # v405 #326 — 渠道真实毛利
    "discount_health",     # v406 #328 — 折扣健康
    "inventory_bom",       # v406 #328 — 食材损耗
    "safety_compliance",   # v406 #328 — 食安合规周
    "energy_efficiency",   # v406 #328 — 能耗效率
)

_REPORTS_SCHEMA = "reports"

# 字段简介（让 LLM 知道每个视图存什么）— prompt 内嵌
_VIEW_HINTS: dict[str, str] = {
    "daily_revenue":      "(tenant_id, store_id, day, total_revenue_fen, cash_system_fen, wechat_received_fen, alipay_received_fen, card_received_fen, stored_value_consumed_fen)：日营收聚合（仅已结算）",
    "member_clv":         "(tenant_id, customer_id, total_spend_fen, visit_count, voucher_used_count, voucher_cost_fen, stored_value_balance_fen, clv_fen, rfm_segment, last_visit_at)：会员生命周期价值",
    "store_pnl":          "(tenant_id, brand_id, store_id, day, gross_revenue_fen, net_revenue_fen, cogs_fen, gross_profit_fen, gross_margin_rate, labor_cost_fen, overhead_fen, net_profit_fen, order_count, customer_count, avg_check_fen)：门店 P&L 日聚合",
    "channel_margin":     "(tenant_id, store_id, day, channel, gross_revenue_fen, commission_fen, promotion_subsidy_fen, net_revenue_fen, cogs_fen, gross_margin_fen, gross_margin_rate, order_count)：渠道真实毛利",
    "discount_health":    "(tenant_id, store_id, day, total_orders, discounted_orders, discount_rate, total_discount_fen, unauthorized_count, leak_types, threshold_breaches)：折扣健康",
    "inventory_bom":      "(tenant_id, store_id, day, ingredient_id, ingredient_name, theoretical_usage_g, actual_usage_g, waste_g, unexplained_loss_g, loss_rate)：食材 BOM 损耗",
    "safety_compliance":  "(tenant_id, store_id, week_start, sample_logged_count, inspection_required, inspection_done, inspection_rate, violation_count, compliance_score)：食安合规周",
    "energy_efficiency":  "(tenant_id, store_id, day, electricity_kwh, gas_m3, water_ton, energy_cost_fen, revenue_fen, energy_revenue_ratio, anomaly_count)：能耗效率",
}


# ─── 异常 ────────────────────────────────────────────────────────────────


class SqlGenerationError(RuntimeError):
    """LLM 输出无法解析、违反防火墙或白名单时抛出。"""


# ─── ModelRouter 协议（最小依赖面） ──────────────────────────────────────


class ModelRouterLike(Protocol):
    """匹配 ModelRouterCompat / MultiProviderRouter 的子集（与 sonnet_narrator 一致）。"""

    async def complete(
        self,
        tenant_id: str,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        system: str | None = ...,
        urgency: str = ...,
        max_tokens: int = ...,
        timeout_s: int = ...,
        request_id: str | None = ...,
        db: Any = ...,
    ) -> Any:
        ...


# ─── LLM 输出强校验 ──────────────────────────────────────────────────────


class _GeneratorOutput(BaseModel):
    """LLM 返回 JSON 强校验：必须是单字段 sql:str。

    空字符串由后续 .strip() 检查（区分"缺字段/类型错"vs"内容空"两类错误消息）。
    """

    model_config = ConfigDict(extra="ignore")

    sql: str = Field(..., max_length=10_000)


# ─── 白名单校验 ──────────────────────────────────────────────────────────


# 匹配 FROM/JOIN 后的表引用（含可选 schema 前缀）
# 例：FROM reports.daily_revenue / JOIN public.orders / FROM mv_x
_TABLE_REF_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*))?",
    re.IGNORECASE,
)


def _assert_reports_only(sql: str) -> None:
    """所有 FROM/JOIN 引用必须形如 reports.<已知视图名>。

    无 schema 前缀（如 FROM mv_daily_settlement）一律拒（generator 不允许 search_path 解析）。
    information_schema / pg_catalog / public 一律拒。
    """
    refs = _TABLE_REF_PATTERN.findall(sql)
    if not refs:
        # 无 FROM/JOIN 也允许（如 SELECT 1）— 但实际 LLM 不该输出
        return
    for first, second in refs:
        if not second:
            # 无 schema 前缀 → 拒（防 search_path 默认 public 走漏）
            raise SqlGenerationError(
                f"SQL 引用未限定 schema 的表 {first!r}；必须 reports.<view>"
            )
        schema, view = first.lower(), second.lower()
        if schema != _REPORTS_SCHEMA:
            raise SqlGenerationError(
                f"SQL 引用 {schema}.{view}；只允许 reports schema"
            )
        if view not in REPORTS_VIEW_NAMES:
            raise SqlGenerationError(
                f"SQL 引用 reports.{view}；不在 NLQ 已暴露视图清单"
            )


# ─── System prompt 模板 ──────────────────────────────────────────────────


def _build_system_prompt() -> str:
    view_lines = "\n".join(
        f"- reports.{name} {hint}"
        for name, hint in _VIEW_HINTS.items()
    )
    return f"""你是屯象OS NLQ 系统的 SQL 生成器。把用户自然语言问题转换为 PostgreSQL SELECT 查询。

【可用视图（仅 reports schema 内）】
{view_lines}

【硬约束】
1. 只能查 reports.* 视图，不得引用其他 schema/表（包括 mv_* / orders / customers / public / information_schema / pg_catalog）
2. 表引用必须显式 reports.<view> 写法（不允许省略 schema）
3. 必须包含 LIMIT 子句（建议 ≤ 1000；不要超过 10000）
4. 只能用 SELECT，不得有 DROP/UPDATE/INSERT/DELETE/TRUNCATE/MERGE/ALTER/SECURITY DEFINER 等
5. 不要在 WHERE 中过滤 tenant_id（RLS 自动过滤，写了反而冗余）
6. 输出严格 JSON：`{{"sql": "<完整 SQL>"}}`，不要任何其他文字、不要 markdown 代码块

【示例】
Q: 过去 7 天每天的营收？
A: {{"sql": "SELECT day, total_revenue_fen FROM reports.daily_revenue WHERE day >= CURRENT_DATE - INTERVAL '7 days' ORDER BY day LIMIT 7"}}

Q: 流失风险最高的 10 个会员？
A: {{"sql": "SELECT customer_id, clv_fen, rfm_segment, last_visit_at FROM reports.member_clv ORDER BY last_visit_at ASC LIMIT 10"}}
"""


# ─── 主 Service ──────────────────────────────────────────────────────────


class SqlGenerator:
    """NLQ 自然语言 → reports.* SQL 生成器。

    用法：
        gen = SqlGenerator(model_router=router)
        sql = await gen.generate(
            tenant_id=UUID(...), request_id=UUID(...), nl_query="过去 7 天营收"
        )
        # sql 已通过防火墙 + reports 白名单校验，可直接交给 sql_sandbox.execute
    """

    TASK_TYPE = "nlq_sql_generation"

    def __init__(
        self,
        model_router: ModelRouterLike,
        *,
        max_tokens: int = 800,
        timeout_s: int = 25,
    ) -> None:
        self._router = model_router
        self._max_tokens = max_tokens
        self._timeout_s = timeout_s

    async def generate(
        self,
        *,
        tenant_id: UUID,
        request_id: UUID,
        nl_query: str,
    ) -> str:
        """生成校验过的 reports.* SELECT。

        Raises:
            SqlGenerationError: LLM 输出不合法 / 违反防火墙 / 违反白名单
            TimeoutError / 其他: 透传 ModelRouter 上游异常（让上层 SSE 降级）
        """
        system = _build_system_prompt()
        messages = [
            {"role": "user", "content": nl_query.strip() or "（空查询）"},
        ]
        # ModelRouter 异常透传（不 wrap，让上层 SSE 区分降级路径）
        raw = await self._router.complete(
            tenant_id=str(tenant_id),
            task_type=self.TASK_TYPE,
            messages=messages,
            system=system,
            urgency="normal",
            max_tokens=self._max_tokens,
            timeout_s=self._timeout_s,
            request_id=str(request_id),
        )
        return self._parse_and_validate(raw)

    @staticmethod
    def _parse_and_validate(raw: Any) -> str:
        # 兼容 ModelRouter 返回 str / 含 .text / 含 .content 的对象
        if isinstance(raw, str):
            text_payload = raw
        elif hasattr(raw, "text"):
            text_payload = raw.text
        elif hasattr(raw, "content"):
            text_payload = raw.content
        else:
            text_payload = str(raw)

        if not text_payload or not text_payload.strip():
            raise SqlGenerationError("LLM 返回空响应")

        try:
            obj = json.loads(text_payload)
        except json.JSONDecodeError as exc:
            raise SqlGenerationError(
                f"LLM 输出不是合法 JSON: {exc.msg}"
            ) from exc

        try:
            parsed = _GeneratorOutput.model_validate(obj)
        except ValidationError as exc:
            raise SqlGenerationError(
                f"LLM 输出 JSON 缺字段或类型错误: {exc.errors()}"
            ) from exc

        sql = parsed.sql.strip()
        if not sql:
            raise SqlGenerationError("LLM 输出 sql 字段为空（empty）")

        # 防火墙：写入关键字 / 多语句 / SECURITY DEFINER
        try:
            assert_safe_sql(sql)
        except UnsafeSqlError as exc:
            raise SqlGenerationError(
                f"LLM 输出违反防火墙: {exc}"
            ) from exc

        # 白名单：仅 reports.<已知视图>
        _assert_reports_only(sql)

        return sql


# ─── 工厂函数（PR2.B.2 接真 ModelRouter） ────────────────────────────────


def create_default_sql_generator(
    *,
    max_tokens: int = 800,
    timeout_s: int = 25,
) -> "SqlGenerator":
    """从 ANTHROPIC_API_KEY 环境变量构造 SqlGenerator。

    用法（FastAPI Depends）：
        from .services.sql_generator import create_default_sql_generator
        @router.post("/nlq/query")
        async def nlq(...):
            try:
                gen = create_default_sql_generator()
            except ValueError:
                raise HTTPException(503, "LLM service unavailable: check ANTHROPIC_API_KEY")
            sql = await gen.generate(...)

    Raises:
        ValueError: ANTHROPIC_API_KEY 未设置（透传 MigrationRouter 的错误）。
        ImportError: anthropic SDK 未安装（应在 requirements.txt 装好）。

    Notes:
        - 用 MigrationRouter 而非直接 ModelRouterCompat —— 走 MULTI_PROVIDER_ENABLED 开关
        - 不缓存 router 实例（生产可改 lru_cache 或 dependency injection）
    """
    from shared.ai_providers.migration import MigrationRouter

    router = MigrationRouter()
    return SqlGenerator(
        model_router=router,  # type: ignore[arg-type]
        max_tokens=max_tokens,
        timeout_s=timeout_s,
    )
