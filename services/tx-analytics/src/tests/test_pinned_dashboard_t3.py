"""Tier 3 — S4-04 驾驶舱 Pin 洞察 service 层测试

覆盖（issue #291 acceptance ≥5 测试）：
  - pin add 返回完整 PinnedItem（pin_id / pinned_at / surface_snapshot）
  - list 按最新在前排序
  - FIFO 淘汰：第 21 个 pin 把最旧的挤掉
  - tenant 隔离：tenant=A pin 不出现在 tenant=B list
  - remove 真删（list 不再包含）
  - remove 不存在的 pin_id 返 False
  - tenant_id 空 → ValueError（防 RLS 绕过）

Tier 3 标准（CLAUDE.md §17）：功能测试通过即可（无强制 TDD），mock-based 单元。
"""

from __future__ import annotations

import uuid

import pytest

from ..services.pinned_dashboard import (
    PIN_LIMIT_PER_TENANT,
    PinnedItem,
    _assert_pin_store_mode_safe,
    _clear_for_test,
    add_pin,
    list_pins,
    remove_pin,
)


@pytest.fixture(autouse=True)
def reset_store():
    _clear_for_test()
    yield
    _clear_for_test()


TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
USER_A1 = str(uuid.uuid4())
USER_B1 = str(uuid.uuid4())

_SAMPLE_SURFACE = {
    "version": "0.8",
    "surface": {
        "id": "card-1",
        "type": "card",
        "props": {"title": "本周营收", "severity": "info"},
        "children": [
            {"id": "t1", "type": "text", "props": {"content": "+12.3%"}},
        ],
    },
}


class TestPinnedDashboardT3:
    """店长把 AI 洞察 Pin 到驾驶舱 — 5 类核心场景。"""

    def test_add_pin_returns_complete_item(self):
        """店长 Pin 一条"本周营收洞察" → 返回含 pin_id / pinned_at / 完整 surface_snapshot。"""
        item = add_pin(
            tenant_id=TENANT_A,
            pinner_user_id=USER_A1,
            surface_snapshot=_SAMPLE_SURFACE,
            source_natural_query="本周营收同比怎样",
        )
        assert isinstance(item, PinnedItem)
        assert item.pin_id  # 非空
        assert item.tenant_id == TENANT_A
        assert item.pinner_user_id == USER_A1
        assert item.surface_snapshot == _SAMPLE_SURFACE
        assert item.source_natural_query == "本周营收同比怎样"

    def test_list_pins_newest_first(self):
        """连续 Pin 三条 → list 按最新在前（栈顶序）。"""
        a = add_pin(tenant_id=TENANT_A, pinner_user_id=USER_A1, surface_snapshot={"v": "a"})
        b = add_pin(tenant_id=TENANT_A, pinner_user_id=USER_A1, surface_snapshot={"v": "b"})
        c = add_pin(tenant_id=TENANT_A, pinner_user_id=USER_A1, surface_snapshot={"v": "c"})
        pins = list_pins(TENANT_A)
        assert [p.pin_id for p in pins] == [c.pin_id, b.pin_id, a.pin_id]

    def test_fifo_eviction_at_limit(self):
        """连续 Pin 21 条 → 第 21 条把最旧的（第 1 条）挤掉，list 永远 ≤ PIN_LIMIT_PER_TENANT。"""
        first = add_pin(
            tenant_id=TENANT_A, pinner_user_id=USER_A1, surface_snapshot={"i": 0}
        )
        for i in range(1, PIN_LIMIT_PER_TENANT + 1):
            add_pin(tenant_id=TENANT_A, pinner_user_id=USER_A1, surface_snapshot={"i": i})

        pins = list_pins(TENANT_A)
        assert len(pins) == PIN_LIMIT_PER_TENANT
        assert all(p.pin_id != first.pin_id for p in pins), "第 1 条应该被 FIFO 挤掉"

    def test_tenant_isolation(self):
        """tenant=A Pin 一条 → tenant=B list 看不到（RLS 隔离 stub，PR2 上真 RLS）。"""
        add_pin(tenant_id=TENANT_A, pinner_user_id=USER_A1, surface_snapshot={"who": "A"})
        add_pin(tenant_id=TENANT_B, pinner_user_id=USER_B1, surface_snapshot={"who": "B"})

        a_pins = list_pins(TENANT_A)
        b_pins = list_pins(TENANT_B)

        assert len(a_pins) == 1
        assert a_pins[0].surface_snapshot == {"who": "A"}
        assert len(b_pins) == 1
        assert b_pins[0].surface_snapshot == {"who": "B"}

    def test_remove_existing_pin_returns_true(self):
        """店长 Unpin 一条 → list 不再包含，remove 返 True。"""
        item = add_pin(tenant_id=TENANT_A, pinner_user_id=USER_A1, surface_snapshot={})
        ok = remove_pin(tenant_id=TENANT_A, pin_id=item.pin_id)
        assert ok is True
        assert all(p.pin_id != item.pin_id for p in list_pins(TENANT_A))

    def test_remove_nonexistent_pin_returns_false(self):
        """Unpin 不存在的 pin_id → 返 False，不抛异常。"""
        ok = remove_pin(tenant_id=TENANT_A, pin_id="ghost-pin-id")
        assert ok is False

    def test_remove_does_not_cross_tenant(self):
        """tenant=A 的 pin 不能被 tenant=B 的 remove 调用删掉（防 RLS 绕过）。"""
        item = add_pin(tenant_id=TENANT_A, pinner_user_id=USER_A1, surface_snapshot={})
        ok = remove_pin(tenant_id=TENANT_B, pin_id=item.pin_id)
        assert ok is False, "跨 tenant remove 必须返 False"
        assert len(list_pins(TENANT_A)) == 1, "原 tenant 的 pin 不可被跨 tenant 删除"

    def test_empty_tenant_id_rejected(self):
        """tenant_id 空 → ValueError（防 RLS 绕过）。"""
        with pytest.raises(ValueError, match="tenant_id"):
            add_pin(tenant_id="", pinner_user_id=USER_A1, surface_snapshot={})
        with pytest.raises(ValueError, match="tenant_id"):
            list_pins("")
        with pytest.raises(ValueError, match="tenant_id"):
            remove_pin(tenant_id="", pin_id="anything")


