/**
 * useAgentInsights — Agent 洞察 Hook（SSE 优先 + 轮询回退）
 *
 * Phase 2 升级:
 *   - SSE 实时推送优先（Mac mini → 浏览器 EventSource）
 *   - SSE 断开时自动回退到 30s REST 轮询
 *   - SSE 恢复时切回实时模式
 *
 * 数据源优先级:
 *   1. SSE agent_alert / agent_recommendation / agent_member 事件
 *   2. 轮询 dispatchAgent（discount_guard / smart_menu / member_insight）
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { dispatchAgent } from '../api/tradeApi';
import { useAgentSSE } from './useAgentSSE';
import type { SSEConnectionState } from './useAgentSSE';

// ─── 类型 ──────────────────────────────────────────────────────────────────────

export interface AgentInsight {
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

interface UseAgentInsightsReturn {
  alerts: AgentInsight[];
  recommendations: AgentInsight[];
  memberInsights: AgentInsight[];
  loading: boolean;
  error: string | null;
  dismissInsight: (id: string) => void;
  activeTab: 'alerts' | 'recommendations' | 'member';
  setActiveTab: (tab: 'alerts' | 'recommendations' | 'member') => void;
  unreadCount: number;
  /** SSE 连接状态（调试用 / UI 提示） */
  sseState: SSEConnectionState;
}

// ─── 常量 ──────────────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 30_000;
const FETCH_TIMEOUT_MS = 5_000;

// ─── 工具 ──────────────────────────────────────────────────────────────────────

async function fetchWithTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  const timeout = new Promise<never>((_, reject) =>
    setTimeout(() => reject(new Error('Agent timeout')), ms),
  );
  return Promise.race([promise, timeout]);
}

