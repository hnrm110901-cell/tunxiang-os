# 微生活会员管理平台适配器

对接微生活（i200.cn）会员管理系统开放平台 API，覆盖会员查询、列表同步、交易记录、积分储值与门店管理。
适用于连锁餐饮企业会员数据同步与运营管理。

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
| `WSH_BASE_URL` | 否 | `https://open.i200.cn` | API 基础 URL |
| `WSH_APPID` | 是 | — | 应用 ID |
| `WSH_APP_SECRET` | 是 | — | 应用密钥（仅用于获取 token，不随业务请求发送） |
| `WSH_TIMEOUT` | 否 | `30` | 请求超时（秒） |
| `WSH_RETRY_TIMES` | 否 | `3` | 失败重试次数 |
| `WSH_TENANT_ID` | 否 | — | 屯象租户 ID（事件发射用） |

### 构造函数参数

`WeishenghuoAdapter.__init__(config)` 接受一个字典：

| 键 | 必填 | 类型 | 默认值 | 说明 |
|-------|------|------|--------|------|
| `base_url` | 否 | str | `https://open.i200.cn` | API 基础 URL |
| `appid` | 是 | str | — | 应用 ID |
| `app_secret` | 是 | str | — | 应用密钥 |
| `timeout` | 否 | int | `30` | 请求超时（秒） |
| `retry_times` | 否 | int | `3` | 失败重试次数 |
| `tenant_id` | 否 | str | `""` | 屯象租户 ID（事件发射用） |

---

## 快速开始

```python
import asyncio
from src.adapter import WeishenghuoAdapter

async def main():
    adapter = WeishenghuoAdapter({
        "appid": "your_appid",
        "app_secret": "your_secret",
        "tenant_id": "tenant_uuid",
    })

    # 查询会员
    member = await adapter.get_member_info(mobile="13800138000")
    print("会员:", member)

    # 分页拉取会员列表（增量同步）
    members = await adapter.list_members(page=1, page_size=100, updated_after="2026-03-01")
    print("会员数:", members["total"])

    # 查询交易记录
    tx = await adapter.get_member_transactions(
        member_id="M001",
        start_date="2026-03-01",
        end_date="2026-03-17",
    )
    print("交易数:", tx["total"])

    await adapter.aclose()

asyncio.run(main())
```

---

## API 方法

### WeishenghuoAdapter

#### 认证机制

适配器使用 `appid + app_secret` 获取 `access_token`（POST `/auth/token`），
Token 在内存中缓存（7200 秒有效，提前 60 秒自动刷新），
过期后自动重新获取，调用方无需关心 Token 生命周期。

#### `get_member_info(mobile, member_id) -> dict`

获取会员详情（积分、余额、等级、卡号等）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `mobile` | str | 否 | 手机号 |
| `member_id` | str | 否 | 会员 ID |

`mobile` 与 `member_id` 至少填写一个。

返回会员信息字典，包含 `member_id` / `mobile` / `points` / `balance` / `level` / `card_no` 等字段。
查询失败时返回空字典 `{}`。

#### `list_members(page, page_size, updated_after) -> dict`

分页拉取会员列表，支持增量同步。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `page` | int | 否 | 页码，从 1 开始（默认 1） |
| `page_size` | int | 否 | 每页条数，最大 100（默认 100） |
| `updated_after` | str | 否 | 增量同步起始时间（ISO 格式，如 `"2026-03-01"`） |

返回结构：
```json
{
    "list": [{"member_id": "M001", ...}],
    "total": 150,
    "page": 1,
    "page_size": 100
}
```

拉取失败时返回 `{"list": [], "total": 0, "page": 1, "page_size": 100}`。

#### `get_member_transactions(member_id, start_date, end_date, page) -> dict`

查询会员交易记录。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `member_id` | str | 是 | 会员 ID |
| `start_date` | str | 是 | 起始日期（如 `"2026-03-01"`） |
| `end_date` | str | 是 | 结束日期（如 `"2026-03-17"`） |
| `page` | int | 否 | 页码，从 1 开始（默认 1） |

金额字段单位为**分（fen）**，调用方按需转换为元。
查询失败时返回 `{"list": [], "total": 0, "page": 1}`。

#### `get_member_points(member_id) -> dict`

查询会员积分余额及变动历史。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `member_id` | str | 是 | 会员 ID |

返回结构：
```json
{
    "balance": 2500,
    "history": []
}
```

