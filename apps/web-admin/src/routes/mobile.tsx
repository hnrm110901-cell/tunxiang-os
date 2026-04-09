/**
 * 移动端管理直通车路由 — /m/*
 */
import { Route, Navigate } from 'react-router-dom';
import { MobileDashboard } from '../pages/mobile/MobileDashboard';
import { MobileAnomalyPage } from '../pages/mobile/MobileAnomalyPage';
import { MobileTableStatusPage } from '../pages/mobile/MobileTableStatusPage';
import { MobileHomePage } from '../pages/mobile/MobileHomePage';
import { MobileStoreListPage } from '../pages/mobile/MobileStoreListPage';
import { TrialDataClearPage } from '../pages/settings/TrialDataClearPage';

export const mobileRoutes = (
  <>
    <Route path="/m/home" element={<MobileHomePage />} />
    <Route path="/m/stores" element={<MobileStoreListPage />} />
    <Route path="/m/dashboard" element={<MobileDashboard />} />
    <Route path="/m/anomaly" element={<MobileAnomalyPage />} />
    <Route path="/m/tables" element={<MobileTableStatusPage />} />
    <Route path="/m/reports" element={<MobileDashboard />} />
    <Route path="/m/settings" element={<Navigate to="/settings" replace />} />
    <Route path="/m" element={<Navigate to="/m/home" replace />} />
    <Route path="/settings/trial-data-clear" element={<TrialDataClearPage />} />
  </>
);
