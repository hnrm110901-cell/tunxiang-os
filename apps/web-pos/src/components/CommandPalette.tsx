/**
 * CommandPalette — Cmd+K 命令面板组件
 *
 * 设计参考: web-hub CmdK.tsx (Linear/Vercel 风格)
 * 适配: web-pos 暗色主题 + POS 快捷键系统
 *
 * 特性:
 *   - 搜索过滤（标题/描述/快捷键/关键词）
 *   - 分组显示（POS操作/页面导航/系统功能）
 *   - ↑↓ 键盘导航 + Enter 执行
 *   - 快捷键徽标
 *   - 淡入/缩放动画
 */
import { useState, useEffect, useRef } from 'react';
import { useCommandPalette } from '../hooks/useCommandPalette';
import { A2UIRenderer, parseA2UIFromAgent } from './a2ui/A2UIRenderer';
import { txColors } from '@tx/tokens';

// ─── 颜色常量 ──────────────────────────────────────────────────────────────────

const C = {
  overlayBg: 'rgba(11, 26, 32, 0.96)',
  panelBg: '#10232D',
  panelBorder: 'rgba(255,255,255,0.1)',
  searchBg: 'rgba(255,255,255,0.06)',
  itemHover: '#182F3A',
  itemSelected: '#1E3A48',
  text: 'rgba(255,255,255,0.92)',
  text2: 'rgba(255,255,255,0.55)',
  text3: 'rgba(255,255,255,0.3)',
  accent: txColors.primary,
  shortcutBg: 'rgba(255,255,255,0.08)',
  separator: 'rgba(255,255,255,0.06)',
  shadow: '0 24px 64px rgba(0,0,0,0.55)',
};

// ─── 动画注入 ──────────────────────────────────────────────────────────────────

const keyframes = `
@keyframes tx-cmdk-fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes tx-cmdk-scaleIn { from { transform: translateY(-12px) scale(0.97); opacity: 0; } to { transform: translateY(0) scale(1); opacity: 1; } }
@keyframes tx-cmdk-spin { to { transform: rotate(360deg); } }
`;

// ─── 组件 ──────────────────────────────────────────────────────────────────────

