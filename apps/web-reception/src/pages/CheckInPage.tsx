/**
 * 到店签到 — 搜索客户 → 确认到店 → 显示客户偏好 → 推荐桌台
 */
import { useState, useCallback } from 'react';
import {
  searchCustomer,
  checkInCustomer,
  type CustomerProfile,
} from '../api/memberDepthApi';
import {
  recommendTable,
} from '../api/tablesApi';
import {
  findByCode,
} from '../api/reservationApi';

const STORE_ID = import.meta.env.VITE_STORE_ID || '';

interface RecommendedTable {
  table_id: string;
  table_name: string;
  zone: string;
  score: number;
  reason: string;
}

export function CheckInPage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<CustomerProfile[]>([]);
  const [selectedCustomer, setSelectedCustomer] = useState<CustomerProfile | null>(null);
  const [checkedIn, setCheckedIn] = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const [checkInLoading, setCheckInLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recommendedTables, setRecommendedTables] = useState<RecommendedTable[]>([]);
  const [tablesLoading, setTablesLoading] = useState(false);
  // Track reservation info found via code lookup
  const [reservationInfo, setReservationInfo] = useState<{
    reservation_id: string;
    time_slot: string;
    guest_count: number;
    room_or_table: string;
    reservation_code: string;
  } | null>(null);

  const handleSearch = useCallback(async () => {
    const q = searchQuery.trim();
    if (!q) return;
    try {
      setSearchLoading(true);
      setError(null);
      setSelectedCustomer(null);
      setCheckedIn(false);
      setReservationInfo(null);

      // Search for customers by keyword (phone/name)
      const result = await searchCustomer(q);
      setSearchResults(result.items);

      // If it looks like a reservation code, also try to look it up
      if (q.toUpperCase().startsWith('YD') || q.length >= 10) {
        try {
          const reservation = await findByCode(q);
          // If we found a reservation, store its info for display
          setReservationInfo({
            reservation_id: reservation.reservation_id,
            time_slot: reservation.time_slot,
            guest_count: reservation.guest_count,
            room_or_table: reservation.room_or_table,
            reservation_code: reservation.reservation_code,
          });
        } catch {
          // Not a valid reservation code, ignore
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '搜索失败，请重试');
      setSearchResults([]);
    } finally {
      setSearchLoading(false);
    }
  }, [searchQuery]);

  const handleCheckIn = useCallback(async () => {
    if (!selectedCustomer) return;
    try {
      setCheckInLoading(true);
      setError(null);
      await checkInCustomer(
        STORE_ID,
        selectedCustomer.member_id,
        reservationInfo?.reservation_id,
      );
      setCheckedIn(true);

      // After check-in, fetch recommended tables
      setTablesLoading(true);
      try {
        const guestCount = reservationInfo?.guest_count || 2;
        const result = await recommendTable(STORE_ID, guestCount, selectedCustomer.preferences);
        setRecommendedTables(result.items);
      } catch {
        // Non-critical: table recommendation failed, don't block flow
        setRecommendedTables([]);
      } finally {
        setTablesLoading(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '签到失败，请重试');
    } finally {
      setCheckInLoading(false);
    }
  }, [selectedCustomer, reservationInfo]);

  return (
    <div style={{ padding: 24, display: 'flex', gap: 24, height: '100vh' }}>
      {/* 左侧：搜索 + 结果 */}
      <div style={{ flex: '0 0 420px', display: 'flex', flexDirection: 'column', gap: 20 }}>
        <h1 style={{ fontSize: 32, fontWeight: 800 }}>到店签到</h1>

        {/* 错误提示 */}
        {error && (
          <div style={{
            background: '#FFF5F5', border: '1px solid var(--tx-danger)', borderRadius: 'var(--tx-radius-sm)',
            padding: '12px 20px', color: 'var(--tx-danger)', fontSize: 18,
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <span>{error}</span>
            <button onClick={() => setError(null)} style={{
              border: 'none', background: 'transparent', color: 'var(--tx-danger)',
              fontSize: 18, cursor: 'pointer', fontWeight: 700,
            }}>关闭</button>
          </div>
        )}

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
            disabled={searchLoading}
            style={{
              minWidth: 80,
              height: 56,
              borderRadius: 'var(--tx-radius-md)',
              border: 'none',
              background: 'var(--tx-primary)',
              color: '#fff',
              fontSize: 20,
              fontWeight: 700,
              cursor: searchLoading ? 'not-allowed' : 'pointer',
              opacity: searchLoading ? 0.6 : 1,
            }}
          >
            {searchLoading ? '...' : '搜索'}
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
          {searchLoading && (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--tx-text-3)', fontSize: 18 }}>
              搜索中...
            </div>
          )}
          {!searchLoading && searchResults.length === 0 && searchQuery && (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--tx-text-3)', fontSize: 18 }}>
              未找到匹配客户，请核实信息
            </div>
          )}
          {searchResults.map(c => (
            <button
              key={c.member_id}
              onClick={() => { setSelectedCustomer(c); setCheckedIn(false); setRecommendedTables([]); }}
              style={{
                background: selectedCustomer?.member_id === c.member_id ? 'var(--tx-primary-light)' : '#fff',
                border: `2px solid ${selectedCustomer?.member_id === c.member_id ? 'var(--tx-primary)' : 'var(--tx-border)'}`,
                borderRadius: 'var(--tx-radius-md)',
                padding: 16,
                textAlign: 'left',
                cursor: 'pointer',
                minHeight: 56,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 22, fontWeight: 700 }}>{c.name}</span>
                {c.is_vip && (
                  <span style={{
                    background: '#FFD700', color: '#6B4E00',
                    fontSize: 16, fontWeight: 800, padding: '2px 8px', borderRadius: 4,
                  }}>VIP</span>
                )}
                {c.vip_level && (
                  <span style={{ fontSize: 16, color: 'var(--tx-text-3)' }}>{c.vip_level}</span>
                )}
              </div>
              <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginTop: 4 }}>
                {c.phone} | 累计{c.total_visits}次 | {c.favorite_seat || '无常坐位'}
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
                  {selectedCustomer.is_vip && (
                    <span style={{
                      background: '#FFD700', color: '#6B4E00',
                      fontSize: 18, fontWeight: 800, padding: '4px 12px', borderRadius: 6,
                    }}>{selectedCustomer.vip_level}</span>
                  )}
                </div>
                <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginTop: 4 }}>
                  {selectedCustomer.phone} | 累计到店 {selectedCustomer.total_visits} 次
                </div>
              </div>

              {!checkedIn ? (
                <button
                  onClick={handleCheckIn}
                  disabled={checkInLoading}
                  style={{
                    minWidth: 140,
                    height: 56,
                    borderRadius: 'var(--tx-radius-md)',
                    border: 'none',
                    background: 'var(--tx-primary)',
                    color: '#fff',
                    fontSize: 22,
                    fontWeight: 700,
                    cursor: checkInLoading ? 'not-allowed' : 'pointer',
                    opacity: checkInLoading ? 0.6 : 1,
                  }}
                >
                  {checkInLoading ? '签到中...' : '确认到店'}
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
              <InfoCell label="预订时间" value={reservationInfo?.time_slot || '-'} />
              <InfoCell label="人数" value={reservationInfo ? `${reservationInfo.guest_count}人` : '-'} />
              <InfoCell label="桌台/包厢" value={reservationInfo?.room_or_table || '-'} />
              <InfoCell label="上次到店" value={selectedCustomer.last_visit || '-'} />
              <InfoCell label="上次消费" value={selectedCustomer.last_spend_fen ? `￥${(selectedCustomer.last_spend_fen / 100).toFixed(0)}` : '-'} />
              <InfoCell label="预订号" value={reservationInfo?.reservation_code || '-'} />
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
              {selectedCustomer.favorite_items.map(f => (
                <Tag key={f} color="var(--tx-primary)" bg="var(--tx-primary-light)">{f}</Tag>
              ))}
              {selectedCustomer.favorite_items.length === 0 && (
                <span style={{ fontSize: 18, color: 'var(--tx-text-3)' }}>暂无记录</span>
              )}
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
                {tablesLoading ? (
                  <div style={{ fontSize: 18, color: 'var(--tx-text-3)' }}>加载推荐桌台中...</div>
                ) : recommendedTables.length > 0 ? (
                  <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                    {recommendedTables.map(t => {
                      const isReserved = reservationInfo != null && t.table_name === reservationInfo.room_or_table;
                      return (
                        <div key={t.table_id} style={{
                          background: isReserved ? 'var(--tx-primary-light)' : 'var(--tx-bg-2)',
                          border: `2px solid ${isReserved ? 'var(--tx-primary)' : 'var(--tx-border)'}`,
                          borderRadius: 'var(--tx-radius-md)',
                          padding: 16,
                          minWidth: 160,
                          cursor: 'pointer',
                        }}>
                          <div style={{ fontSize: 20, fontWeight: 700 }}>{t.table_name}</div>
                          <div style={{ fontSize: 16, color: 'var(--tx-text-2)' }}>{t.zone}</div>
                          {t.reason && (
                            <div style={{ fontSize: 16, color: 'var(--tx-primary)', marginTop: 4 }}>
                              {t.reason}
                            </div>
                          )}
                          {isReserved && (
                            <div style={{ fontSize: 16, color: 'var(--tx-primary)', fontWeight: 700, marginTop: 4 }}>
                              已预留
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div style={{ fontSize: 18, color: 'var(--tx-text-3)' }}>暂无推荐桌台</div>
                )}
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
