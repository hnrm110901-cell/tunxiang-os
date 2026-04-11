/**
 * 菜品管理路由 — /hq/menu/*, /menu/*
 */
import { Route } from 'react-router-dom';
import { CatalogPage } from '../pages/CatalogPage';
import { LiveSeafoodPage } from '../pages/menu/live-seafood/LiveSeafoodPage';
import { MenuTemplatePage } from '../pages/menu/template/MenuTemplatePage';
import MenuSchemePage from '../pages/menu/MenuSchemePage';
import { MenuOptimizePage } from '../pages/menu/MenuOptimizePage';
import { DishSpecPage } from '../pages/menu/DishSpecPage';
import { DishSortPage } from '../pages/menu/DishSortPage';
import { DishBatchPage } from '../pages/menu/DishBatchPage';
import DishRankingPage from '../pages/menu/DishRankingPage';
import ChannelMenuPage from '../pages/menu/ChannelMenuPage';
import { DishAgentDashboardPage } from '../pages/hq/menu/DishAgentDashboardPage';
import { BomEditorPage } from '../pages/supply/bom/BomEditorPage';

export const menuRoutes = (
  <>
    <Route path="/hq/menu/dishes" element={<CatalogPage />} />
    <Route path="/hq/menu/categories" element={<CatalogPage />} />
    <Route path="/hq/menu/live-seafood" element={<LiveSeafoodPage />} />
    <Route path="/hq/menu/specs" element={<DishSpecPage />} />
    <Route path="/hq/menu/packages" element={<MenuSchemePage />} />
    <Route path="/hq/menu/pricing" element={<MenuSchemePage />} />
    <Route path="/hq/menu/ranking" element={<DishRankingPage />} />
    <Route path="/hq/menu/bom" element={<BomEditorPage />} />
    <Route path="/hq/menu/optimize" element={<MenuOptimizePage />} />
    <Route path="/hq/menu/rd" element={<MenuSchemePage />} />
    <Route path="/hq/menu/quality" element={<MenuSchemePage />} />
    <Route path="/hq/menu/dish-agent" element={<DishAgentDashboardPage />} />
    <Route path="/hq/menu/kitchen-schedule" element={<DishAgentDashboardPage />} />
    {/* Legacy */}
    <Route path="/catalog" element={<CatalogPage />} />
    <Route path="/menu-templates" element={<MenuTemplatePage />} />
    <Route path="/menu/optimize" element={<MenuOptimizePage />} />
    <Route path="/menu/specs" element={<DishSpecPage />} />
    <Route path="/menu/sort" element={<DishSortPage />} />
    <Route path="/menu/batch" element={<DishBatchPage />} />
    <Route path="/menu/schemes" element={<MenuSchemePage />} />
    <Route path="/menu/ranking" element={<DishRankingPage />} />
    <Route path="/menu/channels" element={<ChannelMenuPage />} />
  </>
);
