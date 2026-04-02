/**
 * Windows POS 壳 — Electron 主进程
 * TXBridge.print → 可选 node-printer RAW（Windows 热敏/针打）；未安装依赖时仅打日志。
 */
const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');

/** @type {null | { printDirect: Function, getPrinters?: Function, getDefaultPrinterName?: Function }} */
let printerMod = null;
try {
  // npm 包名 `printer`（node-printer），仅 Windows 生产环境建议安装并 npx electron-rebuild
  printerMod = require('printer');
} catch {
  printerMod = null;
}

function resolvePrinterName() {
  const envName = process.env.TX_PRINTER_NAME;
  if (envName) return envName;
  if (!printerMod) return '';
  if (typeof printerMod.getDefaultPrinterName === 'function') {
    try {
      const n = printerMod.getDefaultPrinterName();
      if (n) return n;
    } catch {
      /* ignore */
    }
  }
  if (typeof printerMod.getPrinters === 'function') {
    try {
      const list = printerMod.getPrinters() || [];
      if (list[0]?.name) return list[0].name;
    } catch {
      /* ignore */
    }
  }
  return '';
}

function printRawEscPos(content) {
  const payload = typeof content === 'string' ? Buffer.from(content, 'utf8') : Buffer.from(content);
  const name = resolvePrinterName();
  if (!printerMod || typeof printerMod.printDirect !== 'function' || !name) {
    console.log('[TXBridge.print] fallback (no printer module or TX_PRINTER_NAME)', payload.slice(0, 120).toString('hex'));
    return;
  }
  printerMod.printDirect({
    data: payload,
    printer: name,
    type: 'RAW',
    success: (jobId) => {
      console.log('[TXBridge.print] job', jobId, 'printer', name);
    },
    error: (err) => {
      console.error('[TXBridge.print]', err);
    },
  });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 600,
    title: '屯象OS POS',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  const startUrl = process.env.TX_POS_URL || 'http://localhost:5173';
  win.loadURL(startUrl).catch((err) => {
    console.error('[windows-pos-shell] loadURL failed:', startUrl, err);
  });

  if (process.env.TX_DEVTOOLS === '1') {
    win.webContents.openDevTools({ mode: 'detach' });
  }
}

ipcMain.on('tx-bridge-print', (_evt, content) => {
  printRawEscPos(content);
});

ipcMain.on('tx-bridge-cashbox', () => {
  console.log('[TXBridge.openCashBox] noop (wire USB relay in production)');
});

ipcMain.on('tx-bridge-scale-start', () => {
  console.log('[TXBridge.startScale] noop');
});

ipcMain.on('tx-bridge-scan', () => {
  console.log('[TXBridge.scan] noop');
});

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
