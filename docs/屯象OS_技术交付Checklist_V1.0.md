# 屯象OS 技术交付与商业运营 — 可执行开发任务清单

> 基于《技术交付与商业运营方案 V1.0》+ 代码库深度审计，2026-03-12 生成
> 服务器: 42.194.229.21 | 域名: www.zlsjos.cn

---

## 代码库审计结论（先校准再排期）

方案中提到的很多能力，代码库已经实现但未启用：

| 方案要求 | 代码完成度 | 实际工作 |
|----------|-----------|----------|
| TenantContext 租户隔离 | ✅ 已实现 `src/core/tenant_context.py` | 仅需注册中间件 |
| StoreAccessMiddleware | ✅ 已实现 `src/middleware/store_access.py` | **未注册到 main.py**，需一行代码 |
| JWT 携带 brand_id/store_id | ✅ 已实现 `auth_service.py:54-60` | 无需改动 |
| ORM 级租户过滤 | ✅ 已实现 `src/core/tenant_filter.py` (RLS) | 无需改动 |
| 商户管理 API+前端 | ✅ 已实现 `api/merchants.py` + `MerchantManagementPage` | 无需改动 |
| 品智 POS 适配器 | ✅ 已实现 `packages/api-adapters/pinzhi/` | 需补数据回填脚本 |
| 天财商龙适配器 | ⚠️ 骨架 `packages/api-adapters/tiancai-shanglong/` | 需补全 API 调用 |
| 客如云适配器 | ⚠️ 骨架 `packages/api-adapters/keruyun/` | 需补全 API 调用 |
| Edge Hub 模型+API | ✅ 已实现 `models/edge_hub.py` + `api/edge_hub.py` | 无需改动 |
| 语音播报+TTS | ✅ 已实现 `api/voice.py` + `voice_ws.py` + `shokz_service.py` | 需现场部署 |
| 硬件集成 API | ✅ 已实现 `api/hardware_integration.py` | 无需改动 |
| Nginx 子域名路由 | ❌ 不存在 | **需新建配置** |
| Schema 隔离 | ❌ 不存在（当前仅用 public schema） | **需实现** |
| SSL 泛域名证书 | ❌ 不存在 | **需申请** |
| 前端动态品牌主题 | ❌ 不存在 | **需实现** |

---

## Phase 1: 多租户架构改造（W1-W2）

### 1.1 Nginx 子域名路由

- [ ] **1.1.1** DNS 解析配置（域名服务商操作）
  - 添加 A 记录: `admin` → 42.194.229.21
  - 添加 A 记录: `api` → 42.194.229.21
  - 添加 A 记录: `changzaiyiqi` → 42.194.229.21
  - 添加 A 记录: `zuiqianxian` → 42.194.229.21
  - 添加 A 记录: `shanggongchu` → 42.194.229.21
  - 添加 CNAME 泛解析: `*` → zlsjos.cn
  - **验收**: `dig changzaiyiqi.zlsjos.cn` 返回 42.194.229.21
  - **负责人**: 运维
  - **耗时**: 0.5d

- [ ] **1.1.2** SSL 泛域名证书申请
  - 安装 certbot + DNS 插件
  - 执行: `certbot certonly --manual --preferred-challenges dns -d "*.zlsjos.cn" -d zlsjos.cn`
  - 配置自动续期 cron
  - **验收**: `curl -I https://changzaiyiqi.zlsjos.cn` 返回有效证书
  - **负责人**: 运维
  - **耗时**: 0.5d

- [ ] **1.1.3** 改造 `nginx/conf.d/default.conf`
  - 添加 `map $host $tenant_id` 指令
  - 添加 `proxy_set_header X-Tenant-ID $tenant_id`
  - 分离 server block: admin / 商户 / API
  - 更新 SSL 证书路径为泛域名证书
  - **关键文件**: `nginx/conf.d/default.conf`
  - **验收**: 访问不同子域名, 后端日志显示正确的 X-Tenant-ID header
  - **负责人**: 后端
  - **耗时**: 0.5d

### 1.2 PostgreSQL Schema 隔离

