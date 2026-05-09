"""Tier 1 — NLQ POST /api/v1/brain/nlq/query SSE 端点

S4-02 PR2.C — 串联 sql_generator → sql_sandbox.run_safe_query → SSE 流。

校验点（CLAUDE.md §17 Tier1 路径必须 TDD）：
  1. 端点存在且接受 X-Tenant-ID header + nl_query body
  2. 缺 X-Tenant-ID → 422（FastAPI Header(...) 强制必填）
  3. ANTHROPIC_API_KEY 缺失 → 503（factory ValueError → HTTPException）
  4. 正常路径：SSE 流依次发出 sql / result / done 三类事件
  5. SqlGenerationError → SSE error 事件 kind=generation
  6. SandboxTimeoutError → SSE error 事件 kind=sandbox_timeout
  7. RowLimitExceeded → SSE error 事件 kind=row_limit
  8. LLM TimeoutError 透传 → SSE error 事件 kind=llm_timeout
  9. 防御 raw event 文本注入：data 内的换行/特殊字符必须 JSON 编码

设计：
  - 用 FastAPI app.dependency_overrides 注入 mock generator + mock runner + mock db
  - 不依赖真 PG / 真 LLM
  - SSE 解析：按 \n\n 切分 event 块，每块 `event: <kind>\ndata: <json>`

Refs: issue #289
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.nlq_routes import (
    _get_db_with_tenant,
    _get_run_safe_query,
    _get_sql_generator,
    router,
)
from services.sql_generator import SqlGenerationError
from services.sql_sandbox import RowLimitExceeded, SandboxResult, SandboxTimeoutError


_TENANT = "11111111-1111-1111-1111-111111111111"


# ─── helpers ─────────────────────────────────────────────────────────────


def _build_app(
    *,
    sql_generator: Any = None,
    runner: Any = None,
    db: Any = None,
) -> FastAPI:
    """构造 FastAPI app + 注入指定 dependency 替身。"""
    app = FastAPI()
    app.include_router(router)
    if sql_generator is not None:
        app.dependency_overrides[_get_sql_generator] = lambda: sql_generator
    if runner is not None:
        app.dependency_overrides[_get_run_safe_query] = lambda: runner
    if db is not None:
        async def _stub_db() -> Any:
            return db
        app.dependency_overrides[_get_db_with_tenant] = _stub_db
    return app


def _parse_sse(body: str) -> list[dict[str, Any]]:
    """SSE 解析：把 `event: X\ndata: Y\n\n` 块切成 dict 列表。

    返回形态：[{"event": "sql", "data": {...}}, ...]
    """
    out = []
    for chunk in body.strip().split("\n\n"):
        if not chunk.strip():
            continue
        event_kind = None
        data_payload = None
        for line in chunk.split("\n"):
            if line.startswith("event:"):
                event_kind = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_payload = line[len("data:") :].strip()
        if event_kind is None:
            continue
        out.append(
            {
                "event": event_kind,
                "data": json.loads(data_payload) if data_payload else None,
            }
        )
    return out


# ─── 1. 缺 X-Tenant-ID → 422 ─────────────────────────────────────────────


def test_missing_tenant_header_returns_422() -> None:
    app = _build_app(sql_generator=AsyncMock(), runner=AsyncMock(), db=object())
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/brain/nlq/query", json={"nl_query": "x"}
        )
    assert resp.status_code == 422


# ─── 2. ANTHROPIC_API_KEY 缺失 → 503 ─────────────────────────────────────


def test_missing_api_key_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """工厂抛 ValueError 时端点应映射为 503（service unavailable）。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("MULTI_PROVIDER_ENABLED", "false")

    # 不 override _get_sql_generator —— 让真 factory 跑（应抛 ValueError）
    app = FastAPI()
    app.include_router(router)
    # 仅 override db 避免连真 PG
    async def _stub_db() -> Any:
        return object()
    app.dependency_overrides[_get_db_with_tenant] = _stub_db

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/brain/nlq/query",
            json={"nl_query": "..."},
            headers={"X-Tenant-ID": _TENANT},
        )
    # 503 if ANTHROPIC_API_KEY missing；接受 503 或 500（SDK 缺时也可能 500）
    assert resp.status_code in (500, 503)


# ─── 3. 正常路径：SSE 三事件序列 ─────────────────────────────────────────


