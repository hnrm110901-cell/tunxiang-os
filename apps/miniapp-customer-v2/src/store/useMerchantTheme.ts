/**
 * useMerchantTheme — 商户主题配置全局状态
 *
 * 在 app.tsx 中加载，通过 CSS 变量注入品牌色。
 */
import { create } from 'zustand'
import Taro from '@tarojs/taro'

// ─── Types ──────────────────────────────────────────────────────────────────

export interface DishCardStyleConfig {
  variant: 'default' | 'elegant' | 'compact' | 'large-image'
  show_tag: boolean
  show_description: boolean
  price_color: string
  background_color: string
  border_radius: string
}

export interface BannerSlide {
  id: string
  image_url?: string
  title: string
  subtitle?: string
  link?: string
  background_color: string
}

export interface FeatureToggles {
  ai_recommend: boolean
  reorder_banner: boolean
  quick_entries: boolean
  today_activities: boolean
  hot_dishes: boolean
  ai_chat_assistant: boolean
}

export interface MerchantTheme {
  merchant_code: string
  merchant_name: string
  brand_color: string
  brand_color_dark: string
  logo_url?: string
  banner_slides: BannerSlide[]
  nav_bar_color: string
  nav_bar_text_color: string
  page_background: string
  card_background: string
  text_primary: string
  text_secondary: string
  dish_card: DishCardStyleConfig
  features: FeatureToggles
}

// ─── Default theme ──────────────────────────────────────────────────────────

export const DEFAULT_THEME: MerchantTheme = {
  merchant_code: 'default',
  merchant_name: '屯象OS',
  brand_color: '#FF6B35',
  brand_color_dark: '#E55A2B',
  banner_slides: [
    { id: '1', title: '春季新品上线', subtitle: '限时特惠，先到先得', background_color: '#1A3A4A' },
    { id: '2', title: '满100减20', subtitle: '本周五六日全天有效', background_color: '#1A2A3A' },
    { id: '3', title: '会员双倍积分', subtitle: '消费即可累积，随时兑换', background_color: '#2A1A3A' },
  ],
  nav_bar_color: '#0B1A20',
  nav_bar_text_color: '#E8F4F8',
  page_background: '#0B1A20',
  card_background: '#132029',
  text_primary: '#E8F4F8',
  text_secondary: '#9EB5C0',
  dish_card: {
    variant: 'default',
    show_tag: true,
    show_description: true,
    price_color: '#FF6B35',
    background_color: '#132029',
    border_radius: '16rpx',
  },
  features: {
    ai_recommend: true,
    reorder_banner: true,
    quick_entries: true,
    today_activities: true,
    hot_dishes: true,
    ai_chat_assistant: true,
  },
}

// ─── CSS variable injection ─────────────────────────────────────────────────

/** Inject theme into CSS variables on the page `<style>` */
export function injectThemeCSS(theme: MerchantTheme): void {
  const css = `
    page, .page-root {
      --tx-brand: ${theme.brand_color};
      --tx-brand-dark: ${theme.brand_color_dark};
      --tx-page-bg: ${theme.page_background};
      --tx-card-bg: ${theme.card_background};
      --tx-text-primary: ${theme.text_primary};
      --tx-text-secondary: ${theme.text_secondary};
      --tx-nav-bar: ${theme.nav_bar_color};
      --tx-nav-text: ${theme.nav_bar_text_color};
      --tx-dish-price: ${theme.dish_card.price_color};
      --tx-dish-card-bg: ${theme.dish_card.background_color};
      --tx-dish-card-radius: ${theme.dish_card.border_radius};
    }
  `

  // Remove any existing theme style element
  const existingId = 'tx-theme-vars'
  const existing = document.getElementById(existingId)
  if (existing) existing.remove()

  const style = document.createElement('style')
  style.id = existingId
  style.textContent = css
  document.head.appendChild(style)
}

// ─── Store ──────────────────────────────────────────────────────────────────

interface MerchantThemeState {
  theme: MerchantTheme
  loaded: boolean
  loading: boolean
}

interface MerchantThemeActions {
  setTheme: (theme: MerchantTheme) => void
  setLoading: (loading: boolean) => void
}

type MerchantThemeStore = MerchantThemeState & MerchantThemeActions

export const useMerchantTheme = create<MerchantThemeStore>()((set) => ({
  theme: DEFAULT_THEME,
  loaded: false,
  loading: false,

  setTheme(theme: MerchantTheme) {
    injectThemeCSS(theme)
    set({ theme, loaded: true, loading: false })
  },

  setLoading(loading: boolean) {
    set({ loading })
  },
}))