function classifyInsight(item: AgentInsight): { list: 'alerts' | 'recommendations' | 'member' } {
  return { list: item.type === 'alert' ? 'alerts' : item.type === 'recommendation' ? 'recommendations' : 'member' };
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAgentInsights(
  storeId?: string,
  tenantId?: string,
): UseAgentInsightsReturn {
  const [alerts, setAlerts] = useState<AgentInsight[]>([]);
  const [recommendations, setRecommendations] = useState<AgentInsight[]>([]);
  const [memberInsights, setMemberInsights] = useState<AgentInsight[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'alerts' | 'recommendations' | 'member'>('alerts');
  const dismissedRef = useRef<Set<string>>(new Set());

  const sseEnabled = !!(storeId && tenantId);
  const { connectionState: sseState, insights: sseInsights } = useAgentSSE(
    sseEnabled,
    storeId ?? '',
    tenantId ?? '',
  );
  const sseConnected = sseState === 'connected';

  // 将 SSE 推送的 insight 分散到对应列表（处理批量到达）
  const sseProcessedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (sseInsights.length === 0) return;
    for (const insight of sseInsights) {
      if (dismissedRef.current.has(insight.id) || sseProcessedRef.current.has(insight.id)) continue;
      sseProcessedRef.current.add(insight.id);
      const { list } = classifyInsight(insight);
      if (list === 'alerts') {
        setAlerts((prev) => {
          if (prev.some((a) => a.id === insight.id)) return prev;
          return [insight, ...prev.slice(0, 19)];
        });
      } else if (list === 'recommendations') {
        setRecommendations((prev) => {
          if (prev.some((r) => r.id === insight.id)) return prev;
          return [insight, ...prev.slice(0, 19)];
        });
      } else {
        setMemberInsights((prev) => {
          if (prev.some((m) => m.id === insight.id)) return prev;
          return [insight, ...prev.slice(0, 4)];
        });
      }
    }
  }, [sseInsights]);

  const dismissInsight = useCallback((id: string) => {
    dismissedRef.current.add(id);
    setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, dismissed: true } : a)));
    setRecommendations((prev) => prev.map((r) => (r.id === id ? { ...r, dismissed: true } : r)));
    setMemberInsights((prev) => prev.map((m) => (m.id === id ? { ...m, dismissed: true } : m)));
  }, []);

  // 仅在 SSE 断开时启用轮询
  const poll = useCallback(async () => {
    if (sseConnected) return; // SSE 在线，无需轮询
    setLoading(true);
    setError(null);

    const now = new Date().toISOString();

    const results = await Promise.allSettled([
      fetchWithTimeout(dispatchAgent('discount_guard', 'check_discount', {}), FETCH_TIMEOUT_MS),
      fetchWithTimeout(dispatchAgent('smart_menu', 'get_recommendations', {}), FETCH_TIMEOUT_MS),
      fetchWithTimeout(dispatchAgent('member_insight', 'get_member_profile', {}), FETCH_TIMEOUT_MS),
    ]);

    if (results[0].status === 'fulfilled') {
      const data = results[0].value as Record<string, unknown>;
      const items = Array.isArray(data?.alerts) ? data.alerts as Record<string, unknown>[] : [];
      setAlerts((prev) => {
        const mapped = items.map((a, i) => ({
          id: `alert-${a.alert_id || i}-${Date.now()}`,
          type: 'alert' as const,
          agentName: '折扣守护',
          agentId: 'discount_guard',
          severity: (a.severity as AgentInsight['severity']) || 'warning',
          title: String(a.title || '折扣异常'),
          message: String(a.message || a.reasoning || '检测到异常折扣'),
          data: a as Record<string, unknown>,
          timestamp: now,
          dismissed: false,
        }));
        return [...mapped, ...prev.slice(0, 20)];
      });
    } else if (!sseConnected) {
      setError('Agent 暂不可用');
    }

    if (results[1].status === 'fulfilled') {
      const data = results[1].value as Record<string, unknown>;
      const items = Array.isArray(data?.recommendations) ? data.recommendations as Record<string, unknown>[] : [];
      setRecommendations((prev) => {
        const mapped = items.map((r, i) => ({
          id: `rec-${r.dish_id || i}-${Date.now()}`,
          type: 'recommendation' as const,
          agentName: '智能排菜',
          agentId: 'smart_menu',
          severity: 'info' as const,
          title: String(r.dish_name || '推荐菜品'),
          message: String(r.reason || '基于历史数据推荐'),
          data: r as Record<string, unknown>,
          timestamp: now,
          dismissed: false,
        }));
        return [...mapped, ...prev.slice(0, 20)];
      });
    }

    if (results[2].status === 'fulfilled') {
      const data = results[2].value as Record<string, unknown>;
      const member = data?.member || data;
      if (member && typeof member === 'object') {
        const m = member as Record<string, unknown>;
        setMemberInsights((prev) => {
          const mapped: AgentInsight[] = [{
            id: `member-${m.member_id || Date.now()}`,
            type: 'member',
            agentName: '会员洞察',
            agentId: 'member_insight',
            severity: 'info',
            title: String(m.name || m.customer_name || '会员'),
            message: `等级: ${m.level || '普通'} | 累计消费: ${m.total_spend || '--'} | 到店: ${m.visit_count || '--'}次`,
            data: m,
            timestamp: now,
            dismissed: false,
          }];
          return [...mapped, ...prev.slice(0, 5)];
        });
      }
    }

    setLoading(false);
  }, [sseConnected]);

  // 轮询周期（仅在 SSE 断开时有效）
  useEffect(() => {
    if (sseConnected) return; // SSE 在线，跳过轮询
    poll();
    const timer = setInterval(poll, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [poll, sseConnected]);

  // 当 SSE 从断开→连接 或 连接→断开 时触发
  useEffect(() => {
    if (sseConnected) {
      setError(null); // SSE 恢复，清除轮询错误
    } else {
      // SSE 断开，立即触发一次轮询
      poll();
    }
  }, [sseConnected, poll]);

  const undismissedAlerts = alerts.filter((a) => !a.dismissed);
  const undismissedRecs = recommendations.filter((r) => !r.dismissed);
  const undismissedMember = memberInsights.filter((m) => !m.dismissed);
  const unreadCount = undismissedAlerts.length + undismissedRecs.length + undismissedMember.length;

  return {
    alerts: undismissedAlerts,
    recommendations: undismissedRecs,
    memberInsights: undismissedMember,
    loading,
    error,
    dismissInsight,
    activeTab,
    setActiveTab,
    unreadCount,
    sseState,
  };
}
