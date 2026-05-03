# 客如云 API 适配器

对接客如云餐饮管理系统开放平台 API，覆盖订单、菜品、会员、报表等核心业务。
适用于 POS 收银数据同步与门店运营管理。

## 目录

1. [配置说明](#配置说明)
2. [快速开始](#快速开始)
3. [API 方法](#api-方法)
4. [字段映射](#字段映射)
5. [错误处理](#错误处理)
6. [幂等性保障](#幂等性保障)
7. [事件发射](#事件发射)
8. [已知问题与注意事项](#已知问题与注意事项)

---

## 配置说明

### 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `KERUYUN_CLIENT_ID` | 是 | — | 客如云 API Client ID |
| `KERUYUN_CLIENT_SECRET` | 是 | — | 客如云 API Client Secret |
| `KERUYUN_BASE_URL` | 否 | `https://api.keruyun.com` | API 基础 URL |
| `KERUYUN_STORE_ID` | 否 | — | 默认门店 ID |
| `KERUYUN_TENANT_ID` | 否 | — | 屯象租户 ID（事件发射用） |

### 构造函数参数

`KeruyunAdapter.__init__(config)` 接受一个字典：

| 键 | 必填 | 类型 | 默认值 | 说明 |
|-------|------|------|--------|------|
| `client_id` | 是 | str | — | 客如云 Client ID |
| `client_secret` | 是 | str | — | 客如云 Client Secret |
| `base_url` | 否 | str | `https://api.keruyun.com` | API 基础 URL |
| `store_id` | 否 | str | — | 默认门店 ID |
| `tenant_id` | 否 | str | `""` | 屯象租户 ID（事件发射用） |
| `timeout` | 否 | int | `30` | 请求超时（秒） |
| `retry_times` | 否 | int | `3` | 失败重试次数 |

---

## 快速开始

```python
import asyncio
from shared.adapters.keruyun.src.adapter import KeruyunAdapter

async def main():
    adapter = KeruyunAdapter({
        "client_id": "your_client_id",
        "client_secret": "your_client_secret",
        "store_id": "STORE_001",
        "tenant_id": "tenant_uuid",
    })

    # 查询订单
    order = await adapter.query_order(order_sn="KR20240301001")
    print("订单:", order)

    # 更新订单状态（3=已结账）
    result = await adapter.update_order_status(order_id="KR_001", status=3)
    print("更新结果:", result)

    # 查询会员
    member = await adapter.query_member(mobile="13800138000")
    print("会员:", member)

    await adapter.close()

asyncio.run(main())
```

### 标准化映射

```python
raw_order = {
    "order_id": "KR_20240301_001",
    "status": 3,
    "total_amount": 24600,
    "items": [{"sku_id": "SKU_001", "sku_name": "夫妻肺片", "qty": 1, "unit_price": 15800}],
}
order_schema = adapter.to_order(raw_order, store_id="STORE_KR1", brand_id="BRAND_001")
print(order_schema.order_status)  # OrderStatus.COMPLETED
print(order_schema.total)         # Decimal('246.00')
```

---

## API 方法

### KeruyunAdapter

#### 订单管理

##### `query_order(order_id, order_sn, start_time, end_time) -> dict`

查询订单信息。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_id` | str | 否 | 订单 ID |
| `order_sn` | str | 否 | 订单编号 |
| `start_time` | str | 否 | 起始时间（ISO） |
| `end_time` | str | 否 | 结束时间（ISO） |

返回响应 `data` 字段。

##### `update_order_status(order_id, status) -> dict`

更新订单状态。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_id` | str | 是 | 订单 ID |
| `status` | int | 是 | 状态值（1=待确认, 2=服务中, 3=已结账, 4=已取消） |

#### 菜品管理

##### `query_dish(sku_id, category_id) -> list`

查询菜品信息。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sku_id` | str | 否 | SKU ID |
| `category_id` | str | 否 | 分类 ID |

返回菜品列表。

##### `update_dish_status(sku_id, is_sold_out) -> dict`

更新菜品售罄状态。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sku_id` | str | 是 | SKU ID |
| `is_sold_out` | int | 是 | 1=售罄, 0=正常 |

#### 会员管理

##### `query_member(member_id, mobile) -> dict`

查询会员信息。`member_id` 和 `mobile` 至少填写一个。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `member_id` | str | 否 | 会员 ID |
| `mobile` | str | 否 | 手机号 |

#### 报表

##### `query_revenue_report(date) -> dict`

查询日营收报表。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `date` | str | 是 | 日期（如 `"2026-03-01"`） |

### 标准化数据映射

##### `to_order(raw, store_id, brand_id) -> OrderSchema`

将客如云原始订单映射为统一 OrderSchema。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `raw` | dict | 是 | 客如云原始订单数据 |
| `store_id` | str | 是 | 屯象门店 ID |
| `brand_id` | str | 是 | 屯象品牌 ID |

##### `to_staff_action(raw, store_id, brand_id) -> StaffAction`

将客如云操作日志映射为统一 StaffAction。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `raw` | dict | 是 | 客如云原始操作日志 |
| `store_id` | str | 是 | 屯象门店 ID |
| `brand_id` | str | 是 | 屯象品牌 ID |

---

## 字段映射

### 订单状态映射

| 客如云 status | OrderStatus | 说明 |
|---------------|-------------|------|
| `1` | `PENDING` | 待确认 |
| `2` | `CONFIRMED` | 服务中 |
| `3` | `COMPLETED` | 已结账 |
| `4` | `CANCELLED` | 已取消 |
| 其他 | `PENDING` | 默认降级 |

### 订单字段映射

| 客如云字段 | OrderSchema 字段 | 说明 |
|------------|------------------|------|
| `order_id` | `order_id` | 订单 ID |
| `order_sn` | `order_number` | 订单编号 |
| `store_id` | — | 映射到参数 `store_id` |
| `table_name` | `table_number` | 桌号（回退到 `table_id`） |
| `status` | `order_status` | 见状态映射表 |
| `total_amount` | `total` | 分转元（÷100） |
| `discount_amount` | `discount` | 分转元（÷100） |
| `create_time` | `created_at` | ISO 时间或 Unix 时间戳 |
| `member_id` | `customer_id` | 会员 ID |
| `waiter_id` | `waiter_id` | 服务员 ID |
| `note` | `notes` | 备注 |

### 订单项字段映射

| 客如云字段 | OrderItemSchema 字段 | 说明 |
|------------|----------------------|------|
| `item_id` | `item_id` | 明细 ID |
| `sku_id` | `dish_id` | 菜品 ID |
| `sku_name` | `dish_name` | 菜品名称 |
| `qty` / `quantity` | `quantity` | 数量 |
| `unit_price` | `unit_price` | 单价，分转元（÷100） |
| `note` | `special_requirements` | 特殊要求 |

### 操作日志字段映射

| 客如云字段 | StaffAction 字段 | 说明 |
|------------|------------------|------|
| `action_type` / `type` | `action_type` | 操作类型 |
| `staff_id` / `operator_id` | `operator_id` | 操作员 ID |
| `amount` | `amount` | 金额，分转元（÷100） |
| `reason` | `reason` | 原因 |
| `approved_by` | `approved_by` | 审批人 |
| `operate_time` / `create_time` | `created_at` | 操作时间 |

---

## 错误处理

### 错误码对照表

| code | 说明 | 处理策略 |
|------|------|----------|
| `0` / `200` / `"success"` | 成功 | 正常处理 |
| 其他 | 业务错误 | 抛出 `Exception("客如云API错误 [{code}]: {message}")` |

### 异常体系

| 异常 | 触发条件 | 说明 |
|------|----------|------|
| `ValueError` | 缺少 client_id/client_secret | 初始化参数校验 |
| `httpx.HTTPStatusError` | 非 2xx 响应 | 自动重试最多 3 次 |
| `httpx.ConnectError` | 网络不可达 | 自动重试最多 3 次 |
| `httpx.TimeoutException` | 请求超时 | 自动重试最多 3 次 |
| `httpx.DecodingError` | 响应解码失败 | 自动重试最多 3 次 |
| `RuntimeError` | 重试耗尽 | 达到最大重试次数后抛出 |

### 日志关键点

| Logger | level | 触发场景 |
|--------|-------|----------|
| `客如云适配器初始化` | INFO | 适配器创建 |
| `查询订单` | INFO | 调用 query_order |
| `更新订单状态` | INFO | 调用 update_order_status |
| `HTTP请求失败` | ERROR | 网络层错误 |
| `请求异常` | ERROR | 连接/超时/解码错误 |
| `keruyun.event_emit_failed` | WARNING | 事件发射失败（不阻断主流程） |

---

## 幂等性保障

`KeruyunAdapter` 内置运行时幂等性检查：

```python
# 生成幂等键
key = adapter.idempotency_key("update_status", {"order_id": "001", "status": 3})
# key 基于 operation + tenant_id + payload 的 MD5 哈希

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
| `STATUS_PUSHED` | `update_order_status` | `order_status` | `keruyun:order:{order_id}` |
| `STATUS_PUSHED` | `update_dish_status` | `dish_status` | `keruyun:dish:{sku_id}` |

事件发射失败仅记录 WARNING，不阻断主业务流程。

---

## 已知问题与注意事项

### 已知问题

1. **签名算法要求**：客如云签名按 `client_id + sorted_params + client_secret` 拼接后 MD5，需确保参数排序一致。
2. **幂等性内存存储**：`_nonce_store` 使用 `Set[str]` 而非 Redis，项目重启后去重状态丢失。多实例部署场景需改为共享存储。
3. **金额单位为分**：所有金额字段使用整数（分），`to_order()` 和 `to_staff_action()` 会自动转换为元。
4. **schemas 导入依赖**：`to_order()` 和 `to_staff_action()` 依赖 `schemas.restaurant_standard_schema`，该模块位于 `apps/api-gateway/src`。使用前需确保该路径在 Python 路径中。

### 注意事项

1. **请求重试策略**：指数退避仅在网络层错误（连接/超时/解码）时重试，业务错误码直接抛出，不重试。
2. **HTTP 客户端复用**：`__init__` 中创建 `httpx.AsyncClient`，使用完毕后调用 `close()` 释放连接。
3. **并发控制**：`authenticate()` 方法不涉及 token 刷新，无并发问题。
4. **事件发射异常隔离**：`_emit_sync_event` 使用 fire-and-forget 模式，事件总线故障不影响主业务逻辑。

### 测试指南

```bash
# 运行单元测试
pytest shared/adapters/keruyun/tests/ -v

# 覆盖率报告
pytest shared/adapters/keruyun/tests/ --cov=shared.adapters.keruyun.src --cov-report=term-missing
```

测试覆盖以下场景：
- 适配器初始化与参数校验
- `to_order()` 订单映射（含状态、金额、时间、空列表）
- `to_staff_action()` 操作日志映射（含金额换算、空值）
- 幂等性键生成与去重
- 事件发射（update_order_status / update_dish_status）
