/**
 * 到店签到 — 搜索客户 → 确认到店 → 显示客户偏好 → 推荐桌台
 */
import { useState } from 'react';

interface CustomerProfile {
  id: string;
  name: string;
  phone: string;
  reservationCode: string;
  guestCount: number;
  timeSlot: string;
  roomOrTable: string;
  isVip: boolean;
  vipLevel: string;
  lastVisit: string;
  lastSpend: number;
  totalVisits: number;
  preferences: string[];    // 口味偏好
  allergies: string[];      // 忌口
  favoriteItems: string[];  // 常点菜
  notes: string;
}

// 模拟搜索结果
const MOCK_CUSTOMERS: CustomerProfile[] = [
  {
    id: 'C001', name: '张总', phone: '13812346789', reservationCode: 'YD20260327001',
    guestCount: 8, timeSlot: '11:30', roomOrTable: '牡丹厅',
    isVip: true, vipLevel: '至尊VIP',
    lastVisit: '2026-03-15', lastSpend: 6800, totalVisits: 42,
    preferences: ['偏清淡', '爱喝茶'], allergies: ['辣椒', '花生'],
    favoriteItems: ['清蒸东星斑', '松茸炖鸡汤', '荷塘小炒'],
    notes: '习惯坐主宾位左侧，喜欢安静包厢',
  },
  {
    id: 'C002', name: '李女士', phone: '13912341234', reservationCode: 'YD20260327002',
    guestCount: 4, timeSlot: '11:30', roomOrTable: 'A3桌',
    isVip: false, vipLevel: '银卡会员',
    lastVisit: '2026-03-20', lastSpend: 420, totalVisits: 8,
    preferences: ['微辣'], allergies: [],
    favoriteItems: ['酸菜鱼', '蒜蓉西兰花'],
    notes: '带小孩，需要儿童椅',
  },
  {
    id: 'C003', name: '王经理', phone: '13612345678', reservationCode: 'YD20260327003',
    guestCount: 10, timeSlot: '12:00', roomOrTable: '芙蓉厅',
    isVip: true, vipLevel: '黄金VIP',
    lastVisit: '2026-03-10', lastSpend: 8200, totalVisits: 15,
    preferences: ['商务宴请风格'], allergies: ['海鲜（甲壳类）'],
    favoriteItems: ['极品牛排', '佛跳墙', '精品凉菜拼盘'],
    notes: '多次商务接待，重视摆台和服务节奏',
  },
];

const RECOMMENDED_TABLES = [
  { id: 'T-MuDan', name: '牡丹厅', type: '大包厢', capacity: 12, status: 'reserved', minSpend: 3000 },
  { id: 'T-FuRong', name: '芙蓉厅', type: '大包厢', capacity: 12, status: 'available', minSpend: 2800 },
  { id: 'T-A3', name: 'A3桌', type: '大厅', capacity: 6, status: 'reserved', minSpend: 0 },
  { id: 'T-B1', name: 'B1桌', type: '大厅', capacity: 4, status: 'available', minSpend: 0 },
];

