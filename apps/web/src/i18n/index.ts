/**
 * i18n 基础设施（自实现轻量 hook，不引入 i18next 额外依赖）
 *
 * 用法：
 *   import { t, useI18n } from '@/i18n';
 *   const { t, locale, setLocale } = useI18n();
 *   <span>{t('common.save')}</span>
 *
 * 启动时在 main.tsx 调用 bootstrapI18n() 从后端拉翻译。
 */

import { useCallback, useSyncExternalStore } from 'react';
import { apiClient } from '../services/api';

export type Locale = 'zh-CN' | 'zh-TW' | 'en-US' | 'vi-VN' | 'th-TH' | 'id-ID';

export const SUPPORTED_LOCALES: Locale[] = [
  'zh-CN', 'zh-TW', 'en-US', 'vi-VN', 'th-TH', 'id-ID',
];

export const DEFAULT_LOCALE: Locale = 'zh-CN';
const STORAGE_KEY = 'tuxiang.locale';
const STORAGE_BUNDLE = 'tuxiang.i18n_bundle';

type Bundle = Record<string, Record<string, string>>; // namespace -> key -> value

let currentLocale: Locale = (localStorage.getItem(STORAGE_KEY) as Locale) || DEFAULT_LOCALE;
let currentBundle: Bundle = {};

// 内存加载 localStorage 缓存
try {
  const cached = localStorage.getItem(STORAGE_BUNDLE);
  if (cached) currentBundle = JSON.parse(cached);
} catch {
  // ignore
}

// 订阅发布机制
const listeners = new Set<() => void>();
const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => listeners.delete(cb);
};
const notify = () => listeners.forEach((cb) => cb());
const getSnapshot = () => currentLocale + '|' + Object.keys(currentBundle).length;

function applyVars(template: string, vars?: Record<string, unknown>): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_, k) =>
    vars[k] !== undefined ? String(vars[k]) : `{${k}}`,
  );
}

/**
 * 翻译函数。key 形如 "common.save"。fallback 顺序：
 * 1) 当前 locale 翻译
 * 2) key 本身（不抛错）
 */
export function t(key: string, vars?: Record<string, unknown>): string {
  const [ns, ...rest] = key.split('.');
  const k = rest.join('.');
  const ns_bundle = currentBundle[ns];
  const value = ns_bundle ? ns_bundle[k] : undefined;
  return applyVars(value || key, vars);
}

export async function bootstrapI18n(locale?: Locale): Promise<void> {
  const loc = locale || currentLocale;
  try {
    const resp = await apiClient.get(`/api/v1/i18n/translations?locale=${loc}`);
    currentBundle = (resp.data || {}) as Bundle;
    currentLocale = loc;
    localStorage.setItem(STORAGE_KEY, loc);
    localStorage.setItem(STORAGE_BUNDLE, JSON.stringify(currentBundle));
    notify();
  } catch (e) {
    // 降级：使用 localStorage 已缓存的 bundle（不阻塞渲染）
    // eslint-disable-next-line no-console
    console.warn('i18n 加载失败，使用缓存或 fallback', e);
  }
}

export function getLocale(): Locale {
  return currentLocale;
}

export async function setLocale(loc: Locale): Promise<void> {
  if (loc === currentLocale) return;
  await bootstrapI18n(loc);
}

/** React Hook */
export function useI18n() {
  useSyncExternalStore(subscribe, getSnapshot);
  const translate = useCallback((key: string, vars?: Record<string, unknown>) => t(key, vars), []);
  return {
    t: translate,
    locale: currentLocale,
    setLocale,
    supportedLocales: SUPPORTED_LOCALES,
  };
}
