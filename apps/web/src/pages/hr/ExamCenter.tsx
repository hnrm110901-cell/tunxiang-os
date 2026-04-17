/**
 * 考试中心 — D11 Should-Fix P1
 *
 * 三列看板：待开始 / 进行中 / 已完成
 * 数据源：GET /api/v1/bff/hr/exam-center/{employee_id}（一次聚合，前端无 N+1）
 * 路由：/hr/exam-center
 */
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Col, Row, Button, List, Tag, message, Space, Input } from 'antd';
import { useNavigate } from 'react-router-dom';
import apiClient from '../../services/api';

interface PendingItem {
  enrollment_id: string;
  course_id: string;
  course_name?: string;
  paper_id: string;
  paper_title?: string;
  duration_min?: number;
  pass_score?: number;
}

interface InProgressItem {
  attempt_id: string;
  paper_id: string;
  paper_title?: string;
  started_at?: string;
  expires_at?: string;
  remaining_sec?: number;
}

interface CompletedItem {
  attempt_id: string;
  paper_title?: string;
  score?: number;
  passed?: boolean;
  submitted_at?: string;
  cert_no?: string;
  cert_expire_at?: string;
}

interface ExamCenterData {
  pending: PendingItem[];
  in_progress: InProgressItem[];
  completed: CompletedItem[];
}

export default function ExamCenter() {
  const navigate = useNavigate();
  const [employeeId, setEmployeeId] = useState<string>(localStorage.getItem('employee_id') || 'E001');
  const [storeId, setStoreId] = useState<string>(localStorage.getItem('store_id') || 'S001');
  const [data, setData] = useState<ExamCenterData>({ pending: [], in_progress: [], completed: [] });
  const [myCerts, setMyCerts] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const loadCenter = useCallback(async () => {
    if (!employeeId) return;
    setLoading(true);
    try {
      const resp = await apiClient.get(`/api/v1/bff/hr/exam-center/${employeeId}`);
      const d = resp.data?.data;
      if (d) setData({
        pending: d.pending || [],
        in_progress: d.in_progress || [],
        completed: d.completed || [],
      });
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '加载考试中心失败');
    } finally {
      setLoading(false);
    }
  }, [employeeId]);

  const loadMyCerts = useCallback(async () => {
    if (!employeeId) return;
    try {
      const resp = await apiClient.get('/api/v1/hr/training/exam/certificates/my', {
        params: { employee_id: employeeId },
      });
      setMyCerts(resp.data?.data || []);
    } catch (e) {
      // 静默
    }
  }, [employeeId]);

  useEffect(() => {
    loadCenter();
    loadMyCerts();
  }, [loadCenter, loadMyCerts]);

  const handleStartPending = async (item: PendingItem) => {
    setLoading(true);
    try {
      const resp = await apiClient.post('/api/v1/hr/training/exam/attempts', {
        paper_id: item.paper_id,
        employee_id: employeeId,
        store_id: storeId,
      });
      const d = resp.data?.data;
      if (d?.id) {
        localStorage.setItem('employee_id', employeeId);
        localStorage.setItem('store_id', storeId);
        navigate(`/hr/exam/take/${item.paper_id}?attempt=${d.id}`);
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '开始考试失败');
    } finally {
      setLoading(false);
    }
  };

  const handleResume = (item: InProgressItem) => {
    navigate(`/hr/exam/take/${item.paper_id}?attempt=${item.attempt_id}`);
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
          <Button loading={loading} onClick={loadCenter}>
            刷新
          </Button>
          <Button onClick={() => navigate('/hr/my-certificates')}>我的证书</Button>
        </Space>
      </Card>

      <Row gutter={16}>
        <Col span={8}>
          <Card title={`待开始（${data.pending.length}）`} size="small">
            <List
              dataSource={data.pending}
              locale={{ emptyText: '暂无待考试卷' }}
              renderItem={(item) => (
                <List.Item
                  actions={[
                    <Button type="link" onClick={() => handleStartPending(item)}>
                      开始
                    </Button>,
                  ]}
                >
                  <List.Item.Meta
                    title={item.paper_title || item.paper_id}
                    description={
                      <Space size="small">
                        {item.course_name && <Tag>{item.course_name}</Tag>}
                        {item.duration_min ? <span>{item.duration_min} 分钟</span> : null}
                        {item.pass_score ? <span>及格 {item.pass_score} 分</span> : null}
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card title={`进行中（${data.in_progress.length}）`} size="small">
            <List
              dataSource={data.in_progress}
              locale={{ emptyText: '无进行中考试' }}
              renderItem={(item) => (
                <List.Item
                  actions={[
                    <Button type="link" onClick={() => handleResume(item)}>
                      继续
                    </Button>,
                  ]}
                >
                  <List.Item.Meta
                    title={item.paper_title || item.paper_id}
                    description={
                      <Space size="small">
                        <Tag color="processing">进行中</Tag>
                        {item.remaining_sec != null ? (
                          <span>剩余 {Math.floor((item.remaining_sec || 0) / 60)} 分</span>
                        ) : null}
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card title={`已完成（${data.completed.length}）`} size="small">
            <List
              dataSource={data.completed}
              locale={{ emptyText: '暂无记录' }}
              renderItem={(item) => (
                <List.Item>
                  <List.Item.Meta
                    title={item.paper_title || item.attempt_id}
                    description={
                      <Space size="small" wrap>
                        <span>得分 {item.score ?? '-'}</span>
                        <Tag color={item.passed ? 'green' : 'red'}>{item.passed ? '通过' : '未通过'}</Tag>
                        {item.cert_no && <Tag color="gold">证书 {item.cert_no}</Tag>}
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
