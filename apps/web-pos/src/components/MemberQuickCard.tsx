/**
 * MemberQuickCard — 底部弹出式会员快速识别卡片
 *
 * 开台/结账时识别会员，展示精简画像，3秒倒计时自动关闭。
 * Sprint 2：菜品智能体 + 客户大脑 POS 层
 */
import { useEffect, useRef, useState } from 'react';

interface MemberQuickCardProps {
  visible: boolean;
  onClose: () => void;
  member?: {
    name: string;
    level: string;
    preferences: string[];
    avoidances?: string[];
    lastOrderSummary?: string;
    wineStorage?: string;
  };
}

const AUTO_CLOSE_SECONDS = 3;

export default function MemberQuickCard({
  visible,
  onClose,
  member,
}: MemberQuickCardProps) {
  const [countdown, setCountdown] = useState(AUTO_CLOSE_SECONDS);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 倒计时：每次 visible 变为 true 时重置
  useEffect(() => {
    if (!visible) {
      setCountdown(AUTO_CLOSE_SECONDS);
      if (timerRef.current) clearInterval(timerRef.current);
      return;
    }

    setCountdown(AUTO_CLOSE_SECONDS);
    timerRef.current = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(timerRef.current!);
          onClose();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [visible, onClose]);

  if (!visible) return null;

  return (
    <>
      {/* 背景遮罩 */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 999,
          background: 'rgba(0,0,0,0.45)',
        }}
      />

      {/* 底部卡片 */}
      <div
        style={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          zIndex: 1000,
          height: 300,
          background: '#1a2a33',
          borderRadius: '16px 16px 0 0',
          padding: '16px 20px 24px',
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          boxShadow: '0 -4px 24px rgba(0,0,0,0.35)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0' }}>
            👤 会员识别
          </span>
          <button
            onClick={onClose}
            aria-label="关闭"
            style={{
              minWidth: 44,
              minHeight: 44,
              background: 'transparent',
              border: 'none',
              color: '#8A94A4',
              fontSize: 20,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: 8,
            }}
          >
            ✕
          </button>
        </div>

        {/* 会员信息 */}
        {member ? (
          <div style={{ flex: 1, overflow: 'hidden' }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#e2e8f0', marginBottom: 4 }}>
              {member.name}
              <span
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: '#FFD700',
                  border: '1px solid rgba(255,215,0,.4)',
                  borderRadius: 4,
                  padding: '1px 6px',
                  marginLeft: 10,
                }}
              >
                {member.level}
              </span>
            </div>

            {/* 偏好 */}
            {member.preferences.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                {member.preferences.map((tag) => (
                  <span
                    key={tag}
                    style={{
                      fontSize: 12,
                      padding: '3px 8px',
                      borderRadius: 4,
                      background: 'rgba(109,62,168,.2)',
                      color: '#c4b5fd',
                      fontWeight: 600,
                    }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}

            {/* 忌口 */}
            {member.avoidances && member.avoidances.length > 0 && (
              <div style={{ fontSize: 13, color: '#f87171', marginTop: 8, fontWeight: 600 }}>
                ⚠ 忌{member.avoidances.join('/')}
              </div>
            )}

            {/* 上次消费 */}
            {member.lastOrderSummary && (
              <div style={{ fontSize: 13, color: '#64748b', marginTop: 6 }}>
                上次：{member.lastOrderSummary}
              </div>
            )}

            {/* 存酒 */}
            {member.wineStorage && (
              <div style={{ fontSize: 13, color: '#BA7517', marginTop: 4, fontWeight: 600 }}>
                🍷 {member.wineStorage}
              </div>
            )}
          </div>
        ) : (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ fontSize: 14, color: '#64748b' }}>未识别会员信息</span>
          </div>
        )}

        {/* 确认按钮（含倒计时） */}
        <button
          onClick={onClose}
          style={{
            width: '100%',
            height: 56,
            border: 'none',
            borderRadius: 12,
            background: '#FF6B35',
            color: '#fff',
            fontSize: 16,
            fontWeight: 700,
            cursor: 'pointer',
            fontFamily: 'inherit',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
          }}
        >
          确认，继续服务
          <span
            style={{
              fontSize: 13,
              background: 'rgba(255,255,255,.25)',
              borderRadius: 20,
              padding: '2px 8px',
            }}
          >
            {countdown}s
          </span>
        </button>
      </div>
    </>
  );
}
