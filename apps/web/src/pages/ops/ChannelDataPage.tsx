import React from 'react';
import { Card, Typography, Tag, Space, Empty } from 'antd';
import { NodeIndexOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

const ChannelDataPage: React.FC = () => {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Space align="center" size="middle">
            <Title level={3} style={{ margin: 0 }}>渠道数据</Title>
            <Tag color="blue">开发中</Tag>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            多销售渠道数据汇聚，统一管理堂食、外卖、团购等渠道数据
          </Paragraph>
        </div>
        <Card>
          <Empty description="功能开发中，敬请期待" />
        </Card>
      </Space>
    </div>
  );
};

export default ChannelDataPage;
