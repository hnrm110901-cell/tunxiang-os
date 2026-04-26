/**
 * web-hub v2.0 — 顶部工作模式导航 + 双栏 Workspace 布局
 * 深色主题：--bg #0A1418, --surface #0E1E24, --orange #FF6B2C
 */
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  useNavigate,
  useParams,
  useLocation,
} from 'react-router-dom';
import { useEffect, useCallback } from 'react';

/* ─── v1.0 页面组件（保留兼容） ─── */
import { MerchantsPage } from './pages/MerchantsPage';
import { StoresPage } from './pages/StoresPage';
import { TemplatesPage } from './pages/TemplatesPage';
import { AdaptersPage } from './pages/AdaptersPage';
import { AgentMonitorPage } from './pages/AgentMonitorPage';
import { BillingPage } from './pages/BillingPage';
import { TicketsPage } from './pages/TicketsPage';
import { DeploymentPage } from './pages/DeploymentPage';
import { PlatformDataPage } from './pages/PlatformDataPage';

/* ─── v2.0 模块 ─── */
import { useHubStore } from './store/hubStore';
import { ListPanel } from './components/ListPanel';
import type { WorkMode, WorkspaceType, ListItem } from './types/hub';
import { WORKSPACE_META, OBJECT_PAGE_TABS } from './types/hub';

/* ═══════════════════════════════════════════════════════════════
   色板常量
   ═══════════════════════════════════════════════════════════════ */
const C = {
  bg: '#0A1418',
  surface: '#0E1E24',
  surface2: '#132932',
  surface3: '#1A3540',
  border: '#1A3540',
  text: '#E6EDF1',
  text2: '#94A8B3',
  text3: '#647985',
  orange: '#FF6B2C',
  green: '#22C55E',
  yellow: '#F59E0B',
  red: '#EF4444',
  blue: '#3B82F6',
} as const;

/* ═══════════════════════════════════════════════════════════════
   样式
   ═══════════════════════════════════════════════════════════════ */
const sty = {
  /* 全局容器 */
  root: {
    display: 'flex',
    flexDirection: 'column' as const,
    height: '100vh',
    background: C.bg,
    color: C.text,
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    margin: 0,
  } as React.CSSProperties,

  /* ─── 顶部导航栏 48px ─── */
  topNav: {
    height: 48,
    minHeight: 48,
    background: C.surface,
    borderBottom: `1px solid ${C.border}`,
    display: 'flex',
    alignItems: 'center',
    padding: '0 16px',
    gap: 0,
    zIndex: 100,
  } as React.CSSProperties,

  logo: {
    fontSize: 15,
    fontWeight: 700,
    color: C.orange,
    marginRight: 24,
    whiteSpace: 'nowrap' as const,
    cursor: 'pointer',
  } as React.CSSProperties,

  navGroup: {
    display: 'flex',
    alignItems: 'center',
    gap: 2,
    flex: 1,
  } as React.CSSProperties,

  navBtn: (active: boolean): React.CSSProperties => ({
    padding: '6px 14px',
    borderRadius: 6,
    fontSize: 13,
    fontWeight: active ? 600 : 400,
    color: active ? C.orange : C.text2,
    background: active ? 'rgba(255,107,44,0.12)' : 'transparent',
    border: 'none',
    cursor: 'pointer',
    transition: 'all 0.15s',
    whiteSpace: 'nowrap',
  }),

  wsDropdown: {
    position: 'relative' as const,
  } as React.CSSProperties,

  wsMenu: {
    position: 'absolute' as const,
    top: 36,
    left: 0,
    background: C.surface2,
    border: `1px solid ${C.border}`,
    borderRadius: 8,
    padding: '6px 0',
    minWidth: 180,
    zIndex: 200,
    boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
  } as React.CSSProperties,

  wsMenuItem: (active: boolean): React.CSSProperties => ({
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '8px 16px',
    fontSize: 13,
    color: active ? C.orange : C.text,
    background: active ? 'rgba(255,107,44,0.08)' : 'transparent',
    cursor: 'pointer',
    transition: 'background 0.15s',
  }),

  cmdkBtn: {
    marginLeft: 'auto',
    padding: '5px 12px',
    borderRadius: 6,
    fontSize: 12,
    color: C.text3,
    background: C.surface2,
    border: `1px solid ${C.border}`,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  } as React.CSSProperties,

  /* ─── 内容区 ─── */
  body: {
    flex: 1,
    display: 'flex',
    overflow: 'hidden',
  } as React.CSSProperties,

  mainContent: {
    flex: 1,
    overflow: 'auto',
    padding: 24,
  } as React.CSSProperties,

  /* ─── Object Page Tab 栏 ─── */
  tabBar: {
    display: 'flex',
    gap: 0,
    borderBottom: `1px solid ${C.border}`,
    padding: '0 24px',
    background: C.surface,
  } as React.CSSProperties,

  tab: (active: boolean): React.CSSProperties => ({
    padding: '10px 16px',
    fontSize: 13,
    fontWeight: active ? 600 : 400,
    color: active ? C.orange : C.text2,
    borderBottom: `2px solid ${active ? C.orange : 'transparent'}`,
    cursor: 'pointer',
    transition: 'all 0.15s',
    background: 'transparent',
    border: 'none',
    borderBottomWidth: 2,
    borderBottomStyle: 'solid',
    borderBottomColor: active ? C.orange : 'transparent',
  }),

  /* ─── 占位页 ─── */
  placeholder: {
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: C.text3,
    fontSize: 15,
    gap: 8,
  } as React.CSSProperties,
};

