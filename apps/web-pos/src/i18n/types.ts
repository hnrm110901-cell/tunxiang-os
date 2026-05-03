/**
 * POS 国际化翻译 Key 类型定义
 *
 * 按模块分组：checkout（收银）、menu（菜品）、order（订单）、delivery（外卖）、common（通用）
 */
export type TranslationKeys = typeof import('./zh').zh;
