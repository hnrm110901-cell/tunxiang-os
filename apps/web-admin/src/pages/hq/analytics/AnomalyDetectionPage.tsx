/**
 * AnomalyDetectionPage — 经营异常检测
 * Sprint 4: tx-analytics 异常检测
 */
import React, { useState, useEffect } from 'react';
import {
  ConfigProvider, Alert, Row, Col, Card, Statistic, Tag, Button, Select, Space,
} from 'antd';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';

// ---- 类型 ----
interface AnomalyRow {
  key: number;
  time: string;
  store: string;
  anomalyType: '营收' | '库存' | '会员' | '设备';
  desc: string;
  impactAmount: string;
  aiAnalysis: string;
  status: '待处理' | '处理中' | '已解决';
}

// ---- Mock 数据 ----
const anomalyData: AnomalyRow[] = [
  {
    key: 1, time: '今日09:15', store: '南山旗舰',
    anomalyType: '营收', desc: '午市营业额较同期低38%，异常下滑',
    impactAmount: '¥3,200', aiAnalysis: '周边出现新竞争对手，建议午市促销',
    status: '待处理',
  },
  {
    key: 2, time: '今日10:30', store: '福田中心',
    anomalyType: '库存', desc: '濑尿虾库存消耗速度异常，可能存在损耗',
    impactAmount: '¥580', aiAnalysis: '建议盘点核查',
    status: '待处理',
  },
  {
    key: 3, time: '昨日21:00', store: '系统',
    anomalyType: '设备', desc: 'POS打印机离线，影响结账效率',
    impactAmount: '¥0', aiAnalysis: '设备故障告警',
    status: '已解决',
  },
  {
    key: 4, time: '今日08:00', store: '罗湖商圈',
    anomalyType: '会员', desc: '会员复购率本周骤降18%',
    impactAmount: '¥1,200', aiAnalysis: '近期1km内新开同类门店',
    status: '处理中',
  },
  {
    key: 5, time: '今日11:00', store: '天河高端店',
    anomalyType: '营收', desc: '外卖平台订单量较昨日下降42%',
    impactAmount: '¥860', aiAnalysis: '平台流量权重下降，建议补贴活动',
    status: '待处理',
  },
  {
    key: 6, time: '昨日18:30', store: '南山旗舰',
    anomalyType: '库存', desc: '食用油消耗量超过正常水平200%',
    impactAmount: '¥320', aiAnalysis: '疑似计量误差，建议人工核查称重设备',
    status: '已解决',
  },
  {
    key: 7, time: '昨日22:00', store: '福田中心',
    anomalyType: '会员', desc: '当日会员积分兑换异常集中，1小时内兑换47次',
    impactAmount: '¥2,100', aiAnalysis: '疑似规则漏洞被利用，已触发风控规则',
    status: '处理中',
  },
];

const anomalyTypeColor: Record<AnomalyRow['anomalyType'], string> = {
  '营收': 'red',
  '库存': 'orange',
  '会员': 'purple',
  '设备': 'blue',
};

const statusColor: Record<AnomalyRow['status'], string> = {
  '待处理': 'orange',
  '处理中': 'blue',
  '已解决': 'green',
};

// ---- 列定义 ----
const columns: ProColumns<AnomalyRow>[] = [
  { title: '发现时间', dataIndex: 'time',         width: 110 },
  { title: '门店',     dataIndex: 'store',        width: 90  },
  {
    title: '异常类型', dataIndex: 'anomalyType', width: 90,
    render: (_, r) => <Tag color={anomalyTypeColor[r.anomalyType]}>{r.anomalyType}</Tag>,
  },
  { title: '异常描述', dataIndex: 'desc',         flex: 1 },
  { title: '影响金额', dataIndex: 'impactAmount', width: 90  },
  { title: 'AI分析',   dataIndex: 'aiAnalysis',   width: 180 },
  {
    title: '状态', dataIndex: 'status', width: 80,
    render: (_, r) => <Tag color={statusColor[r.status]}>{r.status}</Tag>,
  },
  {
    title: '操作', valueType: 'option', width: 110,
    render: () => [
      <a key="handle" style={{ color: '#FF6B35' }}>处理</a>,
      <a key="ignore" style={{ color: '#999', marginLeft: 8 }}>忽略</a>,
    ],
  },
];

// ---- 页面组件 ----
export const AnomalyDetectionPage: React.FC = () => {
  const [anomalies, setAnomalies] = useState<any[]>([]);
  const [summary, setSummary] = useState<{critical:number,warning:number,info:number,total:number}>({critical:0,warning:0,info:0,total:0});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const tenantId = localStorage.getItem('tx-tenant-id') || 'default';
    fetch('/api/v1/anomaly/today', {
      headers: { 'X-Tenant-ID': tenantId },
    })
      .then(r => r.json())
      .then(res => {
        if (res.ok && res.data) {
          if (res.data.anomalies?.length > 0) setAnomalies(res.data.anomalies);
          if (res.data.summary) setSummary(res.data.summary);
        }
      })
      .catch(() => {/* 保留 mock */})
      .finally(() => setLoading(false));
  }, []);

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24, background: '#f5f5f5', minHeight: '100vh' }}>
        {/* 顶部 Alert + 操作按钮 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
          <Alert
            type="error"
            showIcon
            message="今日发现 7 条异常"
            style={{ flex: 1, marginRight: 16 }}
          />
          <Space>
            <Button>全部标记已读</Button>
            <Select
              defaultValue="all"
              style={{ width: 140 }}
              options={[
                { label: '按严重程度筛选', value: 'all' },
                { label: '严重',           value: 'critical' },
                { label: '中度',           value: 'medium' },
                { label: '轻微',           value: 'minor' },
              ]}
            />
          </Space>
        </div>

        {/* 统计卡片 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Card>
              <Statistic
                title="严重异常"
                value={2}
                valueStyle={{ color: '#A32D2D' }}
                suffix="条"
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card>
              <Statistic
                title="中度异常"
                value={3}
                valueStyle={{ color: '#BA7517' }}
                suffix="条"
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card>
              <Statistic title="轻微异常" value={2} suffix="条" />
            </Card>
          </Col>
        </Row>

        {/* 主体异常列表 */}
        <Card>
          <ProTable<AnomalyRow>
            columns={columns}
            dataSource={anomalyData}
            rowKey="key"
            search={false}
            pagination={false}
            toolBarRender={false}
            size="small"
          />
        </Card>
      </div>
    </ConfigProvider>
  );
};
