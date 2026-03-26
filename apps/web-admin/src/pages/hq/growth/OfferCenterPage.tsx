/**
 * OfferCenterPage — 权益策略中心
 * 路由: /hq/growth/offers
 * 活跃/过期/草稿统计 + 券模板网格 + 创建表单 + 核销分析
 */
import { useState } from 'react';

const BG_0 = '#0B1A20';
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

type TabKey = 'overview' | 'templates' | 'create' | 'analytics';
type OfferCategory = '全部' | '新客' | '复购' | '老带新' | '储值' | '新品' | '低峰';

interface OfferTemplate {
  id: string;
  name: string;
  category: OfferCategory;
  type: '满减' | '折扣' | '赠品' | '免费' | '积分' | '储值';
  rule: string;
  marginImpact: number;
  totalIssued: number;
  totalRedeemed: number;
  avgOrderIncrease: number;
  status: '生效中' | '已过期' | '草稿';
  validDays: number;
}

interface RedemptionStat {
  date: string;
  issued: number;
  redeemed: number;
  expired: number;
  revenue: number;
}

const MOCK_TEMPLATES: OfferTemplate[] = [
  { id: 'o1', name: '新客首单立减20', category: '新客', type: '满减', rule: '满80减20', marginImpact: -3.2, totalIssued: 5200, totalRedeemed: 2340, avgOrderIncrease: 12.5, status: '生效中', validDays: 7 },
  { id: 'o2', name: '复购满100减15', category: '复购', type: '满减', rule: '满100减15', marginImpact: -2.1, totalIssued: 3800, totalRedeemed: 1560, avgOrderIncrease: 18.3, status: '生效中', validDays: 14 },
  { id: 'o3', name: '老带新邀请券¥25', category: '老带新', type: '满减', rule: '新客满60减25', marginImpact: -4.5, totalIssued: 1200, totalRedeemed: 478, avgOrderIncrease: 22.7, status: '生效中', validDays: 30 },
  { id: 'o4', name: '充500送80', category: '储值', type: '储值', rule: '充值500元赠送80元', marginImpact: -1.8, totalIssued: 860, totalRedeemed: 645, avgOrderIncrease: 35.2, status: '生效中', validDays: 365 },
  { id: 'o5', name: '新品尝鲜8折', category: '新品', type: '折扣', rule: '酸汤系列首次点单8折', marginImpact: -2.8, totalIssued: 2100, totalRedeemed: 1240, avgOrderIncrease: 8.6, status: '生效中', validDays: 14 },
  { id: 'o6', name: '低峰下午茶套餐', category: '低峰', type: '折扣', rule: '14:00-17:00全单8折', marginImpact: -3.5, totalIssued: 1500, totalRedeemed: 620, avgOrderIncrease: 0, status: '生效中', validDays: 7 },
  { id: 'o7', name: '老客回归礼包', category: '复购', type: '赠品', rule: '60天未到店赠甜品一份', marginImpact: -1.2, totalIssued: 2400, totalRedeemed: 380, avgOrderIncrease: 45.6, status: '生效中', validDays: 14 },
  { id: 'o8', name: '双12限时5折', category: '新客', type: '折扣', rule: '全场5折（限前100名）', marginImpact: -12.0, totalIssued: 4000, totalRedeemed: 3200, avgOrderIncrease: -5.2, status: '已过期', validDays: 1 },
  { id: 'o9', name: '春节储值加倍', category: '储值', type: '储值', rule: '充1000送200', marginImpact: -2.4, totalIssued: 520, totalRedeemed: 480, avgOrderIncrease: 42.1, status: '已过期', validDays: 15 },
  { id: 'o10', name: '端午特惠套餐券', category: '新品', type: '满减', rule: '端午套餐满150减30', marginImpact: -2.6, totalIssued: 0, totalRedeemed: 0, avgOrderIncrease: 0, status: '草稿', validDays: 3 },
];

const MOCK_REDEMPTION: RedemptionStat[] = [
  { date: '03-20', issued: 420, redeemed: 186, expired: 12, revenue: 23400 },
  { date: '03-21', issued: 380, redeemed: 201, expired: 18, revenue: 25600 },
  { date: '03-22', issued: 510, redeemed: 245, expired: 15, revenue: 31200 },
  { date: '03-23', issued: 460, redeemed: 218, expired: 22, revenue: 28100 },
  { date: '03-24', issued: 390, redeemed: 192, expired: 14, revenue: 24500 },
  { date: '03-25', issued: 440, redeemed: 228, expired: 20, revenue: 29300 },
  { date: '03-26', issued: 470, redeemed: 235, expired: 8, revenue: 30100 },
];

