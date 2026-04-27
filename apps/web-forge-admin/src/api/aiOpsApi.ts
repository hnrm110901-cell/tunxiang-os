import { forgeApi } from './client'

export const aiOpsApi = {
  agents: (params?: Record<string, string>) => forgeApi(`/ai-ops/agents?${new URLSearchParams(params)}`),
  agentDetail: (id: string, days?: number) => forgeApi(`/ai-ops/agents/${id}?days=${days || 7}`),
  traces: (params?: Record<string, string>) => forgeApi(`/ai-ops/traces?${new URLSearchParams(params)}`),
  traceDetail: (sessionId: string) => forgeApi(`/ai-ops/traces/${sessionId}`),
  decisions: (params?: Record<string, string>) => forgeApi(`/ai-ops/decisions?${new URLSearchParams(params)}`),
  models: (days?: number) => forgeApi(`/ai-ops/models?days=${days || 30}`),
  llmCost: (params?: Record<string, string>) => forgeApi(`/ai-ops/llm/cost?${new URLSearchParams(params)}`),
  llmLatency: (params?: Record<string, string>) => forgeApi(`/ai-ops/llm/latency?${new URLSearchParams(params)}`),
  memories: (params?: Record<string, string>) => forgeApi(`/ai-ops/memories?${new URLSearchParams(params)}`),
}
