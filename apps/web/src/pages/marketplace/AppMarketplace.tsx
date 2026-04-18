/**
 * 应用市场首页 — 分类 Tabs + 应用卡片网格
 */
import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Tabs, Card, Input, Tag, Rate, Button, Empty, Spin, message } from 'antd';
import { apiClient, handleApiError } from '../../services/api';

const CATEGORIES = [
  { key: 'all', label: '全部', filter: undefined },
  { key: 'ai_agent', label: 'AI 智能体', filter: 'ai_agent' },
  { key: 'self_built', label: '自有应用', filter: 'self_built' },
  { key: 'third_party', label: '第三方', filter: 'third_party' },
  { key: 'industry_solution', label: '行业方案', filter: 'industry_solution' },
];

interface AppItem {
  id: string;
  code: string;
  name: string;
  category: string;
  description?: string;
  icon_url?: string;
  provider: string;
  price_yuan: number;
  price_model: string;
  avg_rating: number;
  review_count: number;
  trial_days: number;
}

const AppMarketplace: React.FC = () => {
  const [tab, setTab] = useState('all');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [apps, setApps] = useState<AppItem[]>([]);

  const load = async () => {
    setLoading(true);
    try {
      const cat = CATEGORIES.find((c) => c.key === tab)?.filter;
      const params: Record<string, string> = {};
      if (cat) params.category = cat;
      if (search) params.search = search;
      const resp = await apiClient.get('/api/v1/marketplace/apps', { params });
      setApps(resp.data || []);
    } catch (err) {
      message.error(handleApiError(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 16 }}>🛒 应用市场</h2>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <Input.Search
          placeholder="搜索应用 / 数智员工 / 行业方案"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onSearch={load}
          style={{ maxWidth: 400 }}
          allowClear
        />
        <Link to="/marketplace/my-apps">
          <Button>我的应用</Button>
        </Link>
        <Link to="/marketplace/billing">
          <Button>月度账单</Button>
        </Link>
      </div>
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={CATEGORIES.map((c) => ({ key: c.key, label: c.label }))}
      />
      <Spin spinning={loading}>
        {apps.length === 0 ? (
          <Empty description="暂无应用" />
        ) : (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
              gap: 16,
              marginTop: 16,
            }}
          >
            {apps.map((a) => (
              <Card
                key={a.id}
                hoverable
                title={a.name}
                extra={<Tag color="orange">{a.category}</Tag>}
                actions={[
                  <Link key="detail" to={`/marketplace/apps/${a.id}`}>
                    查看详情
                  </Link>,
                ]}
              >
                <div style={{ minHeight: 48, color: '#666' }}>{a.description}</div>
                <div style={{ marginTop: 8 }}>
                  <Rate disabled allowHalf value={a.avg_rating} />
                  <span style={{ color: '#999', marginLeft: 8 }}>
                    {a.review_count} 条评价
                  </span>
                </div>
                <div style={{ marginTop: 8, fontSize: 18, color: '#FF6B2C' }}>
                  {a.price_model === 'free'
                    ? '免费'
                    : `¥${a.price_yuan.toFixed(0)}/${
                        a.price_model === 'one_time' ? '次' : '月'
                      }`}
                </div>
                {a.trial_days > 0 && (
                  <Tag color="green" style={{ marginTop: 4 }}>
                    {a.trial_days} 天试用
                  </Tag>
                )}
              </Card>
            ))}
          </div>
        )}
      </Spin>
    </div>
  );
};

export default AppMarketplace;