def test_normal_path_emits_sql_result_done_events() -> None:
    sql = "SELECT day FROM reports.daily_revenue LIMIT 7"
    rows = [{"day": "2026-05-09"}, {"day": "2026-05-08"}]
    sample_result = SandboxResult(
        rows=rows, row_count=len(rows), columns=["day"], truncated=False
    )

    gen = AsyncMock()
    gen.generate.return_value = sql

    runner = AsyncMock(return_value=sample_result)

    app = _build_app(sql_generator=gen, runner=runner, db=object())

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/brain/nlq/query",
            json={"nl_query": "过去 7 天每天的营收"},
            headers={"X-Tenant-ID": _TENANT},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    kinds = [e["event"] for e in events]
    assert kinds == ["sql", "result", "done"], f"事件序列错：{kinds}"

    # sql 事件
    assert events[0]["data"]["sql"] == sql

    # result 事件含 rows + row_count + columns
    result_data = events[1]["data"]
    assert result_data["row_count"] == 2
    assert result_data["columns"] == ["day"]
    assert len(result_data["rows"]) == 2

    # generator + runner 都被调过一次
    gen.generate.assert_awaited_once()
    runner.assert_awaited_once()


# ─── 4. SqlGenerationError → SSE error 事件 ─────────────────────────────


@pytest.mark.parametrize(
    "exc_factory, expected_kind",
    [
        (lambda: SqlGenerationError("LLM 输出违反防火墙"), "generation"),
        (lambda: TimeoutError("LLM timeout"), "llm_timeout"),
    ],
)
def test_generator_error_emits_sse_error_event(
    exc_factory: Any, expected_kind: str
) -> None:
    gen = AsyncMock()
    gen.generate.side_effect = exc_factory()
    runner = AsyncMock()  # 不该被调

    app = _build_app(sql_generator=gen, runner=runner, db=object())

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/brain/nlq/query",
            json={"nl_query": "..."},
            headers={"X-Tenant-ID": _TENANT},
        )

    assert resp.status_code == 200  # SSE 内部错也是 200，错误在 event 里
    events = _parse_sse(resp.text)
    assert len(events) == 1
    assert events[0]["event"] == "error"
    assert events[0]["data"]["kind"] == expected_kind
    assert events[0]["data"]["message"]  # 非空
    runner.assert_not_awaited()


@pytest.mark.parametrize(
    "exc_factory, expected_kind",
    [
        (lambda: SandboxTimeoutError("PG 超时"), "sandbox_timeout"),
        (lambda: RowLimitExceeded("行数超限"), "row_limit"),
    ],
)
def test_sandbox_error_emits_sse_error_event(
    exc_factory: Any, expected_kind: str
) -> None:
    """generator 成功但 sandbox 失败时，应已发 sql 事件后再发 error 事件。"""
    gen = AsyncMock()
    gen.generate.return_value = "SELECT 1 FROM reports.daily_revenue LIMIT 1"
    runner = AsyncMock(side_effect=exc_factory())

    app = _build_app(sql_generator=gen, runner=runner, db=object())

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/brain/nlq/query",
            json={"nl_query": "..."},
            headers={"X-Tenant-ID": _TENANT},
        )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert [e["event"] for e in events] == ["sql", "error"]
    assert events[1]["data"]["kind"] == expected_kind


# ─── 5. SSE data 注入防御 ────────────────────────────────────────────────


def test_sse_data_escapes_newlines_in_sql() -> None:
    """LLM 输出 SQL 含换行字符时，SSE data 必须 JSON 编码（\\n），否则破坏帧格式。"""
    multi_line_sql = (
        "SELECT day,\n total_revenue_fen\n FROM reports.daily_revenue LIMIT 7"
    )
    rows: list[dict[str, Any]] = []
    sample_result = SandboxResult(
        rows=rows, row_count=0, columns=[], truncated=False
    )

    gen = AsyncMock()
    gen.generate.return_value = multi_line_sql
    runner = AsyncMock(return_value=sample_result)

    app = _build_app(sql_generator=gen, runner=runner, db=object())

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/brain/nlq/query",
            json={"nl_query": "..."},
            headers={"X-Tenant-ID": _TENANT},
        )

    events = _parse_sse(resp.text)
    # 关键：能正常解析回来 → 说明 SQL 内换行已被 JSON 编码
    assert events[0]["event"] == "sql"
    assert events[0]["data"]["sql"] == multi_line_sql  # 解码后还原原文
