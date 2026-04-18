/**
 * 语言切换器 — 顶栏下拉
 */
import { useEffect, useState } from 'react';
import { Select } from 'antd';
import { useI18n, type Locale } from '../i18n';
import { apiClient } from '../services/api';

interface LocaleOption {
  code: Locale;
  name: string;
  flag_emoji?: string;
}

const FALLBACK: LocaleOption[] = [
  { code: 'zh-CN', name: '简体中文', flag_emoji: '🇨🇳' },
  { code: 'zh-TW', name: '繁體中文', flag_emoji: '🇭🇰' },
  { code: 'en-US', name: 'English', flag_emoji: '🇺🇸' },
  { code: 'vi-VN', name: 'Tiếng Việt', flag_emoji: '🇻🇳' },
  { code: 'th-TH', name: 'ภาษาไทย', flag_emoji: '🇹🇭' },
  { code: 'id-ID', name: 'Bahasa Indonesia', flag_emoji: '🇮🇩' },
];

export default function LanguageSwitcher() {
  const { locale, setLocale } = useI18n();
  const [options, setOptions] = useState<LocaleOption[]>(FALLBACK);

  useEffect(() => {
    apiClient
      .get('/api/v1/i18n/locales')
      .then((r) => {
        if (Array.isArray(r.data) && r.data.length > 0) setOptions(r.data as LocaleOption[]);
      })
      .catch(() => {
        /* 使用 fallback */
      });
  }, []);

  return (
    <Select
      size="small"
      style={{ width: 150 }}
      value={locale}
      onChange={(v) => setLocale(v as Locale)}
      options={options.map((o) => ({
        value: o.code,
        label: `${o.flag_emoji || ''} ${o.name}`,
      }))}
    />
  );
}
