"""test_kds_delta_tier1 — Sprint C3 KDS delta + device_registry Tier1 徐记场景

Tier1 铁律（CLAUDE.md §17/§20 零容忍）：
  - 测试用例全部基于徐记海鲜真实场景（非技术边界值）
  - cursor 单调 / RLS 跨租户不可见 / store_id 边界 / P99<100ms / 60s 断网恢复
  - device_kind 枚举强制 / 心跳 upsert last_seen / kds 专属字段过滤
  - 先写测试、再写实现（本文件锁定行为契约）

与 A3 的契约共享：
  - device_id 格式 = `{prefix}-{store}-{counter}` 字符串（A3 已锁，本 C3 不重定义）
  - tenant_id / store_id 路径保持 RLS
  - sync_attempts / last_sync_at 命名范式与 A3 offline_order_mapping 对齐

8 条徐记海鲜场景（与工单 Step 2 一一对应）：
  1. test_xujihaixian_kds_delta_returns_only_new_orders_since_cursor
  2. test_xujihaixian_kds_delta_respects_rls_cross_tenant
  3. test_xujihaixian_kds_delta_bounded_by_store_id
  4. test_xujihaixian_kds_delta_p99_under_100ms_at_200_orders
  5. test_xujihaixian_kds_reconnect_60s_full_sync
  6. test_xujihaixian_device_registry_heartbeat_last_seen_updated
  7. test_xujihaixian_device_kind_enum_enforced
  8. test_xujihaixian_kds_delta_includes_device_kind_filter

数据约定：徐记海鲜长沙 17 号店（tenant_A）/ 18 号店（tenant_A same）/ 韶山路店（tenant_B）
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("TX_AUTH_ENABLED", "true")

from src.services.device_registry_service import (  # noqa: E402
    ALLOWED_DEVICE_KINDS,
    DeviceKind,
    DeviceRegistryService,
)
from src.services.kds_delta_service import (  # noqa: E402
    KDSDeltaService,
    parse_cursor,
)

# ──────────────── 徐记海鲜测试租户 ────────────────

XUJI_17_TENANT = "00000000-0000-0000-0000-0000000000a1"  # 长沙 17 号店所属租户
XUJI_SHAOSHAN_TENANT = "00000000-0000-0000-0000-0000000000b1"
STORE_17 = "00000000-0000-0000-0000-000000000017"
STORE_18 = "00000000-0000-0000-0000-000000000018"
STORE_SHAOSHAN = "00000000-0000-0000-0000-00000000b002"
KDS_DEVICE_17 = "kds-xuji-17-fryer-01"
KDS_DEVICE_SHAOSHAN = "kds-xuji-shaoshan-01"


# ──────────────── MockDB 捕获 SQL ────────────────


class _MockDB:
    """捕获 kds_delta / device_registry service SQL。

    内部模型：
      orders: {(tenant_id, id): {...}}
      registry: {(tenant_id, device_id): {...}}
    """

    def __init__(self) -> None:
        self.executes: list[tuple[str, dict]] = []
        self.commits = 0
        self.rollbacks = 0
        self.orders: dict[tuple[str, str], dict] = {}
        self.registry: dict[tuple[str, str], dict] = {}

    def seed_order(self, **kw) -> None:
        key = (kw["tenant_id"], kw["id"])
        self.orders[key] = kw

    async def execute(self, stmt, params=None):
        sql = str(stmt).strip()
        p = dict(params) if params else {}
        self.executes.append((sql, p))

        # ── KDS delta SELECT ──
        if sql.startswith("SELECT") and "FROM orders" in sql:
            tid = p.get("tenant_id")
            sid = p.get("store_id")
            cursor = p.get("cursor")
            limit = int(p.get("limit", 100))
            rows = []
            for (rtid, _rid), row in self.orders.items():
                if rtid != tid:
                    continue
                if sid and row.get("store_id") != sid:
                    continue
                if cursor and row.get("updated_at") <= cursor:
                    continue
                if row.get("status") not in ("pending", "confirmed", "preparing", "ready"):
                    continue
                rows.append(row)
            rows.sort(key=lambda r: r["updated_at"])
            rows = rows[:limit]
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(all=lambda: rows, first=lambda: rows[0] if rows else None)
            )

        # ── device_registry UPSERT ──
        if sql.startswith("INSERT INTO edge_device_registry"):
            key = (p["tenant_id"], p["device_id"])
            existed = self.registry.get(key)
            if existed is None:
                self.registry[key] = {
                    "tenant_id": p["tenant_id"],
                    "store_id": p["store_id"],
                    "device_id": p["device_id"],
                    "device_kind": p["device_kind"],
                    "device_label": p.get("device_label"),
                    "os_version": p.get("os_version"),
                    "app_version": p.get("app_version"),
                    "last_seen_at": p.get("last_seen_at"),
                    "health_status": p.get("health_status", "unknown"),
                    "buffer_backlog": p.get("buffer_backlog", 0),
                    "created_at": p.get("last_seen_at"),
                    "updated_at": p.get("last_seen_at"),
                    "heartbeat_count": 1,
                }
            else:
                # ON CONFLICT DO UPDATE
                existed.update(
                    {
                        "last_seen_at": p.get("last_seen_at"),
                        "health_status": p.get("health_status", existed.get("health_status")),
                        "buffer_backlog": p.get("buffer_backlog", existed.get("buffer_backlog")),
                        "os_version": p.get("os_version", existed.get("os_version")),
                        "app_version": p.get("app_version", existed.get("app_version")),
                        "device_label": p.get("device_label", existed.get("device_label")),
                        "updated_at": p.get("last_seen_at"),
                        "heartbeat_count": existed.get("heartbeat_count", 0) + 1,
                    }
                )
            return AsyncMock(rowcount=1)

        if sql.startswith("SELECT") and "FROM edge_device_registry" in sql:
            tid = p.get("tenant_id")
            did = p.get("device_id")
            row = self.registry.get((tid, did)) if did else None
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(first=lambda: row, all=lambda: [row] if row else [])
            )

        # set_config（RLS 绑定）
        return AsyncMock()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _make_order(
    *,
    tenant_id: str,
    store_id: str,
    order_id: str | None = None,
    status: str = "preparing",
    updated_at: datetime | None = None,
) -> dict:
    return {
        "tenant_id": tenant_id,
        "id": order_id or str(uuid.uuid4()),
        "store_id": store_id,
        "order_no": f"TX{int(time.time())}",
        "status": status,
        "table_number": "17",
        "updated_at": updated_at or datetime.now(timezone.utc),
        "order_metadata": {},
        "items_count": 3,
    }


# ─────────── 场景 1：cursor 之后的新订单 ───────────


@pytest.mark.asyncio
async def test_xujihaixian_kds_delta_returns_only_new_orders_since_cursor():
    """徐记海鲜长沙 17 号店后厨 KDS 每 5 秒轮询 delta，
    cursor=18:00:00，只返回 18:00:00 之后 status∈(pending/preparing/ready) 的订单。"""
    db = _MockDB()

    base = datetime(2026, 4, 24, 18, 0, 0, tzinfo=timezone.utc)
    # 旧单（cursor 之前，不返回）
    db.seed_order(**_make_order(tenant_id=XUJI_17_TENANT, store_id=STORE_17, updated_at=base - timedelta(minutes=1)))
    # 新单 1（cursor 之后，preparing，返回）
    db.seed_order(
        **_make_order(
            tenant_id=XUJI_17_TENANT,
            store_id=STORE_17,
            updated_at=base + timedelta(seconds=5),
            status="preparing",
        )
    )
    # 新单 2（cursor 之后，ready，返回）
    db.seed_order(
        **_make_order(
            tenant_id=XUJI_17_TENANT,
            store_id=STORE_17,
            updated_at=base + timedelta(seconds=12),
            status="ready",
        )
    )
    # 新单 3（cursor 之后但 completed 不在 KDS 关心状态，不返回）
    db.seed_order(
        **_make_order(
            tenant_id=XUJI_17_TENANT,
            store_id=STORE_17,
            updated_at=base + timedelta(seconds=20),
            status="completed",
        )
    )

    svc = KDSDeltaService(db=db, tenant_id=XUJI_17_TENANT)
    result = await svc.get_orders_delta(store_id=STORE_17, cursor=base, limit=100)

    assert len(result["orders"]) == 2, f"期望只返回 2 条（cursor+preparing+ready），实际 {len(result['orders'])}"
    # next_cursor 为最新一条订单的 updated_at
    assert result["next_cursor"] is not None
    assert result["next_cursor"] >= base + timedelta(seconds=12)
    # 必带 server_time
    assert "server_time" in result


# ─────────── 场景 2：RLS 跨租户 ───────────


@pytest.mark.asyncio
async def test_xujihaixian_kds_delta_respects_rls_cross_tenant():
    """徐记长沙 17 号店 tenant_A 的 KDS 不能看到韶山路店 tenant_B 的订单（RLS 兜底 + service 层过滤）。"""
    db = _MockDB()
    base = datetime(2026, 4, 24, 18, 0, 0, tzinfo=timezone.utc)

    # tenant_A 订单
    db.seed_order(
        **_make_order(tenant_id=XUJI_17_TENANT, store_id=STORE_17, updated_at=base + timedelta(seconds=5))
    )
    # tenant_B 订单（韶山路店）
    db.seed_order(
        **_make_order(
            tenant_id=XUJI_SHAOSHAN_TENANT,
            store_id=STORE_SHAOSHAN,
            updated_at=base + timedelta(seconds=5),
        )
    )

    svc_a = KDSDeltaService(db=db, tenant_id=XUJI_17_TENANT)
    result_a = await svc_a.get_orders_delta(store_id=STORE_17, cursor=base)
    assert len(result_a["orders"]) == 1
    assert result_a["orders"][0]["tenant_id"] == XUJI_17_TENANT, "tenant_A 只能看到自家订单"

    svc_b = KDSDeltaService(db=db, tenant_id=XUJI_SHAOSHAN_TENANT)
    result_b = await svc_b.get_orders_delta(store_id=STORE_SHAOSHAN, cursor=base)
    assert len(result_b["orders"]) == 1
    assert result_b["orders"][0]["tenant_id"] == XUJI_SHAOSHAN_TENANT

    # SELECT 必须显式带 tenant_id 过滤（不能依赖 RLS 单层）
    select_sqls = [s for s, _ in db.executes if s.startswith("SELECT") and "FROM orders" in s]
    assert all("tenant_id" in s for s in select_sqls), "SELECT 必须显式带 tenant_id 过滤"


# ─────────── 场景 3：store_id 边界 ───────────


@pytest.mark.asyncio
async def test_xujihaixian_kds_delta_bounded_by_store_id():
    """徐记长沙 17 号店 KDS 不会看到 18 号店的订单（同租户跨门店隔离）。"""
    db = _MockDB()
    base = datetime(2026, 4, 24, 18, 0, 0, tzinfo=timezone.utc)

    db.seed_order(
        **_make_order(tenant_id=XUJI_17_TENANT, store_id=STORE_17, updated_at=base + timedelta(seconds=5))
    )
    db.seed_order(
        **_make_order(tenant_id=XUJI_17_TENANT, store_id=STORE_18, updated_at=base + timedelta(seconds=7))
    )

    svc = KDSDeltaService(db=db, tenant_id=XUJI_17_TENANT)
    result = await svc.get_orders_delta(store_id=STORE_17, cursor=base)

    assert len(result["orders"]) == 1, f"17 号店只应看到自家订单，实际 {len(result['orders'])}"
    assert result["orders"][0]["store_id"] == STORE_17


# ─────────── 场景 4：P99<100ms 性能 ───────────


@pytest.mark.asyncio
async def test_xujihaixian_kds_delta_p99_under_100ms_at_200_orders():
    """徐记长沙 17 号店晚高峰 200 单堆积，KDS delta 查询 P99<100ms。

    门禁说明：KDS 端门禁比 POS（200ms）更严，因为出餐节奏要求低延迟感知。
    本单元测试不走真 PG，仅验证 service 层无 O(n²) 路径或 sleep。
    """
    db = _MockDB()
    base = datetime(2026, 4, 24, 18, 0, 0, tzinfo=timezone.utc)

    for i in range(200):
        db.seed_order(
            **_make_order(
                tenant_id=XUJI_17_TENANT,
                store_id=STORE_17,
                updated_at=base + timedelta(seconds=i),
            )
        )

    svc = KDSDeltaService(db=db, tenant_id=XUJI_17_TENANT)
    samples: list[float] = []
    for _ in range(50):
        t0 = time.perf_counter()
        await svc.get_orders_delta(store_id=STORE_17, cursor=base, limit=100)
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    p99 = samples[int(0.99 * len(samples)) - 1]
    assert p99 < 100, f"P99 {p99:.1f}ms 超过 KDS 100ms 门禁"


# ─────────── 场景 5：60s 断网恢复全同步 ───────────


@pytest.mark.asyncio
async def test_xujihaixian_kds_reconnect_60s_full_sync():
    """徐记长沙 17 号店 KDS 断网 5 分钟，累计 500 单待同步。
    恢复联网后以 limit=100 分页拉取，60s 内全同步完成（5 轮，每轮 P99<100ms）。"""
    db = _MockDB()
    base = datetime(2026, 4, 24, 18, 0, 0, tzinfo=timezone.utc)

    for i in range(500):
        db.seed_order(
            **_make_order(
                tenant_id=XUJI_17_TENANT,
                store_id=STORE_17,
                updated_at=base + timedelta(seconds=i + 1),
            )
        )

    svc = KDSDeltaService(db=db, tenant_id=XUJI_17_TENANT)
    cursor = base  # base < 所有订单 updated_at（seed 从 base+1s 开始）
    collected = 0
    rounds = 0
    t0 = time.perf_counter()

    while rounds < 10:  # 上限 10 轮防死循环
        result = await svc.get_orders_delta(store_id=STORE_17, cursor=cursor, limit=100)
        orders = result["orders"]
        if not orders:
            break
        collected += len(orders)
        cursor = result["next_cursor"]
        rounds += 1

    elapsed = time.perf_counter() - t0
    assert collected == 500, f"500 单应全部同步，实际 {collected}"
    assert rounds == 5, f"limit=100 应 5 轮同步完，实际 {rounds}"
    assert elapsed < 60, f"同步总耗时 {elapsed:.2f}s 超过 60s 门禁"


# ─────────── 场景 6：设备注册表心跳 last_seen ───────────


@pytest.mark.asyncio
async def test_xujihaixian_device_registry_heartbeat_last_seen_updated():
    """徐记长沙 17 号店炒锅 KDS 首次心跳 → insert edge_device_registry；
    后续心跳 → last_seen_at 更新，heartbeat_count 累加。"""
    db = _MockDB()
    svc = DeviceRegistryService(db=db, tenant_id=XUJI_17_TENANT)

    # 首次心跳
    t1 = datetime(2026, 4, 24, 18, 0, 0, tzinfo=timezone.utc)
    await svc.heartbeat(
        device_id=KDS_DEVICE_17,
        device_kind="kds",
        store_id=STORE_17,
        os_version="Android 13",
        app_version="3.0.0",
        buffer_backlog=0,
        now=t1,
    )
    row1 = await svc.get(KDS_DEVICE_17)
    assert row1 is not None
    assert row1["device_kind"] == "kds"
    assert row1["last_seen_at"] == t1

    # 30s 后二次心跳
    t2 = t1 + timedelta(seconds=30)
    await svc.heartbeat(
        device_id=KDS_DEVICE_17,
        device_kind="kds",
        store_id=STORE_17,
        os_version="Android 13",
        app_version="3.0.0",
        buffer_backlog=2,
        now=t2,
    )
    row2 = await svc.get(KDS_DEVICE_17)
    assert row2["last_seen_at"] == t2, "last_seen_at 必须更新"
    assert row2["buffer_backlog"] == 2
    assert row2["heartbeat_count"] >= 2


# ─────────── 场景 7：device_kind 枚举强制 ───────────


@pytest.mark.asyncio
async def test_xujihaixian_device_kind_enum_enforced():
    """只允许 pos/kds/crew_phone/tv_menu/reception/mac_mini，其他值抛错。

    A3 device_id 格式 + C3 device_kind 协议 = sync-engine Phase 1 共享字段。
    """
    db = _MockDB()
    svc = DeviceRegistryService(db=db, tenant_id=XUJI_17_TENANT)

    # 合法枚举全过
    for kind in ALLOWED_DEVICE_KINDS:
        await svc.heartbeat(
            device_id=f"{kind}-test",
            device_kind=kind,
            store_id=STORE_17,
            now=datetime.now(timezone.utc),
        )

    # DeviceKind 枚举值完整性
    assert {k.value for k in DeviceKind} == set(ALLOWED_DEVICE_KINDS)
    assert {"pos", "kds", "crew_phone", "tv_menu", "reception", "mac_mini"} == ALLOWED_DEVICE_KINDS

    # 非法枚举必须抛 ValueError（service 层拦截在进 SQL 之前）
    with pytest.raises(ValueError, match="device_kind"):
        await svc.heartbeat(
            device_id="bad-device",
            device_kind="laptop",  # 未授权
            store_id=STORE_17,
            now=datetime.now(timezone.utc),
        )


# ─────────── 场景 8：device_kind 过滤返回 KDS 必要字段 ───────────


@pytest.mark.asyncio
async def test_xujihaixian_kds_delta_includes_device_kind_filter():
    """?device_kind=kds 时只返回出餐相关字段（order_no/table_number/items_count/
    status/updated_at），剔除与 KDS 无关的金额/客户信息。

    契约目的：限制 KDS 屏幕只看到出餐所需字段，防止客户信息意外泄漏到后厨屏。
    """
    db = _MockDB()
    base = datetime(2026, 4, 24, 18, 0, 0, tzinfo=timezone.utc)

    db.seed_order(
        tenant_id=XUJI_17_TENANT,
        id=str(uuid.uuid4()),
        store_id=STORE_17,
        order_no="TX20260424001",
        status="preparing",
        table_number="17",
        updated_at=base + timedelta(seconds=5),
        order_metadata={},
        items_count=3,
        # 下列字段不应出现在 KDS 视角的响应中：
        customer_phone="13800138000",
        total_amount_fen=28800,
    )

    svc = KDSDeltaService(db=db, tenant_id=XUJI_17_TENANT)
    result = await svc.get_orders_delta(
        store_id=STORE_17,
        cursor=base,
        device_kind="kds",
        limit=100,
    )

    assert len(result["orders"]) == 1
    o = result["orders"][0]

    # KDS 必要字段必须存在
    assert "order_no" in o and o["order_no"] == "TX20260424001"
    assert "status" in o
    assert "updated_at" in o
    assert "table_number" in o
    assert "items_count" in o

    # 敏感字段必须被剔除
    assert "customer_phone" not in o, "KDS 视角不应返回客户手机号"
    assert "total_amount_fen" not in o, "KDS 视角不应返回订单金额"


# ─────────── 附：cursor 解析容错 ───────────


def test_parse_cursor_accepts_iso8601_and_empty():
    """cursor 支持 ISO8601 字符串 / datetime / None。非法格式抛 ValueError。"""
    # datetime 透传
    dt = datetime(2026, 4, 24, 18, 0, 0, tzinfo=timezone.utc)
    assert parse_cursor(dt) == dt

    # ISO8601 Z 后缀
    assert parse_cursor("2026-04-24T18:00:00Z") == dt

    # ISO8601 +00:00
    assert parse_cursor("2026-04-24T18:00:00+00:00") == dt

    # None / 空串 → None（首次拉取）
    assert parse_cursor(None) is None
    assert parse_cursor("") is None

    # 非法
    with pytest.raises(ValueError):
        parse_cursor("yesterday")


# ─────────── 附：Flag 注册 ───────────


def test_flag_edge_kds_delta_sync_registered_defaults_off():
    """edge.kds.delta_sync flag 必须注册且默认全 off（Tier1 灰度铁律）。"""
    from shared.feature_flags.flag_names import EdgeFlags

    assert EdgeFlags.KDS_DELTA_SYNC == "edge.kds.delta_sync"

    import pathlib

    import yaml

    repo_root = pathlib.Path(__file__).resolve().parents[4]
    flag_file = repo_root / "flags" / "edge" / "edge_flags.yaml"
    data = yaml.safe_load(flag_file.read_text(encoding="utf-8"))
    names = {f["name"]: f for f in data["flags"]}
    assert EdgeFlags.KDS_DELTA_SYNC in names, "flag 未注册到 edge_flags.yaml"
    flag = names[EdgeFlags.KDS_DELTA_SYNC]
    assert flag["defaultValue"] is False, "Tier1 Flag 默认必须 off"
    for env in ("dev", "test", "pilot", "prod"):
        assert flag["environments"][env] is False, f"env={env} 不应默认开启"
    assert flag["rollout"] == [5, 50, 100]
    assert "tier1" in flag["tags"]
    assert "c3" in flag["tags"]