class TestPinStoreFailFastT3:
    """生产 / 预发启动 fail-fast — 多 worker 部署 in-memory store 数据分裂保护。

    PR1 阶段 _PINNED_STORE 是 module-level dict，N worker 部署时每 worker 持有
    独立副本。pin add 在 worker-A，下次请求路由到 worker-B 看不到 → 静默数据
    分裂。本组测试验证 module-load 校验把"已知缺陷"转成"启动失败"。
    """

    def test_production_without_ack_raises(self):
        """TUNXIANG_ENV=production 未 ack → 抛 RuntimeError，K8s pod 启动失败。"""
        with pytest.raises(RuntimeError, match="多 worker"):
            _assert_pin_store_mode_safe({"TUNXIANG_ENV": "production"})

    def test_staging_without_ack_raises(self):
        """TUNXIANG_ENV=staging 未 ack → 抛 RuntimeError（预发同生产对待）。"""
        with pytest.raises(RuntimeError, match="多 worker"):
            _assert_pin_store_mode_safe({"TUNXIANG_ENV": "staging"})

    def test_production_with_acknowledged_passes(self):
        """生产 + TX_PIN_STORE_MODE=in_memory_acknowledged → 放行（单 worker 试用）。"""
        _assert_pin_store_mode_safe(
            {
                "TUNXIANG_ENV": "production",
                "TX_PIN_STORE_MODE": "in_memory_acknowledged",
            }
        )

    def test_dev_environment_passes_silently(self):
        """开发环境无需任何 env，import 不抛错（既有测试不被破坏）。"""
        _assert_pin_store_mode_safe({"TUNXIANG_ENV": "development"})

    def test_unset_env_passes(self):
        """完全空 env → 不抛错（CI / 本地测试 / docker compose without TUNXIANG_ENV）。"""
        _assert_pin_store_mode_safe({})
