# 抖音生活服务开放平台 API 适配器

对接抖音生活服务开放平台，提供团购券管理、订单查询、门店信息、结算单等功能。

## 目录

1. [配置说明](#配置说明)
2. [快速开始](#快速开始)
3. [API 方法](#api-方法)
4. [字段映射](#字段映射)
5. [错误码表](#错误码表)
6. [错误处理](#错误处理)
7. [幂等性保障](#幂等性保障)
8. [事件发射](#事件发射)
9. [已知问题与注意事项](#已知问题与注意事项)
10. [测试指南](#测试指南)

---

## 配置说明

### 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `DOUYIN_APP_ID` | 是 | — | 抖音开放平台 App ID |
| `DOUYIN_APP_SECRET` | 是 | — | 抖音开放平台 App Secret |
| `DOUYIN_SANDBOX` | 否 | `false` | 设为 `true` 使用沙箱环境 |

### 构造函数参数

`DouyinAdapter.__init__(config)` 接受一个字典：

| 键 | 必填 | 类型 | 默认值 | 说明 |
|-------|------|------|--------|------|
| `app_id` | 是 | str | `DOUYIN_APP_ID` | 抖音开放平台应用ID |
| `app_secret` | 是 | str | `DOUYIN_APP_SECRET` | 抖音开放平台密钥 |
| `sandbox` | 否 | bool | `False` | 沙箱模式开关 |
| `tenant_id` | 否 | str | `""` | 屯象租户 ID（事件发射用） |
| `timeout` | 否 | int | `30` | HTTP 超时（秒） |
| `retry_times` | 否 | int | `3` | 失败重试次数 |

### URL 规则

- **生产环境**：`https://open.douyin.com`
- **沙箱环境**：`https://open-sandbox.douyin.com`

---

## 快速开始

```python
import asyncio
from shared.adapters.douyin.src.adapter import DouyinAdapter

async def main():
    adapter = DouyinAdapter({
        "app_id": "your_app_id",
        "app_secret": "your_app_secret",
        "sandbox": True,
    })

    # 查询团购券
    coupons = await adapter.query_coupons(page=1, page_size=20)
    print("团购券:", coupons)

    # 查询订单
    orders = await adapter.query_orders("2026-01-01T00:00:00", "2026-01-31T23:59:59")
    print("订单:", orders)

    # 核销团购券
    result = await adapter.verify_coupon(code="encrypted_code", shop_id="shop_123")
    print("核销结果:", result)

    await adapter.close()

asyncio.run(main())
```

---

## API 方法

### DouyinAdapter

#### `query_coupons(page, page_size) -> dict`

查询团购券列表。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `page` | int | 否 | `1` | 页码 |
| `page_size` | int | 否 | `20` | 每页数量 |

返回 `data` 字段内容，典型结构：

```json
{
    "coupons": [
        {"coupon_id": "123", "code": "ABC", "status": 1, "amount": 1000}
    ],
    "total": 100,
    "page": 1
}
```

#### `get_coupon_detail(coupon_id) -> dict`

查询单张团购券详情。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `coupon_id` | str | 是 | 团购券 ID |

#### `verify_coupon(code, shop_id) -> dict`

核销团购券（委托 `DouyinClient.verify_certificate`）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | str | 是 | 加密券码 |
| `shop_id` | str | 是 | 抖音门店 ID |

#### `query_orders(start_time, end_time, page, page_size) -> dict`

查询团购订单列表。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `start_time` | str | 是 | — | 开始时间 (ISO 格式) |
| `end_time` | str | 是 | — | 结束时间 (ISO 格式) |
| `page` | int | 否 | `1` | 页码 |
| `page_size` | int | 否 | `20` | 每页大小 |

#### `get_order_detail(order_id) -> dict`

查询团购订单详情。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_id` | str | 是 | 抖音订单 ID |

#### `get_shop_info(shop_id) -> dict`

查询抖音门店信息。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `shop_id` | str | 是 | 抖音门店 ID |

#### `query_settlements(start_date, end_date) -> dict`

查询结算单列表。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `start_date` | str | 是 | 开始日期 (YYYY-MM-DD) |
| `end_date` | str | 是 | 结束日期 (YYYY-MM-DD) |

#### `close()`

关闭适配器，释放 HTTP 连接池。

---

## 字段映射

### 核销请求

| 抖音参数 | 适配器参数 | 类型 | 说明 |
|----------|-----------|------|------|
| `encrypted_code` | `code` | string | 加密券码（核销时传入） |
| `shop_id` | `shop_id` | string | 抖音门店 ID |

### 订单查询响应

| 抖音字段 | 映射到屯象字段 | 类型 | 说明 |
|----------|---------------|------|------|
| `order_id` | `order_id` | string | 抖音订单号 |
| `status` | `order_status` | int | 订单状态码 |
| `total_amount` | `total_fen` | int | 总金额（分） |
| `create_time` | `created_at` | string | 创建时间 |

### 结算单响应

| 抖音字段 | 映射到屯象字段 | 类型 | 说明 |
|----------|---------------|------|------|
| `settlement_id` | `settlement_id` | string | 结算单号 |
| `amount` | `amount_fen` | int | 结算金额（分） |
| `status` | `status` | int | 结算状态 |

---

## 错误码表

| 抖音 error_code | 说明 | 处理策略 |
|----------------|------|----------|
| `0` | 成功 | 正常处理 |
| `2` | 参数错误 | 检查请求参数，不重试 |
| `2100001` | access_token 过期 | 自动刷新后重试 |
| `2100002` | access_token 无效 | 自动刷新后重试 |
| `2100007` | 签名错误 | 检查 app_secret 配置 |
| `2100010` | 调用频率超限 | 降速后重试 |
| `2100011` | API 不存在 | 检查接口路径 |
| `2200001` | 券码不存在 | 检查券码，不重试 |
| `2200002` | 券已核销 | 幂等处理，不重试 |
| `2200003` | 券已过期 | 提示用户，不重试 |
| `2200004` | 门店不匹配 | 检查 shop_id |
| `2300001` | 订单不存在 | 检查 order_id |
| `2400001` | 结算单不存在 | 检查日期范围 |

---

## 错误处理

### 异常体系

| 异常 | 触发条件 | 说明 |
|------|----------|------|
| `ConnectionError` | 抖音返回非 2xx HTTP 状态码 | 自动重试（最多 `retry_times` 次），重试耗尽后抛出 |
| `httpx.ConnectError` | 网络不可达 | 自动重试 |
| `httpx.TimeoutException` | 请求超时 | 自动重试 |
| `ValueError` | 抖音返回业务错误码（非 0） | 从 `_check_biz_error` 抛出，不重试 |
| `PermissionError` | token 获取失败 | 检查 app_id/app_secret 配置 |

### 重试策略

- 指数退避：无显式退避，连续重试
- 仅重试 HTTP 层错误（连接/超时/5xx）
- 业务错误码（如"券已核销"）不重试

### 日志关键点

| Logger Name | level | 触发场景 |
|-------------|-------|----------|
| `douyin_client_init` | INFO | Client 初始化 |
| `douyin_token_refreshed` | INFO | Token 刷新成功 |
| `douyin_token_http_error` | ERROR | Token 请求 HTTP 错误 |
| `douyin_http_error` | ERROR | API 请求 HTTP 错误 |
| `douyin_request_error` | ERROR | 网络/超时错误 |
| `douyin_client_closed` | INFO | Client 关闭 |
| `douyin.event_emit_failed` | WARNING | 事件发射失败（不阻断主流程） |

---

## 幂等性保障

`DouyinAdapter` 内置运行时幂等性检查：

```python
# 生成幂等键
key = adapter.idempotency_key("verify_coupon", {"code": "xxx", "shop_id": "yyy"})
# key 基于 "operation:tenant_id:payload(json)" 的 MD5 哈希

# 检查重复
if adapter.is_duplicate(key):
    # 已处理过相同请求
    return {"success": True, "message": "duplicate"}

# 标记已处理
adapter.mark_idempotent(key)
```

幂等性基于内存 `Set[str]` 实现，进程重启后去重状态丢失。
**生产环境**建议配合数据库唯一约束或 Redis 持久化。

---

## 事件发射

适配器在关键操作后异步发射总线事件（fire-and-forget）：

| 事件类型 | 触发操作 | scope | stream_id 格式 |
|----------|----------|-------|----------------|
| `STATUS_PUSHED` | `query_coupons` | `coupon_query` | `douyin:coupon:list` |
| `STATUS_PUSHED` | `get_coupon_detail` | `coupon_detail` | `douyin:coupon:{coupon_id}` |
| `STATUS_PUSHED` | `verify_coupon` | `coupon_verify` | `douyin:coupon:verify:{shop_id}` |
| `SYNC_FINISHED` | `query_orders` | `orders` | `douyin:orders:{start}:{end}` |
| `SYNC_FINISHED` | `get_order_detail` | `order_detail` | `douyin:order:{order_id}` |
| `SYNC_FINISHED` | `get_shop_info` | `shop_info` | `douyin:shop:{shop_id}` |
| `SYNC_FINISHED` | `query_settlements` | `settlement` | `douyin:settlement:{start}:{end}` |

事件发射失败仅记录 WARNING，不阻断主业务流程。

---

## 已知问题与注意事项

### 已知问题

1. **Token 无持久化**：`_access_token` 存储在内存中，进程重启后需要重新获取。Token 有效期通常为 2 小时，过期前 1 分钟自动刷新。
2. **幂等性内存存储**：`_nonce_store` 使用 `Set[str]` 而非 Redis，项目重启后去重状态丢失。多实例部署场景需改为共享存储。
3. **沙箱环境限制**：沙箱环境部分接口可能不完整，建议先在沙箱验证核心流程。沙箱 token 目前默认从生产环境获取，与抖音官方配置有关。
4. **券码加密**：`verify_coupon` 接收的 `code` 参数是抖音加密券码，不是明文券码。核销前需确保从正确途径获取。

### 注意事项

1. **金额单位统一为分**：所有金额字段使用整数（分），避免浮点精度问题。
2. **接口版本差异**：团购券管理使用 `v2` 接口，核销和订单查询使用 `goodlife/v1` 接口。两套接口在路径和认证方式上略有差异，注意区分。
3. **时间参数格式**：`query_orders` 的 `start_time` 和 `end_time` 使用 ISO 8601 格式（如 `"2026-01-01T00:00:00"`），`query_settlements` 的日期使用 `YYYY-MM-DD` 格式。
4. **分页限制**：单次查询最大 page_size 通常为 50，超过限制会报参数错误。
5. **网络重试策略**：仅重试 HTTP 层面错误，业务错误码不重试。`retry_times` 控制最大尝试次数，包括首次请求。
6. **事件发射异常隔离**：`_emit_sync_event` 使用 `asyncio.create_task` 异步发射，不阻塞主流程。事件总线故障不影响接口调用。
7. **核销操作不可逆**：`verify_coupon` 一旦调用成功，券码即被核销。调用前建议做幂等性检查和业务确认。

### 测试指南

```bash
# 运行单元测试
pytest shared/adapters/douyin/tests/ -v

# 覆盖率报告
pytest shared/adapters/douyin/tests/ --cov=shared.adapters.douyin.src --cov-report=term-missing
```

测试覆盖以下场景：
- 初始化（沙箱/生产环境配置）
- Access Token 缓存与过期刷新
- 幂等性键生成与去重
- 各业务方法成功路径
- 业务错误路径（抖音 API 错误码）
- HTTP 错误路径（连接/超时/状态码错误）
- 事件发射（fire-and-forget）

---

## 版本兼容性

| 适配器版本 | 抖音 API 版本 | 屯象 OS 版本 | 备注 |
|------------|---------------|-------------|------|
| v1.0 | 2024-06 | v0.9+ | 初始版本 |
| v1.1 | 2025-06 | v0.11+ | 增加事件发射 + 幂等性 |

---

## 参考链接

- [抖音开放平台文档](https://open.douyin.com)
- [抖音生活服务 API 文档](https://developer.open-douyin.com/docs/)
