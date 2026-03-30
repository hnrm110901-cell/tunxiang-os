"""外卖出餐码服务 — 单元测试

覆盖场景（≥ 8 个）：
1.  生成出餐码 — 格式为 6 位字母数字
2.  幂等生成 — 同一 order 重复调用返回相同 code
3.  扫码确认 — 成功路径，confirmed=True，记录时间戳
4.  重复扫码 — already_confirmed=True，不报错
5.  错误 code — ScanResult.success=False，error 说明
6.  平台回调失败不阻塞 — 回调网络错误，扫码仍返回 success
7.  跨租户隔离 — 租户 A 的 code 不能被租户 B 扫
8.  待确认列表 — 只返回未确认订单
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import re
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest


# ─── 工具 ───

def _uid() -> str:
    return str(uuid.uuid4())


TENANT_A = _uid()
TENANT_B = _uid()


def _clear_stores():
    """在测试间清理内存存储，避免状态污染"""
    from services.dispatch_code_service import _store_by_order, _store_by_code
    _store_by_order.clear()
    _store_by_code.clear()


# ─── 测试 1: 生成出餐码格式 ───

@pytest.mark.asyncio
async def test_generate_code_format():
    """生成的出餐码必须是 6 位字母数字（base62）"""
    _clear_stores()
    from services.dispatch_code_service import DispatchCodeService

    order_id = _uid()
    dc = await DispatchCodeService.generate(
        order_id=order_id,
        tenant_id=TENANT_A,
        platform="meituan",
    )

    assert len(dc.code) == 6, f"出餐码长度应为 6，实际: {len(dc.code)}"
    assert re.fullmatch(r"[A-Za-z0-9]{6}", dc.code), (
        f"出餐码应为字母数字，实际: {dc.code}"
    )
    assert dc.order_id == order_id
    assert dc.tenant_id == TENANT_A
    assert dc.platform == "meituan"
    assert dc.confirmed is False
    assert dc.confirmed_at is None


# ─── 测试 2: 幂等生成 ───

@pytest.mark.asyncio
async def test_generate_idempotent():
    """同一订单重复生成，返回相同 code（幂等）"""
    _clear_stores()
    from services.dispatch_code_service import DispatchCodeService

    order_id = _uid()
    dc1 = await DispatchCodeService.generate(
        order_id=order_id,
        tenant_id=TENANT_A,
        platform="eleme",
    )
    dc2 = await DispatchCodeService.generate(
        order_id=order_id,
        tenant_id=TENANT_A,
        platform="eleme",
    )

    assert dc1.code == dc2.code, "幂等调用应返回相同出餐码"
    assert dc1.id == dc2.id, "幂等调用应返回同一记录"


# ─── 测试 3: 扫码确认成功路径 ───

@pytest.mark.asyncio
async def test_confirm_by_scan_success():
    """扫码确认：confirmed=True，记录 confirmed_at 和 operator_id"""
    _clear_stores()
    from services.dispatch_code_service import DispatchCodeService

    order_id = _uid()
    operator_id = _uid()

    dc = await DispatchCodeService.generate(
        order_id=order_id,
        tenant_id=TENANT_A,
        platform="douyin",
    )
    code = dc.code

    result = await DispatchCodeService.confirm_by_scan(
        code=code,
        operator_id=operator_id,
        tenant_id=TENANT_A,
    )

    assert result.success is True
    assert result.order_id == order_id
    assert result.platform == "douyin"
    assert result.already_confirmed is False
    assert result.error is None

    # 验证持久化状态
    updated = await DispatchCodeService.get_by_order(
        order_id=order_id,
        tenant_id=TENANT_A,
    )
    assert updated is not None
    assert updated.confirmed is True
    assert updated.confirmed_at is not None
    assert isinstance(updated.confirmed_at, datetime)
    assert updated.operator_id == operator_id


# ─── 测试 4: 重复扫码 ───

@pytest.mark.asyncio
async def test_confirm_already_confirmed():
    """重复扫码应返回 already_confirmed=True，不报错"""
    _clear_stores()
    from services.dispatch_code_service import DispatchCodeService

    order_id = _uid()
    operator_id = _uid()

    dc = await DispatchCodeService.generate(
        order_id=order_id,
        tenant_id=TENANT_A,
        platform="meituan",
    )

    # 第一次扫码
    r1 = await DispatchCodeService.confirm_by_scan(
        code=dc.code,
        operator_id=operator_id,
        tenant_id=TENANT_A,
    )
    assert r1.success is True
    assert r1.already_confirmed is False

    # 第二次扫码（重复）
    r2 = await DispatchCodeService.confirm_by_scan(
        code=dc.code,
        operator_id=operator_id,
        tenant_id=TENANT_A,
    )
    assert r2.success is True
    assert r2.already_confirmed is True
    assert r2.error is None


# ─── 测试 5: 错误 code ───

@pytest.mark.asyncio
async def test_confirm_invalid_code():
    """不存在的出餐码，ScanResult.success=False，error 有说明"""
    _clear_stores()
    from services.dispatch_code_service import DispatchCodeService

    result = await DispatchCodeService.confirm_by_scan(
        code="XXXXXX",
        operator_id=_uid(),
        tenant_id=TENANT_A,
    )

    assert result.success is False
    assert result.error is not None
    assert len(result.error) > 0
    assert result.order_id is None


# ─── 测试 6: 平台回调失败不阻塞 ───

@pytest.mark.asyncio
async def test_platform_notify_failure_does_not_block():
    """平台出餐回调网络错误，扫码仍应返回 success=True"""
    _clear_stores()
    from services.dispatch_code_service import DispatchCodeService, set_platform_client

    order_id = _uid()
    operator_id = _uid()

    # 生成出餐码（meituan 是支持的平台，会触发回调）
    dc = await DispatchCodeService.generate(
        order_id=order_id,
        tenant_id=TENANT_A,
        platform="meituan",
    )

    # 注入会抛出 ConnectionError 的 mock 客户端
    class _FailingClient:
        async def notify_dispatch(self, platform: str, order_id: str) -> dict:
            raise ConnectionError("平台网络不可达")

    original_client = None
    from services import dispatch_code_service as _svc
    original_client = _svc._platform_client
    set_platform_client(_FailingClient())

    try:
        result = await DispatchCodeService.confirm_by_scan(
            code=dc.code,
            operator_id=operator_id,
            tenant_id=TENANT_A,
        )
        # 回调失败不阻塞，扫码仍成功
        assert result.success is True
        assert result.already_confirmed is False
        assert result.order_id == order_id
    finally:
        set_platform_client(original_client)


# ─── 测试 7: 跨租户隔离 ───

@pytest.mark.asyncio
async def test_cross_tenant_isolation():
    """租户 A 的出餐码不能被租户 B 扫到"""
    _clear_stores()
    from services.dispatch_code_service import DispatchCodeService

    order_id = _uid()
    operator_id = _uid()

    # 租户 A 生成出餐码
    dc = await DispatchCodeService.generate(
        order_id=order_id,
        tenant_id=TENANT_A,
        platform="eleme",
    )
    code_a = dc.code

    # 租户 B 用同一 code 扫码 → 应失败
    result = await DispatchCodeService.confirm_by_scan(
        code=code_a,
        operator_id=operator_id,
        tenant_id=TENANT_B,
    )

    assert result.success is False
    assert result.error is not None

    # 租户 A 自己扫 → 成功
    result_a = await DispatchCodeService.confirm_by_scan(
        code=code_a,
        operator_id=operator_id,
        tenant_id=TENANT_A,
    )
    assert result_a.success is True


# ─── 测试 8: 待确认列表只返回未确认订单 ───

@pytest.mark.asyncio
async def test_list_pending_only_unconfirmed():
    """list_pending 只返回 confirmed=False 的出餐码"""
    _clear_stores()
    from services.dispatch_code_service import DispatchCodeService

    tenant_id = _uid()
    operator_id = _uid()
    store_id = _uid()

    # 创建 3 条出餐码
    dc1 = await DispatchCodeService.generate(
        order_id=_uid(), tenant_id=tenant_id, platform="meituan"
    )
    dc2 = await DispatchCodeService.generate(
        order_id=_uid(), tenant_id=tenant_id, platform="eleme"
    )
    dc3 = await DispatchCodeService.generate(
        order_id=_uid(), tenant_id=tenant_id, platform="douyin"
    )

    # 确认 dc1
    await DispatchCodeService.confirm_by_scan(
        code=dc1.code,
        operator_id=operator_id,
        tenant_id=tenant_id,
    )

    pending = await DispatchCodeService.list_pending(
        tenant_id=tenant_id,
        store_id=store_id,
    )

    pending_ids = {p.order_id for p in pending}
    assert dc1.order_id not in pending_ids, "已确认的订单不应在待确认列表中"
    assert dc2.order_id in pending_ids
    assert dc3.order_id in pending_ids
    assert len(pending) == 2


# ─── 测试 9: get_by_order 不存在时返回 None ───

@pytest.mark.asyncio
async def test_get_by_order_not_found():
    """不存在的 order_id 返回 None"""
    _clear_stores()
    from services.dispatch_code_service import DispatchCodeService

    result = await DispatchCodeService.get_by_order(
        order_id=_uid(),
        tenant_id=TENANT_A,
    )
    assert result is None


# ─── 测试 10: 生成出餐码包含纯数字字串也有效 ───

@pytest.mark.asyncio
async def test_generate_code_base62_chars():
    """生成的 code 字符集严格为 A-Z、a-z、0-9"""
    _clear_stores()
    import string
    from services.dispatch_code_service import generate_dispatch_code

    allowed = set(string.ascii_uppercase + string.ascii_lowercase + string.digits)
    for _ in range(20):
        code = generate_dispatch_code(order_id=_uid(), tenant_id=_uid())
        assert set(code).issubset(allowed), f"code 含非法字符: {code}"
        assert len(code) == 6
