/**
 * 宴请接待 — VIP客户管理、到店弹窗提醒、历史偏好、宴请标记
 */
import { useState, useEffect, useCallback } from 'react';
import {
  fetchVIPAlerts,
  acknowledgeVIPAlert,
  getCustomerProfile,
  type VIPAlert,
  type CustomerProfile,
} from '../api/memberDepthApi';
import {
  fetchReservations,
  type Reservation,
} from '../api/reservationApi';

const STORE_ID = import.meta.env.VITE_STORE_ID || 'default-store';

type BanquetType = 'business' | 'family' | 'celebration' | 'other';

const BANQUET_MAP: Record<BanquetType, { label: string; color: string; bg: string }> = {
  business:    { label: '商务宴请', color: 'var(--tx-info)',    bg: '#EBF3FF' },
  family:      { label: '家庭聚餐', color: 'var(--tx-success)', bg: '#E8F5F0' },
  celebration: { label: '庆祝宴会', color: '#9333EA',           bg: '#F3E8FF' },
  other:       { label: '其他宴请', color: 'var(--tx-text-2)',  bg: 'var(--tx-bg-3)' },
};

const ALERT_TYPE_MAP: Record<VIPAlert['alert_type'], { label: string; color: string; bg: string }> = {
  arrival:      { label: '到店提醒', color: 'var(--tx-primary)', bg: 'var(--tx-primary-light)' },
  birthday:     { label: '生日提醒', color: '#9333EA',           bg: '#F3E8FF' },
  anniversary:  { label: '纪念日',   color: 'var(--tx-info)',    bg: '#EBF3FF' },
  long_absence: { label: '久未到店', color: 'var(--tx-warning)', bg: '#FEF3C7' },
};

