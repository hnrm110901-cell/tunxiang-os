/**
 * 驾驶舱 Pin 洞察 API 客户端 — S4-04 PR2.D
 *
 * 对应 backend：services/tx-analytics/src/api/pinned_dashboard_routes.py
 *   POST   /api/v1/dashboard/pins         → 新增 Pin
 *   GET    /api/v1/dashboard/pins         → 列 active Pin
 *   DELETE /api/v1/dashboard/pins/{pin_id} → 软删（幂等）
 *
 * StandardResponse envelope ({ok, data, error}) 由 txFetchData 自动展开为 data。
 */
import { apiGet, apiPost, getTokenPayload, txFetchData } from './client';

export interface PinnedItem {
  pin_id: string;
  tenant_id: string;
  pinner_user_id: string;
  pinned_at: string;  // ISO 8601
  surface_snapshot: Record<string, unknown>;  // A2UIDeclaration shape
  source_query_id: string | null;
  source_natural_query: string | null;
}

export interface PinListResponse {
  items: PinnedItem[];
  total: number;
}

/**
 * 列出当前 tenant 的 active Pin（最新在前，最多 20 条）。
 * RLS USING 自动 tenant 过滤；跨 tenant 不可见。
 */
export async function listPinnedInsights(): Promise<PinListResponse> {
  return apiGet<PinListResponse>('/api/v1/dashboard/pins');
}

/**
 * 新增 Pin。pinner_user_id 从 JWT 取；无 token 时用 all-zeros UUID 占位
 * （TODO：未来 auth 整合后改为 throw / 触发登录跳转）。
 */
export async function createPin(
  surfaceSnapshot: Record<string, unknown>,
  sourceNaturalQuery?: string,
): Promise<PinnedItem> {
  const pinnerUserId =
    getTokenPayload()?.user_id ?? '00000000-0000-0000-0000-000000000000';
  return apiPost<PinnedItem>('/api/v1/dashboard/pins', {
    pinner_user_id: pinnerUserId,
    surface_snapshot: surfaceSnapshot,
    source_natural_query: sourceNaturalQuery ?? null,
  });
}

/**
 * 软删 Pin（幂等）。跨 tenant / 已软删 → deleted=false（不抛错）。
 */
export async function deletePin(pinId: string): Promise<{ deleted: boolean }> {
  return txFetchData<{ deleted: boolean }>(
    `/api/v1/dashboard/pins/${encodeURIComponent(pinId)}`,
    { method: 'DELETE' },
  );
}
