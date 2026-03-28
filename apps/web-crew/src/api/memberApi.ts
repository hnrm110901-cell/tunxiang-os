/**
 * 会员识别 API — /api/v1/member/*
 * 搜索会员、查看会员详情、绑定订单
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface MemberInfo {
  member_id: string;
  name: string;
  phone: string;
  level: string;
  points: number;
  balance_fen: number;
  preferences: string[];
  allergies: string[];
  visit_count: number;
  last_visit: string;
  total_spend_fen: number;
}

export interface MemberRecommendation {
  dish_id: string;
  dish_name: string;
  reason: string;
  confidence: number;
}

// ─── 接口 ───

/** 搜索会员（手机号/姓名） */
export async function searchMember(
  keyword: string,
): Promise<{ items: MemberInfo[] }> {
  return txFetch(`/api/v1/member/search?keyword=${encodeURIComponent(keyword)}`);
}

/** 获取会员详情 */
export async function getMemberDetail(
  memberId: string,
): Promise<MemberInfo> {
  return txFetch(`/api/v1/member/${encodeURIComponent(memberId)}`);
}

/** 绑定会员到订单 */
export async function bindMemberToOrder(
  orderId: string,
  memberId: string,
): Promise<{ order_id: string; member_id: string }> {
  return txFetch(`/api/v1/member/bind-order`, {
    method: 'POST',
    body: JSON.stringify({ order_id: orderId, member_id: memberId }),
  });
}

/** 获取会员个性化推荐菜品 */
export async function fetchMemberRecommendations(
  memberId: string,
  storeId: string,
): Promise<{ items: MemberRecommendation[] }> {
  return txFetch(
    `/api/v1/member/${encodeURIComponent(memberId)}/recommendations?store_id=${encodeURIComponent(storeId)}`,
  );
}

/** 会员积分抵扣 */
export async function deductPoints(
  memberId: string,
  orderId: string,
  points: number,
): Promise<{ deducted: number; discount_fen: number; remaining_points: number }> {
  return txFetch(`/api/v1/member/${encodeURIComponent(memberId)}/deduct-points`, {
    method: 'POST',
    body: JSON.stringify({ order_id: orderId, points }),
  });
}
