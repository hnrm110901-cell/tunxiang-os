import { apiClient } from './client'
import type {
  Application,
  ApplicationCreatePayload,
  ApplicationListQuery,
  ApplicationListResponse,
} from '@/types/application'

const PREFIX = '/api/v1/devforge/applications'

/** Mock 数据 — 后端未启动时 fallback */
const MOCK_APPS: Application[] = [
  {
    id: 'mock-1',
    tenant_id: 'demo-tenant',
    code: 'tx-trade',
    name: '交易履约服务',
    resource_type: 'backend_service',
    owner: '未了已',
    repo_path: 'services/tx-trade',
    tech_stack: 'python',
    description: '90 路由文件 · 收银/桌台/KDS/预订/宴席/外卖',
    metadata_json: { port: 8001 },
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-25T10:00:00Z',
  },
  {
    id: 'mock-2',
    tenant_id: 'demo-tenant',
    code: 'web-pos',
    name: 'POS 收银前端',
    resource_type: 'frontend_app',
    owner: '前端组',
    repo_path: 'apps/web-pos',
    tech_stack: 'typescript',
    description: '20+ 路由 · 安卓/Windows/iPad 共用',
    metadata_json: {},
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-26T08:00:00Z',
  },
  {
    id: 'mock-3',
    tenant_id: 'demo-tenant',
    code: 'mac-station',
    name: 'Mac mini 边缘站',
    resource_type: 'edge_image',
    owner: '边缘组',
    repo_path: 'edge/mac-station',
    tech_stack: 'python',
    description: '门店本地 API + PostgreSQL 副本',
    metadata_json: {},
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-20T12:00:00Z',
  },
  {
    id: 'mock-4',
    tenant_id: 'demo-tenant',
    code: 'adapter-pinjin',
    name: '品智 POS 适配器',
    resource_type: 'adapter',
    owner: '集成组',
    repo_path: 'shared/adapters/pinjin',
    tech_stack: 'python',
    description: '尝在一起首批客户',
    metadata_json: {},
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-15T09:00:00Z',
  },
  {
    id: 'mock-5',
    tenant_id: 'demo-tenant',
    code: 'mv-store-pnl',
    name: '门店 P&L 物化视图',
    resource_type: 'data_asset',
    owner: '数据组',
    repo_path: 'shared/db-migrations/v148',
    tech_stack: 'sql',
    description: '8 个物化视图之一',
    metadata_json: {},
    created_at: '2026-04-04T00:00:00Z',
    updated_at: '2026-04-04T00:00:00Z',
  },
]

/** 列出应用 — 失败时 fallback 到 mock */
export async function listApplications(
  query: ApplicationListQuery = {},
): Promise<{ items: Application[]; total: number; usingMock: boolean }> {
  try {
    const resp = await apiClient.get<ApplicationListResponse>(PREFIX, { params: query })
    if (resp.data?.ok && resp.data?.data) {
      return { ...resp.data.data, usingMock: false }
    }
    throw new Error('Invalid response shape')
  } catch (err) {
    // Fallback to mock
    let items = MOCK_APPS
    if (query.resource_type) {
      items = items.filter((a) => a.resource_type === query.resource_type)
    }
    if (query.q) {
      const q = query.q.toLowerCase()
      items = items.filter(
        (a) =>
          a.code.toLowerCase().includes(q) ||
          a.name.toLowerCase().includes(q) ||
          (a.description ?? '').toLowerCase().includes(q),
      )
    }
    return { items, total: items.length, usingMock: true }
  }
}

export async function getApplication(id: string): Promise<Application | null> {
  try {
    const resp = await apiClient.get<{ ok: boolean; data: Application }>(`${PREFIX}/${id}`)
    return resp.data?.data ?? null
  } catch {
    return MOCK_APPS.find((a) => a.id === id) ?? null
  }
}

export async function createApplication(payload: ApplicationCreatePayload): Promise<Application> {
  const resp = await apiClient.post<{ ok: boolean; data: Application }>(PREFIX, payload)
  return resp.data.data
}

export async function updateApplication(
  id: string,
  payload: Partial<ApplicationCreatePayload>,
): Promise<Application> {
  const resp = await apiClient.patch<{ ok: boolean; data: Application }>(
    `${PREFIX}/${id}`,
    payload,
  )
  return resp.data.data
}

export async function deleteApplication(id: string): Promise<void> {
  await apiClient.delete(`${PREFIX}/${id}`)
}
