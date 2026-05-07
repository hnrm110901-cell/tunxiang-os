/**
 * SmartSidebar — Agent 实时洞察侧边栏（SSE 优先 + 轮询回退）
 *
 * 固定在收银界面右侧，可折叠（326px 宽度）。
 * 三 Tab: Alerts（告警）/ Recommendations（推荐）/ Member（会员）
 * SSE 在线时实时推送，断开时自动回退到 30s 轮询。
 */
import { useAgentInsights } from '../hooks/useAgentInsights';
import { InsightCard } from './InsightCard';
import { txColors } from '@tx/tokens';

// ─── 样式 ──────────────────────────────────────────────────────────────────────

const C = {
  sidebar: (open: boolean): React.CSSProperties => ({
    width: open ? 326 : 0,
    minWidth: open ? 326 : 0,
    background: '#0D1E25',
    borderLeft: open ? '1px solid rgba(255,255,255,0.06)' : 'none',
    display: 'flex', flexDirection: 'column',
    transition: 'width 250ms ease, min-width 250ms',
    overflow: 'hidden',
    flexShrink: 0,
    position: 'relative',
  }),

  toggle: (open: boolean): React.CSSProperties => ({
    position: 'absolute', left: -36, top: 16,
    width: 36, height: 36,
    borderRadius: '8px 0 0 8px',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRight: 'none',
    background: '#112B36',
    color: 'rgba(255,255,255,0.55)',
    fontSize: 14, cursor: 'pointer',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 10,
    transition: 'background 150ms',
  }),

  header: {
    padding: '14px 16px 10px',
    borderBottom: '1px solid rgba(255,255,255,0.05)',
  } as React.CSSProperties,

  headerTitle: {
    fontSize: 14, fontWeight: 700, color: 'rgba(255,255,255,0.85)',
    display: 'flex', alignItems: 'center', gap: 8,
  } as React.CSSProperties,

  tabBar: {
    display: 'flex', gap: 4, padding: '8px 12px',
    borderBottom: '1px solid rgba(255,255,255,0.05)',
  } as React.CSSProperties,

  tab: (active: boolean): React.CSSProperties => ({
    flex: 1, height: 36, borderRadius: 8, border: 'none',
    background: active ? 'rgba(255,107,53,0.12)' : 'transparent',
    color: active ? txColors.primary : 'rgba(255,255,255,0.45)',
    fontSize: 12, fontWeight: active ? 700 : 400,
    cursor: 'pointer', display: 'flex', alignItems: 'center',
    justifyContent: 'center', gap: 4,
    transition: 'background 150ms, color 150ms',
    minHeight: 36,
  }),

  badge: {
    padding: '1px 6px', borderRadius: 8,
    background: txColors.primary, color: '#fff',
    fontSize: 10, fontWeight: 700, minWidth: 16, textAlign: 'center',
  } as React.CSSProperties,

  scrollArea: {
    flex: 1, overflowY: 'auto', padding: '12px 12px 40px',
  } as React.CSSProperties,

  emptyState: {
    textAlign: 'center', padding: 32, color: 'rgba(255,255,255,0.2)', fontSize: 13,
  } as React.CSSProperties,

  errorBanner: {
    margin: '0 12px 8px', padding: '8px 12px', borderRadius: 6,
    background: 'rgba(235,87,87,0.08)', border: '1px solid rgba(235,87,87,0.15)',
    color: '#EB5757', fontSize: 12,
  } as React.CSSProperties,
};

// ─── 组件 ──────────────────────────────────────────────────────────────────────

interface SmartSidebarProps {
  open: boolean;
  onToggle: () => void;
  /** 门店 ID（用于 SSE 连接和轮询） */
  storeId?: string;
  /** 租户 ID（用于 SSE 连接） */
  tenantId?: string;
}

