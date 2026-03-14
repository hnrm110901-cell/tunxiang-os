/**
 * 公开邀请函H5页 — 全屏主题模板 + RSVP表单
 */
import React, { useState, useEffect } from 'react';
import { apiClient } from '../../utils/apiClient';
import styles from './InvitationView.module.css';

interface InvitationData {
  host_name: string;
  event_type: string;
  event_title: string;
  event_date: string;
  venue_name: string;
  venue_address: string;
  venue_lat?: number;
  venue_lng?: number;
  template: string;
  message: string;
  cover_image_url?: string;
  view_count: number;
  rsvp_count: number;
}

const THEME_MAP: Record<string, string> = {
  wedding_red: styles.themeWeddingRed,
  birthday_gold: styles.themeBirthdayGold,
  corporate_blue: styles.themeCorporateBlue,
  full_moon_pink: styles.themeFullMoonPink,
  graduation_green: styles.themeGraduationGreen,
};

const InvitationView: React.FC = () => {
  const [data, setData] = useState<InvitationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // RSVP form
  const [guestName, setGuestName] = useState('');
  const [partySize, setPartySize] = useState(1);
  const [dietary, setDietary] = useState('');
  const [blessMsg, setBlessMsg] = useState('');
  const [rsvpSubmitted, setRsvpSubmitted] = useState(false);

  // Extract share_token from URL
  const shareToken = window.location.pathname.split('/invitation/')[1] || '';

  useEffect(() => {
    if (!shareToken) {
      setError('无效的邀请函链接');
      setLoading(false);
      return;
    }
    loadInvitation();
  }, [shareToken]);

  const loadInvitation = async () => {
    try {
      const resp = await apiClient.get<InvitationData>(`/api/v1/public/invitation/${shareToken}`);
      setData(resp);
    } catch {
      setError('邀请函不存在或未发布');
    } finally {
      setLoading(false);
    }
  };

  const submitRsvp = async () => {
    if (!guestName.trim()) return;
    try {
      await apiClient.post(`/api/v1/public/invitation/${shareToken}/rsvp`, {
        guest_name: guestName,
        party_size: partySize,
        dietary_restrictions: dietary,
        message: blessMsg,
        status: 'attending',
      });
      setRsvpSubmitted(true);
    } catch {
      alert('提交失败，请重试');
    }
  };

  const formatDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      const days = ['日', '一', '二', '三', '四', '五', '六'];
      return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 周${days[d.getDay()]}`;
    } catch {
      return dateStr;
    }
  };

  if (loading) {
    return (
      <div className={`${styles.invitation} ${styles.themeCorporateBlue}`}>
        <div className={styles.container} style={{ display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
          <div style={{ color: '#999', fontSize: 16 }}>加载中...</div>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className={`${styles.invitation} ${styles.themeCorporateBlue}`}>
        <div className={styles.container} style={{ textAlign: 'center', paddingTop: 80 }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>📨</div>
          <div style={{ color: '#999', fontSize: 16 }}>{error || '邀请函不存在'}</div>
        </div>
      </div>
    );
  }

  const themeClass = THEME_MAP[data.template] || styles.themeCorporateBlue;

  return (
    <div className={`${styles.invitation} ${themeClass}`}>
      <div className={styles.container}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.eventType}>{data.event_type}</div>
          <h1 className={styles.eventTitle}>{data.event_title}</h1>
        </div>

        <div className={styles.divider} />

        {/* AI Generated Message */}
        {data.message && (
          <div className={styles.messageBox}>{data.message}</div>
        )}

        {/* Event Info */}
        <div className={styles.infoSection}>
          <div className={styles.infoRow}>
            <div className={styles.infoIcon}>📅</div>
            <div>
              <div className={styles.infoLabel}>时间</div>
              <div className={styles.infoValue}>{formatDate(data.event_date)}</div>
            </div>
          </div>
          <div className={styles.infoRow}>
            <div className={styles.infoIcon}>📍</div>
            <div>
              <div className={styles.infoLabel}>地点</div>
              <div className={styles.infoValue}>{data.venue_name}</div>
              {data.venue_address && (
                <div className={styles.infoLabel} style={{ marginTop: 2 }}>{data.venue_address}</div>
              )}
            </div>
          </div>
          <div className={styles.infoRow}>
            <div className={styles.infoIcon}>👤</div>
            <div>
              <div className={styles.infoLabel}>主人</div>
              <div className={styles.infoValue}>{data.host_name}</div>
            </div>
          </div>
        </div>

        {/* Navigation button */}
        {data.venue_lat && data.venue_lng && (
          <div style={{ textAlign: 'center' }}>
            <a
              className={styles.navBtn}
              href={`https://uri.amap.com/marker?position=${data.venue_lng},${data.venue_lat}&name=${encodeURIComponent(data.venue_name)}`}
              target="_blank"
              rel="noreferrer"
            >
              导航至餐厅
            </a>
          </div>
        )}

        <div className={styles.divider} />

        {/* RSVP */}
        <div className={styles.rsvpSection}>
          <h3 className={styles.rsvpTitle}>回执确认</h3>

          {rsvpSubmitted ? (
            <div className={styles.success}>
              ✓ 回执已提交，感谢您的确认！
            </div>
          ) : (
            <>
              <div className={styles.rsvpField}>
                <label className={styles.rsvpLabel}>您的姓名 *</label>
                <input
                  className={styles.rsvpInput}
                  placeholder="请输入姓名"
                  value={guestName}
                  onChange={e => setGuestName(e.target.value)}
                />
              </div>
              <div className={styles.rsvpField}>
                <label className={styles.rsvpLabel}>出席人数</label>
                <div className={styles.partySizeRow}>
                  {[1, 2, 3, 4, 5].map(n => (
                    <button
                      key={n}
                      className={`${styles.partySizeBtn} ${partySize === n ? styles.partySizeBtnActive : ''}`}
                      onClick={() => setPartySize(n)}
                    >
                      {n}人
                    </button>
                  ))}
                </div>
              </div>
              <div className={styles.rsvpField}>
                <label className={styles.rsvpLabel}>饮食限制</label>
                <input
                  className={styles.rsvpInput}
                  placeholder="如：素食、过敏等"
                  value={dietary}
                  onChange={e => setDietary(e.target.value)}
                />
              </div>
              <div className={styles.rsvpField}>
                <label className={styles.rsvpLabel}>祝福语</label>
                <textarea
                  className={styles.rsvpTextarea}
                  placeholder="送上您的祝福..."
                  value={blessMsg}
                  onChange={e => setBlessMsg(e.target.value)}
                />
              </div>
              <button
                className={styles.rsvpSubmit}
                disabled={!guestName.trim()}
                onClick={submitRsvp}
              >
                确认出席
              </button>
            </>
          )}
        </div>

        {/* Stats */}
        <div className={styles.stats}>
          {data.view_count}人已浏览 · {data.rsvp_count}人已确认
        </div>
      </div>
    </div>
  );
};

export default InvitationView;
