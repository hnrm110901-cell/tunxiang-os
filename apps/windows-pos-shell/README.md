# Windows POS 壳（Electron）

门店若使用 **Windows PC + 浏览器/Electron** 运行与 `web-pos` 同一套 React 应用时，通过本壳注入 `window.TXBridge`，与安卓商米壳的 JavaScript 接口保持一致，便于外设能力后续接 USB 打印/钱箱等（当前为 **占位实现**，日志走主进程 `tx-bridge-*` 事件，可扩展为 `node-usb` / 厂商 DLL）。

## 前置

1. 启动网关/API（如需真数据）：`localhost:8000`
2. 启动 `apps/web-pos`：`npm run dev`（默认 `http://localhost:5173`）

## 运行

```bash
cd apps/windows-pos-shell
npm install
npm start
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `TX_POS_URL` | 覆盖加载的 Web App URL（默认 `http://localhost:5173`） |
| `TX_MAC_MINI_URL` | `getMacMiniUrl()` 返回值（边缘 Mac mini 局域网地址） |
| `TX_PRINTER_NAME` | Windows 打印机名称（与「设备和打印机」中一致）；不设置时尝试 `printer` 模块的默认打印机 |
| `TX_DEVTOOLS=1` | 打开 DevTools |

## Windows 真机打印（ESC/POS RAW）

1. **仅建议在 Windows x64** 安装原生模块：`npm install`（`optionalDependencies` 中的 `printer`）。
2. 与当前 Electron 版本 ABI 对齐：`npm run rebuild`（内部为 `electron-rebuild -f -w printer`）。
3. React 中 `window.TXBridge.print(content)` 传入 **ESC/POS 字节串或 UTF-8 文本**；主进程以 **RAW** 方式提交至 `TX_PRINTER_NAME` 指定打印机。
4. 未安装 `printer` 或重建失败时：**不抛错**，仅在控制台输出十六进制预览（与开发期行为一致）。

## 与安卓壳的差异

- 称重/扫码仍为 **占位**；打印已可走 **RAW**（依赖本机驱动与 `printer` 模块）。
- iPad 场景仍建议通过 HTTP 将打印指令转发到 **安卓 POS 主机**（见 `CLAUDE.md` 壳层规范）。
