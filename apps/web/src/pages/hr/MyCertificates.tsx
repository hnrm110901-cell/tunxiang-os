/**
 * 我的证书 — D11 Should-Fix P1
 * 路由：/hr/my-certificates
 */
import React, { useEffect, useState } from 'react';
import { Card, Row, Col, Tag, Empty, Input, Space, Button } from 'antd';
import apiClient from '../../services/api';

interface Cert {
  id: string;
  cert_no: string;
  course_id: string;
  issued_at?: string;
  expire_at?: string;
  days_left?: number;
  level: 'red' | 'yellow' | 'green';
  status: string;
  pdf_url?: string;
}

export default function MyCertificates() {
  const [employeeId, setEmployeeId] = useState<string>(localStorage.getItem('employee_id') || 'E001');
  const [certs, setCerts] = useState<Cert[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (!employeeId) return;
    setLoading(true);
    try {
      const resp = await apiClient.get('/api/v1/hr/training/exam/certificates/my', {
        params: { employee_id: employeeId },
      });
      setCerts(resp.data?.data || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const levelColor = (lv: string) => (lv === 'red' ? '#ff4d4f' : lv === 'yellow' ? '#faad14' : '#52c41a');

  // 简单的"二维码"占位：证书编号的验证链接
  const verifyUrl = (certNo: string) => `${window.location.origin}/verify?cert=${certNo}`;

  return (
    <div style={{ padding: 16 }}>
      <h2>我的证书</h2>
      <Space style={{ marginBottom: 16 }}>
        <Input
          addonBefore="员工 ID"
          value={employeeId}
          onChange={(e) => setEmployeeId(e.target.value)}
          style={{ width: 260 }}
        />
        <Button type="primary" loading={loading} onClick={load}>
          查询
        </Button>
      </Space>

      {certs.length === 0 ? (
        <Empty description="暂无证书" />
      ) : (
        <Row gutter={[16, 16]}>
          {certs.map((c) => (
            <Col key={c.id} xs={24} sm={12} md={8}>
              <Card
                title={c.cert_no}
                extra={<Tag color={levelColor(c.level)}>{c.status}</Tag>}
                style={{ borderLeft: `4px solid ${levelColor(c.level)}` }}
              >
                <p style={{ margin: '4px 0' }}>
                  颁发：{c.issued_at ? c.issued_at.slice(0, 10) : '-'}
                </p>
                <p style={{ margin: '4px 0' }}>
                  到期：{c.expire_at ? c.expire_at.slice(0, 10) : '长期有效'}
                </p>
                <p style={{ margin: '4px 0' }}>
                  {c.days_left != null && (
                    <Tag color={levelColor(c.level)}>
                      {c.days_left >= 0 ? `剩余 ${c.days_left} 天` : `已过期 ${-c.days_left} 天`}
                    </Tag>
                  )}
                </p>
                <div style={{ marginTop: 12, fontSize: 12, color: '#666' }}>
                  <a href={verifyUrl(c.cert_no)} target="_blank" rel="noreferrer">
                    扫码验证 / 复制验证链接
                  </a>
                </div>
                {c.pdf_url && (
                  <Button type="link" href={c.pdf_url} target="_blank" style={{ padding: 0 }}>
                    下载 PDF
                  </Button>
                )}
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </div>
  );
}
