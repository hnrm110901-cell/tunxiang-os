import React from 'react';
import { Card, Empty } from 'antd';
import { ExportOutlined } from '@ant-design/icons';

const DataExportPage: React.FC = () => (
  <div style={{ padding: 0 }}>
    <Card>
      <Empty
        image={<ExportOutlined style={{ fontSize: 48, color: 'rgba(255,255,255,0.15)' }} />}
        description={
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: 'var(--text-primary)' }}>数据导出</div>
            <div style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>商户数据导出与报表下载，支持定时任务</div>
          </div>
        }
      />
    </Card>
  </div>
);

export default DataExportPage;