- [ ] **1.2.1** 创建商户 Schema 初始化脚本
  - 新建 `scripts/create_tenant_schema.py`
  - 功能: 接收 schema_name 参数 → `CREATE SCHEMA IF NOT EXISTS {name}` → 复制 public 表结构
  - 排除系统表: users, groups, brands, regions, alembic_version, system_config
  - 租户表清单(从 tenant_filter.py 的 TENANT_TABLES): orders, order_items, reservations, inventory_items, inventory_transactions, schedules, employees 等
  - **验收**: `\dn` 显示 czq, zqx, sgc 三个 schema
  - **负责人**: 后端
  - **耗时**: 1d

- [ ] **1.2.2** 改造 database.py — 动态 search_path
  - 在 `get_db()` / `get_db_session()` 中增加逻辑:
    1. 从 TenantContext 获取 brand_id
    2. 映射 brand_id → schema_name (配置表或 dict)
    3. 执行 `SET search_path TO {schema}, public`
  - 添加 brand_to_schema 映射: `{"BRD_CZYZ0001": "czq", "BRD_ZQX00001": "zqx", "BRD_SGC00001": "sgc"}`
  - **关键文件**: `src/core/database.py`
  - **验收**: 不同 brand_id 的请求查询到各自 schema 的数据
  - **负责人**: 后端
  - **耗时**: 1d

- [ ] **1.2.3** 改造 Alembic 多 Schema 迁移
  - 修改 `alembic/env.py` — 遍历所有租户 schema 执行 DDL
  - 新增 `alembic/tenant_schemas.py` 配置文件
  - **关键文件**: `apps/api-gateway/alembic/env.py`
  - **验收**: `alembic upgrade head` 同时迁移 czq/zqx/sgc 三个 schema
  - **负责人**: 后端
  - **耗时**: 0.5d

- [ ] **1.2.4** Schema 级备份脚本
  - 新建 `scripts/backup_tenant.sh`
  - 按 schema 独立 `pg_dump -n {schema}`
  - cron 每日凌晨 3:00 自动执行
  - 可选: WAL 归档至腾讯云 COS
  - **验收**: backup 目录有按日期+schema 命名的 SQL 文件
  - **负责人**: 运维
  - **耗时**: 0.5d

### 1.3 应用层租户隔离启用

- [ ] **1.3.1** 注册 StoreAccessMiddleware（**1 行代码**）
  - 在 `src/main.py` 中间件注册区域 (~line 335) 添加:
    ```python
    from src.middleware.store_access import StoreAccessMiddleware
    app.add_middleware(StoreAccessMiddleware)
    ```
  - **关键文件**: `src/main.py`, `src/middleware/store_access.py`
  - **验收**: 非管理员用户无法跨品牌访问数据
  - **负责人**: 后端
  - **耗时**: 0.5h

- [ ] **1.3.2** 增强中间件读取 X-Tenant-ID Header
  - 修改 `src/middleware/store_access.py`:
    - 在 `dispatch()` 开头读取 `request.headers.get("X-Tenant-ID")`
    - 如存在, 用 X-Tenant-ID 设置 TenantContext brand
    - 优先级: Header > JWT > 默认
  - **关键文件**: `src/middleware/store_access.py`
  - **验收**: 通过子域名访问时, TenantContext 自动设置正确的 brand_id
  - **负责人**: 后端
  - **耗时**: 0.5d

- [ ] **1.3.3** 品牌-Schema 映射配置表
  - 在 `src/core/config.py` 的 Settings 中添加 TENANT_SCHEMA_MAP 字段
  - 或新建 `tenant_schemas` 表: brand_id → schema_name → 子域名
  - 商户开通时自动写入映射关系
  - **验收**: 新开通商户自动创建 schema + 映射
  - **负责人**: 后端
  - **耗时**: 0.5d

### 1.4 前端多租户适配

- [ ] **1.4.1** 动态品牌主题加载
  - 登录成功后, 根据 JWT 中 brand_id 加载品牌配置（Logo/主色调/品牌名）
  - 新建 `src/hooks/useBrandTheme.ts` — 从 `/api/v1/merchants/{brand_id}` 获取品牌信息
  - 在 `MainLayout.tsx` / 各角色 Layout 中应用品牌 Logo 和配色
  - CSS 变量覆盖: `--accent`, `--brand-logo`, `--brand-name`
  - **验收**: 不同商户登录看到不同 Logo 和主色调
  - **负责人**: 前端
  - **耗时**: 1d