function OverviewCards() {
  const active = MOCK_TEMPLATES.filter(t => t.status === '生效中').length;
  const expired = MOCK_TEMPLATES.filter(t => t.status === '已过期').length;
  const draft = MOCK_TEMPLATES.filter(t => t.status === '草稿').length;
  const totalRedeemed = MOCK_TEMPLATES.reduce((a, t) => a + t.totalRedeemed, 0);
  const avgRedemptionRate = MOCK_TEMPLATES.filter(t => t.totalIssued > 0).reduce((a, t) => a + (t.totalRedeemed / t.totalIssued * 100), 0) / MOCK_TEMPLATES.filter(t => t.totalIssued > 0).length;

  const cards = [
    { label: '生效中', value: active, color: GREEN },
    { label: '已过期', value: expired, color: TEXT_4 },
    { label: '草稿', value: draft, color: YELLOW },
    { label: '总核销数', value: totalRedeemed.toLocaleString(), color: BRAND },
    { label: '平均核销率', value: `${avgRedemptionRate.toFixed(1)}%`, color: BLUE },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16 }}>
      {cards.map((c, i) => (
        <div key={i} style={{
          background: BG_1, borderRadius: 10, padding: '16px 18px',
          border: `1px solid ${BG_2}`,
        }}>
          <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{c.label}</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: c.color }}>{c.value}</div>
        </div>
      ))}
    </div>
  );
}

