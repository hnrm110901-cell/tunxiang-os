import { useLang, type Lang } from '@/i18n/LangContext';
import styles from './LangSwitcher.module.css';

const LANGS: { code: Lang; label: string; flag: string }[] = [
  { code: 'zh', label: '中文', flag: '🇨🇳' },
  { code: 'en', label: 'EN', flag: '🇬🇧' },
  { code: 'ja', label: '日本語', flag: '🇯🇵' },
  { code: 'ko', label: '한국어', flag: '🇰🇷' },
];

export default function LangSwitcher() {
  const { lang, setLang } = useLang();

  return (
    <div className={styles.switcher}>
      {LANGS.map((l) => (
        <button
          key={l.code}
          className={`${styles.btn} ${lang === l.code ? styles.active : ''} tx-pressable`}
          onClick={() => setLang(l.code)}
          aria-label={l.label}
        >
          <span className={styles.flag}>{l.flag}</span>
          <span className={styles.label}>{l.label}</span>
        </button>
      ))}
    </div>
  );
}
