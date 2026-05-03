/**
 * Admin 语言切换 Provider
 */
import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import { zh } from './zh';
import { en } from './en';
import { ms } from './ms';
import { vi } from './vi';
import { id } from './id';
import type { TranslationKeys } from './types';

export type Lang = 'zh' | 'en' | 'ms' | 'vi' | 'id';

type Translations = typeof zh;

const dictMap: Record<Lang, Record<string, string>> = {
  zh: _flatten(zh),
  en: _flatten(en),
  ms: _flatten(ms),
  vi: _flatten(vi),
  id: _flatten(id),
};

function _flatten(obj: Translations, prefix = ''): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'string') {
      result[fullKey] = value;
    } else if (typeof value === 'object' && value !== null) {
      Object.assign(result, _flatten(value as Translations, fullKey));
    }
  }
  return result;
}

interface LangContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}

const LangContext = createContext<LangContextValue | null>(null);

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>('zh');

  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => {
      const template = dictMap[lang][key] ?? dictMap['zh'][key] ?? key;
      if (!params) return template;
      return template.replace(/\{(\w+)\}/g, (_, k) =>
        params[k] !== undefined ? String(params[k]) : `{${k}}`,
      );
    },
    [lang],
  );

  return (
    <LangContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LangContext.Provider>
  );
}

export function useLang(): LangContextValue {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error('useLang must be used within LangProvider');
  return ctx;
}
