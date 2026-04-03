/**
 * TXBridge — 多终端外设桥接抽象层
 *
 * 打印路径优先级：
 *   1. 安卓 POS：window.TXBridge.print()（商米 SDK）
 *   2. 蓝牙打印机：Web Bluetooth API（iPad/浏览器直连）
 *   3. 网络打印机：HTTP → Mac mini → TCP socket（局域网打印）
 *   4. 兜底：HTTP → 安卓 POS 转发
 */

/** 安卓 Kotlin 层注入的原生接口 */
interface NativeTXBridge {
  print(content: string): void;
  openCashBox(): void;
  startScale(): void;
  onScaleData(callback: string): void;
  scan(): void;
  onScanResult(callback: string): void;
  getDeviceInfo(): string;
  getMacMiniUrl(): string;
}

declare global {
  interface Window {
    TXBridge?: NativeTXBridge;
  }
}

/** 设备环境检测 */
export const isAndroidPOS = (): boolean => !!window.TXBridge;
export const isIPad = (): boolean => !window.TXBridge && /iPad/.test(navigator.userAgent);
export const isBrowser = (): boolean => !window.TXBridge && !isIPad();

/** Mac mini 地址（门店局域网） */
let _macMiniUrl: string | null = null;
export const getMacMiniUrl = (): string => {
  if (_macMiniUrl) return _macMiniUrl;
  if (isAndroidPOS() && window.TXBridge) {
    _macMiniUrl = window.TXBridge.getMacMiniUrl();
  }
  return _macMiniUrl || localStorage.getItem('tx_mac_mini_url') || 'http://localhost:8000';
};

/** 设置 Mac mini 地址（iPad 首次配置时调用） */
export const setMacMiniUrl = (url: string): void => {
  _macMiniUrl = url;
  localStorage.setItem('tx_mac_mini_url', url);
};

// ─── 蓝牙打印机 ───

let _bleDevice: BluetoothDevice | null = null;
let _bleCharacteristic: BluetoothRemoteGATTCharacteristic | null = null;

/** 蓝牙打印机是否可用 */
export const isBLEPrinterAvailable = (): boolean =>
  'bluetooth' in navigator && _bleCharacteristic !== null;

/** 连接蓝牙打印机（用户触发，弹出配对对话框） */
export const connectBLEPrinter = async (): Promise<boolean> => {
  if (!('bluetooth' in navigator)) {
    console.warn('Web Bluetooth API 不可用');
    return false;
  }

  try {
    // 扫描 ESC/POS 打印机（通用串口服务 UUID）
    _bleDevice = await navigator.bluetooth.requestDevice({
      filters: [
        { services: ['000018f0-0000-1000-8000-00805f9b34fb'] },  // 通用 ESC/POS 打印机
        { namePrefix: 'GP-' },   // 佳博
        { namePrefix: 'XP-' },   // 芯烨
        { namePrefix: 'PT-' },   // 精臣
        { namePrefix: 'HM-' },   // 汉印
      ],
      optionalServices: ['000018f0-0000-1000-8000-00805f9b34fb'],
    });

    if (!_bleDevice.gatt) return false;

    const server = await _bleDevice.gatt.connect();
    const service = await server.getPrimaryService('000018f0-0000-1000-8000-00805f9b34fb');
    _bleCharacteristic = await service.getCharacteristic('00002af1-0000-1000-8000-00805f9b34fb');

    console.log(`蓝牙打印机已连接: ${_bleDevice.name}`);
    return true;
  } catch (err) {
    console.error('蓝牙打印机连接失败:', err);
    _bleDevice = null;
    _bleCharacteristic = null;
    return false;
  }
};

/** 断开蓝牙打印机 */
export const disconnectBLEPrinter = (): void => {
  if (_bleDevice?.gatt?.connected) {
    _bleDevice.gatt.disconnect();
  }
  _bleDevice = null;
  _bleCharacteristic = null;
};