export function SmartSidebar({ open, onToggle, storeId, tenantId }: SmartSidebarProps) {
  const {
    alerts, recommendations, memberInsights,
    loading, error, dismissInsight,
    activeTab, setActiveTab, unreadCount, sseState,
  } = useAgentInsights(storeId, tenantId);

  const currentItems = activeTab === 'alerts'
    ? alerts
    : activeTab === 'recommendations'
      ? recommendations
      : memberInsights;

  return (
    <div style={C.sidebar(open)}>
      {/* 折叠/展开按钮 */}
      <button
        style={{
          ...C.toggle(open),
          animation: unreadCount > 0 ? 'tx-pulse 2s ease-in-out infinite' : undefined,
        }}
        onClick={onToggle}
        title={open ? '收起面板' : '展开面板'}
      >
        {open ? '⟩' : '⟨'}
        {!open && unreadCount > 0 && (
          <span style={{
            position: 'absolute', top: -2, right: -2,
            width: 14, height: 14, borderRadius: '50%',
            background: txColors.primary, fontSize: 9,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {/* 头部 */}
      <div style={C.header}>
        <div style={C.headerTitle}>
          🤖 运营指挥官
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            marginLeft: 8, fontSize: 10, fontWeight: 400,
            color: sseState === 'connected' ? '#52c41a' :
                   sseState === 'connecting' ? '#faad14' :
                   sseState === 'error' ? '#ff4d4f' : '#666',
          }}>
            <span style={{
              width: 6, height: 6, borderRadius: '50%',
              background: sseState === 'connected' ? '#52c41a' :
                         sseState === 'connecting' ? '#faad14' :
                         sseState === 'error' ? '#ff4d4f' : '#666',
              display: 'inline-block',
              animation: sseState === 'connecting' ? 'tx-pulse 1.5s ease-in-out infinite' : undefined,
            }} />
            {sseState === 'connected' ? '实时' :
             sseState === 'connecting' ? '连接中' :
             sseState === 'error' ? '离线' : '未连接'}
          </span>
        </div>
      </div>

      {/* Tab 栏 */}
      <div style={C.tabBar}>
        <button style={C.tab(activeTab === 'alerts')} onClick={() => setActiveTab('alerts')}>
          告警 {alerts.length > 0 && <span style={C.badge}>{alerts.length}</span>}
        </button>
        <button style={C.tab(activeTab === 'recommendations')} onClick={() => setActiveTab('recommendations')}>
          推荐 {recommendations.length > 0 && <span style={C.badge}>{recommendations.length}</span>}
        </button>
        <button style={C.tab(activeTab === 'member')} onClick={() => setActiveTab('member')}>
          会员 {memberInsights.length > 0 && <span style={C.badge}>{memberInsights.length}</span>}
        </button>
      </div>

      {/* 错误提示 */}
      {error && (
        <div style={C.errorBanner}>⚠ {error}</div>
      )}

      {/* 内容区 */}
      <div style={C.scrollArea}>
        {loading && currentItems.length === 0 ? (
          <>
            <InsightCard
              insight={{ id: 'sk1', type: 'alert', agentName: '', agentId: '', title: '', message: '', timestamp: '', dismissed: false }}
              onDismiss={() => {}}
              loading
            />
            <InsightCard
              insight={{ id: 'sk2', type: 'recommendation', agentName: '', agentId: '', title: '', message: '', timestamp: '', dismissed: false }}
              onDismiss={() => {}}
              loading
            />
          </>
        ) : currentItems.length === 0 ? (
          <div style={C.emptyState}>
            <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.4 }}>🧘</div>
            {activeTab === 'alerts' && '暂无告警'}
            {activeTab === 'recommendations' && '暂无推荐'}
            {activeTab === 'member' && '暂无会员数据'}
          </div>
        ) : (
          currentItems.map((item) => (
            <InsightCard
              key={item.id}
              insight={item}
              onDismiss={dismissInsight}
            />
          ))
        )}
      </div>
    </div>
  );
}
