/**
 * 知识库管理路由
 *
 * 总部后台 → 知识库管理模块（Phase 4）
 */
import { lazy } from 'react';
import { Route } from 'react-router-dom';

// 延迟加载页面组件
const KnowledgeDashboardPage = lazy(() => import('../pages/knowledge/KnowledgeDashboardPage'));
const DocumentListPage = lazy(() => import('../pages/knowledge/DocumentListPage'));
const DocumentUploadPage = lazy(() => import('../pages/knowledge/DocumentUploadPage'));
const SearchTestPage = lazy(() => import('../pages/knowledge/SearchTestPage'));

export const knowledgeRoutes = (
  <>
    <Route path="/knowledge" element={<KnowledgeDashboardPage />} />
    <Route path="/knowledge/documents" element={<DocumentListPage />} />
    <Route path="/knowledge/upload" element={<DocumentUploadPage />} />
    <Route path="/knowledge/search" element={<SearchTestPage />} />
  </>
);
