/**
 * 宴请接待 — VIP客户管理、到店弹窗提醒、历史偏好、宴请标记
 */
import { useState } from 'react';

type BanquetType = 'business' | 'family' | 'celebration' | 'other';

interface VIPGuest {
  id: string;
  name: string;
  phone: string;
  vipLevel: string;
  company: string;
  banquetType: BanquetType;
  banquetNote: string;
  guestCount: number;
  timeSlot: string;
  room: string;
  isArrived: boolean;
  // 偏好
  preferences: string[];
  allergies: string[];
  favoriteItems: string[];
  favoriteSeat: string;
  drinkPreference: string;
  // 历史
  totalVisits: number;
  totalSpend: number;
  lastVisit: string;
}

const BANQUET_MAP: Record<BanquetType, { label: string; color: string; bg: string }> = {
  business:    { label: '商务宴请', color: 'var(--tx-info)',    bg: '#EBF3FF' },
  family:      { label: '家庭聚餐', color: 'var(--tx-success)', bg: '#E8F5F0' },
  celebration: { label: '庆祝宴会', color: '#9333EA',           bg: '#F3E8FF' },
  other:       { label: '其他宴请', color: 'var(--tx-text-2)',  bg: 'var(--tx-bg-3)' },
};

const MOCK_VIPS: VIPGuest[] = [
  {
    id: 'V1', name: '张总', phone: '138****6789', vipLevel: '至尊VIP',
    company: '湘江集团', banquetType: 'business', banquetNote: '招待北京客户，规格要高',
    guestCount: 8, timeSlot: '11:30', room: '牡丹厅', isArrived: false,
    preferences: ['偏清淡', '爱喝茶', '注重仪式感'], allergies: ['辣椒', '花生'],
    favoriteItems: ['清蒸东星斑', '松茸炖鸡汤', '荷塘小炒', '蟹粉豆腐'],
    favoriteSeat: '主宾位左侧', drinkPreference: '茅台飞天 + 龙井茶',
    totalVisits: 42, totalSpend: 286000, lastVisit: '2026-03-15',
  },
  {
    id: 'V2', name: '王经理', phone: '136****5678', vipLevel: '黄金VIP',
    company: '星辰科技', banquetType: 'business', banquetNote: '商务谈判宴，需安静环境',
    guestCount: 10, timeSlot: '12:00', room: '芙蓉厅', isArrived: false,
    preferences: ['商务风格', '快节奏上菜'], allergies: ['海鲜（甲壳类）'],
    favoriteItems: ['极品牛排', '佛跳墙', '精品凉菜拼盘'],
    favoriteSeat: '无特殊', drinkPreference: '五粮液 + 可乐',
    totalVisits: 15, totalSpend: 123000, lastVisit: '2026-03-10',
  },
  {
    id: 'V3', name: '陈总', phone: '135****9999', vipLevel: '至尊VIP',
    company: '麓山投资', banquetType: 'celebration', banquetNote: '公司年会庆功宴，需布置横幅',
    guestCount: 12, timeSlot: '18:00', room: '国宾厅', isArrived: false,
    preferences: ['高端排场', '喜欢热闹氛围'], allergies: ['海鲜过敏'],
    favoriteItems: ['极品鲍鱼', '龙虾三吃', '澳洲和牛', '松露炒饭'],
    favoriteSeat: '中央主位', drinkPreference: '拉菲红酒 + 茅台',
    totalVisits: 28, totalSpend: 520000, lastVisit: '2026-03-22',
  },
  {
    id: 'V4', name: '赵女士', phone: '177****8765', vipLevel: '银卡会员',
    company: '', banquetType: 'family', banquetNote: '老人80大寿，准备寿桃',
    guestCount: 6, timeSlot: '17:30', room: '梅花厅', isArrived: false,
    preferences: ['口味偏甜', '需要软烂菜品'], allergies: [],
    favoriteItems: ['红烧狮子头', '桂花糯米藕', '清蒸鲈鱼'],
    favoriteSeat: '靠窗位', drinkPreference: '橙汁 + 热茶',
    totalVisits: 8, totalSpend: 15600, lastVisit: '2026-02-28',
  },
];

