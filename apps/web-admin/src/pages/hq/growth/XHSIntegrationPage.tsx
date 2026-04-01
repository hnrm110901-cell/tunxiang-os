/**
 * XHSIntegrationPage — 小红书对接管理
 * 路由: /hq/growth/xhs
 * POI 绑定 + 团购券核销 + 笔记监控
 */
import { useState } from 'react';

const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const XHS_RED = '#FF2442';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

type TabKey = 'poi' | 'verification' | 'notes';

interface POIBinding {
  id: string;
  storeName: string;
  storeId: string;
  xhsPoiId: string;
  xhsPoiName: string;
  status: '已绑定' | '待审核' | '未绑定';
  syncedAt?: string;
  couponCount: number;
}

interface CouponVerification {
  id: string;
  couponCode: string;
  storeName: string;
  customerPhone: string;
  amount: string;
  productName: string;
  status: '已核销' | '待核销' | '已退款';
  verifiedAt: string;
  operatorName: string;
}

interface XHSNote {
  id: string;
  title: string;
  author: string;
  likes: number;
  comments: number;
  mentions: string;
  sentiment: '正面' | '中性' | '负面';
  publishedAt: string;
}

interface KPI {
  label: string;
  value: string;
  sub: string;
  trend?: 'up' | 'down';
}

const MOCK_KPIS: KPI[] = [
  { label: '绑定门店', value: '12/15', sub: '80% 覆盖率', trend: 'up' },
  { label: '本月核销', value: '347', sub: '核销金额 ¥4.2万', trend: 'up' },
  { label: '相关笔记', value: '86', sub: '本月新增 23 篇', trend: 'up' },
  { label: '到店转化率', value: '42.5%', sub: '较上月 +6.2%', trend: 'up' },
];

const MOCK_POI: POIBinding[] = [
  { id: 'p1', storeName: '长沙·芙蓉广场店', storeId: 'store-001', xhsPoiId: 'xhs-poi-001', xhsPoiName: '徐记海鲜(芙蓉广场店)', status: '已绑定', syncedAt: '2026-04-01 08:00', couponCount: 156 },
  { id: 'p2', storeName: '长沙·五一路店', storeId: 'store-002', xhsPoiId: 'xhs-poi-002', xhsPoiName: '徐记海鲜(五一路店)', status: '已绑定', syncedAt: '2026-04-01 08:00', couponCount: 98 },
  { id: 'p3', storeName: '长沙·梅溪湖店', storeId: 'store-003', xhsPoiId: '', xhsPoiName: '', status: '待审核', couponCount: 0 },
  { id: 'p4', storeName: '北京·国贸店', storeId: 'store-004', xhsPoiId: '', xhsPoiName: '', status: '未绑定', couponCount: 0 },
];

const MOCK_VERIFICATIONS: CouponVerification[] = [
  { id: 'v1', couponCode: 'XHS20260401001', storeName: '芙蓉广场店', customerPhone: '138****8001', amount: '¥128', productName: '双人海鲜套餐', status: '已核销', verifiedAt: '2026-04-01 12:35', operatorName: '收银-小王' },
  { id: 'v2', couponCode: 'XHS20260401002', storeName: '五一路店', customerPhone: '139****9002', amount: '¥98', productName: '龙虾套餐', status: '已核销', verifiedAt: '2026-04-01 11:20', operatorName: '收银-小李' },
  { id: 'v3', couponCode: 'XHS20260401003', storeName: '芙蓉广场店', customerPhone: '137****7003', amount: '¥168', productName: '四人海鲜套餐', status: '待核销', verifiedAt: '-', operatorName: '-' },
  { id: 'v4', couponCode: 'XHS20260331005', storeName: '芙蓉广场店', customerPhone: '136****6004', amount: '¥128', productName: '双人海鲜套餐', status: '已退款', verifiedAt: '2026-03-31 18:40', operatorName: '店长-张' },
];

