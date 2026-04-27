import { forgeApi } from './client'

// Marketplace APIs
export const developerApi = {
  list: (params?: Record<string, string>) => forgeApi(`/developers?${new URLSearchParams(params)}`),
  get: (id: string) => forgeApi(`/developers/${id}`),
  create: (data: any) => forgeApi('/developers', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => forgeApi(`/developers/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  revenue: (id: string) => forgeApi(`/developers/${id}/revenue`),
}

export const appApi = {
  list: (params?: Record<string, string>) => forgeApi(`/apps?${new URLSearchParams(params)}`),
  get: (id: string) => forgeApi(`/apps/${id}`),
  submit: (data: any) => forgeApi('/apps', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => forgeApi(`/apps/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  revenue: (id: string) => forgeApi(`/apps/${id}/revenue`),
  reviews: (id: string) => forgeApi(`/apps/${id}/reviews`),
}

export const reviewApi = {
  pending: () => forgeApi('/reviews/pending'),
  submit: (data: any) => forgeApi('/reviews', { method: 'POST', body: JSON.stringify(data) }),
}

export const installApi = {
  list: () => forgeApi('/installations'),
  install: (data: any) => forgeApi('/installations', { method: 'POST', body: JSON.stringify(data) }),
  uninstall: (appId: string) => forgeApi(`/installations/${appId}`, { method: 'DELETE' }),
  status: (appId: string) => forgeApi(`/installations/${appId}/status`),
}

export const analyticsApi = {
  stats: () => forgeApi('/analytics/stats'),
  trending: (params?: Record<string, string>) => forgeApi(`/analytics/trending?${new URLSearchParams(params)}`),
  categories: () => forgeApi('/analytics/categories'),
}

// v1.5 Trust & Governance APIs
export const trustApi = {
  tiers: () => forgeApi('/trust/tiers'),
  appStatus: (appId: string) => forgeApi(`/trust/${appId}/status`),
  submitAudit: (data: any) => forgeApi('/trust/audit', { method: 'POST', body: JSON.stringify(data) }),
  requestUpgrade: (appId: string, data: any) => forgeApi(`/trust/${appId}/upgrade`, { method: 'POST', body: JSON.stringify(data) }),
  downgrade: (appId: string, data: any) => forgeApi(`/trust/${appId}/downgrade`, { method: 'POST', body: JSON.stringify(data) }),
}

export const runtimeApi = {
  getPolicy: (appId: string) => forgeApi(`/runtime/${appId}/policy`),
  updatePolicy: (appId: string, data: any) => forgeApi(`/runtime/${appId}/policy`, { method: 'PUT', body: JSON.stringify(data) }),
  kill: (appId: string, data: any) => forgeApi(`/runtime/${appId}/kill`, { method: 'POST', body: JSON.stringify(data) }),
  unkill: (appId: string) => forgeApi(`/runtime/${appId}/kill`, { method: 'DELETE' }),
  violations: (params?: Record<string, string>) => forgeApi(`/runtime/violations?${new URLSearchParams(params)}`),
}

export const mcpApi = {
  servers: (params?: Record<string, string>) => forgeApi(`/mcp/servers?${new URLSearchParams(params)}`),
  serverDetail: (id: string) => forgeApi(`/mcp/servers/${id}`),
  registerServer: (data: any) => forgeApi('/mcp/servers', { method: 'POST', body: JSON.stringify(data) }),
  tools: (params?: Record<string, string>) => forgeApi(`/mcp/tools?${new URLSearchParams(params)}`),
  toolSchema: (id: string) => forgeApi(`/mcp/tools/${id}/schema`),
  registerTool: (data: any) => forgeApi('/mcp/tools', { method: 'POST', body: JSON.stringify(data) }),
}

export const ontologyApi = {
  bindings: (params?: Record<string, string>) => forgeApi(`/ontology/bindings?${new URLSearchParams(params)}`),
  setBinding: (data: any) => forgeApi('/ontology/bindings', { method: 'PUT', body: JSON.stringify(data) }),
  entityApps: (entity: string) => forgeApi(`/ontology/${entity}/apps`),
  validateManifest: (data: any) => forgeApi('/manifest/validate', { method: 'POST', body: JSON.stringify(data) }),
  submitManifest: (data: any) => forgeApi('/manifest/submit', { method: 'POST', body: JSON.stringify(data) }),
}

// ─── v2.0 Agent Exchange APIs ───────────────────────────────────────

export const outcomeApi = {
  definitions: (params?: Record<string, string>) => forgeApi(`/outcomes/definitions?${new URLSearchParams(params)}`),
  createDefinition: (data: any) => forgeApi('/outcomes/definitions', { method: 'POST', body: JSON.stringify(data) }),
  recordEvent: (data: any) => forgeApi('/outcomes/events', { method: 'POST', body: JSON.stringify(data) }),
  verifyEvent: (eventId: string, data: any) => forgeApi(`/outcomes/events/${eventId}/verify`, { method: 'POST', body: JSON.stringify(data) }),
  dashboard: (params?: Record<string, string>) => forgeApi(`/outcomes/dashboard?${new URLSearchParams(params)}`),
  events: (params?: Record<string, string>) => forgeApi(`/outcomes/events?${new URLSearchParams(params)}`),
}

export const tokenApi = {
  recordUsage: (data: any) => forgeApi('/tokens/usage', { method: 'POST', body: JSON.stringify(data) }),
  getUsage: (params: Record<string, string>) => forgeApi(`/tokens/usage?${new URLSearchParams(params)}`),
  getTrend: (params: Record<string, string>) => forgeApi(`/tokens/trend?${new URLSearchParams(params)}`),
  setPricing: (data: any) => forgeApi('/tokens/pricing', { method: 'PUT', body: JSON.stringify(data) }),
  getAlerts: () => forgeApi('/tokens/alerts'),
}

export const discoveryApi = {
  search: (data: { query: string }) => forgeApi('/discovery/search', { method: 'POST', body: JSON.stringify(data) }),
  recordClick: (searchId: string, data: any) => forgeApi(`/discovery/search/${searchId}/click`, { method: 'POST', body: JSON.stringify(data) }),
  analytics: (params?: Record<string, string>) => forgeApi(`/discovery/analytics?${new URLSearchParams(params)}`),
  combos: (params?: Record<string, string>) => forgeApi(`/discovery/combos?${new URLSearchParams(params)}`),
  roleRecommendations: (role: string) => forgeApi(`/discovery/roles/${encodeURIComponent(role)}`),
}

export const evidenceApi = {
  createCard: (data: any) => forgeApi('/evidence/cards', { method: 'POST', body: JSON.stringify(data) }),
  listCards: (params?: Record<string, string>) => forgeApi(`/evidence/cards?${new URLSearchParams(params)}`),
  appProfile: (appId: string) => forgeApi(`/evidence/${appId}/profile`),
  updateCard: (cardId: string, data: any) => forgeApi(`/evidence/cards/${cardId}`, { method: 'PUT', body: JSON.stringify(data) }),
}

// ─── v2.5 Developer Enablement APIs ─────────────────────────────────

export const builderApi = {
  createProject: (data: any) => forgeApi('/builder/projects', { method: 'POST', body: JSON.stringify(data) }),
  listProjects: (params?: Record<string, string>) => forgeApi(`/builder/projects?${new URLSearchParams(params)}`),
  getProject: (id: string) => forgeApi(`/builder/projects/${id}`),
  updateProject: (id: string, data: any) => forgeApi(`/builder/projects/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  submitProject: (id: string) => forgeApi(`/builder/projects/${id}/submit`, { method: 'POST' }),
  templates: (params?: Record<string, string>) => forgeApi(`/builder/templates?${new URLSearchParams(params)}`),
}

export const autoReviewApi = {
  run: (data: any) => forgeApi('/auto-review/run', { method: 'POST', body: JSON.stringify(data) }),
  get: (reviewId: string) => forgeApi(`/auto-review/${reviewId}`),
  list: (params?: Record<string, string>) => forgeApi(`/auto-review?${new URLSearchParams(params)}`),
  templates: (params?: Record<string, string>) => forgeApi(`/auto-review/templates?${new URLSearchParams(params)}`),
}

// ─── v3.0 Ecosystem Flywheel APIs ───────────────────────────────────

export const allianceApi = {
  createListing: (data: any) => forgeApi('/alliance/listings', { method: 'POST', body: JSON.stringify(data) }),
  listListings: (params?: Record<string, string>) => forgeApi(`/alliance/listings?${new URLSearchParams(params)}`),
  getListing: (id: string) => forgeApi(`/alliance/listings/${id}`),
  installAlliance: (listingId: string) => forgeApi(`/alliance/listings/${listingId}/install`, { method: 'POST' }),
  revenue: (params?: Record<string, string>) => forgeApi(`/alliance/revenue?${new URLSearchParams(params)}`),
}

export const workflowApi = {
  create: (data: any) => forgeApi('/workflows', { method: 'POST', body: JSON.stringify(data) }),
  list: (params?: Record<string, string>) => forgeApi(`/workflows?${new URLSearchParams(params)}`),
  get: (id: string) => forgeApi(`/workflows/${id}`),
  startRun: (id: string, data?: any) => forgeApi(`/workflows/${id}/run`, { method: 'POST', body: JSON.stringify(data || {}) }),
  listRuns: (id: string, params?: Record<string, string>) => forgeApi(`/workflows/${id}/runs?${new URLSearchParams(params)}`),
  analytics: (id: string) => forgeApi(`/workflows/${id}/analytics`),
}

export const ecosystemApi = {
  compute: () => forgeApi('/ecosystem/compute', { method: 'POST' }),
  metrics: (params?: Record<string, string>) => forgeApi(`/ecosystem/metrics?${new URLSearchParams(params)}`),
  flywheel: () => forgeApi('/ecosystem/flywheel'),
}
