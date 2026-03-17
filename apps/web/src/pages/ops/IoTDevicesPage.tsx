import React from 'react';
import { Card, Typography, Tag, Space, Empty } from 'antd';
import { ClusterOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

const IoTDevicesPage: React.FC = () => {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Space align="center" size="middle">
            <Title level={3} style={{ margin: 0 }}>IoT设备</Title>
            <Tag color="blue">开发中</Tag>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            IoT设备管理，监控门店传感器、边缘网关与设备在线状态
          </Paragraph>
        </div>
        <Card>
          <Empty description="功能开发中，敬请期待" />
        </Card>
      </Space>
    </div>
  );
};

export default IoTDevicesPage;
