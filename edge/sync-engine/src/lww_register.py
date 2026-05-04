"""lww_register.py — CRDT (LWW-Register) 冲突解决核心算法

[Tier 1 — 零容忍模块]

为什么需要 LWW（Last-Write-Wins Register）：
  屯象OS 的边缘架构（路线C）下，门店 Mac mini 与云端 PG 通过 sync-engine
  增量同步，且离线 4 小时内允许 POS 继续作业。当多端（前台 POS / 领位 / 服务员
  PWA / 云端 BO）同时修改同一记录的同一字段（最典型：12 号桌的 status）时，
  必须有一个**确定性**的合并算法，否则 CRDT 不收敛 → 不同节点看到不同状态 →
  出餐错乱、双开台、对账不平。

LWW-Register 算法：
  - 每个写入携带 (value, timestamp, node_id)
  - 合并时选择 timestamp 最大者
  - timestamp 相同时按 node_id 字典序较大者胜出（确定性 tie-breaker）
  - timestamp + node_id + value 都相同 → 视为同一次写入（幂等）

为什么 node_id 必须是 tie-breaker：
  NTP 同步极佳的两台 POS 可能在同一微秒内写入。没有 tie-breaker 时，
  resolve_lww(a,b) 与 resolve_lww(b,a) 可能给出不同结果，CRDT 不满足
  交换律 → 不收敛。

混合时钟（NodeClock）：
  系统墙钟可能因 NTP 校正、夏令时回退。NodeClock 在墙钟回退时仍保证
  逻辑时钟严格递增（last_ts + 1μs），防止旧值"复活"覆盖新值。

涵盖字段（CRDT-managed）：
  - 桌台 status（available/reserved/occupied/cleaning）
  - 订单 status（open/paid/cancelled/refunded）
  - 库存 quantity（按时间戳取最新快照，事件流仍走 CRDT-counter，此处仅状态字段）

不适用场景（仍走 server_wins）：
  - 涉及金额计算的累加值（用 OR-Set/PN-Counter）
  - 涉及顺序的列表（用 RGA/Logoot）
  本模块仅处理"末次写入即真相"的标量字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Generic, Iterable, Optional, TypeVar

import structlog

logger = structlog.get_logger()

T = TypeVar("T")


# ─── LWW-Register 核心 ────────────────────────────────────────────────────


@dataclass(frozen=True)
class LWWValue(Generic[T]):
    """单次写入的 LWW 值

    Attributes:
        value:     业务值（任意可序列化类型）
        timestamp: 写入时刻（UTC，必须带 tzinfo）
        node_id:   节点标识（POS 设备 ID / 'cloud' / 'crew-xxx'）
    """

    value: T
    timestamp: datetime
    node_id: str

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("LWWValue.timestamp 必须带 tzinfo（UTC）")
        if not self.node_id:
            raise ValueError("LWWValue.node_id 不可为空（CRDT 无法 tie-break）")


def resolve_lww(a: LWWValue[T], b: LWWValue[T]) -> LWWValue[T]:
    """LWW-Register 合并：返回胜出的那一方

    决策顺序（必须是确定性的）：
      1. timestamp 较大者胜
      2. timestamp 相同时，node_id 字典序较大者胜
      3. 完全相同 → 任意一方（幂等）

    满足：
      - 交换律：resolve_lww(a, b) == resolve_lww(b, a)
      - 结合律：resolve_lww(resolve_lww(a, b), c) == resolve_lww(a, resolve_lww(b, c))
      - 幂等性：resolve_lww(a, a) == a
    """
    if a.timestamp > b.timestamp:
        return a
    if a.timestamp < b.timestamp:
        return b
    # 时间戳完全相同 → 用 node_id 字典序决胜（较大者胜）
    if a.node_id > b.node_id:
        return a
    if a.node_id < b.node_id:
        return b
    # node_id 相同 → 幂等场景，任意返回
    return a


class LWWRegister(Generic[T]):
    """LWW-Register CRDT 容器

    用法：
        reg: LWWRegister[str] = LWWRegister()
        reg.set("available", ts=..., node_id="pos-A")
        reg.set("reserved",  ts=..., node_id="pos-B")
        print(reg.value)   # 由 LWW 决定
    """

    def __init__(self) -> None:
        self._current: Optional[LWWValue[T]] = None

    def set(self, value: T, timestamp: datetime, node_id: str) -> LWWValue[T]:
        """写入一个新值，返回当前胜出的 LWWValue"""
        new = LWWValue(value=value, timestamp=timestamp, node_id=node_id)
        if self._current is None:
            self._current = new
        else:
            self._current = resolve_lww(self._current, new)
        return self._current

    @property
    def value(self) -> Optional[T]:
        return self._current.value if self._current else None

    @property
    def timestamp(self) -> Optional[datetime]:
        return self._current.timestamp if self._current else None

    @property
    def node_id(self) -> Optional[str]:
        return self._current.node_id if self._current else None


# ─── 混合逻辑时钟（防止墙钟回退） ─────────────────────────────────────────


@dataclass
class NodeClock:
    """混合时钟：保证 now() 单调递增，即使系统墙钟回退

    NTP 校正、夏令时切换、运维误操作都会让 datetime.now() 回退。
    LWW 在时钟回退时会被欺骗（旧值时间戳更大 → 覆盖新值）。
    用 NodeClock 包装：last_ts + 1μs 保底。
    """

    node_id: str
    _last_ts: Optional[datetime] = None

    def now(self, wall_clock: Optional[datetime] = None) -> datetime:
        """返回严格递增的 timestamp（带 tzinfo）"""
        wc = wall_clock if wall_clock is not None else datetime.now(timezone.utc)
        if wc.tzinfo is None:
            wc = wc.replace(tzinfo=timezone.utc)
        if self._last_ts is None or wc > self._last_ts:
            self._last_ts = wc
        else:
            # 墙钟回退：在上一次时间戳基础上 +1 微秒
            self._last_ts = self._last_ts + timedelta(microseconds=1)
        return self._last_ts


# ─── 离线事件回放（按时序、幂等、确定性） ─────────────────────────────────


def replay_offline_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将离线缓冲的事件按时序排序后回放

    输入事件结构（必须字段）：
        {
            "event_id":  str,           # 全局唯一（用于幂等去重）
            "client_ts": datetime,      # 写入时刻（带 tzinfo）
            "type":      str,           # 事件类型（ORDER_CREATED 等）
            "payload":   dict,          # 业务负载（金额一律分/int）
            "node_id":   str,           # 写入节点
        }

    回放规则：
      1. 按 event_id 去重（同一事件重传只回放一次 — 幂等）
      2. 按 (client_ts, node_id, event_id) 排序（确定性）
      3. 不变换 payload（金额保持 int）

    返回：按时序排序后的事件列表
    """
    # 幂等去重：保留首次出现
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for evt in events:
        eid = evt.get("event_id")
        if not eid:
            logger.warning("replay_offline_events.missing_event_id", evt=evt)
            continue
        if eid in seen:
            continue
        seen.add(eid)
        deduped.append(evt)

    # 确定性排序：(client_ts, node_id, event_id) 三键
    def _sort_key(e: dict[str, Any]) -> tuple[datetime, str, str]:
        ts = e["client_ts"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (ts, e.get("node_id", ""), e.get("event_id", ""))

    deduped.sort(key=_sort_key)
    return deduped


# ─── 增量同步 Token ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class SyncToken:
    """增量同步游标

    设计原因：
      用 (last_seen_ts, last_seen_seq) 双键代替单纯时间戳，避免同一秒内多事件
      被遗漏。seq 由云端事件存储分配（v147+ events 表的 seq 字段）。

    持久化：
      to_string() / from_string() 用于保存到 sync_checkpoints 表，崩溃恢复
      后从持久化的 token 续传。

    禁止回退：
      advance() 只前进、不后退，防止重复拉取或丢失数据。
    """

    last_seen_ts: datetime
    last_seen_seq: int

    @classmethod
    def initial(cls) -> "SyncToken":
        """首次拉取：epoch 起点"""
        return cls(
            last_seen_ts=datetime(1970, 1, 1, tzinfo=timezone.utc),
            last_seen_seq=0,
        )

    def advance(self, events: Iterable[dict[str, Any]]) -> "SyncToken":
        """根据本批事件推进 token（取 max(ts) 与 max(seq)）"""
        evts = list(events)
        if not evts:
            return self

        max_ts = self.last_seen_ts
        max_seq = self.last_seen_seq
        for e in evts:
            ts = e.get("client_ts") or e.get("ts")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if ts is not None:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts > max_ts:
                    max_ts = ts
            seq_val = int(e.get("seq", 0))
            if seq_val > max_seq:
                max_seq = seq_val

        # 防回退：取 max
        return SyncToken(
            last_seen_ts=max(max_ts, self.last_seen_ts),
            last_seen_seq=max(max_seq, self.last_seen_seq),
        )

    def filter_unseen(self, events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """过滤出 token 之后的事件（增量）

        规则：保留 (client_ts > last_seen_ts) 或 (相等且 seq > last_seen_seq) 的事件
        """
        result: list[dict[str, Any]] = []
        for e in events:
            ts = e.get("client_ts") or e.get("ts")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            seq_val = int(e.get("seq", 0))

            if ts is None:
                continue
            if ts > self.last_seen_ts:
                result.append(e)
            elif ts == self.last_seen_ts and seq_val > self.last_seen_seq:
                result.append(e)
        return result

    def to_string(self) -> str:
        """序列化为字符串（用于持久化）"""
        return f"{self.last_seen_ts.isoformat()}|{self.last_seen_seq}"

    @classmethod
    def from_string(cls, s: str) -> "SyncToken":
        """从字符串恢复"""
        if not s or "|" not in s:
            return cls.initial()
        ts_str, seq_str = s.split("|", 1)
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return cls(last_seen_ts=ts, last_seen_seq=int(seq_str))


# ─── 离线队列回放器（与 OfflineSyncService 集成的工具类） ──────────────────


@dataclass
class ReplayResult:
    """单次回放的结果（用于审计与日志）"""

    applied: bool
    winner_value: Any
    winner_node_id: str
    reason: str = ""


class OfflineQueueReplay:
    """离线队列回放器：将本地缓冲事件按 LWW 与云端合并

    用法：
        replay = OfflineQueueReplay()
        # 1. 拉取云端最新值预填
        replay.upsert_remote(stream_id, field, value, ts, node_id)
        # 2. 应用本地离线事件
        result = replay.apply_local(stream_id, field, value, ts, node_id)
        if result.applied:
            # 推送到云端
            ...
    """

    def __init__(self) -> None:
        # (stream_id, field) -> LWWValue
        self._state: dict[tuple[str, str], LWWValue[Any]] = {}

    def upsert_remote(
        self,
        stream_id: str,
        field: str,
        value: Any,
        timestamp: datetime,
        node_id: str,
    ) -> ReplayResult:
        """预填云端值（pull 阶段）"""
        key = (stream_id, field)
        new = LWWValue(value=value, timestamp=timestamp, node_id=node_id)
        existing = self._state.get(key)
        if existing is None:
            self._state[key] = new
            return ReplayResult(applied=True, winner_value=value, winner_node_id=node_id, reason="initial")
        winner = resolve_lww(existing, new)
        self._state[key] = winner
        applied = winner is new
        return ReplayResult(
            applied=applied,
            winner_value=winner.value,
            winner_node_id=winner.node_id,
            reason="remote_lww",
        )

    def apply_local(
        self,
        stream_id: str,
        field: str,
        value: Any,
        timestamp: datetime,
        node_id: str,
    ) -> ReplayResult:
        """应用本地离线事件（replay 阶段）"""
        key = (stream_id, field)
        new = LWWValue(value=value, timestamp=timestamp, node_id=node_id)
        existing = self._state.get(key)
        if existing is None:
            self._state[key] = new
            logger.info(
                "offline_replay.applied_initial",
                stream_id=stream_id, field=field, node_id=node_id,
            )
            return ReplayResult(applied=True, winner_value=value, winner_node_id=node_id, reason="initial")

        winner = resolve_lww(existing, new)
        self._state[key] = winner
        applied = winner.timestamp == new.timestamp and winner.node_id == new.node_id and winner.value == new.value
        if not applied:
            logger.info(
                "offline_replay.local_lost_to_remote",
                stream_id=stream_id, field=field,
                local_ts=timestamp.isoformat(), remote_ts=existing.timestamp.isoformat(),
                winner_node=winner.node_id,
            )
        return ReplayResult(
            applied=applied,
            winner_value=winner.value,
            winner_node_id=winner.node_id,
            reason="lww",
        )

    def get_value(self, stream_id: str, field: str) -> Any:
        key = (stream_id, field)
        v = self._state.get(key)
        return v.value if v else None

    def snapshot(self) -> dict[tuple[str, str], LWWValue[Any]]:
        """返回当前状态快照（只读副本）"""
        return dict(self._state)
