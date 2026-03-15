// ── 商户管理 — 共享类型 & 常量 ────────────────────────────────────────────────

export const CUISINE_LABELS: Record<string, string> = {
  chinese_formal: '中餐正餐', sichuan: '川菜', hunan: '湘菜',
  cantonese: '粤菜', guizhou: '黔菜', hotpot: '火锅',
  bbq: '烧烤', fast_food: '快餐', other: '其他',
};

export const INDUSTRY_LABELS: Record<string, string> = {
  chinese_formal: '中餐正餐', hotpot: '火锅', fast_food: '快餐',
  bbq: '烧烤', other: '其他',
};

export const ROLE_LABELS: Record<string, string> = {
  admin: '管理员', store_manager: '店长', assistant_manager: '店助',
  floor_manager: '楼面经理', customer_manager: '客户经理',
  team_leader: '领班', waiter: '服务员', head_chef: '厨师长',
  station_manager: '档口负责人', chef: '厨师',
  warehouse_manager: '库管', finance: '财务', procurement: '采购',
};

export const CUISINE_OPTIONS = Object.entries(CUISINE_LABELS).map(([v, l]) => ({ value: v, label: l }));

export const ROLE_OPTIONS = [
  'store_manager', 'floor_manager', 'head_chef', 'waiter',
  'chef', 'warehouse_manager', 'finance', 'procurement',
].map(v => ({ value: v, label: ROLE_LABELS[v] || v }));

export const CHANNEL_LABELS: Record<string, string> = {
  dine_in: '堂食',
  takeaway_meituan: '美团外卖',
  takeaway_ele: '饿了么外卖',
  takeaway_douyin: '抖音外卖',
  group_buy: '团购',
  private_domain: '私域',
  other: '其他',
};

export const CHANNEL_OPTIONS = Object.entries(CHANNEL_LABELS).map(([v, l]) => ({ value: v, label: l }));

// ── Types ────────────────────────────────────────────────────────────────────

export interface MerchantSummary {
  brand_id: string;
  brand_name: string;
  cuisine_type: string;
  status: string;
  avg_ticket_yuan: number | null;
  group_id: string;
  group_name: string;
  contact_person: string;
  contact_phone: string;
  store_count: number;
  user_count: number;
  created_at: string | null;
}

export interface StoreItem {
  id: string;
  name: string;
  code: string;
  city: string;
  district: string;
  status: string;
  address: string;
  seats: number | null;
  created_at: string | null;
}

export interface UserItem {
  id: string;
  username: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  store_id: string | null;
  created_at: string | null;
}

export interface MerchantDetail {
  brand_id: string;
  brand_name: string;
  cuisine_type: string;
  avg_ticket_yuan: number | null;
  target_food_cost_pct: number;
  target_labor_cost_pct: number;
  target_rent_cost_pct: number | null;
  target_waste_pct: number;
  logo_url: string | null;
  status: string;
  created_at: string | null;
  group: {
    group_id: string;
    group_name: string;
    legal_entity: string;
    unified_social_credit_code: string;
    industry_type: string;
    contact_person: string;
    contact_phone: string;
    address: string | null;
  };
  stores: StoreItem[];
  users: UserItem[];
}

export interface PlatformStats {
  total_merchants: number;
  active_merchants: number;
  inactive_merchants: number;
  total_stores: number;
  active_stores: number;
  total_users: number;
  active_users: number;
  total_groups: number;
}

export interface ConfigSummary {
  im: {
    configured: boolean;
    platform: string | null;
    last_sync_status: string | null;
    last_sync_at: string | null;
  };
  agents: {
    total: number;
    enabled: number;
  };
  channels: {
    count: number;
  };
  store_count: number;
  user_count: number;
}

export interface ChannelConfigItem {
  id: string;
  brand_id: string;
  channel: string;
  platform_commission_pct: number;
  delivery_cost_fen: number;
  packaging_cost_fen: number;
  is_active: boolean;
}
