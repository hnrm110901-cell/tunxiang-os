# Edge节点 GitOps 配置说明

## 概述

Edge节点（mac-station）运行在餐厅本地Mac Mini上，提供本地化AI推理、
离线容错、POS对接等能力。Edge节点**不进K8s集群**，通过GitOps配置同步机制
管理配置变更。

## 配置层级

```
边缘配置优先级（低→高，高优先级覆盖低优先级同名字段）：

全局默认配置
    └── 品牌级配置（brand/<brand_id>/config.yaml）
            └── 门店级配置（store/<store_id>/config.yaml）
                    └── 节点级配置（store/<store_id>/nodes/<node_id>.yaml，可选）
```

## 目录结构

```
edge/
├── README.md                       # 本文件
├── brand/                          # 品牌级配置（适用于同品牌所有门店）
│   ├── pilot_brand_001/
│   │   └── config.yaml             # 试点品牌配置
│   └── <brand_id>/
│       └── config.yaml
└── store/                          # 门店级配置（覆盖品牌配置特定字段）
    ├── store_001/
    │   └── config.yaml             # 一号门店特定配置
    └── <store_id>/
        └── config.yaml
```

## 同步机制

### sync-engine 工作流程

```
┌─────────────────────────────────────────────────────┐
│                    Mac Mini (Edge)                   │
│                                                      │
│  ┌──────────────┐   pull配置   ┌──────────────────┐  │
│  │  sync-engine │ ──────────► │  GitHub/GitLab   │  │
│  │  (Port 8100) │             │  (本仓库)         │  │
│  └──────┬───────┘             └──────────────────┘  │
│         │ 配置变更通知                                │
│         ▼                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │  mac-station │  │coreml-bridge │  │  POS适配器 │  │
│  │  (Port 8050) │  │  (Port 8100) │  │           │  │
│  └──────────────┘  └──────────────┘  └───────────┘  │
└─────────────────────────────────────────────────────┘
```

### 同步策略

| 配置项 | 说明 |
|--------|------|
| 同步间隔 | 默认300秒（5分钟），可按品牌/门店覆盖 |
| 增量同步 | 启用delta_sync时仅同步变更部分，减少带宽 |
| 离线保障 | 网络断开时沿用本地缓存配置，不影响门店运营 |
| 配置校验 | sync-engine对配置进行schema校验，非法配置不生效 |
| 回滚机制 | 配置应用失败自动回滚到上一个有效配置 |

## 配置变更流程

1. 提交配置变更PR到本仓库
2. SRE Review并合并到main分支
3. Harness Pipeline 触发 `gitops-edge-sync` 流水线
4. Pipeline通知对应品牌/门店的sync-engine拉取最新配置
5. sync-engine校验配置并热重载（无需重启服务）
6. 企微Bot发送变更通知给品牌SRE

## 敏感配置说明

Edge节点的敏感配置（数据库连接串、API Key等）**不存储在本目录**，
通过以下方式管理：
- mac-station本地加密存储（Keychain）
- 通过Harness Secrets下发，sync-engine解密后写入本地加密存储
- 轮换周期：90天

## 运维命令

```bash
# 手动触发门店配置同步（SSH到mac-mini后执行）
curl -X POST http://localhost:8100/api/sync/force -H "Authorization: Bearer $SYNC_TOKEN"

# 查看当前生效配置
curl http://localhost:8100/api/config/current

# 查看同步历史
curl http://localhost:8100/api/sync/history?limit=10
```
