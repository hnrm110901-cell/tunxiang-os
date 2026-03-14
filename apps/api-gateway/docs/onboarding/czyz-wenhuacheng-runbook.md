# 尝在一起文化城店 — 正式接入 Runbook

**门店**: 尝在一起文化城店
**内部 Store ID**: CZYZ-2461
**POS 系统**: 品智收银
**边缘设备**: Raspberry Pi 5 8GB
**执行日期**: 2026-03-14
**执行人**: 运营工程师

---

## 零、安装包在哪里

```
apps/api-gateway/
├── edge/                          ← 树莓派端运行文件
│   ├── edge_node_agent.py         主进程（注册+心跳+离线队列）
│   ├── shokz_callback_daemon.py   Shokz 回调守护（含蓝牙层）
│   ├── shokz_bluetooth_manager.py 真实 BlueZ 蓝牙执行层
│   ├── edge_model_manager.py      本地 AI 模型管理
│   ├── edge_business_queue.py     离线业务事件队列
│   ├── edge_health_check.py       现场运维诊断 CLI
│   ├── zhilian-edge-node.service  systemd 主服务
│   └── zhilian-edge-shokz.service systemd Shokz 服务
│
└── scripts/
    ├── install_raspberry_pi_edge.sh        一键安装（在 Pi 上执行）
    ├── install_raspberry_pi_edge_remote.sh SSH 远程安装（在开发机执行）
    ├── onboard_store.sh                    门店接入一键脚本
    ├── build_edge_image.sh                 Pi OS 定制镜像构建
    └── batch_deploy_edge.py                批量多门店部署
```

**快速路径**：开发机 SSH 远程安装，3 分钟完成，无需人到现场。

---

## 一、前置核对清单

| 项目 | 值 | 状态 |
|------|-----|------|
| 品智 API 地址 | `https://czyq.pinzhikeji.net/api/v1` | ✅ 已确认 |
| 品智品牌 Token | `3bbc9bed2b42c1e1b3cca26389fbb81c` | ✅ 已确认 |
| 品智门店 ID | `2461` | ✅ 已确认 |
| 品智门店 Token | `752b4b16a863ce47def11cf33b1b521f` | ✅ 已确认 |
| 奥琦玮 AppID | `dp25MLoc2gnXE7A223ZiVv` | ✅ 已确认 |
| 奥琦玮 AppKey | `3d2eaa5f9b9a6a6746a18d28e770b501` | ✅ 已确认 |
| 奥琦玮 MerchantID | `1275413383` | ✅ 已确认 |
| Pi5 IP（有线 eth0） | `192.168.110.96` | ✅ 已确认 |
| Pi5 IP（无线 wlan0） | `192.168.110.95`（备用） | ✅ 已确认 |
| Pi5 SSH 用户名 | `pi`（默认） | ✅ |
| Docker 已安装 | Pi5 已运行 docker0=172.17.0.1 | ✅ 已确认 |
| Shokz 耳机 MAC 地址 | 需现场确认 | ⬜ 待填 |

---

## 二、管理后台配置（PlatformIntegrationsPage）

### 步骤 1 — 新增品智收银接入配置

访问：`https://admin.zlsjos.cn/platform/integrations` → 点击「新增接入配置」

填写：
```
配置名称: 尝在一起文化城店-品智收银
系统类型: 品智收银 (pinzhi_pos)
API地址:  https://czyq.pinzhikeji.net/api/v1  ← 已预填
API Token: 752b4b16a863ce47def11cf33b1b521f   ← 门店专属 Token（非品牌 Token）
```

保存后记录生成的 **Integration ID**（后续数据同步需要）。

### 步骤 2 — 新增奥琦玮会员接入配置

```
配置名称: 尝在一起文化城店-奥琦玮会员
系统类型: 奥琦玮微生活会员 (aoqiwei_crm)
API地址:  https://api.acewill.net              ← 已预填
AppID:    dp25MLoc2gnXE7A223ZiVv
AppKey:   3d2eaa5f9b9a6a6746a18d28e770b501
```

