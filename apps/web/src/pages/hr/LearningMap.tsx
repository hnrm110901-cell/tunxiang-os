/**
 * 学习地图可视化 — 推荐路径 + 我的进度（横向流程图）
 * 路由: /hr/learning/map
 */
import React, { useEffect, useState } from 'react';
import { Card, Steps, Typography, Button, Empty, message, Spin, Row, Col, Tag } from 'antd';
import { BookOutlined, RocketOutlined } from '@ant-design/icons';
import { apiClient } from '../../services/api';
import { useAuthStore } from '../../stores/authStore';

const { Title, Text } = Typography;

interface PathReco {
  path_id: string;
  code: string;
  name: string;
  description?: string;
  estimated_hours: number;
  course_count: number;
}

interface Progress {
  enrolled: boolean;
  enrollment_id?: string;
  status?: string;
  progress_pct?: number;
  completed_courses?: string[];
  next_course?: any;
  total_courses?: number;
}

const LearningMap: React.FC = () => {
  const user = useAuthStore((s) => s.user);
  const [recos, setRecos] = useState<PathReco[]>([]);
  const [active, setActive] = useState<PathReco | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [loading, setLoading] = useState(false);

  const loadRecos = async () => {
    if (!user?.id) return;
    setLoading(true);
    try {
      const resp = await apiClient.get(`/api/v1/hr/learning/my-paths?employee_id=${user.id}`);
      setRecos(resp.data || []);
    } catch { /* ignore */ } finally { setLoading(false); }
  };

  const openPath = async (p: PathReco) => {
    setActive(p);
    try {
      const resp = await apiClient.get(`/api/v1/hr/learning/my-paths?employee_id=${user?.id}&path_id=${p.path_id}`);
      setProgress(resp.data);
    } catch { setProgress(null); }
  };

  const onEnroll = async () => {
    if (!active || !user?.id) return;
    try {
      await apiClient.post(`/api/v1/hr/learning/paths/${active.path_id}/enroll`, { employee_id: user.id });
      message.success('已加入路径');
      openPath(active);
    } catch { message.error('加入失败'); }
  };

  const onComplete = async (courseId: string) => {
    if (!progress?.enrollment_id) return;
    try {
      await apiClient.post('/api/v1/hr/learning/complete', {
        enrollment_id: progress.enrollment_id,
        course_id: courseId,
      });
      message.success('已完成该课程 +10 学分');
      if (active) openPath(active);
    } catch (e: any) { message.error(e?.response?.data?.detail || '完成失败'); }
  };

  useEffect(() => { loadRecos(); /* eslint-disable-next-line */ }, []);

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}><BookOutlined /> 学习地图</Title>
      {loading ? <Spin /> : recos.length === 0 ? <Empty description="暂无推荐路径" /> : (
        <Row gutter={[16, 16]}>
          {recos.map(r => (
            <Col span={8} key={r.path_id}>
              <Card hoverable onClick={() => openPath(r)}
                title={<><RocketOutlined /> {r.name}</>}
                extra={<Tag color="blue">{r.course_count} 课</Tag>}>
                <Text type="secondary">{r.description || r.code}</Text>
                <div style={{ marginTop: 8 }}><Text>预计 {r.estimated_hours}h</Text></div>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      {active && (
        <Card style={{ marginTop: 24 }} title={`路径：${active.name}`}
          extra={!progress?.enrolled && <Button type="primary" onClick={onEnroll}>加入路径</Button>}>
          {progress?.enrolled ? (
            <>
              <Text>进度：{progress.progress_pct}% · 状态：{progress.status}</Text>
              <Steps
                style={{ marginTop: 16 }}
                current={(progress.completed_courses || []).length}
                items={Array.from({ length: progress.total_courses || 0 }, (_, i) => ({
                  title: `第 ${i + 1} 课`,
                }))}
              />
              {progress.next_course && (
                <div style={{ marginTop: 16 }}>
                  <Text strong>下一门课：</Text>
                  <Text>{progress.next_course.course_id}</Text>
                  <Button style={{ marginLeft: 12 }} onClick={() => onComplete(progress.next_course.course_id)}>
                    标记完成
                  </Button>
                </div>
              )}
            </>
          ) : (
            <Text type="secondary">尚未加入此路径</Text>
          )}
        </Card>
      )}
    </div>
  );
};

export default LearningMap;
