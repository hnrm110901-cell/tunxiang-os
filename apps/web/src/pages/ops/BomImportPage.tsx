import React from 'react';
import { Card, Typography, Tag, Space, Empty } from 'antd';
import { PartitionOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

const BomImportPage: React.FC = () => {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Space align="center" size="middle">
            <Title level={3} style={{ margin: 0 }}>BOM导入</Title>
            <Tag color="blue">开发中</Tag>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            物料清单(BOM)数据导入工具，支持版本管理与差异对比
          </Paragraph>
        </div>
        <Card>
          <Empty description="功能开发中，敬请期待" />
        </Card>
      </Space>
    </div>
  );
};

export default BomImportPage;