export function CheckInPage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<CustomerProfile[]>([]);
  const [selectedCustomer, setSelectedCustomer] = useState<CustomerProfile | null>(null);
  const [checkedIn, setCheckedIn] = useState(false);

  const handleSearch = () => {
    if (!searchQuery.trim()) return;
    const q = searchQuery.trim().toLowerCase();
    const results = MOCK_CUSTOMERS.filter(c =>
      c.phone.includes(q) ||
      c.reservationCode.toLowerCase().includes(q) ||
      c.name.includes(q)
    );
    setSearchResults(results);
    setSelectedCustomer(null);
    setCheckedIn(false);
  };

  const handleCheckIn = () => {
    setCheckedIn(true);
  };

  return (
    <div style={{ padding: 24, display: 'flex', gap: 24, height: '100vh' }}>
      {/* 左侧：搜索 + 结果 */}
      <div style={{ flex: '0 0 420px', display: 'flex', flexDirection: 'column', gap: 20 }}>
        <h1 style={{ fontSize: 32, fontWeight: 800 }}>到店签到</h1>

        {/* 搜索栏 */}
        <div style={{ display: 'flex', gap: 12 }}>
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            placeholder="手机号 / 预订号 / 姓名"
            style={{
              flex: 1,
              height: 56,
              borderRadius: 'var(--tx-radius-md)',
              border: '2px solid var(--tx-border)',
              padding: '0 20px',
              fontSize: 20,
              outline: 'none',
            }}
          />
          <button
            onClick={handleSearch}
            style={{
              minWidth: 80,
              height: 56,
              borderRadius: 'var(--tx-radius-md)',
              border: 'none',
              background: 'var(--tx-primary)',
              color: '#fff',
              fontSize: 20,
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            搜索
          </button>
        </div>

        {/* 搜索结果列表 */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch',
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
        }}>
          {searchResults.length === 0 && searchQuery && (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--tx-text-3)', fontSize: 18 }}>
              未找到匹配客户，请核实信息
            </div>
          )}
          {searchResults.map(c => (
            <button
              key={c.id}
              onClick={() => { setSelectedCustomer(c); setCheckedIn(false); }}
              style={{
                background: selectedCustomer?.id === c.id ? 'var(--tx-primary-light)' : '#fff',
                border: `2px solid ${selectedCustomer?.id === c.id ? 'var(--tx-primary)' : 'var(--tx-border)'}`,
                borderRadius: 'var(--tx-radius-md)',
                padding: 16,
                textAlign: 'left',
                cursor: 'pointer',
                minHeight: 56,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 22, fontWeight: 700 }}>{c.name}</span>
                {c.isVip && (
                  <span style={{
                    background: '#FFD700', color: '#6B4E00',
                    fontSize: 16, fontWeight: 800, padding: '2px 8px', borderRadius: 4,
                  }}>VIP</span>
                )}
              </div>
              <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginTop: 4 }}>
                {c.phone} | {c.guestCount}人 | {c.timeSlot} | {c.roomOrTable}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* 右侧：客户详情 + 偏好 */}
      <div style={{
        flex: 1,
        background: '#fff',
        borderRadius: 'var(--tx-radius-lg)',
        boxShadow: 'var(--tx-shadow-md)',
        padding: 28,
        overflowY: 'auto',
        WebkitOverflowScrolling: 'touch',
      }}>
        {!selectedCustomer ? (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            fontSize: 22,
            color: 'var(--tx-text-3)',
          }}>
            搜索并选择客户以查看详情
          </div>
        ) : (
          <>
            {/* 客户头部 */}
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'flex-start',
              marginBottom: 24,
            }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ fontSize: 28, fontWeight: 800 }}>{selectedCustomer.name}</span>
                  {selectedCustomer.isVip && (
                    <span style={{
                      background: '#FFD700', color: '#6B4E00',
                      fontSize: 18, fontWeight: 800, padding: '4px 12px', borderRadius: 6,
                    }}>{selectedCustomer.vipLevel}</span>
                  )}
                </div>
                <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginTop: 4 }}>
                  {selectedCustomer.phone} | 累计到店 {selectedCustomer.totalVisits} 次
                </div>
              </div>

              {!checkedIn ? (
                <button
                  onClick={handleCheckIn}
                  style={{
                    minWidth: 140,
                    height: 56,
                    borderRadius: 'var(--tx-radius-md)',
                    border: 'none',
                    background: 'var(--tx-primary)',
                    color: '#fff',
                    fontSize: 22,
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >
                  确认到店
                </button>
              ) : (
                <div style={{
                  minWidth: 140,
                  height: 56,
                  borderRadius: 'var(--tx-radius-md)',
                  background: '#E8F5F0',
                  color: 'var(--tx-success)',
                  fontSize: 22,
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                  已签到
                </div>
              )}
            </div>

            {/* 预订信息 */}
            <SectionTitle>预订信息</SectionTitle>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: 16,
              marginBottom: 24,
            }}>
              <InfoCell label="预订时间" value={selectedCustomer.timeSlot} />
              <InfoCell label="人数" value={`${selectedCustomer.guestCount}人`} />
              <InfoCell label="桌台/包厢" value={selectedCustomer.roomOrTable} />
              <InfoCell label="上次到店" value={selectedCustomer.lastVisit} />
              <InfoCell label="上次消费" value={`￥${selectedCustomer.lastSpend}`} />
              <InfoCell label="预订号" value={selectedCustomer.reservationCode} />
            </div>

            {/* 口味偏好 */}
            <SectionTitle>口味偏好</SectionTitle>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 24 }}>
              {selectedCustomer.preferences.map(p => (
                <Tag key={p} color="var(--tx-info)" bg="#EBF3FF">{p}</Tag>
              ))}
              {selectedCustomer.preferences.length === 0 && (
                <span style={{ fontSize: 18, color: 'var(--tx-text-3)' }}>暂无记录</span>
              )}
            </div>

            {/* 忌口过敏 */}
            {selectedCustomer.allergies.length > 0 && (
              <>
                <SectionTitle>忌口/过敏</SectionTitle>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 24 }}>
                  {selectedCustomer.allergies.map(a => (
                    <Tag key={a} color="var(--tx-danger)" bg="#FFF5F5">{a}</Tag>
                  ))}
                </div>
              </>
            )}

            {/* 常点菜品 */}
            <SectionTitle>常点菜品</SectionTitle>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 24 }}>
              {selectedCustomer.favoriteItems.map(f => (
                <Tag key={f} color="var(--tx-primary)" bg="var(--tx-primary-light)">{f}</Tag>
              ))}
            </div>

            {/* 备注 */}
            {selectedCustomer.notes && (
              <>
                <SectionTitle>客户备注</SectionTitle>
                <div style={{
                  fontSize: 18,
                  color: 'var(--tx-text-2)',
                  background: 'var(--tx-bg-3)',
                  padding: 16,
                  borderRadius: 'var(--tx-radius-sm)',
                  marginBottom: 24,
                }}>
                  {selectedCustomer.notes}
                </div>
              </>
            )}

            {/* 推荐桌台 */}
            {checkedIn && (
              <>
                <SectionTitle>推荐桌台</SectionTitle>
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                  {RECOMMENDED_TABLES
                    .filter(t => t.capacity >= selectedCustomer.guestCount)
                    .map(t => (
                      <div key={t.id} style={{
                        background: t.name === selectedCustomer.roomOrTable ? 'var(--tx-primary-light)' : 'var(--tx-bg-2)',
                        border: `2px solid ${t.name === selectedCustomer.roomOrTable ? 'var(--tx-primary)' : 'var(--tx-border)'}`,
                        borderRadius: 'var(--tx-radius-md)',
                        padding: 16,
                        minWidth: 160,
                        cursor: 'pointer',
                      }}>
                        <div style={{ fontSize: 20, fontWeight: 700 }}>{t.name}</div>
                        <div style={{ fontSize: 16, color: 'var(--tx-text-2)' }}>{t.type} | {t.capacity}人</div>
                        {t.minSpend > 0 && (
                          <div style={{ fontSize: 16, color: 'var(--tx-warning)', marginTop: 4 }}>
                            低消 ￥{t.minSpend}
                          </div>
                        )}
                        {t.name === selectedCustomer.roomOrTable && (
                          <div style={{ fontSize: 16, color: 'var(--tx-primary)', fontWeight: 700, marginTop: 4 }}>
                            已预留
                          </div>
                        )}
                      </div>
                    ))
                  }
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 style={{
      fontSize: 20,
      fontWeight: 700,
      color: 'var(--tx-text-2)',
      marginBottom: 12,
      borderBottom: '2px solid var(--tx-border)',
      paddingBottom: 8,
    }}>
      {children}
    </h2>
  );
}

function InfoCell({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      background: 'var(--tx-bg-2)',
      borderRadius: 'var(--tx-radius-sm)',
      padding: 12,
    }}>
      <div style={{ fontSize: 16, color: 'var(--tx-text-3)' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 600, marginTop: 4 }}>{value}</div>
    </div>
  );
}

function Tag({ children, color, bg }: { children: React.ReactNode; color: string; bg: string }) {
  return (
    <span style={{
      display: 'inline-block',
      fontSize: 18,
      fontWeight: 600,
      color,
      background: bg,
      padding: '6px 14px',
      borderRadius: 6,
    }}>
      {children}
    </span>
  );
}
