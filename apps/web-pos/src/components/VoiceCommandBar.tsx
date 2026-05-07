/**
 * VoiceCommandBar — 语音指令悬浮条
 *
 * 固定在底部中央的麦克风按钮 + 识别文本显示。
 * 用于 POS 收银台 / KDS 出餐屏的语音交互入口。
 *
 * 使用 useVoiceAgent hook：
 *   - 点击麦克风开始/停止录音
 *   - 实时显示识别文本
 *   - 识别完成后回调 onCommand
 */
import { useState, useEffect, useRef } from 'react';
import { useVoiceAgent, type VoiceCommand } from '../hooks/useVoiceAgent';
import { txColors } from '@tx/tokens';

// ─── Props ──────────────────────────────────────────────────────────────────────

interface VoiceCommandBarProps {
  /** 识别到命令时的回调 */
  onCommand?: (command: VoiceCommand) => void;
  /** 当前上下文描述（如 "收银台"、"KDS出餐"） */
  context?: string;
  /** 播报命令（外部触发，如 KDS 叫号播报） */
  speakText?: string | null;
  /** 自定义位置，默认底部居中 */
  position?: 'bottom-center' | 'bottom-right' | 'top-right';
}

// ─── Design Tokens ──────────────────────────────────────────────────────────────

const C = {
  bg: '#112B36',
  border: '#1A3A48',
  accent: txColors.primary,
  success: '#10B981',
  danger: '#EF4444',
  text: '#E0E0E0',
  text2: 'rgba(255,255,255,0.55)',
};

// ─── Component ──────────────────────────────────────────────────────────────────

export function VoiceCommandBar({
  onCommand,
  context = '收银台',
  speakText,
  position = 'bottom-right',
}: VoiceCommandBarProps) {
  const [expanded, setExpanded] = useState(false);

  const voice = useVoiceAgent({
    lang: 'zh-CN',
    onCommand: (cmd) => {
      onCommand?.(cmd);
      // 收到命令后短暂展开显示结果
      setExpanded(true);
      setTimeout(() => setExpanded(false), 3000);
    },
    onSpeakEnd: () => {
      // 播报结束后自动收起（如果是从 speakText 触发的）
    },
  });

  // 外部触发播报（useEffect 避免 render-phase side effect）
  const prevSpeakRef = useRef<string | null | undefined>(null);
  useEffect(() => {
    if (speakText && speakText !== prevSpeakRef.current) {
      prevSpeakRef.current = speakText;
      voice.speak(speakText);
    }
    // voice.speak intentionally omitted: stable across renders, only speakText triggers
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speakText]);

  const positionStyles: Record<string, React.CSSProperties> = {
    'bottom-center': { bottom: 24, left: '50%', transform: 'translateX(-50%)' },
    'bottom-right': { bottom: 24, right: 24 },
    'top-right': { top: 16, right: 24 },
  };

  return (
    <div style={{
      position: 'fixed',
      zIndex: 8000,
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      ...positionStyles[position],
    }}>
      {/* 展开面板 — 识别文本 + 历史命令 */}
      {expanded && (
        <div style={{
          width: 300, marginBottom: 10,
          background: C.bg,
          border: `1px solid ${C.border}`,
          borderRadius: 12,
          padding: 12,
          boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
          maxHeight: 200, overflowY: 'auto',
        }}>
          {/* 当前识别 */}
          {voice.listening && voice.interimTranscript && (
            <div style={{
              padding: '8px 12px', borderRadius: 8,
              background: 'rgba(255,107,53,0.08)',
              border: `1px solid rgba(255,107,53,0.15)`,
              fontSize: 13, color: C.accent, fontWeight: 500,
              marginBottom: 8,
            }}>
              🎤 {voice.interimTranscript}
            </div>
          )}

          {/* 清空按钮 */}
          {voice.commands.length > 0 && (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span style={{ fontSize: 11, color: C.text2, fontWeight: 600 }}>语音记录</span>
              <button
                onClick={voice.clearCommands}
                style={{
                  background: 'transparent', border: 'none',
                  color: C.text2, fontSize: 11, cursor: 'pointer',
                }}
              >
                清空
              </button>
            </div>
          )}

          {voice.commands.map((cmd, i) => (
            <div key={cmd.timestamp} style={{
              display: 'flex', justifyContent: 'space-between',
              padding: '4px 0', borderBottom: i < voice.commands.length - 1 ? `1px solid ${C.border}` : 'none',
            }}>
              <span style={{ fontSize: 12, color: C.text, flex: 1 }}>{cmd.text}</span>
              <span style={{ fontSize: 10, color: C.text2, marginLeft: 8 }}>
                {Math.round(cmd.confidence * 100)}%
              </span>
            </div>
          ))}
        </div>
      )}

      {/* 主按钮 — 麦克风 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {/* 上下文标签 */}
        <span style={{
          fontSize: 11, color: C.text2,
          background: C.bg, borderRadius: 12,
          padding: '4px 10px', border: `1px solid ${C.border}`,
        }}>
          {context}
        </span>

        {/* 播报中指示 */}
        {voice.speaking && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 4,
            background: 'rgba(16,185,129,0.12)',
            borderRadius: 12, padding: '4px 10px',
            border: '1px solid rgba(16,185,129,0.2)',
          }}>
            <span style={{
              width: 6, height: 6, borderRadius: '50%',
              background: C.success,
              animation: 'vc-pulse 1s ease-in-out infinite',
            }} />
            <span style={{ fontSize: 11, color: C.success, fontWeight: 600 }}>播报中</span>
          </div>
        )}

        {/* 麦克风按钮 */}
        <button
          onClick={() => {
            if (voice.listening) {
              voice.stopListening();
            } else {
              voice.startListening();
              setExpanded(true);
            }
          }}
          disabled={!voice.recognitionSupported}
          title={voice.listening ? '停止录音' : voice.recognitionSupported ? '开始语音指令' : '浏览器不支持语音识别'}
          style={{
            width: 52, height: 52, borderRadius: '50%',
            background: voice.listening ? C.danger :
              voice.speaking ? C.success : C.accent,
            border: 'none',
            cursor: voice.recognitionSupported ? 'pointer' : 'not-allowed',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: voice.listening
              ? `0 0 0 6px rgba(239,68,68,0.2), 0 4px 16px rgba(0,0,0,0.3)`
              : voice.speaking
                ? `0 0 0 6px rgba(16,185,129,0.2), 0 4px 16px rgba(0,0,0,0.3)`
                : '0 4px 16px rgba(0,0,0,0.3)',
            opacity: voice.recognitionSupported ? 1 : 0.4,
            transition: 'all 200ms ease',
          }}
        >
          <span style={{ fontSize: 22 }}>
            {voice.listening ? '⏹' : voice.speaking ? '🔊' : '🎤'}
          </span>
        </button>
      </div>

      {/* CSS animation */}
      <style>{`@keyframes vc-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }`}</style>
    </div>
  );
}

