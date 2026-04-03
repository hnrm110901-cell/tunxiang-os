/**
 * DiscountPreviewSheet — 折扣分析底部抽屉
 *
 * 在收银员执行折扣前，实时调用 tx-brain 折扣分析 API，
 * 展示 AI 风险评估结果（allow / warn / reject）。
 *
 * 设计规范：Store 终端（安卓 POS），纯内联 CSS，禁止 Ant Design。
 * 最小点击区域 48×48px，字体 ≥ 16px，无 hover 依赖。
 */
import { useState, useEffect, useRef } from 'react';

// ─── 类型定义 ───────────────────────────────────────────────────────────────

export interface DiscountParams {
  orderId: string;
  discountType: 'percentage' | 'fixed' | 'free_item';
  discountValue: number;   // 折扣率(0-1) 或 减免金额(分)
  orderAmountFen: number;
  employeeId: string;
  currentMarginRate: number; // 当前毛利率 0-1
}

interface AnalyzeResult {
  decision: 'allow' | 'warn' | 'reject';
  confidence: number;
  reason: string;
  constraints_check: {
    margin_ok: boolean;
    authority_ok: boolean;
    pattern_ok: boolean;
  };
}

export interface DiscountPreviewSheetProps {
  visible: boolean;
  onClose: () => void;
  onConfirm: () => void;
  discountParams: DiscountParams | null;
}

// ─── 辅助常量 ────────────────────────────────────────────────────────────────

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const TIMEOUT_MS = 8000;

const DECISION_CONFIG = {
  allow: {
    icon: '✓',
    label: '可以操作',
    color: '#0F6E56',
    bgColor: 'rgba(15,110,86,0.18)',
  },
  warn: {
    icon: '⚠',
    label: '需要注意',
    color: '#BA7517',
    bgColor: 'rgba(186,117,23,0.18)',
  },
  reject: {
    icon: '✗',
    label: '无法执行',
    color: '#A32D2D',
    bgColor: 'rgba(163,45,45,0.18)',
  },
} as const;

const CONSTRAINT_LABELS: Record<'margin_ok' | 'authority_ok' | 'pattern_ok', string> = {
  margin_ok: '毛利底线',
  authority_ok: '权限校验',
  pattern_ok: '操作合规',
};

// ─── 动画关键帧（通过 <style> 注入一次）────────────────────────────────────

