export type MenuDomain = 'CORE' | 'ECOSYSTEM' | 'BUSINESS' | 'GUARDRAIL' | 'AI_OPS'

export interface MenuItem {
  id: string
  path: string
  icon: string
  label: string
  domain: MenuDomain
  badge?: { text: string; tone: 'danger' | 'warn' | 'info' }
  subItems: SubMenuItem[]
}

export interface SubMenuItem {
  label: string
  path: string
}
