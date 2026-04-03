import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useLang } from '@/i18n/LangContext';
import { getOrderStatus, rushOrder as rushOrderApi } from '@/api/orderApi';
import type { OrderStatusInfo, OrderStatus } from '@/api/orderApi';
import ProgressTracker from '@/components/ProgressTracker';

const RUSH_COOLDOWN = 30; // 催菜冷却秒数
const POLL_INTERVAL = 5000; // 轮询间隔

/** 实时进度追踪页 — Domino's Tracker 风格 */
export default function OrderTrack() {
  const { id: orderId } = useParams<{ id: string }>();
  const { t } = useLang();
  const navigate = useNavigate();

  const [status, setStatus] = useState<OrderStatusInfo | null>(null);
  const [rushCooldown, setRushCooldown] = useState(0);
  const cooldownRef = useRef<ReturnType<typeof setInterval>>();

  // 轮询订单状态
  useEffect(() => {
    if (!orderId) return;

    const poll = async () => {
      try {
        const data = await getOrderStatus(orderId);
        setStatus(data);
      } catch {
        /* retry on next poll */
      }
    };

    poll();
    const interval = setInterval(poll, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [orderId]);

  // 催菜冷却倒计时
  useEffect(() => {
    if (rushCooldown <= 0) {
      if (cooldownRef.current) clearInterval(cooldownRef.current);
      return;
    }
    cooldownRef.current = setInterval(() => {
      setRushCooldown((prev) => {
        if (prev <= 1) {
          clearInterval(cooldownRef.current);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => { if (cooldownRef.current) clearInterval(cooldownRef.current); };
  }, [rushCooldown]);

  // 催菜
  const handleRush = useCallback(async () => {
    if (rushCooldown > 0 || !orderId) return;
    try {
      await rushOrderApi(orderId);
      setRushCooldown(RUSH_COOLDOWN);
    } catch {
      /* ignore */
    }
  }, [orderId, rushCooldown]);

  const isComplete = status?.status === 'pickup' || status?.status === 'completed';

  return (
    <div style={{
      minHeight: '100vh', background: 'var(--tx-bg-primary)', padding: '16px',
    }}>
      {/* 顶部 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
        <button
          className="tx-pressable"
          onClick={() => navigate('/menu')}
          style={{
            width: 40, height: 40, borderRadius: 20,
            background: 'var(--tx-bg-tertiary)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M15 19l-7-7 7-7" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
        <h1 style={{ fontSize: 'var(--tx-font-xl)', fontWeight: 700, color: 'var(--tx-text-primary)' }}>
          {t('trackTitle')}
        </h1>
      </div>

      {!status ? (
        <div style={{ textAlign: 'center', padding: 48, color: 'var(--tx-text-tertiary)' }}>
          {t('loading')}
        </div>
      ) : (
        <>
          {/* 四步进度条 */}
          <div style={{
            background: 'var(--tx-bg-card)',
            borderRadius: 'var(--tx-radius-lg)',
            padding: '8px 0',
            marginBottom: 20,
          }}>
            <ProgressTracker steps={status.steps} currentStatus={status.status} />
          </div>

          {/* 当前制作的菜品 */}
          {status.currentDishName && status.status === 'cooking' && (
            <div
              className="tx-fade-in"
              style={{
                padding: 20,
                borderRadius: 'var(--tx-radius-md)',
                background: 'var(--tx-bg-card)',
                marginBottom: 16,
                textAlign: 'center',
              }}
            >
              <div style={{ fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-secondary)', marginBottom: 6 }}>
                {t('currentDish')}
              </div>
              <div style={{
                fontSize: 'var(--tx-font-lg)', fontWeight: 700,
                color: 'var(--tx-text-primary)',
              }}>
                {status.currentDishName}
              </div>
              {/* 动画指示器 */}
              <div style={{
                display: 'flex', justifyContent: 'center', gap: 6, marginTop: 16,
              }}>
                {[0, 1, 2].map((i) => (
                  <div
                    key={i}
                    style={{
                      width: 8, height: 8, borderRadius: 4,
                      background: 'var(--tx-brand)',
                      animation: `tx-pulse 1.2s infinite ${i * 0.2}s`,
                    }}
                  />
                ))}
              </div>
            </div>
          )}

          {/* 完成提示 */}
          {isComplete && (
            <div
              className="tx-fade-in"
              style={{
                padding: 32,
                borderRadius: 'var(--tx-radius-lg)',
                background: 'rgba(34, 197, 94, 0.1)',
                border: '1px solid rgba(34, 197, 94, 0.2)',
                textAlign: 'center', marginBottom: 16,
              }}
            >
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" style={{ margin: '0 auto 12px' }}>
                <circle cx="12" cy="12" r="10" stroke="#22C55E" strokeWidth="2"/>
                <path d="M8 12l3 3 5-5" stroke="#22C55E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              <div style={{ fontSize: 'var(--tx-font-lg)', fontWeight: 700, color: 'var(--tx-success)' }}>
                {t('stepPickup')}
              </div>
            </div>
          )}

          {/* 催菜按钮 */}
          {!isComplete && (
            <button
              className="tx-pressable"
              onClick={handleRush}
              disabled={rushCooldown > 0}
              style={{
                width: '100%', height: 52,
                borderRadius: 'var(--tx-radius-md)',
                background: rushCooldown > 0 ? 'var(--tx-bg-tertiary)' : 'var(--tx-bg-card)',
                border: rushCooldown > 0 ? 'none' : '1px solid var(--tx-brand)',
                color: rushCooldown > 0 ? 'var(--tx-text-tertiary)' : 'var(--tx-brand)',
                fontSize: 'var(--tx-font-md)', fontWeight: 600,
                marginBottom: 16,
                transition: 'all 0.2s',
              }}
            >
              {rushCooldown > 0
                ? t('rushCooldown').replace('{sec}', String(rushCooldown))
                : t('rushOrder')}
            </button>
          )}

          {/* 通知方式 */}
          {!isComplete && (
            <div style={{
              padding: 16, borderRadius: 'var(--tx-radius-md)',
              background: 'var(--tx-bg-card)', marginBottom: 16,
            }}>
              <div style={{
                fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-secondary)', marginBottom: 12,
              }}>
                出餐通知
              </div>
              <div style={{ display: 'flex', gap: 10 }}>
                <button
                  className="tx-pressable"
                  style={{
                    flex: 1, padding: '12px', borderRadius: 'var(--tx-radius-md)',
                    background: 'var(--tx-bg-tertiary)',
                    color: 'var(--tx-text-primary)', fontSize: 'var(--tx-font-sm)',
                  }}
                >
                  {t('notifyWechat')}
                </button>
                <button
                  className="tx-pressable"
                  style={{
                    flex: 1, padding: '12px', borderRadius: 'var(--tx-radius-md)',
                    background: 'var(--tx-bg-tertiary)',
                    color: 'var(--tx-text-primary)', fontSize: 'var(--tx-font-sm)',
                  }}
                >
                  {t('notifySms')}
                </button>
              </div>
            </div>
          )}

          {/* 去评价（完成后显示） */}
          {isComplete && orderId && (
            <button
              className="tx-pressable"
              onClick={() => navigate(`/feedback/${orderId}`)}
              style={{
                width: '100%', height: 52,
                borderRadius: 'var(--tx-radius-full)',
                background: 'var(--tx-brand)', color: '#fff',
                fontSize: 'var(--tx-font-md)', fontWeight: 700,
              }}
            >
              {t('feedbackTitle')}
            </button>
          )}
        </>
      )}
    </div>
  );
}
