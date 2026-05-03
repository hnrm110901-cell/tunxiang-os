# 小红书适配器

小红书开放平台集成，提供团购券核销、POI 门店同步、评论采集和 Webhook 签名验证能力。

## 配置说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| tenant_id | str | 是 | 租户 UUID |
| app_id | str | 是 | 小红书开放平台分配的 App ID |
| app_secret | str | 是 | 小红书开放平台分配的 App Secret |

## 快速开始

```python
from shared.adapters.xiaohongshu.src.adapter import XiaohongshuAdapter

adapter = XiaohongshuAdapter(
    tenant_id="your-tenant-uuid",
    app_id="your-app-id",
    app_secret="your-app-secret",
)

# 核销团购券
result = await adapter.verify_coupon(
    coupon_data={
        "coupon_code": "XHS123",
        "store_id": "store-uuid",
        "order_id": "order-uuid",
        "verified_by": "cashier-uuid",
    },
    tenant_id="your-tenant-uuid",
    db=db_session,
)

# 同步门店到小红书 POI
result = await adapter.sync_poi(
    store_data={
        "store_id": "store-uuid",
        "xhs_poi_id": "poi-id",
        "name": "测试门店",
        "address": "长沙市...",
    },
    tenant_id="your-tenant-uuid",
    db=db_session,
)

# 采集门店评论
reviews = await adapter.query_reviews(
    note_id="store-uuid",
    tenant_id="your-tenant-uuid",
    db=db_session,
)

await adapter.close()
```

## API 方法

### verify_coupon(coupon_data, tenant_id, db)

核销小红书团购券。

- `coupon_data` (dict): 包含以下键：
  - `coupon_code` (str): 券码
  - `store_id` (str): 门店 UUID
  - `order_id` (str, optional): 关联订单
  - `verified_by` (str, optional): 操作员 UUID
- `tenant_id` (str): 租户 UUID
- `db` (AsyncSession): SQLAlchemy 异步会话

返回:
```json
{
    "verified": true,
    "record_id": "uuid",
    "coupon_code": "XHS123",
    "coupon_info": {"type": "group_buy", "paid_fen": 5000}
}
```

### sync_poi(store_data, tenant_id, db)

同步门店信息到小红书 POI。

- `store_data` (dict): 包含以下键：
  - `store_id` (str): 门店 UUID
  - `xhs_poi_id` (str, optional): 小红书 POI ID（首次绑定时必填）
  - `name` / `address` / `phone` / `business_hours`: 门店信息
- `tenant_id` (str): 租户 UUID
- `db` (AsyncSession): SQLAlchemy 异步会话

返回:
```json
{"action": "created", "mapping_id": "uuid", "store_id": "uuid", "xhs_poi_id": "poi-id"}
```

### query_reviews(note_id, tenant_id, db)

采集门店关联的小红书笔记和评论。

- `note_id` (str): 门店 UUID（参数名兼容评分卡）
- `tenant_id` (str): 租户 UUID
- `db` (AsyncSession): SQLAlchemy 异步会话

返回:
```json
{
    "store_id": "uuid",
    "notes_count": 5,
    "comments_count": 20,
    "reviews": [
        {"source": "xiaohongshu", "note_id": "...", "title": "...", "content": "...", ...}
    ]
}
```

## OAuth 流程说明

小红书使用 OAuth 2.0 授权，流程如下：

1. 用户在浏览器中完成小红书授权（获取 authorization_code）
2. 调用 `XhsOAuthTokenService.exchange_code_for_token(code=...)` 换取 TokenPair
3. TokenPair 包含 access_token 和 refresh_token，access_token 有效期 2 小时
4. 通过 `ensure_fresh_token(pair)` 自动在到期前刷新
5. 连续 3 次 401 错误会标记为过期，需重新授权

详见 `oauth_token_service.py`。

## Webhook 签名验证

小红书核销回调会携带 `X-Xhs-Signature`、`X-Xhs-Timestamp`、`X-Xhs-Nonce` 三个 header。
使用 `webhook_signature.py` 验证：

