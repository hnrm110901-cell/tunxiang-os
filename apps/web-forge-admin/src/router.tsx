import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'

const OverviewPage      = lazy(() => import('./pages/OverviewPage'))
const CatalogPage       = lazy(() => import('./pages/CatalogPage'))
const ReviewPage        = lazy(() => import('./pages/ReviewPage'))
const MakersPage        = lazy(() => import('./pages/MakersPage'))
const SubscriptionsPage = lazy(() => import('./pages/SubscriptionsPage'))
const LabsPage          = lazy(() => import('./pages/LabsPage'))
const AdaptersPage      = lazy(() => import('./pages/AdaptersPage'))
const FinancePage       = lazy(() => import('./pages/FinancePage'))
const AnalyticsPage     = lazy(() => import('./pages/AnalyticsPage'))
const ContentPage       = lazy(() => import('./pages/ContentPage'))
const AgentObservatoryPage = lazy(() => import('./pages/AgentObservatoryPage'))
const ModelRegistryPage    = lazy(() => import('./pages/ModelRegistryPage'))
const LlmObservabilityPage = lazy(() => import('./pages/LlmObservabilityPage'))
const SecurityPage      = lazy(() => import('./pages/SecurityPage'))
const IntegrationsPage  = lazy(() => import('./pages/IntegrationsPage'))
const SettingsPage      = lazy(() => import('./pages/SettingsPage'))
const RbacPage          = lazy(() => import('./pages/RbacPage'))
const TrustTierPage     = lazy(() => import('./pages/TrustTierPage'))
const RuntimePolicyPage = lazy(() => import('./pages/RuntimePolicyPage'))
const MCPRegistryPage   = lazy(() => import('./pages/MCPRegistryPage'))
const OntologyMapPage      = lazy(() => import('./pages/OntologyMapPage'))
const OutcomePricingPage   = lazy(() => import('./pages/OutcomePricingPage'))
const TokenMeterPage       = lazy(() => import('./pages/TokenMeterPage'))
const SmartDiscoveryPage   = lazy(() => import('./pages/SmartDiscoveryPage'))
const EvidenceCardsPage    = lazy(() => import('./pages/EvidenceCardsPage'))
const ForgeBuilderPage     = lazy(() => import('./pages/ForgeBuilderPage'))
const AutoReviewPage       = lazy(() => import('./pages/AutoReviewPage'))
const AllianceMarketPage   = lazy(() => import('./pages/AllianceMarketPage'))
const WorkflowEditorPage   = lazy(() => import('./pages/WorkflowEditorPage'))
const EcosystemHealthPage  = lazy(() => import('./pages/EcosystemHealthPage'))

export function AppRouter() {
  return (
    <Suspense fallback={<div style={{ padding: 32, color: 'var(--ink-300)' }}>载入中…</div>}>
      <Routes>
        <Route path="/" element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/catalog" element={<CatalogPage />} />
        <Route path="/review" element={<ReviewPage />} />
        <Route path="/makers" element={<MakersPage />} />
        <Route path="/subscriptions" element={<SubscriptionsPage />} />
        <Route path="/labs" element={<LabsPage />} />
        <Route path="/adapters" element={<AdaptersPage />} />
        <Route path="/finance" element={<FinancePage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/content" element={<ContentPage />} />
        <Route path="/agent-observatory" element={<AgentObservatoryPage />} />
        <Route path="/model-registry" element={<ModelRegistryPage />} />
        <Route path="/llm-observability" element={<LlmObservabilityPage />} />
        <Route path="/security" element={<SecurityPage />} />
        <Route path="/integrations" element={<IntegrationsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/rbac" element={<RbacPage />} />
        <Route path="/trust" element={<TrustTierPage />} />
        <Route path="/runtime" element={<RuntimePolicyPage />} />
        <Route path="/mcp" element={<MCPRegistryPage />} />
        <Route path="/ontology" element={<OntologyMapPage />} />
        <Route path="/outcomes" element={<OutcomePricingPage />} />
        <Route path="/tokens" element={<TokenMeterPage />} />
        <Route path="/discovery" element={<SmartDiscoveryPage />} />
        <Route path="/evidence" element={<EvidenceCardsPage />} />
        <Route path="/builder" element={<ForgeBuilderPage />} />
        <Route path="/auto-review" element={<AutoReviewPage />} />
        <Route path="/alliance" element={<AllianceMarketPage />} />
        <Route path="/workflows" element={<WorkflowEditorPage />} />
        <Route path="/ecosystem" element={<EcosystemHealthPage />} />
      </Routes>
    </Suspense>
  )
}
