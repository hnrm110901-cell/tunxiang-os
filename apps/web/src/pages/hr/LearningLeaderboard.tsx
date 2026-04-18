/**
 * 学习积分排行榜
 * 路由: /hr/learning/leaderboard
 */
import React, { useEffect, useState } from 'react';
import { Card, Table, Typography, Select, Row, Col, Statistic, List, Tag } from 'antd';
import { TrophyOutlined, StarOutlined } from '@ant-design/icons';
import { apiClient } from '../../services/api';
import { useAuthStore } from '../../stores/authStore';

const { Title, Text } = Typography;

const LearningLeaderboard: React.FC = () => {
  const user = useAuthStore((s) => s.user);
  const storeId = user?.store_id || '';
  const [period, setPeriod] = useState('month');
  const [items, setItems] = useState<any[]>([]);
  const [myPoints, setMyPoints] = useState<any>(null);
  const [achievements, setAchievements] = useState<any[]>([]);

  const load = async () => {
    try {
      const resp = await apiClient.get(`/api/v1/hr/learning/leaderboard/${storeId}?period=${period}`);
      setItems(resp.data?.items || []);
    } catch { /* ignore */ }
    if (user?.id) {
      try {
        const mp = await apiClient.get(`/api/v1/hr/learning/points/my?employee_id=${user.id}`);
        setMyPoints(mp.data);
      } catch { /* ignore */ }
      try {
        const ac = await apiClient.get(`/api/v1/hr/learning/achievements/my?employee_id=${user.id}`);
        setAchievements(ac.data?.items || []);
      } catch { /* ignore */ }
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [period, storeId]);

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}><TrophyOutlined /> 学习积分排行榜</Title>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card><Statistic title="我的积分" value={myPoints?.total_points || 0} prefix={<StarOutlined />} /></Card>
        </Col>
        <Col span={18}>
          <Card title="我的徽章" size="small">
            {achievements.length === 0 ? <Text type="secondary">尚无徽章</Text> :
              achievements.map(a => <Tag color="gold" key={a.badge_code}>{a.badge_name}</Tag>)}
          </Card>
        </Col>
      </Row>
      <Card
        title={`门店排行（${storeId || '全部'}）`}
        extra={
          <Select value={period} onChange={setPeriod} options={[
            { value: 'week', label: '本周' },
            { value: 'month', label: '本月' },
            { value: 'quarter', label: '本季' },
            { value: 'year', label: '本年' },
          ]} />
        }
      >
        <Table
          rowKey="employee_id"
          dataSource={items}
          pagination={false}
          columns={[
            { title: '排名', dataIndex: 'rank', width: 80 },
            { title: '员工 ID', dataIndex: 'employee_id' },
            { title: '总积分', dataIndex: 'total_points' },
            { title: '事件数', dataIndex: 'event_count' },
          ]}
        />
      </Card>
      {myPoints?.recent_events?.length > 0 && (
        <Card title="我的近期积分事件" style={{ marginTop: 16 }}>
          <List
            size="small"
            dataSource={myPoints.recent_events}
            renderItem={(e: any) => (
              <List.Item>
                <Text>{e.awarded_at?.slice(0, 16)} — {e.event_type} +{e.points_value}</Text>
                {e.remark && <Text type="secondary"> · {e.remark}</Text>}
              </List.Item>
            )}
          />
        </Card>
      )}
    </div>
  );
};

export default LearningLeaderboard;
