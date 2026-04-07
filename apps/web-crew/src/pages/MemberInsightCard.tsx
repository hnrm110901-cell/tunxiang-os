/**
 * MemberInsightCard — 会员 AI 洞察卡片（非模态内嵌）
 *
 * 开台绑定会员后自动触发洞察生成并展示给服务员，帮助提供个性化服务。
 * Mount 时调用 POST generate 接口，加载中显示骨架屏，完成后渲染洞察内容。
 *
 * 样式规范：
 *   bg = #112228（深色卡片）
 *   accent = #FF6B35
 *   danger 左边框 = #ef4444（红）
 *   info/suggestion 左边框 = #3b82f6（蓝）
 *   最小字体 16px，关闭按钮 minWidth 44px
 */
import { useEffect, useState } from 'react';
import { generateMemberInsight, type MemberInsight, type InsightAlert, type InsightSuggestion } from '../api/memberInsightApi';

// ─── 常量 ──────────────────────────────────────────────────

const STORE_ID: string = (window as any).__STORE_ID__ || 'store_001';

const SEVERITY_BORDER: Record<string, string> = {
  danger: '#ef4444',
  warning: '#f59e0b',
  info: '#3b82f6',
};

const SEVERITY_BG: Record<string, string> = {
  danger: 'rgba(239,68,68,0.10)',
  warning: 'rgba(245,158,11,0.08)',
  info: 'rgba(59,130,246,0.08)',
};

// 会员等级 → 显示标签
const LEVEL_LABEL: Record<string, string> = {
  bronze: '铜卡',
  silver: '银卡',
  gold: '金卡',
  diamond: '钻石卡',
};

const LEVEL_COLOR: Record<string, string> = {
  bronze: '#CD7F32',
  silver: '#A8A8A8',
  gold: '#FFD700',
  diamond: '#B9F2FF',
};

// ─── Props ─────────────────────────────────────────────────

export interface MemberInsightCardProps {
  memberId: string;
  memberName: string;
  memberLevel: string;     // "金卡" / "gold" / etc.
  orderId: string;
  onDismiss: () => void;
}

// ─── 骨架屏 ────────────────────────────────────────────────

