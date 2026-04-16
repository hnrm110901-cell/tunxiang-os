/**
 * MenuSearch — 菜品搜索输入框
 *
 * 支持语音搜索（webkitSpeechRecognition, zh-CN）
 * 防抖由父组件负责
 */
import { useRef, useCallback } from 'react';
import { cn } from '../../utils/cn';
import styles from './MenuSearch.module.css';

export interface MenuSearchProps {
  placeholder?: string;
  enableVoice?: boolean;
  value: string;
  onChange: (value: string) => void;
  onVoiceResult?: (text: string) => void;
  className?: string;
}

/* ─── SVG Icons ─── */

function SearchIcon() {
  return (
    <svg
      className={styles.searchIcon}
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}

function ClearIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="10" />
      <path d="m15 9-6 6" />
      <path d="m9 9 6 6" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" x2="12" y1="19" y2="22" />
    </svg>
  );
}

export default function MenuSearch({
  placeholder = '搜索菜品...',
  enableVoice = false,
  value,
  onChange,
  onVoiceResult,
  className,
}: MenuSearchProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleClear = useCallback(() => {
    onChange('');
    inputRef.current?.focus();
  }, [onChange]);

  const handleVoice = useCallback(() => {
    const SpeechRecognition =
      (window as any).SpeechRecognition ??
      (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    const recognition = new SpeechRecognition();
    recognition.lang = 'zh-CN';
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event: any) => {
      const transcript: string = event.results[0][0].transcript;
      onChange(transcript);
      onVoiceResult?.(transcript);
    };
    recognition.start();
  }, [onChange, onVoiceResult]);

  const hasVoiceApi =
    typeof window !== 'undefined' &&
    ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);

  return (
    <div className={cn(styles.wrapper, className)}>
      <SearchIcon />
      <input
        ref={inputRef}
        className={styles.input}
        type="text"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        enterKeyHint="search"
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
      />
      {value && (
        <button
          className={styles.clearBtn}
          onClick={handleClear}
          aria-label="清除搜索"
          type="button"
        >
          <ClearIcon />
        </button>
      )}
      {enableVoice && hasVoiceApi && (
        <button
          className={styles.voiceBtn}
          onClick={handleVoice}
          aria-label="语音搜索"
          type="button"
        >
          <MicIcon />
        </button>
      )}
    </div>
  );
}
