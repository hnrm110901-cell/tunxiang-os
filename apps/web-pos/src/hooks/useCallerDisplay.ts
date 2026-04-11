/**
 * useCallerDisplay — 叫号屏联动 Hook
 *
 * 职责：
 *   1. 维护与叫号屏后端的 WebSocket 长连接
 *   2. 出餐完成时通过 WS 推送叫号消息（优先）
 *   3. WS 未就绪时降级为 HTTP POST（保证可靠性）
 *   4. 推送失败静默处理，不阻断主收银流程
 *
 * 使用方式：
 *   const { callNumber, callStatus } = useCallerDisplay({ storeId, enabled });
 *   await callNumber('001', '剁椒鱼头 × 1');
 *
 * WebSocket 消息格式（与叫号屏 CallingScreenPage 协议一致）：
 *   发送：{ type: 'CALL_NUMBER', table: '001', summary: '...', store_id: '...' }
 *   服务端广播给所有叫号屏客户端
 *
 * HTTP 回退端点：
 *   POST /api/v1/trade/caller-display/call
 *   Body: { table_number: '001', message: '...', store_id: '...' }
 */
import { useCallback, useEffect, useRef, useState } from 'react';

// ─── 类型 ─────────────────────────────────────────────────────────────────────

export type CallerDisplayStatus = 'connecting' | 'connected' | 'disconnected' | 'disabled';

export interface UseCallerDisplayOptions {
  /** 门店 ID，用于多门店区分推送 */
  storeId: string;
  /** 是否启用叫号屏联动（根据门店快餐配置决定） */
  enabled?: boolean;
  /** 自定义 API base URL（默认读 window.__API_BASE__） */
  apiBase?: string;
  /** WebSocket 重连间隔（毫秒，默认 5000） */
  reconnectInterval?: number;
}

export interface UseCallerDisplayReturn {
  /** 当前 WebSocket 连接状态 */
  callStatus: CallerDisplayStatus;
  /**
   * 推送叫号
   * @param tableNumber 牌号，如 "001"
   * @param orderSummary 品项摘要，如 "剁椒鱼头×1 白米饭×2"
   * @returns Promise<void>（成功/失败均 resolve，失败仅打印 warn）
   */
  callNumber: (tableNumber: string, orderSummary: string) => Promise<void>;
  /** 手动重连 WebSocket */
  reconnect: () => void;
}

// ─── 工具 ─────────────────────────────────────────────────────────────────────

function getApiBase(): string {
  return (
    (window as unknown as Record<string, unknown>).__API_BASE__ as string ||
    ''
  );
}

function getTenantId(): string {
  return (
    (window as unknown as Record<string, unknown>).__TENANT_ID__ as string ||
    localStorage.getItem('tenant_id') ||
    ''
  );
}

function buildWsUrl(apiBase: string, storeId: string): string {
  // 将 http(s):// 转为 ws(s)://
  const base = apiBase || window.location.origin;
  const wsBase = base.replace(/^http/, 'ws');
  return `${wsBase}/ws/v1/caller-display?store_id=${encodeURIComponent(storeId)}`;
}

// ─── Hook ──────────────────────────────────────────────────────────────────────

export function useCallerDisplay({
  storeId,
  enabled = true,
  apiBase,
  reconnectInterval = 5000,
}: UseCallerDisplayOptions): UseCallerDisplayReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMountedRef = useRef(true);

  const [callStatus, setCallStatus] = useState<CallerDisplayStatus>(
    enabled ? 'connecting' : 'disabled',
  );

  const effectiveBase = apiBase ?? getApiBase();

  // ── WebSocket 连接管理 ──────────────────────────────────────────────────────

  const connect = useCallback(() => {
    if (!enabled || !storeId) return;

    // 清理已有连接
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
      wsRef.current = null;
    }

    setCallStatus('connecting');

    let ws: WebSocket;
    try {
      ws = new WebSocket(buildWsUrl(effectiveBase, storeId));
    } catch {
      // WebSocket 构造失败（如 URL 非法），直接降级为 HTTP only
      if (isMountedRef.current) setCallStatus('disconnected');
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      if (!isMountedRef.current) return;
      setCallStatus('connected');
    };

    ws.onclose = () => {
      if (!isMountedRef.current) return;
      setCallStatus('disconnected');
      // 自动重连
      reconnectTimerRef.current = setTimeout(() => {
        if (isMountedRef.current) connect();
      }, reconnectInterval);
    };

    ws.onerror = () => {
      // error 之后会紧接着触发 onclose，在 onclose 中处理重连
      // 这里只记录日志
      console.warn('[useCallerDisplay] WebSocket error，将在 onclose 后重连');
    };

    ws.onmessage = (_event) => {
      // 叫号屏可能推回确认消息，目前不处理，保留扩展点
    };
  }, [enabled, storeId, effectiveBase, reconnectInterval]);

  // ── 生命周期 ────────────────────────────────────────────────────────────────

  useEffect(() => {
    isMountedRef.current = true;
    if (enabled) {
      connect();
    } else {
      setCallStatus('disabled');
    }
    return () => {
      isMountedRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) {
        wsRef.current.onopen = null;
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect, enabled]);

  // ── 推送叫号 ────────────────────────────────────────────────────────────────

  const callNumber = useCallback(
    async (tableNumber: string, orderSummary: string): Promise<void> => {
      if (!enabled) return;

      const payload = {
        type: 'CALL_NUMBER',
        table: tableNumber,
        summary: orderSummary,
        store_id: storeId,
      };

      // 方式 1：WebSocket（延迟最低，<5ms）
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        try {
          wsRef.current.send(JSON.stringify(payload));
          return;
        } catch (wsErr) {
          console.warn('[useCallerDisplay] WS send 失败，降级到 HTTP', wsErr);
        }
      }

      // 方式 2：HTTP POST（回退，~100ms）
      try {
        const resp = await fetch(
          `${effectiveBase}/api/v1/trade/caller-display/call`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Tenant-ID': getTenantId(),
            },
            body: JSON.stringify({
              table_number: tableNumber,
              message: orderSummary,
              store_id: storeId,
            }),
            // 叫号推送设置较短超时，不影响主流程
            signal: AbortSignal.timeout ? AbortSignal.timeout(3000) : undefined,
          },
        );
        if (!resp.ok) {
          console.warn(
            `[useCallerDisplay] HTTP 叫号失败 HTTP ${resp.status}`,
          );
        }
      } catch (httpErr) {
        // 叫号失败不影响主收银流程，静默处理
        console.warn('[useCallerDisplay] 叫号屏推送失败（HTTP）', httpErr);
      }
    },
    [enabled, storeId, effectiveBase],
  );

  return {
    callStatus,
    callNumber,
    reconnect: connect,
  };
}

export default useCallerDisplay;
