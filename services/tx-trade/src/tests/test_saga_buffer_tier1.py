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


# ─── 9. 启动时 flushing → pending 复位（进程崩溃后死单泄漏修复） ──────────────


@pytest.mark.asyncio
async def test_xujihaixian_flushing_reset_on_initialize_after_crash(
    tmp_buffer_path: Path,
    monkeypatch,
):
    """徐记海鲜门店 Mac mini 在补发某单时进程被 kill -9（电源拔出 / OOM），
    SQLite 中残留 state='flushing' 的条目。重启后 SagaBuffer.initialize 必须
    将这些"无主"条目复位为 pending，否则下一轮 flush_ready (WHERE state=
    'pending') 永远不会再选中它们 → 死单泄漏。

    场景：长沙店收银员小王结账 O-77777 → Flusher mark_flushing 后 POST 阶段
    Mac mini 断电 → entry 卡在 flushing → 重启后必须重新进入 pending 队列。
    """
    # 第一次：手工注入 flushing 条目（模拟崩溃前的现场）
    buf1 = SagaBuffer(device_id=POS_DEVICE_A, db_path=tmp_buffer_path)
    await buf1.initialize()
    await buf1.enqueue(
        idempotency_key="settle:XJ20260424-CRASH-001",
        tenant_id=XUJI_CHANGSHA_TENANT,
        store_id=XUJI_CHANGSHA_STORE,
        saga_id=generate_saga_id(),
        payload={"amount_fen": 18800},
    )
    await buf1.mark_flushing("settle:XJ20260424-CRASH-001")
    # 直接在底层连接上再插一条 flushing 条目（模拟崩溃前 Flusher 已切到 flushing
    # 但 POST 没回来），避免依赖 mark_flushing 的当前实现细节
    now_ts = int(time.time())
    expires_ts = now_ts + TTL_SECONDS
    await buf1._conn.execute(
        "INSERT INTO saga_buffer "
        "(idempotency_key, tenant_id, store_id, device_id, saga_id, "
        " payload_json, attempts, state, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, 'flushing', ?, ?)",
        (
            "settle:XJ20260424-CRASH-002",
            XUJI_CHANGSHA_TENANT,
            XUJI_CHANGSHA_STORE,
            POS_DEVICE_A,
            generate_saga_id(),
            '{"amount_fen": 25800}',
            now_ts,
            expires_ts,
        ),
    )
    await buf1._conn.commit()

    # 验证：崩溃前 flush_ready 取不到 flushing 条目（即"死单泄漏"现象）
    pre_ready = await buf1.flush_ready(tenant_id=XUJI_CHANGSHA_TENANT)
    assert pre_ready == [], "flushing 条目本来就被 flush_ready WHERE state='pending' 排除"

    # 不调用 mark_sent，直接 close 模拟崩溃 / 重启
    await buf1.close()

    # 第二次：重新打开同一个 SQLite 文件 — initialize 必须把 flushing 全部复位
    captured_warnings: list[tuple[str, dict]] = []

    def fake_warning(event, **kwargs):  # noqa: ANN001
        captured_warnings.append((event, kwargs))

    # patch 模块级 logger，捕获 warning 调用
    from saga_buffer import buffer as buffer_mod

    monkeypatch.setattr(buffer_mod.logger, "warning", fake_warning)

    buf2 = SagaBuffer(device_id=POS_DEVICE_A, db_path=tmp_buffer_path)
    await buf2.initialize()
    try:
        # warning 必须被调用，且 event 名匹配，count == 2
        reset_events = [
            (event, kw)
            for (event, kw) in captured_warnings
            if event == "saga_buffer.flushing_reset_on_startup"
        ]
        assert len(reset_events) == 1, (
            f"启动复位 warning 必须打且只打一次，实际 events={captured_warnings}"
        )
        assert reset_events[0][1]["count"] == 2, (
            f"应复位 2 条 flushing，实际 count={reset_events[0][1].get('count')}"
        )

        # 复位后两条都应回到 pending，flush_ready 必须捞到（否则就是死单泄漏）
        ready = await buf2.flush_ready(tenant_id=XUJI_CHANGSHA_TENANT)
        keys = sorted(e.idempotency_key for e in ready)
        assert keys == [
            "settle:XJ20260424-CRASH-001",
            "settle:XJ20260424-CRASH-002",
        ], f"复位后必须能被 flush_ready 选中，实际 keys={keys}"
        for entry in ready:
            assert entry.state == SagaBufferState.PENDING

        stats = await buf2.stats(tenant_id=XUJI_CHANGSHA_TENANT)
        assert stats.flushing_count == 0
        assert stats.pending_count == 2
    finally:
        await buf2.close()


