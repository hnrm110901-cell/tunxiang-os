import { useState, useCallback, useEffect } from 'react';

export type ThemeMode = 'light' | 'dark' | 'kds';

/**
 * 主题切换 Hook
 */
export function useTheme(defaultMode: ThemeMode = 'dark') {
  const [mode, setMode] = useState<ThemeMode>(() => {
    if (typeof window === 'undefined') return defaultMode;
    return (document.documentElement.getAttribute('data-theme') as ThemeMode) || defaultMode;
  });

  const setTheme = useCallback((newMode: ThemeMode) => {
    document.documentElement.setAttribute('data-theme', newMode);
    setMode(newMode);
  }, []);

  useEffect(() => {
    const observer = new MutationObserver(() => {
      const current = document.documentElement.getAttribute('data-theme') as ThemeMode;
      if (current && current !== mode) setMode(current);
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, [mode]);

  return { mode, setTheme } as const;
}
