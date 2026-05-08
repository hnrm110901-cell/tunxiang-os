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
      // 即使光标在输入框中也允许触发（业界惯例：AI 唤起优先级高）
      if ((e.metaKey || e.ctrlKey) && (e.key === 'j' || e.key === 'J')) {
        e.preventDefault();
        openChat();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [openChat]);
}
