/**
 * TrainingModeBanner — 训练模式顶部固定横幅
 *
 * - 橙色背景固定在视口顶部（z-index 9998，低于离线横幅）
 * - 闪烁动画持续提醒操作者当前处于训练模式
 * - 显示当前训练场景名称和已用时长
 * - 退出按钮（需管理员密码二次确认）
 *
 * 编码规范：TypeScript strict，纯 inline style，触控按钮 >= 48px，字体 >= 16px
 */
import { useState, useEffect, useRef, useCallback } from 'react';

// ─── 类型 ───────────────────────────────────────────────────────────────────

interface TrainingModeBannerProps {
  scenarioLabel: string | null;
  startedAt: Date | null;
  onExit: (password: string) => boolean;
}

// ─── 计时器 ─────────────────────────────────────────────────────────────────

function formatElapsed(startedAt: Date): string {
  const diff = Math.max(0, Math.floor((Date.now() - startedAt.getTime()) / 1000));
  const m = Math.floor(diff / 60);
  const s = diff % 60;
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

// ─── 组件 ───────────────────────────────────────────────────────────────────

export function TrainingModeBanner({ scenarioLabel, startedAt, onExit }: TrainingModeBannerProps) {
  const [elapsed, setElapsed] = useState('00:00');
  const [showExitDialog, setShowExitDialog] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // 每秒更新已用时长
  useEffect(() => {
    if (!startedAt) return;
    const tick = () => setElapsed(formatElapsed(startedAt));
    tick();
    timerRef.current = setInterval(tick, 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [startedAt]);

  // 弹出退出框时自动聚焦
  useEffect(() => {
    if (showExitDialog && inputRef.current) {
      inputRef.current.focus();
    }
  }, [showExitDialog]);

  const handleExit = useCallback(() => {
    if (!password.trim()) {
      setError('请输入管理员密码');
      return;
    }
    const ok = onExit(password);
    if (ok) {
      setShowExitDialog(false);
      setPassword('');
      setError('');
    } else {
      setError('密码错误');
      setPassword('');
    }
  }, [password, onExit]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleExit();
    }
  }, [handleExit]);

  // ─── 注入闪烁动画 keyframes ──────────────────────────────────────────────
  useEffect(() => {
    const STYLE_ID = 'tx-training-banner-keyframes';
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      @keyframes tx-training-pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.7; }
      }
    `;
    document.head.appendChild(style);
    return () => {
      const el = document.getElementById(STYLE_ID);
      if (el) el.remove();
    };
  }, []);

  // ─── 样式 ────────────────────────────────────────────────────────────────

  const bannerStyle: React.CSSProperties = {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 9998,
    backgroundColor: '#D97706',
    color: '#FFFFFF',
    padding: '10px 20px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '16px',
    fontSize: '16px',
    fontWeight: 700,
    boxShadow: '0 2px 12px rgba(217, 119, 6, 0.5)',
    animation: 'tx-training-pulse 2s ease-in-out infinite',
    fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
  };

  const dotStyle: React.CSSProperties = {
    width: 10,
    height: 10,
    borderRadius: '50%',
    backgroundColor: '#FFFFFF',
    flexShrink: 0,
  };

  const labelStyle: React.CSSProperties = {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    fontSize: '16px',
    minWidth: 0,
  };

  const timerStyle: React.CSSProperties = {
    backgroundColor: 'rgba(0,0,0,0.2)',
    borderRadius: '8px',
    padding: '4px 12px',
    fontSize: '16px',
    fontWeight: 700,
    fontVariantNumeric: 'tabular-nums',
    flexShrink: 0,
  };

  const exitBtnStyle: React.CSSProperties = {
    minWidth: 48,
    minHeight: 48,
    padding: '8px 20px',
    borderRadius: '8px',
    border: '2px solid rgba(255,255,255,0.6)',
    backgroundColor: 'rgba(255,255,255,0.15)',
    color: '#FFFFFF',
    fontSize: '16px',
    fontWeight: 700,
    cursor: 'pointer',
    flexShrink: 0,
    transition: 'transform 200ms ease, background-color 200ms ease',
  };

  // ─── 退出确认弹层 ───────────────────────────────────────────────────────

  const overlayStyle: React.CSSProperties = {
    position: 'fixed',
    inset: 0,
    zIndex: 10000,
    backgroundColor: 'rgba(0,0,0,0.6)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  };

  const dialogStyle: React.CSSProperties = {
    backgroundColor: '#1A2332',
    borderRadius: '16px',
    padding: '32px',
    width: '380px',
    maxWidth: '90vw',
    boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
    fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
  };

  const dialogTitleStyle: React.CSSProperties = {
    color: '#FFFFFF',
    fontSize: '20px',
    fontWeight: 700,
    margin: '0 0 8px 0',
  };

  const dialogDescStyle: React.CSSProperties = {
    color: 'rgba(255,255,255,0.6)',
    fontSize: '16px',
    margin: '0 0 24px 0',
    lineHeight: 1.5,
  };

  const inputStyle: React.CSSProperties = {
    width: '100%',
    height: '56px',
    borderRadius: '12px',
    border: error ? '2px solid #EB5757' : '2px solid rgba(255,255,255,0.15)',
    backgroundColor: 'rgba(255,255,255,0.08)',
    color: '#FFFFFF',
    fontSize: '20px',
    fontWeight: 600,
    textAlign: 'center',
    letterSpacing: '6px',
    outline: 'none',
    boxSizing: 'border-box',
    padding: '0 16px',
  };

  const errorStyle: React.CSSProperties = {
    color: '#EB5757',
    fontSize: '16px',
    marginTop: '8px',
    textAlign: 'center' as const,
  };

  const dialogBtnRow: React.CSSProperties = {
    display: 'flex',
    gap: '12px',
    marginTop: '24px',
  };

  const cancelBtnStyle: React.CSSProperties = {
    flex: 1,
    minHeight: 56,
    borderRadius: '12px',
    border: '1px solid rgba(255,255,255,0.15)',
    backgroundColor: 'transparent',
    color: 'rgba(255,255,255,0.7)',
    fontSize: '18px',
    fontWeight: 600,
    cursor: 'pointer',
  };

  const confirmBtnStyle: React.CSSProperties = {
    flex: 1,
    minHeight: 56,
    borderRadius: '12px',
    border: 'none',
    backgroundColor: '#EB5757',
    color: '#FFFFFF',
    fontSize: '18px',
    fontWeight: 700,
    cursor: 'pointer',
  };

  return (
    <>
      {/* ── 顶部橙色横幅 ── */}
      <div style={bannerStyle}>
        <div style={labelStyle}>
          <span style={dotStyle} />
          <span>
            训练模式{scenarioLabel ? ` - ${scenarioLabel}` : ''} -- 数据不会保存
          </span>
        </div>
        {startedAt && <span style={timerStyle}>{elapsed}</span>}
        <button
          type="button"
          style={exitBtnStyle}
          onPointerDown={(e) => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
          }}
          onPointerUp={(e) => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
          }}
          onPointerCancel={(e) => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
          }}
          onClick={() => {
            setShowExitDialog(true);
            setPassword('');
            setError('');
          }}
        >
          退出训练
        </button>
      </div>

      {/* ── 占位条（防止内容被横幅遮挡） ── */}
      <div style={{ height: 52 }} />

      {/* ── 退出确认弹层 ── */}
      {showExitDialog && (
        <div
          style={overlayStyle}
          onClick={(e) => {
            if (e.target === e.currentTarget) {
              setShowExitDialog(false);
            }
          }}
        >
          <div style={dialogStyle}>
            <h3 style={dialogTitleStyle}>退出训练模式</h3>
            <p style={dialogDescStyle}>
              退出后将恢复正常收银模式，训练期间的操作不会被保存。请输入管理员密码确认。
            </p>
            <input
              ref={inputRef}
              type="password"
              inputMode="numeric"
              maxLength={6}
              placeholder="管理员密码"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setError('');
              }}
              onKeyDown={handleKeyDown}
              style={inputStyle}
            />
            {error && <div style={errorStyle}>{error}</div>}
            <div style={dialogBtnRow}>
              <button
                type="button"
                style={cancelBtnStyle}
                onClick={() => setShowExitDialog(false)}
              >
                取消
              </button>
              <button
                type="button"
                style={confirmBtnStyle}
                onClick={handleExit}
              >
                确认退出
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