const SPIN_KEYFRAME_ID = 'tx-spin-keyframe';
function ensureSpinKeyframe() {
  if (document.getElementById(SPIN_KEYFRAME_ID)) return;
  const style = document.createElement('style');
  style.id = SPIN_KEYFRAME_ID;
  style.textContent = `@keyframes tx-spin { to { transform: rotate(360deg); } }`;
  document.head.appendChild(style);
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export function DiscountPreviewSheet({
  visible,
  onClose,
  onConfirm,
  discountParams,
}: DiscountPreviewSheetProps) {
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [result, setResult] = useState<AnalyzeResult | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 注入动画关键帧
  useEffect(() => { ensureSpinKeyframe(); }, []);

  // 每次 discountParams 变化（或 sheet 打开）时自动调用 API
  useEffect(() => {
    if (!visible || !discountParams) return;

    // 取消上一次未完成的请求
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setStatus('loading');
    setResult(null);

    const tenantId = localStorage.getItem('tenantId') ?? '';

    const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);

    fetch(`${API_BASE}/api/v1/brain/discount/analyze`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Tenant-ID': tenantId,
      },
      body: JSON.stringify({
        order_id: discountParams.orderId,
        discount_type: discountParams.discountType,
        discount_value: discountParams.discountValue,
        order_amount_fen: discountParams.orderAmountFen,
        employee_id: discountParams.employeeId,
        current_margin_rate: discountParams.currentMarginRate,
      }),
      signal: controller.signal,
    })
      .then(async (res) => {
        clearTimeout(timeoutId);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: AnalyzeResult = await res.json();
        setResult(data);
        setStatus('success');
      })
      .catch((err: unknown) => {
        clearTimeout(timeoutId);
        if (err instanceof Error && err.name === 'AbortError') return; // 手动取消，不更新状态
        setStatus('error');
      });

    return () => {
      clearTimeout(timeoutId);
      controller.abort();
    };
  }, [visible, discountParams]);

  // 关闭时重置状态
  const handleClose = () => {
    abortRef.current?.abort();
    setStatus('idle');
    setResult(null);
    onClose();
  };

  const canConfirm =
    status === 'error' ||
    (status === 'success' && result !== null && result.decision !== 'reject');

  const decisionConfig = result ? DECISION_CONFIG[result.decision] : null;

  return (
    <>
      {/* 遮罩层 */}
      <div
        onClick={handleClose}
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.55)',
          zIndex: 900,
          opacity: visible ? 1 : 0,
          pointerEvents: visible ? 'auto' : 'none',
          transition: 'opacity 0.3s ease',
        }}
      />

      {/* 抽屉主体 */}
      <div
        style={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          zIndex: 901,
          background: '#1E2A3A',
          borderRadius: '16px 16px 0 0',
          transform: visible ? 'translateY(0)' : 'translateY(100%)',
          transition: 'transform 0.3s ease',
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
          fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
          color: '#fff',
        }}
      >
        {/* ── 标题栏 ── */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 20px',
          height: 60,
          borderBottom: '1px solid rgba(255,255,255,0.08)',
          flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 20, fontWeight: 700 }}>折扣分析</span>
            <span style={{
              fontSize: 13,
              padding: '2px 8px',
              borderRadius: 4,
              background: 'rgba(255,107,53,0.2)',
              color: '#FF6B35',
              fontWeight: 600,
            }}>
              AI 风险评估
            </span>
          </div>
          <button
            type="button"
            onClick={handleClose}
            style={{
              width: 48,
              height: 48,
              border: 'none',
              borderRadius: 8,
              background: 'rgba(255,255,255,0.08)',
              color: '#E0E0E0',
              fontSize: 22,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
            aria-label="关闭"
          >
            ×
          </button>
        </div>

        {/* ── 内容区域 ── */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch',
          padding: 20,
        }}>
          {/* 加载状态 */}
          {status === 'loading' && (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 16,
              minHeight: 160,
            }}>
              <div style={{
                width: 48,
                height: 48,
                border: '4px solid rgba(255,107,53,0.2)',
                borderTopColor: '#FF6B35',
                borderRadius: '50%',
                animation: 'tx-spin 0.8s linear infinite',
              }} />
              <span style={{ fontSize: 18, color: '#B0B8C8' }}>AI 分析中...</span>
            </div>
          )}

          {/* 错误状态 */}
          {status === 'error' && (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 12,
              minHeight: 160,
              textAlign: 'center',
            }}>
              <div style={{ fontSize: 40 }}>📡</div>
              <div style={{ fontSize: 17, color: '#BA7517', fontWeight: 600 }}>
                分析服务暂时不可用
              </div>
              <div style={{ fontSize: 16, color: '#8A94A4', lineHeight: 1.5 }}>
                请手动判断折扣合理性
                <br />
                确认后操作将正常执行
              </div>
            </div>
          )}

          {/* 成功状态 */}
          {status === 'success' && result && decisionConfig && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              {/* 决策状态卡片 */}
              <div style={{
                borderRadius: 12,
                background: decisionConfig.bgColor,
                border: `1.5px solid ${decisionConfig.color}`,
                padding: '16px 20px',
                display: 'flex',
                alignItems: 'center',
                gap: 16,
              }}>
                <div style={{
                  width: 56,
                  height: 56,
                  borderRadius: '50%',
                  background: decisionConfig.color,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 26,
                  fontWeight: 700,
                  color: '#fff',
                  flexShrink: 0,
                }}>
                  {decisionConfig.icon}
                </div>
                <div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: decisionConfig.color }}>
                    {decisionConfig.label}
                  </div>
                  <div style={{ fontSize: 16, color: '#8A94A4', marginTop: 2 }}>
                    决策类型：{
                      result.decision === 'allow' ? '允许' :
                      result.decision === 'warn' ? '警告' : '拒绝'
                    }
                  </div>
                </div>
              </div>

              {/* 置信度进度条 */}
              <div>
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  marginBottom: 8,
                  fontSize: 16,
                  color: '#B0B8C8',
                }}>
                  <span>AI 置信度</span>
                  <span style={{ fontWeight: 700, color: '#fff' }}>
                    {Math.round(result.confidence * 100)}%
                  </span>
                </div>
                <div style={{
                  height: 8,
                  background: 'rgba(255,255,255,0.1)',
                  borderRadius: 4,
                  overflow: 'hidden',
                }}>
                  <div style={{
                    height: '100%',
                    width: `${Math.round(result.confidence * 100)}%`,
                    background: decisionConfig.color,
                    borderRadius: 4,
                    transition: 'width 0.6s ease',
                  }} />
                </div>
              </div>

              {/* AI 原因说明 */}
              <div style={{
                borderRadius: 10,
                background: 'rgba(255,255,255,0.05)',
                padding: '12px 16px',
              }}>
                <div style={{ fontSize: 14, color: '#8A94A4', marginBottom: 6, fontWeight: 600 }}>
                  分析依据
                </div>
                <div style={{ fontSize: 16, color: '#E0E0E0', lineHeight: 1.6 }}>
                  {result.reason}
                </div>
              </div>

              {/* 三条硬约束校验 */}
              <div>
                <div style={{ fontSize: 16, color: '#8A94A4', marginBottom: 10, fontWeight: 600 }}>
                  硬约束校验
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {(
                    ['margin_ok', 'authority_ok', 'pattern_ok'] as const
                  ).map((key) => {
                    const passed = result.constraints_check[key];
                    return (
                      <div
                        key={key}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 12,
                          padding: '10px 14px',
                          borderRadius: 8,
                          background: passed
                            ? 'rgba(15,110,86,0.12)'
                            : 'rgba(163,45,45,0.12)',
                          minHeight: 48,
                        }}
                      >
                        <div style={{
                          width: 24,
                          height: 24,
                          borderRadius: '50%',
                          background: passed ? '#0F6E56' : '#A32D2D',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: 14,
                          color: '#fff',
                          fontWeight: 700,
                          flexShrink: 0,
                        }}>
                          {passed ? '√' : '✗'}
                        </div>
                        <span style={{
                          fontSize: 17,
                          color: passed ? '#4DC9A3' : '#E06060',
                          fontWeight: 500,
                        }}>
                          {CONSTRAINT_LABELS[key]}
                        </span>
                        <span style={{
                          marginLeft: 'auto',
                          fontSize: 16,
                          color: passed ? '#4DC9A3' : '#E06060',
                          fontWeight: 600,
                        }}>
                          {passed ? '通过' : '未通过'}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ── 底部按钮行 ── */}
        <div style={{
          display: 'flex',
          gap: 12,
          padding: '12px 20px 20px',
          borderTop: '1px solid rgba(255,255,255,0.08)',
          flexShrink: 0,
        }}>
          <button
            type="button"
            onClick={handleClose}
            style={{
              flex: 1,
              height: 56,
              border: 'none',
              borderRadius: 10,
              background: '#374151',
              color: '#E0E0E0',
              fontSize: 18,
              fontWeight: 600,
              cursor: 'pointer',
              fontFamily: 'inherit',
              transition: 'transform 200ms ease',
            }}
            onTouchStart={(e) => { (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)'; }}
            onTouchEnd={(e) => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => { if (canConfirm) { onConfirm(); handleClose(); } }}
            disabled={!canConfirm}
            style={{
              flex: 1,
              height: 56,
              border: 'none',
              borderRadius: 10,
              background: canConfirm ? '#FF6B35' : '#3A3A3A',
              color: canConfirm ? '#fff' : '#666',
              fontSize: 18,
              fontWeight: 700,
              cursor: canConfirm ? 'pointer' : 'not-allowed',
              fontFamily: 'inherit',
              opacity: canConfirm ? 1 : 0.5,
              transition: 'transform 200ms ease, background 200ms ease',
            }}
            onTouchStart={(e) => {
              if (canConfirm) (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
            }}
            onTouchEnd={(e) => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
          >
            {status === 'loading'
              ? 'AI 分析中...'
              : status === 'error'
                ? '忽略风险，确认折扣'
                : result?.decision === 'reject'
                  ? '不可执行'
                  : '确认折扣'}
          </button>
        </div>
      </div>
    </>
  );
}
