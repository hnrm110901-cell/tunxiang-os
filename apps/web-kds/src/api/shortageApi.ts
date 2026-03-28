/**
 * 缺料联动 API — /api/v1/kds/shortage/*
 * 缺料上报、联动沽清、缺料记录查询
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface Ingredient {
  ingredient_id: string;
  name: string;
  category: string;
  unit: string;
  current_stock: number;
  safety_stock: number;
}

export interface ShortageRecord {
  shortage_id: string;
  ingredient_id: string;
  ingredient_name: string;
  reported_at: string;
  reporter_id: string;
  reporter_name: string;
  affected_dishes: string[];
  status: 'reported' | 'confirmed' | 'resolved';
  auto_sold_out: boolean;
}

// ─── 接口 ───

/** 获取当前工作站相关原料库存 */
export async function fetchStationIngredients(
  stationId: string,
): Promise<{ items: Ingredient[] }> {
  return txFetch(
    `/api/v1/kds/shortage/ingredients?station_id=${encodeURIComponent(stationId)}`,
  );
}

/** 上报缺料 */
export async function reportShortage(
  stationId: string,
  ingredientId: string,
  reporterId: string,
): Promise<{ shortage_id: string; affected_dishes: string[]; auto_sold_out: boolean }> {
  return txFetch('/api/v1/kds/shortage/report', {
    method: 'POST',
    body: JSON.stringify({
      station_id: stationId,
      ingredient_id: ingredientId,
      reporter_id: reporterId,
    }),
  });
}

/** 查询缺料记录 */
export async function fetchShortageRecords(
  stationId: string,
  status?: string,
): Promise<{ items: ShortageRecord[] }> {
  const statusParam = status ? `&status=${encodeURIComponent(status)}` : '';
  return txFetch(
    `/api/v1/kds/shortage/records?station_id=${encodeURIComponent(stationId)}${statusParam}`,
  );
}

/** 确认缺料已补充（解除沽清） */
export async function resolveShortage(
  shortageId: string,
): Promise<{ shortage_id: string; status: string; restored_dishes: string[] }> {
  return txFetch(`/api/v1/kds/shortage/${encodeURIComponent(shortageId)}/resolve`, {
    method: 'POST',
  });
}