`balance` 为当前可用积分。查询失败时返回 `{"balance": 0, "history": []}`。

#### `get_member_stored_value(member_id) -> dict`

查询会员储值余额。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `member_id` | str | 是 | 会员 ID |

返回结构：
```json
{
    "balance": 100000
}
```

`balance` 单位为**分（fen）**（如 `100000` 分 = 1000 元）。
查询失败时返回 `{"balance": 0}`。

#### `get_shop_list() -> list`

获取当前账号下所有门店列表。

返回门店列表：
```json
[
    {"shop_id": "S001", "shop_name": "朝阳门店"},
    {"shop_id": "S002", "shop_name": "海淀门店"}
]
```

API 可能返回 `{"list": [...]}` 或直接返回列表格式，适配器自动处理两种格式。
查询失败时返回 `[]`。

---

## 字段映射

### 响应字段映射

微生活 API 统一响应格式：`{"errcode": 0, "errmsg": "ok", "data": {...}}`
适配器 `_request` 方法自动解包 `data` 字段返回。

#### 会员信息字段

| 微生活字段 | 类型 | 说明 |
|-----------|------|------|
| `member_id` | string | 会员 ID |
| `mobile` | string | 手机号 |
| `points` | number | 当前积分 |
| `balance` | number | 储值余额（分） |
| `level` | string | 会员等级（如 "金卡"） |
| `card_no` | string | 会员卡号 |

#### 交易记录字段

| 微生活字段 | 类型 | 说明 |
|-----------|------|------|
| `tx_id` | string | 交易 ID |
| `amount` | number | 金额（分） |
| `type` | string | 交易类型（`consume` / `recharge` 等） |
| `create_time` | string | 交易时间 |

#### 门店字段

| 微生活字段 | 类型 | 说明 |
|-----------|------|------|
| `shop_id` | string | 门店 ID |
| `shop_name` | string | 门店名称 |

---

## 错误处理

### 错误码对照表

| errcode | 说明 | 处理策略 |
|---------|------|----------|
| `0` | 成功 | 正常处理 |
| 非 `0` | 业务错误 | 抛出 `Exception("微生活业务错误 [errcode=N]: {errmsg}")` |

### 异常体系

| 异常 | 触发条件 | 说明 |
|------|----------|------|
| `ValueError` | `get_member_info` 未传 mobile 和 member_id | 参数校验 |
| `Exception` | Token 获取失败（errcode != 0） | `"微生活获取 token 失败"` |
| `Exception` | 业务请求失败（errcode != 0） | `"微生活业务错误"`，不重试 |
| `httpx.ConnectError` | 网络不可达 | 自动重试（指数退避） |
| `httpx.TimeoutException` | 请求超时 | 自动重试（指数退避） |
| `httpx.DecodingError` | 响应解码失败 | 自动重试（指数退避） |
| `RuntimeError` | 重试耗尽 | 达到最大重试次数后抛出 |

### 降级策略

所有业务接口（`get_member_info` / `list_members` / `get_member_transactions` 等）
在请求失败时**返回默认值**而非抛出异常，确保调用方不会因微生活不可用而崩溃：

| 接口 | 降级返回值 |
|------|-----------|
| `get_member_info` | `{}` |
| `list_members` | `{"list": [], "total": 0, "page": N, "page_size": N}` |
| `get_member_transactions` | `{"list": [], "total": 0, "page": N}` |
| `get_member_points` | `{"balance": 0, "history": []}` |
| `get_member_stored_value` | `{"balance": 0}` |
| `get_shop_list` | `[]` |

### 日志关键点

| Logger Name | level | 触发场景 |
|-------------|-------|----------|
| `微生活适配器初始化` | INFO | 适配器创建 |
| `微生活获取 access_token` | INFO | Token 获取 |
| `微生活 access_token 获取成功` | INFO | Token 获取成功 |
| `微生活请求失败，准备重试` | WARNING | 网络层错误，即将重试 |
| `微生活请求失败，已重试 N 次` | ERROR | 重试耗尽 |
| `获取微生活会员信息失败` | WARNING | 会员查询失败（降级返回） |
| `拉取微生活会员列表失败` | WARNING | 列表拉取失败（降级返回） |
| `weishenghuo.event_emit_failed` | WARNING | 事件发射失败（不阻断主流程） |

---

## 幂等性保障

`WeishenghuoAdapter` 内置运行时幂等性检查：