export function CommandPalette() {
  const palette = useCommandPalette();
  const {
    open, setOpen, query, setQuery,
    selectedIndex, flatItems, groupedItems, enabled,
    agentMode, agentResult, agentLoading, agentError, askAgent,
    exitAgentMode, clearAgentResult,
  } = palette;
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const agentInputRef = useRef<HTMLInputElement>(null);
  const [followUp, setFollowUp] = useState('');

  // 打开时自动聚焦输入框
  useEffect(() => {
    if (open) {
      setTimeout(() => {
        if (agentMode) {
          agentInputRef.current?.focus();
        } else {
          inputRef.current?.focus();
        }
      }, 50);
    }
  }, [open, agentMode]);

  // 自动滚动到选中项
  useEffect(() => {
    if (!listRef.current) return;
    const item = listRef.current.querySelector(`[data-cmdk-index="${selectedIndex}"]`) as HTMLElement;
    if (item) {
      item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [selectedIndex]);

  if (!open || !enabled) return null;

  const showAgentEntry = !agentMode && query.trim().length >= 3 && flatItems.length === 0;

  // Agent 结果面板
  const renderAgentResult = () => (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
    }}>
      {/* 头部 — 返回按钮 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '10px 16px', borderBottom: `1px solid ${C.separator}`,
      }}>
        <button
          onClick={exitAgentMode}
          style={{
            background: C.searchBg, border: 'none', borderRadius: 6,
            color: C.text2, cursor: 'pointer', fontSize: 13,
            padding: '6px 12px', minHeight: 32,
            display: 'flex', alignItems: 'center', gap: 4,
          }}
        >
          ← 返回搜索
        </button>
        <span style={{ fontSize: 12, color: C.text3 }}>向运营指挥官提问</span>
      </div>

      {/* Agent 响应区 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {agentLoading ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, paddingTop: 40 }}>
            <div style={{
              width: 28, height: 28,
              border: '3px solid rgba(255,107,53,0.15)',
              borderTopColor: C.accent,
              borderRadius: '50%',
              animation: 'tx-cmdk-spin 0.6s linear infinite',
            }} />
            <div style={{ color: C.text2, fontSize: 14 }}>正在分析业务数据...</div>
          </div>
        ) : agentError ? (
          <div style={{
            padding: 16, borderRadius: 8,
            background: 'rgba(235,87,87,0.08)',
            border: '1px solid rgba(235,87,87,0.2)',
            color: '#EB5757', fontSize: 14,
          }}>
            <div style={{ fontWeight: 700, marginBottom: 6 }}>❌ 查询失败</div>
            <div>{agentError}</div>
            <button
              onClick={() => askAgent(query)}
              style={{
                marginTop: 12, padding: '8px 16px', minHeight: 36,
                background: C.accent, color: '#fff', border: 'none',
                borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 600,
              }}
            >
              重试
            </button>
          </div>
        ) : (
          <>
            {/* 用户问题 */}
            <div style={{
              padding: '10px 14px', borderRadius: 8, marginBottom: 12,
              background: 'rgba(255,107,53,0.08)',
              border: '1px solid rgba(255,107,53,0.15)',
              color: C.accent, fontSize: 13, fontWeight: 600,
            }}>
              💬 {query}
            </div>
            {/* Agent 回复 — 尝试 A2UI 渲染，回退为纯文本 */}
            {(() => {
              if (!agentResult) return null;
              try {
                const data = JSON.parse(agentResult);
                const a2ui = parseA2UIFromAgent(data);
                if (a2ui) {
                  return <A2UIRenderer declaration={a2ui} />;
                }
              } catch { /* 非 JSON 文本，回退到纯文本 */ }
              return (
                <div style={{
                  padding: '14px 16px', borderRadius: 8,
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid rgba(255,255,255,0.06)',
                  color: C.text, fontSize: 14, lineHeight: 1.7,
                  whiteSpace: 'pre-wrap',
                }}>
                  {agentResult}
                </div>
              );
            })()}
          </>
        )}
      </div>

      {/* 后续提问输入 */}
      {!agentLoading && (agentResult || agentError) && (
        <div style={{
          display: 'flex', gap: 8, padding: '12px 16px',
          borderTop: `1px solid ${C.separator}`,
        }}>
          <input
            ref={agentInputRef}
            value={followUp}
            onChange={(e) => setFollowUp(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && followUp.trim()) {
                const q = followUp.trim();
                setFollowUp('');
                askAgent(q);
              }
            }}
            placeholder="追问..."
            style={{
              flex: 1, height: 40, padding: '0 12px',
              background: C.searchBg, border: 'none', borderRadius: 8,
              color: C.text, fontSize: 13, outline: 'none',
            }}
          />
          <button
            onClick={() => {
              if (followUp.trim()) {
                const q = followUp.trim();
                setFollowUp('');
                askAgent(q);
              }
            }}
            disabled={!followUp.trim()}
            style={{
              padding: '8px 16px', minHeight: 40,
              background: !followUp.trim() ? C.searchBg : C.accent,
              color: !followUp.trim() ? C.text3 : '#fff',
              border: 'none', borderRadius: 8,
              cursor: !followUp.trim() ? 'default' : 'pointer',
              fontSize: 13, fontWeight: 600,
            }}
          >
            发送
          </button>
        </div>
      )}
    </div>
  );

  return (
    <>
      <style>{keyframes}</style>
      <div
        onClick={() => setOpen(false)}
        style={{
          position: 'fixed', inset: 0, zIndex: 9000,
          background: C.overlayBg,
          display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
          paddingTop: 100,
          animation: 'tx-cmdk-fadeIn 150ms ease-out',
        }}
      >
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            width: 580, maxHeight: 520,
            background: C.panelBg,
            border: `1px solid ${C.panelBorder}`,
            borderRadius: 14,
            overflow: 'hidden',
            display: 'flex', flexDirection: 'column',
            boxShadow: C.shadow,
            animation: agentMode ? undefined : 'tx-cmdk-scaleIn 150ms ease-out',
          }}
        >
          {agentMode ? renderAgentResult() : (
            <>
              {/* 搜索框 */}
              <div style={{
                display: 'flex', alignItems: 'center',
                padding: '0 18px', borderBottom: `1px solid ${C.separator}`,
              }}>
                <span style={{ fontSize: 16, color: C.text3, marginRight: 10 }}>⌘</span>
                <input
                  ref={inputRef}
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    clearAgentResult();
                  }}
                  placeholder="搜索 POS 命令，或输入问题向 Agent 提问..."
                  style={{
                    flex: 1, height: 52,
                    background: 'transparent', border: 'none', outline: 'none',
                    color: C.text, fontSize: 16,
                  }}
                />
                {query && (
                  <button
                    onClick={() => setQuery('')}
                    style={{
                      background: C.searchBg, border: 'none', borderRadius: 4,
                      color: C.text2, fontSize: 12, cursor: 'pointer',
                      padding: '4px 8px', minHeight: 28,
                    }}
                  >
                    Esc
                  </button>
                )}
              </div>

              {/* 命令列表 */}
              <div ref={listRef} style={{ flex: 1, overflowY: 'auto', padding: '8px 12px' }}>
                {flatItems.length === 0 && !showAgentEntry ? (
                  <div style={{
                    textAlign: 'center', padding: 40, color: C.text3, fontSize: 14,
                  }}>
                    没有匹配的命令
                  </div>
                ) : (
                  <>
                    {groupedItems.map((group) => (
                      <div key={group.group} style={{ marginBottom: 4 }}>
                        <div style={{
                          fontSize: 11, fontWeight: 700, color: C.text3,
                          padding: '8px 8px 4px', textTransform: 'uppercase',
                          letterSpacing: 0.5,
                        }}>
                          {group.label}
                        </div>
                        {group.items.map((cmd) => {
                          const idx = flatItems.indexOf(cmd);
                          const isSelected = idx === selectedIndex;
                          return (
                            <div
                              key={cmd.id}
                              data-cmdk-index={idx}
                              onClick={() => {
                                setTimeout(() => cmd.action(), 50);
                                setOpen(false);
                              }}
                              onMouseEnter={() => palette.setSelectedIndex(idx)}
                              style={{
                                display: 'flex', alignItems: 'center', gap: 10,
                                padding: '10px 12px', borderRadius: 8,
                                cursor: 'pointer',
                                background: isSelected ? C.itemSelected : 'transparent',
                                transition: 'background 80ms',
                              }}
                            >
                              <span style={{ fontSize: 18, flexShrink: 0 }}>{cmd.icon}</span>
                              <div style={{ flex: 1 }}>
                                <div style={{ fontSize: 14, fontWeight: 600, color: C.text }}>
                                  {cmd.title}
                                </div>
                                {cmd.description && (
                                  <div style={{ fontSize: 12, color: C.text2, marginTop: 1 }}>
                                    {cmd.description}
                                  </div>
                                )}
                              </div>
                              {cmd.shortcut && (
                                <span style={{
                                  padding: '3px 8px', borderRadius: 4,
                                  background: isSelected ? 'rgba(255,255,255,0.12)' : C.shortcutBg,
                                  color: isSelected ? C.accent : C.text2,
                                  fontSize: 11, fontWeight: 600,
                                  fontFamily: 'monospace', flexShrink: 0,
                                }}>
                                  {cmd.shortcut}
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    ))}

                    {/* Agent 入口 */}
                    {showAgentEntry && (
                      <div style={{ marginTop: 8, borderTop: `1px solid ${C.separator}`, paddingTop: 8 }}>
                        <div style={{
                          fontSize: 11, fontWeight: 700, color: C.text3,
                          padding: '8px 8px 4px', textTransform: 'uppercase',
                          letterSpacing: 0.5,
                        }}>
                          智能助理
                        </div>
                        <div
                          onClick={() => askAgent(query.trim())}
                          style={{
                            display: 'flex', alignItems: 'center', gap: 10,
                            padding: '12px', borderRadius: 8,
                            cursor: 'pointer',
                            background: 'rgba(255,107,53,0.08)',
                            border: '1px solid rgba(255,107,53,0.15)',
                            transition: 'background 80ms',
                          }}
                        >
                          <span style={{ fontSize: 18, flexShrink: 0 }}>🤖</span>
                          <div>
                            <div style={{ fontSize: 14, fontWeight: 600, color: C.accent }}>
                              向运营指挥官提问
                            </div>
                            <div style={{ fontSize: 12, color: C.text2, marginTop: 1 }}>
                              "{query.trim()}" — Agent 分析结果
                            </div>
                          </div>
                          <span style={{
                            marginLeft: 'auto', fontSize: 11, color: C.text3,
                          }}>
                            ↵ 发送
                          </span>
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>

              {/* 底部操作提示 */}
              <div style={{
                display: 'flex', gap: 16, padding: '10px 18px',
                borderTop: `1px solid ${C.separator}`,
              }}>
                {[
                  { keys: '↑↓', desc: '导航' },
                  { keys: '↵', desc: '执行' },
                  { keys: 'Esc', desc: '关闭' },
                ].map((hint) => (
                  <div key={hint.keys} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{
                      padding: '2px 6px', borderRadius: 3,
                      background: C.shortcutBg, color: C.text2,
                      fontSize: 10, fontFamily: 'monospace', fontWeight: 600,
                    }}>
                      {hint.keys}
                    </span>
                    <span style={{ fontSize: 11, color: C.text3 }}>{hint.desc}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
