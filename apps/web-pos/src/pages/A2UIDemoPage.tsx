/**
 * A2UIDemoPage — A2UI 组件演示页 /a2ui-demo
 *
 * 展示 A2UI 渲染引擎支持的全部组件类型，用于开发调试和回归验证。
 */
import { A2UIRenderer, type A2UIDeclaration } from '../components/a2ui';

const DEMO_DECLARATIONS: { label: string; decl: A2UIDeclaration }[] = [
  {
    label: 'Card + Text + Button',
    decl: {
      version: '0.8',
      surface: {
        id: 'demo-card',
        type: 'card',
        props: { title: '折扣风险预警', severity: 'warning' as const },
        children: [
          { id: 'txt', type: 'text', props: { content: '订单 #1234 当前折扣率 45%，超过门店阈值 30%' } },
          { id: 'div', type: 'divider', props: {} },
          {
            id: 'actions-1',
            type: 'actions',
            props: { buttons: [
              { label: '批准', variant: 'primary', action: 'approve' },
              { label: '拒绝', variant: 'danger', action: 'reject' },
              { label: '查看详情', variant: 'ghost', action: 'view' },
            ]},
          },
        ],
      },
    },
  },
  {
    label: 'Badge + Progress + Chart',
    decl: {
      version: '0.8',
      surface: {
        id: 'demo-stats',
        type: 'card',
        props: { title: '今日门店健康度' },
        children: [
          {
            id: 'badges',
            type: 'section',
            props: { title: '状态标签' },
            children: [
              { id: 'b1', type: 'badge', props: { text: '正常运营', variant: 'success' } },
            ],
          },
          {
            id: 'progress-section',
            type: 'section',
            props: { title: '翻台率' },
            children: [
              { id: 'p1', type: 'progress', props: { value: 75, max: 100, label: '午市翻台', color: 'accent' } },
              { id: 'p2', type: 'progress', props: { value: 42, max: 100, label: '晚市翻台', color: 'warning' } },
            ],
          },
          {
            id: 'chart-section',
            type: 'section',
            props: { title: '品类分布' },
            children: [
              { id: 'c1', type: 'chart', props: { chartType: 'bar', title: '热销品类 Top 5', data: [
                { label: '湘菜', value: 85, color: '#FF6B35' },
                { label: '海鲜', value: 62, color: '#1890ff' },
                { label: '蒸菜', value: 48, color: '#10B981' },
                { label: '凉菜', value: 35, color: '#F59E0B' },
                { label: '饮品', value: 28, color: '#722ed1' },
              ]}},
            ],
          },
        ],
      },
    },
  },
  {
    label: 'List + Table + Number Chart',
    decl: {
      version: '0.8',
      surface: {
        id: 'demo-list-table',
        type: 'card',
        props: { title: '运营数据总览' },
        children: [
          {
            id: 'kpi-chart',
            type: 'chart',
            props: { chartType: 'number', data: [
              { label: '今日营收', value: 28600, color: '#FF6B35' },
              { label: '订单数', value: 124, color: '#1890ff' },
              { label: '客单价', value: 230, color: '#10B981' },
              { label: '翻台', value: 3.2, color: '#F59E0B' },
            ]},
          },
          {
            id: 'recs',
            type: 'list', props: { items: [
              { id: 'r1', title: '推荐菜品: 剁椒鱼头', subtitle: '毛利率 62% · 今日已售 28 份', leadingIcon: '🔥' },
              { id: 'r2', title: '库存预警: 小龙虾', subtitle: '库存仅剩 3 份 · 建议下架', leadingIcon: '⚠️', trailingText: '紧急' },
              { id: 'r3', title: '会员到店: 张先生', subtitle: 'VIP · 累计消费 ¥12,800 · 上次到店 3 天前', leadingIcon: '👤', actionId: 'view_member' },
            ]},
          },
          {
            id: 'table-demo',
            type: 'table', props: { columns: [
              { key: 'table', title: '桌号' },
              { key: 'status', title: '状态' },
              { key: 'revenue', title: '消费', align: 'right' as const },
              { key: 'duration', title: '时长', align: 'center' as const },
            ], rows: [
              { table: 'A02', status: '就餐中', revenue: '¥368', duration: '28min' },
              { table: 'A03', status: '超时', revenue: '¥886', duration: '95min' },
              { table: 'B01', status: 'VIP', revenue: '¥2,680', duration: '45min' },
            ]},
          },
        ],
      },
    },
  },
];

export function A2UIDemoPage() {
  return (
    <div style={{
      background: '#0B1A20', minHeight: '100vh', color: '#E0E0E0',
      fontFamily: 'Noto Sans SC, sans-serif', padding: 24,
    }}>
      <div style={{ fontSize: 18, fontWeight: 700, color: '#FF6B35', marginBottom: 20 }}>
        A2UI 组件演示 — 全部白名单组件
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: 16 }}>
        {DEMO_DECLARATIONS.map(({ label, decl }, i) => (
          <div key={i} style={{
            background: '#112B36', borderRadius: 12, padding: '16px 20px',
            border: '1px solid rgba(255,255,255,0.06)',
          }}>
            <div style={{
              fontSize: 12, fontWeight: 700, color: 'rgba(255,255,255,0.35)',
              textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 12,
            }}>
              {label}
            </div>
            <A2UIRenderer declaration={decl} />
          </div>
        ))}
      </div>
    </div>
  );
}
