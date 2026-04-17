/**
 * 考试中心 — D11 Should-Fix P1
 *
 * 三列看板：待开始 / 进行中 / 已完成
 * 后端：
 *   GET /api/v1/hr/training/exam/papers/{id}
 *   POST /api/v1/hr/training/exam/attempts
 * 路由：/hr/exam-center
 */
import React, { useEffect, useState } from 'react';
import { Card, Col, Row, Button, List, Tag, message, Space, Input } from 'antd';
import { useNavigate } from 'react-router-dom';
import apiClient from '../../services/api';

interface AttemptSummary {
  id: string;
  paper_id: string;
  paper_title?: string;
  status: string;
  score?: number;
  passed?: boolean;
}

export default function ExamCenter() {
  const navigate = useNavigate();
  const [employeeId, setEmployeeId] = useState<string>(localStorage.getItem('employee_id') || 'E001');
  const [storeId, setStoreId] = useState<string>(localStorage.getItem('store_id') || 'S001');
  const [paperId, setPaperId] = useState<string>('');
  const [myCerts, setMyCerts] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  // 占位：后端暂无"我的待考列表"聚合端点，这里提供手动输入 paper_id 的入口
  // 上线后可接入 /api/v1/hr/training/enrollments?employee_id= 联动
  const [pendingPapers] = useState<AttemptSummary[]>([]);
  const [inProgress] = useState<AttemptSummary[]>([]);
  const [completed] = useState<AttemptSummary[]>([]);

  useEffect(() => {
    loadMyCerts();
  }, [employeeId]);

  const loadMyCerts = async () => {
    if (!employeeId) return;
    try {
      const resp = await apiClient.get('/api/v1/hr/training/exam/certificates/my', {
        params: { employee_id: employeeId },
      });
      setMyCerts(resp.data?.data || []);
    } catch (e) {
      // 静默
    }
  };

  const handleStart = async () => {
    if (!paperId) {
      message.warning('请输入试卷 ID');
      return;
    }
    setLoading(true);
    try {
      const resp = await apiClient.post('/api/v1/hr/training/exam/attempts', {
        paper_id: paperId,
        employee_id: employeeId,
        store_id: storeId,
      });
      const data = resp.data?.data;
      if (data?.id) {
        localStorage.setItem('employee_id', employeeId);
        localStorage.setItem('store_id', storeId);
        navigate(`/hr/exam/take/${paperId}?attempt=${data.id}`);
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '开始考试失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: 16 }}>
      <h2>考试中心</h2>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Input
            addonBefore="员工 ID"
            value={employeeId}
            onChange={(e) => setEmployeeId(e.target.value)}
            style={{ width: 240 }}
          />
          <Input
            addonBefore="门店 ID"
            value={storeId}
            onChange={(e) => setStoreId(e.target.value)}
            style={{ width: 220 }}
          />
          <Input
            addonBefore="试卷 ID"
            placeholder="粘贴 paper_id"
            value={paperId}
            onChange={(e) => setPaperId(e.target.value)}
            style={{ width: 340 }}
          />
          <Button type="primary" loading={loading} onClick={handleStart}>
            开始考试
          </Button>
          <Button onClick={() => navigate('/hr/my-certificates')}>我的证书</Button>
        </Space>
      </Card>

      <Row gutter={16}>
        <Col span={8}>
          <Card title="待开始" size="small">
            <List
              dataSource={pendingPapers}
              locale={{ emptyText: '暂无待考试卷' }}
              renderItem={(item) => (
                <List.Item
                  actions={[
                    <Button type="link" onClick={() => navigate(`/hr/exam/take/${item.paper_id}`)}>
                      开始
                    </Button>,
                  ]}
                >
                  <List.Item.Meta title={item.paper_title || item.paper_id} />
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="进行中" size="small">
            <List
              dataSource={inProgress}
              locale={{ emptyText: '无进行中考试' }}
              renderItem={(item) => (
                <List.Item>
                  <List.Item.Meta title={item.paper_title || item.paper_id} description={<Tag color="processing">进行中</Tag>} />
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="已完成" size="small">
            <List
              dataSource={completed}
              locale={{ emptyText: '暂无记录' }}
              renderItem={(item) => (
                <List.Item>
                  <List.Item.Meta
                    title={item.paper_title || item.paper_id}
                    description={
                      <Space>
                        <span>得分 {item.score ?? '-'}</span>
                        <Tag color={item.passed ? 'green' : 'red'}>{item.passed ? '通过' : '未通过'}</Tag>
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>

      <Card title={`我的证书（${myCerts.length}）`} style={{ marginTop: 16 }}>
        <List
          dataSource={myCerts.slice(0, 3)}
          locale={{ emptyText: '暂无证书' }}
          renderItem={(c) => (
            <List.Item>
              <List.Item.Meta
                title={c.cert_no}
                description={
                  <Space>
                    <Tag color={c.level === 'red' ? 'red' : c.level === 'yellow' ? 'gold' : 'green'}>
                      {c.days_left != null ? `${c.days_left} 天后到期` : '长期有效'}
                    </Tag>
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      </Card>
    </div>
  );
}
