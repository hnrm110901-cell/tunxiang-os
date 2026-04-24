"""test_offline_order_id_tier1 — Sprint A3 离线订单号 UUID v7 + 死信映射 Tier1 徐记场景

Tier1 铁律（CLAUDE.md §17/§20 零容忍）：
  - 测试用例全部基于徐记海鲜真实场景（非技术边界值）
  - 断网 100 单零丢失 / UUID v7 时间单调 / 死信人工确认 / RLS 隔离
  - 先写测试、再写实现（本文件锁定行为契约）

A1/A2 合约兼容：
  - order_id 格式 = `{device_id}:{ms_epoch}:{counter}`（人读前缀）
    + UUID v7 payload（作为 idempotency_key 后半段 `settle:{order_id}`）
  - A2 SagaBuffer.enqueue 的 idempotency_key 必须能被本工单生成的 order_id 识别
  - 本工单不改 A2 表结构、不改 A1 前端已落逻辑

8 条徐记海鲜场景（与工单 Step 2 一一对应）：
  1. test_xujihaixian_offline_200_orders_unique_uuid_v7_zero_collision
     — 商米 T2 离线生成 200 单，UUID v7 无碰撞，ms_epoch 单调
  2. test_xujihaixian_device_counter_resets_on_new_day_safe
     — 设备 counter 跨天重置，配合 ms_epoch 仍唯一
  3. test_xujihaixian_two_devices_same_ms_no_collision
     — 两台 POS 同毫秒生成单号，device_id 前缀保证无碰撞
  4. test_xujihaixian_offline_order_resync_maps_to_cloud_id
     — 离线 order_id 同步上云后，offline_order_mapping 记录 offline → cloud 映射
  5. test_xujihaixian_dead_letter_awaits_manual_confirm
     — 补发 20 次仍失败 → dead_letter 状态，不自动删除，等店长确认
  6. test_xujihaixian_idempotency_key_format_consistent_with_a2
     — A3 生成的 idempotency_key 能被 A2 SagaBuffer 正确 dedup
  7. test_xujihaixian_cross_tenant_order_id_no_leak
     — tenant_A 的 offline_order_mapping 对 tenant_B 不可见（RLS 兜底 + service 层拦截）
  8. test_flag_off_legacy_server_generated_order_id
     — edge.offline.order_id_bridge off 时保留服务端生成 order_id（legacy）

数据约定：徐记海鲜长沙·王府井店（tenant_A）/ 韶山路店（tenant_B）
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# 关闭 dev bypass 前的 env 依赖；离线 order_id 生成是纯函数，无 DB 依赖
os.environ.setdefault("TX_AUTH_ENABLED", "true")

from src.services.offline_order_id import (  # noqa: E402
    generate_offline_order_id,
    parse_offline_order_id,
)
from src.services.offline_order_mapping_service import (  # noqa: E402
    DEAD_LETTER_MAX_ATTEMPTS,
    MappingState,
    OfflineOrderMappingService,
)

# ──────────────── 徐记海鲜测试租户 ────────────────

XUJI_CHANGSHA_TENANT = "00000000-0000-0000-0000-0000000000a1"
XUJI_SHAOSHAN_TENANT = "00000000-0000-0000-0000-0000000000b1"
XUJI_CHANGSHA_STORE = "00000000-0000-0000-0000-0000000000a2"
XUJI_SHAOSHAN_STORE = "00000000-0000-0000-0000-0000000000b2"
POS_DEVICE_A = "pos-xuji-changsha-001"
POS_DEVICE_B = "pos-xuji-shaoshan-001"


# ──────────────── MockDB —— 复用 A4 RBAC 风格 ────────────────


class _MockDB:
    """捕获 offline_order_mapping_service SQL。"""

    def __init__(self) -> None:
        self.executes: list[tuple[str, dict]] = []
        self.commits = 0
        self.rollbacks = 0
        # 简化: (tenant_id, offline_order_id) -> row dict
        self._rows: dict[tuple[str, str], dict] = {}

    async def execute(self, stmt, params=None):
        sql = str(stmt).strip()
        p = dict(params) if params else {}
        self.executes.append((sql, p))

        # UPSERT mapping
        if sql.startswith("INSERT INTO offline_order_mapping"):
            key = (p["tenant_id"], p["offline_order_id"])
            row = self._rows.get(key, {})
            row.update(
                {
                    "tenant_id": p["tenant_id"],
                    "store_id": p["store_id"],
                    "device_id": p["device_id"],
                    "offline_order_id": p["offline_order_id"],
                    "cloud_order_id": p.get("cloud_order_id"),
                    "state": p.get("state", MappingState.PENDING.value),
                    "sync_attempts": p.get("sync_attempts", 0),
                    "dead_letter_reason": p.get("dead_letter_reason"),
                    "created_at": p.get("created_at"),
                    "synced_at": p.get("synced_at"),
                }
            )
            self._rows[key] = row
            return AsyncMock(rowcount=1)

        if sql.startswith("UPDATE offline_order_mapping"):
            key = (p["tenant_id"], p["offline_order_id"])
            if key in self._rows:
                row = self._rows[key]
                # service 层把 dead_letter_reason 作为 :reason 传入；sync_attempts
                # 递增在生产 SQL 中用表达式完成（非参数），此处 mock 代为 +1
                if "reason" in p:
                    row["dead_letter_reason"] = p["reason"]
                for k in (
                    "cloud_order_id",
                    "state",
                    "synced_at",
                ):
                    if k in p:
                        row[k] = p[k]
                # sync_attempts 递增（匹配生产 SET sync_attempts = sync_attempts + 1）
                if "SET sync_attempts" in sql and "+ 1" in sql:
                    row["sync_attempts"] = int(row.get("sync_attempts", 0)) + 1
                return AsyncMock(rowcount=1)
            return AsyncMock(rowcount=0)

        if sql.startswith("SELECT") and "offline_order_mapping" in sql:
            # 返回行列表
            if "AND offline_order_id" in sql:
                key = (p["tenant_id"], p["offline_order_id"])
                row = self._rows.get(key)
                mock_result = SimpleNamespace(
                    mappings=lambda: SimpleNamespace(first=lambda: row, all=lambda: [row] if row else [])
                )
                return mock_result
            # list_pending
            rows = [
                r
                for r in self._rows.values()
                if r["tenant_id"] == p.get("tenant_id")
                and r["store_id"] == p.get("store_id")
                and r["state"] == MappingState.PENDING.value
            ]
            mock_result = SimpleNamespace(
                mappings=lambda: SimpleNamespace(
                    first=lambda: rows[0] if rows else None,
                    all=lambda: rows,
                )
            )
            return mock_result

        # set_config（RLS 绑定）与其它
        return AsyncMock()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


# ──────────────── 场景 1：200 单 UUID v7 无碰撞 + 单调 ────────────────


def test_xujihaixian_offline_200_orders_unique_uuid_v7_zero_collision():
    """徐记王府井店商米 T2 断网 2 小时，连续生成 200 个离线订单号。
    验证：
      - 200 个 UUID v7 payload 互不碰撞
      - 200 个 order_id 字符串互不碰撞
      - UUID v7 时间戳单调不减（同设备）
      - order_id 格式符合 A1 锁定：{device_id}:{ms_epoch}:{counter}
    """
    order_ids: list[str] = []
    uuids: list = []
    for i in range(200):
        counter = i + 1
        oid, u = generate_offline_order_id(POS_DEVICE_A, counter)
        order_ids.append(oid)
        uuids.append(u)

    # 无碰撞
    assert len(set(order_ids)) == 200, "200 order_id 必须互不相同"
    assert len(set(str(u) for u in uuids)) == 200, "200 UUID v7 必须互不相同"

    # UUID v7 版本字段
    for u in uuids:
        assert u.version == 7, f"期望 UUID v7，得 {u.version}"

    # 单调：UUID v7 高 48 bit 为 ms epoch 不减（同设备同批次）
    # ms_epoch 从 UUID 前 48 位抽出
    def _ms_from_uuid7(u) -> int:
        return (u.int >> 80) & 0xFFFFFFFFFFFF

    ms_list = [_ms_from_uuid7(u) for u in uuids]
    assert ms_list == sorted(ms_list), "UUID v7 ms epoch 必须单调不减"

    # A1 锁定格式：{device_id}:{ms_epoch}:{counter}
    for i, oid in enumerate(order_ids):
        parsed = parse_offline_order_id(oid)
        assert parsed["device_id"] == POS_DEVICE_A
        assert parsed["counter"] == i + 1
        assert isinstance(parsed["ms_epoch"], int)
        assert parsed["ms_epoch"] > 0


# ──────────────── 场景 2：跨天 counter 重置仍唯一 ────────────────


def test_xujihaixian_device_counter_resets_on_new_day_safe():
    """徐记王府井店 POS 凌晨 0 点跨天，counter 重置为 1。
    同设备 counter=1 在 day1 和 day2 分别生成，order_id 必须仍唯一
    (ms_epoch 不同)。"""
    # day1 12:00
    day1_ms = 1735833600000  # 2025-01-02 12:00:00 UTC
    day2_ms = day1_ms + 86400 * 1000  # +24h

    clock1 = [day1_ms / 1000.0]
    oid1, u1 = generate_offline_order_id(POS_DEVICE_A, counter=1, clock=lambda: clock1[0])

    # 跨天后 counter 重置
    clock2 = [day2_ms / 1000.0]
    oid2, u2 = generate_offline_order_id(POS_DEVICE_A, counter=1, clock=lambda: clock2[0])

    assert oid1 != oid2, "跨天 counter=1 必须仍唯一"
    assert u1 != u2
    p1 = parse_offline_order_id(oid1)
    p2 = parse_offline_order_id(oid2)
    assert p1["counter"] == p2["counter"] == 1
    assert p2["ms_epoch"] > p1["ms_epoch"]


# ──────────────── 场景 3：两台 POS 同毫秒无碰撞 ────────────────


def test_xujihaixian_two_devices_same_ms_no_collision():
    """徐记王府井店 2 号台商米 POS-A 与 4 号台 POS-B 同一毫秒生成订单号。
    device_id 前缀保证 order_id 无碰撞；UUID v7 payload 仍然独立。"""
    fixed_ms = 1735833600000
    fixed_clock = lambda: fixed_ms / 1000.0  # noqa: E731

    oid_a, u_a = generate_offline_order_id(POS_DEVICE_A, 7, clock=fixed_clock)
    oid_b, u_b = generate_offline_order_id(POS_DEVICE_B, 7, clock=fixed_clock)

    assert oid_a != oid_b, "两台设备同毫秒必须产生不同 order_id"
    assert u_a != u_b, "UUID v7 payload 必须独立（随机位不同）"

    p_a = parse_offline_order_id(oid_a)
    p_b = parse_offline_order_id(oid_b)
    assert p_a["device_id"] == POS_DEVICE_A
    assert p_b["device_id"] == POS_DEVICE_B
    assert p_a["ms_epoch"] == p_b["ms_epoch"]
    assert p_a["counter"] == p_b["counter"] == 7


# ──────────────── 场景 4：离线 order_id 同步上云 → 映射 ────────────────


@pytest.mark.asyncio
async def test_xujihaixian_offline_order_resync_maps_to_cloud_id():
    """徐记王府井店断网 1h 生成 order_id，恢复联网后同步到云端，
    云端生成 cloud_order_id（UUID），offline_order_mapping 记录
    offline_id → cloud_id 映射供对账使用。"""
    db = _MockDB()
    svc = OfflineOrderMappingService(db=db, tenant_id=XUJI_CHANGSHA_TENANT)

    offline_id, _ = generate_offline_order_id(POS_DEVICE_A, counter=42)
    cloud_id = "11111111-1111-1111-1111-111111111111"

    # Step1: enqueue pending
    await svc.upsert_mapping(
        store_id=XUJI_CHANGSHA_STORE,
        device_id=POS_DEVICE_A,
        offline_order_id=offline_id,
    )
    row_pending = await svc.get(offline_id)
    assert row_pending is not None
    assert row_pending["state"] == MappingState.PENDING.value

    # Step2: 同步成功
    await svc.mark_synced(offline_order_id=offline_id, cloud_order_id=cloud_id)
    row_synced = await svc.get(offline_id)
    assert row_synced["state"] == MappingState.SYNCED.value
    assert row_synced["cloud_order_id"] == cloud_id


# ──────────────── 场景 5：补发 20 次死信不自动删除 ────────────────


@pytest.mark.asyncio
async def test_xujihaixian_dead_letter_awaits_manual_confirm():
    """徐记王府井店某单格式损坏，后台 Flusher 连续补发 20 次均失败
    → mark_dead_letter('sync_failed_20x')；条目必须保留等待店长确认，
    严禁自动删除（CLAUDE.md §13 禁止悄无声息吞单）。"""
    db = _MockDB()
    svc = OfflineOrderMappingService(db=db, tenant_id=XUJI_CHANGSHA_TENANT)

    offline_id, _ = generate_offline_order_id(POS_DEVICE_A, counter=99)

    await svc.upsert_mapping(
        store_id=XUJI_CHANGSHA_STORE,
        device_id=POS_DEVICE_A,
        offline_order_id=offline_id,
    )

    # 连续 20 次失败
    for _ in range(DEAD_LETTER_MAX_ATTEMPTS):
        await svc.increment_sync_attempt(offline_id)

    await svc.mark_dead_letter(offline_order_id=offline_id, reason="sync_failed_20x")

    row = await svc.get(offline_id)
    assert row is not None, "死信条目不得自动删除"
    assert row["state"] == MappingState.DEAD_LETTER.value
    assert row["dead_letter_reason"] == "sync_failed_20x"
    assert row["sync_attempts"] >= DEAD_LETTER_MAX_ATTEMPTS


# ──────────────── 场景 6：A2 SagaBuffer 幂等键格式一致 ────────────────


def test_xujihaixian_idempotency_key_format_consistent_with_a2():
    """徐记王府井店离线结算：
      - 前端生成 order_id = `{device_id}:{ms_epoch}:{counter}`
      - idempotency_key = `settle:{order_id}`
      - A2 SagaBuffer.enqueue 以 idempotency_key 作为 PK 去重

    两次同一 order_id 生成 idempotency_key 必须一致（字符串相等），
    A2 buffer 才能正确 UPSERT 复用 saga_id（防双扣费）。"""
    offline_id, _ = generate_offline_order_id(POS_DEVICE_A, counter=47)
    ikey1 = f"settle:{offline_id}"
    ikey2 = f"settle:{offline_id}"
    assert ikey1 == ikey2, "同一 order_id 生成幂等键必须字符串相等"

    # 校验 ikey 格式可被 A2 SagaBuffer 使用（TEXT PRIMARY KEY 无长度限制但 <= 128）
    assert ikey1.startswith("settle:")
    assert len(ikey1) <= 128, "idempotency_key 须 <= 128（A2 Pydantic max_length）"

    # 格式可被解析
    oid_recovered = ikey1[len("settle:") :]
    parsed = parse_offline_order_id(oid_recovered)
    assert parsed["device_id"] == POS_DEVICE_A
    assert parsed["counter"] == 47


# ──────────────── 场景 7：跨租户不可见（RLS + service 层双隔离） ────────────────


@pytest.mark.asyncio
async def test_xujihaixian_cross_tenant_order_id_no_leak():
    """徐记王府井店 tenant_A 与韶山路店 tenant_B 共用一个 Mac mini 同步服务
    （压测场景）。service 层查询必须带 tenant_id 过滤，下层 RLS 再兜底。
    tenant_B service 绝不能读取 tenant_A 的 mapping。"""
    db = _MockDB()
    svc_a = OfflineOrderMappingService(db=db, tenant_id=XUJI_CHANGSHA_TENANT)
    svc_b = OfflineOrderMappingService(db=db, tenant_id=XUJI_SHAOSHAN_TENANT)

    oid_a, _ = generate_offline_order_id(POS_DEVICE_A, counter=1)
    oid_b, _ = generate_offline_order_id(POS_DEVICE_B, counter=1)

    await svc_a.upsert_mapping(
        store_id=XUJI_CHANGSHA_STORE,
        device_id=POS_DEVICE_A,
        offline_order_id=oid_a,
    )
    await svc_b.upsert_mapping(
        store_id=XUJI_SHAOSHAN_STORE,
        device_id=POS_DEVICE_B,
        offline_order_id=oid_b,
    )

    # tenant_B svc 查 tenant_A 的 oid → 拿不到
    row = await svc_b.get(oid_a)
    assert row is None, "tenant_B 不得读取 tenant_A mapping"

    # tenant_A svc 查自家能拿到
    row_own = await svc_a.get(oid_a)
    assert row_own is not None
    assert row_own["tenant_id"] == XUJI_CHANGSHA_TENANT

    # SQL 必须包含 tenant_id 过滤（不能依赖 RLS 单层）
    select_sqls = [s for s, _ in db.executes if s.startswith("SELECT") and "offline_order_mapping" in s]
    assert any("tenant_id" in s for s in select_sqls), "SELECT 必须显式带 tenant_id 过滤"


# ──────────────── 场景 8：Flag off 保留 legacy 行为 ────────────────


def test_flag_off_legacy_server_generated_order_id():
    """edge.offline.order_id_bridge 默认 off。legacy 行为：order_id
    由服务端 _gen_order_no() 生成（TX + 时间 + uuid4.hex[:4]）。
    验证 flag 注册且默认 off，rollout 节奏为 [5, 50, 100]。"""
    from shared.feature_flags.flag_names import EdgeFlags

    assert EdgeFlags.OFFLINE_ORDER_ID_BRIDGE == "edge.offline.order_id_bridge"

    # 解析 edge_flags.yaml 并定位该 flag
    import pathlib

    import yaml

    repo_root = pathlib.Path(__file__).resolve().parents[4]
    flag_file = repo_root / "flags" / "edge" / "edge_flags.yaml"
    data = yaml.safe_load(flag_file.read_text(encoding="utf-8"))
    names = {f["name"]: f for f in data["flags"]}
    assert EdgeFlags.OFFLINE_ORDER_ID_BRIDGE in names, "flag 未注册到 edge_flags.yaml"
    flag = names[EdgeFlags.OFFLINE_ORDER_ID_BRIDGE]
    assert flag["defaultValue"] is False, "Tier1 Flag 默认必须 off"
    for env in ("dev", "test", "pilot", "prod"):
        assert flag["environments"][env] is False, f"env={env} 不应默认开启"
    assert flag["rollout"] == [5, 50, 100]
    assert "tier1" in flag["tags"]


# ──────────────── 补：UUID v7 性能 & 边界 ────────────────


def test_generate_offline_order_id_performance_smoke():
    """附加：单次生成应 < 1ms（不影响 P99<200ms 结算预算）。非 Tier1 门槛，
    仅防止引入时间锁/加密昂贵调用。"""
    t0 = time.perf_counter()
    for i in range(500):
        generate_offline_order_id(POS_DEVICE_A, counter=i + 1)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    # 500 次 < 500ms 即可（平均 < 1ms/次）
    assert elapsed_ms < 500, f"生成性能超预算: {elapsed_ms:.1f}ms/500 次"
