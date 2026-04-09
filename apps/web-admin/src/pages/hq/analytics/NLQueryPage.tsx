/**
 * NLQueryPage — AI 自然语言问数
 * Sprint 3: 经营分析师 AI 工作台
 */
import { useState, useEffect, useRef } from 'react';
import {
  ConfigProvider, Input, Button, Tag, Table, Tabs, Typography, Row, Col,
} from 'antd';
import type { TabsProps } from 'antd';
import { SendOutlined, AudioOutlined } from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';

const { TextArea } = Input;
const { Text } = Typography;

// ---- 类型 ----
interface ChatMsg {
  role: 'user' | 'ai';
  content: string;
  table?: { store: string; today: number; yesterday: number; ratio: string }[];
}

interface StoreRevRow {
  key: number;
  store: string;
  today: number;
  yesterday: number;
  ratio: string;
}

// ---- Mock 数据 ----
const QUICK_QUESTIONS = [
  '今天各门店营业额',
  '本周哪个菜品点单最多',
  '上个月会员复购率',
  '毛利率低于30%的菜品',
];

const MOCK_MESSAGES: ChatMsg[] = [
  { role: 'user', content: '今天各门店营业额对比' },
  {
    role: 'ai',
    content: '以下是今日(2026-04-07)各门店营业额汇总：',
    table: [
      { store: '南山旗舰店', today: 28640, yesterday: 25300, ratio: '+13.3%' },
      { store: '福田中心店', today: 19820, yesterday: 21100, ratio: '-6.1%' },
      { store: '罗湖商圈店', today: 15430, yesterday: 14800, ratio: '+4.3%' },
    ],
  },
];

const MOCK_TABLE_DATA: StoreRevRow[] = [
  { key: 1, store: '南山旗舰店', today: 28640, yesterday: 25300, ratio: '+13.3%' },
  { key: 2, store: '福田中心店', today: 19820, yesterday: 21100, ratio: '-6.1%' },
  { key: 3, store: '罗湖商圈店', today: 15430, yesterday: 14800, ratio: '+4.3%' },
  { key: 4, store: '龙华新城店', today: 12300, yesterday: 11800, ratio: '+4.2%' },
  { key: 5, store: '宝安广场店', today: 9870, yesterday: 10200, ratio: '-3.2%' },
];

const MOCK_SQL = `SELECT
  s.store_name,
  SUM(CASE WHEN DATE(o.paid_at) = CURRENT_DATE THEN o.total_fen ELSE 0 END) / 100.0 AS today_revenue,
  SUM(CASE WHEN DATE(o.paid_at) = CURRENT_DATE - 1 THEN o.total_fen ELSE 0 END) / 100.0 AS yesterday_revenue
FROM orders o
JOIN stores s ON o.store_id = s.id
WHERE o.tenant_id = current_setting('app.tenant_id')::uuid
  AND o.paid_at >= CURRENT_DATE - 1
  AND o.status = 'paid'
GROUP BY s.store_name
ORDER BY today_revenue DESC;`;

const TABLE_COLUMNS: ProColumns<StoreRevRow>[] = [
  { title: '门店名', dataIndex: 'store', width: 140 },
  { title: '今日营业额', dataIndex: 'today', width: 120,
    render: (v) => <span style={{ color: '#FF6B35', fontWeight: 600 }}>¥{Number(v).toLocaleString()}</span> },
  { title: '昨日营业额', dataIndex: 'yesterday', width: 120,
    render: (v) => <span>¥{Number(v).toLocaleString()}</span> },
  { title: '环比', dataIndex: 'ratio', width: 90,
    render: (v) => {
      const s = String(v);
      return <span style={{ color: s.startsWith('+') ? '#0F6E56' : '#A32D2D', fontWeight: 600 }}>{s}</span>;
    } },
];

const MSG_TABLE_COLS = [
  { title: '门店', dataIndex: 'store', key: 'store' },
  { title: '今日(¥)', dataIndex: 'today', key: 'today', render: (v: number) => v.toLocaleString() },
  { title: '昨日(¥)', dataIndex: 'yesterday', key: 'yesterday', render: (v: number) => v.toLocaleString() },
  { title: '环比', dataIndex: 'ratio', key: 'ratio',
    render: (v: string) => <span style={{ color: v.startsWith('+') ? '#0F6E56' : '#A32D2D' }}>{v}</span> },
];

// ---- 右侧 Result 面板 ----
const resultTabs: TabsProps['items'] = [
  {
    key: 'chart',
    label: '图表',
    children: (
      <div style={{
        height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: '#f8f7f5', borderRadius: 8, color: '#888', fontSize: 13,
        border: '2px dashed #d9d9d9',
      }}>
        图表区域 — 待接入 @ant-design/charts
      </div>
    ),
  },
  {
    key: 'table',
    label: '数据表',
    children: (
      <ProTable<StoreRevRow>
        dataSource={MOCK_TABLE_DATA}
        columns={TABLE_COLUMNS}
        rowKey="key"
        search={false}
        toolBarRender={false}
        pagination={false}
        size="small"
      />
    ),
  },
  {
    key: 'sql',
    label: 'SQL',
    children: (
      <pre style={{
        background: '#1e2a3a', color: '#a8d8a8', padding: 16, borderRadius: 8,
        fontSize: 12, overflowX: 'auto', margin: 0, lineHeight: 1.6,
      }}>
        {MOCK_SQL}
      </pre>
    ),
  },
];

