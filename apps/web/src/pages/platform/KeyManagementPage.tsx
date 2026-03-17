import React from 'react';
import { Card, Empty } from 'antd';
import { KeyOutlined } from '@ant-design/icons';

const KeyManagementPage: React.FC = () => (
  <div style={{ padding: 0 }}>
    <Card>
      <Empty
        image={<KeyOutlined style={{ fontSize: 48, color: 'rgba(255,255,255,0.15)' }} />}
        description={
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: 'var(--text-primary)' }}>密钥管理</div>
            <div style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>API Key 发放与轮换，保障接口访问安全</div>
          </div>
        }
      />
    </Card>
  </div>
);

export default KeyManagementPage;
