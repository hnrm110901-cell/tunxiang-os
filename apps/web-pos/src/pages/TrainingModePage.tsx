/**
 * TrainingModePage — 训练模式入口设置页
 *
 * 功能：
 * - 管理员密码输入验证（默认 888888）
 * - 训练场景选择（新手收银/换班交接/退单处理/宴席开台）
 * - 场景详情预览（步骤、预计时长）
 * - 进入训练模式后跳转到 POS 主页
 *
 * 编码规范：TypeScript strict，纯 inline style
 * Store终端规则：触控 >= 48px，字体 >= 16px，禁止 hover-only 反馈
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useTrainingMode,
  TRAINING_SCENARIOS,
  type TrainingScenario,
  type TrainingScenarioInfo,
} from '../hooks/useTrainingMode';

// ─── 场景图标映射（纯文字符号，避免外部依赖） ────────────────────────────────

const SCENARIO_ICONS: Record<TrainingScenario, string> = {
  cashier_basics: '$$',
  shift_handover: '<<>>',
  refund_process: '(-)',
  banquet_open: '[][]',
};

const SCENARIO_COLORS: Record<TrainingScenario, string> = {
  cashier_basics: '#0AAF9A',
  shift_handover: '#2D9CDB',
  refund_process: '#EB5757',
  banquet_open: '#F2994A',
};

// ─── 组件 ───────────────────────────────────────────────────────────────────

export function TrainingModePage() {
  const navigate = useNavigate();
  const { enterTrainingMode, isTrainingMode, verifyPassword } = useTrainingMode();

  const [step, setStep] = useState<'password' | 'scenario' | 'preview'>('password');
  const [password, setPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [selectedScenario, setSelectedScenario] = useState<TrainingScenario | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // 已在训练模式 => 直接跳到 dashboard
  useEffect(() => {
    if (isTrainingMode) {
      navigate('/dashboard', { replace: true });
    }
  }, [isTrainingMode, navigate]);

  // 自动聚焦密码输入
  useEffect(() => {
    if (step === 'password' && inputRef.current) {
      inputRef.current.focus();
    }
  }, [step]);

  const handlePasswordSubmit = useCallback(() => {
    if (!password.trim()) {
      setPasswordError('请输入管理员密码');
      return;
    }
    if (!verifyPassword(password)) {
      setPasswordError('密码错误，请重试');
      setPassword('');
      return;
    }
    setPasswordError('');
    setStep('scenario');
  }, [password, verifyPassword]);

  const handleSelectScenario = useCallback((id: TrainingScenario) => {
    setSelectedScenario(id);
    setStep('preview');
  }, []);

  const handleStart = useCallback(() => {
    if (!selectedScenario) return;
    const ok = enterTrainingMode(password, selectedScenario);
    if (ok) {
      navigate('/dashboard', { replace: true });
    }
  }, [selectedScenario, password, enterTrainingMode, navigate]);

  const selectedInfo: TrainingScenarioInfo | null = selectedScenario
    ? TRAINING_SCENARIOS.find((s) => s.id === selectedScenario) ?? null
    : null;

  // ─── 通用样式 ────────────────────────────────────────────────────────────

  const pageStyle: React.CSSProperties = {
    minHeight: '100vh',
    background: 'linear-gradient(180deg, #0B1A20 0%, #111827 100%)',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '32px 24px',
    fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
  };

  const cardStyle: React.CSSProperties = {
    background: '#1A2332',
    borderRadius: '20px',
    padding: '40px 32px',
    width: '100%',
    maxWidth: '520px',
    boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
  };

  const titleStyle: React.CSSProperties = {
    color: '#FFFFFF',
    fontSize: '24px',
    fontWeight: 700,
    margin: '0 0 8px 0',
    textAlign: 'center',
  };

  const subtitleStyle: React.CSSProperties = {
    color: 'rgba(255,255,255,0.5)',
    fontSize: '16px',
    margin: '0 0 32px 0',
    textAlign: 'center',
    lineHeight: 1.5,
  };

  const primaryBtnStyle: React.CSSProperties = {
    width: '100%',
    minHeight: 56,
    borderRadius: '12px',
    border: 'none',
    backgroundColor: '#D97706',
    color: '#FFFFFF',
    fontSize: '18px',
    fontWeight: 700,
    cursor: 'pointer',
    transition: 'transform 200ms ease, background-color 200ms ease',
  };

  const secondaryBtnStyle: React.CSSProperties = {
    width: '100%',
    minHeight: 56,
    borderRadius: '12px',
    border: '1px solid rgba(255,255,255,0.15)',
    backgroundColor: 'transparent',
    color: 'rgba(255,255,255,0.7)',
    fontSize: '18px',
    fontWeight: 600,
    cursor: 'pointer',
    marginTop: '12px',
  };

  // 触控反馈辅助
  const onPointerDown = (e: React.PointerEvent) => {
    (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
  };
  const onPointerUp = (e: React.PointerEvent) => {
    (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
  };

  // ─── 步骤1：密码验证 ─────────────────────────────────────────────────────

  if (step === 'password') {
    return (
      <div style={pageStyle}>
        <div style={cardStyle}>
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <div style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 72,
              height: 72,
              borderRadius: '50%',
              backgroundColor: 'rgba(217, 119, 6, 0.15)',
              marginBottom: 16,
            }}>
              <span style={{ fontSize: 32, color: '#D97706', fontWeight: 700 }}>T</span>
            </div>
          </div>
          <h2 style={titleStyle}>进入训练模式</h2>
          <p style={subtitleStyle}>
            训练模式下的所有操作不会写入真实数据库。{'\n'}
            请输入管理员密码以继续。
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
              setPasswordError('');
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handlePasswordSubmit();
            }}
            style={{
              width: '100%',
              height: 56,
              borderRadius: 12,
              border: passwordError
                ? '2px solid #EB5757'
                : '2px solid rgba(255,255,255,0.15)',
              backgroundColor: 'rgba(255,255,255,0.08)',
              color: '#FFFFFF',
              fontSize: 24,
              fontWeight: 600,
              textAlign: 'center',
              letterSpacing: 8,
              outline: 'none',
              boxSizing: 'border-box',
              marginBottom: 8,
            }}
          />
          {passwordError && (
            <div style={{ color: '#EB5757', fontSize: 16, textAlign: 'center', marginBottom: 16 }}>
              {passwordError}
            </div>
          )}

          <div style={{ marginTop: 24 }}>
            <button
              type="button"
              style={primaryBtnStyle}
              onPointerDown={onPointerDown}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
              onClick={handlePasswordSubmit}
            >
              验证密码
            </button>
            <button
              type="button"
              style={secondaryBtnStyle}
              onClick={() => navigate(-1)}
            >
              返回
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ─── 步骤2：场景选择 ─────────────────────────────────────────────────────

  if (step === 'scenario') {
    return (
      <div style={pageStyle}>
        <div style={{ ...cardStyle, maxWidth: 600 }}>
          <h2 style={titleStyle}>选择训练场景</h2>
          <p style={subtitleStyle}>请选择一个训练场景开始练习</p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {TRAINING_SCENARIOS.map((s) => (
              <button
                key={s.id}
                type="button"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 16,
                  padding: '16px 20px',
                  borderRadius: 16,
                  border: '2px solid rgba(255,255,255,0.08)',
                  backgroundColor: 'rgba(255,255,255,0.04)',
                  color: '#FFFFFF',
                  cursor: 'pointer',
                  textAlign: 'left',
                  transition: 'transform 200ms ease, border-color 200ms ease',
                  minHeight: 80,
                }}
                onPointerDown={onPointerDown}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerUp}
                onClick={() => handleSelectScenario(s.id)}
              >
                {/* 图标区 */}
                <div style={{
                  width: 56,
                  height: 56,
                  borderRadius: 12,
                  backgroundColor: `${SCENARIO_COLORS[s.id]}20`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}>
                  <span style={{
                    fontSize: 20,
                    fontWeight: 700,
                    color: SCENARIO_COLORS[s.id],
                    fontFamily: 'monospace',
                  }}>
                    {SCENARIO_ICONS[s.id]}
                  </span>
                </div>

                {/* 文字区 */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>
                    {s.label}
                  </div>
                  <div style={{ fontSize: 16, color: 'rgba(255,255,255,0.5)', lineHeight: 1.4 }}>
                    {s.description}
                  </div>
                </div>

                {/* 时长 */}
                <div style={{
                  flexShrink: 0,
                  fontSize: 16,
                  color: 'rgba(255,255,255,0.4)',
                  fontWeight: 600,
                }}>
                  ~{s.estimatedMinutes}min
                </div>
              </button>
            ))}
          </div>

          <button
            type="button"
            style={{ ...secondaryBtnStyle, marginTop: 24 }}
            onClick={() => {
              setStep('password');
              setPassword('');
            }}
          >
            返回
          </button>
        </div>
      </div>
    );
  }

  // ─── 步骤3：场景预览 & 开始 ──────────────────────────────────────────────

  if (step === 'preview' && selectedInfo) {
    const color = SCENARIO_COLORS[selectedInfo.id];
    return (
      <div style={pageStyle}>
        <div style={{ ...cardStyle, maxWidth: 560 }}>
          {/* 场景头部 */}
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <div style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 72,
              height: 72,
              borderRadius: 16,
              backgroundColor: `${color}20`,
              marginBottom: 16,
            }}>
              <span style={{ fontSize: 28, fontWeight: 700, color, fontFamily: 'monospace' }}>
                {SCENARIO_ICONS[selectedInfo.id]}
              </span>
            </div>
            <h2 style={{ ...titleStyle, marginBottom: 4 }}>{selectedInfo.label}</h2>
            <p style={{ ...subtitleStyle, marginBottom: 0 }}>
              预计 {selectedInfo.estimatedMinutes} 分钟
            </p>
          </div>

          {/* 训练步骤列表 */}
          <div style={{
            backgroundColor: 'rgba(255,255,255,0.04)',
            borderRadius: 12,
            padding: '20px 24px',
            marginBottom: 32,
          }}>
            <div style={{
              color: 'rgba(255,255,255,0.5)',
              fontSize: 16,
              fontWeight: 600,
              marginBottom: 16,
            }}>
              训练步骤
            </div>
            {selectedInfo.steps.map((stepText, idx) => (
              <div
                key={idx}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 12,
                  marginBottom: idx < selectedInfo.steps.length - 1 ? 14 : 0,
                }}
              >
                <div style={{
                  width: 28,
                  height: 28,
                  borderRadius: '50%',
                  backgroundColor: `${color}30`,
                  color,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 16,
                  fontWeight: 700,
                  flexShrink: 0,
                }}>
                  {idx + 1}
                </div>
                <div style={{
                  color: 'rgba(255,255,255,0.8)',
                  fontSize: 16,
                  lineHeight: 1.5,
                  paddingTop: 2,
                }}>
                  {stepText}
                </div>
              </div>
            ))}
          </div>

          {/* 重要提示 */}
          <div style={{
            backgroundColor: 'rgba(217, 119, 6, 0.1)',
            border: '1px solid rgba(217, 119, 6, 0.3)',
            borderRadius: 12,
            padding: '16px 20px',
            marginBottom: 32,
            display: 'flex',
            gap: 12,
            alignItems: 'flex-start',
          }}>
            <span style={{ color: '#D97706', fontSize: 20, flexShrink: 0, lineHeight: 1 }}>!</span>
            <div style={{ color: 'rgba(255,255,255,0.7)', fontSize: 16, lineHeight: 1.5 }}>
              训练模式下的所有操作（下单、结账、退菜等）均为模拟操作，
              <strong style={{ color: '#D97706' }}>不会影响真实经营数据</strong>。
              训练完成后请退出训练模式恢复正常收银。
            </div>
          </div>

          {/* 操作按钮 */}
          <button
            type="button"
            style={{
              ...primaryBtnStyle,
              minHeight: 64,
              fontSize: 20,
            }}
            onPointerDown={onPointerDown}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onClick={handleStart}
          >
            开始训练
          </button>
          <button
            type="button"
            style={secondaryBtnStyle}
            onClick={() => {
              setSelectedScenario(null);
              setStep('scenario');
            }}
          >
            返回选择场景
          </button>
        </div>
      </div>
    );
  }

  return null;
}
