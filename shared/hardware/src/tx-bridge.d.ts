/**
 * TXBridge -- 屯象 POS 安卓壳层 JS Bridge 类型声明
 *
 * 安卓 POS 设备通过 WebView 的 addJavascriptInterface 注入 window.TXBridge。
 * React Web App 通过此接口调用安卓原生能力（打印/扫码/称重/钱箱等）。
 *
 * 使用前检查：
 *   if (window.TXBridge) { ... }  // 安卓 POS 环境
 *   else { ... }                  // 浏览器/iPad 环境，通过 HTTP 转发到安卓 POS
 *
 * 商米目标机型：T2（双屏收银机）/ V2（手持 POS）
 */
interface TXBridge {
  /**
   * ESC/POS 打印（小票/厨房单/标签）。
   * @param content ESC/POS 格式字符串或 JSON 打印指令
   *
   * JSON 格式：
   *   { "type": "receipt" | "kitchen" | "label", "content": "...", "copies": 1 }
   */
  print(content: string): void;

  /**
   * 弹出钱箱。
   * T2: 通过打印机 RJ11 端口 ESC 指令驱动
   * V2: 通过 Cash Drawer API
   */
  openCashBox(): void;

  /**
   * 启动扫码（商米内置扫码器 / 相机降级）。
   * 扫码结果通过 window.__txScanCallback(barcode) 回调。
   * 可通过 onScanResult() 自定义回调函数名。
   */
  scan(): void;

  /**
   * 开始监听电子秤数据流。
   * 数据通过 window.__txScaleCallback({ weight, unit, stable }) 持续回调。
   * 可通过 onScaleData() 自定义回调函数名。
   */
  startScale(): void;

  /**
   * 返回设备基础信息 JSON 字符串。
   *
   * 返回值示例：
   *   {
   *     "model": "T2",
   *     "manufacturer": "SUNMI",
   *     "serial": "SN123456",
   *     "osVersion": "8.1.0",
   *     "sdkInt": 27,
   *     "isSunmi": true,
   *     "isSupported": true,
   *     "isSunmiT2": true,
   *     "isSunmiV2": false,
   *     "appVersion": "0.1.0",
   *     "appVersionCode": 1
   *   }
   */
  getDeviceInfo(): string;

  /**
   * 返回局域网内 Mac mini 边缘服务地址。
   * @returns URL 字符串，如 "http://192.168.1.100:8000"
   */
  getMacMiniUrl(): string;

  /**
   * 设备震动。
   * @param ms 震动时长（毫秒），上限 5000ms
   */
  vibrate(ms: number): void;

  /**
   * 播放提示音。
   * @param type 提示音类型：
   *   - "success" -- 操作成功（如收款完成）
   *   - "error"   -- 操作失败
   *   - "scan"    -- 扫码成功提示
   *   - "alert"   -- 预警提示（如 Agent 预警）
   */
  playSound(type: string): void;

  /**
   * 设置屏幕常亮状态。
   * POS 设备默认应保持常亮（收银场景）。
   * @param keep true=屏幕常亮，false=恢复系统默认休眠
   */
  setKeepScreenOn(keep: boolean): void;
}

/** 设备信息（getDeviceInfo() 返回值解析后的类型） */
interface TXDeviceInfo {
  model: string;
  manufacturer: string;
  serial: string;
  osVersion: string;
  sdkInt: number;
  isSunmi: boolean;
  isSupported: boolean;
  isSunmiT2: boolean;
  isSunmiV2: boolean;
  appVersion: string;
  appVersionCode: number;
}

/** 电子秤数据回调参数 */
interface TXScaleData {
  /** 重量值 */
  weight: number;
  /** 重量单位（"kg" | "g" | "lb"） */
  unit: string;
  /** 是否稳定（称台静止） */
  stable: boolean;
}

/** 打印指令 JSON 格式 */
interface TXPrintCommand {
  /** 打印类型 */
  type: 'receipt' | 'kitchen' | 'label';
  /** 打印内容（ESC/POS 格式） */
  content: string;
  /** 打印份数，默认 1 */
  copies?: number;
}

/** 网络状态变化事件 detail */
interface TXNetworkChangeDetail {
  online: boolean;
}

declare global {
  interface Window {
    /** 屯象 POS JS Bridge（仅在安卓 POS WebView 环境中存在） */
    TXBridge?: TXBridge;
  }

  interface WindowEventMap {
    /** 网络状态变化事件（由安卓壳层触发） */
    txNetworkChange: CustomEvent<TXNetworkChangeDetail>;
  }
}

export {
  TXBridge,
  TXDeviceInfo,
  TXScaleData,
  TXPrintCommand,
  TXNetworkChangeDetail,
};
