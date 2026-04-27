"""pytest fixtures for ToxiproxyClient.

用法（在测试文件顶部）：
    from shared.test_infra.fixtures import toxiproxy

    @pytest.mark.toxiproxy_required
    @pytest.mark.asyncio
    async def test_pg_high_latency(toxiproxy):
        await toxiproxy.add_latency("pg_proxy", ms=500)
        # ... run scenario ...

fixture 在 yield 后自动 reset，所以不必在测试里手动清理。

注：使用本 fixture 的测试**必须**用 @pytest.mark.toxiproxy_required 标记，
以便 CI 在 toxiproxy 容器未启动时跳过。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest_asyncio

from shared.test_infra.toxiproxy_client import ToxiproxyClient

TOXIPROXY_URL = os.environ.get("TOXIPROXY_URL", "http://localhost:8474")


@pytest_asyncio.fixture
async def toxiproxy() -> AsyncIterator[ToxiproxyClient]:
    """提供 ToxiproxyClient，并在测试结束后自动 reset 所有 toxics。"""
    async with ToxiproxyClient(base_url=TOXIPROXY_URL) as client:
        if not await client.health():
            import pytest

            pytest.skip(
                f"toxiproxy unreachable at {TOXIPROXY_URL} — "
                "启动: docker compose -f infra/docker/docker-compose.toxiproxy.yml up -d"
            )
        try:
            yield client
        finally:
            # 即使测试抛错也清理
            try:
                await client.reset()
            except Exception as exc:  # noqa: BLE001 — fixture cleanup 兜底
                import logging

                logging.getLogger(__name__).warning(
                    "toxiproxy reset failed during teardown: %s", exc
                )
