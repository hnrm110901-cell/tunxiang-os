# 易订适配器 - YiDing Adapter

屯象OS 与易订预订系统（https://open.zhidianfan.com/yidingopen/）的集成适配器。

基于真实易订开放 API 实现预订数据读取、会员查询、订单列表等双向同步功能。

---

## 配置说明

### 配置文件

```python
from src.types import YiDingConfig

config: YiDingConfig = {
    "base_url": "https://open.zhidianfan.com/yidingopen/",  # API 基础 URL
    "appid": "your_app_id",                                   # 应用 ID（账号）
    "secret": "your_app_secret",                              # 应用密钥（密码）
    "hotel_id": "30",                                         # 门店 ID（多店时可选）
    "timeout": 10,                                            # 超时时间（秒）
    "max_retries": 3,                                         # 最大重试次数
    "cache_ttl": 300,                                         # 缓存过期时间（秒）
}
```

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `YIDING_TIMEOUT` | HTTP 超时（秒） | `10` |
| `YIDING_MAX_RETRIES` | 最大重试次数 | `3` |

---

## 快速开始

```python
import asyncio
from src.adapter import YiDingAdapter
from src.types import YiDingConfig

config: YiDingConfig = {
    "base_url": "https://open.zhidianfan.com/yidingopen/",
    "appid": "your_appid",
    "secret": "your_secret",
}

async def main():
    adapter = YiDingAdapter(config)
    try:
        # 健康检查
        ok = await adapter.health_check()
        print(f"易订连接: {'OK' if ok else 'FAILED'}")

        # 获取待处理订单（轮询）
        orders = await adapter.get_pending_orders()
        print(f"待处理订单: {len(orders)} 条")

        # 查询会员
        member = await adapter.get_member_info("13800138000")
        if member:
            print(f"会员: {member['name']}, 累计消费: {member['total_amount']}元")
    finally:
        await adapter.close()

asyncio.run(main())
```

---

## API 方法参考

### 核心业务流程：易订 Polling Workflow

易订使用**轮询（polling）** 模式交付线上预订订单，与多数 POS 系统的 Webhook 模式不同：

```
1. get_pending_orders()   → 拉取待处理订单列表（含 requestId）
2. 内部处理订单（存本地 DB 或推送 POS）
3. confirm_orders()       → 用 requestId 确认已收到（下次轮询不再返回这些订单）
```

**重要**：不调用 `confirm_orders()` 会导致同一批订单在每次轮询中反复返回。

### 方法清单

| 方法 | 端点 | 说明 |
|------|------|------|
| `health_check()` | - | 通过获取 Token 验证连通性 |
| `get_pending_orders()` | GET `/resv/orders` | 获取待处理线上预订（轮询入口） |
| `confirm_orders(orders, request_id)` | PUT `/resv/orders` | 确认已收到订单 |
| `check_table_status(table_code, meal_type_code, resv_date)` | GET `/resv/resvable` | 检查桌位预订状态 |
| `update_order(data)` | PUT `/resv/hh_orders` | 新建/更新线下预订 |
| `get_member_info(vip_phone)` | GET `/resv/user_info` | 按手机号查询会员 |
| `get_member_list(start_date, end_date)` | GET `/resv/user/list` | 获取会员列表 |
| `get_order_list(start_date, end_date)` | GET `/resv/orders/list` | 获取预订订单列表 |
| `get_order_list_v2(start_date, end_date)` | GET `/resv/orders/list/V2` | 订单列表 V2（更多字段） |
| `get_reservation_stats(start_date, end_date)` | - | 预订统计（基于 V2 计算） |
| `sync_tables(areas, tables)` | POST `/sync/tables` | 桌位同步（POS -> 易订） |
| `sync_dishes(dls, xls, cms, remarks, making_method)` | POST `/sync/dishes` | 菜品同步（POS -> 易订） |
| `sync_bills(bills)` | POST `/sync/bills` | 账单数据同步 |
| `sync_vips(vips, classes, hotel_id)` | POST `/sync/vips` | 客史数据同步 |

---

## 字段映射

### UnifiedReservation（统一预订格式）

| 字段 | 易订原始字段 | 类型 | 说明 |
|------|-------------|------|------|
| `external_id` | `resv_order` | str | 易订订单号 |
| `store_id` | `hotel_id` | str | 门店 ID |
| `customer_name` | `vip_name` | str | 客户姓名 |
| `customer_phone` | `vip_phone` | str | 客户手机号 |
| `reservation_time` | `dest_time` | str | 预计到店时间 |
| `party_size` | `resv_num` | int | 就餐人数 |
| `status` | `status` | enum | 预订状态映射 |
| `deposit_amount` | `deposit_amount` | str | 押金金额 |
| `pay_amount` | `paymount` | int | 结账金额 |
| `source_name` | `sourceName` | str | 订单来源（V2） |
| `table_area_name` | `table_area_name` | str | 桌位区域（V2） |
| `in_table_time` | `inTableTime` | str | 入座时间（V2） |

### ReservationStatus 映射

