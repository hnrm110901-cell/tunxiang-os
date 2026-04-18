/**
 * 演示/训练模式 API 客户端
 *
 * 对接 tx-trade /api/v1/training-mode/* 端点
 * Redis 驱动的服务端状态，支持多设备同步
 */
import { txFetch } from './index';

// ─── 类型 ──────────────────────────────────────────────────────────────────

export interface TrainingModeStatus {
  is_demo_mode: boolean;
  demo_tenant_id: string;
  watermark_text: string;
  auto_reset_minutes: number;
  enabled_at?: string;
  enabled_by?: string;
}

export interface EnableTrainingModePayload {
  duration_minutes?: number;
  watermark_text?: string;
  operator_id?: string;
}

// ─── API 函数 ──────────────────────────────────────────────────────────────

/**
 * 查询门店演示模式状态
 * 轮询间隔建议：30秒（低频，不影响收银性能）
 */
export async function fetchTrainingModeStatus(
  storeId: string,
): Promise<TrainingModeStatus> {
  return txFetch<TrainingModeStatus>(
    `/api/v1/training-mode/status/${storeId}`,
  );
}

/**
 * 启用演示模式
 * @param storeId 门店ID
 * @param payload 配置（时长/水印文字/操作人）
 */
export async function enableTrainingMode(
  storeId: string,
  payload: EnableTrainingModePayload = {},
): Promise<{ success: boolean; message: string; duration_minutes: number; watermark_text: string }> {
  return txFetch<{ success: boolean; message: string; duration_minutes: number; watermark_text: string }>(
    `/api/v1/training-mode/enable/${storeId}`,
    {
      method: 'POST',
      body: JSON.stringify({
        duration_minutes: payload.duration_minutes ?? 60,
        watermark_text: payload.watermark_text ?? '演示模式',
        operator_id: payload.operator_id,
      }),
    },
  );
}

/**
 * 关闭演示模式
 */
export async function disableTrainingMode(
  storeId: string,
): Promise<{ success: boolean; message: string }> {
  return txFetch<{ success: boolean; message: string }>(
    `/api/v1/training-mode/disable/${storeId}`,
    { method: 'POST' },
  );
}

/**
 * 重置演示数据（清除所有演示订单记录，同时关闭演示模式）
 */
export async function resetTrainingData(
  storeId: string,
): Promise<{ success: boolean; message: string; cleared_order_count: number }> {
  return txFetch<{ success: boolean; message: string; cleared_order_count: number }>(
    `/api/v1/training-mode/reset/${storeId}`,
    { method: 'POST' },
  );
}

/**
 * 获取当前演示会话产生的所有演示订单
 */
export async function fetchDemoOrders(
  storeId: string,
): Promise<{ store_id: string; demo_order_ids: string[]; total_count: number }> {
  return txFetch<{ store_id: string; demo_order_ids: string[]; total_count: number }>(
    `/api/v1/training-mode/demo-orders/${storeId}`,
  );
}
