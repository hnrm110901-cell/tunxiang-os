import { lazy, Suspense } from 'react'
import { createBrowserRouter, Navigate } from 'react-router-dom'
import { Spin } from 'antd'
import { AppLayout } from './layout/AppLayout'

// 15 个一级模块（懒加载）
const DashboardPage   = lazy(() => import('./pages/dashboard'))
const AppsPage        = lazy(() => import('./pages/apps'))
const AppDetailPage   = lazy(() => import('./pages/apps/AppDetail'))
const SourcePage      = lazy(() => import('./pages/source'))
const PipelinePage    = lazy(() => import('./pages/pipeline'))
const ArtifactPage    = lazy(() => import('./pages/artifact'))
const TestPage        = lazy(() => import('./pages/test'))
const DeployPage      = lazy(() => import('./pages/deploy'))
const ReleasePage     = lazy(() => import('./pages/release'))
const ConfigPage      = lazy(() => import('./pages/config'))
const ObservePage     = lazy(() => import('./pages/observe'))
const EdgePage        = lazy(() => import('./pages/edge'))
const DataPage        = lazy(() => import('./pages/data'))
const IntegrationPage = lazy(() => import('./pages/integration'))
const SecurityPage    = lazy(() => import('./pages/security'))
const SystemPage      = lazy(() => import('./pages/system'))

const withSuspense = (node: React.ReactNode) => (
  <Suspense
    fallback={
      <div style={{ padding: 48, display: 'flex', justifyContent: 'center' }}>
        <Spin />
      </div>
    }
  >
    {node}
  </Suspense>
)

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard',     element: withSuspense(<DashboardPage />) },
      { path: 'apps',          element: withSuspense(<AppsPage />) },
      { path: 'apps/:id',      element: withSuspense(<AppDetailPage />) },
      { path: 'source',        element: withSuspense(<SourcePage />) },
      { path: 'pipeline',      element: withSuspense(<PipelinePage />) },
      { path: 'artifact',      element: withSuspense(<ArtifactPage />) },
      { path: 'test',          element: withSuspense(<TestPage />) },
      { path: 'deploy',        element: withSuspense(<DeployPage />) },
      { path: 'release',       element: withSuspense(<ReleasePage />) },
      { path: 'config',        element: withSuspense(<ConfigPage />) },
      { path: 'observe',       element: withSuspense(<ObservePage />) },
      { path: 'edge',          element: withSuspense(<EdgePage />) },
      { path: 'data',          element: withSuspense(<DataPage />) },
      { path: 'integration',   element: withSuspense(<IntegrationPage />) },
      { path: 'security',      element: withSuspense(<SecurityPage />) },
      { path: 'system',        element: withSuspense(<SystemPage />) },
    ],
  },
])