# ─── 10. 运行期 flushing 卡死自检（5min 阈值）─────────────────────────────────


@pytest.mark.asyncio
async def test_xujihaixian_flushing_stuck_self_check_resets_after_5min(
    tmp_buffer_path: Path,
):
    """徐记海鲜门店 Flusher 进程没崩，但 POST tx-trade 时由于网络半连接卡死
    超过 5min（FLUSHING_STUCK_THRESHOLD_SEC=300），SagaFlusher.heartbeat
    必须自检并强制复位该条目为 pending，让下一轮 flush 能继续推进。

    与崩溃复位的区别：崩溃路径靠 SagaBuffer.initialize 在重启时复位；
    运行期靠 reset_stuck_flushing 周期性自检（heartbeat 触发）。
    """
    fake_now = [1_700_000_000]

    def clock():
        return fake_now[0]

    buf = await _make_buffer(tmp_buffer_path, clock=clock)
    try:
        ikey = "settle:XJ20260424-STUCK-001"
        await buf.enqueue(
            idempotency_key=ikey,
            tenant_id=XUJI_CHANGSHA_TENANT,
            store_id=XUJI_CHANGSHA_STORE,
            saga_id=generate_saga_id(),
            payload={"amount_fen": 8800},
        )
        # T0：mark_flushing（POST 开始）
        await buf.mark_flushing(ikey)

        # 1. 还没到 5min（推进 4min），自检不应复位
        fake_now[0] += 4 * 60
        reset_count = await buf.reset_stuck_flushing(
            threshold_seconds=300,
            tenant_id=XUJI_CHANGSHA_TENANT,
        )
        assert reset_count == 0, "未到 5min 阈值不应复位"
        entry = await buf.get(ikey, tenant_id=XUJI_CHANGSHA_TENANT)
        assert entry is not None
        assert entry.state == SagaBufferState.FLUSHING, "未到阈值仍保持 flushing"

        # 2. 推进到 6min，自检必须复位
        fake_now[0] += 2 * 60  # 累计 6 min
        reset_count = await buf.reset_stuck_flushing(
            threshold_seconds=300,
            tenant_id=XUJI_CHANGSHA_TENANT,
        )
        assert reset_count == 1, "超 5min 必须复位 1 条"

        entry_after = await buf.get(ikey, tenant_id=XUJI_CHANGSHA_TENANT)
        assert entry_after is not None
        assert entry_after.state == SagaBufferState.PENDING
        # last_attempt_at 已被刷新到当前时间
        assert entry_after.last_attempt_at == fake_now[0]

        # 复位后 flush_ready 必须能再次选中（否则修复无意义）
        ready = await buf.flush_ready(tenant_id=XUJI_CHANGSHA_TENANT)
        assert len(ready) == 1
        assert ready[0].idempotency_key == ikey

        # 3. 跨租户隔离：tenant_B 的自检不能动 tenant_A 的条目
        await buf.mark_flushing(ikey)
        fake_now[0] += 10 * 60  # 推进 10min 再次卡死
        reset_for_b = await buf.reset_stuck_flushing(
            threshold_seconds=300,
            tenant_id=XUJI_SHAOSHAN_TENANT,
        )
        assert reset_for_b == 0, "跨租户自检必须 0 命中（行级隔离铁律）"
        entry_b_check = await buf.get(ikey, tenant_id=XUJI_CHANGSHA_TENANT)
        assert entry_b_check.state == SagaBufferState.FLUSHING, (
            "tenant_B 自检不能复位 tenant_A 的条目"
        )
    finally:
        await buf.close()


# ─── 11. 401 JWT 过期不入死信、不增 attempts（Fix-8a） ──────────────────────


