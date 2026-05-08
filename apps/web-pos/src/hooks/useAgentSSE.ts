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

/** 单条 SSE 事件 → SSESightData 的转换器 */
export type SSEEventHandler = (event: MessageEvent) => SSESightData | null;

/**
 * useAgentSSE 可选 DI 参数。零参调用走默认 Mac mini Agent endpoint。
 *
 * 用途：
 *   - 注入 mock SSE 服务器（测试 / Storybook）
 *   - 跨终端复用（如 Crew 端订阅订单变更，URL 不同）
 *   - 自定义事件类型映射（默认 3 个：alert/recommendation/member）
 */
export interface UseAgentSSEOptions {
  /** SSE 基址。默认: window.TX_MAC_URL（ws→http 转换）或 http://localhost:8000 */
  baseUrl?: string;
  /** Stream path。默认: /api/v1/agent/insights/stream */
  streamPath?: string;
  /** 自定义事件 → handler 映射。覆盖默认 alert/recommendation/member 处理器。 */
  eventHandlers?: Record<string, SSEEventHandler>;
}

// ─── 常量 ──────────────────────────────────────────────────────────────────────

const RECONNECT_DELAY_MS = 5_000;
const MAX_RECONNECT_DELAY_MS = 30_000;
const DEFAULT_STREAM_PATH = '/api/v1/agent/insights/stream';

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

// ─── 默认 SSE 事件处理器 ──────────────────────────────────────────────────────

/** 把 alert 事件 JSON 转 SSESightData */
function defaultAlertHandler(event: MessageEvent): SSESightData | null {
  try {
    const data = JSON.parse(event.data) as Record<string, unknown>;
    return {
      id: `sse-alert-${data.alert_id || Date.now()}`,
      type: 'alert',
      agentName: (data.agent_name as string) || '折扣守护',
      agentId: (data.agent_id as string) || 'discount_guard',
      severity: (data.severity as SSESightData['severity']) || 'warning',
      title: String(data.title || 'Agent 告警'),
      message: String(data.message || data.body || ''),
      data,
      timestamp: (data.timestamp as string) || new Date().toISOString(),
      dismissed: false,
    };
  } catch (e) {
    console.warn('[AgentSSE] alert parse error:', e);
    return null;
  }
}

function defaultRecommendationHandler(event: MessageEvent): SSESightData | null {
  try {
    const data = JSON.parse(event.data) as Record<string, unknown>;
    return {
      id: `sse-rec-${data.rec_id || Date.now()}`,
      type: 'recommendation',
      agentName: (data.agent_name as string) || '智能排菜',
      agentId: (data.agent_id as string) || 'smart_menu',
      severity: 'info',
      title: String(data.title || data.dish_name || '推荐'),
      message: String(data.message || data.reason || ''),
      data,
      timestamp: (data.timestamp as string) || new Date().toISOString(),
      dismissed: false,
    };
  } catch (e) {
    console.warn('[AgentSSE] recommendation parse error:', e);
    return null;
  }
}

function defaultMemberHandler(event: MessageEvent): SSESightData | null {
  try {
    const data = JSON.parse(event.data) as Record<string, unknown>;
    return {
      id: `sse-member-${(data.member_id as string) || Date.now()}`,
      type: 'member',
      agentName: (data.agent_name as string) || '会员洞察',
      agentId: (data.agent_id as string) || 'member_insight',
      severity: 'info',
      title: String(data.title || data.name || '会员信息'),
      message: String(data.message || data.body || ''),
      data,
      timestamp: (data.timestamp as string) || new Date().toISOString(),
      dismissed: false,
    };
  } catch (e) {
    console.warn('[AgentSSE] member parse error:', e);
    return null;
  }
}

const DEFAULT_EVENT_HANDLERS: Record<string, SSEEventHandler> = {
  agent_alert: defaultAlertHandler,
  agent_recommendation: defaultRecommendationHandler,
  agent_member: defaultMemberHandler,
};

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAgentSSE(
  enabled: boolean,
  storeId: string,
  tenantId: string,
  options: UseAgentSSEOptions = {},
): UseAgentSSEReturn {
  const baseUrlOverride = options.baseUrl;
  const streamPath = options.streamPath ?? DEFAULT_STREAM_PATH;
  const eventHandlers = options.eventHandlers ?? DEFAULT_EVENT_HANDLERS;

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

    const baseUrl = baseUrlOverride ?? getMacHttpUrl();
    const url = `${baseUrl}${streamPath}?store_id=${encodeURIComponent(storeId)}&tenant_id=${encodeURIComponent(tenantId)}`;

    setConnectionState('connecting');

    try {
      const es = new EventSource(url);
      esRef.current = es;

      es.onopen = () => {
        if (destroyedRef.current) { es.close(); return; }
        setConnectionState('connected');
        reconnectAttemptRef.current = 0;
      };

      // 注册所有事件 handler（DI：由 options.eventHandlers 控制）
      for (const [eventName, handler] of Object.entries(eventHandlers)) {
        es.addEventListener(eventName, (event) => {
          if (destroyedRef.current) return;
          const insight = handler(event as MessageEvent);
          if (!insight) return;
          // member 类型 cap 在 5 条；其他 20 条
          const cap = insight.type === 'member' ? 4 : 19;
          setInsights((prev) => [insight, ...prev.slice(0, cap)]);
        });
      }

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
  }, [enabled, storeId, tenantId, baseUrlOverride, streamPath, eventHandlers]);

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
