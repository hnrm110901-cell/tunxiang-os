/**
 * ServiceSuggestionCard — 主动服务建议浮动提示 (Phase 3-B)
 *
 * 非模态浮动提示，无建议时 height=0 不占空间。
 * 每90秒自动刷新。支持逐条忽略。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

// ─── 类型 ───

export interface ServiceSuggestion {
  type: 'upsell' | 'refill' | 'dessert' | 'checkout_hint';
  message: string;
  urgency: 'info' | 'suggest' | 'urgent';
  action_label: string;
  action_data?: Record<string, unknown>;
}

interface Props {
  orderId: string;
  onAction: (suggestion: ServiceSuggestion) => void;
}

// ─── API ───

const API_BASE = import.meta.env.VITE_API_URL || '';

async function fetchSuggestions(orderId: string): Promise<ServiceSuggestion[]> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/service/suggestions/${orderId}`, {
      headers: { 'X-Tenant-ID': 'demo-tenant' },
    });
    if (!res.ok) return MOCK_SUGGESTIONS;
    const json = await res.json();
    return json.data ?? [];
  } catch {
    return MOCK_SUGGESTIONS;
  }
}

async function dismissSuggestion(orderId: string, suggestionType: string): Promise<void> {
  try {
    await fetch(
      `${API_BASE}/api/v1/service/suggestions/${orderId}/${suggestionType}/dismiss`,
      { method: 'POST', headers: { 'X-Tenant-ID': 'demo-tenant' } }
    );
  } catch {
    // 忽略网络错误，前端本地也记录
  }
}

// ─── Mock 降级数据 ───

const MOCK_SUGGESTIONS: ServiceSuggestion[] = [
  {
    type: 'upsell',
    message: '用餐42分钟，人均¥65，建议推荐加菜',
    urgency: 'suggest',
    action_label: '查看推荐',
  },
  {
    type: 'refill',
    message: '可乐已上桌23分钟，可询问是否续杯',
    urgency: 'info',
    action_label: '加菜',
  },
];

// ─── 样式工具 ───

function getBorderColor(urgency: ServiceSuggestion['urgency']): string {
  if (urgency === 'urgent') return '#E53E3E';
  if (urgency === 'suggest') return '#FF6B35';
  return '#1A9BE8';
}

function getBgColor(urgency: ServiceSuggestion['urgency']): string {
  if (urgency === 'urgent') return '#FFF5F5';
  if (urgency === 'suggest') return '#FFF8F4';
  return '#F0F8FF';
}

function getIconColor(urgency: ServiceSuggestion['urgency']): string {
  if (urgency === 'urgent') return '#E53E3E';
  if (urgency === 'suggest') return '#FF6B35';
  return '#1A9BE8';
}

function getTypeIcon(type: ServiceSuggestion['type']): string {
  if (type === 'upsell') return '➕';
  if (type === 'refill') return '🥤';
  if (type === 'dessert') return '🍮';
  return '💳';
}

// ─── 单条建议行 ───

interface SuggestionRowProps {
  suggestion: ServiceSuggestion;
  onAction: () => void;
  onDismiss: () => void;
}

function SuggestionRow({ suggestion, onAction, onDismiss }: SuggestionRowProps) {
  const borderColor = getBorderColor(suggestion.urgency);
  const bgColor = getBgColor(suggestion.urgency);
  const iconColor = getIconColor(suggestion.urgency);

  return (
    <div
      style={{
        borderLeft: `4px solid ${borderColor}`,
        background: bgColor,
        padding: '10px 12px',
        borderRadius: '0 8px 8px 0',
        marginBottom: 8,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      {/* 图标 */}
      <span style={{ fontSize: 18, flexShrink: 0 }}>{getTypeIcon(suggestion.type)}</span>

      {/* 消息文字 */}
      <div style={{ flex: 1, fontSize: 15, color: '#1A1A1A', lineHeight: 1.4 }}>
        {suggestion.message}
      </div>

      {/* 操作按钮组 */}
      <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
        <button
          onClick={onAction}
          style={{
            minHeight: 36,
            minWidth: 64,
            background: borderColor,
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            fontSize: 14,
            fontWeight: 600,
            cursor: 'pointer',
            padding: '0 10px',
            whiteSpace: 'nowrap',
          }}
        >
          {suggestion.action_label}
        </button>
        <button
          onClick={onDismiss}
          style={{
            minHeight: 36,
            minWidth: 44,
            background: 'transparent',
            color: '#AAAAAA',
            border: '1px solid #E8E8E8',
            borderRadius: 6,
            fontSize: 13,
            cursor: 'pointer',
            padding: '0 8px',
            whiteSpace: 'nowrap',
          }}
        >
          忽略
        </button>
      </div>
    </div>
  );
}

// ─── 主组件 ───

export function ServiceSuggestionCard({ orderId, onAction }: Props) {
  const [suggestions, setSuggestions] = useState<ServiceSuggestion[]>([]);
  // 本地已忽略集合（避免等待 API 往返产生闪烁）
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    const list = await fetchSuggestions(orderId);
    setSuggestions(list);
  }, [orderId]);

  useEffect(() => {
    load();
    timerRef.current = setInterval(load, 90_000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [load]);

  const handleDismiss = useCallback(
    async (type: string) => {
      setDismissed((prev) => new Set([...prev, type]));
      await dismissSuggestion(orderId, type);
    },
    [orderId]
  );

  // 过滤已本地忽略的建议
  const visible = suggestions.filter((s) => !dismissed.has(s.type));

  if (visible.length === 0) return null;

  return (
    <div
      style={{
        background: '#FFFFFF',
        borderTop: '1px solid #E8E8E8',
        padding: '10px 12px 6px',
        flexShrink: 0,
      }}
    >
      {/* 标题栏 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          marginBottom: 8,
        }}
      >
        <span style={{ fontSize: 14, color: '#1A9BE8', fontWeight: 700 }}>
          Agent 服务提醒
        </span>
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 18,
            height: 18,
            background: '#1A9BE8',
            color: '#fff',
            borderRadius: '50%',
            fontSize: 11,
            fontWeight: 700,
          }}
        >
          {visible.length}
        </span>
      </div>

      {/* 建议列表 */}
      {visible.map((s) => (
        <SuggestionRow
          key={s.type}
          suggestion={s}
          onAction={() => onAction(s)}
          onDismiss={() => handleDismiss(s.type)}
        />
      ))}
    </div>
  );
}