- [ ] **1.4.2** 商户后台路由隔离
  - 商户管理员登录后, 自动限定为本品牌数据
  - 侧边栏菜单根据角色+品牌动态生成
  - 隐藏"平台管理"菜单组（仅 ADMIN 可见）
  - **关键文件**: `src/layouts/MainLayout.tsx`
  - **验收**: 商户管理员看不到平台级菜单
  - **负责人**: 前端
  - **耗时**: 0.5d

### 1.5 三级后台体系验证

- [ ] **1.5.1** 平台管理后台 (admin.zlsjos.cn)
  - 验证: 管理员登录 → 商户管理 → 开通/停用/配置
  - 验证: 全局系统监控、账单管理（如有）
  - **验收**: 管理员能看到所有商户数据
  - **耗时**: 0.5d（纯测试）

- [ ] **1.5.2** 商户管理后台 ({brand}.zlsjos.cn)
  - 验证: 商户管理员登录 → 仅看到本品牌数据
  - 验证: 门店管理、员工管理、Agent 配置
  - **验收**: 商户 A 看不到商户 B 的任何数据
  - **耗时**: 0.5d（纯测试）

- [ ] **1.5.3** 门店操作后台 ({brand}.zlsjos.cn/sm or /chef or /floor)
  - 验证: 店长/厨师长/楼面经理登录 → 仅看到本门店
  - **验收**: 角色路由正确, 数据隔离正确
  - **耗时**: 0.5d（纯测试）

---

## Phase 2: 尝在一起深度接入（W3-W4）

### 2.1 数据回填

- [ ] **2.1.1** 创建 czq Schema + 表结构
  - 执行 `scripts/create_tenant_schema.py czq`
  - **验收**: `\dt czq.*` 显示完整表列表
  - **耗时**: 0.5h

- [ ] **2.1.2** 品智 API 历史数据拉取脚本
  - 完善 `scripts/fetch_pinzhi_monthly_data.py`
  - 拉取近 6 个月: 营业日报、订单明细、库存、菜品、会员
  - 写入 czq schema
  - **关键文件**: `scripts/fetch_pinzhi_monthly_data.py`, `packages/api-adapters/pinzhi/`
  - **验收**: czq.orders 表有 6 个月数据, 与品智后台一致性 > 98%
  - **负责人**: 后端
  - **耗时**: 2d

- [ ] **2.1.3** 门店+员工基础数据录入
  - 在商户管理后台录入尝在一起的实际门店（花果园、永安、文化城）
  - 录入管理人员账号（老板、店长、厨师长）
  - **负责人**: 运营
  - **耗时**: 0.5d

### 2.2 Agent 对接与报表

- [ ] **2.2.1** 经营日报 Agent 配置
  - 配置 daily_hub 推送时间 7:30
  - 绑定老板企微 (user.wechat_user_id)
  - 验证日报内容: 营收/客流/食材成本率/关键异常
  - **验收**: 老板企微每天 7:30 收到经营简报
  - **负责人**: 后端
  - **耗时**: 0.5d

- [ ] **2.2.2** 库存预警 Agent 配置
  - 配置低库存阈值 (inventory_items.min_quantity)
  - 临期自动推送 (InventoryBatch.expires_at)
  - 企微告警通道验证
  - **验收**: 低库存 / 临期自动推送企微
  - **负责人**: 后端
  - **耗时**: 0.5d

- [ ] **2.2.3** 三源对账规则配置
  - 配置对账阈值 2%, 周期日结
  - 品智(采购) vs 库存消耗 vs POS(营收) 三角对账
  - **验收**: 每日凌晨自动对账, 差异标红
  - **负责人**: 后端
  - **耗时**: 0.5d

- [ ] **2.2.4** 会员生命周期配置
  - 流失阈值: 90 天未消费
  - 生日提醒: 提前 3 天
  - RFM 分层规则
  - **验收**: 自动触发召回/生日关怀
  - **负责人**: 运营+后端
  - **耗时**: 0.5d

