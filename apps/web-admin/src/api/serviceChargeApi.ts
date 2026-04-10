/**
 * 服务费配置 API 客户端
 * 对应后端: services/tx-trade/src/api/service_charge_routes.py
 */
import { txFetchData } from './client';

// ─── 类型定义 ───

export interface ServiceChargeConfig {
  store_id: string;
  enabled: boolean;
  charge_type: 'percentage' | 'fixed' | 'per_person';
  rate?: number;                    // 百分比时使用，如 10 表示 10%
  fixed_amount_fen?: number;        // 固定金额(分)
  per_person_fen?: number;          // 人头费(分/人)
  min_amount_fen?: number;          // 最低消费(分)，0表示不限
  applicable_days?: number[];       // 适用星期，0=周日，1-6=周一到六
  applicable_hours?: {              // 适用时段
    start: string;                  // 'HH:mm'
    end: string;
  } | null;
  exempt_member_levels?: string[];  // 免收服务费的会员等级
  room_type?: string;               // 适用包房类型，null=全部
}

export interface ServiceChargeTemplate {
  id: string;
  name: string;
  rules: ServiceChargeConfig;
  tenant_id: string;
  created_at: string;
  applied_stores?: string[];
}

export interface CalculateServiceChargeParams {
  order_id?: string;
  store_id: string;
  guest_count?: number;
  order_amount_fen: number;
  room_type?: string;
  duration_minutes?: number;
}

export interface ServiceChargeResult {
  store_id: string;
  charge_fen: number;
  charge_mode: string;
  breakdown: Array<{
    rule: string;
    amount_fen: number;
    description: string;
  }>;
}

// ─── API 函数 ───

/** 获取门店服务费配置 GET /api/v1/service-charge/config/{store_id} */
export async function getChargeConfig(storeId: string): Promise<ServiceChargeConfig> {
  return txFetchData(`/api/v1/service-charge/config/${encodeURIComponent(storeId)}`);
}

/** 设置门店服务费配置 POST /api/v1/service-charge/config */
export async function setChargeConfig(
  storeId: string,
  config: Omit<ServiceChargeConfig, 'store_id'>,
): Promise<ServiceChargeConfig> {
  return txFetchData('/api/v1/service-charge/config', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, config }),
  });
}

/** 计算服务费 POST /api/v1/service-charge/calculate */
export async function calculateServiceCharge(
  storeId: string,
  orderAmountFen: number,
  guestCount: number,
  extra?: { orderId?: string; roomType?: string; durationMinutes?: number },
): Promise<ServiceChargeResult> {
  return txFetchData('/api/v1/service-charge/calculate', {
    method: 'POST',
    body: JSON.stringify({
      order_id: extra?.orderId || `preview_${Date.now()}`,
      store_id: storeId,
      guest_count: guestCount,
      order_amount_fen: orderAmountFen,
      room_type: extra?.roomType,
      duration_minutes: extra?.durationMinutes || 0,
    }),
  });
}

/** 创建服务费模板 POST /api/v1/service-charge/template */
export async function createTemplate(data: {
  name: string;
  rules: Omit<ServiceChargeConfig, 'store_id'>;
}): Promise<ServiceChargeTemplate> {
  return txFetchData('/api/v1/service-charge/template', {
    method: 'POST',
    body: JSON.stringify({ name: data.name, rules: data.rules }),
  });
}

/** 下发模板到门店 POST /api/v1/service-charge/template/publish */
export async function publishTemplate(
  templateId: string,
  storeIds: string[],
): Promise<{ published_count: number; failed_stores: string[] }> {
  return txFetchData('/api/v1/service-charge/template/publish', {
    method: 'POST',
    body: JSON.stringify({ template_id: templateId, store_ids: storeIds }),
  });
}