class _FakeResponse:
    """SagaFlusher._flush_entry 只用 status_code 与 .json()，构造极简 mock."""

    def __init__(self, status_code: int, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict:
        return self._body


class _FakeHttpClient:
    """记录 POST 调用并按预设序列返回 _FakeResponse。"""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict, dict]] = []

    async def post(self, url, *, json, headers, timeout):  # noqa: A002
        self.calls.append((url, json, headers))
        if not self._responses:
            return _FakeResponse(500)
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_xujihaixian_flush_401_skips_dead_letter_no_attempt_increment(
    tmp_buffer_path: Path,
):
    """徐记海鲜长沙店断网恰好 4h 后 Mac mini 重连云端，但 edge_service JWT
    已过期 → tx-trade 返回 401。Fix-8a 铁律：

      - 不入 dead_letter（凭证过期不该一次性写死，等人工补救）
      - 不增 attempts（凭证问题不消耗 20 次重试预算）
      - state 从 flushing 复位回 pending（下一轮可重新选中）
      - 30s 风暴退避：紧接着的 flush_once 不再 POST 该 entry
      - 调一次 token_refresher（如有注入）
      - 第二轮 flush_once 用刷新后的 JWT 直接 200 → mark_sent
    """
    from saga_buffer.flusher import SagaFlusher  # noqa: E402

    fake_now = [1_700_000_000.0]

    def clock():
        return fake_now[0]

    buf = await _make_buffer(tmp_buffer_path)
    try:
        ikey = "settle:XJ20260424-JWT-401-001"
        await buf.enqueue(
            idempotency_key=ikey,
            tenant_id=XUJI_CHANGSHA_TENANT,
            store_id=XUJI_CHANGSHA_STORE,
            saga_id=generate_saga_id(),
            payload={"amount_fen": 18800},
        )

        # 第 1 轮：401（JWT 过期）
        # 第 2 轮：风暴窗口内不应 POST，calls 计数不增
        # 第 3 轮：刷新后 JWT 有效 → 200 sent
        http = _FakeHttpClient(
            [
                _FakeResponse(401, {"detail": "token_expired"}),
                _FakeResponse(200, {"ok": True}),  # 备用，第二轮不应被取
            ]
        )

        refresh_calls = {"count": 0}

        async def token_refresher() -> None:
            refresh_calls["count"] += 1

        flusher = SagaFlusher(
            buffer=buf,
            tenant_id=XUJI_CHANGSHA_TENANT,
            http_client=http,
            base_url="https://tx-trade.local",
            token_refresher=token_refresher,
            clock=clock,
        )

        # 轮 1：触发 401 路径
        result = await flusher.flush_once()
        assert result["sent"] == 0
        assert result["failed"] == 0
        assert result["dead_letter"] == 0
        assert result["jwt_expired_skip"] == 1, (
            f"401 必须计入 jwt_expired_skip，实际 result={result}"
        )

        # 状态机断言
        e = await buf.get(ikey, tenant_id=XUJI_CHANGSHA_TENANT)
        assert e is not None
        assert e.state == SagaBufferState.PENDING, (
            "401 后必须复位 pending（不能停留 flushing 否则下一轮永远死单）"
        )
        assert e.attempts == 0, (
            f"401 不增 attempts，实际 attempts={e.attempts}"
        )
        assert e.last_error is None, (
            "401 不写 last_error（不是业务失败，是凭证过期）"
        )

        # token_refresher 必须被调用一次
        assert refresh_calls["count"] == 1

        # 轮 2：仍在 30s 风暴窗口内，flusher 应跳过该 entry，不再 POST
        fake_now[0] += 5  # +5s，仍在 30s 内
        result2 = await flusher.flush_once()
        assert result2["jwt_expired_skip"] == 1, "风暴窗口内仍计 skip"
        assert len(http.calls) == 1, (
            f"30s 风暴窗口内不应再发 POST，实际 calls={len(http.calls)}"
        )

        # 轮 3：30s 窗口结束 + 模拟 JWT 已刷新 → 200 sent
        fake_now[0] += 30  # 累计 +35s 超过 backoff
        result3 = await flusher.flush_once()
        assert result3["sent"] == 1
        assert len(http.calls) == 2, (
            "30s 窗口外应重新 POST"
        )

        e_final = await buf.get(ikey, tenant_id=XUJI_CHANGSHA_TENANT)
        assert e_final is not None
        assert e_final.state == SagaBufferState.SENT
        # 全程 attempts 不增（凭证问题不消耗预算）
        assert e_final.attempts == 0, (
            f"成功 sent 时 attempts 仍应为 0，实际={e_final.attempts}"
        )
    finally:
        await buf.close()


