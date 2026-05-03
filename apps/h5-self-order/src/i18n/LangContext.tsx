import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import { zh } from './zh';
import { en } from './en';
import { ja } from './ja';
import { ko } from './ko';
import { id } from './id';
import { vi } from './vi';

export type Lang = 'zh' | 'en' | 'ja' | 'ko' | 'id' | 'vi';
type Translations = typeof zh;

const dictMap = { zh, en, ja, ko, id, vi } as Record<Lang, Record<keyof Translations, string>>;

interface LangContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: keyof Translations) => string;
}

const LangContext = createContext<LangContextValue | null>(null);

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>('zh');

  const t = useCallback(
    (key: keyof Translations) => dictMap[lang][key] ?? key,
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
