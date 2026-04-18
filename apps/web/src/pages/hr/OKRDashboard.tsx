/**
 * OKR 看板 — 目标树 + 进度条 + 健康分
 * 路由: /hr/okr
 */
import React, { useEffect, useState } from 'react';
import { Card, Progress, Tag, Typography, Spin, Row, Col, Button, Input, Select, Form, Modal, List, message, Empty } from 'antd';
import { AimOutlined, PlusOutlined, BulbOutlined } from '@ant-design/icons';
import { apiClient } from '../../services/api';
import { useAuthStore } from '../../stores/authStore';

const { Title, Text } = Typography;

interface KR {
  id: string;
  title: string;
  metric_type: string;
  start_value: number;
  target_value: number;
  current_value: number;
  unit?: string;
  weight: number;
  progress_pct: number;
  status: string;
}
interface Objective {
  id: string;
  title: string;
  period: string;
  status: string;
  progress_pct: number;
  health: 'green' | 'yellow' | 'red';
  weight: number;
  key_results: KR[];
}

const HEALTH_COLOR: Record<string, string> = { green: 'success', yellow: 'warning', red: 'error' };

const OKRDashboard: React.FC = () => {
  const user = useAuthStore((s) => s.user);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<Objective[]>([]);
  const [period, setPeriod] = useState('2026Q2');
  const [showCreate, setShowCreate] = useState(false);
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [suggesting, setSuggesting] = useState(false);
  const [form] = Form.useForm();

  const load = async () => {
    if (!user?.id) return;
    setLoading(true);
    try {
      const resp = await apiClient.get(`/api/v1/hr/okr/my?owner_id=${user.id}&period=${period}`);
      setData(resp.data || []);
    } catch (e) {
      message.error('加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [period]);

  const onCreate = async () => {
    const v = await form.validateFields();
    try {
      await apiClient.post('/api/v1/hr/okr/objectives', {
        owner_id: user?.id,
        title: v.title,
        period,
        description: v.description,
      });
      message.success('已创建');
      setShowCreate(false);
      form.resetFields();
      load();
    } catch (e) { message.error('创建失败'); }
  };

  const onSuggest = async () => {
    const title = form.getFieldValue('title');
    if (!title) { message.warning('请先填写目标标题'); return; }
    setSuggesting(true);
    try {
      const resp = await apiClient.post('/api/v1/hr/okr/ai/suggest-krs', { objective_title: title });
      setSuggestions(resp.data?.items || []);
    } catch (e) { message.error('AI 推荐失败'); } finally { setSuggesting(false); }
  };

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={3}><AimOutlined /> OKR 目标看板</Title>
        </Col>
        <Col>
          <Select value={period} onChange={setPeriod} style={{ width: 120, marginRight: 12 }}
            options={[
              { value: '2026Q1', label: '2026 Q1' },
              { value: '2026Q2', label: '2026 Q2' },
              { value: '2026Q3', label: '2026 Q3' },
              { value: '2026Q4', label: '2026 Q4' },
            ]} />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setShowCreate(true)}>新建目标</Button>
        </Col>
      </Row>
      {loading ? <Spin /> : data.length === 0 ? <Empty description="暂无 OKR" /> : (
        <Row gutter={[16, 16]}>
          {data.map(obj => (
            <Col span={24} key={obj.id}>
              <Card
                title={<span>{obj.title} <Tag color={HEALTH_COLOR[obj.health]}>{obj.health}</Tag></span>}
                extra={<Text>权重 {obj.weight}</Text>}
              >
                <Progress percent={Math.round(obj.progress_pct)} status={obj.health === 'red' ? 'exception' : undefined} />
                <Text type="secondary">状态：{obj.status}</Text>
                <List
                  size="small"
                  style={{ marginTop: 12 }}
                  header={<b>关键结果（{obj.key_results.length}）</b>}
                  dataSource={obj.key_results}
                  renderItem={kr => (
                    <List.Item>
                      <div style={{ width: '100%' }}>
                        <Row justify="space-between">
                          <Col><Text>{kr.title}</Text></Col>
                          <Col><Text type="secondary">{kr.current_value}/{kr.target_value} {kr.unit || ''} · 权重 {kr.weight}</Text></Col>
                        </Row>
                        <Progress percent={Math.round(kr.progress_pct)} size="small" />
                      </div>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal open={showCreate} onCancel={() => setShowCreate(false)} onOk={onCreate} title="新建目标" okText="创建">
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="目标标题" rules={[{ required: true }]}>
            <Input placeholder="例：Q2 复购率提升到 35%" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Button icon={<BulbOutlined />} loading={suggesting} onClick={onSuggest}>AI 推荐 KR</Button>
          {suggestions.length > 0 && (
            <List style={{ marginTop: 12 }} size="small"
              dataSource={suggestions}
              renderItem={(s: any) => <List.Item>{s.title} <Text type="secondary">（目标 {s.target_value} {s.unit || ''}，权重 {s.weight}）</Text></List.Item>}
            />
          )}
        </Form>
      </Modal>
    </div>
  );
};

export default OKRDashboard;