# ─── 12. 403 业务拒绝仍入死信（Fix-8a 反向校验） ─────────────────────────────


@pytest.mark.asyncio
async def test_xujihaixian_flush_403_business_rejection_marks_dead_letter(
    tmp_buffer_path: Path,
):
    """徐记海鲜韶山店错配 RBAC：tx-trade 对 settle/retry 返回 403
    ROLE_FORBIDDEN（真业务拒绝，与 401 凭证过期是不同性质）。Fix-8a 必须
    保持现行行为：403 直接 dead_letter 等人工。"""
    from saga_buffer.flusher import SagaFlusher  # noqa: E402

    buf = await _make_buffer(tmp_buffer_path)
    try:
        ikey = "settle:XJ20260424-RBAC-403-001"
        await buf.enqueue(
            idempotency_key=ikey,
            tenant_id=XUJI_SHAOSHAN_TENANT,
            store_id=XUJI_SHAOSHAN_STORE,
            saga_id=generate_saga_id(),
            payload={"amount_fen": 9800},
        )

        http = _FakeHttpClient(
            [_FakeResponse(403, {"detail": "ROLE_FORBIDDEN"})]
        )
        flusher = SagaFlusher(
            buffer=buf,
            tenant_id=XUJI_SHAOSHAN_TENANT,
            http_client=http,
            base_url="https://tx-trade.local",
        )

        result = await flusher.flush_once()
        assert result["dead_letter"] == 1, (
            f"403 必须直接 dead_letter，实际 result={result}"
        )
        assert result["jwt_expired_skip"] == 0, (
            "403 不应被误判为 401 路径"
        )
        assert result["sent"] == 0
        assert result["failed"] == 0

        e = await buf.get(ikey, tenant_id=XUJI_SHAOSHAN_TENANT)
        assert e is not None
        assert e.state == SagaBufferState.DEAD_LETTER, (
            "403 业务拒绝必须 dead_letter（与 401 凭证过期分路）"
        )
        assert e.last_error is not None and "403" in e.last_error
    finally:
        await buf.close()


# ─── 13. memory→disk replay 成功（Fix-8b） ───────────────────────────────────


