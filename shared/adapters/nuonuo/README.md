# 诺诺开放平台 — 电子发票适配器

对接诺诺开放平台电子发票 API，覆盖全电发票开具、查询、作废、红冲及 PDF 下载。
适用于金税四期合规场景。

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
| `NUONUO_APP_KEY` | 是 | — | 诺诺开放平台 App Key |
| `NUONUO_APP_SECRET` | 是 | — | 诺诺开放平台 App Secret |
| `NUONUO_MERCHANT_NO` | 是 | — | 销方税号（纳税人识别号） |
| `NUONUO_SANDBOX` | 否 | `false` | 设为 `true` 使用沙箱环境 |

### 构造函数参数

`NuonuoAdapter.__init__(config)` 接受一个字典：

| 键 | 必填 | 类型 | 默认值 | 说明 |
|-------|------|------|--------|------|
| `app_key` | 是 | str | — | 诺诺开放平台 App Key |
| `app_secret` | 是 | str | — | 诺诺开放平台 App Secret |
| `tax_number` | 是 | str | — | 销方税号 |
| `tenant_id` | 否 | str | `""` | 屯象租户 ID（事件发射用） |
| `sandbox` | 否 | bool | `False` | 沙箱模式开关 |
| `base_url` | 否 | str | `https://sdk.nuonuo.com/open/v1/services` | API 基础 URL |

### URL 规则

- **生产环境**：`https://sdk.nuonuo.com/open/v1/services`
- **沙箱环境**：`https://sandbox.nuonuocs.cn/open/v1/services`
- **Token 生产**：`https://open.nuonuo.com/accessToken`
- **Token 沙箱**：`https://sandbox.nuonuocs.cn/accessToken`

设置 `sandbox=True` 自动切换上述 URL，无需手动指定 `base_url`。

---

## 快速开始

### 直接使用 Adapter

```python
import asyncio
from shared.adapters.nuonuo.src.adapter import NuonuoAdapter

async def main():
    adapter = NuonuoAdapter({
        "app_key": "your_app_key",
        "app_secret": "your_app_secret",
        "tax_number": "91510100MA12345678",
        "sandbox": True,
    })

    # 开具发票
    result = await adapter.issue_invoice({
        "orderNo": "ORD001",
        "buyerName": "测试公司",
        "buyerTaxNum": "91510100MAXXXXXXXX",
        "goodsWithTaxFlag": "1",
        "invoiceDetailList": [
            {
                "goodsName": "测试商品",
                "quantity": 1,
                "price": 10000,  # 分
                "taxRate": "0.01",
            }
        ],
    })
    print("开具结果:", result)

    # 查询发票
    query = await adapter.query_invoice([result["serialNo"]])
    print("查询结果:", query)

    await adapter.close()

asyncio.run(main())
```

### 使用 InvoiceClient（推荐）

```python
import asyncio
from shared.adapters.nuonuo.src.invoice_client import NuonuoInvoiceClient

async def main():
    client = NuonuoInvoiceClient()  # 从环境变量读取配置

    resp = await client.apply_invoice({"orderNo": "ORD001", "buyerName": "测试"})
    if resp.success:
        print("开票成功:", resp.data["serialNo"])
    else:
        print("开票失败:", resp.error_msg)

    await client.close()

asyncio.run(main())
```

---

## API 方法

### NuonuoAdapter

#### `issue_invoice(invoice_data) -> dict`

开具电子发票（异步，通过回调返回结果）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `invoice_data` | dict | 是 | 开票请求数据（含商品明细） |

返回诺诺 `result` 字段，典型结构：

```json
{
    "serialNo": "SN2024001",
    "invoiceCode": "4400123456",
    "invoiceNo": "12345678",
    "pdfUrl": "https://..."
}
```

#### `query_invoice(serial_nos) -> dict`

查询发票开票结果。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `serial_nos` | list | 是 | 平台请求单号列表 |

返回结构：