### 2.3 数据同步自动化

- [ ] **2.3.1** 营业数据定时同步
  - 配置 Celery Beat: 每日凌晨 2:00 拉取品智日营业数据
  - 增量同步: 订单明细每小时拉取
  - **关键文件**: `packages/api-adapters/pinzhi/src/adapter.py`
  - **验收**: 每日数据自动入库, 无需人工操作
  - **负责人**: 后端
  - **耗时**: 1d

- [ ] **2.3.2** 同步中断告警
  - Prometheus 规则: 连续 2 次同步失败 → 企微告警
  - 监控面板: 各数据源同步状态/延迟/成功率
  - **验收**: 手动断开 API → 5 分钟内企微群告警
  - **负责人**: 运维
  - **耗时**: 0.5d

---

## Phase 3: 最黔线标准接入（W3-W6）

### 3.1 信息收集（W3）

- [ ] **3.1.1** 确认 POS 系统品牌及版本
  - 联系最黔线 IT 负责人
  - 获取 API 文档 + AppKey/AppSecret
  - **产出**: POS 系统确认单
  - **负责人**: 商务
  - **耗时**: 3-5d（外部依赖）

- [ ] **3.1.2** 签署数据安全协议
  - 准备数据安全协议模板
  - 明确数据范围、使用权限、安全责任
  - **产出**: 双方签署的协议文件
  - **负责人**: 商务
  - **耗时**: 与 3.1.1 并行

### 3.2 适配器开发（W4-W5）

- [ ] **3.2.1** 完善天财商龙/相应 POS 适配器
  - 基于 `packages/api-adapters/tiancai-shanglong/` 骨架补全
  - 实现 4 大数据域: 门店/菜品/订单/库存
  - 编写单元测试, 覆盖率 > 80%
  - **关键文件**: `packages/api-adapters/tiancai-shanglong/src/adapter.py`
  - **验收**: pytest 全绿, mock 数据结构与实际 API 一致
  - **负责人**: 后端
  - **耗时**: 5d

- [ ] **3.2.2** 创建 zqx Schema + 首次全量同步
  - 执行 `scripts/create_tenant_schema.py zqx`
  - 首次拉取全量数据
  - 与 POS 后台交叉验证
  - **验收**: 数据一致性 > 95%
  - **负责人**: 后端
  - **耗时**: 2d

### 3.3 上线验证（W6）

- [ ] **3.3.1** Agent 对接 + 报表试运行
  - 配置日报推送 / 库存预警 / 对账
  - 试运行一周
  - **验收**: 老板+店长每日收到报表, 无明显数据错误
  - **耗时**: 3d

---

## Phase 4: 尚宫厨精品接入（W5-W10）

### 4.1 POS 确认 + 适配器开发

- [ ] **4.1.1** 确认 POS 系统（预计客如云）
  - 获取 API 文档 + 授权凭证
  - **负责人**: 商务
  - **耗时**: 3-5d（外部依赖）

- [ ] **4.1.2** 完善客如云适配器
  - 基于 `packages/api-adapters/keruyun/` 骨架补全
  - 额外关注: 宴会/包厢数据、高端会员数据
  - **关键文件**: `packages/api-adapters/keruyun/src/adapter.py`
  - **验收**: 测试全绿
  - **负责人**: 后端
  - **耗时**: 5d

- [ ] **4.1.3** sgc Schema + 数据同步 + 上线
  - 流程同最黔线
  - **耗时**: 3d

---

## Phase 5: IoT 硬件部署（W5-W11）

### 5.1 树莓派系统镜像准备

- [ ] **5.1.1** 制作预配置 SD 卡镜像
  - 基础系统: Raspberry Pi OS 64-bit Bookworm
  - 预装: Docker, Edge Runtime, BlueZ, PipeWire
  - 预配置: WiFi 连接模板, 自动注册脚本
  - 写入 `EDGE_BOOTSTRAP_TOKEN` 和 API 地址
  - **产出**: `.img` 镜像文件, 可直接烧录
  - **负责人**: 运维
  - **耗时**: 2d

