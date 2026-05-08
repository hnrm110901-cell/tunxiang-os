/**
 * useAgentConsoleHotkey — Cmd+J / Ctrl+J 唤起 AgentConsole.chat
 *
 * 在 web-admin 全局注册键盘监听：
 *   - macOS: Cmd+J
 *   - Win/Linux: Ctrl+J
 *
 * 与 AdminCommandPalette 的 Cmd+K 共存，分别清晰：
 *   Cmd+K → 命令面板（路由跳转 / 操作 / 系统）
 *   Cmd+J → AI 对话面板（自然语言问数 / NLQ）
 *
 * 业界对照：Linear / Notion 用 Cmd+J 唤起 AI；不抢占 Cmd+K 的命令面板肌肉记忆。
 *
 * Sprint 4 / S4-01 / Tier 2
 */
import { useEffect } from 'react';
import { useAgentConsoleStore } from '../store/agentConsoleStore';

export function useAgentConsoleHotkey() {
  const openChat = useAgentConsoleStore((s) => s.openChat);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Cmd+J（mac）或 Ctrl+J（其他平台）
      if (!((e.metaKey || e.ctrlKey) && (e.key === 'j' || e.key === 'J'))) {
        return;
      }
      // 输入框 / 表单 / 富文本 / chat input 内跳过：让 'j' 字符正常输入。
      // 在 AgentConsole.chat 已开的情况下用户多半在编辑追问，再 Cmd+J 静默拦截
      // 既不打开新会话，又拦了击键，给"按了什么都没发生"的体验。
      const target = e.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable) {
          return;
        }
      }
      e.preventDefault();
      openChat();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [openChat]);
}
