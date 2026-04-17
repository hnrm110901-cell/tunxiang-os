/**
 * 证书公开验证页 — D11 Nice-to-Have
 * 路由：/public/cert/verify/:certNo （公开，不需登录）
 * 扫码直达，展示证书有效性 + 脱敏持证人信息
 */
import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Card, Spin, Descriptions, Tag } from 'antd';
import apiClient from '../../services/api';

interface VerifyResp {
  valid: boolean;
  cert_no: string;
  holder_name_masked?: string;
  course_name?: string;
  issued_at?: string;
  expire_at?: string;
  status?: string;
  reason?: string;
  message?: string;
}

export default function CertVerify() {
  const { certNo } = useParams<{ certNo: string }>();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<VerifyResp | null>(null);

  useEffect(() => {
    const load = async () => {
      if (!certNo) return;
      try {
        // 公开端点，无需 token；apiClient 会自动带上 token 但后端无校验
        const resp = await apiClient.get(`/public/cert/verify/${certNo}`);
        setData(resp.data);
      } catch (e) {
        setData({ valid: false, cert_no: certNo || '', reason: 'error', message: '验证服务异常' });
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [certNo]);

  const renderStatusIcon = () => {
    if (!data) return null;
    if (data.valid) {
      return (
        <div style={{ fontSize: 80, color: '#52c41a', textAlign: 'center' }}>
          ✅
          <div style={{ fontSize: 24, color: '#52c41a', marginTop: 8 }}>证书有效</div>
        </div>
      );
    }
    if (data.reason === 'revoked') {
      return (
        <div style={{ fontSize: 80, color: '#ff4d4f', textAlign: 'center' }}>
          ⛔
          <div style={{ fontSize: 24, color: '#ff4d4f', marginTop: 8 }}>证书已撤销</div>
        </div>
      );
    }
    if (data.reason === 'expired') {
      return (
        <div style={{ fontSize: 80, color: '#faad14', textAlign: 'center' }}>
          ⏰
          <div style={{ fontSize: 24, color: '#faad14', marginTop: 8 }}>证书已过期</div>
        </div>
      );
    }
    return (
      <div style={{ fontSize: 80, color: '#ff4d4f', textAlign: 'center' }}>
        ❌
        <div style={{ fontSize: 24, color: '#ff4d4f', marginTop: 8 }}>
          {data.message || '证书无效'}
        </div>
      </div>
    );
  };

  return (
    <div style={{ minHeight: '100vh', background: '#f5f5f5', padding: '24px 16px' }}>
      <div style={{ maxWidth: 480, margin: '0 auto' }}>
        <div
          style={{
            background: '#FF6B2C',
            color: '#fff',
            padding: '16px 20px',
            borderRadius: '8px 8px 0 0',
            fontSize: 18,
            fontWeight: 600,
          }}
        >
          屯象OS · 培训证书验证
        </div>
        <Card
          style={{ borderRadius: '0 0 8px 8px', borderTop: 0 }}
          bodyStyle={{ padding: 24 }}
        >
          {loading ? (
            <div style={{ textAlign: 'center', padding: 40 }}>
              <Spin size="large" />
            </div>
          ) : (
            <>
              {renderStatusIcon()}
              {data && data.cert_no && (
                <Descriptions
                  column={1}
                  bordered
                  size="small"
                  style={{ marginTop: 24 }}
                  labelStyle={{ width: 100, background: '#fafafa' }}
                >
                  <Descriptions.Item label="证书编号">{data.cert_no}</Descriptions.Item>
                  {data.holder_name_masked && (
                    <Descriptions.Item label="持证人">{data.holder_name_masked}</Descriptions.Item>
                  )}
                  {data.course_name && (
                    <Descriptions.Item label="课程">{data.course_name}</Descriptions.Item>
                  )}
                  {data.issued_at && (
                    <Descriptions.Item label="颁发日期">
                      {data.issued_at.slice(0, 10)}
                    </Descriptions.Item>
                  )}
                  {data.expire_at && (
                    <Descriptions.Item label="到期日期">
                      {data.expire_at.slice(0, 10)}
                    </Descriptions.Item>
                  )}
                  {data.status && (
                    <Descriptions.Item label="状态">
                      <Tag
                        color={
                          data.status === 'active'
                            ? 'green'
                            : data.status === 'expired'
                            ? 'orange'
                            : 'red'
                        }
                      >
                        {data.status}
                      </Tag>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              )}
              <div style={{ marginTop: 24, textAlign: 'center', color: '#999', fontSize: 12 }}>
                由 屯象OS 智链培训系统 提供验证服务
              </div>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
