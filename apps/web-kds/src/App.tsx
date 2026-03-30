/**
 * KDS App — 路由入口
 *
 * 页面清单：
 *   /board         → KitchenBoard（档口任务看板，核心）
 *   /board-legacy  → KDSBoardPage（旧版看板，保留兼容）
 *   /zone-board    → ZoneKitchenBoard（包厢/大厅分区看板，?zone=vip|hall|all）
 *   /booking-prep  → BookingPrepView（预订备餐视图）
 *   /dept          → DeptSelector（档口选择）
 *   /timeout       → TimeoutAlert（超时预警）
 *   /shortage      → ShortageReport（缺料上报）
 *   /stats-panel   → StatsPanel（出品统计，增强版）
 *   /stats         → StatsPage（旧版统计，保留兼容）
 *   /remake        → RemakeModal（重做管理）
 *   /history       → HistoryPage（出餐历史）
 *   /config        → KDSConfigPage（档口配置）
 *   /alerts        → AlertsPage（告警页，旧版）
 *   /runner        → RunnerStation（传菜员工作站，P2）
 */
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { KDSBoardPage } from './pages/KDSBoardPage';
import { HistoryPage } from './pages/HistoryPage';
import { StatsPage } from './pages/StatsPage';
import { KDSConfigPage } from './pages/KDSConfigPage';
import { AlertsPage } from './pages/AlertsPage';
import { KitchenBoard } from './pages/KitchenBoard';
import { DeptSelector } from './pages/DeptSelector';
import { TimeoutAlert } from './pages/TimeoutAlert';
import { ShortageReport } from './pages/ShortageReport';
import { StatsPanel } from './pages/StatsPanel';
import { RemakeModal } from './pages/RemakeModal';
import { RunnerStation } from './pages/RunnerStation';
import { CallingQueue } from './pages/CallingQueue';
import { BookingPrepView } from './pages/BookingPrepView';
import { ZoneKitchenBoard } from './pages/ZoneKitchenBoard';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* 默认跳转到新版看板 */}
        <Route path="/" element={<Navigate to="/board" replace />} />

        {/* 新页面 */}
        <Route path="/board" element={<KitchenBoard />} />
        <Route path="/zone-board" element={<ZoneKitchenBoard />} />
        <Route path="/booking-prep" element={<BookingPrepView />} />
        <Route path="/dept" element={<DeptSelector />} />
        <Route path="/timeout" element={<TimeoutAlert />} />
        <Route path="/shortage" element={<ShortageReport />} />
        <Route path="/stats-panel" element={<StatsPanel />} />
        <Route path="/remake" element={<RemakeModal />} />
        <Route path="/runner" element={<RunnerStation />} />
        <Route path="/calling" element={<CallingQueue />} />

        {/* 原有页面（保留兼容） */}
        <Route path="/board-legacy" element={<KDSBoardPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/stats" element={<StatsPage />} />
        <Route path="/config" element={<KDSConfigPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
      </Routes>
    </BrowserRouter>
  );
}
