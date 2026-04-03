/**
 * 会员洞察 API — /api/v1/members/{member_id}/insights/*
 * 开台时调用，获取 AI 会员画像用于实时 Push 给服务员
 */
import { txFetch } from './index';

// ─── 类型定义 ───

export interface InsightAlert {
  type: 'allergy' | 'preference' | 'vip' | string;
  severity: 'danger' | 'warning' | 'info';
  icon: string;
  title: string;
  body: string;
}

export interface InsightSuggestion {
  type: 'upsell' | 'celebration' | 'retention' | string;
  icon: string;
  title: string;
  body: string;
}

export interface MemberInsightProfile {
  visit_count: number;
  last_visit: string;
  avg_spend_fen: number;
  favorite_dishes: string[];
  avoided_items: string[];
  preferences: string[];
}

export interface MemberInsight {
  member_id: string;
  generated_at: string;
  profile: MemberInsightProfile;
  alerts: InsightAlert[];
  suggestions: InsightSuggestion[];
  service_tips: string;
}

// ─── 接口 ───

/**
 * 生成会员洞察（开台绑定会员后调用）
 * POST /api/v1/members/{member_id}/insights/generate
 */
export async function generateMemberInsight(
  memberId: string,
  orderId: string,
  storeId: string,
): Promise<MemberInsight> {
  return txFetch<MemberInsight>(
    `/api/v1/members/${encodeURIComponent(memberId)}/insights/generate`,
    {
      method: 'POST',
      body: JSON.stringify({ order_id: orderId, store_id: storeId }),
    },
  );
}

/**
 * 获取最近一次洞察缓存
 * GET /api/v1/members/{member_id}/insights/latest
 * 返回 null 表示缓存不存在（应重新 generate）
 */
export async function getLatestInsight(memberId: string): Promise<MemberInsight | null> {
  try {
    return await txFetch<MemberInsight>(
      `/api/v1/members/${encodeURIComponent(memberId)}/insights/latest`,
    );
  } catch {
    // 404 or any error: cache miss, caller should call generate
    return null;
  }
}