```json
{
    "invoiceData": [
        {
            "invoiceNo": "12345678",
            "invoiceCode": "4400123456",
            "status": "SUCCESS",
            "pdfUrl": "https://..."
        }
    ]
}
```

#### `void_invoice(invoice_id, invoice_code, invoice_number) -> dict`

作废发票（仅限当日开具的发票）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `invoice_id` | str | 是 | 发票 ID |
| `invoice_code` | str | 是 | 发票代码 |
| `invoice_number` | str | 是 | 发票号码 |

#### `issue_red_invoice(original_invoice_code, original_invoice_number, reason, invoice_data) -> dict`

开具红字发票（红冲）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `original_invoice_code` | str | 是 | 原蓝字发票代码 |
| `original_invoice_number` | str | 是 | 原蓝字发票号码 |
| `reason` | str | 是 | 红冲原因（如"退货"） |
| `invoice_data` | dict | 是 | 红字发票数据（金额取负） |

注意：`invoice_data` 中的金额必须为负值。

#### `download_pdf(invoice_code, invoice_number) -> str`

获取发票 PDF 下载链接。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `invoice_code` | str | 是 | 发票代码 |
| `invoice_number` | str | 是 | 发票号码 |

返回 PDF URL 字符串。无 PDF 时返回空字符串。

### NuonuoInvoiceClient

