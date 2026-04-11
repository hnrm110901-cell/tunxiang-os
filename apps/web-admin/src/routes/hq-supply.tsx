/**
 * 供应链路由 — /hq/supply/*, /supply/*
 */
import { Route } from 'react-router-dom';
import { InventoryIntelPage } from '../pages/hq/supply/InventoryIntelPage';
import { SupplyChainPage } from '../pages/hq/supply/SupplyChainPage';
import { SupplierPortalPage } from '../pages/hq/supply/SupplierPortalPage';
import { ProcurementSuggestionPage } from '../pages/hq/supply/ProcurementSuggestionPage';
import { WastageAnalysisPage } from '../pages/hq/supply/WastageAnalysisPage';
import { DemandForecastPage } from '../pages/hq/supply/DemandForecastPage';
import { SupplyPage } from '../pages/SupplyPage';
import { CentralKitchenPage } from '../pages/CentralKitchenPage';
import { CentralKitchenPage as CentralKitchenPageV2 } from '../pages/supply/CentralKitchenPage';
import { BomEditorPage } from '../pages/supply/bom/BomEditorPage';
import { PurchaseOrderPage } from '../pages/supply/PurchaseOrderPage';
import { ExpiryAlertPage } from '../pages/supply/ExpiryAlertPage';
import { SupplyDashboardPage } from '../pages/supply/SupplyDashboardPage';

export const supplyRoutes = (
  <>
    <Route path="/hq/supply/inventory-intel" element={<InventoryIntelPage />} />
    <Route path="/hq/supply/chain" element={<SupplyChainPage />} />
    <Route path="/hq/supply/suppliers" element={<SupplierPortalPage />} />
    <Route path="/hq/supply/procurement-ai" element={<ProcurementSuggestionPage />} />
    <Route path="/hq/supply/wastage" element={<WastageAnalysisPage />} />
    <Route path="/hq/supply/demand-forecast" element={<DemandForecastPage />} />
    {/* Legacy */}
    <Route path="/supply" element={<SupplyPage />} />
    <Route path="/central-kitchen" element={<CentralKitchenPage />} />
    <Route path="/supply/central-kitchen" element={<CentralKitchenPageV2 />} />
    <Route path="/supply/bom" element={<BomEditorPage />} />
    <Route path="/supply/purchase-orders" element={<PurchaseOrderPage />} />
    <Route path="/supply/expiry-alerts" element={<ExpiryAlertPage />} />
    <Route path="/supply/dashboard" element={<SupplyDashboardPage />} />
  </>
);
