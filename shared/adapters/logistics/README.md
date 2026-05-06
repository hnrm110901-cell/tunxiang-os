# 物流适配器 — Kuaidi100

快递100开放平台集成，提供快递单号识别、物流轨迹查询和状态订阅能力。

## 配置说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| tenant_id | str | 是 | 租户 UUID |
| customer | str | 是 | 快递100 分配的 customer |
| key | str | 是 | 快递100 分配的 key（用于签名） |

## 快速开始

```python
from shared.adapters.logistics.src.adapter import LogisticsAdapter

adapter = LogisticsAdapter(
    tenant_id="your-tenant-uuid",
    customer="your-customer",
    key="your-key",
)

# 查询物流轨迹
track = await adapter.query_track("SF1234567890", "shunfeng")
print(track["state"], track["traces"])

# 自动识别快递公司
detect = await adapter.auto_detect("SF1234567890")
print(detect["carrier_code"], detect["carrier_name"])

# 订阅物流状态推送
sub = await adapter.subscribe_push(
    "SF1234567890", "shunfeng", "https://your-api.com/callback"
)

await adapter.close()
```

## API 方法

### query_track(tracking_no, carrier_code="")

查询物流轨迹。

- `tracking_no` (str): 快递单号
- `carrier_code` (str, optional): 快递公司编码（如 shunfeng, zhongtong）。为空时自动识别。

返回:
```json
{
    "status": "ok",
    "state": "3",
    "carrier_code": "shunfeng",
    "tracking_no": "SF1234567890",
    "traces": [
        {"time": "2026-04-01 08:00:00", "context": "包裹已揽收"}
    ]
}
```

state 取值: 0-在途 1-揽收 2-疑难 3-签收 4-退签 5-派件 6-退回 7-转投

### auto_detect(tracking_no)

自动识别快递公司。

返回:
```json
{"carrier_code": "zhongtong", "carrier_name": "中通快递"}
```

### subscribe_push(tracking_no, carrier_code, callback_url)

订阅物流状态变更推送。

返回:
```json
{"status": "ok", "subscribed": true}
```

## 错误码表

| 错误码 | 说明 |
|--------|------|
| E_QUERY_FAILED | 查询轨迹失败（网络/API 错误） |
| E_AUTO_DETECT_FAILED | 自动识别失败 |
| E_SUBSCRIBE_FAILED | 订阅推送失败 |
| E_UNKNOWN | 未知错误 |

所有错误抛出 `LogisticsAPIError` 异常，包含 `code`、`method` 和 `message` 字段。

## 幂等性

适配器对每个操作方法（query_track、auto_detect、subscribe_push）基于参数组合生成 SHA256 幂等键。相同参数的重复请求会被跳过，返回 `{"duplicate": true}`。

进程内幂等键存储在 `_nonce_store`（set），生产环境建议替换为 Redis。

## 事件发射

每次成功操作后会旁路发射以下事件（使用 `asyncio.create_task`，不阻塞调用方）：

| 事件类型 | 触发条件 |
|----------|----------|
| logistics.track_queried | query_track 成功 |
| logistics.auto_detected | auto_detect 成功 |
| logistics.subscribed | subscribe_push 成功 |

事件通过 `shared.events.src.emitter.emit_event` 写入 Redis Stream 和 PG events 表。

## 注意事项

- **API 限频**: 快递100免费版有调用频率限制，建议在 query_track 前先调 auto_detect（如不确定快递公司），避免不必要的重复查询。
- **订阅回调**: subscribe_push 的 callback_url 必须公网可达，快递100会在物流状态变更时 POST 回调。
- **幂等性**: 进程内 set 仅适用于单进程部署。多进程/多实例场景需使用 Redis 等共享存储。
- **金额单位**: 不涉及金额字段。

## 测试指南

```bash
# 运行单元测试
cd tunxiang-os
python -m pytest shared/adapters/logistics/tests/test_adapter.py -v

# 覆盖报告
python -m pytest shared/adapters/logistics/tests/test_adapter.py -v --cov=shared.adapters.logistics.src.adapter
```

测试通过 mock `Kuaidi100Client` 避免真实 HTTP 调用，覆盖场景包括：
- 各方法的成功路径
- 幂等性跳过（相同参数重复调用）
- 不同参数不被幂等跳过
- API 错误异常抛出
- `idempotency_key` 稳定性
- `close` 清理

## 依赖

- Python 3.10+
- httpx（生产环境需替换 TODO 注释的 mock 实现）
- shared.events（事件发射）