所有客户端方法返回 `NuonuoResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | bool | 是否成功 |
| `data` | dict | 业务数据 |
| `error_code` | str | 错误码（失败时） |
| `error_msg` | str | 错误描述（失败时） |

| 方法 | 对应 Adapter 方法 | 说明 |
|------|-------------------|------|
| `apply_invoice(data)` | `issue_invoice` | 申请开票，异常安全封装 |
| `query_invoice(request_id)` | `query_invoice` | 查询开票结果 |
| `red_flush_invoice(no, code, reason, data)` | `issue_red_invoice` | 红冲 |
| `void_invoice(id, no, code)` | `void_invoice` | 作废 |
| `get_pdf_url(code, no)` | `download_pdf` | 获取 PDF 链接 |

---

## 字段映射

### 开票请求字段映射

以下为诺诺 `requestBillingNew` 接口与屯象内部字段的映射关系。

#### 请求头字段

| 诺诺字段 | HTTP Header | 映射值 | 说明 |
|----------|-------------|--------|------|
| `accessToken` | Header | `_get_access_token()` 返回 | OAuth 令牌 |
| `X-Nuonuo-Sign` | Header | HMAC-SHA256 签名 | 请求签名 |
| `userTax` | Header | `config.tax_number` | 销方税号 |
| `method` | Header | `nuonuo.ElectronInvoice.requestBillingNew` | API 方法名 |

#### 开票请求体

| 诺诺参数 | 类型 | 必填 | 示例 | 映射说明 |
|----------|------|------|------|----------|
| `orderNo` | string | 是 | `"ORD001"` | 屯象订单号 |
| `buyerName` | string | 是 | `"测试公司"` | 购买方名称 |
| `buyerTaxNum` | string | 否 | `"91510100MAXXXX"` | 购买方税号（企业必填） |
| `buyerAddress` | string | 否 | `"长沙市..."` | 购买方地址 |
| `buyerPhone` | string | 否 | `"13800138000"` | 购买方电话 |
| `buyerBankName` | string | 否 | `"中国银行"` | 购买方开户行 |
| `buyerBankAccount` | string | 否 | `"123456789"` | 购买方银行账号 |
| `invoiceDate` | string | 否 | `"2026-05-02"` | 开票日期 |
| `clerk` | string | 否 | `"张三"` | 开票员 |
| `goodsWithTaxFlag` | string | 否 | `"1"` | 含税标志（1=含税/0=不含税） |
| `invoiceDetailList` | array | 是 | `[...]` | 商品明细（见下） |

#### 商品明细（invoiceDetailList）

| 字段 | 类型 | 必填 | 示例 | 说明 |
|------|------|------|------|------|
| `goodsName` | string | 是 | `"宫保鸡丁"` | 商品名称 |
| `quantity` | number | 是 | `2` | 数量 |
| `price` | number | 是 | `3800` | 单价（**分**） |
| `taxRate` | string | 是 | `"0.01"` | 税率（小数格式字符串） |
| `taxFlag` | string | 否 | `"0"` | 是否含税（0=含税/1=不含税） |

### 响应字段映射

| 诺诺字段 | 类型 | 说明 | 对应屯象字段 |
|----------|------|------|-------------|
| `serialNo` | string | 平台请求单号 | `invoice_request_id` |
| `invoiceCode` | string | 发票代码 | `invoice_code` |
| `invoiceNo` | string | 发票号码 | `invoice_no` |
| `pdfUrl` | string | PDF 下载链接 | `invoice_pdf_url` |
| `status` | string | 开票状态 | `invoice_status` |

### 红冲请求映射

| 参数 | 来源 | 说明 |
|------|------|------|
| `invoiceCode` | `original_invoice_code` | 原蓝字发票代码 |
| `invoiceNo` | `original_invoice_number` | 原蓝字发票号码 |
| `reason` | `reason` | 红冲原因说明 |
| 其余字段 | `invoice_data` | 取负值金额的商品明细 |

---

## 错误处理

### 错误码对照表

| 诺诺 code | 说明 | 处理策略 |
|-----------|------|----------|
| `E0000` | 成功 | 正常处理 |
| `E0001` | 系统异常 | 重试（最多 3 次） |
| `E1001` | 参数异常 | 检查请求参数，不重试 |
| `E1002` | 无权限 | 检查 AppKey/AppSecret 配置 |
| `E2001` | 税号未登记 | 联系诺诺运营完成税号登记 |
| `E2002` | 发票库存不足 | 提醒客户在诺诺后台领用发票 |
| `E2003` | 发票已作废 | 无需再次作废 |
| `E2004` | 红冲次数超限 | 原发票已达最大红冲次数 |
| `E3001` | Token 过期 | 自动刷新 |
| `E3002` | 签名错误 | 检查 AppSecret |
| `E4001` | 接口调用频次超限 | 降速重试 |

所有业务错误统一转为 `NuonuoAPIError`，包含 `code` 和 `method` 上下文。

### 异常体系

| 异常 | 触发条件 | 说明 |
|------|----------|------|
| `NuonuoAPIError` | 诺诺返回非 `E0000` | 业务错误（含错误码和方法名） |
| `httpx.ConnectError` | 网络不可达 | 自动重试最多 3 次 |
| `httpx.TimeoutException` | 请求超时 | 自动重试最多 3 次 |
| `httpx.HTTPStatusError` | 非 2xx 响应 | 客户端层捕获转为 failure |

### 日志关键点

| Logger Name | level | 触发场景 |
|-------------|-------|----------|
| `nuonuo.api_error` | ERROR | 诺诺返回业务错误码 |
| `nuonuo.apply_invoice.ok` | INFO | 开票成功 |
| `nuonuo.apply_invoice.failed` | ERROR | 开票失败 |
| `nuonuo.query_invoice.ok` | INFO | 查询成功 |
| `nuonuo.query_invoice.failed` | ERROR | 查询失败 |
| `nuonuo.red_flush.ok` | INFO | 红冲成功 |
| `nuonuo.red_flush.failed` | ERROR | 红冲失败 |
| `nuonuo.void_invoice.ok` | INFO | 作废成功 |
| `nuonuo.void_invoice.failed` | ERROR | 作废失败 |
| `nuonuo.get_pdf_url.failed` | ERROR | PDF 获取失败 |
| `nuonuo.event_emit_failed` | WARNING | 事件发射失败（不阻断主流程） |

---

## 幂等性保障

`NuonuoAdapter` 内置运行时幂等性检查：

```python
# 生成幂等键
key = adapter.idempotency_key("issue", {"orderNo": "ORD001", "amount": 10000})
# key 基于 operation + payload 的 MD5 哈希

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
| `STATUS_PUSHED` | `issue_invoice` 成功 | `invoice` | `nuonuo:invoice:{serial_no}` |
| `STATUS_PUSHED` | `void_invoice` 成功 | `invoice_void` | `nuonuo:invoice_void:{invoice_number}` |
| `SYNC_FINISHED` | `query_invoice` 有结果 | `invoice_query` | `nuonuo:invoice_query:{serial_no}` |

