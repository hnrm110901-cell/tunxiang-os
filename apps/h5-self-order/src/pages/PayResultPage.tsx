import { useState, useEffect } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useLang } from '@/i18n/LangContext';
import { getOrderStatus } from '@/api/orderApi';
import type { OrderStatusInfo } from '@/api/orderApi';

const PROGRESS_STEPS = [
  { key: 'received' as const, labelKey: 'stepReceived' as const, pct: 25 },
  { key: 'cooking' as const, labelKey: 'stepCooking' as const, pct: 50 },
  { key: 'ready' as const, labelKey: 'stepReady' as const, pct: 75 },
  { key: 'pickup' as const, labelKey: 'stepPickup' as const, pct: 100 },
];

/** 支付结果页 — 成功/失败 + 出餐进度 */
export default function PayResultPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const [searchParams] = useSearchParams();
  const { t } = useLang();
  const navigate = useNavigate();

  const status = searchParams.get('status') ?? 'success';
  const amount = searchParams.get('amount') ?? '0.00';

  const [orderStatus, setOrderStatus] = useState<OrderStatusInfo | null>(null);
  const [estimatedMinutes, setEstimatedMinutes] = useState(15);

  // 轮询出餐进度
  useEffect(() => {
    if (!orderId || status !== 'success') return;

    const poll = async () => {
      try {
        const data = await getOrderStatus(orderId);
        setOrderStatus(data);
        // 找到当前步骤的预估时间
        const currentStep = data.steps.find((s) => s.key === data.status);
        if (currentStep) setEstimatedMinutes(currentStep.estimatedMinutes);
      } catch {
        // Mock: 模拟进度
        setOrderStatus({
          orderId: orderId ?? '',
          status: 'received',
          steps: [
            { key: 'received', label: t('stepReceived'), estimatedMinutes: 2 },
            { key: 'cooking', label: t('stepCooking'), estimatedMinutes: 12 },
            { key: 'ready', label: t('stepReady'), estimatedMinutes: 2 },
            { key: 'pickup', label: t('stepPickup'), estimatedMinutes: 0 },
          ],
          createdAt: new Date().toISOString(),
        });
      }
    };

    poll();
    const interval = setInterval(poll, 8000);
    return () => clearInterval(interval);
  }, [orderId, status, t]);

  const currentPct = orderStatus
    ? (PROGRESS_STEPS.find((s) => s.key === orderStatus.status)?.pct ?? 0)
    : 0;

  if (status !== 'success') {
    return (
      <div style={{
        minHeight: '100vh', background: 'var(--tx-bg-primary)',
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', padding: 32,
      }}>
        <svg width="64" height="64" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="#FF3B30" strokeWidth="2"/>
          <path d="M8 8l8 8M16 8l-8 8" stroke="#FF3B30" strokeWidth="2" strokeLinecap="round"/>
        </svg>
        <div style={{
          fontSize: 'var(--tx-font-xl)', fontWeight: 700,
          color: 'var(--tx-text-primary)', marginTop: 20,
        }}>
          {t('payResultFailed')}
        </div>
        <div style={{
          fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-tertiary)', marginTop: 8,
        }}>
          {t('payResultRetryHint')}
        </div>
        <button
          className="tx-pressable"
          onClick={() => navigate(-1)}
          style={{
            marginTop: 32, padding: '14px 48px',
            borderRadius: 'var(--tx-radius-full)',
            background: '#FF6B35', color: '#fff',
            fontSize: 'var(--tx-font-md)', fontWeight: 600,
          }}
        >
          {t('retry')}
        </button>
      </div>
    );
  }

  return (
    <div style={{
      minHeight: '100vh', background: 'var(--tx-bg-primary)',
      paddingBottom: 120,
    }}>
      {/* 成功头部 */}
      <div style={{
        textAlign: 'center', padding: '48px 32px 32px',
      }}>
        <svg width="64" height="64" viewBox="0 0 24 24" fill="none" style={{ margin: '0 auto' }}>
          <circle cx="12" cy="12" r="10" stroke="#22C55E" strokeWidth="2"/>
          <path d="M8 12l3 3 5-5" stroke="#22C55E" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        <div style={{
          fontSize: 'var(--tx-font-xxl)', fontWeight: 700,
          color: 'var(--tx-text-primary)', marginTop: 16,
        }}>
          {t('payResultSuccess')}
        </div>
        <div style={{
          fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-tertiary)', marginTop: 8,
        }}>
          {t('payResultOrderNo')}: {orderId}
        </div>
        <div style={{
          fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-tertiary)', marginTop: 4,
        }}>
          {t('payResultAmount')}: <span style={{ color: '#FF6B35', fontWeight: 600 }}>{t('yuan')}{amount}</span>
        </div>
      </div>

      {/* 预计出餐时间 */}
      <div style={{
        margin: '0 16px 16px', padding: 20,
        borderRadius: 'var(--tx-radius-lg)',
        background: 'var(--tx-bg-card)', textAlign: 'center',
      }}>
        <div style={{ fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-secondary)' }}>
          {t('payResultEstTime')}
        </div>
        <div style={{
          fontSize: 36, fontWeight: 700, color: '#FF6B35', marginTop: 4,
        }}>
          ~{estimatedMinutes} <span style={{ fontSize: 'var(--tx-font-md)' }}>{t('payResultMinutes')}</span>
        </div>
      </div>

      {/* 出餐进度条 */}
      <div style={{
        margin: '0 16px 16px', padding: 20,
        borderRadius: 'var(--tx-radius-lg)',
        background: 'var(--tx-bg-card)',
      }}>
        <div style={{ fontSize: 'var(--tx-font-sm)', fontWeight: 600, color: 'var(--tx-text-primary)', marginBottom: 16 }}>
          {t('payResultProgress')}
        </div>
        {/* 进度条 */}
        <div style={{
          width: '100%', height: 6, borderRadius: 3,
          background: 'var(--tx-bg-tertiary)', overflow: 'hidden', marginBottom: 12,
        }}>
          <div style={{
            width: `${currentPct}%`, height: '100%', borderRadius: 3,
            background: '#22C55E',
            transition: 'width 1s ease',
          }} />
        </div>
        {/* 步骤标签 */}
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          {PROGRESS_STEPS.map((step) => {
            const isActive = orderStatus?.status === step.key;
            const isDone = currentPct >= step.pct;
            return (
              <div key={step.key} style={{ textAlign: 'center', flex: 1 }}>
                <div style={{
                  width: 24, height: 24, borderRadius: 12,
                  background: isDone ? '#22C55E' : 'var(--tx-bg-tertiary)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  margin: '0 auto 6px',
                  border: isActive ? '2px solid #22C55E' : 'none',
                }}>
                  {isDone && (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                      <path d="M5 12l5 5L19 7" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  )}
                </div>
                <div style={{
                  fontSize: 11,
                  color: isActive ? '#22C55E' : 'var(--tx-text-tertiary)',
                  fontWeight: isActive ? 600 : 400,
                }}>
                  {t(step.labelKey)}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 底部操作按钮 */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        padding: '12px 16px',
        paddingBottom: 'calc(12px + var(--safe-area-bottom))',
        background: 'var(--tx-bg-secondary)',
        borderTop: '1px solid rgba(255,255,255,0.06)',
        display: 'flex', gap: 12,
      }}>
        <button
          className="tx-pressable"
          onClick={() => orderId && navigate(`/order/${orderId}/track`)}
          style={{
            flex: 1, height: 50,
            borderRadius: 'var(--tx-radius-full)',
            background: 'var(--tx-bg-card)',
            border: '1px solid rgba(255,255,255,0.1)',
            color: 'var(--tx-text-primary)',
            fontSize: 'var(--tx-font-sm)', fontWeight: 600,
          }}
        >
          {t('payResultViewOrder')}
        </button>
        <button
          className="tx-pressable"
          onClick={() => navigate('/menu')}
          style={{
            flex: 1, height: 50,
            borderRadius: 'var(--tx-radius-full)',
            background: '#FF6B35', color: '#fff',
            fontSize: 'var(--tx-font-sm)', fontWeight: 700,
          }}
        >
          {t('payResultContinue')}
        </button>
      </div>
    </div>
  );
}