```python
# 生成幂等键
key = adapter.idempotency_key("query_member", {"mobile": "13800138000"})
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
| `MEMBER_SYNCED` | `get_member_info` 成功 | `member_info` | `weishenghuo:member:{member_id\|mobile}` |
| `MEMBER_SYNCED` | `list_members` 成功 | `member_list` | `weishenghuo:member_list:{page}` |
| `SYNC_FINISHED` | `get_member_transactions` 成功 | `member_transactions` | `weishenghuo:transactions:{member_id}` |
| `SYNC_FINISHED` | `get_member_points` 成功 | `member_points` | `weishenghuo:points:{member_id}` |
| `SYNC_FINISHED` | `get_member_stored_value` 成功 | `member_stored_value` | `weishenghuo:stored_value:{member_id}` |
| `SYNC_FINISHED` | `get_shop_list` 成功 | `shop_list` | `weishenghuo:shop_list` |

事件发射失败仅记录 WARNING，不阻断主业务流程。

---

## 已知问题与注意事项

### 已知问题

1. **Token 无并发保护**：`_get_access_token` 在高并发场景下可能被多个协程同时调用，导致多个 token 请求并发发出。建议加锁保护或使用独立 token 管理服务。
2. **幂等性内存存储**：`_nonce_store` 使用 `Set[str]` 而非 Redis，项目重启后去重状态丢失。多实例部署场景需改为共享存储。
3. **金额单位为分**：`balance`（储值）和 `amount`（交易金额）均为整数分，调用方需自行转换为元（÷100）。
4. **积分与储值是独立接口**：`get_member_info` 返回的 `points` / `balance` 可能与专用接口（`get_member_points` / `get_member_stored_value`）存在短暂不一致，以专用接口为准。
5. **appid/app_secret 缺失时不报错**：初始化时 appid/app_secret 缺失仅记录 WARNING 日志，不会阻塞适配器创建。但后续所有 API 调用将失败。

### 注意事项

1. **请求重试策略**：指数退避（0.5s x 2^n），仅重试网络层错误（连接/超时/解码），业务错误码（errcode != 0）直接抛出，不重试。
2. **HTTP 客户端复用**：`__init__` 中创建 `httpx.AsyncClient`，使用完毕后调用 `aclose()` 释放连接。
3. **TLS 与代理**：`httpx.AsyncClient` 默认不配置代理，在内网环境需通过环境变量 `HTTP_PROXY` / `HTTPS_PROXY` 指定。
4. **Token 缓存隔离**：每个适配器实例维护独立的 Token 缓存，多租户场景下需创建多个适配器实例。
5. **事件发射异常隔离**：`_emit_sync_event` 使用 `asyncio.create_task` 异步发射，不阻塞主流程。事件总线故障不影响会员数据查询。
6. **时间格式**：`updated_after` 参数使用 ISO 8601 日期格式（`"YYYY-MM-DD"`），不包含时间部分。

### 测试指南

```bash
# 运行单元测试
pytest shared/adapters/weishenghuo/tests/ -v

# 覆盖率报告
pytest shared/adapters/weishenghuo/tests/ --cov=shared.adapters.weishenghuo.src --cov-report=term-missing
```

测试覆盖以下场景：
- Token 获取与缓存机制（首次获取 / 缓存命中 / 过期刷新 / 获取失败）
- 会员信息查询（手机号 / 会员 ID / 参数校验 / 降级返回）
- 会员列表分页与增量同步（page_size 上限限制 / 降级返回）
- 交易记录查询（正常返回 / 降级返回）
- 积分与储值查询（正常返回 / 降级返回）
- 门店列表查询（dict 格式 / list 格式 / 降级返回）
- 请求重试逻辑（失败重试 / 重试耗尽 / 业务错误不重试）
- 适配器初始化（正常配置 / 缺失凭证 / 默认值）
- 幂等性保障（确定性键生成 / 重复检测 / 标记）
- 事件发射（6 个业务接口的事件触发 / 失败不阻断）

---

## 版本兼容性

| 适配器版本 | 微生活 API | 屯象 OS 版本 | 备注 |
|------------|-----------|-------------|------|
| v1.0 | 2025 | v0.9+ | 初始版本 |
| v1.1 | 2025 | v0.11+ | 增加事件发射 + 幂等性 + 全面降级策略 |

---

## 参考链接

- [微生活开放平台](https://open.i200.cn)
- [微生活 API 文档](https://open.i200.cn/doc)
