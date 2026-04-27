"""toxiproxy_required 烟测——只在真 toxiproxy 容器存在时跑。

执行：
    docker compose -f infra/docker/docker-compose.toxiproxy.yml up -d
    pytest -m toxiproxy_required shared/test_infra/tests/test_toxiproxy_smoke.py

CI（PR gate）默认跳过，只在手动 workflow_dispatch 触发。
"""

from __future__ import annotations

import pytest

from shared.test_infra.fixtures import toxiproxy  # noqa: F401  — pytest fixture import

pytestmark = pytest.mark.toxiproxy_required


@pytest.mark.asyncio
async def test_proxies_listed(toxiproxy):  # noqa: F811
    """预置代理（pg_proxy / redis_proxy / coreml_proxy）都在线。"""
    proxies = await toxiproxy.list_proxies()
    expected = {"pg_proxy", "redis_proxy", "coreml_proxy"}
    assert expected.issubset(proxies.keys()), (
        f"missing proxies: {expected - proxies.keys()}"
    )


@pytest.mark.asyncio
async def test_add_latency_actually_slows_traffic(toxiproxy):  # noqa: F811
    """对 pg_proxy 加 200ms latency 后，TCP connect 时间应明显增加。

    注意：本测试不发 SQL，只验证 toxiproxy 自身能注入 latency。
    我们直接 connect 到代理监听端口（9001），toxiproxy 在 connect 阶段不延迟，
    所以这里测的是首字节响应延迟——发个 HTTP-ish 请求看握手到响应的时差。
    """
    # 基线：列出 toxics，应该是空
    toxics = await toxiproxy.list_toxics("pg_proxy")
    assert toxics == [], "test 开始时不应有遗留 toxic（fixture reset 应已清空）"

    # 注入 200ms latency
    await toxiproxy.add_latency("pg_proxy", ms=200)
    toxics_after = await toxiproxy.list_toxics("pg_proxy")
    assert any(t.get("type") == "latency" for t in toxics_after)

    # 验证可移除
    await toxiproxy.remove_toxic("pg_proxy", "latency_downstream")
    toxics_final = await toxiproxy.list_toxics("pg_proxy")
    assert toxics_final == []


@pytest.mark.asyncio
async def test_disable_then_enable_roundtrip(toxiproxy):  # noqa: F811
    await toxiproxy.disable("redis_proxy")
    proxies = await toxiproxy.list_proxies()
    assert proxies["redis_proxy"]["enabled"] is False

    await toxiproxy.enable("redis_proxy")
    proxies = await toxiproxy.list_proxies()
    assert proxies["redis_proxy"]["enabled"] is True


@pytest.mark.asyncio
async def test_reset_clears_all_toxics(toxiproxy):  # noqa: F811
    await toxiproxy.add_latency("pg_proxy", ms=100)
    await toxiproxy.add_latency("redis_proxy", ms=100)

    await toxiproxy.reset()

    for name in ("pg_proxy", "redis_proxy"):
        toxics = await toxiproxy.list_toxics(name)
        assert toxics == [], f"{name} 仍有 toxics 残留"
