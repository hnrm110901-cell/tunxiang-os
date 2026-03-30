/**
 * PackingStation — 打包员扫码出餐工作站
 *
 * 功能：
 *   - 顶部显示待打包订单数量（红色角标）
 *   - 订单卡片：订单号后 4 位、平台图标、菜品数量、进单时长、新顾客标签
 *   - 每张卡片显示 6 位出餐码（大字）+ 二维码占位区
 *   - 底部「扫码确认出餐」大按钮（≥64px）调用 TXBridge.scan()
 *   - 扫码成功后卡片消失，播放提示音
 *   - 长按卡片 2 秒手动确认（无扫码枪降级方案）
 *   - WebSocket 监听新订单推送，自动刷新
 *   - 深色主题，字体 ≥ 16px，按钮 ≥ 48×48px
 *
 * API 调用：
 *   useTxAPI() → /api/v1/dispatch-codes/*
 *   X-Tenant-ID header 来自 localStorage.getItem('kds_tenant_id')
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { startScan, isAndroidPOS } from '../bridge/TXBridge';
import { playNewOrder } from '../utils/audio';

// ─── 配置 ───

function getConfig() {
  try {
    return {
      host: localStorage.getItem('kds_mac_host') || '',
      storeId: localStorage.getItem('kds_store_id') || '',
      tenantId: localStorage.getItem('kds_tenant_id') || '',
      soundEnabled: localStorage.getItem('kds_sound') !== 'off',
    };
  } catch {
    return { host: '', storeId: '', tenantId: '', soundEnabled: true };
  }
}

// ─── Types ───

interface PendingOrder {
  id: string;            // dispatch_codes.id
  order_id: string;
  code: string;          // 6 位出餐码
  platform: string;      // meituan / eleme / douyin / dianping
  confirmed: boolean;
  created_at: string;    // ISO 字符串
  // 扩展字段（来自订单系统，可选）
  dish_count?: number;
  is_new_customer?: boolean;
  order_number?: string; // 完整订单号，用于截取后 4 位
}

type ConfirmState = 'idle' | 'loading' | 'done' | 'error';

// ─── 平台图标（emoji 文字替代 SVG，KDS 屏无需矢量资源） ───

const PLATFORM_ICONS: Record<string, string> = {
  meituan: '🟡',
  eleme:   '🔵',
  douyin:  '⚫',
  dianping:'🔴',
  unknown: '⬜',
};

const PLATFORM_NAMES: Record<string, string> = {
  meituan: '美团',
  eleme:   '饿了么',
  douyin:  '抖音',
  dianping:'大众点评',
  unknown: '未知',
};

// ─── useTxAPI Hook ───

function useTxAPI() {
  const config = getConfig();

  const baseUrl = config.host
    ? `http://${config.host}/api/v1/dispatch-codes`
    : '/api/v1/dispatch-codes';

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Tenant-ID': config.tenantId,
  };

  const fetchPending = useCallback(async (): Promise<PendingOrder[]> => {
    if (!config.storeId) return [];
    try {
      const resp = await fetch(`${baseUrl}/pending/${encodeURIComponent(config.storeId)}`, {
        headers,
      });
      if (!resp.ok) return [];
      const body = await resp.json();
      return (body?.data?.items as PendingOrder[]) ?? [];
    } catch {
      return [];
    }
  }, [baseUrl, config.storeId, config.tenantId]); // eslint-disable-line react-hooks/exhaustive-deps

  const confirmByCode = useCallback(async (
    code: string,
    operatorId: string,
  ): Promise<{ success: boolean; already_confirmed?: boolean; error?: string }> => {
    try {
      const resp = await fetch(`${baseUrl}/scan`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ code, operator_id: operatorId }),
      });
      const body = await resp.json();
      if (!body.ok) {
        return { success: false, error: body.error?.message ?? '扫码失败' };
      }
      return {
        success: true,
        already_confirmed: body.data?.already_confirmed ?? false,
      };
    } catch {
      return { success: false, error: '网络错误，请重试' };
    }
  }, [baseUrl, config.tenantId]); // eslint-disable-line react-hooks/exhaustive-deps

  return { fetchPending, confirmByCode, config };
}

// ─── 进单时长格式化 ───

function formatAge(createdAt: string): string {
  const diffMs = Date.now() - new Date(createdAt).getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return '刚进单';
  if (diffMin < 60) return `${diffMin} 分钟前`;
  const h = Math.floor(diffMin / 60);
  return `${h} 小时前`;
}

function getAgeColor(createdAt: string): string {
  const diffMin = Math.floor((Date.now() - new Date(createdAt).getTime()) / 60_000);
  if (diffMin >= 15) return '#ff4d4f';
  if (diffMin >= 8) return '#BA7517';
  return '#888';
}

// ─── WebSocket 新订单监听 ───

function usePackingWebSocket(
  host: string,
  storeId: string,
  onNewOrder: (order: PendingOrder) => void,
): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!host || !storeId || !mountedRef.current) return;

    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      if (
        wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING
      ) {
        wsRef.current.close();
      }
    }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    let ws: WebSocket;
    try {
      ws = new WebSocket(
        `${protocol}//${host}/ws/packing/${encodeURIComponent(storeId)}`,
      );
    } catch {
      scheduleRetry();
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setConnected(true);
      retryRef.current = 0;
    };

    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      if (event.data === 'pong') return;
      try {
        const msg = JSON.parse(event.data as string);
        if (msg.type === 'new_dispatch_code' && msg.order) {
          onNewOrder(msg.order as PendingOrder);
        }
      } catch {
        // 忽略非法消息
      }
    };

    ws.onerror = () => {
      // 错误会触发 onclose
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setConnected(false);
      scheduleRetry();
    };

    function scheduleRetry() {
      if (!mountedRef.current) return;
      const delay = Math.min(1000 * Math.pow(2, retryRef.current), 30_000);
      retryRef.current += 1;
      timerRef.current = setTimeout(() => {
        if (mountedRef.current) connect();
      }, delay);
    }
  }, [host, storeId, onNewOrder]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      if (wsRef.current) {
        wsRef.current.onopen = null;
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.onmessage = null;
        wsRef.current.close();
      }
    };
  }, [connect]);

  return { connected };
}

// ─── 订单卡片 ───

interface OrderCardProps {
  order: PendingOrder;
  tick: number;
  confirming: boolean;
  onManualConfirm: (orderId: string, code: string) => void;
}

function OrderCard({ order, tick: _tick, confirming, onManualConfirm }: OrderCardProps) {
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [pressing, setPressing] = useState(false);
  const [longPressProgress, setLongPressProgress] = useState(0);
  const progressTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const orderSuffix = (order.order_number ?? order.order_id).slice(-4).toUpperCase();
  const platformIcon = PLATFORM_ICONS[order.platform] ?? PLATFORM_ICONS.unknown;
  const platformName = PLATFORM_NAMES[order.platform] ?? order.platform;
  const ageColor = getAgeColor(order.created_at);
  const ageText = formatAge(order.created_at);

  const handleLongPressStart = () => {
    setPressing(true);
    setLongPressProgress(0);

    // 进度条更新（每 50ms 更新一次，2000ms 完成）
    let elapsed = 0;
    progressTimer.current = setInterval(() => {
      elapsed += 50;
      setLongPressProgress(Math.min((elapsed / 2000) * 100, 100));
    }, 50);

    longPressTimer.current = setTimeout(() => {
      clearInterval(progressTimer.current!);
      setPressing(false);
      setLongPressProgress(0);
      onManualConfirm(order.order_id, order.code);
    }, 2000);
  };

  const handleLongPressEnd = () => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
    if (progressTimer.current) {
      clearInterval(progressTimer.current);
      progressTimer.current = null;
    }
    setPressing(false);
    setLongPressProgress(0);
  };

  return (
    <div
      style={{
        background: '#111',
        borderRadius: 16,
        padding: 16,
        borderLeft: '6px solid #1890ff',
        userSelect: 'none',
        position: 'relative',
        overflow: 'hidden',
        opacity: confirming ? 0.5 : 1,
        transition: 'opacity 200ms ease',
      }}
      onMouseDown={handleLongPressStart}
      onMouseUp={handleLongPressEnd}
      onMouseLeave={handleLongPressEnd}
      onTouchStart={handleLongPressStart}
      onTouchEnd={handleLongPressEnd}
    >
      {/* 长按进度条 */}
      {pressing && (
        <div style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          height: 4,
          width: `${longPressProgress}%`,
          background: '#52c41a',
          transition: 'width 50ms linear',
          borderRadius: '0 4px 4px 0',
        }} />
      )}

      {/* 第一行：平台图标 + 订单号后 4 位 + 新顾客标签 */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 28 }}>{platformIcon}</span>
          <span style={{ fontSize: 20, color: '#aaa' }}>{platformName}</span>
          <span style={{
            fontSize: 26,
            fontWeight: 'bold',
            color: '#fff',
            fontFamily: 'JetBrains Mono, "Courier New", monospace',
          }}>
            #{orderSuffix}
          </span>
          {order.is_new_customer && (
            <span style={{
              background: '#ff6b35',
              color: '#fff',
              borderRadius: 6,
              padding: '2px 8px',
              fontSize: 14,
              fontWeight: 'bold',
            }}>
              新顾客
            </span>
          )}
        </div>
        <div style={{ textAlign: 'right' }}>
          {order.dish_count !== undefined && (
            <div style={{ fontSize: 18, color: '#aaa' }}>
              {order.dish_count} 件商品
            </div>
          )}
          <div style={{ fontSize: 16, color: ageColor }}>{ageText}</div>
        </div>
      </div>

      {/* 第二行：出餐码（大字）+ 二维码占位 */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        marginBottom: 8,
      }}>
        {/* 出餐码大字 */}
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, color: '#666', marginBottom: 4 }}>出餐码</div>
          <div style={{
            fontSize: 48,
            fontWeight: 'bold',
            color: '#52c41a',
            letterSpacing: 8,
            fontFamily: 'JetBrains Mono, "Courier New", monospace',
            lineHeight: 1.1,
          }}>
            {order.code}
          </div>
        </div>

        {/* 二维码占位区 */}
        <div style={{
          width: 80,
          height: 80,
          background: '#1a1a1a',
          border: '2px dashed #333',
          borderRadius: 8,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}>
          <span style={{ fontSize: 24 }}>▦</span>
          <span style={{ fontSize: 11, color: '#555', marginTop: 4 }}>txdc://{order.code}</span>
        </div>
      </div>

      {/* 长按提示 */}
      {!isAndroidPOS() && (
        <div style={{ fontSize: 13, color: '#444', marginTop: 4 }}>
          长按 2 秒可手动确认出餐
        </div>
      )}
    </div>
  );
}

