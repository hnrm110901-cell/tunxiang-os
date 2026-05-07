/**
 * InsightCard — Agent 洞察卡片组件
 *
 * 用途: SmartSidebar 内展示单条 Agent 洞察
 *
 * 状态: loading（骨架屏）/ normal（内容）/ dismissed（淡出）
 * 严重程度色标: critical=红 / warning=橙 / info=蓝
 */
import { useState, useMemo } from 'react';
import type { AgentInsight } from '../hooks/useAgentInsights';
import { A2UIRenderer, parseA2UIFromAgent } from './a2ui/A2UIRenderer';
import { txColors } from '@tx/tokens';

// ─── 样式 ──────────────────────────────────────────────────────────────────────

const C = {
  card: {
    padding: 14, borderRadius: 10, marginBottom: 10,
    border: '1px solid rgba(255,255,255,0.06)',
    position: 'relative',
    transition: 'opacity 200ms, transform 200ms',
  } as React.CSSProperties,

  header: {
    display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6,
  } as React.CSSProperties,

  agentName: {
    fontSize: 11, fontWeight: 700, color: 'rgba(255,255,255,0.45)',
    textTransform: 'uppercase', letterSpacing: 0.5,
  } as React.CSSProperties,

  severityBadge: (severity: string): React.CSSProperties => {
    const colors: Record<string, string> = {
      critical: '#EB5757', warning: '#F2994A', info: '#2D9CDB',
    };
    return {
      padding: '2px 6px', borderRadius: 4, fontSize: 10, fontWeight: 700,
      background: (colors[severity] || colors.info) + '22',
      color: colors[severity] || colors.info,
      marginLeft: 'auto',
    };
  },

  title: {
    fontSize: 14, fontWeight: 600, color: 'rgba(255,255,255,0.92)', marginBottom: 4,
  } as React.CSSProperties,

  message: {
    fontSize: 12, color: 'rgba(255,255,255,0.55)', lineHeight: 1.4, marginBottom: 8,
  } as React.CSSProperties,

  timestamp: {
    fontSize: 11, color: 'rgba(255,255,255,0.25)',
  } as React.CSSProperties,

  actionBtn: {
    padding: '6px 12px', borderRadius: 6, border: 'none',
    fontSize: 12, fontWeight: 600, cursor: 'pointer',
    background: 'rgba(255,107,53,0.12)',
    color: txColors.primary,
    minHeight: 32,
  } as React.CSSProperties,

  dismissBtn: {
    position: 'absolute', top: 8, right: 8,
    width: 24, height: 24, borderRadius: '50%', border: 'none',
    background: 'transparent', color: 'rgba(255,255,255,0.25)',
    fontSize: 14, cursor: 'pointer', display: 'flex',
    alignItems: 'center', justifyContent: 'center',
  } as React.CSSProperties,

  skeleton: {
    padding: 14, borderRadius: 10, marginBottom: 10,
    background: 'rgba(255,255,255,0.03)',
    animation: 'tx-sk-pulse 1.5s ease-in-out infinite',
  } as React.CSSProperties,
};

const skeletonKeyframes = `
@keyframes tx-sk-pulse { 0%, 100% { opacity: 0.4; } 50% { opacity: 0.8; } }
`;

// ─── 组件 ──────────────────────────────────────────────────────────────────────

interface InsightCardProps {
  insight: AgentInsight;
  onDismiss: (id: string) => void;
  loading?: boolean;
}

export function InsightCard({ insight, onDismiss, loading }: InsightCardProps) {
  const [dismissing, setDismissing] = useState(false);
  const [expanded, setExpanded] = useState(false);

  // 尝试解析 A2UI 数据
  const a2uiDecl = useMemo(() => {
    if (!insight.data) return null;
    return parseA2UIFromAgent(insight.data);
  }, [insight.data]);

  if (loading) {
    return (
      <>
        <style>{skeletonKeyframes}</style>
        <div style={C.skeleton}>
          <div style={{ height: 12, width: '40%', background: 'rgba(255,255,255,0.06)', borderRadius: 3, marginBottom: 8 }} />
          <div style={{ height: 8, width: '80%', background: 'rgba(255,255,255,0.04)', borderRadius: 3, marginBottom: 4 }} />
          <div style={{ height: 8, width: '60%', background: 'rgba(255,255,255,0.04)', borderRadius: 3 }} />
        </div>
      </>
    );
  }

  if (dismissing) {
    return <div style={{ opacity: 0, transform: 'translateX(20px)', transition: 'opacity 200ms, transform 200ms', padding: 14 }} />;
  }

  const handleDismiss = () => {
    setDismissing(true);
    setTimeout(() => onDismiss(insight.id), 200);
  };

  return (
    <div style={C.card}>
      <button style={C.dismissBtn} onClick={handleDismiss} title="忽略">✕</button>
      <div style={C.header}>
        <span style={C.agentName}>{insight.agentName}</span>
        {insight.severity && (
          <span style={C.severityBadge(insight.severity)}>
            {insight.severity === 'critical' ? '严重' : insight.severity === 'warning' ? '注意' : '信息'}
          </span>
        )}
      </div>
      <div style={C.title}>{insight.title}</div>
      <div style={C.message}>{insight.message}</div>
      {/* A2UI 展开内容 */}
      {expanded && a2uiDecl && (
        <div style={{
          marginTop: 8, paddingTop: 8,
          borderTop: '1px solid rgba(255,255,255,0.06)',
        }}>
          <A2UIRenderer declaration={a2uiDecl} />
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={C.timestamp}>{formatRelative(insight.timestamp)}</span>
        <div style={{ display: 'flex', gap: 6 }}>
          {a2uiDecl && (
            <button
              style={C.actionBtn}
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? '收起' : '展开'}
            </button>
          )}
          {insight.type !== 'member' && !a2uiDecl && (
            <button style={C.actionBtn}>查看详情</button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── 工具 ──────────────────────────────────────────────────────────────────────

function formatRelative(iso: string): string {
  const sec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (sec < 60) return '刚刚';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}小时前`;
  return `${Math.floor(hr / 24)}天前`;
}