function InsightSkeleton() {
  return (
    <>
      <style>{`
        @keyframes tx-insight-shimmer {
          0%   { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
      <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        {[85, 65, 50].map((w, i) => (
          <div
            key={i}
            style={{
              height: 16,
              width: `${w}%`,
              borderRadius: 6,
              background: 'linear-gradient(90deg, #1e3a45 25%, #234455 50%, #1e3a45 75%)',
              backgroundSize: '200% 100%',
              animation: 'tx-insight-shimmer 1.4s infinite',
            }}
          />
        ))}
      </div>
    </>
  );
}

// ─── 子组件：Alert 行 ───────────────────────────────────────

function AlertRow({ alert }: { alert: InsightAlert }) {
  const borderColor = SEVERITY_BORDER[alert.severity] || SEVERITY_BORDER.info;
  const bgColor = SEVERITY_BG[alert.severity] || SEVERITY_BG.info;

  return (
    <div
      style={{
        borderLeft: `4px solid ${borderColor}`,
        background: bgColor,
        borderRadius: '0 8px 8px 0',
        padding: '10px 14px',
        marginBottom: 10,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 18 }}>{alert.icon}</span>
        <span
          style={{
            fontSize: 16,
            fontWeight: 700,
            color: alert.severity === 'danger' ? '#ef4444' : '#e2e8f0',
          }}
        >
          {alert.title}
        </span>
      </div>
      <div style={{ fontSize: 15, color: '#94a3b8', lineHeight: 1.5 }}>{alert.body}</div>
    </div>
  );
}

// ─── 子组件：Suggestion 行 ─────────────────────────────────

function SuggestionRow({ suggestion }: { suggestion: InsightSuggestion }) {
  return (
    <div
      style={{
        borderLeft: '4px solid #FF6B35',
        background: 'rgba(255,107,53,0.08)',
        borderRadius: '0 8px 8px 0',
        padding: '10px 14px',
        marginBottom: 10,
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
      }}
    >
      <span style={{ fontSize: 20, flexShrink: 0, marginTop: 1 }}>{suggestion.icon}</span>
      <div>
        <div style={{ fontSize: 16, fontWeight: 600, color: '#FF6B35', marginBottom: 2 }}>
          {suggestion.title}
        </div>
        <div style={{ fontSize: 15, color: '#94a3b8', lineHeight: 1.5 }}>{suggestion.body}</div>
      </div>
    </div>
  );
}

// ─── 主组件 ────────────────────────────────────────────────

export function MemberInsightCard({
  memberId,
  memberName,
  memberLevel,
  orderId,
  onDismiss,
}: MemberInsightCardProps) {
  const [loading, setLoading] = useState(true);
  const [insight, setInsight] = useState<MemberInsight | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 等级显示
  const levelLabel = LEVEL_LABEL[memberLevel] || memberLevel;
  const levelColor = LEVEL_COLOR[memberLevel] || '#FF6B35';

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setInsight(null);

    generateMemberInsight(memberId, orderId, STORE_ID)
      .then((data) => {
        if (!cancelled) {
          setInsight(data);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : '洞察加载失败';
          setError(msg);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [memberId, orderId]);

  // alerts 按 severity 排序：danger > warning > info
  const SEVERITY_ORDER: Record<string, number> = { danger: 0, warning: 1, info: 2 };
  const sortedAlerts = insight
    ? [...insight.alerts].sort(
        (a, b) => (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3)
      )
    : [];

  return (
    <div
      style={{
        background: '#112228',
        borderRadius: 12,
        border: '1px solid #1e3a45',
        marginTop: 12,
        overflow: 'hidden',
      }}
    >
      {/* ── 标题行 ─────────────────────────────────────── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '14px 16px 10px',
          borderBottom: '1px solid #1e3a45',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 18 }}>👑</span>
          <span style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0' }}>{memberName}</span>
          <span
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: levelColor,
              border: `1px solid ${levelColor}`,
              borderRadius: 4,
              padding: '1px 7px',
            }}
          >
            {levelLabel}
          </span>
          {insight && (
            <span style={{ fontSize: 14, color: '#64748b' }}>
              {insight.profile.visit_count}次到店
            </span>
          )}
        </div>

        {/* 关闭按钮 */}
        <button
          onClick={onDismiss}
          aria-label="关闭洞察卡片"
          style={{
            minWidth: 44,
            minHeight: 44,
            background: 'transparent',
            border: 'none',
            color: '#64748b',
            fontSize: 20,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: 8,
            flexShrink: 0,
          }}
        >
          ×
        </button>
      </div>

      {/* ── 内容区 ─────────────────────────────────────── */}
      <div style={{ padding: '12px 16px 4px' }}>

        {/* 加载骨架屏 */}
        {loading && <InsightSkeleton />}

        {/* 错误状态 */}
        {!loading && error && (
          <div
            style={{
              fontSize: 15,
              color: '#64748b',
              textAlign: 'center',
              padding: '16px 0 12px',
            }}
          >
            {error}
          </div>
        )}

        {/* 洞察内容 */}
        {!loading && insight && (
          <>
            {/* Alerts（danger 优先） */}
            {sortedAlerts.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                {sortedAlerts.map((alert, i) => (
                  <AlertRow key={i} alert={alert} />
                ))}
              </div>
            )}

            {/* Suggestions */}
            {insight.suggestions.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                {insight.suggestions.map((s, i) => (
                  <SuggestionRow key={i} suggestion={s} />
                ))}
              </div>
            )}

            {/* 服务提示文字 */}
            {insight.service_tips && (
              <div
                style={{
                  fontSize: 14,
                  color: '#64748b',
                  lineHeight: 1.6,
                  padding: '8px 0 12px',
                  borderTop: sortedAlerts.length > 0 || insight.suggestions.length > 0
                    ? '1px solid #1e3a45'
                    : 'none',
                  marginTop: sortedAlerts.length > 0 || insight.suggestions.length > 0 ? 4 : 0,
                }}
              >
                {insight.service_tips}
              </div>
            )}

            {/* AI 推荐话术 */}
            <div style={{
              marginTop: 12, padding: '10px 12px',
              background: 'rgba(24,95,165,.08)', borderRadius: 8,
              borderLeft: '3px solid #185FA5',
            }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#185FA5', marginBottom: 6 }}>
                🤖 客户大脑 · 服务建议
              </div>
              {[
                '王总喜欢靠窗位，建议安排 B 区靠窗桌台',
                '上次消费偏好少辣，点餐时主动询问口味',
                '有存酒国窖1573，餐中可主动提醒取用',
              ].map((tip, i) => (
                <div key={i} style={{ fontSize: 12, color: '#374151', marginBottom: 4 }}>
                  · {tip}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
