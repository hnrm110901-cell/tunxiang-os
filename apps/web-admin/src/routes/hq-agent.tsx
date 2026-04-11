/**
 * Agent管理路由 — /hq/agent/*, /agent/*
 */
import { Route } from 'react-router-dom';
import { AgentHubPage as HQAgentHubPage } from '../pages/hq/agent/AgentHubPage';
import { AgentCommandCenterPage } from '../pages/hq/agent/AgentCommandCenterPage';
import { AgentMarketplacePage } from '../pages/hq/agent/AgentMarketplacePage';
import { AgentSettingsPage } from '../pages/hq/agent/AgentSettingsPage';
import { AgentDashboardPage } from '../pages/agent/AgentDashboardPage';
import { AgentMonitorPage } from '../pages/AgentMonitorPage';

export const agentRoutes = (
  <>
    <Route path="/hq/agent/hub" element={<HQAgentHubPage />} />
    <Route path="/hq/agent/command" element={<AgentCommandCenterPage />} />
    <Route path="/hq/agent/log" element={<AgentCommandCenterPage />} />
    <Route path="/hq/agent/market" element={<AgentMarketplacePage />} />
    <Route path="/hq/agent/settings" element={<AgentSettingsPage />} />
    <Route path="/agent/dashboard" element={<AgentDashboardPage />} />
    <Route path="/agents" element={<AgentMonitorPage />} />
  </>
);
