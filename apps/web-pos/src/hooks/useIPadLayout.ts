import { useState, useEffect, useCallback, useMemo } from 'react';

/**
 * iPad 布局检测 Hook
 *
 * 检测当前运行环境是否为 iPad，并返回适配布局常量。
 * 支持：
 *   - iPad 检测（通过 userAgent 或 window.__TUNXIANG_PLATFORM__）
 *   - 横/竖屏方向检测
 *   - Split View 宽度检测
 *   - 安全区域
 *   - 布局常量（Sidebar 宽度、台位图格大小、数字键盘按钮大小等）
 *
 * 使用方式：
 *   const { isIPad, isLandscape, sidebarWidth, tableMapCellSize } = useIPadLayout();
 */

type Platform = 'ipad' | 'android-pos' | 'desktop' | 'unknown';

export interface IPadLayout {
  /** 是否为 iPad */
  isIPad: boolean;
  /** 当前平台 */
  platform: Platform;
  /** 横屏 */
  isLandscape: boolean;
  /** 竖屏 */
  isPortrait: boolean;
  /** 视口宽度 (pt) */
  viewportWidth: number;
  /** 视口高度 (pt) */
  viewportHeight: number;
  /** Sidebar 宽度 (pt)：竖屏 280 / 横屏 320 */
  sidebarWidth: number;
  /** 台位图格最小尺寸 (pt) */
  tableMapCellSize: number;
  /** 数字键盘按钮尺寸 (pt) */
  numPadButtonSize: number;
  /** 底部安全区域高度 (pt)，用于 home indicator 避让 */
  safeAreaBottom: number;
  /** 顶部安全区域高度 (pt) */
  safeAreaTop: number;
  /** 是否处于 Split View（宽度明显小于全屏） */
  isSplitView: boolean;
  /** Split View 比例描述 */
  splitViewRatio: 'full' | '2/3' | '1/2' | '1/3';
  /** iPad 型号猜测（用于调试） */
  iPadModel: 'pro12.9' | 'pro11' | 'air' | 'mini' | 'unknown';
}

/** 检测当前平台 */
function detectPlatform(): Platform {
  // 优先使用 WKWebView 注入的标识
  if (
    typeof window !== 'undefined' &&
    (window as unknown as Record<string, unknown>).__TUNXIANG_PLATFORM__ === 'ipad'
  ) {
    return 'ipad';
  }

  // 其次通过 userAgent 检测
  if (typeof navigator === 'undefined') return 'unknown';

  const ua = navigator.userAgent;

  // iPad：iPadOS 13+ 的 userAgent 模拟 Mac，但 supports touch 且无 Android 标识
  const isIPadOS =
    /iPad/.test(ua) ||
    (/Macintosh/.test(ua) && 'ontouchend' in document && !/Android/.test(ua));

  if (isIPadOS) return 'ipad';

  if (/TXBridge/i.test(ua) || /Android.*POS/i.test(ua)) return 'android-pos';

  if (/Windows|Macintosh|Linux/.test(ua) && !/Mobile/.test(ua)) return 'desktop';

  return 'unknown';
}

/** 猜测 iPad 型号 */
function guessIPadModel(width: number): IPadLayout['iPadModel'] {
  if (width >= 1366) return 'pro12.9';
  if (width >= 1180) return 'pro11';
  if (width >= 1024) return 'air';
  if (width >= 744) return 'mini';
  return 'unknown';
}

/** 判断 Split View 比例 */
function getSplitViewRatio(width: number): IPadLayout['splitViewRatio'] {
  if (width >= 1000) return 'full';
  if (width >= 800) return '2/3';
  if (width >= 550) return '1/2';
  return '1/3';
}

/** 是否是 iPad 全屏宽度 */
function isFullScreenWidth(width: number): boolean {
  // 全屏 iPad 宽度 >= 744（iPad mini 竖屏），Split View 通常在 375-920pt
  return width >= 744;
}