// ─── 主组件 ───

export function PackingStation() {
  const { fetchPending, confirmByCode, config } = useTxAPI();

  const [orders, setOrders] = useState<PendingOrder[]>([]);
  const [tick, setTick] = useState(0);
  const [confirmingIds, setConfirmingIds] = useState<Set<string>>(new Set());
  const [scanStatus, setScanStatus] = useState<ConfirmState>('idle');
  const [scanMsg, setScanMsg] = useState('');

  // 每秒刷新进单时长显示
  useEffect(() => {
    const timer = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // 初始加载 + 30 秒轮询补偿
  const refresh = useCallback(async () => {
    const items = await fetchPending();
    setOrders(items);
  }, [fetchPending]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 30_000);
    return () => clearInterval(timer);
  }, [refresh]);

  // WebSocket 新订单推送
  const handleNewOrder = useCallback((order: PendingOrder) => {
    setOrders(prev => {
      if (prev.some(o => o.order_id === order.order_id)) return prev;
      if (config.soundEnabled) playNewOrder();
      return [order, ...prev];
    });
  }, [config.soundEnabled]);

  const { connected } = usePackingWebSocket(
    config.host,
    config.storeId,
    handleNewOrder,
  );

  // 通用确认逻辑（扫码 or 手动）
  const doConfirm = useCallback(async (code: string) => {
    setScanStatus('loading');
    setScanMsg('确认中...');

    const result = await confirmByCode(code, config.storeId || 'packing-operator');

    if (result.success) {
      setScanStatus('done');
      setScanMsg(result.already_confirmed ? '已确认过了' : '出餐确认成功！');
      // 从列表移除对应卡片
      setOrders(prev => prev.filter(o => o.code !== code));
      if (config.soundEnabled && !result.already_confirmed) {
        playNewOrder();
      }
    } else {
      setScanStatus('error');
      setScanMsg(result.error ?? '确认失败，请重试');
    }

    // 3 秒后复位状态
    setTimeout(() => {
      setScanStatus('idle');
      setScanMsg('');
    }, 3000);
  }, [confirmByCode, config.storeId, config.soundEnabled]);

  // 扫码按钮
  const handleScanButton = useCallback(async () => {
    if (scanStatus === 'loading') return;
    try {
      const raw = await startScan();
      if (!raw) {
        setScanStatus('error');
        setScanMsg('扫码取消或无结果');
        setTimeout(() => { setScanStatus('idle'); setScanMsg(''); }, 2000);
        return;
      }
      // 支持直接扫出 6 位码或 txdc:// 格式
      const code = raw.startsWith('txdc://') ? raw.slice(7) : raw.trim();
      await doConfirm(code);
    } catch {
      setScanStatus('error');
      setScanMsg('扫码异常，请重试');
      setTimeout(() => { setScanStatus('idle'); setScanMsg(''); }, 2000);
    }
  }, [scanStatus, doConfirm]);

  // 长按手动确认
  const handleManualConfirm = useCallback(async (_orderId: string, code: string) => {
    if (scanStatus === 'loading') return;
    setConfirmingIds(prev => new Set(prev).add(_orderId));
    await doConfirm(code);
    setConfirmingIds(prev => {
      const next = new Set(prev);
      next.delete(_orderId);
      return next;
    });
  }, [scanStatus, doConfirm]);

  const noConfig = !config.host || !config.storeId || !config.tenantId;
  const pendingCount = orders.length;

  const scanBtnColor =
    scanStatus === 'done'  ? '#52c41a' :
    scanStatus === 'error' ? '#ff4d4f' :
    scanStatus === 'loading' ? '#333' :
    '#1890ff';

  return (
    <div style={{
      background: '#0A0A0A',
      color: '#E0E0E0',
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
      fontSize: 16,
    }}>
      <style>{ANIMATIONS_CSS}</style>

      {/* 顶栏 */}
      <header style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '12px 20px',
        background: '#111',
        borderBottom: '1px solid #222',
        minHeight: 60,
        flexShrink: 0,
        position: 'relative',
      }}>
        {/* 标题 + 角标 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 26, fontWeight: 'bold', color: '#1890ff' }}>
            打包出餐站
          </span>

          {/* 待打包订单数量角标 */}
          {pendingCount > 0 && (
            <span style={{
              background: '#ff4d4f',
              color: '#fff',
              borderRadius: '50%',
              minWidth: 32,
              height: 32,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 18,
              fontWeight: 'bold',
              padding: '0 6px',
              animation: 'packing-badge-pulse 2s infinite',
            }}>
              {pendingCount}
            </span>
          )}

          {/* 连接状态 */}
          {config.host && (
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              fontSize: 16, color: connected ? '#52c41a' : '#ff4d4f',
            }}>
              <span style={{
                width: 10, height: 10, borderRadius: '50%',
                background: connected ? '#52c41a' : '#ff4d4f',
                display: 'inline-block',
              }} />
              {connected ? '实时推送' : '断线重连中'}
            </span>
          )}

          {noConfig && (
            <span style={{ fontSize: 16, color: '#BA7517' }}>
              未配置（需设置 Mac mini 地址/门店/租户）
            </span>
          )}
        </div>

        <span style={{ fontSize: 18, color: '#555' }}>
          待出餐{' '}
          <b style={{ color: '#E0E0E0', fontSize: 28 }}>{pendingCount}</b>
          {' '}单
        </span>
      </header>

      {/* 扫码状态提示条 */}
      {scanStatus !== 'idle' && (
        <div style={{
          padding: '12px 20px',
          background: scanStatus === 'done' ? '#0d2b0d' : scanStatus === 'error' ? '#2b0d0d' : '#0d1a2b',
          color: scanStatus === 'done' ? '#52c41a' : scanStatus === 'error' ? '#ff4d4f' : '#1890ff',
          fontSize: 18,
          fontWeight: 'bold',
          textAlign: 'center',
          flexShrink: 0,
        }}>
          {scanMsg}
        </div>
      )}

      {/* 订单卡片列表 */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '16px 16px 120px',
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        WebkitOverflowScrolling: 'touch',
      }}>
        {orders.length === 0 ? (
          <div style={{
            textAlign: 'center',
            color: '#444',
            fontSize: 22,
            marginTop: 80,
          }}>
            暂无待出餐订单
          </div>
        ) : (
          orders.map(order => (
            <OrderCard
              key={order.order_id}
              order={order}
              tick={tick}
              confirming={confirmingIds.has(order.order_id)}
              onManualConfirm={handleManualConfirm}
            />
          ))
        )}
      </div>

      {/* 底部：扫码确认出餐大按钮 */}
      <div style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        padding: '12px 16px 20px',
        background: 'linear-gradient(transparent, #0A0A0A 30%)',
      }}>
        <button
          onClick={handleScanButton}
          disabled={scanStatus === 'loading'}
          style={{
            width: '100%',
            minHeight: 64,
            background: scanBtnColor,
            color: '#fff',
            border: 'none',
            borderRadius: 16,
            fontSize: 24,
            fontWeight: 'bold',
            cursor: scanStatus === 'loading' ? 'not-allowed' : 'pointer',
            transition: 'transform 200ms ease, background 200ms ease',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 12,
            opacity: scanStatus === 'loading' ? 0.7 : 1,
          }}
          onTouchStart={e => scanStatus === 'idle' && (e.currentTarget.style.transform = 'scale(0.97)')}
          onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
          onMouseDown={e => scanStatus === 'idle' && (e.currentTarget.style.transform = 'scale(0.97)')}
          onMouseUp={e => (e.currentTarget.style.transform = 'scale(1)')}
        >
          <span style={{ fontSize: 28 }}>
            {scanStatus === 'loading' ? '⏳' : scanStatus === 'done' ? '✅' : scanStatus === 'error' ? '❌' : '📷'}
          </span>
          {scanStatus === 'loading' ? '确认中...' :
           scanStatus === 'done'    ? '出餐确认成功' :
           scanStatus === 'error'   ? '扫码失败，重试' :
           '扫码确认出餐'}
        </button>
      </div>
    </div>
  );
}

// ─── 动画 CSS ───

const ANIMATIONS_CSS = `
  @keyframes packing-badge-pulse {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.12); }
  }
`;