- [ ] **5.1.2** Edge Runtime 打包
  - 将 edge_node_service 打包为独立 Python 包
  - 离线缓存: SQLite + 预设规则
  - 心跳上报: 30s 间隔, 含 CPU/内存/磁盘/温度
  - **关键文件**: `src/services/edge_node_service.py`
  - **验收**: Pi 上电后自动注册到云端 admin 面板
  - **负责人**: 后端
  - **耗时**: 3d

### 5.2 尝在一起试点部署（W5-W6）

- [ ] **5.2.1** 硬件采购
  - Raspberry Pi 5 8GB × 2
  - Shokz OpenComm2 UC × 6（3副/店 × 2店）
  - SanDisk 64GB A2 × 2
  - 27W USB-C 电源 × 2
  - USB 蓝牙 5.3 适配器 × 2
  - 小型 UPS × 2
  - **预算**: ~15,060 元
  - **负责人**: 运营
  - **耗时**: 3-5d（物流）

- [ ] **5.2.2** 花果园店现场部署
  - 烧录镜像 → 上电连 WiFi → 云端注册 → 蓝牙配对耳机 → 岗位绑定 → 功能验证
  - SOP 见方案 3.2.2 (7步, ~1小时/店)
  - **验收**: 语音播报测试通过, 离线缓存验证, 心跳稳定
  - **负责人**: 屯象技术现场
  - **耗时**: 0.5d

- [ ] **5.2.3** 永安店部署
  - 同上 SOP
  - **耗时**: 0.5d

### 5.3 最黔线旗舰店部署（W8-W9）

- [ ] **5.3.1** 硬件采购 + 部署
  - Pi5 × 1, Shokz × 5, 配件
  - **预算**: ~8,500 元
  - **耗时**: 1d

### 5.4 尚宫厨旗舰店部署（W10-W11）

- [ ] **5.4.1** 硬件采购 + 部署
  - Pi5 × 1, Shokz × 5, 配件 + VIP 提示屏
  - **预算**: ~10,000 元
  - **耗时**: 1d

---

## Phase 6: 商业运营（贯穿 W1-W12）

### 6.1 合同与收款

- [ ] **6.1.1** 尝在一起合同签署 + 首期收款
  - 版本: 专业版 3,980/店/月 × 3 店
  - 实施费: 5,000 元
  - 硬件: 22,590 元
  - **首年合计**: 170,870 元
  - **目标时间**: W3-W4
  - **负责人**: 商务

- [ ] **6.1.2** 最黔线合同签署 + 首期收款
  - 版本: 基础版 1,980/店/月 × 3 店
  - **首年合计**: 98,870 元
  - **目标时间**: W4-W5
  - **负责人**: 商务

- [ ] **6.1.3** 尚宫厨合同签署 + 首期收款
  - 版本: 专业版 3,980/店/月 × 2 店
  - **首年合计**: 115,580 元
  - **目标时间**: W7-W8
  - **负责人**: 商务

### 6.2 培训与交付

- [ ] **6.2.1** 尝在一起门店培训
  - 老板: 30min（经营看板+日报+决策建议）
  - 店长: 1h（排班+库存+备料+任务）
  - 厨师长: 30min（沽清+损耗+出品）
  - 楼面: 30min（桌态+排队+服务）
  - **产出**: 按角色操作手册
  - **目标时间**: W5-W6

- [ ] **6.2.2** 最黔线培训
  - 同上流程
  - **目标时间**: W8

- [ ] **6.2.3** 尚宫厨培训
  - 额外: 宴会管理模块培训
  - **目标时间**: W10-W11

### 6.3 案例收集

- [ ] **6.3.1** 建立数据采集基线
  - 记录上线前关键指标（成本率/损耗率/翻台率/会员复购率）
  - 为 case_story_generator.py 提供 before/after 对照数据
  - **负责人**: 运营
  - **耗时**: 1d

---

## Phase 7: 稳定性与运维（W9-W12）

### 7.1 监控与告警

