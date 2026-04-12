/**
 * PAD 布局适配 — 平板大屏优化 wrapper
 *
 * 自动检测 iPad / 安卓平板，调整字号和触控区域：
 * - 字号放大 (base 18px vs 手机 16px)
 * - 触控区域放大 (56px minimum vs 48px)
 * - 横屏优化：利用宽屏空间
 * - 不连接任何外设：外设指令通过 WiFi 发到安卓 POS 执行
 *
 * 用法: 包裹需要平板适配的页面
 *   <PadLayout><OrderPage /></PadLayout>
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

// ─── 设备检测 ──────────────────────────────────────────────────────────────────

interface DeviceInfo {
  isPad: boolean;
  isIPad: boolean;
  isAndroidTablet: boolean;
  isLandscape: boolean;
  screenWidth: number;
  screenHeight: number;
  hasNativeBridge: boolean;
}

function detectDevice(): DeviceInfo {
  const ua = navigator.userAgent;
  const isIPad = /iPad/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isAndroidTablet = /Android/.test(ua) && !/Mobile/.test(ua);
  const isPad = isIPad || isAndroidTablet || (window.innerWidth >= 768 && 'ontouchstart' in window);
  const isLandscape = window.innerWidth > window.innerHeight;
  const hasNativeBridge = !!(window as unknown as Record<string, unknown>).TXBridge;

  return {
    isPad,
    isIPad,
    isAndroidTablet,
    isLandscape,
    screenWidth: window.innerWidth,
    screenHeight: window.innerHeight,
    hasNativeBridge,
  };
}

// ─── Context ──────────────────────────────────────────────────────────────────

const PadContext = createContext<DeviceInfo>({
  isPad: false, isIPad: false, isAndroidTablet: false,
  isLandscape: true, screenWidth: 1024, screenHeight: 768, hasNativeBridge: false,
});

export function usePadInfo(): DeviceInfo {
  return useContext(PadContext);
}

// ─── PAD 设计 Token ──────────────────────────────────────────────────────────

export const PAD_TOKENS = {
  // 字号（比手机端放大一档）
  fontBase: 18,
  fontSmall: 15,
  fontLarge: 22,
  fontTitle: 26,
  fontPrice: 24,

  // 触控区域（iPad 大屏，放大到 56px 基准）
  touchMin: 56,
  touchLarge: 72,
  touchCritical: 80,  // 支付等关键操作

  // 间距
  gap: 14,
  padding: 18,
  cardRadius: 12,

  // 网格
  dishGridMinWidth: 160,  // 菜品卡片最小宽度（手机端 140px）
  cartWidth: 380,          // 购物车宽度（手机端 340px）
  categoryWidth: 130,      // 分类栏宽度（手机端 110px）
} as const;

// ─── 主组件 ──────────────────────────────────────────────────────────────────

interface PadLayoutProps {
  children: ReactNode;
  /** 是否强制启用PAD模式（调试用） */
  forcePad?: boolean;
}

export function PadLayout({ children, forcePad }: PadLayoutProps) {
  const [device, setDevice] = useState<DeviceInfo>(detectDevice);

  useEffect(() => {
    const handleResize = () => setDevice(detectDevice());
    window.addEventListener('resize', handleResize);
    window.addEventListener('orientationchange', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('orientationchange', handleResize);
    };
  }, []);

  const isPadMode = forcePad || device.isPad;

  return (
    <PadContext.Provider value={device}>
      <div
        style={{
          // PAD 模式下调整 CSS 变量
          fontSize: isPadMode ? PAD_TOKENS.fontBase : 16,
          // 全屏
          minHeight: '100vh',
          background: '#0B1A20',
          color: '#fff',
          fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
          // PAD 模式提示（仅开发环境）
          ...(isPadMode && import.meta.env.DEV ? { outline: '2px solid rgba(255,107,53,0.2)' } : {}),
        }}
        data-pad-mode={isPadMode ? 'true' : 'false'}
        data-device={device.isIPad ? 'ipad' : device.isAndroidTablet ? 'android-tablet' : 'phone'}
      >
        {children}

        {/* PAD 外设桥接提示：iPad 无 TXBridge，打印等通过 HTTP 发到安卓 POS */}
        {isPadMode && !device.hasNativeBridge && (
          <div style={{
            position: 'fixed', bottom: 8, right: 8,
            padding: '4px 10px', borderRadius: 6,
            background: 'rgba(24,95,165,0.15)', color: '#185FA5',
            fontSize: 12, pointerEvents: 'none', zIndex: 10,
          }}>
            PAD · 外设桥接 → POS
          </div>
        )}
      </div>
    </PadContext.Provider>
  );
}

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

/**
 * 获取 POS 主机地址（iPad 发送外设指令用）
 * 优先从环境变量读取，其次从 localStorage
 */
export function getPosHostUrl(): string {
  return import.meta.env.VITE_POS_HOST_URL
    || localStorage.getItem('pos_host_url')
    || 'http://192.168.1.100:8080';
}

/**
 * 通过 HTTP 发送外设指令到安卓 POS（iPad/浏览器环境使用）
 */
export async function sendToPOS(action: string, payload: Record<string, unknown> = {}): Promise<void> {
  const bridge = (window as unknown as Record<string, unknown>).TXBridge as Record<string, Function> | undefined;
  if (bridge && typeof bridge[action] === 'function') {
    // 安卓 POS 环境：直接调用 JS Bridge
    bridge[action](JSON.stringify(payload));
  } else {
    // iPad/浏览器：HTTP 转发到安卓 POS
    await fetch(`${getPosHostUrl()}/api/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }
}
