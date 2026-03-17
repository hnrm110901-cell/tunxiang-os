import React from 'react';
import { Card, Typography, Tag, Space, Empty } from 'antd';
import { ExperimentOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

const AgentTrainingPage: React.FC = () => {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Space align="center" size="middle">
            <Title level={3} style={{ margin: 0 }}>Agent训练</Title>
            <Tag color="blue">开发中</Tag>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            AI Agent训练管理，配置训练数据集与评估指标
          </Paragraph>
        </div>
        <Card>
          <Empty description="功能开发中，敬请期待" />
        </Card>
      </Space>
    </div>
  );
};

export default AgentTrainingPage;