| 易订状态码 | 含义 | Unified 映射 |
|-----------|------|-------------|
| 1 | 预订 | `PENDING` |
| 2 | 入座 | `SEATED` |
| 3 | 结账 | `COMPLETED` |
| 4 | 退订 | `CANCELLED` |
| 6 | 换台 | `TABLE_CHANGE` |

---

## 错误码表

| error_code | 含义 | 处理建议 |
|-----------|------|---------|
| 0 | 成功 | - |
| 1 | 数据不存在 | 查询类返回 None，非异常 |
| -2 | Token 过期 | 自动重试（SDK 内置） |
| -3 | Token 无效 | 自动重试（SDK 内置） |
| 其他 | API 业务错误 | 检查请求参数或联系易订支持 |

所有网络级异常（超时/连接断开）以 `YiDingAPIError` 形式抛出，SDK 内置指数退避重试（默认最多 3 次）。

---

## 幂等性

适配器内置幂等性支持，防止网络重试导致重复操作：

```python
# 生成幂等键
key = adapter.idempotency_key("sync_tables", payload)

# 先检查是否已处理过
if adapter.is_duplicate(key):
    logger.info("duplicate request, skipping")
    return

# 执行操作...
result = await adapter.sync_tables(areas, tables)

# 标记已处理
adapter.mark_idempotent(key)
```

幂等性基于 `操作名:租户ID:请求体JSON（排序后）` 的 MD5 哈希，确保相同操作+相同数据不会被重复执行。

---

## 事件发射

适配器在关键操作完成后自动向 `tx_adapter_events` 流发射 `STATUS_PUSHED` 事件：

| 操作方法 | scope | stream_id 模式 |
|----------|-------|----------------|
| `get_pending_orders()` | `orders` | `yiding:pending:{hotel_id}` |
| `confirm_orders()` | `orders` | `yiding:confirm:{hotel_id}` |
| `sync_tables()` | `tables` | `yiding:tables:{hotel_id}` |
| `sync_dishes()` | `dishes` | `yiding:dishes:{hotel_id}` |

事件包含 `adapter_name: "yiding"`、`scope`、`ingested_count` / `pushed_count` 等字段。

设置适配器级别 `_tenant_id` 以启用租户级隔离：
```python
adapter._tenant_id = "tenant-uuid"
```

---

## 注意事项

### aiohttp 依赖
易订适配器使用 **aiohttp** 作为 HTTP 客户端（而非 httpx），因为易订 API 的 `access_token` 通过 query param 传递，且 token 刷新逻辑与 aiohttp 的 session 管理集成更紧密。

需安装依赖：
```bash
pip install aiohttp
```

### Polling 机制
易订使用轮询（polling）而非 Webhook 交付线上订单，这与其他适配器不同：
- 轮询间隔建议 30-60 秒
- 每次轮询后必须调用 `confirm_orders()` 确认
- 未确认的订单会在下次轮询中重复返回

### Token 管理
- Token 由 SDK 自动管理，1 小时有效期内复用
- Token 过期时自动刷新（提前 5 分钟）
- Token 过期由易订 API 返回 `error_code: -2/-3` 触发

### 缓存
适配器内置内存缓存（TTL 默认 300 秒），缓存 key 基于请求参数哈希，适用于高频调用的只读接口。

### 重试机制
适配器基于 aiohttp 内置重试 + 自定义指数退避策略：
- 默认最多重试 3 次
- 退避公式：`0.5 * (2 ^ attempt)` 秒
- 仅对可重试的 HTTP 状态码（5xx/超时）触发重试
- Token 过期（error_code: -2/-3）触发自动刷新后重试

### 错误处理
易订 API 错误通过 `YiDingAPIError` 异常抛出，包含 `error_code` 和 `message` 字段：
- `error_code: 0` — 成功
- `error_code: 1` — 数据不存在（查询类返回 None，非异常）
- `error_code: -2/-3` — Token 问题（自动处理）
- 网络错误 — 抛出 `aiohttp.ClientError` 子类

调用方应捕获 `YiDingAPIError` 处理已知业务错误，`aiohttp.ClientError` 处理网络问题。

### 事件系统
适配器在关键业务流程完成后自动发射 `STATUS_PUSHED` 事件。事件通过 `emit_adapter_event` 函数写入事件总线，采用 fire-and-forget 模式不阻塞主流程。当前已接入事件的方法包括 `get_pending_orders()`、`confirm_orders()`、`sync_tables()`、`sync_dishes()`。

---

## 测试指南

```bash
# 运行所有测试
pytest shared/adapters/yiding/tests/ -v

# 运行特定测试类别
pytest shared/adapters/yiding/tests/test_adapter.py -v -k "test_idempotency"
pytest shared/adapters/yiding/tests/test_health_and_idempotency.py -v

# 查看覆盖率
pytest --cov=shared/adapters/yiding/src --cov-report=html shared/adapters/yiding/tests/

# E2E 测试（需要真实配置）
YIDING_APPID=xxx YIDING_SECRET=xxx pytest tests/test_e2e.py
```

测试基于 Mock（`unittest.mock.patch`），不依赖外部服务。