const MOCK_NOTES: XHSNote[] = [
  { id: 'n1', title: '长沙必吃海鲜！这家的清蒸石斑绝了', author: '美食探店小A', likes: 2340, comments: 89, mentions: '芙蓉广场店', sentiment: '正面', publishedAt: '2026-04-01' },
  { id: 'n2', title: '人均不到100的海鲜大餐推荐', author: '吃货日记', likes: 1856, comments: 67, mentions: '五一路店', sentiment: '正面', publishedAt: '2026-03-30' },
  { id: 'n3', title: '长沙海鲜店对比测评', author: '长沙探店达人', likes: 892, comments: 45, mentions: '芙蓉广场店', sentiment: '中性', publishedAt: '2026-03-29' },
  { id: 'n4', title: '排队一小时体验一般…', author: '随便吃吃', likes: 456, comments: 123, mentions: '五一路店', sentiment: '负面', publishedAt: '2026-03-28' },
];

export function XHSIntegrationPage() {
  const [tab, setTab] = useState<TabKey>('poi');

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'poi', label: 'POI 绑定' },
    { key: 'verification', label: '团购券核销' },
    { key: 'notes', label: '笔记监控' },
  ];

  return (
    <div style={{ padding: 24, background: BG_1, minHeight: '100vh', color: TEXT_1, fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif' }}>
      {/* Header */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 36, height: 36, borderRadius: 8, background: XHS_RED, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18, fontWeight: 700 }}>书</div>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>小红书对接</h1>
            <div style={{ fontSize: 13, color: TEXT_3, marginTop: 2 }}>门店 POI · 团购核销 · 内容监控</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={{ background: 'rgba(255,255,255,0.06)', color: TEXT_2, border: 'none', borderRadius: 6, padding: '8px 16px', fontSize: 13, cursor: 'pointer' }}>同步配置</button>
          <button style={{ background: XHS_RED, color: '#fff', border: 'none', borderRadius: 6, padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>+ 绑定新门店</button>
        </div>
      </div>

      {/* KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {MOCK_KPIS.map(k => (
          <div key={k.label} style={{ background: BG_2, borderRadius: 8, padding: 16 }}>
            <div style={{ fontSize: 13, color: TEXT_3 }}>{k.label}</div>
            <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{k.value}</div>
            <div style={{ fontSize: 12, color: k.trend === 'up' ? GREEN : RED, marginTop: 4 }}>↑ {k.sub}</div>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, background: BG_2, borderRadius: 8, padding: 4, width: 'fit-content' }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            style={{
              padding: '8px 20px', fontSize: 14, fontWeight: tab === t.key ? 600 : 400, cursor: 'pointer',
              border: 'none', borderRadius: 6,
              background: tab === t.key ? XHS_RED : 'transparent',
              color: tab === t.key ? '#fff' : TEXT_3,
            }}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'poi' && <POITab />}
      {tab === 'verification' && <VerificationTab />}
      {tab === 'notes' && <NotesTab />}
    </div>
  );
}

function POITab() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
      {MOCK_POI.map(p => (
        <div key={p.id} style={{ background: BG_2, borderRadius: 12, padding: 20, borderLeft: `3px solid ${p.status === '已绑定' ? GREEN : p.status === '待审核' ? YELLOW : TEXT_4}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 16, fontWeight: 600 }}>{p.storeName}</div>
              <div style={{ fontSize: 12, color: TEXT_4, marginTop: 2 }}>ID: {p.storeId}</div>
            </div>
            <span style={{
              padding: '2px 10px', borderRadius: 12, fontSize: 12, fontWeight: 500,
              background: p.status === '已绑定' ? 'rgba(82,196,26,0.15)' : p.status === '待审核' ? 'rgba(250,173,20,0.15)' : 'rgba(255,255,255,0.06)',
              color: p.status === '已绑定' ? GREEN : p.status === '待审核' ? YELLOW : TEXT_4,
            }}>{p.status}</span>
          </div>
          {p.status === '已绑定' && (
            <>
              <div style={{ fontSize: 13, color: TEXT_2, marginBottom: 4 }}>
                <span style={{ color: XHS_RED }}>小红书:</span> {p.xhsPoiName}
              </div>
              <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 8 }}>同步时间: {p.syncedAt}</div>
              <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: 12, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                <span style={{ fontSize: 13 }}>累计核销 <span style={{ color: BRAND, fontWeight: 600 }}>{p.couponCount}</span> 张</span>
                <span style={{ fontSize: 13, color: BLUE, cursor: 'pointer' }}>查看详情</span>
              </div>
            </>
          )}
          {p.status === '未绑定' && (
            <button style={{ marginTop: 8, width: '100%', padding: '8px 0', background: 'rgba(255,36,66,0.1)', color: XHS_RED, border: `1px solid ${XHS_RED}`, borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>绑定小红书 POI</button>
          )}
          {p.status === '待审核' && (
            <div style={{ marginTop: 8, padding: 8, background: 'rgba(250,173,20,0.06)', borderRadius: 6, fontSize: 12, color: YELLOW }}>已提交绑定申请，等待小红书平台审核...</div>
          )}
        </div>
      ))}
    </div>
  );
}

function VerificationTab() {
  return (
    <div style={{ background: BG_2, borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ padding: '12px 16px', display: 'flex', gap: 8, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <input placeholder="搜索券码 / 手机号" style={{ flex: 1, padding: '6px 12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, color: TEXT_1, fontSize: 13, outline: 'none' }} />
        {['全部', '已核销', '待核销', '已退款'].map(f => (
          <button key={f} style={{ padding: '6px 12px', background: f === '全部' ? 'rgba(255,36,66,0.15)' : 'transparent', color: f === '全部' ? XHS_RED : TEXT_3, border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>{f}</button>
        ))}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ background: 'rgba(255,255,255,0.04)' }}>
            {['券码', '门店', '顾客', '商品', '金额', '状态', '核销时间', '操作员'].map(h => (
              <th key={h} style={{ padding: '12px 16px', textAlign: 'left', color: TEXT_3, fontWeight: 500, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {MOCK_VERIFICATIONS.map(v => (
            <tr key={v.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <td style={{ padding: '14px 16px', fontFamily: 'monospace', fontSize: 12 }}>{v.couponCode}</td>
              <td style={{ padding: '14px 16px' }}>{v.storeName}</td>
              <td style={{ padding: '14px 16px', color: TEXT_2 }}>{v.customerPhone}</td>
              <td style={{ padding: '14px 16px' }}>{v.productName}</td>
              <td style={{ padding: '14px 16px', fontWeight: 600, color: BRAND }}>{v.amount}</td>
              <td style={{ padding: '14px 16px' }}>
                <span style={{
                  padding: '2px 10px', borderRadius: 12, fontSize: 12,
                  background: v.status === '已核销' ? 'rgba(82,196,26,0.15)' : v.status === '待核销' ? 'rgba(24,144,255,0.15)' : 'rgba(255,77,79,0.15)',
                  color: v.status === '已核销' ? GREEN : v.status === '待核销' ? BLUE : RED,
                }}>{v.status}</span>
              </td>
              <td style={{ padding: '14px 16px', color: TEXT_3, fontSize: 13 }}>{v.verifiedAt}</td>
              <td style={{ padding: '14px 16px', color: TEXT_3 }}>{v.operatorName}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NotesTab() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 16 }}>
      {MOCK_NOTES.map(n => (
        <div key={n.id} style={{ background: BG_2, borderRadius: 12, padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, flex: 1, lineHeight: 1.4 }}>{n.title}</h3>
            <span style={{
              marginLeft: 8, padding: '2px 8px', borderRadius: 10, fontSize: 11, flexShrink: 0,
              background: n.sentiment === '正面' ? 'rgba(82,196,26,0.15)' : n.sentiment === '负面' ? 'rgba(255,77,79,0.15)' : 'rgba(255,255,255,0.06)',
              color: n.sentiment === '正面' ? GREEN : n.sentiment === '负面' ? RED : TEXT_3,
            }}>{n.sentiment}</span>
          </div>
          <div style={{ fontSize: 13, color: TEXT_3, marginBottom: 8 }}>@{n.author} · {n.publishedAt}</div>
          <div style={{ fontSize: 13, color: TEXT_2, marginBottom: 12 }}>提及: <span style={{ color: XHS_RED }}>{n.mentions}</span></div>
          <div style={{ display: 'flex', gap: 16, fontSize: 13, color: TEXT_3 }}>
            <span>♥ {n.likes}</span>
            <span>💬 {n.comments}</span>
            <span style={{ marginLeft: 'auto', color: BLUE, cursor: 'pointer' }}>查看原文</span>
          </div>
        </div>
      ))}
    </div>
  );
}
