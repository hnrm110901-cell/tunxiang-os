import React from 'react';
import { Card, Typography, Tag, Space, Empty } from 'antd';
import { NotificationOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

const PushStrategyPage: React.FC = () => {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Space align="center" size="middle">
            <Title level={3} style={{ margin: 0 }}>推送策略</Title>
            <Tag color="blue">开发中</Tag>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            通知推送策略配置，管理推送渠道、频率与智能触达规则
          </Paragraph>
        </div>
        <Card>
          <Empty description="功能开发中，敬请期待" />
        </Card>
      </Space>
    </div>
  );
};

export default PushStrategyPage;