### 步骤 3 — 生成 Bootstrap Token（动态 Token，7 天有效）

在管理后台 → 接入配置 → Bootstrap Token 管理，或调用 API：

```bash
curl -X POST https://api.zlsjos.cn/api/v1/hardware/admin/bootstrap-token/issue \
  -H "Authorization: Bearer <管理员JWT>" \
  -H "Content-Type: application/json" \
  -d '{
    "note": "尝在一起文化城店 2026-03-14",
    "store_id": "CZYZ-2461",
    "ttl_days": 7
  }'
```

**响应（明文 Token 仅出现一次，立即复制）**：
```json
{
  "success": true,
  "token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "warning": "此 Token 仅显示一次，请立即复制保存",
  "ttl_days": 7
}
```

将 Token 记为 `BOOTSTRAP_TOKEN=<上面复制的值>`。

---

## 三、树莓派 5 安装

### 方式 A — 一键接入脚本（推荐，自动发放 Token + 执行安装）

```bash
# 在开发机执行，替换 <管理员JWT>
cd apps/api-gateway

bash scripts/onboard_store.sh \
  --api-url    https://api.zlsjos.cn \
  --admin-jwt  <管理员JWT> \
  --store-id   CZYZ-2461 \
  --store-name "尝在一起文化城店" \
  --pi-ip      192.168.110.96 \
  --execute
```

此命令会自动：① 从云端发放 Bootstrap Token → ② SSH 安装边缘层 → ③ 运行 zhilian-check 验证

### 方式 B — SSH 手动安装（有 Bootstrap Token 后执行）

```bash
cd apps/api-gateway

sudo EDGE_API_BASE_URL=https://api.zlsjos.cn \
     EDGE_API_TOKEN=<BOOTSTRAP_TOKEN> \
     EDGE_STORE_ID=CZYZ-2461 \
     EDGE_DEVICE_NAME=czyz-wenhuacheng-rpi5 \
     EDGE_SHOKZ_CALLBACK_SECRET=czyz2461shokz \
     REMOTE_HOST=192.168.110.96 \
     REMOTE_USER=pi \
     bash scripts/install_raspberry_pi_edge_remote.sh
```

安装完成输出示例：
```
屯象OS 边缘节点安装完成。
配置文件 : /etc/zhilian-edge/edge-node.env
状态文件 : /var/lib/zhilian-edge/node_state.json
主服务   : zhilian-edge-node.service ● active
Shokz服务: zhilian-edge-shokz.service ● active
健康检查 : zhilian-check
模型管理 : zhilian-models
事件队列 : zhilian-queue
```

### 方式 C — 现场在 Pi 上执行

```bash
ssh pi@192.168.110.96
cd /tmp
sudo EDGE_API_BASE_URL=https://api.zlsjos.cn \
     EDGE_API_TOKEN=<BOOTSTRAP_TOKEN> \
     EDGE_STORE_ID=CZYZ-2461 \
     EDGE_DEVICE_NAME=czyz-wenhuacheng-rpi5 \
     bash install.sh
```

---

## 四、安装后验证

### 4.1 健康检查（在 Pi 上执行）

```bash
ssh pi@192.168.110.96 "zhilian-check"
```

期望输出：
```
============================================================
  屯象OS 边缘节点健康报告  2026-03-14 14:30:00
  NodeID : czyz-wenhuacheng-rpi5-xxxx…
============================================================
  ✅ 节点注册         已注册 node_id=xxx device_secret=已设置
  ✅ API连通性        status=ok latency=45ms
  ✅ Shokz守护进程    运行中 latency=3ms
  ⚠️  蓝牙适配器       UP RUNNING（Shokz 尚未配对）
  ⚠️  本地AI模型       1/3 个模型未下载
  ✅ 离线业务队列     pending=0 failed=0
  ✅ 磁盘空间         已用 12.4% 剩余 110.2GB
  ✅ CPU温度          42.1°C
  ✅ systemd/zhilian-edge-node.service    active
  ✅ systemd/zhilian-edge-shokz.service   active
------------------------------------------------------------
  综合状态: ⚠️  WARN
============================================================
```

