/**
 * 会员/顾客类型 — 对应 shared/ontology/src/entities.py Customer
 * Golden ID 全渠道画像，RFM 分层，生命周期
 */
import type { TenantEntity, PaginatedResponse, PaginationParams } from './common';
import type { RFMLevel } from './enums';

// ─────────────────────────────────────────────
// 核心实体
// ─────────────────────────────────────────────

/** 会员/顾客（CDP 统一消费者身份） */
export interface Member extends TenantEntity {
  primary_phone: string;
  display_name: string | null;
  gender: string | null;
  birth_date: string | null;
  anniversary: string | null;

  // 微信身份
  wechat_openid: string | null;
  wechat_unionid: string | null;
  wechat_nickname: string | null;
  wechat_avatar_url: string | null;

  // 消费统计
  total_order_count: number;
  total_order_amount_fen: number;
  total_reservation_count: number;
  first_order_at: string | null;
  last_order_at: string | null;
  first_store_id: string | null;

  // RFM
  rfm_recency_days: number | null;
  rfm_frequency: number | null;
  rfm_monetary_fen: number | null;
  rfm_level: RFMLevel | null;
  r_score: number | null;
  f_score: number | null;
  m_score: number | null;
  rfm_updated_at: string | null;

  // 标签 & 偏好
  tags: string[] | null;
  dietary_restrictions: string[] | null;

  // 合并追踪
  is_merged: boolean;
  merged_into: string | null;

  // 门店象限 & 流失风险
  store_quadrant: string | null;
  risk_score: number | null;

  // 来源
  source: string | null;
  confidence_score: number;
  extra: Record<string, unknown> | null;

  // 外卖平台身份
  meituan_user_id: string | null;
  meituan_openid: string | null;
  douyin_openid: string | null;
  eleme_user_id: string | null;

  // 企业微信客户联系（SCRM）
  wecom_external_userid: string | null;
  wecom_follow_user: string | null;
  wecom_follow_at: string | null;
  wecom_remark: string | null;
}

// ─────────────────────────────────────────────
// 请求类型
// ─────────────────────────────────────────────

/** 创建会员请求 */
export interface CreateMemberRequest {
  primary_phone: string;
  display_name?: string;
  gender?: string;
  birth_date?: string;
  anniversary?: string;
  wechat_openid?: string;
  wechat_unionid?: string;
  wechat_nickname?: string;
  wechat_avatar_url?: string;
  tags?: string[];
  dietary_restrictions?: string[];
  source?: string;
  extra?: Record<string, unknown>;
}

/** 更新会员请求 */
export interface UpdateMemberRequest {
  display_name?: string;
  gender?: string;
  birth_date?: string;
  anniversary?: string;
  tags?: string[];
  dietary_restrictions?: string[];
  wechat_nickname?: string;
  wechat_avatar_url?: string;
  extra?: Record<string, unknown>;
}

/** 会员列表查询参数 */
export interface MemberListParams extends PaginationParams {
  keyword?: string;
  rfm_level?: RFMLevel;
  source?: string;
  store_quadrant?: string;
  min_order_count?: number;
  max_risk_score?: number;
  is_merged?: boolean;
}

// ─────────────────────────────────────────────
// 响应类型
// ─────────────────────────────────────────────

export type MemberListResponse = PaginatedResponse<Member>;
