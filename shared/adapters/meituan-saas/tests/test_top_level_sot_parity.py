"""CH-02.7a a3 反测：saas 模块必须经由顶层 MeituanClient SoT。

a2 (PR #431) 已把 client.py 行为合并到 shared/adapters/meituan_delivery_adapter.py
作为唯一 SoT；a3 删除 saas/src/client.py 并把 adapter.py 改用顶层 import。

本反测守护两件事：
1. saas.adapter 暴露的 MeituanClient / MeituanAPIError 类身份 == 顶层 SoT
   （未来若有人在 saas/src/ 重建 client.py stub，identity check 会发现）
2. saas.src.client 模块不可 import（防 stub 重生）

a3 impl 之前本测必失败（red phase）；impl 之后必通过（green phase）。
"""

from __future__ import annotations

import importlib.util


def test_saas_adapter_meituan_client_is_top_level_sot():
    """saas.adapter.MeituanClient 必须 is top-level SoT 同一类对象。"""
    from shared.adapters.meituan_delivery_adapter import (
        MeituanClient as TopLevelMeituanClient,
    )
    from src.adapter import MeituanClient

    assert MeituanClient is TopLevelMeituanClient, (
        "saas.adapter.MeituanClient 必须 is top-level "
        "shared.adapters.meituan_delivery_adapter.MeituanClient — "
        "禁止重新引入 saas/src/client.py stub"
    )


def test_saas_adapter_meituan_api_error_is_top_level_sot():
    """saas.adapter.MeituanAPIError 必须 is top-level SoT 同一类对象。"""
    from shared.adapters.meituan_delivery_adapter import (
        MeituanAPIError as TopLevelMeituanAPIError,
    )
    from src.adapter import MeituanAPIError

    assert MeituanAPIError is TopLevelMeituanAPIError, (
        "saas.adapter.MeituanAPIError 必须 is top-level SoT — "
        "禁止重新引入 saas/src/client.py stub"
    )


def test_no_phantom_client_module_under_saas_src():
    """saas/src/client.py 已在 a3 删除，不应可 import（防 stub 重生）。

    conftest.py 把 meituan-saas/ 加入 sys.path，src.client 解析到 saas/src/client.py；
    a3 删除后此 spec 必须为 None。
    """
    spec = importlib.util.find_spec("src.client")
    assert spec is None, (
        "saas/src/client.py 已在 CH-02.7a a3 删除作为 dead duplicate，"
        f"禁止重新引入。发现可 import spec: {spec}"
    )
