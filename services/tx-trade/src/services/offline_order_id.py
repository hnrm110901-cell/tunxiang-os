"""offline_order_id — Sprint A3 离线订单号生成器（UUID v7 + 人读前缀）

背景（A1 工单 R2 锁定契约）：
  order_id = `{device_id}:{ms_epoch}:{counter}`  ← 人读前缀（收银员/店长肉眼识别）
  同时携带 UUID v7 payload 作为 idempotency 后端强隔离的随机源
  idempotency_key = `settle:{order_id}`          ← A1/A2 共享契约

UUID v7（RFC 9562）结构（128 bit）：
    +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
    |              unix_ts_ms (48 bit)                              |
    +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
    | ver(4) |   rand_a (12 bit)                                    |
    +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
    | var(2) |   rand_b (62 bit)                                    |
    +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+

  - ver  = 0b0111  （v7）
  - var  = 0b10    （RFC 4122 variant）
  - unix_ts_ms 放高 48 bit → B-tree/索引天然时间有序
  - rand_a (12 bit) + rand_b (62 bit) = 74 bit 随机，碰撞概率 < 1e-22

Python 3.11 兼容实现（不依赖 3.14 原生 uuid.uuid7() 与第三方包）。
同毫秒同设备 counter++ 已由调用方维护（见 generate_offline_order_id.counter 参数）。

安全约束：
  - secrets.token_bytes 生成 74 bit 随机（CSPRNG，不可预测）
  - 禁止用 random.random() — 单测可预测但生产不可控

对齐：
  - A1 前端 tradeApi.ts 的 idempotency_key（`settle:{orderId}`）
  - A2 SagaBuffer.enqueue(idempotency_key=...) 的 PK 去重
  - sync-engine V4 Phase 1 字段协议：offline_order_id/cloud_order_id/device_id
"""

from __future__ import annotations

import re
import secrets
import time
import uuid
from typing import Callable

# ─── 格式常量 ─────────────────────────────────────────────────────────────────

# A1 锁定格式：`{device_id}:{ms_epoch}:{counter}`
_ORDER_ID_PATTERN = re.compile(r"^([A-Za-z0-9_\-\.]{1,64}):(\d{10,16}):(\d+)$")

# device_id 允许字母/数字/下划线/短横/点（商米 POS 序列号常见字符集）
_DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-\.]{1,64}$")


# ─── UUID v7 生成 ─────────────────────────────────────────────────────────────


def _uuid7_from_ms(unix_ms: int) -> uuid.UUID:
    """按 RFC 9562 手工构造 UUID v7。

    不用 Python 3.14 原生 uuid.uuid7() — 本 repo 基线 3.11。
    不引入第三方 uuid6 / uuid-utils — 避免加新依赖。

    Args:
        unix_ms: Unix epoch 毫秒（48 bit 内）

    Returns:
        uuid.UUID (version=7, variant=RFC4122)
    """
    if unix_ms < 0 or unix_ms >= (1 << 48):
        raise ValueError(f"unix_ms out of 48-bit range: {unix_ms}")

    # 74 bit 随机（12 + 62）。取 10 字节 = 80 bit，截断到 74 bit
    rand_bytes = secrets.token_bytes(10)
    rand_int = int.from_bytes(rand_bytes, "big")
    rand_a = (rand_int >> 62) & 0xFFF  # 低 12 bit 作 rand_a
    rand_b = rand_int & ((1 << 62) - 1)  # 62 bit rand_b

    # 拼 128 bit 整数
    result = (unix_ms & ((1 << 48) - 1)) << 80
    result |= 0x7 << 76  # version 7
    result |= (rand_a & 0xFFF) << 64
    result |= 0b10 << 62  # RFC 4122 variant
    result |= rand_b & ((1 << 62) - 1)

    return uuid.UUID(int=result)


# ─── 主接口 ──────────────────────────────────────────────────────────────────


def generate_offline_order_id(
    device_id: str,
    counter: int,
    clock: Callable[[], float] = time.time,
) -> tuple[str, uuid.UUID]:
    """生成离线订单号。

    格式严格遵守 A1 锁定契约：
        order_id = f"{device_id}:{ms_epoch}:{counter}"
        UUID v7 作为随机 payload（不拼入字符串，供后端存 cloud_order_id 候选）

    Args:
        device_id: 商米 POS 序列号或其它稳定设备标识（[A-Za-z0-9_\\-\\.]{1,64}）
        counter:   调用方维护的每毫秒自增计数（>=1）。同一毫秒多单必须递增。
        clock:     时钟函数（测试可注入 fake clock）。默认 time.time 秒级。

    Returns:
        (order_id_str, uuid_v7)

    Raises:
        ValueError: device_id 非法 / counter 非正
    """
    if not device_id or not _DEVICE_ID_PATTERN.match(device_id):
        raise ValueError(f"invalid device_id: {device_id!r}")
    if counter < 1:
        raise ValueError(f"counter must be >= 1, got {counter}")

    ms_epoch = int(clock() * 1000)
    if ms_epoch < 0:
        raise ValueError(f"clock returned negative ms: {ms_epoch}")

    uuid_v7 = _uuid7_from_ms(ms_epoch)
    order_id = f"{device_id}:{ms_epoch}:{counter}"
    return order_id, uuid_v7


def parse_offline_order_id(order_id: str) -> dict:
    """解析 order_id 字符串。

    返回 {"device_id": str, "ms_epoch": int, "counter": int}。

    Raises:
        ValueError: 格式非法
    """
    if not isinstance(order_id, str):
        raise ValueError(f"order_id must be str, got {type(order_id).__name__}")

    m = _ORDER_ID_PATTERN.match(order_id)
    if not m:
        raise ValueError(f"invalid offline order_id format (expect 'device_id:ms_epoch:counter'): {order_id!r}")
    device_id, ms_str, counter_str = m.group(1), m.group(2), m.group(3)
    return {
        "device_id": device_id,
        "ms_epoch": int(ms_str),
        "counter": int(counter_str),
    }


def idempotency_key_for_settle(order_id: str) -> str:
    """生成 A1/A2 共享的 settle idempotency_key。

    契约：`settle:{order_id}`。禁止偏离 — 会破坏 A2 SagaBuffer 去重。
    """
    return f"settle:{order_id}"
