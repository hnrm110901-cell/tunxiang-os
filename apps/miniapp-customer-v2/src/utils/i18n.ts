/**
 * i18n — 多语言支持（中/英/日）
 *
 * 用法:
 *   import { t, setLocale, getLocale } from '@/utils/i18n'
 *   <Text>{t('home.welcome')}</Text>
 *
 * 支持:
 *   - zh-CN (默认)
 *   - en-US
 *   - ja-JP
 */
import Taro from '@tarojs/taro'

export type Locale = 'zh-CN' | 'en-US' | 'ja-JP'

// ─── 语言包 ──────────────────────────────────────────────────────────────────

const messages: Record<Locale, Record<string, string>> = {
  'zh-CN': {
    // 通用
    'common.confirm': '确认',
    'common.cancel': '取消',
    'common.save': '保存',
    'common.loading': '加载中...',
    'common.empty': '暂无数据',
    'common.error': '出错了',
    'common.retry': '重试',
    // TabBar
    'tab.home': '首页',
    'tab.menu': '菜单',
    'tab.order': '订单',
    'tab.mine': '我的',
    // 首页
    'home.welcome': '欢迎光临',
    'home.hot_dishes': '热销菜品',
    'home.ai_recommend': 'AI为你推荐',
    'home.activities': '今日活动',
    'home.reorder': '再来一单',
    // 菜单
    'menu.search': '搜索菜品',
    'menu.all': '全部',
    'menu.sold_out': '已售罄',
    'menu.add_to_cart': '加入购物车',
    'menu.specs': '选择规格',
    // 购物车
    'cart.title': '购物车',
    'cart.empty': '购物车是空的',
    'cart.checkout': '去结算',
    'cart.total': '合计',
    // 订单
    'order.all': '全部',
    'order.pending': '待付款',
    'order.processing': '进行中',
    'order.completed': '已完成',
    'order.empty': '暂无订单',
    // 会员
    'member.level': '会员等级',
    'member.points': '积分',
    'member.stored_value': '储值余额',
    'member.subscription': '开通会员',
    'member.taste_profile': '口味档案',
    'member.cross_brand': '跨品牌权益',
    'member.insights': '消费报告',
    // 排队
    'queue.take_number': '取号排队',
    'queue.position': '前方等待',
    'queue.tables': '桌',
    'queue.estimated_wait': '预计等待',
    'queue.minutes': '分钟',
    // 预点餐
    'preorder.title': '预点餐',
    'preorder.select_store': '选择取餐门店',
    'preorder.select_time': '选择取餐时间',
    'preorder.confirm': '确认预点餐信息',
    'preorder.start_order': '开始点餐',
    // AI
    'ai.assistant': 'AI 点餐助手',
    'ai.thinking': 'AI 正在思考...',
    'ai.add': '+ 加入',
    'ai.allergen_warning': '过敏原预警',
  },
  'en-US': {
    'common.confirm': 'Confirm',
    'common.cancel': 'Cancel',
    'common.save': 'Save',
    'common.loading': 'Loading...',
    'common.empty': 'No data',
    'common.error': 'Error',
    'common.retry': 'Retry',
    'tab.home': 'Home',
    'tab.menu': 'Menu',
    'tab.order': 'Orders',
    'tab.mine': 'Me',
    'home.welcome': 'Welcome',
    'home.hot_dishes': 'Popular Dishes',
    'home.ai_recommend': 'AI Picks for You',
    'home.activities': "Today's Specials",
    'home.reorder': 'Reorder',
    'menu.search': 'Search dishes',
    'menu.all': 'All',
    'menu.sold_out': 'Sold Out',
    'menu.add_to_cart': 'Add to Cart',
    'menu.specs': 'Choose Specs',
    'cart.title': 'Cart',
    'cart.empty': 'Your cart is empty',
    'cart.checkout': 'Checkout',
    'cart.total': 'Total',
    'order.all': 'All',
    'order.pending': 'Unpaid',
    'order.processing': 'In Progress',
    'order.completed': 'Completed',
    'order.empty': 'No orders yet',
    'member.level': 'Level',
    'member.points': 'Points',
    'member.stored_value': 'Balance',
    'member.subscription': 'Subscribe',
    'member.taste_profile': 'Taste Profile',
    'member.cross_brand': 'Cross-Brand',
    'member.insights': 'My Report',
    'queue.take_number': 'Join Queue',
    'queue.position': 'Ahead of you',
    'queue.tables': 'tables',
    'queue.estimated_wait': 'Est. wait',
    'queue.minutes': 'min',
    'preorder.title': 'Pre-Order',
    'preorder.select_store': 'Select Pickup Store',
    'preorder.select_time': 'Select Pickup Time',
    'preorder.confirm': 'Confirm Details',
    'preorder.start_order': 'Start Ordering',
    'ai.assistant': 'AI Assistant',
    'ai.thinking': 'AI is thinking...',
    'ai.add': '+ Add',
    'ai.allergen_warning': 'Allergen Alert',
  },
  'ja-JP': {
    'common.confirm': '確認',
    'common.cancel': 'キャンセル',
    'common.save': '保存',
    'common.loading': '読み込み中...',
    'common.empty': 'データなし',
    'common.error': 'エラー',
    'common.retry': '再試行',
    'tab.home': 'ホーム',
    'tab.menu': 'メニュー',
    'tab.order': '注文',
    'tab.mine': 'マイページ',
    'home.welcome': 'いらっしゃいませ',
    'home.hot_dishes': '人気メニュー',
    'home.ai_recommend': 'AIおすすめ',
    'home.activities': '本日のキャンペーン',
    'home.reorder': 'もう一度注文',
    'menu.search': '料理を検索',
    'menu.all': 'すべて',
    'menu.sold_out': '品切れ',
    'menu.add_to_cart': 'カートに追加',
    'menu.specs': '仕様を選択',
    'cart.title': 'カート',
    'cart.empty': 'カートは空です',
    'cart.checkout': 'お会計',
    'cart.total': '合計',
    'order.all': 'すべて',
    'order.pending': '未払い',
    'order.processing': '処理中',
    'order.completed': '完了',
    'order.empty': '注文履歴なし',
    'member.level': '会員ランク',
    'member.points': 'ポイント',
    'member.stored_value': '残高',
    'member.subscription': '会員登録',
    'member.taste_profile': '味の好み',
    'member.cross_brand': 'ブランド横断',
    'member.insights': '利用レポート',
    'queue.take_number': '整理券を取る',
    'queue.position': '前に',
    'queue.tables': 'テーブル',
    'queue.estimated_wait': '推定待ち時間',
    'queue.minutes': '分',
    'preorder.title': '事前注文',
    'preorder.select_store': '受取店舗を選択',
    'preorder.select_time': '受取時間を選択',
    'preorder.confirm': '内容確認',
    'preorder.start_order': '注文開始',
    'ai.assistant': 'AIアシスタント',
    'ai.thinking': 'AI考え中...',
    'ai.add': '+ 追加',
    'ai.allergen_warning': 'アレルゲン警告',
  },
}