@pytest.mark.asyncio
async def test_xujihaixian_memory_mode_disk_recovery_replays_to_sqlite(
    tmp_buffer_path: Path,
):
    """徐记海鲜门店 Mac mini /var 满 → SagaBuffer 降级 memory；运维清理出
    空间后磁盘恢复可写。Fix-8b 铁律：

      1. SagaFlusher.heartbeat 调一次 try_replay_memory_to_disk
      2. 内存条目全部 INSERT 进 SQLite，状态/attempts/saga_id 不丢
      3. _memory_mode 复位为 False，stats.mode 回到 sqlite
      4. 重启进程后能从 SQLite 重建（验证持久化生效）
    """
    # 第 1 步：构造 memory_mode buffer（用不可写路径）
    unwritable_path = Path("/_readonly_root/saga_buffer.db")
    buf_mem = SagaBuffer(device_id=POS_DEVICE_A, db_path=unwritable_path)
    await buf_mem.initialize()
    assert buf_mem.is_memory_mode, "前置条件：必须先在 memory 模式"

    # 注入两条内存条目（模拟断网期间收银 2 单）
    ikey1 = "settle:XJ20260424-MEM-REPLAY-001"
    ikey2 = "settle:XJ20260424-MEM-REPLAY-002"
    await buf_mem.enqueue(
        idempotency_key=ikey1,
        tenant_id=XUJI_CHANGSHA_TENANT,
        store_id=XUJI_CHANGSHA_STORE,
        saga_id=generate_saga_id(),
        payload={"amount_fen": 12300, "order_no": "MEM-001"},
    )
    saga2 = generate_saga_id()
    await buf_mem.enqueue(
        idempotency_key=ikey2,
        tenant_id=XUJI_CHANGSHA_TENANT,
        store_id=XUJI_CHANGSHA_STORE,
        saga_id=saga2,
        payload={"amount_fen": 6800, "order_no": "MEM-002"},
    )

    # 第 2 步：把 db_path 切换到可写路径（模拟运维清理磁盘后）
    buf_mem._db_path = tmp_buffer_path

    # 第 3 步：触发 replay
    replayed = await buf_mem.try_replay_memory_to_disk()
    assert replayed == 2, f"应 replay 2 条，实际 {replayed}"
    assert buf_mem.is_memory_mode is False, (
        "replay 成功后必须退出 memory 模式"
    )
    assert buf_mem._memory_rows == {}, "内存字典必须清空"

    # 第 4 步：当前 buf 仍可读到这两条（已切到 sqlite 模式）
    stats = await buf_mem.stats(tenant_id=XUJI_CHANGSHA_TENANT)
    assert stats.mode == "sqlite"
    assert stats.pending_count == 2

    e1 = await buf_mem.get(ikey1, tenant_id=XUJI_CHANGSHA_TENANT)
    assert e1 is not None
    assert e1.state == SagaBufferState.PENDING
    assert e1.payload["order_no"] == "MEM-001"

    e2 = await buf_mem.get(ikey2, tenant_id=XUJI_CHANGSHA_TENANT)
    assert e2 is not None
    assert e2.saga_id == saga2, "saga_id 必须保留（防双扣费铁律）"

    await buf_mem.close()

    # 第 5 步：模拟进程重启 → 重新打开同一 SQLite 文件，数据仍在
    buf_restart = SagaBuffer(device_id=POS_DEVICE_A, db_path=tmp_buffer_path)
    await buf_restart.initialize()
    try:
        assert buf_restart.is_memory_mode is False
        ready = await buf_restart.flush_ready(
            tenant_id=XUJI_CHANGSHA_TENANT, limit=10
        )
        keys = sorted(e.idempotency_key for e in ready)
        assert keys == [ikey1, ikey2], (
            f"重启后必须能从 SQLite 取回两条 replay 数据（防数据丢失），"
            f"实际 keys={keys}"
        )
    finally:
        await buf_restart.close()


# ─── 14. memory→disk replay 失败（仍 memory）（Fix-8b 失败路径） ─────────────


@pytest.mark.asyncio
async def test_xujihaixian_memory_mode_disk_still_full_stays_in_memory():
    """徐记海鲜门店磁盘仍满 → try_replay_memory_to_disk 必须探测失败，
    返回 0，保持 memory 模式（warning 日志，不抛异常，不删数据）。"""
    unwritable_path = Path("/_readonly_root/saga_buffer.db")
    buf = SagaBuffer(device_id=POS_DEVICE_A, db_path=unwritable_path)
    await buf.initialize()
    try:
        assert buf.is_memory_mode

        ikey = "settle:XJ20260424-MEM-STILL-FULL-001"
        await buf.enqueue(
            idempotency_key=ikey,
            tenant_id=XUJI_CHANGSHA_TENANT,
            store_id=XUJI_CHANGSHA_STORE,
            saga_id=generate_saga_id(),
            payload={"amount_fen": 8800},
        )

        # 磁盘仍不可写：replay 必须返回 0 + 保持 memory 模式
        replayed = await buf.try_replay_memory_to_disk()
        assert replayed == 0, (
            f"磁盘仍不可写时 replay 必须 0 命中，实际 {replayed}"
        )
        assert buf.is_memory_mode is True, (
            "replay 失败后必须保持 memory 模式（绝不能丢数据）"
        )

        # 数据仍然在内存里，可继续 flush_ready
        ready = await buf.flush_ready(tenant_id=XUJI_CHANGSHA_TENANT)
        assert len(ready) == 1
        assert ready[0].idempotency_key == ikey

        # stats 仍报 memory mode（运维监控据此判断需扩盘）
        stats = await buf.stats(tenant_id=XUJI_CHANGSHA_TENANT)
        assert stats.mode == "memory"
        assert stats.pending_count == 1
    finally:
        await buf.close()
