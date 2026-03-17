import React from 'react';
import { Card, Typography, Tag, Space, Empty } from 'antd';
import { MonitorOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

const ModelMonitorPage: React.FC = () => {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Space align="center" size="middle">
            <Title level={3} style={{ margin: 0 }}>模型监控</Title>
            <Tag color="blue">开发中</Tag>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            AI模型运行监控，追踪推理延迟、准确率与异常漂移
          </Paragraph>
        </div>
        <Card>
          <Empty description="功能开发中，敬请期待" />
        </Card>
      </Space>
    </div>
  );
};

export default ModelMonitorPage;
