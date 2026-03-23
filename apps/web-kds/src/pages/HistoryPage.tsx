/**
 * KDS 出餐历史 — 按时段分组的已完成票据列表
 * 大字号设计，厨房友好
 */

/* ---------- Types ---------- */
interface HistoryTicket {
  id: string;
  tableNo: string;
  items: string[];
  elapsed: number; // 分钟
  chef: string;
  completedAt: string;
}

/* ---------- Mock Data ---------- */
const mockHistory: Record<string, HistoryTicket[]> = {
  '午餐 11:00-14:00': [
    { id: '1', tableNo: 'A01', items: ['剁椒鱼头', '小炒肉', '米饭x3'], elapsed: 12, chef: '王师傅', completedAt: '11:42' },
    { id: '2', tableNo: 'A03', items: ['口味虾', '凉拌黄瓜'], elapsed: 18, chef: '李师傅', completedAt: '11:55' },
    { id: '3', tableNo: 'B01', items: ['红烧肉', '蒜蓉西兰花', '米饭x4'], elapsed: 15, chef: '王师傅', completedAt: '12:10' },
    { id: '4', tableNo: 'A02', items: ['酸菜鱼', '辣椒炒肉'], elapsed: 22, chef: '张师傅', completedAt: '12:28' },
    { id: '5', tableNo: 'B03', items: ['外婆鸡', '米饭x2'], elapsed: 14, chef: '李师傅', completedAt: '12:45' },
    { id: '6', tableNo: 'A05', items: ['剁椒鱼头', '口味虾', '凉拌黄瓜', '米饭x6'], elapsed: 25, chef: '王师傅', completedAt: '13:05' },
    { id: '7', tableNo: 'B02', items: ['小炒肉', '蒜蓉西兰花'], elapsed: 10, chef: '张师傅', completedAt: '13:22' },
  ],
  '下午茶 14:00-17:00': [
    { id: '8', tableNo: 'A01', items: ['甜品拼盘', '奶茶x2'], elapsed: 5, chef: '刘师傅', completedAt: '14:30' },
    { id: '9', tableNo: 'B01', items: ['水果沙拉'], elapsed: 3, chef: '刘师傅', completedAt: '15:10' },
  ],
  '晚餐 17:00-21:30': [
    { id: '10', tableNo: 'A03', items: ['剁椒鱼头', '小炒肉', '红烧肉'], elapsed: 20, chef: '王师傅', completedAt: '17:45' },
    { id: '11', tableNo: 'B02', items: ['口味虾x2', '米饭x4'], elapsed: 16, chef: '李师傅', completedAt: '18:10' },
    { id: '12', tableNo: 'A01', items: ['酸菜鱼', '外婆鸡', '蒜蓉西兰花'], elapsed: 19, chef: '张师傅', completedAt: '18:35' },
  ],
};

/* ---------- Component ---------- */
export function HistoryPage() {
  const timeColor = (elapsed: number): string =>
    elapsed >= 25 ? '#ff4d4f' : elapsed >= 15 ? '#faad14' : '#52c41a';

  return (
    <div style={{
      background: '#0B1A20', minHeight: '100vh', color: '#E0E0E0',
      fontFamily: 'Noto Sans SC, sans-serif', padding: 16,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h1 style={{ margin: 0, fontSize: 28, color: '#fff' }}>出餐历史</h1>
        <span style={{ color: '#666', fontSize: 16 }}>今日已完成 {Object.values(mockHistory).flat().length} 单</span>
      </div>

      {/* Grouped by period */}
      {Object.entries(mockHistory).map(([period, tickets]) => (
        <div key={period} style={{ marginBottom: 20 }}>
          <div style={{
            fontSize: 18, fontWeight: 'bold', color: '#1890ff',
            padding: '8px 0', borderBottom: '2px solid #1890ff', marginBottom: 10,
          }}>
            {period}
            <span style={{ fontSize: 14, color: '#666', marginLeft: 12 }}>{tickets.length} 单</span>
          </div>

          {tickets.map(t => (
            <div key={t.id} style={{
              display: 'flex', alignItems: 'center', gap: 16,
              padding: '12px 16px', background: '#112B36', borderRadius: 8, marginBottom: 6,
            }}>
              {/* Table */}
              <div style={{ fontSize: 24, fontWeight: 'bold', color: '#fff', minWidth: 60 }}>
                {t.tableNo}
              </div>

              {/* Items */}
              <div style={{ flex: 1, fontSize: 18, lineHeight: 1.5 }}>
                {t.items.join(' / ')}
              </div>

              {/* Elapsed */}
              <div style={{
                fontSize: 22, fontWeight: 'bold', color: timeColor(t.elapsed),
                fontFamily: 'JetBrains Mono, monospace', minWidth: 60, textAlign: 'right',
              }}>
                {t.elapsed}'
              </div>

              {/* Chef */}
              <div style={{ fontSize: 16, color: '#8899A6', minWidth: 70, textAlign: 'right' }}>
                {t.chef}
              </div>

              {/* Time */}
              <div style={{ fontSize: 14, color: '#555', minWidth: 50, textAlign: 'right' }}>
                {t.completedAt}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