export function VIPAlertPage() {
  const [alerts, setAlerts] = useState<VIPAlert[]>([]);
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAlert, setSelectedAlert] = useState<VIPAlert | null>(null);
  const [customerProfile, setCustomerProfile] = useState<CustomerProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [showArrivalAlert, setShowArrivalAlert] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  /** Find the reservation matching a VIP alert by customer_name (best-effort match) */
  const findReservationForAlert = useCallback(
    (alert: VIPAlert): Reservation | undefined =>
      reservations.find(
        (r) =>
          r.customer_name === alert.customer_name &&
          r.is_vip &&
          r.status !== 'cancelled' &&
          r.status !== 'no_show',
      ),
    [reservations],
  );

  const loadAlerts = useCallback(async () => {
    try {
      setError(null);
      const [alertResult, reservationResult] = await Promise.all([
        fetchVIPAlerts(STORE_ID),
        fetchReservations(STORE_ID),
      ]);
      setAlerts(alertResult.items);
      setReservations(reservationResult.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载VIP提醒失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAlerts();
  }, [loadAlerts]);

  // Load customer profile when an alert is selected
  const handleSelectAlert = useCallback(async (alert: VIPAlert) => {
    setSelectedAlert(alert);
    setCustomerProfile(null);
    try {
      setProfileLoading(true);
      const profile = await getCustomerProfile(alert.member_id);
      setCustomerProfile(profile);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载客户画像失败');
    } finally {
      setProfileLoading(false);
    }
  }, []);

  const handleAcknowledge = useCallback(async (alertId: string) => {
    try {
      setActionLoading(alertId);
      await acknowledgeVIPAlert(alertId);
      setShowArrivalAlert(null);
      await loadAlerts();
      // Update selectedAlert if it was the one acknowledged
      if (selectedAlert?.alert_id === alertId) {
        setSelectedAlert(prev => prev ? { ...prev, acknowledged: true } : null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认提醒失败');
    } finally {
      setActionLoading(null);
    }
  }, [loadAlerts, selectedAlert]);

  const unacknowledgedAlerts = alerts.filter(a => !a.acknowledged);
  const acknowledgedAlerts = alerts.filter(a => a.acknowledged);

  if (loading) {
    return (
      <div style={{ padding: 24, display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <div style={{ fontSize: 22, color: 'var(--tx-text-3)' }}>加载VIP提醒数据中...</div>
      </div>
    );
  }

  return (
    <div style={{ padding: 24, height: '100vh', display: 'flex', gap: 24 }}>
      {/* 左侧：VIP提醒列表 */}
      <div style={{ flex: '0 0 400px', display: 'flex', flexDirection: 'column' }}>
        <h1 style={{ fontSize: 32, fontWeight: 800, marginBottom: 20 }}>宴请接待</h1>

        {/* 错误提示 */}
        {error && (
          <div style={{
            background: '#FFF5F5', border: '1px solid var(--tx-danger)', borderRadius: 'var(--tx-radius-sm)',
            padding: '12px 20px', marginBottom: 16, color: 'var(--tx-danger)', fontSize: 18,
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <span>{error}</span>
            <button onClick={() => setError(null)} style={{
              border: 'none', background: 'transparent', color: 'var(--tx-danger)',
              fontSize: 18, cursor: 'pointer', fontWeight: 700,
            }}>关闭</button>
          </div>
        )}

        <div style={{
          flex: 1,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}>
          {/* 待处理提醒 */}
          {unacknowledgedAlerts.length > 0 && (
            <>
              <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--tx-text-2)' }}>
                待处理 ({unacknowledgedAlerts.length})
              </div>
              {unacknowledgedAlerts.map(a => (
                <VIPAlertCard
                  key={a.alert_id}
                  alert={a}
                  isSelected={selectedAlert?.alert_id === a.alert_id}
                  onSelect={() => handleSelectAlert(a)}
                  onMarkArrived={() => setShowArrivalAlert(a.alert_id)}
                />
              ))}
            </>
          )}

          {/* 已处理提醒 */}
          {acknowledgedAlerts.length > 0 && (
            <>
              <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--tx-text-3)', marginTop: 8 }}>
                已处理 ({acknowledgedAlerts.length})
              </div>
              {acknowledgedAlerts.map(a => (
                <VIPAlertCard
                  key={a.alert_id}
                  alert={a}
                  isSelected={selectedAlert?.alert_id === a.alert_id}
                  onSelect={() => handleSelectAlert(a)}
                  onMarkArrived={() => {}}
                />
              ))}
            </>
          )}

          {alerts.length === 0 && (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--tx-text-3)', fontSize: 18 }}>
              暂无VIP提醒
            </div>
          )}
        </div>
      </div>

      {/* 右侧：VIP详情 */}
      <div style={{
        flex: 1,
        background: '#fff',
        borderRadius: 'var(--tx-radius-lg)',
        boxShadow: 'var(--tx-shadow-md)',
        padding: 28,
        overflowY: 'auto',
        WebkitOverflowScrolling: 'touch',
      }}>
        {!selectedAlert ? (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            height: '100%', fontSize: 22, color: 'var(--tx-text-3)',
          }}>
            选择VIP客户查看接待详情
          </div>
        ) : profileLoading ? (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            height: '100%', fontSize: 22, color: 'var(--tx-text-3)',
          }}>
            加载客户画像中...
          </div>
        ) : customerProfile ? (
          <>
            {/* 头部 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ fontSize: 28, fontWeight: 800 }}>{customerProfile.name}</span>
                  {customerProfile.is_vip && (
                    <span style={{
                      background: '#FFD700', color: '#6B4E00',
                      fontSize: 16, fontWeight: 800, padding: '4px 12px', borderRadius: 6,
                    }}>{customerProfile.vip_level}</span>
                  )}
                  {(() => {
                    const at = ALERT_TYPE_MAP[selectedAlert.alert_type];
                    return (
                      <span style={{
                        background: at.bg, color: at.color,
                        fontSize: 16, fontWeight: 700, padding: '4px 12px', borderRadius: 6,
                      }}>{at.label}</span>
                    );
                  })()}
                </div>
                <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginTop: 4 }}>
                  {customerProfile.phone}
                </div>
              </div>
              <div style={{
                fontSize: 18, fontWeight: 700,
                color: selectedAlert.acknowledged ? 'var(--tx-success)' : 'var(--tx-text-3)',
                background: selectedAlert.acknowledged ? '#E8F5F0' : 'var(--tx-bg-3)',
                padding: '8px 16px', borderRadius: 8,
              }}>
                {selectedAlert.acknowledged ? '已处理' : '待处理'}
              </div>
            </div>

            {/* 提醒信息 */}
            <DetailSection title="提醒信息">
              <div style={{
                background: '#FEF3C7',
                padding: 16,
                borderRadius: 'var(--tx-radius-sm)',
                fontSize: 18,
                color: '#6B4E00',
                fontWeight: 600,
              }}>
                {selectedAlert.message}
              </div>
            </DetailSection>

            {/* 预订信息（如有匹配） */}
            {(() => {
              const res = findReservationForAlert(selectedAlert);
              if (!res) return null;
              return (
                <DetailSection title="预订信息">
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 12 }}>
                    <InfoBlock label="预订时间" value={res.time_slot} />
                    <InfoBlock label="包厢/桌位" value={res.room_or_table || '未指定'} />
                    <InfoBlock label="用餐人数" value={`${res.guest_count}人`} />
                  </div>
                  {res.special_requests && (
                    <div style={{
                      fontSize: 18,
                      color: 'var(--tx-text-2)',
                      background: 'var(--tx-bg-3)',
                      padding: 16,
                      borderRadius: 'var(--tx-radius-sm)',
                    }}>
                      <strong>特殊要求:</strong> {res.special_requests}
                    </div>
                  )}
                </DetailSection>
              );
            })()}

            {/* 客户偏好 */}
            <DetailSection title="客户偏好">
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
                {customerProfile.preferences.map(p => (
                  <span key={p} style={{
                    background: '#EBF3FF', color: 'var(--tx-info)',
                    fontSize: 18, fontWeight: 600, padding: '6px 14px', borderRadius: 6,
                  }}>{p}</span>
                ))}
                {customerProfile.preferences.length === 0 && (
                  <span style={{ fontSize: 18, color: 'var(--tx-text-3)' }}>暂无记录</span>
                )}
              </div>
              {customerProfile.allergies.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--tx-danger)' }}>忌口: </span>
                  {customerProfile.allergies.map(a => (
                    <span key={a} style={{
                      background: '#FFF5F5', color: 'var(--tx-danger)',
                      fontSize: 18, fontWeight: 600, padding: '4px 12px', borderRadius: 6,
                      marginRight: 8,
                    }}>{a}</span>
                  ))}
                </div>
              )}
              {customerProfile.favorite_seat && (
                <div style={{ fontSize: 18, color: 'var(--tx-text-2)' }}>
                  <strong>喜好位置:</strong> {customerProfile.favorite_seat}
                </div>
              )}
              {customerProfile.drink_preference && (
                <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginTop: 4 }}>
                  <strong>酒水偏好:</strong> {customerProfile.drink_preference}
                </div>
              )}
            </DetailSection>

            {/* 常点菜品 */}
            <DetailSection title="常点菜品">
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                {customerProfile.favorite_items.map(f => (
                  <span key={f} style={{
                    background: 'var(--tx-primary-light)', color: 'var(--tx-primary)',
                    fontSize: 18, fontWeight: 600, padding: '6px 14px', borderRadius: 6,
                  }}>{f}</span>
                ))}
                {customerProfile.favorite_items.length === 0 && (
                  <span style={{ fontSize: 18, color: 'var(--tx-text-3)' }}>暂无记录</span>
                )}
              </div>
            </DetailSection>

            {/* 历史数据 */}
            <DetailSection title="消费记录">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
                <InfoBlock label="累计到店" value={`${customerProfile.total_visits}次`} />
                <InfoBlock label="累计消费" value={`￥${(customerProfile.total_spend_fen / 100).toFixed(0)}`} />
                <InfoBlock label="上次到店" value={customerProfile.last_visit || '无记录'} />
              </div>
            </DetailSection>

            {/* 客户备注 */}
            {customerProfile.notes && (
              <DetailSection title="客户备注">
                <div style={{
                  fontSize: 18,
                  color: 'var(--tx-text-2)',
                  background: 'var(--tx-bg-3)',
                  padding: 16,
                  borderRadius: 'var(--tx-radius-sm)',
                }}>
                  {customerProfile.notes}
                </div>
              </DetailSection>
            )}
          </>
        ) : (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            height: '100%', fontSize: 22, color: 'var(--tx-text-3)',
          }}>
            无法加载客户画像
          </div>
        )}
      </div>

      {/* VIP到店弹窗 */}
      {showArrivalAlert && (() => {
        const alert = alerts.find(a => a.alert_id === showArrivalAlert);
        if (!alert) return null;
        const at = ALERT_TYPE_MAP[alert.alert_type];
        const isLoading = actionLoading === alert.alert_id;
        const matchedRes = findReservationForAlert(alert);
        return (
          <div style={{
            position: 'fixed', inset: 0,
            background: 'rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 100,
          }}>
            <div style={{
              background: '#fff',
              borderRadius: 'var(--tx-radius-lg)',
              padding: 40,
              width: 500,
              boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
              textAlign: 'center',
            }}>
              {/* VIP标识 */}
              <div style={{
                width: 80, height: 80,
                background: '#FFD700',
                borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                margin: '0 auto 20px',
                fontSize: 36, fontWeight: 800, color: '#6B4E00',
              }}>
                VIP
              </div>

              <h2 style={{ fontSize: 28, fontWeight: 800, marginBottom: 8 }}>
                {alert.customer_name} - {at.label}
              </h2>
              <div style={{
                display: 'inline-block',
                background: at.bg, color: at.color,
                fontSize: 18, fontWeight: 700, padding: '4px 16px', borderRadius: 6,
                marginBottom: 16,
              }}>
                {alert.vip_level}
              </div>

              <div style={{
                fontSize: 20, color: 'var(--tx-text-2)',
                background: 'var(--tx-bg-2)',
                padding: 16,
                borderRadius: 'var(--tx-radius-md)',
                marginBottom: 16,
                textAlign: 'left',
              }}>
                <div>{alert.message}</div>
              </div>

              {/* 预订详情（如有匹配） */}
              {matchedRes && (
                <div style={{
                  fontSize: 18, color: 'var(--tx-text-2)',
                  background: '#EBF3FF',
                  padding: 16,
                  borderRadius: 'var(--tx-radius-md)',
                  marginBottom: 16,
                  textAlign: 'left',
                }}>
                  <div style={{ fontWeight: 700, marginBottom: 6, color: 'var(--tx-info)' }}>预订信息</div>
                  <div>时间: {matchedRes.time_slot} | 人数: {matchedRes.guest_count}人 | 桌位: {matchedRes.room_or_table || '未指定'}</div>
                  {matchedRes.special_requests && (
                    <div style={{ marginTop: 4 }}>备注: {matchedRes.special_requests}</div>
                  )}
                </div>
              )}

              <div style={{ display: 'flex', gap: 12 }}>
                <button
                  onClick={() => setShowArrivalAlert(null)}
                  style={{
                    flex: 1, height: 56, borderRadius: 'var(--tx-radius-md)',
                    border: '2px solid var(--tx-border)', background: '#fff',
                    fontSize: 20, fontWeight: 700, cursor: 'pointer', color: 'var(--tx-text-2)',
                  }}
                >稍后</button>
                <button
                  disabled={isLoading}
                  onClick={() => handleAcknowledge(alert.alert_id)}
                  style={{
                    flex: 1, height: 56, borderRadius: 'var(--tx-radius-md)',
                    border: 'none', background: 'var(--tx-primary)', color: '#fff',
                    fontSize: 20, fontWeight: 700,
                    cursor: isLoading ? 'not-allowed' : 'pointer',
                    opacity: isLoading ? 0.6 : 1,
                  }}
                >{isLoading ? '处理中...' : '确认已处理'}</button>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

function VIPAlertCard({
  alert, isSelected, onSelect, onMarkArrived,
}: {
  alert: VIPAlert;
  isSelected: boolean;
  onSelect: () => void;
  onMarkArrived: () => void;
}) {
  const at = ALERT_TYPE_MAP[alert.alert_type];

  return (
    <div
      onClick={onSelect}
      style={{
        background: isSelected ? 'var(--tx-primary-light)' : '#fff',
        border: `2px solid ${isSelected ? 'var(--tx-primary)' : 'var(--tx-border)'}`,
        borderRadius: 'var(--tx-radius-md)',
        padding: 16,
        cursor: 'pointer',
        position: 'relative',
        opacity: alert.acknowledged ? 0.6 : 1,
      }}
    >
      {/* VIP + 提醒类型标记 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{
          background: '#FFD700', color: '#6B4E00',
          fontSize: 16, fontWeight: 800, padding: '2px 8px', borderRadius: 4,
        }}>{alert.vip_level}</span>
        <span style={{
          background: at.bg, color: at.color,
          fontSize: 16, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
        }}>{at.label}</span>
        {alert.acknowledged && (
          <span style={{
            background: '#E8F5F0', color: 'var(--tx-success)',
            fontSize: 16, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
          }}>已处理</span>
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{alert.customer_name}</div>
          <div style={{ fontSize: 16, color: 'var(--tx-text-2)', marginTop: 2 }}>
            {alert.message}
          </div>
        </div>

        {!alert.acknowledged && (
          <button
            onClick={e => { e.stopPropagation(); onMarkArrived(); }}
            style={{
              minWidth: 80,
              height: 48,
              borderRadius: 'var(--tx-radius-sm)',
              border: 'none',
              background: 'var(--tx-primary)',
              color: '#fff',
              fontSize: 18,
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            处理
          </button>
        )}
      </div>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <h3 style={{
        fontSize: 20, fontWeight: 700, color: 'var(--tx-text-2)',
        borderBottom: '2px solid var(--tx-border)', paddingBottom: 8, marginBottom: 12,
      }}>
        {title}
      </h3>
      {children}
    </div>
  );
}

function InfoBlock({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      background: 'var(--tx-bg-2)',
      borderRadius: 'var(--tx-radius-sm)',
      padding: 12,
    }}>
      <div style={{ fontSize: 16, color: 'var(--tx-text-3)' }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{value}</div>
    </div>
  );
}