> ⚠️ WARN 状态正常（蓝牙未配对 + 模型未下载），执行 4.2 和 4.3 后变 OK。

### 4.2 Shokz 耳机配对

```bash
# 将耳机调为配对模式（长按电源键 5 秒，蓝灯闪烁）
ssh pi@192.168.110.96

# 扫描并配对
python3 /opt/zhilian-edge/shokz_bluetooth_manager.py
# 或通过云端回调触发：
curl -X POST http://192.168.110.96:9781/shokz/callback \
  -H "X-Edge-Callback-Secret: czyz2461shokz" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "connect_device",
    "device_id": "<SHOKZ_MAC>",
    "payload": {"mac_address": "<SHOKZ_MAC>"}
  }'
```

### 4.3 本地模型下载

```bash
ssh pi@192.168.110.96 "zhilian-models sync"
```

如模型有 download_url，自动下载；否则手动放置：
```bash
scp whisper-tiny.onnx pi@192.168.110.96:/var/lib/zhilian-edge/models/asr/whisper-tiny-zh/model.onnx
```

### 4.4 云端确认注册

在管理后台 → 硬件管理 → 边缘节点，确认看到：
```
设备名: czyz-wenhuacheng-rpi5
门店:   CZYZ-2461
状态:   online ●
心跳:   30秒内
```

---

## 五、品智 POS 数据回填

节点上线后，触发历史数据拉取（前 30 天）：

```bash
curl -X POST https://api.zlsjos.cn/api/v1/integrations/systems/<INTEGRATION_ID>/sync \
  -H "Authorization: Bearer <管理员JWT>"
```

或在管理后台接入配置页点击「测试连接」→ 确认返回绿色。

---

## 六、验收标准

| 检查项 | 期望值 | 方法 |
|--------|--------|------|
| 节点心跳 | ≤ 60s 内有上报 | 管理后台硬件页 |
| 品智接入测试 | 返回最近1条订单 | 接入配置页「测试」 |
| Shokz 语音播报 | 播报"连接成功" | 管理后台发 voice_output 命令 |
| 离线队列 | pending=0 | `zhilian-queue stats` |
| CPU 温度 | <70°C | `zhilian-check` |

---

## 七、常见问题

**Q: 注册失败 401**
A: Bootstrap Token 已过期或输错。到管理后台重新发放，7 天有效。

**Q: SSH 连接失败**
A: 确认 Pi5 在线（ping 192.168.110.96），SSH key 已配置或使用密码登录。备用 IP: 192.168.110.95（WiFi）

**Q: Shokz 连接失败**
A: 确认耳机在配对模式（蓝灯闪）；确认 Pi 的蓝牙适配器已启用 `sudo hciconfig hci0 up`

**Q: 品智接入测试失败**
A: 用门店专属 Token（752b4b16…），不要用品牌 Token（3bbc9bed…）

**Q: 健康检查整体 ERROR**
A: 运行 `zhilian-check --fix` 尝试自动重启失败服务

---

## 八、Bootstrap Token 已使用的安全提示

安装完成后，如 Token 不再需要，立即在管理后台吊销：

```bash
# 在 Pi 上查看 node_id
cat /var/lib/zhilian-edge/node_state.json

# 在管理后台列出 Token，找到对应 hash 后吊销
curl -X GET https://api.zlsjos.cn/api/v1/hardware/admin/bootstrap-token/list \
  -H "Authorization: Bearer <管理员JWT>"

curl -X POST https://api.zlsjos.cn/api/v1/hardware/admin/bootstrap-token/revoke/<TOKEN_HASH> \
  -H "Authorization: Bearer <管理员JWT>"
```
