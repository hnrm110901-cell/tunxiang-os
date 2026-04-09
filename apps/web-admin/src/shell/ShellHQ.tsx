/**
 * Shell-HQ — 总部桌面端四栏布局
 * 决策1：完整四栏 (IconRail + Sidebar + Main + AgentConsole)
 * 决策2：右侧面板升级为 Agent Console
 *
 * Grid: 56px | 220px | 1fr | 340px
 *       48px topbar 贯穿全宽
 */
import { ReactNode, useState, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import { IconRail } from './IconRail';
import { SidebarHQ } from './SidebarHQ';
import { AgentConsole } from './AgentConsole';
import { TopbarHQ } from './TopbarHQ';

interface ShellHQProps {
  children: ReactNode;
  onLogout?: () => void;
}

/** 从URL路径推导当前激活的一级模块 */
function deriveModuleFromPath(pathname: string): string {
  // 优先匹配 /hq/{module}/* 命名空间
  const hqMatch = pathname.match(/^\/hq\/(\w+)/);
  if (hqMatch) {
    const seg = hqMatch[1];
    // 映射规则：URL段 → IconRail模块ID
    const map: Record<string, string> = {
      trade: 'trade', menu: 'menu', analytics: 'analytics',
      growth: 'growth', supply: 'ops', ops: 'ops',
      org: 'org', agent: 'agent', floor: 'store',
      store: 'store', iam: 'org', kds: 'store',
    };
    return map[seg] || 'dashboard';
  }
  // 兼容旧路由
  const topSegs: Record<string, string> = {
    trade: 'trade', menu: 'menu', catalog: 'menu',
    member: 'member', analytics: 'analytics', finance: 'finance',
    org: 'org', hr: 'org', payroll: 'org',
    ops: 'ops', supply: 'ops', store: 'store',
    kds: 'store', franchise: 'org', growth: 'growth',
    agent: 'agent', agents: 'agent',
  };
  const first = pathname.split('/')[1];
  return topSegs[first] || 'dashboard';
}

export function ShellHQ({ children, onLogout }: ShellHQProps) {
  const location = useLocation();
  const derivedModule = useMemo(() => deriveModuleFromPath(location.pathname), [location.pathname]);
  const [manualModule, setManualModule] = useState<string | null>(null);
  const [agentVisible, setAgentVisible] = useState(true);

  // 点击IconRail手动切换模块，URL变化时自动同步
  const activeModule = manualModule ?? derivedModule;
  const handleModuleChange = (id: string) => setManualModule(id);

  // Read current user from localStorage
  let userName = '用户';
  let userRole = '';
  try {
    const raw = localStorage.getItem('tx_user');
    if (raw) {
      const u = JSON.parse(raw);
      userName = u.name || u.username || '用户';
      userRole = u.merchant || '';
    }
  } catch {
    // ignore parse errors
  }

  return (
    <div className="shell--hq" style={{
      display: 'grid',
      gridTemplateRows: '48px 1fr',
      gridTemplateColumns: `56px 220px 1fr ${agentVisible ? '340px' : '0px'}`,
      height: '100vh',
      background: 'var(--bg-0, #0B1A20)',
      color: 'var(--text-1, #fff)',
      fontFamily: 'var(--font-body)',
      fontSize: 'var(--font-size-body, 13px)',
      transition: 'grid-template-columns var(--duration-panel, .3s) var(--ease-out)',
    }}>
      {/* Topbar — 贯穿全宽 */}
      <div style={{ gridColumn: '1 / -1' }}>
        <TopbarHQ
          onToggleAgent={() => setAgentVisible(!agentVisible)}
          userName={userName}
          userRole={userRole}
          onLogout={onLogout}
        />
      </div>

      {/* Icon Rail — 一级导航 */}
      <IconRail activeModule={activeModule} onModuleChange={handleModuleChange} />

      {/* Sidebar — 二级导航 */}
      <SidebarHQ activeModule={activeModule} />

      {/* Main Content */}
      <main style={{ overflow: 'auto', padding: 'var(--sp-6, 24px)' }}>
        {children}
      </main>

      {/* Agent Console — 决策2 */}
      {agentVisible && <AgentConsole />}
    </div>
  );
}
