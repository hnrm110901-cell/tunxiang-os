import React from 'react';
import { Card, Empty } from 'antd';
import { AppstoreOutlined } from '@ant-design/icons';

const ModuleAuthPage: React.FC = () => (
  <div style={{ padding: 0 }}>
    <Card>
      <Empty
        image={<AppstoreOutlined style={{ fontSize: 48, color: 'rgba(255,255,255,0.15)' }} />}
        description={
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: 'var(--text-primary)' }}>模块授权</div>
            <div style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>管理商户可用功能模块，按需开通与关闭业务能力</div>
          </div>
        }
      />
    </Card>
  </div>
);

export default ModuleAuthPage;
