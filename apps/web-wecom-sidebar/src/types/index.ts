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

/** Tab类型 */
export type ProfileTab = 'info' | 'tags' | 'card' | 'coupons';

/** 消费洞察详情 */
export interface ConsumptionDetail {
  total_amount_fen: number;
  total_count: number;
  avg_amount_fen: number;
  max_amount_fen: number;
  min_amount_fen: number;
  last_order_at?: string;
  last_order_days?: number;
  last_store_name?: string;
  avg_interval_days?: number;
  recent_30d_count?: number;
  recent_30d_amount_fen?: number;
}

/** 菜品偏好(含百分比) */
export interface DishPreference {
  dish_name: string;
  order_times: number;
  percentage: number;              // 0.0 - 1.0
}

/** 储值信息 */
export interface StoredValueInfo {
  balance_fen: number;
  total_recharged_fen: number;
  recharge_count: number;
  last_recharge_at?: string;
}

/** 积分信息 */
export interface PointsInfo {
  balance: number;
  total_earned: number;
  total_used: number;
}

/** 会员卡信息 */
export interface MemberCardInfo {
  card_no: string;
  level: string;
  level_name: string;
  expire_at?: string;
  upgrade_progress?: number;       // 0.0 - 1.0
  next_level?: string;
}

/** 可用券 */
export interface AvailableCoupon {
  coupon_id: string;
  name: string;
  discount_desc: string;
  expire_at: string;
  status: string;
}

/** 发券记录 */
export interface CouponSendRecord {
  coupon_name: string;
  sent_at: string;
  send_status: string;             // sent/received/used/expired/failed
  employee_name?: string;
}

/** 客户 360 度档案（对应 tx-member API 返回字段） */
export interface CustomerProfile {
  // === 现有字段 ===
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

  // === 新增字段 ===
  phone?: string;                    // 脱敏手机号
  gender?: string;
  birthday?: string;
  birthday_coming?: boolean;         // 7天内是否生日
  member_since?: string;
  channel_source?: string;
  wechat_nickname?: string;

  // 消费洞察
  consumption?: ConsumptionDetail;

  // 菜品偏好(含百分比)
  dish_preferences?: DishPreference[];

  // 口味标签
  taste_tags?: string[];
  scene_tags?: string[];

  // 储值
  stored_value?: StoredValueInfo;

  // 积分
  points?: PointsInfo;

  // 会员卡
  member_card?: MemberCardInfo;

  // 可用券
  available_coupons?: AvailableCoupon[];
  available_coupon_count?: number;

  // 发券记录
  recent_coupon_sends?: CouponSendRecord[];

  // AI话术建议
  greeting_hint?: string;

  // 常去门店
  frequent_store?: { store_id: string; store_name: string; visit_count: number };
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
