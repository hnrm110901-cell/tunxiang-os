# 新店上线 SOP（标准操作流程）

> 目标：新店上线 ≤ 半天（4小时）

## 物料清单

| 设备 | 型号 | 数量 | 备注 |
|------|------|------|------|
| 安卓 POS 主机 | 商米 T2/V2 | 1 | 含内置打印机 |
| Mac mini M4 | 16GB/256GB | 1 | 含电源线 |
| 安卓 KDS 平板 | 商米 D2 | 1-2 | 后厨出餐屏 |
| 路由器 | 任意千兆 | 1 | 门店局域网 |
| 网线 | Cat6 | 2 | Mac mini + POS |
| UPS | ~200元 | 1 | Mac mini 断电保护 |
| iPad（可选） | Air/Pro | 0-1 | 高端店升级 |

## 上线步骤

### Phase 1: 硬件部署（约 30 分钟）

1. 安装路由器，确认网络通畅
2. Mac mini 连接电源 + 网线，开机
3. 安卓 POS 连接 WiFi + USB 外设（打印机/秤/钱箱）
4. KDS 平板连接 WiFi

### Phase 2: 软件配置（约 30 分钟）

```bash
./scripts/new_store_setup.sh \
  --store-name="门店名" \
  --store-code="STORE-CODE" \
  --brand-id="brand_xxx" \
  --tenant-id="tenant-uuid" \
  --mac-mini-ip="192.168.1.100" \
  --tailscale-key="tskey-xxx"
```

脚本自动完成：
- Mac mini 服务部署（mac-station + sync-engine + coreml-bridge）
- Tailscale VPN 连接
- 门店注册到云端
- 初始数据同步（菜品/员工/桌台）

### Phase 3: POS 配置（约 15 分钟）

1. 安卓 POS 安装 TunxiangPOS APK
2. 配置 Mac mini 地址
3. 测试打印/扫码/钱箱

### Phase 4: 验证测试（约 30 分钟）

- [ ] 开单 → 点菜 → 结算 → 打印小票（收银全流程）
- [ ] 厨房单打印到 KDS
- [ ] 微信支付/支付宝支付
- [ ] 断网后离线收银
- [ ] 恢复网络后数据同步
- [ ] 小程序扫码点餐
- [ ] 交接班报表

### Phase 5: 培训交接（约 2 小时）

1. 店长培训：日常操作 + 交接班 + 异常处理
2. 收银员培训：收银流程 + 退款流程
3. 厨师长培训：KDS 操作 + 催单

## 故障排查

| 问题 | 排查 |
|------|------|
| POS 无法连接 Mac mini | 检查同一 WiFi/网段，ping Mac mini IP |
| 打印机不出纸 | 检查 USB 连接，重启商米打印服务 |
| 断网无法收银 | Mac mini 本地 PG 应能继续工作，检查 mac-station 服务 |
| 数据未同步 | 检查 sync-engine 日志：`tail -f ~/tunxiang-os/logs/sync-engine.log` |
| Core ML 预测慢 | 检查模型是否加载：`curl http://localhost:8100/health` |
