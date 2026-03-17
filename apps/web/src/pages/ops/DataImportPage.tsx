import React from 'react';
import { Card, Empty } from 'antd';
import { ImportOutlined } from '@ant-design/icons';

const DataImportPage: React.FC = () => (
  <div style={{ padding: 0 }}>
    <Card>
      <Empty
        image={<ImportOutlined style={{ fontSize: 48, color: 'rgba(255,255,255,0.15)' }} />}
        description={
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: 'var(--text-primary)' }}>数据导入</div>
            <div style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>通用数据批量导入，支持多种格式与映射配置</div>
          </div>
        }
      />
    </Card>
  </div>
);

export default DataImportPage;
