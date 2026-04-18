/**
 * KDS App — 路由入口
 *
 * 页面清单（原有）：
 *   /board         → KitchenBoard（档口任务看板，核心）
 *   /board-legacy  → KDSBoardPage（旧版看板，保留兼容）
 *   /zone-board    → ZoneKitchenBoard（包厢/大厅分区看板）
 *   /booking-prep  → BookingPrepView（预订备餐视图）
 *   /calling       → CallingQueue（等叫队列）
 *   /runner        → RunnerStation（传菜员工作站）
 *   /shortage      → ShortageReport（缺料上报）
 *   /stats-panel   → StatsPanel（出品统计）
 *   /config        → KDSConfigPage（档口配置）
 *
 * 新增页面（天财商龙对标补齐）：
 *   /swimlane      → SwimLaneBoard（泳道模式/工序流水线）
 *   /manager       → ManagerControlScreen（控菜大屏，厨师长视角）
 *   /chef-stats    → ChefStatsPage（厨师绩效计件排行）
 *   /prep          → PrepRecommendationPanel（预制量智能推荐）
 *   /station-profit → StationProfitPage（档口毛利核算）
 *   /calling-screen → CustomerCallingScreen（快餐顾客叫号屏）
 *
 * 徐记海鲜专属页面：
 *   /banquet-control → BanquetControlScreen（宴席控菜大屏，厨师长宴席同步出品）
 */
import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { getStoreToken } from './api/index';
import { ConnectionProvider, useConnection } from './contexts/ConnectionContext';
import { OfflineBanner } from './components/OfflineBanner';
import { KdsLoginPage } from './pages/KdsLoginPage';
import { KDSBoardPage } from './pages/KDSBoardPage';
import { StoreSelectPage } from './pages/StoreSelectPage';
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
import { SwimLaneBoard } from './pages/SwimLaneBoard';
import { ManagerControlScreen } from './pages/ManagerControlScreen';
import { ChefStatsPage } from './pages/ChefStatsPage';
import { PrepRecommendationPanel } from './pages/PrepRecommendationPanel';
import { StationProfitPage } from './pages/StationProfitPage';
import { CustomerCallingScreen } from './pages/CustomerCallingScreen';
import { DigitalMenuBoardPage } from './pages/DigitalMenuBoardPage';
import BanquetControlScreen from './pages/BanquetControlScreen';
import { BanquetKDSPage } from './pages/BanquetKDSPage';

export default function App() {
  // 演示模式：?demo=true 时跳过登录
  const isDemoUrl = new URLSearchParams(window.location.search).get('demo') === 'true';
  const [isLoggedIn, setIsLoggedIn] = useState(() => !!getStoreToken() || isDemoUrl);

  if (!isLoggedIn) {
    return <KdsLoginPage onLogin={() => setIsLoggedIn(true)} />;
  }

  return (
    <ConnectionProvider>
      <ConnectionBannerHost />
      <BrowserRouter>
        <Routes>
        {/* 默认跳转到门店选择页 */}
        <Route path="/" element={<Navigate to="/select" replace />} />

        {/* 门店选择页 */}
        <Route path="/select" element={<StoreSelectPage />} />

        {/* 演示就绪看板（水平滚动，支持 ?store=wh&demo=true） */}
        <Route path="/board" element={<KDSBoardPage />} />
        {/* 旧版三列看板（保留） */}
        <Route path="/board-kitchen" element={<KitchenBoard />} />
        <Route path="/zone-board" element={<ZoneKitchenBoard />} />
        <Route path="/booking-prep" element={<BookingPrepView />} />
        <Route path="/dept" element={<DeptSelector />} />
        <Route path="/timeout" element={<TimeoutAlert />} />
        <Route path="/shortage" element={<ShortageReport />} />
        <Route path="/stats-panel" element={<StatsPanel />} />
        <Route path="/remake" element={<RemakeModal />} />
        <Route path="/runner" element={<RunnerStation />} />
        <Route path="/calling" element={<CallingQueue />} />

        {/* 天财商龙对标补齐 — 新增功能页面 */}
        <Route path="/swimlane" element={<SwimLaneBoard />} />
        <Route path="/manager" element={<ManagerControlScreen />} />
        <Route path="/chef-stats" element={<ChefStatsPage />} />
        <Route path="/prep" element={<PrepRecommendationPanel />} />
        <Route path="/station-profit" element={<StationProfitPage />} />
        <Route path="/calling-screen" element={<CustomerCallingScreen />} />
        <Route path="/menu-board" element={<DigitalMenuBoardPage />} />
        {/* 徐记海鲜：宴席控菜大屏 */}
        <Route path="/banquet-control" element={<BanquetControlScreen />} />
        {/* 模块4.1：宴会KDS出品看板 */}
        <Route path="/banquet-kds" element={<BanquetKDSPage />} />

        {/* 原有页面（保留兼容） */}
        <Route path="/board-legacy" element={<KitchenBoard />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/stats" element={<StatsPage />} />
        <Route path="/config" element={<KDSConfigPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        </Routes>
      </BrowserRouter>
    </ConnectionProvider>
  );
}

/**
 * ConnectionBannerHost — 顶层固定的连接降级提示条。
 * 独立一层，让 useConnection() 能读到 ConnectionProvider 的值。
 */
function ConnectionBannerHost() {
  const { health, offlineDurationMs } = useConnection();
  return <OfflineBanner health={health} offlineDurationMs={offlineDurationMs} />;
}
