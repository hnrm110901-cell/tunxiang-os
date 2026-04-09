/**
 * WastageAnalysisPage — 损耗分析
 * Sprint 4: tx-supply 供应链卫士
 */
import React from 'react';
import {
  ConfigProvider, Alert, Row, Col, Card, Statistic, Tag, Button, List, Progress,
} from 'antd';
import { BulbOutlined } from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';

// ---- 类型 ----
interface WastageRow {
  key: number;
  name: string;
  lostQty: string;
  lostAmount: string;
  reason: '过期' | '制作损耗' | '退货损耗' | '其他';
  occurTime: string;
  store: string;
}

// ---- Mock 数据 ----
const wastageData: WastageRow[] = [
  { key: 1, name: '鲍鱼（A批）',   lostQty: '3头',   lostAmount: '¥384', reason: '过期',   occurTime: '2026-04-07 08:30', store: '南山旗舰'   },
  { key: 2, name: '三文鱼',        lostQty: '1.2kg', lostAmount: '¥156', reason: '制作损耗', occurTime: '2026-04-07 11:00', store: '福田中心'   },
  { key: 3, name: '濑尿虾',        lostQty: '0.8kg', lostAmount: '¥34',  reason: '退货损耗', occurTime: '2026-04-06 19:30', store: '罗湖商圈'   },
  { key: 4, name: '蒜蓉',          lostQty: '0.5kg', lostAmount: '¥23',  reason: '制作损耗', occurTime: '2026-04-06 14:00', store: '南山旗舰'   },
  { key: 5, name: '龙虾',          lostQty: '1条',   lostAmount: '¥268', reason: '退货损耗', occurTime: '2026-04-06 12:30', store: '天河高端店' },
  { key: 6, name: '花蟹',          lostQty: '2只',   lostAmount: '¥120', reason: '过期',     occurTime: '2026-04-05 21:00', store: '福田中心'   },
  { key: 7, name: '芥蓝',          lostQty: '1kg',   lostAmount: '¥12',  reason: '其他',     occurTime: '2026-04-05 10:00', store: '罗湖商圈'   },
  { key: 8, name: '豆腐',          lostQty: '2块',   lostAmount: '¥8',   reason: '制作损耗', occurTime: '2026-04-05 09:00', store: '南山旗舰'   },
];

const reasonColorMap: Record<WastageRow['reason'], string> = {
  '过期':     'red',
  '制作损耗': 'orange',
  '退货损耗': 'purple',
  '其他':     'default',
};

// ---- 列定义 ----
const wastageColumns: ProColumns<WastageRow>[] = [
  { title: '食材',     dataIndex: 'name',       width: 110 },
  { title: '损耗数量', dataIndex: 'lostQty',    width: 90 },
  { title: '损耗金额', dataIndex: 'lostAmount', width: 90 },
  {
    title: '损耗原因', dataIndex: 'reason', width: 100,
    render: (_, r) => <Tag color={reasonColorMap[r.reason]}>{r.reason}</Tag>,
  },
  { title: '发生时间', dataIndex: 'occurTime', width: 150 },
  { title: '门店',     dataIndex: 'store',     width: 90 },
  {
    title: '操作', valueType: 'option', width: 60,
    render: () => [<a key="detail">详情</a>],
  },
];

const compositionItems = [
  { label: '制作损耗', percent: 48, color: '#FA8C16' },
  { label: '过期',     percent: 12, color: '#A32D2D' },
  { label: '退货损耗', percent: 23, color: '#722ED1' },
  { label: '其他',     percent: 17, color: '#8C8C8C' },
];

const aiSuggestions = [
  '海鲜类食材建议按需进货，避免过度备货，当前过期损耗占12%，具有较大改善空间',
  '制作损耗占48%，建议加强厨师标准化培训，统一操作规范，预计可降低15-20%',
  '退货损耗主要来自濑尿虾和花蟹，建议与供应商谈判改善验收标准和退换货机制',
];

// ---- 页面组件 ----
export const WastageAnalysisPage: React.FC = () => {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24, background: '#f5f5f5', minHeight: '100vh' }}>
        {/* 顶部信息 */}
        <Alert
          type="info"
          showIcon
          message="tx-supply 本周损耗率 4.2%，较上周下降 0.8%，优于行业均值(5.5%)"
          style={{ marginBottom: 16 }}
        />

        {/* 统计卡片 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Card><Statistic title="本周总损耗" value="1,240" prefix="¥" /></Card>
          </Col>
          <Col span={8}>
            <Card>
              <Statistic
                title="损耗率"
                value={4.2}
                suffix="%"
                valueStyle={{ color: '#0F6E56' }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card>
              <Statistic
                title="节省金额"
                value={320}
                prefix="¥"
                valueStyle={{ color: '#0F6E56' }}
              />
            </Card>
          </Col>
        </Row>

        {/* 主体 */}
        <Row gutter={16}>
          {/* 左侧：损耗明细表 */}
          <Col span={16}>
            <Card title="损耗明细">
              <ProTable<WastageRow>
                columns={wastageColumns}
                dataSource={wastageData}
                rowKey="key"
                search={false}
                pagination={{ pageSize: 8 }}
                toolBarRender={false}
                size="small"
              />
            </Card>
          </Col>

          {/* 右侧：损耗构成 + AI降损建议 */}
          <Col span={8}>
            <Card title="损耗构成">
              {compositionItems.map((item) => (
                <div key={item.label} style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 13 }}>
                    <span>{item.label}</span>
                    <span style={{ fontWeight: 600 }}>{item.percent}%</span>
                  </div>
                  <Progress
                    percent={item.percent}
                    size="small"
                    strokeColor={item.color}
                    showInfo={false}
                  />
                </div>
              ))}
            </Card>

            <Card title="AI 降损建议" style={{ marginTop: 16 }}>
              <List
                dataSource={aiSuggestions}
                renderItem={(item) => (
                  <List.Item
                    actions={[
                      <Button key="adopt" size="small" type="link" style={{ color: '#FF6B35' }}>
                        采纳
                      </Button>,
                    ]}
                  >
                    <List.Item.Meta
                      avatar={<BulbOutlined style={{ color: '#FA8C16', fontSize: 16, marginTop: 2 }} />}
                      description={<span style={{ fontSize: 12 }}>{item}</span>}
                    />
                  </List.Item>
                )}
              />
            </Card>
          </Col>
        </Row>
      </div>
    </ConfigProvider>
  );
};
