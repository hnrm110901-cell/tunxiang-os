# 饿了么开放平台 API 适配器

对接饿了么开放平台，提供订单管理、商品管理、门店管理、配送管理等功能。

## 目录

1. [配置说明](#配置说明)
2. [快速开始](#快速开始)
3. [API 方法](#api-方法)
4. [字段映射](#字段映射)
5. [错误码表](#错误码表)
6. [错误处理](#错误处理)
7. [幂等性保障](#幂等性保障)
8. [事件发射](#事件发射)
9. [Webhook 处理](#webhook-处理)
10. [已知问题与注意事项](#已知问题与注意事项)
11. [测试指南](#测试指南)

---

## 配置说明

### 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `ELEME_APP_KEY` | 是 | — | 饿了么开放平台 App Key |
| `ELEME_APP_SECRET` | 是 | — | 饿了么开放平台 App Secret |
| `ELEME_STORE_ID` | 否 | — | 默认门店 ID |

### 构造函数参数

`ElemeAdapter.__init__(config)` 接受一个字典：

| 键 | 必填 | 类型 | 默认值 | 说明 |
|-------|------|------|--------|------|
| `app_key` | 是 | str | `ELEME_APP_KEY` | 饿了么应用 Key |
| `app_secret` | 是 | str | `ELEME_APP_SECRET` | 饿了么应用 Secret |
| `store_id` | 否 | str | `ELEME_STORE_ID` | 默认门店 ID |
| `sandbox` | 否 | bool | `False` | 沙箱模式开关 |
| `tenant_id` | 否 | str | `""` | 屯象租户 ID（事件发射用） |
| `timeout` | 否 | int | `30` | HTTP 超时（秒） |
| `retry_times` | 否 | int | `3` | 失败重试次数 |

### URL 规则

- **生产环境**：`https://open-api.shop.ele.me/api/v1`
- **沙箱环境**：`https://open-api-sandbox.shop.ele.me/api/v1`

---

## 快速开始

```python
import asyncio
from shared.adapters.eleme.src.adapter import ElemeAdapter

async def main():
    adapter = ElemeAdapter({
        "app_key": "your_app_key",
        "app_secret": "your_app_secret",
        "store_id": "store_123",
        "sandbox": True,
    })

    # 查询订单
    orders = await adapter.query_orders(page=1, page_size=10)
    print("订单:", orders)

    # 确认接单
    result = await adapter.confirm_order("order_456")
    print("确认结果:", result)

    await adapter.close()

asyncio.run(main())
```

---

## API 方法

### 订单管理

#### `query_orders(start_time, end_time, status, page, page_size) -> dict`

查询订单列表。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `start_time` | str | 否 | — | 开始时间 (ISO8601) |
| `end_time` | str | 否 | — | 结束时间 (ISO8601) |
| `status` | int | 否 | — | 订单状态筛选 |
| `page` | int | 否 | `1` | 页码 |
| `page_size` | int | 否 | `20` | 每页数量 |

#### `get_order_detail(order_id) -> dict`

获取订单详情。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_id` | str | 是 | 饿了么订单 ID |

#### `confirm_order(order_id) -> dict`

确认接单。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_id` | str | 是 | 饿了么订单 ID |

#### `cancel_order(order_id, reason_code, reason) -> dict`

取消订单。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_id` | str | 是 | 饿了么订单 ID |
| `reason_code` | int | 是 | 取消原因代码 |
| `reason` | str | 是 | 取消原因描述 |

#### `query_refund(order_id) -> dict`

查询退款信息。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_id` | str | 是 | 饿了么订单 ID |

### 商品管理

#### `query_foods(category_id, page, page_size) -> list`

查询商品列表。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `category_id` | str | 否 | — | 分类 ID（可选筛选） |
| `page` | int | 否 | `1` | 页码 |
| `page_size` | int | 否 | `50` | 每页数量 |

#### `update_food_stock(food_id, stock) -> dict`

更新商品库存。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `food_id` | str | 是 | 商品 ID |
| `stock` | int | 是 | 库存数量 |

#### `sold_out_food(food_id) -> dict`

商品售罄（下架）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `food_id` | str | 是 | 商品 ID |

#### `on_sale_food(food_id) -> dict`

商品上架。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `food_id` | str | 是 | 商品 ID |

### 门店管理

#### `get_shop_info(shop_id) -> dict`

查询门店信息。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `shop_id` | str | 否 | 门店 ID（默认当前绑定门店） |

#### `update_shop_status(status, shop_id) -> dict`

更新门店营业状态。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `status` | int | 是 | 营业状态 (`1`=营业中, `0`=休息中) |
| `shop_id` | str | 否 | 门店 ID |

### 配送管理

#### `query_delivery_status(order_id) -> dict`

查询配送状态。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_id` | str | 是 | 订单 ID |

### 标准化数据总线

#### `to_order(raw, store_id, brand_id) -> OrderSchema`

将饿了么原始订单字段映射到标准 `OrderSchema`。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `raw` | dict | 是 | 饿了么原始订单数据 |
| `store_id` | str | 是 | 屯象门店 ID |
| `brand_id` | str | 是 | 屯象品牌 ID |

#### `close()`

关闭适配器，释放 HTTP 连接池。

---

## 字段映射

### 订单状态映射

| 饿了么状态码 | 说明 | 屯象 OrderStatus |
|-------------|------|-----------------|
| `0` | 待付款 | `PENDING` |
| `1` | 待接单 | `PENDING` |
| `2` | 已接单 | `CONFIRMED` |
| `3` | 配送中 | `CONFIRMED` |
| `4` | 已完成 | `COMPLETED` |
| `5` | 已取消 | `CANCELLED` |
| `9` | 退款中 | `CANCELLED` |

### 订单字段映射

| 饿了么字段 | 映射到 OrderSchema | 说明 |
|-----------|-------------------|------|
| `order_id` / `eleme_order_id` | `order_id` | 订单号 |
| `create_time` / `created_at` | `created_at` | 创建时间 |
| `total_price` / `order_amount` | `total` | 总额（元，除以100） |
| `discount_price` / `shop_discount` | `discount` | 折扣（元，除以100） |
| `food_list` / `items` | `items` | 订单明细 |
| `user_id` | `customer_id` | 用户 ID |
| `remark` / `caution` | `notes` | 备注 |

### 订单项字段映射（food_list/items 内）

| 饿了么字段 | 映射到 OrderItemSchema | 说明 |
|-----------|----------------------|------|
| `food_id` / `sku_id` | `dish_id` | 菜品 ID |
| `food_name` / `name` | `dish_name` | 菜品名称 |
| `price` | `unit_price` | 单价（元，除以100） |
| `quantity` / `count` | `quantity` | 数量 |
| `remark` | `special_requirements` | 特殊要求 |

---

## 错误码表

| 饿了么 code | 说明 | 处理策略 |
|------------|------|----------|
| `200` / `ok` | 成功 | 正常处理 |
| `400` | 参数错误 | 检查请求参数，不重试 |
| `401` | 认证失败（token 过期） | 自动刷新 token 后重试 |
| `403` | 无权限 | 检查 AppKey/AppSecret 配置 |
| `404` | 资源不存在 | 检查请求资源 ID |
| `429` | 调用频率超限 | 降速后重试 |
| `500` | 饿了么服务端错误 | 自动重试 |
| `1001` | 订单不存在 | 检查 order_id |
| `1002` | 订单状态不允许操作 | 检查订单当前状态 |
| `1003` | 菜品不存在 | 检查 food_id |
| `1004` | 门店不存在 | 检查 shop_id |
| `2001` | 库存不足 | 需业务方处理 |
| `2002` | 菜品已售罄 | 无需重复操作 |

---

## 错误处理

### 异常体系

| 异常 | 触发条件 | 说明 |
|------|----------|------|
| `ConnectionError` | 饿了么返回非 2xx HTTP 状态码 | 自动重试，401 时自动刷新 token |
| `httpx.ConnectError` | 网络不可达 | 自动重试（最多 `retry_times` 次） |
| `httpx.TimeoutException` | 请求超时 | 自动重试 |
| `ValueError` | 饿了么返回业务错误码 | 从 `_check_biz_error` 抛出，不重试 |
| `PermissionError` | token 获取失败 | 检查 app_key/app_secret 配置 |

### 重试策略

- 401 错误：自动清除 token 缓存，下次请求时重新获取
- HTTP 5xx/网络错误：重试最多 `retry_times` 次
- 业务错误码（如"订单不存在"）：不重试

### 日志关键点

| Logger Name | level | 触发场景 |
|-------------|-------|----------|
| `eleme_client_init` | INFO | Client 初始化 |
| `eleme_token_refreshed` | INFO | Token 刷新成功 |
| `eleme_token_http_error` | ERROR | Token 请求 HTTP 错误 |
| `eleme_http_error` | ERROR | API 请求 HTTP 错误 |
| `eleme_request_error` | ERROR | 网络/超时错误 |
| `eleme_client_closed` | INFO | Client 关闭 |
| `eleme.event_emit_failed` | WARNING | 事件发射失败（不阻断主流程） |

---

## 幂等性保障

`ElemeAdapter` 内置运行时幂等性检查：

```python
# 生成幂等键
key = adapter.idempotency_key("confirm_order", {"order_id": "xxx"})
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
| `SYNC_FINISHED` | `query_orders` | `orders` | `eleme:orders:{start}:{end}` |
| `SYNC_FINISHED` | `get_order_detail` | `order_detail` | `eleme:order:{order_id}` |
| `STATUS_PUSHED` | `confirm_order` | `order_confirm` | `eleme:order:confirm:{order_id}` |
| `STATUS_PUSHED` | `cancel_order` | `order_cancel` | `eleme:order:cancel:{order_id}` |
| `SYNC_FINISHED` | `query_refund` | `order_refund` | `eleme:refund:{order_id}` |
| `SYNC_FINISHED` | `query_foods` | `menu` | `eleme:foods:list` |
| `STATUS_PUSHED` | `update_food_stock` | `menu_stock` | `eleme:food:stock:{food_id}` |
| `STATUS_PUSHED` | `sold_out_food` | `menu_soldout` | `eleme:food:soldout:{food_id}` |
| `STATUS_PUSHED` | `on_sale_food` | `menu_onsale` | `eleme:food:onsale:{food_id}` |
| `SYNC_FINISHED` | `get_shop_info` | `shop_info` | `eleme:shop:{shop_id}` |
| `STATUS_PUSHED` | `update_shop_status` | `shop_status` | `eleme:shop:status:{shop_id}` |
| `SYNC_FINISHED` | `query_delivery_status` | `delivery_status` | `eleme:delivery:{order_id}` |

事件发射失败仅记录 WARNING，不阻断主业务流程。

---

## Webhook 处理

### ElemeWebhookHandler

处理饿了么开放平台推送的各类业务事件。

#### 初始化

```python
handler = ElemeWebhookHandler(app_secret="your_app_secret")
```

#### 签名验证

饿了么签名规则：`SHA256(app_secret + payload + timestamp + app_secret)`，取大写 hex。

```python
is_valid = handler.verify_signature(
    payload=raw_body_string,
    signature=request_headers["signature"],
    timestamp=request_headers["timestamp"],
)
```

签名验证包含时间戳防重放（容许偏差 300 秒）。

#### 注册事件处理器

```python
async def on_order_created(data: dict):
    print("新订单:", data)

handler.on("order.created", on_order_created)
```

#### 支持的事件类型

| 事件类型 | 说明 |
|----------|------|
| `order.created` | 新订单创建 |
| `order.paid` | 订单已支付 |
| `order.cancelled` | 订单已取消 |
| `order.refunded` | 订单已退款 |
| `delivery.status_changed` | 配送状态变更 |
| `food.stock_warning` | 库存预警 |

---

## 已知问题与注意事项

### 已知问题

1. **Token 无持久化**：`_access_token` 存储在内存中，进程重启后需要重新获取。Token 有效期通常为 24 小时，过期前 1 分钟自动刷新。
2. **幂等性内存存储**：`_nonce_store` 使用 `Set[str]` 而非 Redis，项目重启后去重状态丢失。多实例部署场景需改为共享存储。
3. **to_order 方法依赖网关 Schema**：`to_order` 方法通过动态 import 引入 `schemas.restaurant_standard_schema`，要求 `apps/api-gateway/src` 在 `sys.path` 中。如果模块结构变更，需相应调整 import 路径。

### 注意事项

1. **金额单位**：饿了么接口金额单位为**分**（整数）。`to_order` 映射方法会自动除以 100 转换为元。适配器接口参数均为元单位。
2. **订单状态映射**：饿了么订单状态码与屯象内部状态码不完全一致。`to_order` 方法中已定义映射表，添加新状态码时需同步更新。
3. **接单确认超时**：饿了么对商家接单确认有超时限制（通常 5 分钟），超时后订单自动取消。`confirm_order` 建议在收到新订单通知后尽快调用。
4. **401 自动刷新**：当 API 返回 401 时，客户端自动清除 token 缓存，下一次请求时重新获取。此过程在 `request` 方法内部透明处理。
5. **沙箱环境差异**：沙箱环境 URL 与生产环境不同，token 获取逻辑一致。沙箱订单数据不涉及真实资金。
6. **网络重试策略**：仅重试 HTTP 层面错误（连接/超时/5xx），业务错误码不重试。401 错误在重试时自动刷新 token。
7. **事件发射异常隔离**：`_emit_sync_event` 使用 `asyncio.create_task` 异步发射，不阻塞主流程。事件总线故障不影响接口调用。
8. **Webhook 兜底异常捕获**：`ElemeWebhookHandler.handle_event` 中使用 `except Exception` 包裹 handler 调用，确保单次 handler 异常不影响后续事件处理。

### 测试指南

```bash
# 运行单元测试
pytest shared/adapters/eleme/tests/ -v

# 覆盖率报告
pytest shared/adapters/eleme/tests/ --cov=shared.adapters.eleme.src --cov-report=term-missing
```

测试覆盖以下场景：
- 初始化（沙箱/生产环境配置）
- Access Token 缓存与过期刷新
- 幂等性键生成与去重
- 各业务方法成功路径
- 业务错误路径（饿了么 API 错误码）
- HTTP 错误路径（连接/超时/状态码错误）
- 事件发射（fire-and-forget）
- Webhook 签名验证与事件分发

---

## 版本兼容性

| 适配器版本 | 饿了么 API 版本 | 屯象 OS 版本 | 备注 |
|------------|---------------|-------------|------|
| v1.0 | 2024-06 | v0.9+ | 初始版本 |
| v1.1 | 2025-06 | v0.11+ | 增加事件发射 + 幂等性 |

---

## 参考链接

- [饿了么开放平台文档](https://open.shop.ele.me)
- [饿了么 API 文档](https://open.shop.ele.me/api-doc)
