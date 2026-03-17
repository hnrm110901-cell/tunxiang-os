import React from 'react';
import { Card, Typography, Tag, Space, Empty } from 'antd';
import { DashboardOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

const OpsHomePage: React.FC = () => {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Space align="center" size="middle">
            <Title level={3} style={{ margin: 0 }}>运维控制台</Title>
            <Tag color="blue">开发中</Tag>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            运维总览仪表盘，汇总各子系统运行状态与关键指标
          </Paragraph>
        </div>
        <Card>
          <Empty description="功能开发中，敬请期待" />
        </Card>
      </Space>
    </div>
  );
};

export default OpsHomePage;
