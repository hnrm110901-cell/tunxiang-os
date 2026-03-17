import React from 'react';
import { Card, Typography, Tag, Space, Empty } from 'antd';
import { LockOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

const DataIsolationPage: React.FC = () => {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Space align="center" size="middle">
            <Title level={3} style={{ margin: 0 }}>数据隔离</Title>
            <Tag color="blue">开发中</Tag>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            多租户数据隔离管理，确保商户数据安全与访问控制
          </Paragraph>
        </div>
        <Card>
          <Empty description="功能开发中，敬请期待" />
        </Card>
      </Space>
    </div>
  );
};

export default DataIsolationPage;
