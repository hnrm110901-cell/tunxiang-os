import React from 'react';
import { Card, Typography, Tag, Space, Empty } from 'antd';
import { FileTextOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

const MenuImportPage: React.FC = () => {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Space align="center" size="middle">
            <Title level={3} style={{ margin: 0 }}>菜单导入</Title>
            <Tag color="blue">开发中</Tag>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            菜单数据批量导入工具，支持Excel模板与自动校验
          </Paragraph>
        </div>
        <Card>
          <Empty description="功能开发中，敬请期待" />
        </Card>
      </Space>
    </div>
  );
};

export default MenuImportPage;