function OfferGrid({ templates, categoryFilter }: { templates: OfferTemplate[]; categoryFilter: OfferCategory }) {
  const filtered = categoryFilter === '全部' ? templates : templates.filter(t => t.category === categoryFilter);
  const statusColors: Record<string, string> = { '生效中': GREEN, '已过期': TEXT_4, '草稿': YELLOW };
  const categoryColors: Record<string, string> = { '新客': GREEN, '复购': BLUE, '老带新': PURPLE, '储值': BRAND, '新品': YELLOW, '低峰': TEXT_3 };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 12 }}>
      {filtered.map(t => {
        const redemptionRate = t.totalIssued > 0 ? (t.totalRedeemed / t.totalIssued * 100).toFixed(1) : '0';
        return (
          <div key={t.id} style={{
            background: BG_1, borderRadius: 10, padding: 16,
            border: `1px solid ${BG_2}`, cursor: 'pointer',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <div style={{ display: 'flex', gap: 6 }}>
                <span style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 4,
                  background: (categoryColors[t.category] || TEXT_4) + '22',
                  color: categoryColors[t.category] || TEXT_4, fontWeight: 600,
                }}>{t.category}</span>
                <span style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 4,
                  background: BG_2, color: TEXT_3, fontWeight: 600,
                }}>{t.type}</span>
              </div>
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 4,
                background: statusColors[t.status] + '22', color: statusColors[t.status], fontWeight: 600,
              }}>{t.status}</span>
            </div>
            <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 6 }}>{t.name}</div>
            <div style={{
              padding: '8px 12px', background: BG_2, borderRadius: 6, marginBottom: 10,
              fontSize: 13, color: BRAND, fontWeight: 600,
            }}>{t.rule}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 10, color: TEXT_4 }}>已发放</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1 }}>{t.totalIssued.toLocaleString()}</div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: TEXT_4 }}>已核销</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: GREEN }}>{t.totalRedeemed.toLocaleString()}</div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: TEXT_4 }}>核销率</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: Number(redemptionRate) > 40 ? GREEN : YELLOW }}>{redemptionRate}%</div>
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
              <span style={{ color: t.marginImpact < -5 ? RED : t.marginImpact < -3 ? YELLOW : TEXT_3 }}>
                毛利影响: {t.marginImpact}%
              </span>
              <span style={{ color: t.avgOrderIncrease > 0 ? GREEN : RED }}>
                客单提升: {t.avgOrderIncrease > 0 ? '+' : ''}{t.avgOrderIncrease}%
              </span>
              <span style={{ color: TEXT_4 }}>有效期 {t.validDays} 天</span>
            </div>
            {t.marginImpact < -5 && (
              <div style={{
                marginTop: 8, padding: '4px 8px', borderRadius: 4,
                background: RED + '11', fontSize: 10, color: RED,
                borderLeft: `3px solid ${RED}`,
              }}>毛利影响超过5%，需要审批</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function CreateOfferForm() {
  const selectStyle: React.CSSProperties = {
    background: BG_2, border: `1px solid ${BG_2}`, borderRadius: 6,
    color: TEXT_2, padding: '8px 12px', fontSize: 13, outline: 'none',
    cursor: 'pointer', width: '100%',
  };
  const inputStyle: React.CSSProperties = {
    ...selectStyle, cursor: 'text',
  };

  return (
    <div style={{ display: 'flex', gap: 16 }}>
      <div style={{
        flex: 1, background: BG_1, borderRadius: 10, padding: 20,
        border: `1px solid ${BG_2}`,
      }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>创建优惠券</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>券名称</label>
            <input style={inputStyle} placeholder="例：新客首单立减20" />
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>券类型</label>
            <select style={selectStyle}>
              <option>满减</option><option>折扣</option><option>赠品</option>
              <option>免费</option><option>积分</option><option>储值</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>使用场景</label>
            <select style={selectStyle}>
              <option>新客</option><option>复购</option><option>老带新</option>
              <option>储值</option><option>新品</option><option>低峰</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>适用品牌</label>
            <select style={selectStyle}>
              <option>全部品牌</option><option>尝在一起</option><option>最黔线</option><option>尚宫厨</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>门槛金额</label>
            <input style={inputStyle} type="number" placeholder="满X元可用" defaultValue={80} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>优惠金额</label>
            <input style={inputStyle} type="number" placeholder="减X元" defaultValue={20} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>有效天数</label>
            <input style={inputStyle} type="number" placeholder="领取后X天有效" defaultValue={7} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>发放数量</label>
            <input style={inputStyle} type="number" placeholder="总发放上限" defaultValue={5000} />
          </div>
        </div>

        {/* 毛利合规检测 */}
        <div style={{
          marginTop: 16, padding: '12px 16px', borderRadius: 8,
          background: GREEN + '11', borderLeft: `3px solid ${GREEN}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: GREEN }}>毛利合规检测通过</span>
            <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: GREEN + '22', color: GREEN }}>PASS</span>
          </div>
          <div style={{ fontSize: 11, color: TEXT_3, lineHeight: 1.6 }}>
            预估毛利影响: -3.2% | 客均消费提升: +¥12.5 | 预估ROI: 3.8x | 不违反毛利底线约束
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
          <button style={{
            padding: '10px 24px', borderRadius: 8, border: 'none',
            background: BRAND, color: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer',
          }}>创建并发布</button>
          <button style={{
            padding: '10px 24px', borderRadius: 8, border: `1px solid ${BG_2}`,
            background: 'transparent', color: TEXT_3, fontSize: 14, fontWeight: 600, cursor: 'pointer',
          }}>保存草稿</button>
        </div>
      </div>

      {/* 右侧预览 */}
      <div style={{
        width: 280, background: BG_1, borderRadius: 10, padding: 20,
        border: `1px solid ${BG_2}`, flexShrink: 0,
      }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>券面预览</h3>
        <div style={{
          background: `linear-gradient(135deg, ${BRAND}, ${BRAND}cc)`,
          borderRadius: 12, padding: 20, textAlign: 'center',
        }}>
          <div style={{ fontSize: 11, color: '#ffffffcc', marginBottom: 4 }}>尝在一起</div>
          <div style={{ fontSize: 36, fontWeight: 800, color: '#fff' }}>{'\u00A5'}20</div>
          <div style={{ fontSize: 13, color: '#ffffffcc', marginBottom: 12 }}>满80元可用</div>
          <div style={{
            borderTop: '1px dashed #ffffff44', paddingTop: 10,
            fontSize: 11, color: '#ffffff88',
          }}>
            新客首单专享 | 领取后7天有效
          </div>
        </div>
        <div style={{ marginTop: 14, fontSize: 11, color: TEXT_4, lineHeight: 1.8 }}>
          <div>适用品牌：全部品牌</div>
          <div>适用门店：全部门店</div>
          <div>每人限领：1张</div>
          <div>不可叠加使用</div>
        </div>
      </div>
    </div>
  );
}

function RedemptionAnalytics({ data }: { data: RedemptionStat[] }) {
  const maxIssued = Math.max(...data.map(d => d.issued));
  const barH = 140;

  return (
    <div>
      {/* 趋势图 */}
      <div style={{
        background: BG_1, borderRadius: 10, padding: 18,
        border: `1px solid ${BG_2}`, marginBottom: 16,
      }}>
        <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>核销趋势（近7天）</h3>
        <div style={{ display: 'flex', gap: 8, marginBottom: 10, fontSize: 11 }}>
          <span style={{ color: BRAND }}>--- 发放量</span>
          <span style={{ color: GREEN }}>--- 核销量</span>
          <span style={{ color: RED }}>--- 过期量</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', height: barH, gap: 8 }}>
          {data.map((d, i) => (
            <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <div style={{ display: 'flex', gap: 2, alignItems: 'flex-end', height: barH - 30 }}>
                <div style={{
                  width: 16, height: (d.issued / maxIssued) * (barH - 40),
                  background: BRAND, borderRadius: '3px 3px 0 0',
                }} />
                <div style={{
                  width: 16, height: (d.redeemed / maxIssued) * (barH - 40),
                  background: GREEN, borderRadius: '3px 3px 0 0',
                }} />
                <div style={{
                  width: 16, height: Math.max(4, (d.expired / maxIssued) * (barH - 40)),
                  background: RED, borderRadius: '3px 3px 0 0',
                }} />
              </div>
              <span style={{ fontSize: 10, color: TEXT_4 }}>{d.date}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 明细表 */}
      <div style={{
        background: BG_1, borderRadius: 10, padding: 16,
        border: `1px solid ${BG_2}`,
      }}>
        <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>核销明细</h3>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
              {['日期', '发放', '核销', '过期', '核销率', '贡献营收'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map(d => {
              const rate = (d.redeemed / d.issued * 100).toFixed(1);
              return (
                <tr key={d.date} style={{ borderBottom: `1px solid ${BG_2}` }}>
                  <td style={{ padding: '10px', color: TEXT_2 }}>{d.date}</td>
                  <td style={{ padding: '10px', color: TEXT_1 }}>{d.issued}</td>
                  <td style={{ padding: '10px', color: GREEN, fontWeight: 600 }}>{d.redeemed}</td>
                  <td style={{ padding: '10px', color: RED }}>{d.expired}</td>
                  <td style={{ padding: '10px', color: Number(rate) > 45 ? GREEN : YELLOW, fontWeight: 600 }}>{rate}%</td>
                  <td style={{ padding: '10px', color: GREEN, fontWeight: 600 }}>{'\u00A5'}{(d.revenue / 10000).toFixed(1)}万</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function OfferCenterPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const [categoryFilter, setCategoryFilter] = useState<OfferCategory>('全部');

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'overview', label: '券模板总览' },
    { key: 'templates', label: '券模板管理' },
    { key: 'create', label: '创建优惠券' },
    { key: 'analytics', label: '核销分析' },
  ];

  const categories: OfferCategory[] = ['全部', '新客', '复购', '老带新', '储值', '新品', '低峰'];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700 }}>权益策略中心</h2>

      <OverviewCards />

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
            padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
            background: activeTab === t.key ? BRAND : BG_1,
            color: activeTab === t.key ? '#fff' : TEXT_3,
            fontSize: 13, fontWeight: 600,
          }}>{t.label}</button>
        ))}
      </div>

      {/* Category filter */}
      {(activeTab === 'overview' || activeTab === 'templates') && (
        <div style={{ display: 'flex', gap: 4, marginBottom: 14 }}>
          {categories.map(c => (
            <button key={c} onClick={() => setCategoryFilter(c)} style={{
              padding: '4px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: categoryFilter === c ? BLUE : BG_2,
              color: categoryFilter === c ? '#fff' : TEXT_3,
              fontSize: 11, fontWeight: 600,
            }}>{c}</button>
          ))}
        </div>
      )}

      {(activeTab === 'overview' || activeTab === 'templates') && (
        <OfferGrid templates={MOCK_TEMPLATES} categoryFilter={categoryFilter} />
      )}
      {activeTab === 'create' && <CreateOfferForm />}
      {activeTab === 'analytics' && <RedemptionAnalytics data={MOCK_REDEMPTION} />}
    </div>
  );
}
