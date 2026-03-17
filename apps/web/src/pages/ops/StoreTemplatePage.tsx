import React from 'react';
import { Card, Typography, Tag, Space, Empty } from 'antd';
import { ShopOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

const StoreTemplatePage: React.FC = () => {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Space align="center" size="middle">
            <Title level={3} style={{ margin: 0 }}>门店模板</Title>
            <Tag color="blue">开发中</Tag>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            门店配置模板管理，快速复制标准化配置到新门店
          </Paragraph>
        </div>
        <Card>
          <Empty description="功能开发中，敬请期待" />
        </Card>
      </Space>
    </div>
  );
};

export default StoreTemplatePage;