// ─── State ────────────────────────────────────────────────────────────────────

let currentLocale: Locale = 'zh-CN'

export function getLocale(): Locale {
  return currentLocale
}

export function setLocale(locale: Locale): void {
  currentLocale = locale
  Taro.setStorageSync('tx_locale', locale)
}

export function initLocale(): void {
  const stored = Taro.getStorageSync<string>('tx_locale') as Locale | ''
  if (stored && stored in messages) {
    currentLocale = stored
  } else {
    // 自动检测系统语言
    const sys = Taro.getSystemInfoSync()
    const lang = sys.language || 'zh_CN'
    if (lang.startsWith('en')) currentLocale = 'en-US'
    else if (lang.startsWith('ja')) currentLocale = 'ja-JP'
    else currentLocale = 'zh-CN'
  }
}

// ─── Translation ──────────────────────────────────────────────────────────────

export function t(key: string, fallback?: string): string {
  return messages[currentLocale]?.[key] ?? messages['zh-CN']?.[key] ?? fallback ?? key
}

export const SUPPORTED_LOCALES: { locale: Locale; label: string; flag: string }[] = [
  { locale: 'zh-CN', label: '简体中文', flag: '🇨🇳' },
  { locale: 'en-US', label: 'English', flag: '🇺🇸' },
  { locale: 'ja-JP', label: '日本語', flag: '🇯🇵' },
]