/** 通过蓝牙发送 ESC/POS 数据（分包发送，BLE 每包最大 512 字节） */
const _sendViaBLE = async (data: Uint8Array): Promise<boolean> => {
  if (!_bleCharacteristic) return false;

  const CHUNK_SIZE = 512;
  for (let offset = 0; offset < data.length; offset += CHUNK_SIZE) {
    const chunk = data.slice(offset, offset + CHUNK_SIZE);
    await _bleCharacteristic.writeValueWithResponse(chunk);
  }
  return true;
};

// ─── 打印（核心） ───

/**
 * 打印小票 — 自动选择最优通道
 *
 * @param escPosBase64 - ESC/POS 字节流的 base64 编码
 * @param printerId - 指定打印机 ID（可选，默认自动选择）
 */
export const printReceipt = async (
  escPosBase64: string,
  printerId?: string,
): Promise<{ ok: boolean; channel: string }> => {

  // 路径 1: 安卓 POS（商米 SDK 直连）
  if (isAndroidPOS() && window.TXBridge) {
    window.TXBridge.print(escPosBase64);
    return { ok: true, channel: 'android_sunmi' };
  }

  // 路径 2: 蓝牙打印机（iPad/浏览器直连，无需中转）
  if (isBLEPrinterAvailable()) {
    const bytes = Uint8Array.from(atob(escPosBase64), c => c.charCodeAt(0));
    const ok = await _sendViaBLE(bytes);
    if (ok) return { ok: true, channel: 'bluetooth' };
    // 蓝牙失败则 fallback 到网络打印机
  }

  // 路径 3: 网络打印机（通过 Mac mini TCP 转发）
  try {
    const resp = await fetch(`${getMacMiniUrl()}/api/print`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content_base64: escPosBase64,
        printer_id: printerId || '',
      }),
    });
    const result = await resp.json();
    return { ok: result.ok, channel: result.data?.channel || 'mac_mini' };
  } catch (err) {
    console.error('打印失败:', err);
    return { ok: false, channel: 'none' };
  }
};

// ─── 兼容旧接口（hex 字符串格式） ───

export const printReceiptHex = async (escPosHex: string): Promise<void> => {
  const bytes = new Uint8Array(escPosHex.match(/.{1,2}/g)!.map(b => parseInt(b, 16)));
  const base64 = btoa(String.fromCharCode(...bytes));
  await printReceipt(base64);
};

// ─── 其他外设 ───

/** 弹出钱箱 */
export const openCashBox = async (): Promise<void> => {
  if (isAndroidPOS() && window.TXBridge) {
    window.TXBridge.openCashBox();
  } else {
    await fetch(`${getMacMiniUrl()}/api/cash-box`, { method: 'POST' });
  }
};

/** 扫码 */
export const startScan = (): Promise<string> => {
  return new Promise((resolve) => {
    if (isAndroidPOS() && window.TXBridge) {
      const callbackName = `__txScanCb_${Date.now()}`;
      (window as Record<string, unknown>)[callbackName] = (result: string) => {
        delete (window as Record<string, unknown>)[callbackName];
        resolve(result);
      };
      window.TXBridge.scan();
      window.TXBridge.onScanResult(callbackName);
    } else if (isIPad()) {
      // iPad 用摄像头扫码（需要额外组件支持）
      resolve(prompt('请扫码（或手动输入条码）：') || '');
    } else {
      resolve(prompt('扫码结果（调试模式）：') || '');
    }
  });
};

/** 获取设备信息 */
export const getDeviceInfo = (): Record<string, string> => {
  if (isAndroidPOS() && window.TXBridge) {
    return JSON.parse(window.TXBridge.getDeviceInfo());
  }
  return {
    model: isIPad() ? 'iPad' : 'browser',
    serial: 'dev',
    blePrinter: _bleDevice?.name || 'none',
  };
};
