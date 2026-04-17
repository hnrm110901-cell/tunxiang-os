/**
 * 我的证书 — D11 Should-Fix P1 + Nice-to-Have（PDF 下载 / 二维码预览）
 * 路由：/hr/my-certificates
 */
import React, { useEffect, useState } from 'react';
import { Card, Row, Col, Tag, Empty, Input, Space, Button, Modal, message } from 'antd';
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
  const [qrModal, setQrModal] = useState<{ open: boolean; cert?: Cert }>({ open: false });

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

  // 公开验证页地址
  const verifyUrl = (certNo: string) => `${window.location.origin}/public/cert/verify/${certNo}`;

  // 下载 PDF（走需登录端点，通过 apiClient 带 token）
  const handleDownloadPdf = async (cert: Cert) => {
    try {
      const resp = await apiClient.get(`/api/v1/hr/training/exam/certificates/${cert.id}/pdf`, {
        responseType: 'blob',
      });
      const blob = new Blob([resp.data], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${cert.cert_no}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      message.error('PDF 下载失败');
    }
  };

  // 二维码图片 URL（走 apiClient baseURL）
  const qrImgSrc = (cert: Cert) =>
    `${apiClient.defaults.baseURL || ''}/api/v1/hr/training/exam/certificates/${cert.id}/qrcode.png?size=320`;

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
                <Space style={{ marginTop: 8 }} wrap>
                  <Button size="small" type="primary" onClick={() => handleDownloadPdf(c)}>
                    下载 PDF
                  </Button>
                  <Button size="small" onClick={() => setQrModal({ open: true, cert: c })}>
                    查看二维码
                  </Button>
                  <a href={verifyUrl(c.cert_no)} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>
                    验证链接
                  </a>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal
        open={qrModal.open}
        title={qrModal.cert ? `证书二维码 · ${qrModal.cert.cert_no}` : '证书二维码'}
        onCancel={() => setQrModal({ open: false })}
        footer={null}
        centered
        width={400}
      >
        {qrModal.cert && (
          <div style={{ textAlign: 'center' }}>
            <img
              src={qrImgSrc(qrModal.cert)}
              alt="证书二维码"
              style={{ width: 320, height: 320, objectFit: 'contain' }}
            />
            <p style={{ marginTop: 12, color: '#666' }}>微信扫一扫验证</p>
            <p style={{ fontSize: 12, color: '#999', wordBreak: 'break-all' }}>
              {verifyUrl(qrModal.cert.cert_no)}
            </p>
          </div>
        )}
      </Modal>
    </div>
  );
}
