/** 与后端 services/tx-devforge/src/models/application.py 对齐 */

export type ResourceType =
  | 'backend_service'
  | 'frontend_app'
  | 'edge_image'
  | 'adapter'
  | 'data_asset'

export const RESOURCE_TYPE_LABELS: Record<ResourceType, string> = {
  backend_service: '后端服务',
  frontend_app: '前端应用',
  edge_image: '边缘镜像',
  adapter: '适配器',
  data_asset: '数据资产',
}

export const RESOURCE_TYPE_COLORS: Record<ResourceType, string> = {
  backend_service: 'blue',
  frontend_app: 'green',
  edge_image: 'orange',
  adapter: 'purple',
  data_asset: 'gold',
}

export interface Application {
  id: string
  tenant_id: string
  code: string
  name: string
  resource_type: ResourceType
  owner: string | null
  repo_path: string | null
  tech_stack: string | null
  description: string | null
  metadata_json: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ApplicationListResponse {
  ok: boolean
  data: {
    items: Application[]
    total: number
  }
  error?: { code: string; message: string }
}

export interface ApplicationCreatePayload {
  code: string
  name: string
  resource_type: ResourceType
  owner?: string
  repo_path?: string
  tech_stack?: string
  description?: string
  metadata_json?: Record<string, unknown>
}

export interface ApplicationListQuery {
  page?: number
  size?: number
  resource_type?: ResourceType
  q?: string
}