/* ═══════════════════════════════════════════════════════════════
   工作模式定义
   ═══════════════════════════════════════════════════════════════ */
const WORK_MODES: { key: WorkMode; label: string; path: string }[] = [
  { key: 'today',      label: 'Today',      path: '/' },
  { key: 'stream',     label: 'Stream',     path: '/stream' },
  { key: 'workspaces', label: 'Workspaces', path: '/w' },
  { key: 'playbooks',  label: 'Playbooks',  path: '/playbooks' },
];

const WORKSPACE_KEYS: WorkspaceType[] = [
  'customers', 'stores', 'edges', 'services',
  'adapters', 'agents', 'migrations', 'incidents',
];

/* ─── v1.0 路由 → v2.0 重定向映射 ─── */
const V1_REDIRECTS: Record<string, string> = {
  '/merchants':  '/w/customers',
  '/stores':     '/w/stores',
  '/templates':  '/w/migrations',
  '/adapters':   '/w/adapters',
  '/agents':     '/w/agents',
  '/tickets':    '/w/incidents',
  '/deployment': '/w/edges',
};

/* ═══════════════════════════════════════════════════════════════
   TopNav — 顶部工作模式导航条
   ═══════════════════════════════════════════════════════════════ */
function TopNav() {
  const navigate = useNavigate();
  const location = useLocation();
  const { workMode, setWorkMode, activeWorkspace, setActiveWorkspace, setCmdKOpen } = useHubStore();
  const [wsMenuOpen, setWsMenuOpen] = __useState(false);

  /* 从 URL 同步工作模式 */
  useEffect(() => {
    const p = location.pathname;
    if (p.startsWith('/w/') || p === '/w') {
      if (workMode !== 'workspaces') setWorkMode('workspaces');
    } else if (p.startsWith('/stream')) {
      if (workMode !== 'stream') setWorkMode('stream');
    } else if (p.startsWith('/playbooks')) {
      if (workMode !== 'playbooks') setWorkMode('playbooks');
    } else if (p === '/' || p === '/today') {
      if (workMode !== 'today') setWorkMode('today');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  /* Cmd-K 快捷键 */
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCmdKOpen(true);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [setCmdKOpen]);

  const handleModeClick = useCallback(
    (mode: WorkMode, path: string) => {
      if (mode === 'workspaces') {
        setWsMenuOpen((v: boolean) => !v);
        if (activeWorkspace) {
          navigate(`/w/${activeWorkspace}`);
        }
        return;
      }
      setWsMenuOpen(false);
      setWorkMode(mode);
      navigate(path);
    },
    [navigate, setWorkMode, activeWorkspace],
  );

  const handleWsSelect = useCallback(
    (ws: WorkspaceType) => {
      setActiveWorkspace(ws);
      setWsMenuOpen(false);
      navigate(`/w/${ws}`);
    },
    [navigate, setActiveWorkspace],
  );

  return (
    <div style={sty.topNav}>
      <div style={sty.logo} onClick={() => { setWorkMode('today'); navigate('/'); }}>
        屯象Hub v2.0
      </div>

      <div style={sty.navGroup}>
        {WORK_MODES.map((m) => (
          m.key === 'workspaces' ? (
            <div key={m.key} style={sty.wsDropdown}>
              <button
                style={sty.navBtn(workMode === 'workspaces')}
                onClick={() => handleModeClick(m.key, m.path)}
              >
                {m.label} {activeWorkspace ? `· ${WORKSPACE_META[activeWorkspace].label}` : ''} ▾
              </button>
              {wsMenuOpen && (
                <div style={sty.wsMenu}>
                  {WORKSPACE_KEYS.map((ws) => (
                    <div
                      key={ws}
                      style={sty.wsMenuItem(activeWorkspace === ws)}
                      onClick={() => handleWsSelect(ws)}
                      onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,107,44,0.08)'; }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = activeWorkspace === ws ? 'rgba(255,107,44,0.08)' : 'transparent';
                      }}
                    >
                      <span>{WORKSPACE_META[ws].icon}</span>
                      <span>{WORKSPACE_META[ws].label}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <button
              key={m.key}
              style={sty.navBtn(workMode === m.key)}
              onClick={() => handleModeClick(m.key, m.path)}
            >
              {m.label}
            </button>
          )
        ))}
      </div>

      <button style={sty.cmdkBtn} onClick={() => setCmdKOpen(true)}>
        <span style={{ fontFamily: 'monospace' }}>&#x2318;K</span>
      </button>
    </div>
  );
}

/* 使用 React.useState 并加别名避免与 import 冲突 */
import { useState as __useState } from 'react';

/* ═══════════════════════════════════════════════════════════════
   Today 页（占位）
   ═══════════════════════════════════════════════════════════════ */
function TodayPage() {
  return (
    <div style={sty.placeholder}>
      <div style={{ fontSize: 32 }}>&#9728;</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: C.text }}>Today</div>
      <div>今日待办 / 告警 / Incident / 续约</div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Stream 页（占位）
   ═══════════════════════════════════════════════════════════════ */
function StreamPage() {
  return (
    <div style={sty.placeholder}>
      <div style={{ fontSize: 32 }}>&#x26A1;</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: C.text }}>Stream</div>
      <div>全局实时事件流（SSE）</div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Playbooks 页（占位）
   ═══════════════════════════════════════════════════════════════ */
function PlaybooksPage() {
  return (
    <div style={sty.placeholder}>
      <div style={{ fontSize: 32 }}>&#x1F4D6;</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: C.text }}>Playbooks</div>
      <div>剧本库</div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Workspace 双栏布局
   ═══════════════════════════════════════════════════════════════ */

/** 临时 mock 数据（后续接真实 API） */
function getMockItems(ws: WorkspaceType): ListItem[] {
  const meta = WORKSPACE_META[ws];
  return Array.from({ length: 12 }, (_, i) => ({
    id: `${ws}-${i + 1}`,
    name: `${meta.label} #${i + 1}`,
    status: (['online', 'offline', 'warning', 'error'] as const)[i % 4],
    subtitle: `示例${meta.label}对象`,
    meta: i % 3 === 0 ? '99%' : undefined,
  }));
}

function WorkspaceLayout() {
  const { workspace } = useParams<{ workspace: string }>();
  const { activeWorkspace, setActiveWorkspace, selectedObjectId, selectObject } = useHubStore();

  const ws = (workspace || activeWorkspace || 'customers') as WorkspaceType;

  /* 路由参数同步到 store */
  useEffect(() => {
    if (workspace && workspace !== activeWorkspace) {
      setActiveWorkspace(workspace as WorkspaceType);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace]);

  const wsKey = WORKSPACE_META[ws] ? ws : 'customers';
  const items = getMockItems(wsKey);

  const filterChips = [
    { key: 'online', label: '在线' },
    { key: 'offline', label: '离线' },
    { key: 'warning', label: '告警' },
    { key: 'error', label: '异常' },
  ];

  return (
    <div style={sty.body}>
      <ListPanel
        title={WORKSPACE_META[wsKey].label}
        items={items}
        selectedId={selectedObjectId}
        onSelect={selectObject}
        filterChips={filterChips}
      />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {selectedObjectId ? (
          <ObjectPageShell objectId={selectedObjectId} workspace={wsKey} />
        ) : (
          <div style={sty.placeholder}>
            <div style={{ fontSize: 24 }}>{WORKSPACE_META[wsKey].icon}</div>
            <div>请从左侧选择一个{WORKSPACE_META[wsKey].label}对象</div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Object Page Shell（Tab 栏 + 占位内容） ─── */
function ObjectPageShell({ objectId, workspace }: { objectId: string; workspace: WorkspaceType }) {
  const { activeTab, setActiveTab } = useHubStore();

  return (
    <>
      <div style={sty.tabBar}>
        {OBJECT_PAGE_TABS.map((t) => (
          <button
            key={t.key}
            style={sty.tab(activeTab === t.key)}
            onClick={() => setActiveTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div style={sty.mainContent}>
        <div style={{ marginBottom: 16 }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: C.text }}>
            {WORKSPACE_META[workspace].icon} {objectId}
          </span>
          <span style={{ marginLeft: 12, fontSize: 13, color: C.text3 }}>
            {activeTab}
          </span>
        </div>
        <div style={{ color: C.text3, fontSize: 13 }}>
          Object Page 内容区 — {WORKSPACE_META[workspace].label} / {objectId} / {activeTab}
        </div>
      </div>
    </>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Workspace 带 objectId 的路由
   ═══════════════════════════════════════════════════════════════ */
function WorkspaceObjectRoute() {
  const { workspace, id } = useParams<{ workspace: string; id: string }>();
  const { selectObject } = useHubStore();

  useEffect(() => {
    if (id) selectObject(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  return <WorkspaceLayout />;
}

/* ═══════════════════════════════════════════════════════════════
   App 根组件
   ═══════════════════════════════════════════════════════════════ */
function AppLayout() {
  return (
    <div style={sty.root}>
      <TopNav />
      <div style={sty.body}>
        <Routes>
          {/* v2.0 核心路由 */}
          <Route path="/" element={<TodayPage />} />
          <Route path="/today" element={<Navigate to="/" replace />} />
          <Route path="/stream" element={<StreamPage />} />
          <Route path="/playbooks" element={<PlaybooksPage />} />
          <Route path="/w/:workspace/:id" element={<WorkspaceObjectRoute />} />
          <Route path="/w/:workspace" element={<WorkspaceLayout />} />
          <Route path="/w" element={<Navigate to="/w/customers" replace />} />

          {/* v1.0 兼容重定向 */}
          {Object.entries(V1_REDIRECTS).map(([from, to]) => (
            <Route key={from} path={from} element={<Navigate to={to} replace />} />
          ))}

          {/* v1.0 保留页面（billing/platform 暂无 v2 对应） */}
          <Route path="/billing" element={<BillingPage />} />
          <Route path="/platform" element={<PlatformDataPage />} />

          {/* 兜底 */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppLayout />
    </BrowserRouter>
  );
}

export default App;

/* ─── 消除 v1.0 组件未使用警告（保留导入以备后续迁移） ─── */
void MerchantsPage;
void StoresPage;
void TemplatesPage;
void AdaptersPage;
void AgentMonitorPage;
void TicketsPage;
void DeploymentPage;