事件发射失败仅记录 WARNING，不阻断主业务流程。

---

## 已知问题与注意事项

### 已知问题

1. **Token 无持久化**：`_access_token` 存储在内存中，进程重启后需要重新获取。Token 有效期通常为 2 小时，过期前 5 分钟自动刷新（300 秒缓冲）。
2. **幂等性内存存储**：`_nonce_store` 使用 `Set[str]` 而非 Redis，项目重启后去重状态丢失。多实例部署场景需改为共享存储。
3. **沙箱环境差异**：沙箱环境 URL 后缀为 `.cn`（`sandbox.nuonuocs.cn`），生产环境为 `.com`（`sdk.nuonuo.com`）。沙箱环境 token 端点域名不同，已自动处理。
4. **红冲金额取负**：`issue_red_invoice` 不自动翻转金额正负，调用方需确保 `invoice_data` 中金额为负值，否则诺诺会返回参数错误。
5. **无 PDF 时返回空字符串**：`download_pdf` 返回的 URL 可能为空字符串，调用方需处理空值场景。
6. **异步回调**：`issue_invoice` 是异步接口，诺诺通过回调返回结果。`query_invoice` 轮询间隔建议 >= 5 秒。

### 注意事项

1. **金额单位统一为分**：所有金额字段使用整数（分），避免浮点精度问题。含税标志配合单价时需特别注意单位一致性。
2. **税率格式**：诺诺接口的 `taxRate` 为字符串格式（如 `"0.01"`），而非百分比整数，与部分 POS 系统不同。
3. **发票作废时限**：诺诺仅允许作废**当日**开具的发票。跨日发票需走红冲流程。
4. **商品明细数量限制**：单次开票请求建议不超过 200 条商品明细，超出可能导致接口超时。
5. **网络重试策略**：指数退避（0.5s × 2^n），最多重试 3 次。仅重试可恢复错误（连接/超时），业务错误不重试。
6. **并发控制**：`_get_access_token` 存在并发获取问题，高并发场景下可能导致多个 token 请求。建议加锁保护或使用独立 token 管理服务。
7. **事件发射异常隔离**：`_emit_sync_event` 使用 `asyncio.create_task` 异步发射，不阻塞主流程。事件总线故障不影响发票操作。

### 测试指南

```bash
# 运行单元测试
pytest shared/adapters/nuonuo/tests/ -v

# 覆盖率报告
pytest shared/adapters/nuonuo/tests/ --cov=shared.adapters.nuonuo.src --cov-report=term-missing
```

测试覆盖以下场景：
- NuonuoAPIError 自定义异常构造
- 沙箱/生产 URL 选择
- Access Token 缓存与过期刷新
- HMAC 签名头验证
- 幂等性键生成与去重
- 发票开具/查询/作废/红冲/PDF 下载
- 事件发射（fire-and-forget）
- InvoiceClient 异常安全封装层（5 个方法 × 2 种异常路径）

---

## 版本兼容性

| 适配器版本 | 诺诺 API 版本 | 屯象 OS 版本 | 备注 |
|------------|---------------|-------------|------|
| v1.0 | 2024-12 | v0.9+ | 初始版本 |
| v1.1 | 2025-06 | v0.11+ | 增加事件发射 + 幂等性 |

---

## 参考链接

- [诺诺开放平台文档](https://open.nuonuo.com)
- [诺诺电子发票 API 文档](https://open.nuonuo.com/doc-center)
- [金税四期合规要求](https://www.chinatax.gov.cn)