export function VIPAlertPage() {
  const [vips, setVips] = useState<VIPGuest[]>(MOCK_VIPS);
  const [selectedVip, setSelectedVip] = useState<VIPGuest | null>(null);
  const [showArrivalAlert, setShowArrivalAlert] = useState<string | null>(null);

  const handleMarkArrived = (id: string) => {
    setShowArrivalAlert(id);
  };

  const confirmArrival = (id: string) => {
    setVips(prev => prev.map(v => v.id === id ? { ...v, isArrived: true } : v));
    setShowArrivalAlert(null);
    // 自动选中该VIP
    const vip = vips.find(v => v.id === id);
    if (vip) setSelectedVip({ ...vip, isArrived: true });
  };

  const lunchVips = vips.filter(v => parseInt(v.timeSlot) < 17);
  const dinnerVips = vips.filter(v => parseInt(v.timeSlot) >= 17);

  return (
    <div style={{ padding: 24, height: '100vh', display: 'flex', gap: 24 }}>
      {/* 左侧：VIP列表 */}
      <div style={{ flex: '0 0 400px', display: 'flex', flexDirection: 'column' }}>
        <h1 style={{ fontSize: 32, fontWeight: 800, marginBottom: 20 }}>宴请接待</h1>

        <div style={{
          flex: 1,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}>
          {/* 午宴 */}
          {lunchVips.length > 0 && (
            <>
              <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--tx-text-2)' }}>午宴</div>
              {lunchVips.map(v => (
                <VIPCard key={v.id} vip={v} isSelected={selectedVip?.id === v.id}
                  onSelect={() => setSelectedVip(v)}
                  onMarkArrived={() => handleMarkArrived(v.id)}
                />
              ))}
            </>
          )}

          {/* 晚宴 */}
          {dinnerVips.length > 0 && (
            <>
              <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--tx-text-2)', marginTop: 8 }}>晚宴</div>
              {dinnerVips.map(v => (
                <VIPCard key={v.id} vip={v} isSelected={selectedVip?.id === v.id}
                  onSelect={() => setSelectedVip(v)}
                  onMarkArrived={() => handleMarkArrived(v.id)}
                />
              ))}
            </>
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
        {!selectedVip ? (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            height: '100%', fontSize: 22, color: 'var(--tx-text-3)',
          }}>
            选择VIP客户查看接待详情
          </div>
        ) : (
          <>
            {/* 头部 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ fontSize: 28, fontWeight: 800 }}>{selectedVip.name}</span>
                  <span style={{
                    background: '#FFD700', color: '#6B4E00',
                    fontSize: 16, fontWeight: 800, padding: '4px 12px', borderRadius: 6,
                  }}>{selectedVip.vipLevel}</span>
                  {(() => {
                    const bt = BANQUET_MAP[selectedVip.banquetType];
                    return (
                      <span style={{
                        background: bt.bg, color: bt.color,
                        fontSize: 16, fontWeight: 700, padding: '4px 12px', borderRadius: 6,
                      }}>{bt.label}</span>
                    );
                  })()}
                </div>
                {selectedVip.company && (
                  <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginTop: 4 }}>
                    {selectedVip.company}
                  </div>
                )}
              </div>
              <div style={{
                fontSize: 18, fontWeight: 700,
                color: selectedVip.isArrived ? 'var(--tx-success)' : 'var(--tx-text-3)',
                background: selectedVip.isArrived ? '#E8F5F0' : 'var(--tx-bg-3)',
                padding: '8px 16px', borderRadius: 8,
              }}>
                {selectedVip.isArrived ? '已到店' : '待到店'}
              </div>
            </div>

            {/* 宴请信息 */}
            <DetailSection title="宴请信息">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
                <InfoBlock label="时间" value={selectedVip.timeSlot} />
                <InfoBlock label="包厢" value={selectedVip.room} />
                <InfoBlock label="人数" value={`${selectedVip.guestCount}人`} />
              </div>
              {selectedVip.banquetNote && (
                <div style={{
                  marginTop: 12,
                  background: '#FEF3C7',
                  padding: 12,
                  borderRadius: 'var(--tx-radius-sm)',
                  fontSize: 18,
                  color: '#6B4E00',
                  fontWeight: 600,
                }}>
                  {selectedVip.banquetNote}
                </div>
              )}
            </DetailSection>

            {/* 客户偏好 */}
            <DetailSection title="客户偏好">
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
                {selectedVip.preferences.map(p => (
                  <span key={p} style={{
                    background: '#EBF3FF', color: 'var(--tx-info)',
                    fontSize: 18, fontWeight: 600, padding: '6px 14px', borderRadius: 6,
                  }}>{p}</span>
                ))}
              </div>
              {selectedVip.allergies.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--tx-danger)' }}>忌口: </span>
                  {selectedVip.allergies.map(a => (
                    <span key={a} style={{
                      background: '#FFF5F5', color: 'var(--tx-danger)',
                      fontSize: 18, fontWeight: 600, padding: '4px 12px', borderRadius: 6,
                      marginRight: 8,
                    }}>{a}</span>
                  ))}
                </div>
              )}
              <div style={{ fontSize: 18, color: 'var(--tx-text-2)' }}>
                <strong>喜好位置:</strong> {selectedVip.favoriteSeat}
              </div>
              <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginTop: 4 }}>
                <strong>酒水偏好:</strong> {selectedVip.drinkPreference}
              </div>
            </DetailSection>

            {/* 常点菜品 */}
            <DetailSection title="常点菜品">
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                {selectedVip.favoriteItems.map(f => (
                  <span key={f} style={{
                    background: 'var(--tx-primary-light)', color: 'var(--tx-primary)',
                    fontSize: 18, fontWeight: 600, padding: '6px 14px', borderRadius: 6,
                  }}>{f}</span>
                ))}
              </div>
            </DetailSection>

            {/* 历史数据 */}
            <DetailSection title="消费记录">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
                <InfoBlock label="累计到店" value={`${selectedVip.totalVisits}次`} />
                <InfoBlock label="累计消费" value={`￥${(selectedVip.totalSpend / 10000).toFixed(1)}万`} />
                <InfoBlock label="上次到店" value={selectedVip.lastVisit} />
              </div>
            </DetailSection>
          </>
        )}
      </div>

      {/* VIP到店弹窗 */}
      {showArrivalAlert && (() => {
        const vip = vips.find(v => v.id === showArrivalAlert);
        if (!vip) return null;
        const bt = BANQUET_MAP[vip.banquetType];
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
                {vip.name} 到店
              </h2>
              <div style={{
                display: 'inline-block',
                background: bt.bg, color: bt.color,
                fontSize: 18, fontWeight: 700, padding: '4px 16px', borderRadius: 6,
                marginBottom: 16,
              }}>
                {bt.label}
              </div>

              <div style={{
                fontSize: 20, color: 'var(--tx-text-2)',
                background: 'var(--tx-bg-2)',
                padding: 16,
                borderRadius: 'var(--tx-radius-md)',
                marginBottom: 16,
                textAlign: 'left',
              }}>
                <div>{vip.room} | {vip.guestCount}人 | {vip.timeSlot}</div>
                {vip.banquetNote && <div style={{ marginTop: 8, color: 'var(--tx-warning)', fontWeight: 600 }}>{vip.banquetNote}</div>}
                {vip.allergies.length > 0 && (
                  <div style={{ marginTop: 8, color: 'var(--tx-danger)', fontWeight: 600 }}>
                    忌口: {vip.allergies.join('、')}
                  </div>
                )}
              </div>

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
                  onClick={() => confirmArrival(vip.id)}
                  style={{
                    flex: 1, height: 56, borderRadius: 'var(--tx-radius-md)',
                    border: 'none', background: 'var(--tx-primary)', color: '#fff',
                    fontSize: 20, fontWeight: 700, cursor: 'pointer',
                  }}
                >确认到店并引导</button>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

function VIPCard({
  vip, isSelected, onSelect, onMarkArrived,
}: {
  vip: VIPGuest;
  isSelected: boolean;
  onSelect: () => void;
  onMarkArrived: () => void;
}) {
  const bt = BANQUET_MAP[vip.banquetType];

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
      }}
    >
      {/* VIP + 宴请标记 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{
          background: '#FFD700', color: '#6B4E00',
          fontSize: 16, fontWeight: 800, padding: '2px 8px', borderRadius: 4,
        }}>VIP</span>
        <span style={{
          background: bt.bg, color: bt.color,
          fontSize: 16, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
        }}>{bt.label}</span>
        {vip.isArrived && (
          <span style={{
            background: '#E8F5F0', color: 'var(--tx-success)',
            fontSize: 16, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
          }}>已到店</span>
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{vip.name}</div>
          <div style={{ fontSize: 16, color: 'var(--tx-text-2)', marginTop: 2 }}>
            {vip.timeSlot} | {vip.room} | {vip.guestCount}人
          </div>
        </div>

        {!vip.isArrived && (
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
            到店
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
