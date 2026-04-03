/**
 * 预加载脚本 — 向渲染进程暴露 window.TXBridge（占位实现，与安卓 Kotlin 桥签名对齐）
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('TXBridge', {
  print(content) {
    ipcRenderer.send('tx-bridge-print', content);
  },
  openCashBox() {
    ipcRenderer.send('tx-bridge-cashbox');
  },
  startScale() {
    ipcRenderer.send('tx-bridge-scale-start');
  },
  onScaleData(callback) {
    if (typeof callback !== 'function') return;
    ipcRenderer.on('tx-bridge-scale-data', (_evt, payload) => {
      callback(String(payload));
    });
  },
  scan() {
    ipcRenderer.send('tx-bridge-scan');
  },
  onScanResult(callback) {
    if (typeof callback !== 'function') return;
    ipcRenderer.on('tx-bridge-scan-result', (_evt, payload) => {
      callback(String(payload));
    });
  },
  getDeviceInfo() {
    return JSON.stringify({
      platform: 'win32',
      shell: 'windows-pos-shell',
      electron: process.versions.electron,
    });
  },
  getMacMiniUrl() {
    return process.env.TX_MAC_MINI_URL || '';
  },
});
