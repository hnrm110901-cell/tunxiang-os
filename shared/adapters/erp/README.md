# ERP 适配器 - ERP Adapter

屯象OS 与金蝶 K3/Cloud、用友云 YonBIP/NC 等 ERP 系统的统一集成适配器。

提供凭证推送、科目同步等财务接口的统一抽象层。

---

## 配置说明

### 金蝶 K3/Cloud

#### 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `KINGDEE_APP_ID` | 是 | 金蝶开放平台 App ID |
| `KINGDEE_APP_SECRET` | 是 | 金蝶开放平台 App Secret |
| `KINGDEE_BASE_URL` | 是 | 金蝶 Cloud 实例地址，如 `https://xxx.kingdeecloud.com` |
| `KINGDEE_ENTITY_ID` | 否 | 账套 ID（多账套场景必填） |

#### 认证方式
HMAC-SHA256 签名认证：
```
签名字符串 = app_id + timestamp + nonce + SHA256(body)
签名       = HMAC-SHA256(app_secret, 签名字符串)
```

### 用友云 YonBIP/NC

#### 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `YONYOU_CLIENT_ID` | 是 | 用友开放平台 Client ID |
| `YONYOU_CLIENT_SECRET` | 是 | 用友开放平台 Client Secret |
| `YONYOU_BASE_URL` | 是 | 用友云实例地址，如 `https://xxx.yonbip.com` |
| `YONYOU_TENANT_CODE` | 否 | 用友账套编码（多账套场景） |
| `YONYOU_QUEUE_PATH` | 否 | 离线队列路径，默认 `/tmp/yonyou_push_queue.jsonl` |

#### 认证方式
OAuth2 Client Credentials Flow（grant_type=client_credentials）。

---

## 快速开始

```python
import asyncio
from shared.adapters.erp.src import get_erp_adapter
from shared.adapters.erp.src import ERPVoucher, ERPVoucherEntry, VoucherType
from datetime import date

async def main():
    # 工厂方法创建适配器
    adapter = get_erp_adapter("kingdee")  # 或 "yonyou"

    try:
        # 健康检查
        ok = await adapter.health_check()
        print(f"ERP 连接: {'OK' if ok else 'FAILED'}")

        # 同步科目表
        accounts = await adapter.sync_chart_of_accounts()
        print(f"同步科目: {len(accounts)} 条")

        # 推送凭证
        voucher = ERPVoucher(
            voucher_type=VoucherType.MEMO,
            business_date=date.today(),
            entries=[
                ERPVoucherEntry(
                    account_code="5001",
                    account_name="主营业务收入",
                    credit_fen=8800,
                    summary="日结收入结转",
                ),
                ERPVoucherEntry(
                    account_code="1002",
                    account_name="银行存款",
                    debit_fen=8800,
                    summary="日结收入结转",
                ),
            ],
            source_type="daily_revenue",
            source_id="SETTLE20260503",
            tenant_id="tenant-uuid",
            store_id="store-uuid",
        )
        result = await adapter.push_voucher(voucher)
        print(f"推送结果: {result.status.value}")
    finally:
        await adapter.close()

asyncio.run(main())
```

---

## 凭证推送字段映射

### 统一凭证格式（ERPVoucher）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `voucher_id` | str | 自动 | 屯象内部凭证 ID（UUID hex） |
| `voucher_type` | VoucherType | 是 | 凭证字：收/付/转/记 |
| `business_date` | date | 是 | 业务日期 |
| `entries` | list | 是 | 分录列表（至少 2 条，借贷平衡） |
| `source_type` | str | 是 | 来源类型：`purchase_order` / `daily_revenue` / `payroll` |
| `source_id` | str | 是 | 来源单据 ID |
| `tenant_id` | str | 是 | 租户 ID |
| `store_id` | str | 是 | 门店 ID |
| `memo` | str | 否 | 凭证备注 |

### 分录格式（ERPVoucherEntry）

| 字段 | 类型 | 说明 |
|------|------|------|
| `account_code` | str | 科目编码，如 `5001` |
| `account_name` | str | 科目名称，如 `主营业务收入` |
| `debit_fen` | int | 借方金额（分），非负 |
| `credit_fen` | int | 贷方金额（分），非负 |
| `summary` | str | 摘要，不超过 200 字 |

**规则**：借贷金额严格遵守单边原则——每笔分录 `debit_fen > 0` 时 `credit_fen` 必须为 0，反之亦然。整个凭证的借方合计必须等于贷方合计（借贷平衡，分为单位）。

### 金蝶 K3/Cloud 字段映射

| ERPVoucher | 金蝶 Cloud 字段 |
|-----------|----------------|
| `voucher_type` | `Model.FVoucherGroupID.FNumber` |
| `business_date` | `Model.FDate` |
| `memo` | `Model.FNote` |
| `voucher_id` | `Model.FDescription`（扩展备注） |
| `entry.account_code` | `Model.FBillEntry[].FAccountID.FNumber` |
| `entry.debit_fen` / 100 | `Model.FBillEntry[].FDEBIT`（分 -> 元） |
| `entry.credit_fen` / 100 | `Model.FBillEntry[].FCREDIT`（分 -> 元） |
| `entry.summary` | `Model.FBillEntry[].FEXPLANATION` |

