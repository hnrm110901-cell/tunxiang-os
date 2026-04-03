/**
 * TXBridge — 安卓 POS 外设桥接抽象层
 *
 * 安卓环境：通过 window.TXBridge 调用 Kotlin JS Bridge（商米 SDK）
 * iPad/浏览器：通过 HTTP 转发到安卓 POS 主机执行
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

/** 获取安卓 POS 主机 URL（iPad/浏览器环境用 HTTP 转发外设指令） */
let _posHostUrl: string | null = null;
export const getPosMachineUrl = (): string => {
  if (_posHostUrl) return _posHostUrl;
  if (isAndroidPOS() && window.TXBridge) {
    _posHostUrl = window.TXBridge.getMacMiniUrl();
  }
  return _posHostUrl || 'http://localhost:8000';
};

/** 获取 Mac mini 本地 API 地址 */
export const getMacMiniUrl = (): string => {
  if (isAndroidPOS() && window.TXBridge) {
    return window.TXBridge.getMacMiniUrl();
  }
  return 'http://localhost:8000';
};

/** 打印小票 */
export const printReceipt = async (escPosContent: string): Promise<void> => {
  if (isAndroidPOS() && window.TXBridge) {
    window.TXBridge.print(escPosContent);
  } else {
    await fetch(`${getPosMachineUrl()}/api/print`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: escPosContent }),
    });
  }
};

/** 弹出钱箱 */
export const openCashBox = async (): Promise<void> => {
  if (isAndroidPOS() && window.TXBridge) {
    window.TXBridge.openCashBox();
  } else {
    await fetch(`${getPosMachineUrl()}/api/cash-box`, { method: 'POST' });
  }
};

/** 扫码 */
export const startScan = (): Promise<string> => {
  return new Promise((resolve) => {
    if (isAndroidPOS() && window.TXBridge) {
      const callbackName = `__txScanCb_${Date.now()}`;
      (window as unknown as Record<string, unknown>)[callbackName] = (result: string) => {
        delete (window as unknown as Record<string, unknown>)[callbackName];
        resolve(result);
      };
      window.TXBridge.scan();
      window.TXBridge.onScanResult(callbackName);
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
  return { model: 'browser', serial: 'dev' };
};

/** 开始监听电子秤 */
export const startScale = (): void => {
  if (isAndroidPOS() && window.TXBridge) {
    window.TXBridge.startScale();
  }
};

/** 停止监听电子秤 */
export const stopScale = (): void => {
  if (isAndroidPOS() && window.TXBridge) {
    (window.TXBridge as NativeTXBridge & { stopScale?: () => void }).stopScale?.();
  }
};

/**
 * 监听称重回调（返回 cleanup 函数）
 * 真实商米秤通过 onScaleData 推送数据，格式: "S,ST,+001.350kg"（稳定）或 "S,US,+001.350kg"（不稳定）
 */
export const onScaleWeight = (
  callback: (kg: number, stable: boolean) => void,
): (() => void) => {
  if (isAndroidPOS() && window.TXBridge) {
    const cbName = `__txScale_${Date.now()}`;
    (window as unknown as Record<string, unknown>)[cbName] = (raw: string) => {
      // 商米秤数据格式: "S,ST,+001.350kg"(稳定) 或 "S,US,+001.350kg"(不稳定)
      const stable = raw.includes(',ST,');
      const match = raw.match(/([0-9.]+)kg/);
      if (match) callback(parseFloat(match[1]), stable);
    };
    window.TXBridge.onScaleData(cbName);
    return () => {
      delete (window as unknown as Record<string, unknown>)[cbName];
    };
  } else {
    // 开发模式：模拟秤数据（每500ms随机波动，3秒后稳定）
    let count = 0;
    const mockWeight = 1.2 + Math.random() * 0.5;
    const timer = setInterval(() => {
      count++;
      const stable = count > 6;
      const weight = stable ? mockWeight : mockWeight + (Math.random() - 0.5) * 0.05;
      callback(parseFloat(weight.toFixed(3)), stable);
    }, 500);
    return () => clearInterval(timer);
  }
};
