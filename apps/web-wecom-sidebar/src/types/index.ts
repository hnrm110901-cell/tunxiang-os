// ─────────────────────────────────────────────────────────────────
// 企微侧边栏 — 类型定义
// ─────────────────────────────────────────────────────────────────

/** 会员等级 */
export type MemberLevel = 'normal' | 'silver' | 'gold' | 'diamond';

/** RFM 分层（S1=最优质, S5=最高风险） */
export type RfmLevel = 'S1' | 'S2' | 'S3' | 'S4' | 'S5';

/** 偏好菜品 */
export interface FavoriteDish {
  name: string;
  order_times: number;
}

/** 客户 360 度档案（对应 tx-member API 返回字段） */
export interface CustomerProfile {
  customer_id: string;
  display_name: string;
  wechat_avatar_url?: string;
  member_level: MemberLevel;
  rfm_level: RfmLevel;
  r_score: number;   // 近度得分 1-5
  f_score: number;   // 频度得分 1-5
  m_score: number;   // 消费额得分 1-5
  total_order_amount_fen: number;   // 单位：分
  total_order_count: number;
  last_order_at?: string;           // ISO 8601
  risk_score: number;               // 0.0 - 1.0，流失风险
  tags: string[];
  favorite_dishes: FavoriteDish[];
  wecom_remark?: string;
  wecom_external_userid?: string;
}

/** 优惠券（发券用） */
export interface Coupon {
  coupon_id: string;
  name: string;
  discount_desc: string;   // "满100减20"
  expire_at: string;
}

/** 快捷操作面板 — 弹层类型 */
export type ActionPanelMode = 'coupon' | 'tag' | 'remark' | null;

/** 企微 JS-SDK 配置（后端返回） */
export interface JssdkConfig {
  appId: string;
  timestamp: number;
  nonceStr: string;
  signature: string;
  agentSignature: string;
  agentId: string;
}

/** 统一 API 响应结构 */
export interface ApiResponse<T> {
  ok: boolean;
  data: T;
  error?: {
    code: string;
    message: string;
  };
}
