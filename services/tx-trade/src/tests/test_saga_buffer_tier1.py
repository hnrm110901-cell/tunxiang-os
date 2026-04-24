"""test_saga_buffer_tier1 — Sprint A2 Saga SQLite 缓冲 Tier1 徐记海鲜场景

Tier1 铁律（CLAUDE.md §17/§20）：
  - 测试用例全部基于真实餐厅场景（非技术边界值）
  - 断网 4h 零数据丢失 + P99 < 200ms + 支付成功率 > 99.9%
  - 先写测试，后写实现（本文件在实装后补齐符号引用，但行为锁定在此）

8 条场景（与工单 Step 2 对应）：
  1. test_xujihaixian_network_drop_100_orders_buffered_to_sqlite
     — 断网 4h 期间收银端推送 100 单 → SQLite 本地暂存 → 恢复后全部补发成功
  2. test_xujihaixian_idempotency_key_dedup_same_order_twice
     — 同一 settle:{orderId} 提交 2 次 → UPSERT 去重，saga_id 共享
  3. test_xujihaixian_4h_buffer_auto_expire_cleanup
     — 超 4h 未补发 → sweep_expired 标 dead_letter，不自动删除
  4. test_xujihaixian_saga_buffer_disk_full_safe_degrade
     — 磁盘写满 → 降级内存队列 + 打 disk_io_error，不崩溃（A1 R1）
  5. test_xujihaixian_200_concurrent_checkout_buffer_p99_under_200ms
     — 200 并发 enqueue + flush_ready，结算 P99 < 200ms
  6. test_xujihaixian_saga_id_consistency_front_to_back
     — 前端 abort 3s 后重试，saga_id 通过 idempotency_key 保持一致（防双扣费）
  7. test_xujihaixian_cross_tenant_buffer_isolation
     — tenant_A 的 SQLite 条目不会被 tenant_B Worker 取走（行级隔离）
  8. test_flag_off_legacy_direct_write
     — edge.payment.saga_buffer=off 时保持 legacy 行为（仅验证 flag 命名注册）

数据约定：徐记海鲜长沙店（tenant_A）/ 韶山店（tenant_B）
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

# 只把 edge/mac-station/src 加入 sys.path 尾部（避免 shadow `services.*`：
# edge/mac-station/src 下有个 services/ 子目录，若 insert(0, ...) 会把
# `from services.xxx` 误路由到 mac-station 侧，拖垮同批次 test_payment_saga）。
_ROOT = Path(__file__).resolve().parents[4]
_MAC_STATION_SRC = _ROOT / "edge" / "mac-station" / "src"
if str(_MAC_STATION_SRC) not in sys.path:
    sys.path.append(str(_MAC_STATION_SRC))

from saga_buffer.buffer import (  # noqa: E402
    TTL_SECONDS,
    SagaBuffer,
    SagaBufferState,
    generate_saga_id,
)

# ──────────────── 徐记海鲜测试租户 ────────────────

XUJI_CHANGSHA_TENANT = "00000000-0000-0000-0000-0000000000a1"
XUJI_SHAOSHAN_TENANT = "00000000-0000-0000-0000-0000000000b1"
XUJI_CHANGSHA_STORE = "00000000-0000-0000-0000-0000000000a2"
XUJI_SHAOSHAN_STORE = "00000000-0000-0000-0000-0000000000b2"
POS_DEVICE_A = "pos-xuji-changsha-001"
POS_DEVICE_B = "pos-xuji-shaoshan-001"


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_buffer_path(tmp_path: Path) -> Path:
    """每个测试独立 SQLite 文件（避免跨用例污染）。"""
    return tmp_path / "saga_buffer.db"


@pytest.fixture
async def buffer(tmp_buffer_path: Path):
    buf = SagaBuffer(device_id=POS_DEVICE_A, db_path=tmp_buffer_path)
    await buf.initialize()
    try:
        yield buf
    finally:
        await buf.close()


async def _make_buffer(
    tmp_buffer_path: Path, *, clock=None, device_id: str = POS_DEVICE_A
) -> SagaBuffer:
    """测试辅助：构造并初始化 SagaBuffer。测试自己负责 await buf.close()。"""
    buf = SagaBuffer(device_id=device_id, db_path=tmp_buffer_path, clock=clock)
    await buf.initialize()
    return buf


# ─── 1. 断网 100 单零丢失 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_xujihaixian_network_drop_100_orders_buffered_to_sqlite(
    tmp_buffer_path: Path,
):
    """徐记海鲜长沙店断网 4h，收银端 100 单全部入 SQLite，恢复后 Flusher
    全部补发成功，SQLite 无数据丢失。"""
    buf = await _make_buffer(tmp_buffer_path)
    try:
        orders = []
        for i in range(100):
            order_no = f"XJ20260424-{i:05d}"
            ikey = f"settle:{order_no}"
            saga_id = generate_saga_id()
            await buf.enqueue(
                idempotency_key=ikey,
                tenant_id=XUJI_CHANGSHA_TENANT,
                store_id=XUJI_CHANGSHA_STORE,
                saga_id=saga_id,
                payload={"amount_fen": 8800 + i, "order_no": order_no},
            )
            orders.append((ikey, saga_id))

        stats = await buf.stats(tenant_id=XUJI_CHANGSHA_TENANT)
        assert stats.pending_count == 100, (
            f"expect 100 pending, got {stats.pending_count}"
        )
        assert stats.dead_letter_count == 0
        assert stats.sent_count == 0

        # 恢复联网：依次标 sent
        ready = await buf.flush_ready(tenant_id=XUJI_CHANGSHA_TENANT, limit=200)
        assert len(ready) == 100, "100 单全部可 flush"
        for entry in ready:
            await buf.mark_sent(entry.idempotency_key)

        # 再次统计：100 全部 sent
        stats_after = await buf.stats(tenant_id=XUJI_CHANGSHA_TENANT)
        assert stats_after.sent_count == 100
        assert stats_after.pending_count == 0
        assert stats_after.dead_letter_count == 0
    finally:
        await buf.close()


# ─── 2. 幂等键去重 ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_xujihaixian_idempotency_key_dedup_same_order_twice(
    tmp_buffer_path: Path,
):
    """徐记海鲜收银员小王对同一单 O-00047 在 3 秒内重试 2 次（前端 abort
    → retry），SQLite UPSERT 去重，saga_id 复用（防 saga 双扣费）。"""
    buf = await _make_buffer(tmp_buffer_path)
    try:
        ikey = "settle:XJ20260424-00047"
        first_saga = generate_saga_id()
        second_saga = generate_saga_id()
        assert first_saga != second_saga

        e1 = await buf.enqueue(
            idempotency_key=ikey,
            tenant_id=XUJI_CHANGSHA_TENANT,
            store_id=XUJI_CHANGSHA_STORE,
            saga_id=first_saga,
            payload={"amount_fen": 12800},
        )
        # 第二次提交带新 saga_id，但 buffer 必须返回既有 entry
        e2 = await buf.enqueue(
            idempotency_key=ikey,
            tenant_id=XUJI_CHANGSHA_TENANT,
            store_id=XUJI_CHANGSHA_STORE,
            saga_id=second_saga,
            payload={"amount_fen": 12800, "retry": True},
        )
        assert e1.saga_id == first_saga
        assert e2.saga_id == first_saga, "saga_id 必须复用，防双扣费"
        stats = await buf.stats(tenant_id=XUJI_CHANGSHA_TENANT)
        assert stats.pending_count == 1, "两次 enqueue 仍然只有 1 条"
    finally:
        await buf.close()


# ─── 3. 4h TTL dead letter（不自动删除）─────────────────────────────────────


@pytest.mark.asyncio
async def test_xujihaixian_4h_buffer_auto_expire_cleanup(tmp_buffer_path: Path):
    """徐记海鲜门店停电 5 小时，恢复后超 4h 未补发的订单进 dead_letter，
    等人工核销（不自动删除，防止"悄无声息吞单"）。"""
    fake_now = [1_700_000_000]

    def clock():
        return fake_now[0]

    buf = await _make_buffer(tmp_buffer_path, clock=clock)
    try:
        ikey = "settle:XJ20260424-TTL-001"
        await buf.enqueue(
            idempotency_key=ikey,
            tenant_id=XUJI_CHANGSHA_TENANT,
            store_id=XUJI_CHANGSHA_STORE,
            saga_id=generate_saga_id(),
            payload={"amount_fen": 9900},
        )

        # 推进到 4h + 1s 之后
        fake_now[0] += TTL_SECONDS + 1

        # flush_ready 不应返回过期条目
        ready = await buf.flush_ready(tenant_id=XUJI_CHANGSHA_TENANT)
        assert ready == [], "过期条目不应出现在 flush_ready"

        # sweep_expired 标 dead_letter
        swept = await buf.sweep_expired(tenant_id=XUJI_CHANGSHA_TENANT)
        assert swept == 1

        # entry 仍然存在（不删除），状态为 dead_letter
        entry = await buf.get(ikey, tenant_id=XUJI_CHANGSHA_TENANT)
        assert entry is not None, "4h 到期条目不自动删除"
        assert entry.state == SagaBufferState.DEAD_LETTER
        assert entry.last_error == "ttl_expired_4h"

        stats = await buf.stats(tenant_id=XUJI_CHANGSHA_TENANT)
        assert stats.dead_letter_count == 1
    finally:
        await buf.close()


# ─── 4. 磁盘满降级内存 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_xujihaixian_saga_buffer_disk_full_safe_degrade():
    """徐记海鲜门店 Mac mini /var 目录磁盘 100% 满，SagaBuffer 必须降级到
    内存队列（不崩溃），并打 disk_io_error 对齐 A1 R1。"""
    # 用一个不存在且无法创建的只读路径模拟权限拒绝
    # /_readonly_root 父目录不可写，SagaBuffer 应触发 memory fallback
    unwritable_path = Path("/_readonly_root/saga_buffer.db")
    buf = SagaBuffer(device_id=POS_DEVICE_A, db_path=unwritable_path)
    await buf.initialize()
    try:
        assert buf.is_memory_mode, "磁盘不可写必须降级内存模式"

        ikey = "settle:XJ20260424-DISK-FULL"
        entry = await buf.enqueue(
            idempotency_key=ikey,
            tenant_id=XUJI_CHANGSHA_TENANT,
            store_id=XUJI_CHANGSHA_STORE,
            saga_id=generate_saga_id(),
            payload={"amount_fen": 6800},
        )
        assert entry.idempotency_key == ikey
        assert entry.state == SagaBufferState.PENDING

        # 基本行为仍工作
        ready = await buf.flush_ready(tenant_id=XUJI_CHANGSHA_TENANT)
        assert len(ready) == 1
        await buf.mark_sent(ikey)
        stats = await buf.stats(tenant_id=XUJI_CHANGSHA_TENANT)
        assert stats.mode == "memory"
        assert stats.sent_count == 1
    finally:
        await buf.close()


# ─── 5. 200 并发 P99 < 200ms ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_xujihaixian_200_concurrent_checkout_buffer_p99_under_200ms(
    tmp_buffer_path: Path,
):
    """徐记海鲜晚高峰 200 桌并发结算，enqueue + flush_ready 单次 P99 < 200ms。
    验证 aiosqlite 异步不阻塞主业务。"""
    buf = await _make_buffer(tmp_buffer_path)
    try:
        async def one_checkout(i: int) -> float:
            t0 = time.perf_counter()
            await buf.enqueue(
                idempotency_key=f"settle:XJ-LOAD-{i:05d}",
                tenant_id=XUJI_CHANGSHA_TENANT,
                store_id=XUJI_CHANGSHA_STORE,
                saga_id=generate_saga_id(),
                payload={"amount_fen": 8800 + i},
            )
            # 模拟 Flusher 单次查询
            await buf.flush_ready(tenant_id=XUJI_CHANGSHA_TENANT, limit=10)
            return (time.perf_counter() - t0) * 1000  # ms

        # 200 并发
        durations = await asyncio.gather(
            *(one_checkout(i) for i in range(200))
        )
        durations.sort()
        p99_idx = int(len(durations) * 0.99)
        p99 = durations[p99_idx]
        assert p99 < 200.0, f"P99={p99:.1f}ms 超标（Tier1 门槛 200ms）"

        stats = await buf.stats(tenant_id=XUJI_CHANGSHA_TENANT)
        assert stats.pending_count == 200
    finally:
        await buf.close()


# ─── 6. 前端 abort 重试 saga_id 一致性 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_xujihaixian_saga_id_consistency_front_to_back(tmp_buffer_path: Path):
    """徐记海鲜收银员扫码支付,3s 后前端 abort 自动重试(A1 合约),
    SagaBuffer 必须通过 idempotency_key=settle:O-001 保证 saga_id 不变,
    下游 tx-trade settle/retry 凭此复用既有 saga 状态(防双扣费)。"""
    buf = await _make_buffer(tmp_buffer_path)
    try:
        order_id = "XJ20260424-SAGA-ID-001"
        ikey = f"settle:{order_id}"

        # 第一次：前端首次提交
        saga_id_initial = generate_saga_id()
        e1 = await buf.enqueue(
            idempotency_key=ikey,
            tenant_id=XUJI_CHANGSHA_TENANT,
            store_id=XUJI_CHANGSHA_STORE,
            saga_id=saga_id_initial,
            payload={"amount_fen": 18800},
        )
        # Flusher 开始补发但尚未完成
        await buf.mark_flushing(ikey)

        # 第二次：前端 3s abort 后 AbortController 重试 → 新 saga_id 候选
        saga_id_retry = generate_saga_id()
        e2 = await buf.enqueue(
            idempotency_key=ikey,
            tenant_id=XUJI_CHANGSHA_TENANT,
            store_id=XUJI_CHANGSHA_STORE,
            saga_id=saga_id_retry,  # 新候选，但必须被拒
            payload={"amount_fen": 18800, "retry": True},
        )

        # saga_id 必须与初次一致，retry payload 不覆盖
        assert e1.saga_id == saga_id_initial
        assert e2.saga_id == saga_id_initial, (
            "重试必须复用首次 saga_id（防双扣费）"
        )
        assert e2.state == SagaBufferState.FLUSHING  # 状态保持

        # 通过 get 再次确认持久化的值
        stored = await buf.get(ikey, tenant_id=XUJI_CHANGSHA_TENANT)
        assert stored is not None
        assert stored.saga_id == saga_id_initial
    finally:
        await buf.close()


# ─── 7. 跨租户行级隔离 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_xujihaixian_cross_tenant_buffer_isolation(tmp_buffer_path: Path):
    """徐记海鲜长沙店 tenant_A 与韶山店 tenant_B 共享一个 Mac mini 场景
    （多租户压测）。tenant_B 的 Flusher 扫表时绝不能捞到 tenant_A 的条目。"""
    buf = await _make_buffer(tmp_buffer_path)
    try:
        # tenant_A 3 单
        for i in range(3):
            await buf.enqueue(
                idempotency_key=f"settle:A-{i}",
                tenant_id=XUJI_CHANGSHA_TENANT,
                store_id=XUJI_CHANGSHA_STORE,
                saga_id=generate_saga_id(),
                payload={"amount_fen": 100 + i},
            )

        # tenant_B 2 单
        for i in range(2):
            await buf.enqueue(
                idempotency_key=f"settle:B-{i}",
                tenant_id=XUJI_SHAOSHAN_TENANT,
                store_id=XUJI_SHAOSHAN_STORE,
                saga_id=generate_saga_id(),
                payload={"amount_fen": 200 + i},
            )

        a_ready = await buf.flush_ready(tenant_id=XUJI_CHANGSHA_TENANT)
        b_ready = await buf.flush_ready(tenant_id=XUJI_SHAOSHAN_TENANT)

        assert len(a_ready) == 3
        assert len(b_ready) == 2
        assert all(e.tenant_id == XUJI_CHANGSHA_TENANT for e in a_ready)
        assert all(e.tenant_id == XUJI_SHAOSHAN_TENANT for e in b_ready)

        # get 跨租户必须返回 None
        a_key = "settle:A-0"
        assert await buf.get(a_key, tenant_id=XUJI_SHAOSHAN_TENANT) is None, (
            "tenant_B 不得读取 tenant_A 条目（行级隔离铁律）"
        )
        assert await buf.get(a_key, tenant_id=XUJI_CHANGSHA_TENANT) is not None

        # stats 租户独立
        stats_a = await buf.stats(tenant_id=XUJI_CHANGSHA_TENANT)
        stats_b = await buf.stats(tenant_id=XUJI_SHAOSHAN_TENANT)
        assert stats_a.pending_count == 3
        assert stats_b.pending_count == 2
    finally:
        await buf.close()


# ─── 8. Flag 默认 off（legacy 直写）───────────────────────────────────────────


def test_flag_off_legacy_direct_write():
    """edge.payment.saga_buffer 默认 off。验证 flag 名称注册到位，
    未注册时 is_enabled 返回 False（legacy 行为兜底）。"""
    from shared.feature_flags.flag_names import EdgeFlags

    assert EdgeFlags.PAYMENT_SAGA_BUFFER == "edge.payment.saga_buffer"

    # 解析 edge_flags.yaml 并定位该 flag
    import yaml

    flag_file = (
        _ROOT / "flags" / "edge" / "edge_flags.yaml"
    )
    data = yaml.safe_load(flag_file.read_text(encoding="utf-8"))
    names = {f["name"]: f for f in data["flags"]}
    assert EdgeFlags.PAYMENT_SAGA_BUFFER in names, "flag 未注册到 edge_flags.yaml"
    flag = names[EdgeFlags.PAYMENT_SAGA_BUFFER]
    assert flag["defaultValue"] is False, "Tier1 Flag 默认必须 off"
    # 各环境均 off，符合 5%→50%→100% 灰度铁律
    for env in ("dev", "test", "uat", "pilot", "prod"):
        assert flag["environments"][env] is False, f"env={env} 不应默认开启"
    # rollout 节奏
    assert flag["rollout"] == [5, 50, 100]
    # tier1 tag 必须存在（运维灰度发布时必查）
    assert "tier1" in flag["tags"]
