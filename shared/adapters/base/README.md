# 适配器基础库 (shared/adapters/base)

所有第三方 POS/供应链/平台适配器的基类和通用工具。

## 核心组件

| 组件 | 路径 | 说明 |
|------|------|------|
| BaseAdapter | `src/adapter.py` | 抽象基类，所有适配器必须继承 |
| AdapterEventMixin | `src/event_bus.py` | 事件发射 Mixin，集成适配器同步事件 |
| emit_adapter_event | `src/event_bus.py` | 函数式适配器事件发射接口 |
| SyncTrack | `src/event_bus.py` | 同步追踪上下文管理器 |

## 快速开始

### 1. 创建适配器

```python
from shared.adapters.base.src.adapter import BaseAdapter
from shared.events.src.event_types import AdapterEventType
from shared.adapters.base.src.event_bus import AdapterEventMixin


class MyPOSAdapter(BaseAdapter, AdapterEventMixin):
    adapter_name = "my_pos"

    def __init__(self, config: dict):
        super().__init__(config)
        self.tenant_id = config.get("tenant_id")

    async def authenticate(self) -> dict[str, str]:
        # 实现认证逻辑
        return {"Authorization": f"Bearer {self.config['api_key']}"}

    def handle_error(self, response: dict) -> None:
        # 实现业务错误处理
        pass

    def to_order(self, raw: dict, store_id: str, brand_id: str):
        # 将 POS 原始订单映射为标准 OrderSchema
        pass

    def to_staff_action(self, raw: dict, store_id: str, brand_id: str):
        # 将 POS 原始操作映射为标准 StaffAction
        pass

    def idempotency_key(self, operation: str, payload: dict) -> str:
        # 生成幂等性密钥
        import hashlib, json
        raw = json.dumps({operation: payload}, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()
```

### 2. 发射同步事件

```python
import asyncio

async def sync_orders(adapter):
    async with adapter.track_sync(tenant_id=adapter.tenant_id, scope="orders") as track:
        orders = await adapter.fetch_orders()
        for o in orders:
            await adapter.pos_upload_order(o)
            track.ingested += 1
        # track_sync 自动发 SYNC_STARTED → SUCCESS/FAILED
```

## 适配器规范

所有适配器必须实现 BaseAdapter 的 5 个抽象方法：

| 方法 | 用途 | 返回值 |
|------|------|--------|
| `authenticate()` | 获取认证头 | `Dict[str, str]` |
| `handle_error(data)` | 处理业务错误响应 | None（异常抛出） |
| `to_order(raw, ...)` | 原始订单 → 标准 OrderSchema | `OrderSchema` |
| `to_staff_action(raw)` | 原始操作 → 标准 StaffAction | `StaffAction` |
| `idempotency_key(op, payload)` | 幂等性密钥生成 | `str` |

## 幂等性保障

BaseAdapter 内置幂等性支持：

```python
# 在写入方法中检查重复
key = adapter.idempotency_key("upload_order", order_data)
if adapter.is_duplicate(key):
    logger.info("跳过重复请求", key=key)
    return {"success": True, "message": "duplicate"}

adapter.mark_idempotent(key)
# ...处理业务逻辑...
```

`_idempotency_store` 是一个内存 `Set[str]`，用于运行时去重。生产环境
建议结合数据库唯一约束或 Redis 持久化。

## 配置参考

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `ADAPTER_DEFAULT_TIMEOUT` | 30 | HTTP 请求超时（秒） |
| `ADAPTER_DEFAULT_RETRY_TIMES` | 3 | 最大重试次数 |
| `ADAPTER_RETRY_ATTEMPTS` | 3 | tenacity 重试次数 |
| `ADAPTER_RETRY_MULTIPLIER` | 1 | 指数退避乘数 |
| `ADAPTER_RETRY_MIN` | 2 | 最小退避（秒） |
| `ADAPTER_RETRY_MAX` | 10 | 最大退避（秒） |

配置通过 `BaseAdapter.__init__(config)` 注入，config 字典优先级高于环境变量。

## 事件约定

适配器通过 `emit_adapter_event()` 或 `AdapterEventMixin` 发射异步事件：

```python
asyncio.create_task(emit_adapter_event(
    adapter_name="my_adapter",
    event_type=AdapterEventType.MENU_SYNCED,
    tenant_id=tenant_id,
    scope="menu",
    stream_id="my_adapter:menu",
))
```

### 可发射的事件类型

| 事件 | 触发场景 |
|------|----------|
| `SYNC_STARTED` | 同步开始 |
| `SYNC_FINISHED` | 同步成功结束 |
| `SYNC_FAILED` | 同步失败 |
| `ORDER_INGESTED` | 订单写入完成 |
| `MENU_SYNCED` | 菜单/菜品同步 |
| `MEMBER_SYNCED` | 会员信息同步 |
| `INVENTORY_SYNCED` | 库存同步 |
| `STATUS_PUSHED` | 状态推送 |
| `WEBHOOK_RECEIVED` | 三方 Webhook 回调 |
| `RECONNECTED` | 长时故障后恢复 |
| `CREDENTIAL_EXPIRED` | Token/密钥过期 |

见 `shared.events.src.event_types.AdapterEventType` 获取完整事件类型列表。

## 错误处理

BaseAdapter 提供统一的请求重试和超时机制：

```python
try:
    result = await adapter.request("POST", "/api/order", data=order)
except APIError as e:
    logger.error("API 调用失败", code=e.code, system=e.system)
    # code >= 400 时自动抛 APIError
```

- `tenacity` 指数退避自动重试可恢复错误
- 所有 HTTP 状态码 >= 400 统一转为 `APIError`
- `handle_error()` 处理业务层错误响应
