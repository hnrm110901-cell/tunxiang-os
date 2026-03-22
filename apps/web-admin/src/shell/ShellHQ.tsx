/**
 * Shell-HQ — 总部桌面端四栏布局
 * 决策1：完整四栏 (IconRail + Sidebar + Main + AgentConsole)
 * 决策2：右侧面板升级为 Agent Console
 *
 * Grid: 56px | 220px | 1fr | 340px
 *       48px topbar 贯穿全宽
 */
import { ReactNode, useState } from 'react';
import { IconRail } from './IconRail';
import { SidebarHQ } from './SidebarHQ';
import { AgentConsole } from './AgentConsole';
import { TopbarHQ } from './TopbarHQ';

interface ShellHQProps {
  children: ReactNode;
}

export function ShellHQ({ children }: ShellHQProps) {
  const [activeModule, setActiveModule] = useState('dashboard');
  const [agentVisible, setAgentVisible] = useState(true);

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
        <TopbarHQ onToggleAgent={() => setAgentVisible(!agentVisible)} />
      </div>

      {/* Icon Rail — 一级导航 */}
      <IconRail activeModule={activeModule} onModuleChange={setActiveModule} />

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
