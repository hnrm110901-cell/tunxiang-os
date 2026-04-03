import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useLang } from '@/i18n/LangContext';
import { getOrderSummary, submitFeedback } from '@/api/orderApi';
import type { OrderSummary } from '@/api/orderApi';

/** 评价页 — 5星评分 + 菜品单独评价 + 拍照 */
export default function FeedbackPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const { t } = useLang();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [order, setOrder] = useState<OrderSummary | null>(null);
  const [dishRatings, setDishRatings] = useState<Record<string, number>>({});
  const [serviceRating, setServiceRating] = useState(5);
  const [environmentRating, setEnvironmentRating] = useState(5);
  const [comment, setComment] = useState('');
  const [photos, setPhotos] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [earnedPoints, setEarnedPoints] = useState(0);

  useEffect(() => {
    if (!orderId) return;
    getOrderSummary(orderId).then((data) => {
      setOrder(data);
      const ratings: Record<string, number> = {};
      data.items.forEach((item) => { ratings[item.dishId] = 5; });
      setDishRatings(ratings);
    }).catch(() => { /* 404 */ });
  }, [orderId]);

  const handlePhotoUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    Array.from(files).forEach((file) => {
      const reader = new FileReader();
      reader.onload = () => {
        if (typeof reader.result === 'string') {
          setPhotos((prev) => [...prev, reader.result as string]);
        }
      };
      reader.readAsDataURL(file);
    });
  };

  const handleSubmit = async () => {
    if (!orderId || submitting) return;
    setSubmitting(true);
    try {
      const result = await submitFeedback({
        orderId,
        dishRatings: Object.entries(dishRatings).map(([dishId, rating]) => ({ dishId, rating })),
        serviceRating,
        environmentRating,
        comment: comment || undefined,
        photoUrls: photos.length > 0 ? photos : undefined,
      });
      setEarnedPoints(result.pointsEarned);
      setSubmitted(true);
    } catch {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        background: 'var(--tx-bg-primary)', padding: 32,
      }}>
        <svg width="80" height="80" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="var(--tx-success)" strokeWidth="2"/>
          <path d="M8 12l3 3 5-5" stroke="var(--tx-success)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        <div style={{
          marginTop: 20, fontSize: 'var(--tx-font-xl)', fontWeight: 700,
          color: 'var(--tx-text-primary)',
        }}>
          {t('feedbackReward').replace('{points}', String(earnedPoints))}
        </div>
        <button
          className="tx-pressable"
          onClick={() => navigate('/menu')}
          style={{
            marginTop: 32, padding: '14px 40px',
            borderRadius: 'var(--tx-radius-full)',
            background: 'var(--tx-brand)', color: '#fff',
            fontSize: 'var(--tx-font-md)', fontWeight: 600,
          }}
        >
          {t('menuTitle')}
        </button>
      </div>
    );
  }

  return (
    <div style={{
      minHeight: '100vh', background: 'var(--tx-bg-primary)',
      paddingBottom: 100,
    }}>
      {/* 顶部 */}
      <div style={{ display: 'flex', alignItems: 'center', padding: 16, gap: 12 }}>
        <button
          className="tx-pressable"
          onClick={() => navigate(-1)}
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
          {t('feedbackTitle')}
        </h1>
      </div>

      {/* 整体评分：服务 + 环境 */}
      <div style={{
        margin: '0 16px 16px', padding: 16,
        borderRadius: 'var(--tx-radius-md)',
        background: 'var(--tx-bg-card)',
      }}>
        <RatingRow
          label={t('rateService')}
          value={serviceRating}
          onChange={setServiceRating}
        />
        <div style={{ height: 12 }} />
        <RatingRow
          label={t('rateEnvironment')}
          value={environmentRating}
          onChange={setEnvironmentRating}
        />
      </div>

      {/* 菜品单独评分 */}
      {order && (
        <div style={{
          margin: '0 16px 16px', padding: 16,
          borderRadius: 'var(--tx-radius-md)',
          background: 'var(--tx-bg-card)',
        }}>
          <div style={{
            fontSize: 'var(--tx-font-md)', fontWeight: 600,
            color: 'var(--tx-text-primary)', marginBottom: 16,
          }}>
            {t('rateDish')}
          </div>
          {order.items.map((item) => (
            <div key={item.dishId} style={{
              display: 'flex', gap: 12, marginBottom: 16,
              alignItems: 'center',
            }}>
              <img
                src={item.dishImage}
                alt={item.dishName}
                loading="lazy"
                style={{
                  width: 56, height: 56, borderRadius: 8,
                  objectFit: 'cover', flexShrink: 0,
                }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-primary)',
                  fontWeight: 500,
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                }}>
                  {item.dishName}
                </div>
                <StarRow
                  value={dishRatings[item.dishId] ?? 5}
                  onChange={(v) => setDishRatings((prev) => ({ ...prev, [item.dishId]: v }))}
                  size={20}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 文字评价 */}
      <div style={{ margin: '0 16px 16px' }}>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={t('feedbackPlaceholder')}
          rows={4}
          style={{
            width: '100%', padding: 14,
            borderRadius: 'var(--tx-radius-md)',
            background: 'var(--tx-bg-card)',
            color: 'var(--tx-text-primary)',
            fontSize: 'var(--tx-font-sm)',
            resize: 'none',
          }}
        />
      </div>

      {/* 上传照片 */}
      <div style={{ margin: '0 16px 16px' }}>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          multiple
          onChange={handlePhotoUpload}
          style={{ display: 'none' }}
        />
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {photos.map((src, idx) => (
            <div key={idx} style={{ position: 'relative', width: 80, height: 80 }}>
              <img
                src={src}
                alt=""
                style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: 8 }}
              />
              <button
                onClick={() => setPhotos((prev) => prev.filter((_, i) => i !== idx))}
                style={{
                  position: 'absolute', top: -6, right: -6,
                  width: 22, height: 22, borderRadius: 11,
                  background: 'var(--tx-danger)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                  <path d="M6 6l12 12M6 18L18 6" stroke="#fff" strokeWidth="3" strokeLinecap="round"/>
                </svg>
              </button>
            </div>
          ))}
          <button
            className="tx-pressable"
            onClick={() => fileInputRef.current?.click()}
            style={{
              width: 80, height: 80, borderRadius: 8,
              background: 'var(--tx-bg-tertiary)',
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center',
              gap: 4,
            }}
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="5" width="18" height="14" rx="2" stroke="#666" strokeWidth="1.5"/>
              <circle cx="12" cy="12" r="3" stroke="#666" strokeWidth="1.5"/>
            </svg>
            <span style={{ fontSize: 10, color: 'var(--tx-text-tertiary)' }}>
              {t('uploadPhoto')}
            </span>
          </button>
        </div>
      </div>

      {/* 底部提交 */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        padding: '12px 16px',
        paddingBottom: 'calc(12px + var(--safe-area-bottom))',
        background: 'var(--tx-bg-secondary)',
        borderTop: '1px solid rgba(255,255,255,0.06)',
      }}>
        <button
          className="tx-pressable"
          onClick={handleSubmit}
          disabled={submitting}
          style={{
            width: '100%', height: 54,
            borderRadius: 'var(--tx-radius-full)',
            background: submitting ? 'var(--tx-bg-tertiary)' : 'var(--tx-brand)',
            color: submitting ? 'var(--tx-text-tertiary)' : '#fff',
            fontSize: 'var(--tx-font-lg)', fontWeight: 700,
          }}
        >
          {submitting ? t('loading') : t('submitFeedback')}
        </button>
      </div>
    </div>
  );
}

/* ---- 辅助组件 ---- */

function RatingRow({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
      <span style={{ fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-secondary)' }}>{label}</span>
      <StarRow value={value} onChange={onChange} size={28} />
    </div>
  );
}

function StarRow({ value, onChange, size }: { value: number; onChange: (v: number) => void; size: number }) {
  return (
    <div style={{ display: 'flex', gap: 4 }}>
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          onClick={() => onChange(star)}
          style={{ padding: 2, lineHeight: 1 }}
          aria-label={`${star} star`}
        >
          <svg width={size} height={size} viewBox="0 0 24 24" fill={star <= value ? '#FF6B2C' : 'none'}>
            <path
              d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"
              stroke={star <= value ? '#FF6B2C' : '#666'}
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      ))}
    </div>
  );
}