export function useIPadLayout(): IPadLayout {
  const [viewportWidth, setViewportWidth] = useState<number>(
    typeof window !== 'undefined' ? window.innerWidth : 1024,
  );
  const [viewportHeight, setViewportHeight] = useState<number>(
    typeof window !== 'undefined' ? window.innerHeight : 1366,
  );

  const platform = useMemo<Platform>(() => detectPlatform(), []);
  const isIPad = platform === 'ipad';

  // 监听窗口大小变化（旋转 / Split View）
  const handleResize = useCallback(() => {
    setViewportWidth(window.innerWidth);
    setViewportHeight(window.innerHeight);
  }, []);

  useEffect(() => {
    if (!isIPad) return;

    handleResize(); // 初始读取

    window.addEventListener('resize', handleResize);
    window.addEventListener('orientationchange', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('orientationchange', handleResize);
    };
  }, [isIPad, handleResize]);

  return useMemo(() => {
    // ── 非 iPad：返回默认值 ──
    if (!isIPad) {
      return {
        isIPad: false,
        platform,
        isLandscape: viewportWidth > viewportHeight,
        isPortrait: viewportWidth <= viewportHeight,
        viewportWidth,
        viewportHeight,
        sidebarWidth: 220,
        tableMapCellSize: 56,
        numPadButtonSize: 48,
        safeAreaBottom: 0,
        safeAreaTop: 0,
        isSplitView: false,
        splitViewRatio: 'full',
        iPadModel: 'unknown',
      };
    }

    // ── iPad：计算布局常量 ──
    const isLandscape = viewportWidth > viewportHeight;
    const isPortrait = !isLandscape;
    const isSplitView = !isFullScreenWidth(viewportWidth);
    const splitViewRatio = getSplitViewRatio(viewportWidth);

    // Sidebar 宽度
    let sidebarWidth: number;
    if (splitViewRatio === '1/3' || splitViewRatio === '1/2') {
      sidebarWidth = 0; // 窄 Split View 下 Sidebar 折叠为抽屉
    } else if (isLandscape && viewportWidth >= 1366) {
      sidebarWidth = 340;
    } else if (isLandscape) {
      sidebarWidth = 320;
    } else if (viewportWidth >= 1024) {
      sidebarWidth = 280;
    } else {
      sidebarWidth = 260;
    }

    // 台位图格大小
    let tableMapCellSize: number;
    if (viewportWidth >= 1366) {
      tableMapCellSize = 88;
    } else if (isLandscape) {
      tableMapCellSize = 80;
    } else if (isSplitView) {
      tableMapCellSize = 52;
    } else {
      tableMapCellSize = 64;
    }

    // 数字键盘按钮大小
    let numPadButtonSize: number;
    if (viewportWidth >= 1366) {
      numPadButtonSize = 60;
    } else if (isSplitView) {
      numPadButtonSize = 44;
    } else if (isPortrait) {
      numPadButtonSize = 52;
    } else {
      numPadButtonSize = 56;
    }

    // 安全区域（跨平台通用计算）
    const safeAreaBottom = isIPad ? 20 : 0;
    const safeAreaTop = isIPad ? 24 : 0;

    return {
      isIPad: true,
      platform,
      isLandscape,
      isPortrait,
      viewportWidth,
      viewportHeight,
      sidebarWidth,
      tableMapCellSize,
      numPadButtonSize,
      safeAreaBottom,
      safeAreaTop,
      isSplitView,
      splitViewRatio,
      iPadModel: guessIPadModel(viewportWidth),
    };
  }, [isIPad, platform, viewportWidth, viewportHeight]);
}

/**
 * 便捷导出：仅返回最常用的几个值
 *
 * 使用方式：
 *   const { isIPad, sidebarWidth, numPadButtonSize } = useIPadLayoutSimple();
 */
export function useIPadLayoutSimple() {
  const layout = useIPadLayout();
  return {
    isIPad: layout.isIPad,
    isLandscape: layout.isLandscape,
    sidebarWidth: layout.sidebarWidth,
    tableMapCellSize: layout.tableMapCellSize,
    numPadButtonSize: layout.numPadButtonSize,
    isSplitView: layout.isSplitView,
  };
}

export default useIPadLayout;