```python
from shared.adapters.xiaohongshu.src.webhook_signature import (
    verify_signature, extract_xhs_headers
)

headers = extract_xhs_headers(request.headers)
result = verify_signature(
    secret=webhook_secret,
    signature=headers["signature"],
    timestamp=headers["timestamp"],
    nonce=headers["nonce"],
    body=await request.body(),
)
if not result.ok:
    raise HTTPException(400, result.error_message)
```

## 错误码表

| 错误码 | 说明 |
|--------|------|
| E_COUPON_VERIFY_FAILED | 团购券核销失败（网络/API 错误） |
| E_POI_BIND_FAILED | POI 门店绑定失败 |
| E_POI_SYNC_FAILED | POI 信息同步失败 |
| E_REVIEW_CRAWL_FAILED | 评论采集失败 |
| E_UNKNOWN | 未知错误 |

所有错误抛出 `XiaohongshuAPIError` 异常，包含 `code`、`method` 和 `message` 字段。

## 幂等性

适配器对每个操作方法基于参数组合生成 SHA256 幂等键。相同参数的重复请求会被跳过，返回 `{"duplicate": true}`。核销操作特别注意防止重复核销同一券码。

进程内幂等键存储在 `_nonce_store`（set），生产环境建议替换为 Redis。

## 事件发射

每次成功操作后会旁路发射以下事件（使用 `asyncio.create_task`，不阻塞调用方）：

| 事件类型 | 触发条件 |
|----------|----------|
| coupon.verified | verify_coupon 成功 |
| poi.synced | sync_poi 成功 |
| review.crawled | query_reviews 成功 |

事件通过 `shared.events.src.emitter.emit_event` 写入 Redis Stream 和 PG events 表。

## 注意事项

- **OAuth 有效期**: access_token 2 小时过期，refresh_token 30 天过期。需确保 refresh 流程正常。
- **Webhook 防重放**: 默认允许 5 分钟时间偏差，超时拒绝。可使用 `max_skew_seconds` 自定义。
- **幂等性**: 进程内 set 仅适用于单进程部署。多进程需使用 Redis 共享存储。
- **金额单位**: 所有金额字段单位为分(fen)，整数类型。
- **核销检查**: verify_coupon 内部会先检查是否已核销（DB 查重 + 幂等性双重保障）。
- **API 限频**: 小红书开放平台有调用频率限制，注意控制并发。

## 测试指南

```bash
# 运行适配器单元测试
python -m pytest shared/adapters/xiaohongshu/tests/test_adapter.py -v

# 覆盖报告
python -m pytest shared/adapters/xiaohongshu/tests/test_adapter.py -v \
  --cov=shared.adapters.xiaohongshu.src.adapter

# 保留的 E3 验证测试不受影响
python -m pytest shared/adapters/xiaohongshu/tests/test_e3_verification.py -v
```

测试通过 mock 服务类避免真实 HTTP 调用和 DB 依赖，覆盖场景包括：
- 各方法的成功路径
- 幂等性跳过（相同参数重复调用）
- 不同参数不被幂等跳过
- API 错误异常抛出
- 门店未绑定场景
- `idempotency_key` 稳定性
- `close` 清理

## 文件结构

```
shared/adapters/xiaohongshu/
  README.md
  src/
    __init__.py              # 模块入口
    adapter.py               # 统一适配器入口（新增）
    xhs_client.py            # HTTP 客户端 + 签名
    xhs_coupon_adapter.py    # 团购券核销
    xhs_poi_sync.py          # POI 门店同步
    xhs_review_crawler.py    # 评论/笔记采集
    oauth_token_service.py   # OAuth 2.0 token 管理
    webhook_signature.py     # Webhook 签名验证
  tests/
    __init__.py
    test_adapter.py          # 适配器测试（新增）
    test_e3_verification.py  # E3 验证测试（保持原样）
```

## 依赖

- Python 3.10+
- httpx（生产环境需替换 TODO 注释的 mock 实现）
- SQLAlchemy 2.0+ (AsyncSession)
- shared.events（事件发射）