### 用友云 YonBIP 字段映射

| ERPVoucher | 用友云字段 |
|-----------|-----------|
| `voucher_type` | `voucherType` |
| `business_date` | `voucherDate` |
| `memo` | `memo` |
| `voucher_id` | `sourceVoucherId` |
| `entry.account_code` | `entries[].accountCode` |
| `entry.debit_fen` / 100 | `entries[].debitAmount`（分 -> 元） |
| `entry.credit_fen` / 100 | `entries[].creditAmount`（分 -> 元） |
| `entry.summary` | `entries[].explanation` |

---

## 科目同步说明

### 金蝶
- 端点：GET `/ierp/api/v2/bd/account/getAll`
- 参数：`EntityId`（账套 ID，可选）
- 降级策略：HTTP 失败时返回内置默认科目表（13 个常用科目）

### 用友
- 端点：GET `/api/v1/bd/account/list`
- 参数：`tenantCode`（账套编码）、`pageSize: 500`
- 无降级策略：失败时抛出异常

### 内置默认科目表（金蝶降级用）

| 编码 | 名称 | 类型 |
|------|------|------|
| 1001 | 库存现金 | 资产 |
| 1002 | 银行存款 | 资产 |
| 1012.01 | 微信收款 | 资产 |
| 1012.02 | 支付宝收款 | 资产 |
| 1122 | 应收账款 | 资产 |
| 1403 | 原材料 | 资产 |
| 1405 | 库存商品 | 资产 |
| 1406 | 在途物资 | 资产 |
| 2202 | 应付账款 | 负债 |
| 2211 | 应付职工薪酬 | 负债 |
| 5001 | 主营业务收入 | 收入 |
| 5401 | 主营业务成本 | 费用 |
| 5602 | 管理费用 | 费用 |

---

## 错误码

### ERPPushResult.status

| 状态 | 说明 |
|------|------|
| `SUCCESS` | 推送成功，`erp_voucher_id` 不为空 |
| `FAILED` | 推送失败 |
| `QUEUED` | 推送失败已入本地队列（用友），待 `drain_queue()` 重试 |

### 异常类型

| 异常 | 触发条件 | 处理建议 |
|------|---------|---------|
| `httpx.HTTPError` | 网络/HTTP 层错误 | 重试 |
| `ValueError` | 凭证格式或业务校验错误 | 修复请求参数 |
| `RuntimeError` | ERP 系统返回业务错误 | 检查 ERP 侧日志 |

### 用友离线重试

推送失败时自动写入本地 JSON Lines 队列文件，通过 `drain_queue()` 批量重试：
```python
remaining = adapter.queue_size()
if remaining > 0:
    results = await adapter.drain_queue()
```

---

## 幂等性

适配器基类内置幂等性支持，防止网络重试导致重复推送：

```python
# 生成幂等键（基于操作名 + 租户 + 请求体）
key = adapter.idempotency_key("push_voucher", voucher.model_dump())

# 跳过重复请求
if adapter.is_duplicate(key):
    log.info("duplicate push, skipping")
    return

# 执行推送
result = await adapter.push_voucher(voucher)

# 标记已处理
adapter.mark_idempotent(key)
```

---

## 事件发射

适配器在凭证推送成功后向 `tx_adapter_events` 流发射 `STATUS_PUSHED` 事件：

| 适配器 | scope | stream_id 模式 | 触发点 |
|--------|-------|----------------|--------|
| 金蝶 | `finance` | `kingdee:voucher:{voucher_id}` | `push_voucher()` 成功后 |
| 用友 | `finance` | `yonyou:voucher:{voucher_id}` | `push_voucher()` 成功后 |

事件 payload 包含 `voucher_id`、`source_type`、`source_id`、`total_fen`、`erp_voucher_id`。

设置 `_tenant_id` 以启用租户级事件隔离：
```python
adapter._tenant_id = "tenant-uuid"
```

---

## 金蝶 vs 用友配置差异

| 维度 | 金蝶 K3/Cloud | 用友云 YonBIP |
|------|---------------|---------------|
| 认证方式 | HMAC-SHA256 签名 | OAuth2 Client Credentials |
| 凭证端点 | POST `/ierp/api/v2/gl/vouchers/save` | POST `/api/v1/gl/vouchers` |
| 科目端点 | GET `/ierp/api/v2/bd/account/getAll` | GET `/api/v1/bd/account/list` |
| 金额单位 | 元（接口要求） | 元（接口要求） |
| 科目降级 | 有（默认 13 个科目） | 无 |
| 离线重试 | 无（异常直接抛出） | 有（JSON Lines 队列） |
| 失败处理 | 调用方自行决策 | 自动入队 + drain_queue |

---

## 测试指南

```bash
# 运行所有 ERP 适配器测试
pytest shared/adapters/erp/tests/ -v

# 运行特定测试
pytest shared/adapters/erp/tests/test_adapter.py -v -k "test_push_voucher"

# 查看覆盖率
pytest --cov=shared/adapters/erp/src --cov-report=html shared/adapters/erp/tests/
```

测试基于 Mock（`unittest.mock.patch` / `httpx.AsyncClient` mock），不依赖真实 ERP 系统。
