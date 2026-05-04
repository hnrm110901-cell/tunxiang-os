/**
 * useAgentSSE — Agent 洞察 SSE 实时推送 Hook
 *
 * 连接 Mac mini SSE 端点接收 Agent 实时洞察。
 * 若 SSE 不可用（端点未部署/网络断开），静默降级，
 * 由调用方（useSSESightDatas）切换为轮询。
 *
 * SSE URL: {TX_MAC_HTTP_URL}/api/v1/agent/insights/stream
 * 事件类型:
 *   agent_alert          — 折扣守护/库存预警
 *   agent_recommendation — 智能排菜/运营推荐
 *   agent_member         — 会员洞察
 *   keepalive            — 心跳（忽略）
 */
import { useCallback, useEffect, useRef, useState } from 'react';

// ─── 类型 ──────────────────────────────────────────────────────────────────────

export type SSEConnectionState = 'connecting' | 'connected' | 'disconnected' | 'error';

/** useSSESightDatas 的子集类型，避免循环依赖 */
interface SSESightData {
  id: string;
  type: 'alert' | 'recommendation' | 'member';
  agentName: string;
  agentId: string;
  severity?: 'info' | 'warning' | 'critical';
  title: string;
  message: string;
  data?: Record<string, unknown>;
  timestamp: string;
  dismissed: boolean;
}

interface UseAgentSSEReturn {
  connectionState: SSEConnectionState;
  insights: SSESightData[];
  /** 手动触发重连 */
  reconnect: () => void;
}

// ─── 常量 ──────────────────────────────────────────────────────────────────────

const RECONNECT_DELAY_MS = 5_000;
const MAX_RECONNECT_DELAY_MS = 30_000;

// ─── 工具 ──────────────────────────────────────────────────────────────────────

/** ws:// → http://, wss:// → https:// */
function wsToHttp(url: string): string {
  return url.replace(/^ws(s?):\/\//, (_, s) => (s ? 'https://' : 'http://'));
}

function getMacHttpUrl(): string {
  const wsUrl =
    (window as unknown as Record<string, string>).TX_MAC_URL ??
    'ws://localhost:8000';
  return wsToHttp(wsUrl);
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAgentSSE(
  enabled: boolean,
  storeId: string,
  tenantId: string,
): UseAgentSSEReturn {
  const [connectionState, setConnectionState] = useState<SSEConnectionState>('disconnected');
  const [insights, setInsights] = useState<SSESightData[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptRef = useRef(0);
  const destroyedRef = useRef(false);

  const clearReconnect = () => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  };

  const connect = useCallback(() => {
    if (destroyedRef.current) return;
    if (!enabled || !storeId) return;

    // 清除挂起的重连定时器，防止重复连接
    clearReconnect();

    // 关闭旧连接
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }

    const baseUrl = getMacHttpUrl();
    const url = `${baseUrl}/api/v1/agent/insights/stream?store_id=${encodeURIComponent(storeId)}&tenant_id=${encodeURIComponent(tenantId)}`;

    setConnectionState('connecting');

    try {
      const es = new EventSource(url);
      esRef.current = es;

      es.onopen = () => {
        if (destroyedRef.current) { es.close(); return; }
        setConnectionState('connected');
        reconnectAttemptRef.current = 0;
      };

      // agent_alert 事件
      es.addEventListener('agent_alert', (event) => {
        if (destroyedRef.current) return;
        try {
          const data = JSON.parse(event.data) as Record<string, unknown>;
          const insight: SSESightData = {
            id: `sse-alert-${data.alert_id || Date.now()}`,
            type: 'alert',
            agentName: (data.agent_name as string) || '折扣守护',
            agentId: (data.agent_id as string) || 'discount_guard',
            severity: (data.severity as SSESightData['severity']) || 'warning',
            title: String(data.title || 'Agent 告警'),
            message: String(data.message || data.body || ''),
            data: data as Record<string, unknown>,
            timestamp: (data.timestamp as string) || new Date().toISOString(),
            dismissed: false,
          };
          setInsights((prev) => [insight, ...prev.slice(0, 19)]);
        } catch (e) { console.warn('[AgentSSE] alert parse error:', e); }
      });

      // agent_recommendation 事件
      es.addEventListener('agent_recommendation', (event) => {
        if (destroyedRef.current) return;
        try {
          const data = JSON.parse(event.data) as Record<string, unknown>;
          const insight: SSESightData = {
            id: `sse-rec-${data.rec_id || Date.now()}`,
            type: 'recommendation',
            agentName: (data.agent_name as string) || '智能排菜',
            agentId: (data.agent_id as string) || 'smart_menu',
            severity: 'info',
            title: String(data.title || data.dish_name || '推荐'),
            message: String(data.message || data.reason || ''),
            data: data as Record<string, unknown>,
            timestamp: (data.timestamp as string) || new Date().toISOString(),
            dismissed: false,
          };
          setInsights((prev) => [insight, ...prev.slice(0, 19)]);
        } catch (e) { console.warn('[AgentSSE] recommendation parse error:', e); }
      });

      // agent_member 事件
      es.addEventListener('agent_member', (event) => {
        if (destroyedRef.current) return;
        try {
          const data = JSON.parse(event.data) as Record<string, unknown>;
          const insight: SSESightData = {
            id: `sse-member-${(data.member_id as string) || Date.now()}`,
            type: 'member',
            agentName: (data.agent_name as string) || '会员洞察',
            agentId: (data.agent_id as string) || 'member_insight',
            severity: 'info',
            title: String(data.title || data.name || '会员信息'),
            message: String(data.message || data.body || ''),
            data: data as Record<string, unknown>,
            timestamp: (data.timestamp as string) || new Date().toISOString(),
            dismissed: false,
          };
          setInsights((prev) => [insight, ...prev.slice(0, 4)]);
        } catch (e) { console.warn('[AgentSSE] recommendation parse error:', e); }
      });

      es.onerror = () => {
        if (destroyedRef.current) return;
        setConnectionState('error');
        es.close();
        esRef.current = null;

        // 自动重连（指数退避）
        const delay = Math.min(
          RECONNECT_DELAY_MS * Math.pow(2, reconnectAttemptRef.current),
          MAX_RECONNECT_DELAY_MS,
        );
        reconnectAttemptRef.current += 1;
        clearReconnect();
        reconnectTimerRef.current = setTimeout(() => connect(), delay);
      };
    } catch (e) {
      console.warn('[AgentSSE] EventSource construction failed:', e);
      setConnectionState('error');
    }
  }, [enabled, storeId, tenantId]);

  // 初始连接 + 清理
  useEffect(() => {
    connect();
    return () => {
      destroyedRef.current = true;
      clearReconnect();
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [connect]);

  const reconnect = useCallback(() => {
    reconnectAttemptRef.current = 0;
    connect();
  }, [connect]);

  return { connectionState, insights, reconnect };
}