// ─── 语音指令映射 ────────────────────────────────────────────────────────────────

export interface VoiceCommandEntry {
  action: string;
  patterns: string[];       // 匹配模式（中文短句）
  context?: string;         // 限制在特定上下文中
  description: string;      // 人类可读的描述
}

export const POS_VOICE_COMMANDS: VoiceCommandEntry[] = [
  // 桌台操作
  { action: 'open_table', patterns: ['开台', '新开桌', '打开桌台'], context: '收银台', description: '开新桌台' },
  { action: 'view_tables', patterns: ['桌台总览', '查看桌台', '桌台地图', '鸟瞰'], context: '收银台', description: '查看桌台总览' },
  // 收银操作
  { action: 'quick_cash', patterns: ['快速收银', '快速结账', '现金结账'], context: '收银台', description: '快速现金收银' },
  { action: 'settle_wx', patterns: ['微信支付', '微信结账'], context: '收银台', description: '微信支付结账' },
  { action: 'settle_ali', patterns: ['支付宝', '支付宝结账'], context: '收银台', description: '支付宝结账' },
  { action: 'print_receipt', patterns: ['打印小票', '打小票', '打印'], context: '收银台', description: '打印小票' },
  // 导航
  { action: 'go_dashboard', patterns: ['打开仪表盘', '回首页', '主控台'], context: '*', description: '返回仪表盘' },
  { action: 'go_reservations', patterns: ['预订', '查看预订', '预订台账'], context: '*', description: '查看预订' },
  { action: 'go_queue', patterns: ['排队', '排队管理', '取号'], context: '*', description: '排队管理' },
  { action: 'go_shift', patterns: ['交接班', '换班', '开班'], context: '*', description: '交接班' },
  // KDS 操作
  { action: 'mark_ready', patterns: ['出餐', '好了', '完成出餐', '可以上菜'], context: 'KDS出餐', description: '标记出餐完成' },
  { action: 'call_number', patterns: ['叫号', '叫'], context: 'KDS出餐', description: '呼叫取餐号' },
  { action: 'next_order', patterns: ['下一个', '下一单'], context: 'KDS出餐', description: '查看下一单' },
  { action: 'skip_order', patterns: ['跳过', '过'], context: 'KDS出餐', description: '跳过当前单' },
  // 语音搜索 Agent
  { action: 'agent_query', patterns: ['搜索', '查询', '查找', '分析', '报告', '统计'], context: '*', description: '向 Agent 提问' },
  // 快捷键触发
  { action: 'open_command_palette', patterns: ['打开命令面板', '命令面板', '搜索命令'], context: '*', description: '打开 Cmd+K 命令面板' },
  { action: 'toggle_sidebar', patterns: ['打开侧边栏', '关闭侧边栏', '侧边栏', '运营指挥官'], context: '收银台', description: '打开/关闭侧边栏' },
];

/** KDS 专用保持向后兼容 */
export const KDS_VOICE_COMMANDS: Record<string, string> = Object.fromEntries(
  POS_VOICE_COMMANDS
    .filter((c) => !c.context || c.context === 'KDS出餐' || c.context === '*')
    .map((c) => [c.patterns[0], c.action]),
);

/** 上下文 + 模式 匹配语音指令 */
export function matchVoiceCommand(transcript: string, context?: string): string | null {
  const text = transcript.toLowerCase().trim();
  // 按 pattern 长度降序匹配（优先匹配更具体的短语）
  const sorted = [...POS_VOICE_COMMANDS].sort((a, b) => b.patterns[0].length - a.patterns[0].length);
  for (const cmd of sorted) {
    // 上下文过滤
    if (cmd.context && cmd.context !== '*' && context && cmd.context !== context) continue;
    for (const pattern of cmd.patterns) {
      if (text.includes(pattern.toLowerCase())) return cmd.action;
    }
  }
  return null;
}

/** 获取所有匹配的命令（用于展示可能的命令选项） */
export function matchAllVoiceCommands(transcript: string, context?: string): VoiceCommandEntry[] {
  const text = transcript.toLowerCase().trim();
  return POS_VOICE_COMMANDS.filter((cmd) => {
    if (cmd.context && cmd.context !== '*' && context && cmd.context !== context) return false;
    return cmd.patterns.some((p) => text.includes(p.toLowerCase()));
  });
}
