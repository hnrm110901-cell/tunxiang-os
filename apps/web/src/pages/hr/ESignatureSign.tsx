/**
 * 电子签约 — 员工端签署页
 * 路由：/hr/e-signature/sign/:envelopeId
 * - 展示信封详情 + 合同预览
 * - Canvas 手写签名
 * - 同意 / 拒签按钮
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { apiClient } from '../../services/api';
import styles from './HRPages.module.css';

interface EnvelopeDetail {
  id: string;
  envelope_no: string;
  subject?: string;
  envelope_status: string;
  records: Array<{
    id: string;
    signer_id: string;
    signer_name?: string;
    signer_role: string;
    status: string;
  }>;
}

const ESignatureSign: React.FC = () => {
  const { envelopeId } = useParams<{ envelopeId: string }>();
  const [userId] = useState<string>(localStorage.getItem('user_id') || '');
  const [detail, setDetail] = useState<EnvelopeDetail | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawingRef = useRef(false);

  const load = useCallback(async () => {
    if (!envelopeId) return;
    const res = await apiClient.get(`/api/v1/hr/e-signature/envelopes/${envelopeId}`);
    setDetail(res.data);
  }, [envelopeId]);

  useEffect(() => { void load(); }, [load]);

  // Canvas 画板事件
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.strokeStyle = '#111';
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';

    const getPos = (e: MouseEvent | TouchEvent) => {
      const rect = canvas.getBoundingClientRect();
      const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX;
      const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY;
      return { x: clientX - rect.left, y: clientY - rect.top };
    };
    const start = (e: MouseEvent | TouchEvent) => {
      drawingRef.current = true;
      const { x, y } = getPos(e);
      ctx.beginPath();
      ctx.moveTo(x, y);
    };
    const move = (e: MouseEvent | TouchEvent) => {
      if (!drawingRef.current) return;
      const { x, y } = getPos(e);
      ctx.lineTo(x, y);
      ctx.stroke();
    };
    const end = () => { drawingRef.current = false; };

    canvas.addEventListener('mousedown', start);
    canvas.addEventListener('mousemove', move);
    canvas.addEventListener('mouseup', end);
    canvas.addEventListener('touchstart', start);
    canvas.addEventListener('touchmove', move);
    canvas.addEventListener('touchend', end);
    return () => {
      canvas.removeEventListener('mousedown', start);
      canvas.removeEventListener('mousemove', move);
      canvas.removeEventListener('mouseup', end);
      canvas.removeEventListener('touchstart', start);
      canvas.removeEventListener('touchmove', move);
      canvas.removeEventListener('touchend', end);
    };
  }, []);

  const clearCanvas = () => {
    const canvas = canvasRef.current;
    if (canvas) canvas.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height);
  };

  const handleSign = async () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const b64 = canvas.toDataURL('image/png').replace(/^data:image\/png;base64,/, '');
    try {
      await apiClient.post(`/api/v1/hr/e-signature/envelopes/${envelopeId}/sign`, {
        signer_id: userId,
        signature_image_base64: b64,
        device_info: navigator.userAgent,
      });
      alert('签署成功');
      void load();
    } catch (e: any) {
      alert(`签署失败：${e?.response?.data?.detail || e?.message}`);
    }
  };

  const handleReject = async () => {
    if (!rejectReason.trim()) {
      alert('请填写拒签原因');
      return;
    }
    try {
      await apiClient.post(`/api/v1/hr/e-signature/envelopes/${envelopeId}/reject`, {
        signer_id: userId,
        reason: rejectReason,
      });
      alert('已拒签');
      void load();
    } catch (e: any) {
      alert(`拒签失败：${e?.response?.data?.detail || e?.message}`);
    }
  };

  if (!detail) return <div className={styles.empty}>加载中...</div>;

  const myRecord = detail.records.find(r => r.signer_id === userId);
  const canSign = myRecord?.status === 'pending'
    && (detail.envelope_status === 'sent' || detail.envelope_status === 'partially_signed');

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>电子签署 · {detail.subject || detail.envelope_no}</h1>
      <div className={styles.card}>
        <p>信封编号：{detail.envelope_no}</p>
        <p>状态：{detail.envelope_status}</p>
        <p>你的身份：{myRecord ? `${myRecord.signer_role} (${myRecord.status})` : '非签署人'}</p>
      </div>

      {canSign ? (
        <>
          <div className={styles.card}>
            <h3>请在下方签名区域手写签名</h3>
            <canvas
              ref={canvasRef}
              width={500}
              height={200}
              style={{ border: '1px solid #ccc', background: '#fff', touchAction: 'none' }}
            />
            <div>
              <button onClick={clearCanvas}>重写</button>
              <button className={styles.primaryBtn} style={{ marginLeft: 8 }} onClick={handleSign}>
                同意并签署
              </button>
            </div>
          </div>

          <div className={styles.card}>
            <h3>或拒绝签署</h3>
            <textarea
              placeholder="请填写拒签原因"
              rows={3}
              value={rejectReason}
              onChange={e => setRejectReason(e.target.value)}
            />
            <button onClick={handleReject} style={{ color: '#EB5757' }}>拒签</button>
          </div>
        </>
      ) : (
        <div className={styles.empty}>
          {myRecord?.status === 'signed' ? '你已签署' :
           myRecord?.status === 'rejected' ? '你已拒签' : '当前状态不允许签署'}
        </div>
      )}
    </div>
  );
};

export default ESignatureSign;
