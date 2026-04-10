# GitOps 目录结构说明

## 概述

本目录管理屯象OS各环境的Helm values覆盖配置及Edge节点同步配置，
配合 `/infra/helm/` 中的基础Chart，通过环境差异化覆盖实现多环境管理。

## 目录结构

```
gitops/
├── dev/                        # 开发环境（本地/腾讯云dev命名空间）
│   └── api-gateway/
│       └── values-override.yaml
├── test/                       # 测试环境（集成测试）
│   └── api-gateway/
│       └── values-override.yaml
├── uat/                        # UAT验收环境
│   └── api-gateway/
│       └── values-override.yaml
├── pilot/                      # Pilot试点环境（真实品牌小流量验证）
│   └── api-gateway/
│       └── values-override.yaml
├── prod/                       # 生产环境（TKE集群）
│   ├── api-gateway/
│   ├── tx-agent/
│   └── web-admin/
└── edge/                       # Edge节点配置（mac-station，不进K8s）
    ├── README.md
    ├── brand/                  # 品牌级配置
    │   └── pilot_brand_001/
    └── store/                  # 门店级配置（继承品牌配置）
        └── store_001/
```

## 各环境配置差异点

| 配置项 | dev | test | uat | pilot | prod |
|--------|-----|------|-----|-------|------|
| replicaCount | 1 | 1 | 2 | 2 | 3 |
| image.tag | latest | latest | latest | 指定版本 | ${IMAGE_TAG} |
| CPU limit | 200m | 200m | 300m | 400m | 500m |
| Memory limit | 256Mi | 256Mi | 384Mi | 512Mi | 512Mi |
| LOG_LEVEL | debug | debug | info | info | info |
| autoscaling | 关 | 关 | 关 | 关 | 开（3-10） |
| TLS | 可选 | 可选 | 是 | 是 | 是 |

## Helm部署命令

```bash
# dev环境部署
helm upgrade --install api-gateway ./infra/helm/api-gateway \
  -f ./gitops/dev/api-gateway/values-override.yaml \
  -n tunxiang-dev

# prod环境部署（由Harness CD执行，IMAGE_TAG由流水线注入）
helm upgrade --install api-gateway ./infra/helm/api-gateway \
  -f ./gitops/prod/api-gateway/values-override.yaml \
  --set image.tag=${IMAGE_TAG} \
  -n tunxiang-prod
```

## Edge节点配置说明

Edge节点（mac-station）运行在餐厅本地Mac Mini上，**不进K8s集群**，
采用GitOps配置同步机制：

- **同步方式**: sync-engine服务定期（默认5分钟）拉取本目录下的配置变更
- **配置层级**: 品牌级配置（brand/）> 门店级配置（store/）> 节点级配置
- **合并策略**: 门店配置覆盖品牌配置中的同名字段
- **离线保障**: 配置同步失败时沿用本地缓存配置，不影响门店运营
- **变更通知**: 配置变更后企微Bot自动通知对应品牌SRE

详见 `edge/README.md`。

## 注意事项

- `prod/` 目录下的配置变更须经过 GitOps Pipeline 审批（sre_group）方可生效
- `image.tag: ${IMAGE_TAG}` 是占位符，由Harness CD在部署时替换为实际镜像Tag
- Secret（DB_URL、API Key等）不在此目录管理，通过腾讯云SSM + K8s External Secret注入
