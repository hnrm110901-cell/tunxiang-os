"""Tier 1 — NLQ SQL Generator 单元测试

S4-02 PR2.B.1 — sql_generator.py 骨架（mock LLM，不接真 ModelRouter）。

校验点（CLAUDE.md §17 Tier1 路径必须 TDD）：
  1. 正常路径：LLM 返回合法 reports.* SELECT → 透传
  2. 防火墙：LLM 输出含 DROP/UPDATE/INSERT 等写入关键字 → SqlGenerationError
  3. 白名单：LLM 输出引用 reports schema 之外的表 → SqlGenerationError
  4. 输出格式：LLM 返回非 JSON / 缺 sql 字段 → SqlGenerationError
  5. 空 SQL：LLM 返回空字符串 → SqlGenerationError
  6. LLM 超时：透传上游异常（让上层降级）
  7. Prompt 完整性：所有 8 个 reports 视图都在 system prompt 里（防漂移 — 漏视图 LLM 不会用）

设计约定：
  - SqlGenerator 接受 ModelRouterLike Protocol（与 sonnet_narrator 一致）
  - LLM 返回 JSON `{"sql": "..."}` 单字段
  - 防火墙复用 nlq_keyword_firewall.assert_safe_sql
  - reports.* 白名单是 generator 自身职责（沙箱不做）

后续 PR2.B.2 接真 ModelRouter；PR2.C 接 SSE 端点。
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest

from services.sql_generator import (
    REPORTS_VIEW_NAMES,
    SqlGenerationError,
    SqlGenerator,
)


_TENANT = UUID("11111111-1111-1111-1111-111111111111")
_REQUEST = UUID("22222222-2222-2222-2222-222222222222")


def _wrap(sql: str) -> str:
    """LLM 响应包装：合法 JSON `{"sql": "..."}`（不能用 !r，那是 Python repr）。"""
    return json.dumps({"sql": sql}, ensure_ascii=False)


class _FakeRouter:
    """模拟 ModelRouterLike — 返回预设字符串或抛预设异常。"""

    def __init__(
        self,
        response_text: str = '{"sql": "SELECT day FROM reports.daily_revenue LIMIT 7"}',
        raise_exc: BaseException | None = None,
    ) -> None:
        self._response = response_text
        self._raise = raise_exc
        self.last_messages: list[dict[str, str]] | None = None
        self.last_system: str | None = None

    async def complete(
        self,
        tenant_id: str,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        system: str | None = None,
        urgency: str = "normal",
        max_tokens: int = 600,
        timeout_s: int = 25,
        request_id: str | None = None,
        db: Any = None,
    ) -> str:
        self.last_messages = messages
        self.last_system = system
        if self._raise is not None:
            raise self._raise
        return self._response


# ──────────────── 1. 正常路径 ────────────────


@pytest.mark.asyncio
async def test_normal_path_returns_safe_sql() -> None:
    router = _FakeRouter(
        response_text='{"sql": "SELECT day, total_revenue_fen FROM reports.daily_revenue ORDER BY day DESC LIMIT 7"}'
    )
    gen = SqlGenerator(model_router=router)
    sql = await gen.generate(
        tenant_id=_TENANT, request_id=_REQUEST, nl_query="过去 7 天每天的营收"
    )
    assert sql.strip().upper().startswith("SELECT")
    assert "reports.daily_revenue" in sql
    assert "LIMIT" in sql.upper()


# ──────────────── 2. 防火墙：写入关键字 ────────────────


@pytest.mark.parametrize(
    "malicious_sql",
    [
        "SELECT 1; DROP TABLE orders",                       # 多语句
        "WITH x AS (SELECT 1) DELETE FROM orders",           # WITH+DELETE
        "SELECT * FROM reports.daily_revenue; UPDATE x SET y=1",  # 多语句 + UPDATE
        "INSERT INTO reports.daily_revenue VALUES (1)",      # INSERT
        "TRUNCATE reports.daily_revenue",                    # TRUNCATE
    ],
)
@pytest.mark.asyncio
async def test_firewall_rejects_writes(malicious_sql: str) -> None:
    router = _FakeRouter(response_text=_wrap(malicious_sql))
    gen = SqlGenerator(model_router=router)
    with pytest.raises(SqlGenerationError):
        await gen.generate(
            tenant_id=_TENANT, request_id=_REQUEST, nl_query="..."
        )


# ──────────────── 3. 白名单：reports schema 外的表 ────────────────


@pytest.mark.parametrize(
    "out_of_scope_sql",
    [
        "SELECT * FROM mv_daily_settlement LIMIT 10",           # 直查 mv_* 原表
        "SELECT * FROM orders LIMIT 10",                         # 公共 schema 业务表
        "SELECT * FROM customers LIMIT 10",                      # PII 表
        "SELECT * FROM public.orders LIMIT 10",                  # 显式 public schema
        "SELECT * FROM information_schema.tables LIMIT 10",      # 元数据
        "SELECT * FROM pg_catalog.pg_tables LIMIT 10",           # PG 内部
    ],
)
@pytest.mark.asyncio
async def test_whitelist_rejects_non_reports_schema(
    out_of_scope_sql: str,
) -> None:
    router = _FakeRouter(response_text=_wrap(out_of_scope_sql))
    gen = SqlGenerator(model_router=router)
    with pytest.raises(SqlGenerationError, match="reports"):
        await gen.generate(
            tenant_id=_TENANT, request_id=_REQUEST, nl_query="..."
        )


# ──────────────── 4. 输出格式：非 JSON / 缺字段 ────────────────


@pytest.mark.parametrize(
    "bad_response",
    [
        "not json at all",                                       # 完全不是 JSON
        '{"explanation": "我想想"}',                              # 缺 sql 字段
        '{"sql": null}',                                         # sql 是 null
        '{"sql": 42}',                                           # sql 是数字
        "",                                                      # 空字符串
    ],
)
@pytest.mark.asyncio
async def test_invalid_response_format_raises(
    bad_response: str,
) -> None:
    router = _FakeRouter(response_text=bad_response)
    gen = SqlGenerator(model_router=router)
    with pytest.raises(SqlGenerationError):
        await gen.generate(
            tenant_id=_TENANT, request_id=_REQUEST, nl_query="..."
        )


# ──────────────── 5. 空 SQL ────────────────


@pytest.mark.asyncio
async def test_empty_sql_raises() -> None:
    router = _FakeRouter(response_text='{"sql": ""}')
    gen = SqlGenerator(model_router=router)
    with pytest.raises(SqlGenerationError, match=r"empty|空"):
        await gen.generate(
            tenant_id=_TENANT, request_id=_REQUEST, nl_query="..."
        )


# ──────────────── 6. LLM 超时透传 ────────────────


@pytest.mark.asyncio
async def test_router_timeout_propagates() -> None:
    """LLM 超时必须透传给上层（让 SSE 端点降级），不应被吞为 generic Error。"""
    router = _FakeRouter(raise_exc=TimeoutError("model timeout"))
    gen = SqlGenerator(model_router=router)
    with pytest.raises(TimeoutError):
        await gen.generate(
            tenant_id=_TENANT, request_id=_REQUEST, nl_query="..."
        )


# ──────────────── 7. Prompt 完整性（防漂移） ────────────────


@pytest.mark.asyncio
async def test_prompt_includes_all_reports_views() -> None:
    """system prompt 必须列出所有 8 个 reports 视图，否则 LLM 不会去用。

    防漂移：未来 reports schema 加视图，REPORTS_VIEW_NAMES 必须同步更新。
    """
    router = _FakeRouter()
    gen = SqlGenerator(model_router=router)
    await gen.generate(
        tenant_id=_TENANT, request_id=_REQUEST, nl_query="..."
    )
    prompt = (router.last_system or "") + "\n".join(
        m.get("content", "") for m in (router.last_messages or [])
    )
    for view_name in REPORTS_VIEW_NAMES:
        assert f"reports.{view_name}" in prompt, (
            f"system prompt 缺少 reports.{view_name}（漂移：视图存在但 LLM 不会用）"
        )


def test_reports_view_names_match_v404_v405_v406_migrations() -> None:
    """REPORTS_VIEW_NAMES 必须与 v404/v405/v406 迁移落地的 8 个视图严格一致。

    防漂移：迁移加视图 → 必须更新此清单 → LLM prompt 自动同步。
    """
    expected = {
        "daily_revenue",       # v404 #325
        "member_clv",          # v404 #325
        "store_pnl",           # v405 #326
        "channel_margin",      # v405 #326
        "discount_health",     # v406 #328
        "inventory_bom",       # v406 #328
        "safety_compliance",   # v406 #328
        "energy_efficiency",   # v406 #328
    }
    assert set(REPORTS_VIEW_NAMES) == expected


# ──────────────── 8. tenant_id 透传 ────────────────


@pytest.mark.asyncio
async def test_tenant_id_passed_to_router() -> None:
    """tenant_id 必须传给 ModelRouter（route 层多租户配额隔离需要）。"""
    captured = {}

    class _CapturingRouter:
        async def complete(
            self,
            tenant_id: str,
            task_type: str,
            messages: list[dict[str, str]],
            **kwargs: Any,
        ) -> str:
            captured["tenant_id"] = tenant_id
            captured["task_type"] = task_type
            return '{"sql": "SELECT day FROM reports.daily_revenue LIMIT 1"}'

    gen = SqlGenerator(model_router=_CapturingRouter())
    await gen.generate(
        tenant_id=_TENANT, request_id=_REQUEST, nl_query="..."
    )
    assert captured["tenant_id"] == str(_TENANT)
    assert captured["task_type"]  # 非空字符串