- [ ] **7.1.1** Prometheus 多租户指标
  - 按 brand_id 标签采集: API 响应时间/错误率/DB 连接数
  - Grafana Dashboard: 三商户并排对比
  - **验收**: Grafana 能看到三商户各自的实时指标
  - **负责人**: 运维
  - **耗时**: 1d

- [ ] **7.1.2** 自动化运维
  - 日志轮转: 7 天保留, 压缩归档
  - DB 连接池监控: 超过 80% 告警
  - 磁盘空间监控: 超过 80% 告警
  - **耗时**: 0.5d

### 7.2 性能优化

- [ ] **7.2.1** 评估单服务器承载能力
  - 压测: 模拟三商户高峰并发（午市 11:30-13:00）
  - 瓶颈分析: CPU/内存/DB 连接/带宽
  - 如需: 升级至 8 核 16GB 或启用 CDN
  - **验收**: P95 响应 < 500ms, 无 OOM
  - **负责人**: 后端+运维
  - **耗时**: 1d

- [ ] **7.2.2** Redis 精简
  - 评估 Sentinel 必要性, 三商户场景下单 Redis 即可
  - 节省 ~600MB 内存
  - **耗时**: 0.5d

### 7.3 容灾

- [ ] **7.3.1** 全量备份验证
  - 模拟: 从备份恢复单个商户 Schema
  - 验证: 数据完整性 + 应用可用性
  - **验收**: 恢复后应用正常运行
  - **耗时**: 0.5d

---

## 里程碑总览

| 里程碑 | 时间 | 核心验收标准 | 商业收入 |
|--------|------|-------------|---------|
| **M0**: 架构改造完成 | W2 末 | 三子域名可访问, Schema 隔离验证通过 | - |
| **M1**: 尝在一起上线 | W4 末 | 日报+库存+对账稳定运行 | 首期款 |
| **M2**: 最黔线签约+开发 | W5 末 | 合同签署, 适配器完成 | 首期款 |
| **M3**: IoT 首店部署 | W6 末 | 2 店语音播报正常 | 硬件款 |
| **M4**: 三客户全上线 | W10 末 | 8 店在线运营 | 全额年费 |
| **M5**: 稳定运营 | W12 末 | 月度复盘无P0故障 | ARR > 38 万 |

---

## 工作量估算

| Phase | 后端(人天) | 前端(人天) | 运维(人天) | 运营/商务(人天) | 合计 |
|-------|-----------|-----------|-----------|----------------|------|
| P1 多租户 | 4 | 1.5 | 2 | 0 | 7.5 |
| P2 尝在一起 | 5 | 0 | 1 | 1.5 | 7.5 |
| P3 最黔线 | 10 | 0 | 0.5 | 3 | 13.5 |
| P4 尚宫厨 | 8 | 0 | 0.5 | 3 | 11.5 |
| P5 IoT | 5 | 0 | 3 | 2 | 10 |
| P6 商业 | 0 | 0 | 0 | 8 | 8 |
| P7 稳定性 | 2 | 0 | 2 | 0 | 4 |
| **合计** | **34** | **1.5** | **9** | **17.5** | **62** |

---

## 风险登记簿

| ID | 风险 | 概率 | 影响 | 应对 | Owner |
|----|------|------|------|------|-------|
| R1 | POS API 限制/不开放 | 中 | 高 | 优先确认 API; 备选 RPA 抓取 | 商务 |
| R2 | 单服务器性能瓶颈 | 低 | 中 | CDN 分流; 异步重计算; 预备 8C16G 升级 | 运维 |
| R3 | 商户 IT 配合度低 | 中 | 中 | 傻瓜 SOP; 屯象全程驻场 | 运营 |
| R4 | 耳机蓝牙不稳定 | 中 | 低 | 预烧固件; 定期 OTA; 备用耳机 | 运维 |
| R5 | 客户付费意愿不足 | 中 | 高 | 首月免费试用; 按效果付费条款 | 商务 |
| R6 | Schema 迁移数据丢失 | 低 | 高 | 迁移前全量备份; 双写验证期 | 后端 |
| R7 | 泛域名 SSL 审批慢 | 低 | 中 | 提前申请; 备选单域名证书 | 运维 |

---

*生成日期: 2026-03-12 | 基于代码库 commit 6886922*
