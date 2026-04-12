/**
 * GovernanceStaffing — 编制治理
 * Sprint 6 · 总部治理台
 *
 * API: GET /api/v1/hr/governance/staffing
 */

import { useEffect, useState } from 'react';
import { Card, Col, Row, Tag, message } from 'antd';
import { ProColumns, ProTable } from '@ant-design/pro-components';
import { Column } from '@ant-design/charts';
import { txFetchData } from '../../../api';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface StaffingItem {
  store_id: string;
  store_name: string;
  quota: number;
  actual: number;
  shortage: number;
  surplus: number;
  shortage_rate: number;
}

interface StaffingResp {
  items: StaffingItem[];
  total: number;
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function GovernanceStaffing() {
  const [data, setData] = useState<StaffingItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    txFetchData<StaffingResp>('/api/v1/hr/governance/staffing')
      .then((resp) => setData(resp.data?.items ?? []))
      .catch(() => message.error('加载编制数据失败'))
      .finally(() => setLoading(false));
  }, []);

  const columns: ProColumns<StaffingItem>[] = [
    { title: '门店', dataIndex: 'store_name' },
    { title: '编制数', dataIndex: 'quota', valueType: 'digit', width: 90 },
    { title: '实际人数', dataIndex: 'actual', valueType: 'digit', width: 90 },
    {
      title: '缺编',
      dataIndex: 'shortage',
      width: 80,
      render: (_, r) => (
        <span style={{ color: r.shortage > 2 ? '#A32D2D' : undefined, fontWeight: r.shortage > 2 ? 600 : 400 }}>
          {r.shortage}
        </span>
      ),
    },
    {
      title: '超编',
      dataIndex: 'surplus',
      width: 80,
      render: (_, r) => (
        <span style={{ color: r.surplus > 0 ? '#BA7517' : undefined }}>
          {r.surplus}
        </span>
      ),
    },
    {
      title: '缺编率',
      dataIndex: 'shortage_rate',
      width: 100,
      sorter: (a, b) => a.shortage_rate - b.shortage_rate,
      render: (_, r) => (
        <Tag color={r.shortage_rate > 15 ? 'red' : r.shortage_rate > 5 ? 'orange' : 'green'}>
          {r.shortage_rate.toFixed(1)}%
        </Tag>
      ),
    },
  ];

  // 柱状图数据
  const chartData = data.flatMap((item) => [
    { store_name: item.store_name, type: '编制', count: item.quota },
    { store_name: item.store_name, type: '实际', count: item.actual },
  ]);

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={24}>
          <Card title="各门店编制 vs 实际人数">
            <Column
              data={chartData}
              xField="store_name"
              yField="count"
              seriesField="type"
              isGroup
              height={320}
              color={['#185FA5', '#FF6B35']}
              xAxis={{ label: { autoRotate: true } }}
              legend={{ position: 'top-right' }}
            />
          </Card>
        </Col>
      </Row>

      <ProTable<StaffingItem>
        headerTitle="编制治理明细"
        columns={columns}
        dataSource={data}
        loading={loading}
        rowKey="store_id"
        search={false}
        pagination={{ defaultPageSize: 20 }}
        toolBarRender={false}
        rowClassName={(r) => (r.shortage > 2 ? 'row-shortage-warning' : '')}
      />

      <style>{`
        .row-shortage-warning {
          background: #fff1f0 !important;
        }
      `}</style>
    </div>
  );
}