// ---- 主组件 ----
export const NLQueryPage = () => {
  const [messages, setMessages] = useState<ChatMsg[]>(MOCK_MESSAGES);
  const [inputVal, setInputVal] = useState('');
  const [checkedTags, setCheckedTags] = useState<string[]>([]);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const [suggestions, setSuggestions] = useState<Array<{id:string,text:string,category:string}>>([]);
  const [sending, setSending] = useState(false);

  const tenantId = localStorage.getItem('tx-tenant-id') || 'default';

  // 加载推荐问题
  useEffect(() => {
    fetch('/api/v1/nlq/suggestions', {
      headers: { 'X-Tenant-ID': tenantId },
    })
      .then(r => r.json())
      .then(res => { if (res.ok) setSuggestions(res.data); })
      .catch(() => {});
  }, [tenantId]);

  // 发送问题到 AI
  const sendQuery = async (query: string) => {
    if (!query.trim() || sending) return;
    setSending(true);
    try {
      const res = await fetch('/api/v1/nlq/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Tenant-ID': tenantId },
        body: JSON.stringify({ query }),
      });
      const data = await res.json();
      return data;
    } catch { return null; }
    finally { setSending(false); }
  };

  const handleSend = () => {
    const q = inputVal.trim();
    if (!q) return;
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: q },
      { role: 'ai', content: 'AI 正在分析中，请稍候…（mock 响应）' },
    ]);
    setInputVal('');
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
  };

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
        {/* 顶部 PageHeader */}
        <div style={{ padding: '16px 24px', borderBottom: '1px solid #f0f0f0', background: '#fff', flexShrink: 0 }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#2C2C2A' }}>AI 自然语言问数</div>
          <div style={{ fontSize: 13, color: '#888', marginTop: 2 }}>用自然语言提问，AI 自动生成报表</div>
        </div>

        {/* 主体区域 */}
        <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
          {/* 左侧聊天面板 */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderRight: '1px solid #f0f0f0', overflow: 'hidden' }}>
            {/* 快捷标签 */}
            <div style={{ padding: '12px 16px', borderBottom: '1px solid #f0f0f0', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {QUICK_QUESTIONS.map((q) => (
                <Tag.CheckableTag
                  key={q}
                  checked={checkedTags.includes(q)}
                  onChange={(checked) => {
                    setCheckedTags(checked ? [...checkedTags, q] : checkedTags.filter((t) => t !== q));
                    if (checked) setInputVal(q);
                  }}
                  style={{ cursor: 'pointer', fontSize: 12 }}
                >
                  {q}
                </Tag.CheckableTag>
              ))}
            </div>

            {/* 聊天气泡列表 */}
            <div style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>
              {messages.map((msg, idx) => (
                <div key={idx} style={{ display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                  <div style={{
                    maxWidth: '85%',
                    background: msg.role === 'user' ? '#FF6B35' : '#f8f7f5',
                    color: msg.role === 'user' ? '#fff' : '#2C2C2A',
                    padding: '10px 14px',
                    borderRadius: msg.role === 'user' ? '14px 14px 4px 14px' : '14px 14px 14px 4px',
                    fontSize: 14,
                  }}>
                    <div>{msg.content}</div>
                    {msg.table && (
                      <div style={{ marginTop: 10 }}>
                        <Table
                          dataSource={msg.table.map((r, i) => ({ ...r, key: i }))}
                          columns={MSG_TABLE_COLS}
                          pagination={false}
                          size="small"
                          style={{ background: '#fff', borderRadius: 6 }}
                        />
                      </div>
                    )}
                  </div>
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>

            {/* 底部输入区 */}
            <div style={{ padding: 16, borderTop: '1px solid #f0f0f0', display: 'flex', gap: 8, alignItems: 'flex-end' }}>
              <TextArea
                value={inputVal}
                onChange={(e) => setInputVal(e.target.value)}
                placeholder="输入您的问题，如：今天各门店营业额对比"
                autoSize={{ minRows: 2, maxRows: 4 }}
                style={{ flex: 1 }}
                onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); handleSend(); } }}
              />
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={handleSend}
                style={{ background: '#FF6B35', borderColor: '#FF6B35', height: 40 }}
              >
                发送
              </Button>
              <Button icon={<AudioOutlined />} style={{ height: 40 }}>
                🎙️ 语音
              </Button>
            </div>
          </div>

          {/* 右侧结果面板 */}
          <div style={{ width: 400, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid #f0f0f0', fontWeight: 600, fontSize: 14, background: '#fafafa' }}>
              查询结果
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
              <Tabs items={resultTabs} size="small" />
            </div>
          </div>
        </div>
      </div>
    </ConfigProvider>
  );
};
