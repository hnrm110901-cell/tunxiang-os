"""test_offline_sync_crdt.py — Tier 1 CRDT (LWW-Register) 测试套件

覆盖（基于真实餐厅场景）：
  1. 断网 4 小时零数据丢失（Week 8 DEMO 验收门槛）
  2. 两端同时改桌台状态 → LWW 正确解决
  3. 离线订单按下单时序回放
  4. 时间戳完全相同时用节点 ID 决胜（确定性 tie-breaker）
  5. 增量同步 token 推进正确

铁律：所有金额单位为「分」（整数），不允许浮点。

运行：
  pytest edge/sync-engine/tests/test_offline_sync_crdt.py -v
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, SRC_DIR)

from lww_register import (  # noqa: E402
    LWWRegister,
    LWWValue,
    NodeClock,
    OfflineQueueReplay,
    SyncToken,
    replay_offline_events,
    resolve_lww,
)


# ─── 工具：生成稳定时间戳 ─────────────────────────────────────────────────


def _ts(seconds_offset: int = 0, micros: int = 0) -> datetime:
    """相对一个固定锚点的时间戳，避免测试受系统时钟漂移影响"""
    base = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=seconds_offset, microseconds=micros)


# ═════════════════════════════════════════════════════════════════════════
# 1. test_concurrent_table_status_lww — 两端同时改桌台状态
# ═════════════════════════════════════════════════════════════════════════


class TestConcurrentTableStatusLWW:
    """场景：徐记海鲜旗舰店，POS-A（前台收银）和 POS-B（领位）
    几乎同时把 12 号桌从 'occupied' 改成不同状态。LWW 必须给出确定的赢家。"""

    def test_later_timestamp_wins(self):
        """收银 12:00:00.100 改成 'available'，领位 12:00:00.300 改成 'reserved'
        → 后写入者赢（reserved）"""
        v_a = LWWValue(value="available", timestamp=_ts(0, 100_000), node_id="pos-A")
        v_b = LWWValue(value="reserved", timestamp=_ts(0, 300_000), node_id="pos-B")

        winner = resolve_lww(v_a, v_b)
        assert winner.value == "reserved"
        assert winner.node_id == "pos-B"

    def test_unordered_input_same_result(self):
        """LWW 必须满足交换律：resolve(a,b) == resolve(b,a)"""
        v_a = LWWValue(value="available", timestamp=_ts(0, 100_000), node_id="pos-A")
        v_b = LWWValue(value="reserved", timestamp=_ts(0, 300_000), node_id="pos-B")

        assert resolve_lww(v_a, v_b).value == resolve_lww(v_b, v_a).value

    def test_three_way_concurrent_table_status(self):
        """三个终端（前台/领位/服务员）同时操作 12 号桌 → 时间戳最新者赢"""
        v_a = LWWValue(value="available", timestamp=_ts(0, 100_000), node_id="pos-A")
        v_b = LWWValue(value="reserved", timestamp=_ts(0, 200_000), node_id="pos-B")
        v_c = LWWValue(value="occupied", timestamp=_ts(0, 500_000), node_id="crew-C")

        # 满足结合律
        result_1 = resolve_lww(resolve_lww(v_a, v_b), v_c)
        result_2 = resolve_lww(v_a, resolve_lww(v_b, v_c))
        assert result_1.value == result_2.value == "occupied"


# ═════════════════════════════════════════════════════════════════════════
# 2. test_lww_tie_breaker_by_node_id — 时间戳相同时用节点 ID 决胜
# ═════════════════════════════════════════════════════════════════════════


class TestLWWTieBreakerByNodeID:
    """场景：两台 POS NTP 同步极好，物理时间戳到微秒都相同。
    必须有确定性 tie-breaker，否则不同节点解析结果不一致 → CRDT 不收敛。"""

    def test_same_timestamp_higher_node_id_wins(self):
        """两个节点同微秒写入，按 node_id 字典序较大者赢（确定性）"""
        ts = _ts(0, 500_000)
        v_a = LWWValue(value="status_x", timestamp=ts, node_id="pos-A")
        v_b = LWWValue(value="status_y", timestamp=ts, node_id="pos-B")

        winner = resolve_lww(v_a, v_b)
        # pos-B > pos-A 字典序
        assert winner.node_id == "pos-B"
        assert winner.value == "status_y"

    def test_tie_breaker_is_deterministic_across_calls(self):
        """同样输入多次调用结果必须一致"""
        ts = _ts(0, 500_000)
        v_a = LWWValue(value="x", timestamp=ts, node_id="pos-A")
        v_b = LWWValue(value="y", timestamp=ts, node_id="pos-B")

        results = {resolve_lww(v_a, v_b).value for _ in range(100)}
        assert len(results) == 1, "tie-breaker 必须确定，不能有抖动"

    def test_same_node_id_same_timestamp_same_value_no_conflict(self):
        """完全相同的写入（幂等场景）— 任意一方都可"""
        ts = _ts(0, 500_000)
        v_a = LWWValue(value="ok", timestamp=ts, node_id="pos-A")
        v_b = LWWValue(value="ok", timestamp=ts, node_id="pos-A")

        winner = resolve_lww(v_a, v_b)
        assert winner.value == "ok"


# ═════════════════════════════════════════════════════════════════════════
# 3. test_offline_order_queue_replay_in_order — 离线订单按下单时序回放
# ═════════════════════════════════════════════════════════════════════════


class TestOfflineOrderQueueReplayInOrder:
    """场景：徐记海鲜某店中午 12:00 断网，POS 离线写入 5 单：
    12:01 下单 → 12:02 加菜 → 12:05 改折扣 → 12:08 支付 → 12:10 关单
    16:00 网络恢复，必须按这个时序回放，否则金额可能错乱。"""

    def test_events_replayed_in_chronological_order(self):
        """乱序输入必须按 client_ts 升序回放"""
        events = [
            {"event_id": "e3", "client_ts": _ts(300), "type": "DISCOUNT_APPLIED",
             "payload": {"discount_fen": 5_000}, "node_id": "pos-A"},
            {"event_id": "e1", "client_ts": _ts(60), "type": "ORDER_CREATED",
             "payload": {"total_fen": 28_800}, "node_id": "pos-A"},
            {"event_id": "e5", "client_ts": _ts(600), "type": "ORDER_CLOSED",
             "payload": {}, "node_id": "pos-A"},
            {"event_id": "e2", "client_ts": _ts(120), "type": "ITEM_ADDED",
             "payload": {"item_fen": 6_800}, "node_id": "pos-A"},
            {"event_id": "e4", "client_ts": _ts(480), "type": "PAYMENT_CONFIRMED",
             "payload": {"paid_fen": 30_600}, "node_id": "pos-A"},
        ]

        replayed = replay_offline_events(events)

        order = [e["event_id"] for e in replayed]
        assert order == ["e1", "e2", "e3", "e4", "e5"], (
            f"必须按时序回放，实际：{order}"
        )

    def test_replay_amounts_in_fen_no_float(self):
        """回放后所有金额字段保持 int（分），禁止浮点"""
        events = [
            {"event_id": "p1", "client_ts": _ts(60), "type": "PAYMENT_CONFIRMED",
             "payload": {"paid_fen": 12_345}, "node_id": "pos-A"},
        ]
        replayed = replay_offline_events(events)
        assert isinstance(replayed[0]["payload"]["paid_fen"], int)

    def test_replay_uses_node_id_tie_breaker_for_same_ts(self):
        """同时间戳事件按 node_id 决定顺序（确定性回放）"""
        ts = _ts(60)
        events = [
            {"event_id": "e_b", "client_ts": ts, "type": "X",
             "payload": {}, "node_id": "pos-B"},
            {"event_id": "e_a", "client_ts": ts, "type": "X",
             "payload": {}, "node_id": "pos-A"},
        ]
        replayed = replay_offline_events(events)
        # 同 ts 时 node_id 字典序小的先回放（业务确定性）
        assert [e["node_id"] for e in replayed] == ["pos-A", "pos-B"]

    def test_replay_drops_duplicates_by_event_id(self):
        """同一 event_id 重复（网络重传）只回放一次（幂等）"""
        events = [
            {"event_id": "e1", "client_ts": _ts(60), "type": "X",
             "payload": {"v": 1}, "node_id": "pos-A"},
            {"event_id": "e1", "client_ts": _ts(60), "type": "X",
             "payload": {"v": 1}, "node_id": "pos-A"},
            {"event_id": "e2", "client_ts": _ts(120), "type": "Y",
             "payload": {"v": 2}, "node_id": "pos-A"},
        ]
        replayed = replay_offline_events(events)
        assert len(replayed) == 2
        assert {e["event_id"] for e in replayed} == {"e1", "e2"}


# ═════════════════════════════════════════════════════════════════════════
# 4. test_offline_4h_crdt_no_data_loss — 断网 4 小时重连零丢失
# ═════════════════════════════════════════════════════════════════════════


class TestOffline4HCRDTNoDataLoss:
    """Week 8 DEMO 验收门槛：断网 4 小时无数据丢失。
    场景：周日中午 12:00 城市光纤抢修，徐记某店离线 4h，期间 200 单。
    16:00 恢复连接，全部回放上云，零订单丢失。"""

    def test_4h_offline_200_orders_all_replayed(self):
        """4 小时离线缓冲 200 单（约徐记海鲜旗舰店午餐峰值），重连后全部回放"""
        offline_start = _ts(0)
        # 4 小时 = 14400 秒，200 单平均每 72 秒一单
        events = []
        for i in range(200):
            events.append({
                "event_id": f"order-{i:04d}",
                "client_ts": offline_start + timedelta(seconds=i * 72),
                "type": "ORDER_CREATED",
                "payload": {"total_fen": 28_800 + i * 100, "table_no": (i % 50) + 1},
                "node_id": "pos-flagship",
            })

        replayed = replay_offline_events(events)

        assert len(replayed) == 200, "200 单必须 0 丢失"
        # 时序严格递增
        for prev, curr in zip(replayed, replayed[1:]):
            assert prev["client_ts"] <= curr["client_ts"], "回放必须时序严格递增"
        # 金额都是 int
        for e in replayed:
            assert isinstance(e["payload"]["total_fen"], int)

    def test_4h_offline_with_lww_field_resolution(self):
        """4 小时离线期间，桌台状态被 POS 改了 30 次，重连时云端也改过 1 次。
        最终结果由时间戳 + node_id 决定，结果必须可预测。"""
        register: LWWRegister[str] = LWWRegister()
        offline_start = _ts(0)

        # 离线期间 POS 写入 30 次
        for i in range(30):
            register.set(
                value=f"local_status_{i}",
                timestamp=offline_start + timedelta(seconds=i * 60),
                node_id="pos-A",
            )

        # 云端在重连前 1 秒写入
        cloud_ts = offline_start + timedelta(hours=4) - timedelta(seconds=1)
        register.set(value="cloud_status_X", timestamp=cloud_ts, node_id="cloud")

        # 云端写入更晚 → 应当胜出
        assert register.value == "cloud_status_X"
        assert register.node_id == "cloud"

    def test_4h_offline_pos_late_write_beats_cloud(self):
        """对称场景：云端先写，POS 4h 内最后一次写入时间戳更晚 → POS 赢"""
        register: LWWRegister[str] = LWWRegister()

        # 云端先写
        register.set(value="cloud_x", timestamp=_ts(60), node_id="cloud")
        # POS 离线期间最后一次写（4h 内更晚的时间戳）
        register.set(
            value="pos_final",
            timestamp=_ts(60) + timedelta(hours=3, minutes=59),
            node_id="pos-A",
        )

        assert register.value == "pos_final"


# ═════════════════════════════════════════════════════════════════════════
# 5. test_incremental_sync_with_token — 增量 token 推进正确
# ═════════════════════════════════════════════════════════════════════════


class TestIncrementalSyncWithToken:
    """场景：sync-engine 每 300 秒轮询拉取增量。
    last_sync_token 必须只在确认所有数据已落地后才推进，
    否则中间崩溃会丢数据。"""

    def test_token_advances_to_max_seen_ts(self):
        """token 推进到本批数据的最大时间戳"""
        token = SyncToken.initial()
        assert token.last_seen_ts == datetime(1970, 1, 1, tzinfo=timezone.utc)
        assert token.last_seen_seq == 0

        events = [
            {"client_ts": _ts(60), "seq": 1},
            {"client_ts": _ts(120), "seq": 2},
            {"client_ts": _ts(90), "seq": 3},
        ]

        new_token = token.advance(events)
        assert new_token.last_seen_ts == _ts(120)
        assert new_token.last_seen_seq == 3  # max(seq)

    def test_token_does_not_regress(self):
        """新 token 必须 >= 旧 token，禁止回退（否则会重复拉取或丢失）"""
        token = SyncToken(last_seen_ts=_ts(1000), last_seen_seq=100)
        # 给一批更早的事件，token 不应回退
        new_token = token.advance([{"client_ts": _ts(60), "seq": 1}])
        assert new_token.last_seen_ts >= token.last_seen_ts
        assert new_token.last_seen_seq >= token.last_seen_seq

    def test_token_serialization_roundtrip(self):
        """token 必须可序列化成字符串持久化（崩溃恢复）"""
        token = SyncToken(last_seen_ts=_ts(120), last_seen_seq=42)
        serialized = token.to_string()
        assert isinstance(serialized, str)
        recovered = SyncToken.from_string(serialized)
        assert recovered.last_seen_ts == token.last_seen_ts
        assert recovered.last_seen_seq == token.last_seen_seq

    def test_empty_batch_does_not_advance_token(self):
        """空批次（无新数据）不推进 token"""
        token = SyncToken(last_seen_ts=_ts(1000), last_seen_seq=100)
        new_token = token.advance([])
        assert new_token.last_seen_ts == token.last_seen_ts
        assert new_token.last_seen_seq == token.last_seen_seq

    def test_token_filter_already_seen(self):
        """基于 token 过滤：只保留 client_ts > last_seen_ts 或 (相等且 seq > last_seen_seq) 的事件"""
        token = SyncToken(last_seen_ts=_ts(120), last_seen_seq=2)
        events = [
            {"client_ts": _ts(60), "seq": 1},  # 旧，过滤
            {"client_ts": _ts(120), "seq": 2},  # 等于 watermark，过滤（已见）
            {"client_ts": _ts(120), "seq": 3},  # 同 ts 但 seq 更大，保留
            {"client_ts": _ts(200), "seq": 4},  # 新，保留
        ]
        filtered = token.filter_unseen(events)
        assert [e["seq"] for e in filtered] == [3, 4]


# ═════════════════════════════════════════════════════════════════════════
# 6. NodeClock — 混合时钟（防止系统时钟回退导致旧值复活）
# ═════════════════════════════════════════════════════════════════════════


class TestNodeClock:
    """系统时钟可能回退（NTP 校正、夏令时），混合时钟保证单调递增"""

    def test_clock_monotonic_even_when_wall_clock_regresses(self):
        """墙钟回退时，逻辑时钟必须仍然递增"""
        clock = NodeClock(node_id="pos-A")
        ts1 = clock.now(wall_clock=_ts(100))
        ts2 = clock.now(wall_clock=_ts(50))  # 墙钟回退！
        assert ts2 > ts1, "时钟必须严格递增"

    def test_clock_advances_with_wall_clock_when_forward(self):
        """墙钟前进时，逻辑时钟跟随"""
        clock = NodeClock(node_id="pos-A")
        ts1 = clock.now(wall_clock=_ts(100))
        ts2 = clock.now(wall_clock=_ts(200))
        assert ts2 > ts1


# ═════════════════════════════════════════════════════════════════════════
# 7. OfflineQueueReplay — 与 OfflineSyncService 集成场景（确定性）
# ═════════════════════════════════════════════════════════════════════════


class TestOfflineQueueReplayWithLWWConflict:
    """场景：重连后回放本地订单，遇到云端已存在同 stream_id 的事件 → LWW 决策"""

    def test_local_event_wins_when_later(self):
        """本地事件时间戳更晚 → 本地版本应用"""
        replay = OfflineQueueReplay()
        # 云端已存在
        replay.upsert_remote(
            stream_id="order-99",
            field="status",
            value="open",
            timestamp=_ts(60),
            node_id="cloud",
        )
        # 本地稍后写
        result = replay.apply_local(
            stream_id="order-99",
            field="status",
            value="paid",
            timestamp=_ts(120),
            node_id="pos-A",
        )
        assert result.applied is True
        assert result.winner_value == "paid"
        assert result.winner_node_id == "pos-A"

    def test_local_event_loses_when_earlier(self):
        """本地事件时间戳更早 → 云端胜出，本地不覆盖"""
        replay = OfflineQueueReplay()
        replay.upsert_remote(
            stream_id="order-99",
            field="status",
            value="paid",
            timestamp=_ts(120),
            node_id="cloud",
        )
        result = replay.apply_local(
            stream_id="order-99",
            field="status",
            value="open",
            timestamp=_ts(60),
            node_id="pos-A",
        )
        assert result.applied is False
        assert result.winner_value == "paid"

    def test_two_local_writes_use_lww(self):
        """同一 stream_id 两次本地写：晚的胜出"""
        replay = OfflineQueueReplay()
        r1 = replay.apply_local(
            stream_id="order-1", field="amount_fen",
            value=10_000, timestamp=_ts(60), node_id="pos-A",
        )
        r2 = replay.apply_local(
            stream_id="order-1", field="amount_fen",
            value=12_000, timestamp=_ts(120), node_id="pos-A",
        )
        assert r1.applied is True
        assert r2.applied is True
        assert replay.get_value("order-1", "amount_fen") == 12_000
