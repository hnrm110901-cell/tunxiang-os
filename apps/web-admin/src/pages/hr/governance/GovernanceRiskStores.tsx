/**
 * GovernanceRiskStores — 高风险门店
 * Sprint 6 · 总部治理台
 *
 * API: GET /api/v1/hr/governance/risk-stores
 */

import { useEffect, useState } from 'react';
import { Card, Col, Row, Space, Tag, message } from 'antd';
import { ProColumns, ProTable } from '@ant-design/pro-components';
import { Pie } from '@ant-design/charts';
import { txFetchData } from '../../../api';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface RiskStore {
  store_id: string;
  store_name: string;
  attendance_rate: number;
  late_rate: number;
  compliance_alerts: number;
  labor_cost_rate: number;
  risk_score: number;
}

interface RiskStoreResp {
  items: RiskStore[];
  total: number;
}

// ─── 工具 ────────────────────────────────────────────────────────────────────

function scoreTag(score: number) {
  if (score < 60) return <Tag color="red" style={{ fontWeight: 600 }}>{score}</Tag>;
  if (score < 80) return <Tag color="orange">{score}</Tag>;
  return <Tag color="green">{score}</Tag>;
}

function scoreLevel(score: number): string {
  if (score < 60) return '高风险';
  if (score < 80) return '中风险';
  return '低风险';
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function GovernanceRiskStores() {
  const [data, setData] = useState<RiskStore[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    txFetchData<RiskStoreResp>('/api/v1/hr/governance/risk-stores')
      .then((resp) => setData(resp.data?.items ?? []))
      .catch(() => message.error('加载风险门店数据失败'))
      .finally(() => setLoading(false));
  }, []);

  const columns: ProColumns<RiskStore>[] = [
    { title: '门店', dataIndex: 'store_name' },
    {
      title: '出勤率',
      dataIndex: 'attendance_rate',
      width: 90,
      render: (_, r) => `${r.attendance_rate.toFixed(1)}%`,
      sorter: (a, b) => a.attendance_rate - b.attendance_rate,
    },
    {
      title: '迟到率',
      dataIndex: 'late_rate',
      width: 90,
      render: (_, r) => `${r.late_rate.toFixed(1)}%`,
    },
    {
      title: '合规预警数',
      dataIndex: 'compliance_alerts',
      width: 100,
      render: (_, r) => (
        <span style={{ color: r.compliance_alerts > 5 ? '#A32D2D' : undefined }}>
          {r.compliance_alerts}
        </span>
      ),
    },
    {
      title: '人工成本率',
      dataIndex: 'labor_cost_rate',
      width: 100,
      render: (_, r) => `${r.labor_cost_rate.toFixed(1)}%`,
    },
    {
      title: '综合评分',
      dataIndex: 'risk_score',
      width: 100,
      sorter: (a, b) => a.risk_score - b.risk_score,
      defaultSortOrder: 'ascend',
      render: (_, r) => scoreTag(r.risk_score),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 150,
      render: (_, r) => (
        <Space size="small">
          <a onClick={() => message.info(`查看 ${r.store_name} 详情`)}>查看详情</a>
          {r.risk_score < 60 && (
            <a style={{ color: '#A32D2D' }} onClick={() => message.info(`发起对 ${r.store_name} 的干预`)}>
              发起干预
            </a>
          )}
        </Space>
      ),
    },
  ];

  // 饼图数据
  const pieData = [
    { level: '高风险', count: data.filter((d) => d.risk_score < 60).length },
    { level: '中风险', count: data.filter((d) => d.risk_score >= 60 && d.risk_score < 80).length },
    { level: '低风险', count: data.filter((d) => d.risk_score >= 80).length },
  ].filter((d) => d.count > 0);

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card title="风险门店分布">
            <Pie
              data={pieData}
              angleField="count"
              colorField="level"
              radius={0.8}
              innerRadius={0.5}
              height={260}
              color={['#A32D2D', '#BA7517', '#0F6E56']}
              label={{ type: 'spider', content: '{name}: {value}' }}
              statistic={{
                title: { content: '门店总数' },
                content: { content: String(data.length) },
              }}
            />
          </Card>
        </Col>
        <Col span={16}>
          <Card>
            <Row gutter={16}>
              <Col span={8}>
                <div style={{ textAlign: 'center', padding: 16 }}>
                  <div style={{ fontSize: 32, fontWeight: 600, color: '#A32D2D' }}>
                    {data.filter((d) => d.risk_score < 60).length}
                  </div>
                  <div style={{ color: '#666' }}>高风险门店</div>
                </div>
              </Col>
              <Col span={8}>
                <div style={{ textAlign: 'center', padding: 16 }}>
                  <div style={{ fontSize: 32, fontWeight: 600, color: '#BA7517' }}>
                    {data.filter((d) => d.risk_score >= 60 && d.risk_score < 80).length}
                  </div>
                  <div style={{ color: '#666' }}>中风险门店</div>
                </div>
              </Col>
              <Col span={8}>
                <div style={{ textAlign: 'center', padding: 16 }}>
                  <div style={{ fontSize: 32, fontWeight: 600, color: '#0F6E56' }}>
                    {data.filter((d) => d.risk_score >= 80).length}
                  </div>
                  <div style={{ color: '#666' }}>低风险门店</div>
                </div>
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      <ProTable<RiskStore>
        headerTitle="高风险门店排名"
        columns={columns}
        dataSource={data}
        loading={loading}
        rowKey="store_id"
        search={false}
        pagination={{ defaultPageSize: 20 }}
        toolBarRender={false}
        rowClassName={(r) => (r.risk_score < 60 ? 'row-high-risk' : '')}
      />

      <style>{`
        .row-high-risk {
          background: #fff1f0 !important;
        }
      `}</style>
    </div>
  );
}
