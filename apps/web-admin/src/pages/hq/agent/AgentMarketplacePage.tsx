/**
 * AgentMarketplacePage — Agent 市场
 * Sprint 4: tx-agent Agent市场
 */
import React from 'react';
import {
  ConfigProvider, Row, Col, Card, Badge, Button, Input, Select, Tag, Pagination, Space,
} from 'antd';

// ---- 类型 ----
interface AgentItem {
  id: number;
  icon: string;
  name: string;
  desc: string;
  version: string;
  price: string;
  installed: boolean;
}

// ---- Mock 数据 ----
const agents: AgentItem[] = [
  { id: 1, icon: '🎯', name: '运营指挥官 Pro', desc: '全局经营数据实时监控，智能异常预警，跨门店协同调度', version: 'v2.3.1', price: '¥299/月', installed: true  },
  { id: 2, icon: '🍳', name: '菜品智能体',     desc: '菜品健康度分析、沽清预警、新品追踪、厨房排班建议',   version: 'v1.8.0', price: '¥199/月', installed: true  },
  { id: 3, icon: '👤', name: '客户大脑',       desc: '客户全域画像、RFM分层、流失预警、个性化推荐',       version: 'v3.1.2', price: '¥249/月', installed: true  },
  { id: 4, icon: '💰', name: '收益优化师',     desc: '动态定价建议、翻台率提升、时段收益分析',           version: 'v1.5.4', price: '¥199/月', installed: true  },
  { id: 5, icon: '📦', name: '供应链卫士',     desc: 'AI采购建议、损耗预警、临期管理、需求预测',         version: 'v2.0.3', price: '¥179/月', installed: true  },
  { id: 6, icon: '📊', name: '经营分析师',     desc: '自然语言问数、经营简报、多维报表自动生成',         version: 'v1.9.7', price: '¥229/月', installed: true  },
  { id: 7, icon: '🤝', name: '智能招聘助手',   desc: '岗位画像匹配、简历筛选、面试安排、入职跟进',       version: 'v1.2.0', price: '¥149/月', installed: false },
  { id: 8, icon: '📣', name: '口碑管理Agent', desc: '全平台评价监控、负面预警、自动回复建议、口碑报告', version: 'v1.0.5', price: '¥129/月', installed: false },
];

const categoryOptions = [
  { label: '全部分类', value: 'all' },
  { label: '餐饮',     value: 'food' },
  { label: '营销',     value: 'marketing' },
  { label: '供应链',   value: 'supply' },
  { label: '财务',     value: 'finance' },
];

// ---- 页面组件 ----
export const AgentMarketplacePage: React.FC = () => {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24, background: '#f5f5f5', minHeight: '100vh' }}>
        {/* 顶部搜索 */}
        <div style={{ marginBottom: 20, display: 'flex', gap: 12, alignItems: 'center' }}>
          <Input.Search
            placeholder="搜索 Agent..."
            style={{ width: 300 }}
            allowClear
          />
          <Select
            defaultValue="all"
            style={{ width: 140 }}
            options={categoryOptions}
          />
        </div>

        {/* Agent 卡片网格 */}
        <Row gutter={[16, 16]}>
          {agents.map((agent) => (
            <Col key={agent.id} span={6}>
              <Card
                hoverable
                style={{ height: '100%' }}
                bodyStyle={{ padding: 20 }}
              >
                {/* 图标 + 名称 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                  <span style={{ fontSize: 32 }}>{agent.icon}</span>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 600, lineHeight: '20px' }}>
                      {agent.name}
                    </div>
                    <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>
                      {agent.version}
                    </div>
                  </div>
                </div>

                {/* 简介 */}
                <div style={{ fontSize: 12, color: '#666', marginBottom: 12, lineHeight: '18px', minHeight: 36 }}>
                  {agent.desc}
                </div>

                {/* 价格 + 状态 + 操作 */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: '#FF6B35' }}>{agent.price}</div>
                    {agent.installed ? (
                      <Badge status="success" text={<span style={{ fontSize: 11 }}>已安装</span>} />
                    ) : (
                      <Tag color="default" style={{ fontSize: 11 }}>未安装</Tag>
                    )}
                  </div>
                  {agent.installed ? (
                    <Button size="small">配置</Button>
                  ) : (
                    <Button
                      size="small"
                      type="primary"
                      style={{ background: '#FF6B35', border: 'none' }}
                    >
                      免费试用7天
                    </Button>
                  )}
                </div>
              </Card>
            </Col>
          ))}
        </Row>

        {/* 分页 */}
        <div style={{ marginTop: 24, textAlign: 'right' }}>
          <Pagination total={24} pageSize={8} showSizeChanger={false} />
        </div>
      </div>
    </ConfigProvider>
  );
};
