/** 演示环境监控面板 — Gap C-04 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Button, Card, Col, Row, Statistic, Table, Tag, Typography, Space, Spin,
} from 'antd';
import {
  ReloadOutlined, CheckCircleOutlined, CloseCircleOutlined, MinusCircleOutlined,
} from '@ant-design/icons';
import type { MerchantHealth, ServiceInfo } from '../api/demoMonitorApi';
import { fetchDemoHealth, fetchDemoServices } from '../api/demoMonitorApi';

const { Title, Text } = Typography;

const STATUS_CONFIG: Record<string, { color: string; icon: React.ReactNode }> = {
  healthy: { color: 'green', icon: <CheckCircleOutlined /> },
  degraded: { color: 'orange', icon: <MinusCircleOutlined /> },
  error: { color: 'red', icon: <CloseCircleOutlined /> },
};

function DemoMonitorPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [merchants, setMerchants] = useState<MerchantHealth[]>([]);
  const [services, setServices] = useState<ServiceInfo[]>([]);
  const [lastUpdated, setLastUpdated] = useState<string>('');
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    let hasError = false;

    const [healthRes, servicesRes] = await Promise.allSettled([
      fetchDemoHealth(),
      fetchDemoServices(),
    ]);

    if (healthRes.status === 'fulfilled') {
      setMerchants(healthRes.value.data ?? []);
    } else {
      hasError = true;
    }
    if (servicesRes.status === 'fulfilled') {
      setServices(servicesRes.value.data?.services ?? []);
    } else {
      hasError = true;
    }

    setLastUpdated(new Date().toLocaleTimeString('zh-CN'));
    setError(hasError ? '部分数据获取失败，面板可能不完整' : null);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchAll();
    intervalRef.current = setInterval(fetchAll, 30_000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchAll]);

  const healthColumns = [
    { title: '检查项', dataIndex: 'name', key: 'name' },
    { title: '数量', dataIndex: 'count', key: 'count' },
    {
      title: '状态', dataIndex: 'ok', key: 'ok',
      render: (ok: boolean) => (ok
        ? <Tag icon={<CheckCircleOutlined />} color="success">通过</Tag>
        : <Tag icon={<CloseCircleOutlined />} color="error">未通过</Tag>),
    },
  ];

  const serviceColumns = [
    { title: '服务', dataIndex: 'name', key: 'name' },
    { title: '端口', dataIndex: 'port', key: 'port' },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (status: string) => {
        const cfg = STATUS_CONFIG[status] ?? { color: 'default', icon: <MinusCircleOutlined /> };
        return <Tag icon={cfg.icon} color={cfg.color}>{status}</Tag>;
      },
    },
    { title: '说明', dataIndex: 'note', key: 'note' },
  ];

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
        <Spin size="large" tip="加载监控数据..." />
      </div>
    );
  }

  return (
    <div style={{ padding: 24, background: '#0f0f1a', minHeight: '100vh', color: '#e0e0e0' }}>
      {/* Header */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 24 }}>
        <Col>
          <Title level={3} style={{ color: '#e0e0e0', margin: 0 }}>📊 演示环境监控面板</Title>
          <Text type="secondary" style={{ color: '#888' }}>
            最后更新: {lastUpdated} · 自动每 30 秒刷新
          </Text>
        </Col>
        <Col>
          <Button type="primary" icon={<ReloadOutlined />} onClick={fetchAll} loading={loading}>
            刷新
          </Button>
        </Col>
      </Row>

      {error && (
        <Card style={{ marginBottom: 16, background: '#1a1a2e', borderColor: '#ff4d4f' }}>
          <Text type="danger">⚠️ {error}</Text>
        </Card>
      )}

      {/* Merchant Health Cards */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        {merchants.map((m) => {
          const cfg = STATUS_CONFIG[m.status] ?? { color: 'default', icon: <MinusCircleOutlined /> };
          return (
            <Col span={8} key={m.merchant_code}>
              <Card
                title={(
                  <Space>
                    <span>{m.merchant_name}</span>
                    <Tag icon={cfg.icon} color={cfg.color}>{m.status}</Tag>
                  </Space>
                )}
                style={{ background: '#1a1a2e', borderColor: '#333', color: '#e0e0e0' }}
                headStyle={{ color: '#e0e0e0', borderBottom: '1px solid #333' }}
              >
                <Row gutter={[16, 16]}>
                  <Col span={12}>
                    <Statistic
                      title={<span style={{ color: '#888' }}>数据质量评分</span>}
                      value={m.data_quality_score}
                      suffix={`/ 100`}
                      valueStyle={{ color: m.data_quality_score >= 70 ? '#52c41a' : '#faad14' }}
                    />
                  </Col>
                  <Col span={12}>
                    <Statistic
                      title={<span style={{ color: '#888' }}>等级</span>}
                      value={m.grade}
                      valueStyle={{ color: '#e0e0e0', fontSize: 32 }}
                    />
                  </Col>
                </Row>
                <Table
                  dataSource={m.checks}
                  columns={healthColumns}
                  pagination={false}
                  size="small"
                  rowKey="name"
                  style={{ marginTop: 16 }}
                  locale={{ emptyText: '无检查项' }}
                />
              </Card>
            </Col>
          );
        })}
      </Row>

      {/* Services Table */}
      <Card
        title={<span style={{ color: '#e0e0e0' }}>微服务列表</span>}
        style={{ background: '#1a1a2e', borderColor: '#333' }}
        headStyle={{ color: '#e0e0e0', borderBottom: '1px solid #333' }}
      >
        <Table
          dataSource={services}
          columns={serviceColumns}
          pagination={false}
          size="small"
          rowKey="name"
          locale={{ emptyText: '无服务数据' }}
        />
      </Card>
    </div>
  );
}

export default DemoMonitorPage;
