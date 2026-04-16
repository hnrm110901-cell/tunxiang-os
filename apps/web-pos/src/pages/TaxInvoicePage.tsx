/**
 * 税控与票据页面
 * 发票类型选择 → 抬头信息输入 → 税号校验 → 调用税控接口
 */
import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { formatPrice } from '@tx-ds/utils';

/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

const INVOICE_TYPES = [
  { key: 'electronic', label: '电子普票', desc: '电子发票发送至邮箱/手机', icon: 'E' },
  { key: 'paper', label: '纸质普票', desc: '现场打印纸质发票', icon: 'P' },
  { key: 'special', label: '增值税专票', desc: '需提供完整企业信息', icon: 'S' },
];

/** 税号格式校验（15/18/20位数字字母） */
function validateTaxNo(taxNo: string): boolean {
  if (!taxNo) return false;
  return /^[A-Za-z0-9]{15,20}$/.test(taxNo);
}

/** 邮箱格式校验 */
function validateEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

interface InvoiceForm {
  type: string;
  title: string;
  taxNo: string;
  bankName: string;
  bankAccount: string;
  companyAddress: string;
  companyPhone: string;
  receiverEmail: string;
  receiverPhone: string;
  remark: string;
}

const INITIAL_FORM: InvoiceForm = {
  type: '',
  title: '',
  taxNo: '',
  bankName: '',
  bankAccount: '',
  companyAddress: '',
  companyPhone: '',
  receiverEmail: '',
  receiverPhone: '',
  remark: '',
};

export function TaxInvoicePage() {
  const { orderId } = useParams();
  const navigate = useNavigate();

  const [form, setForm] = useState<InvoiceForm>(INITIAL_FORM);
  const [step, setStep] = useState<'type' | 'info' | 'confirm' | 'done'>('type');
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Mock 订单金额
  const orderAmountFen = 35600;

  const updateField = (field: keyof InvoiceForm, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    setErrors((prev) => { const next = { ...prev }; delete next[field]; return next; });
  };

  const handleSelectType = (type: string) => {
    updateField('type', type);
    setStep('info');
  };

  const validate = (): boolean => {
    const errs: Record<string, string> = {};

    if (!form.title.trim()) errs.title = '请输入发票抬头';
    if (!form.taxNo.trim()) {
      errs.taxNo = '请输入税号';
    } else if (!validateTaxNo(form.taxNo)) {
      errs.taxNo = '税号格式不正确（15-20位字母数字）';
    }

    // 专票必填项
    if (form.type === 'special') {
      if (!form.bankName.trim()) errs.bankName = '专票必填开户银行';
      if (!form.bankAccount.trim()) errs.bankAccount = '专票必填银行账号';
      if (!form.companyAddress.trim()) errs.companyAddress = '专票必填公司地址';
      if (!form.companyPhone.trim()) errs.companyPhone = '专票必填公司电话';
    }

    // 电子票必填邮箱或手机
    if (form.type === 'electronic') {
      if (!form.receiverEmail.trim() && !form.receiverPhone.trim()) {
        errs.receiverEmail = '请填写邮箱或手机号';
      } else if (form.receiverEmail.trim() && !validateEmail(form.receiverEmail)) {
        errs.receiverEmail = '邮箱格式不正确';
      }
    }

    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleNext = () => {
    if (validate()) {
      setStep('confirm');
    }
  };

  const handleSubmit = async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      // TODO: 调用税控接口
      // await txFetch(`/api/v1/finance/invoice`, {
      //   method: 'POST',
      //   body: JSON.stringify({
      //     order_id: orderId,
      //     invoice_type: form.type,
      //     title: form.title,
      //     tax_no: form.taxNo,
      //     bank_name: form.bankName,
      //     bank_account: form.bankAccount,
      //     company_address: form.companyAddress,
      //     company_phone: form.companyPhone,
      //     receiver_email: form.receiverEmail,
      //     receiver_phone: form.receiverPhone,
      //     remark: form.remark,
      //     amount_fen: orderAmountFen,
      //   }),
      // });
      await new Promise((r) => setTimeout(r, 800));
      setStep('done');
    } catch (e) {
      alert(`开票失败: ${e instanceof Error ? e.message : '未知错误'}`);
    } finally {
      setSubmitting(false);
    }
  };

  const typeInfo = INVOICE_TYPES.find((t) => t.key === form.type);

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff' }}>
      {/* 左侧 — 步骤 + 订单摘要 */}
      <div style={{ width: 240, background: '#112228', padding: 24, display: 'flex', flexDirection: 'column' }}>
        <h3 style={{ margin: '0 0 20px', fontSize: 20 }}>开具发票</h3>

        {/* 步骤 */}
        {(['type', 'info', 'confirm', 'done'] as const).map((s, i) => {
          const labels = ['选择类型', '填写信息', '确认提交', '完成'];
          const isCurrent = s === step;
          const isPast = ['type', 'info', 'confirm', 'done'].indexOf(step) > i;
          return (
            <div key={s} style={{
              display: 'flex', alignItems: 'center', gap: 12, padding: '10px 12px',
              borderRadius: 8, fontSize: 16, marginBottom: 4,
              background: isCurrent ? '#1A3A48' : 'transparent',
              color: isCurrent ? '#FF6B2C' : isPast ? '#0F6E56' : '#555',
              fontWeight: isCurrent ? 'bold' : 'normal',
            }}>
              <div style={{
                width: 26, height: 26, borderRadius: 13, display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: isCurrent ? '#FF6B2C' : isPast ? '#0F6E56' : '#333',
                color: '#fff', fontSize: 16, fontWeight: 'bold', flexShrink: 0,
              }}>
                {isPast ? '✓' : i + 1}
              </div>
              {labels[i]}
            </div>
          );
        })}

        {/* 订单摘要 */}
        <div style={{ marginTop: 'auto', background: '#0B1A20', borderRadius: 12, padding: 16 }}>
          <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 8 }}>订单信息</div>
          <div style={{ fontSize: 16, marginBottom: 4 }}>订单号: {orderId || '--'}</div>
          <div style={{ fontSize: 20, fontWeight: 'bold', color: '#FF6B2C' }}>开票金额: {fen2yuan(orderAmountFen)}</div>
        </div>

        <button
          onClick={() => navigate(-1)}
          style={{ marginTop: 16, width: '100%', padding: 16, background: '#333', border: 'none', borderRadius: 12, color: '#fff', fontSize: 16, cursor: 'pointer', minHeight: 56 }}
        >
          返回
        </button>
      </div>

      {/* 右侧 — 主区域 */}
      <div style={{ flex: 1, padding: 24, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {/* Step 1: 类型选择 */}
        {step === 'type' && (
          <div style={{ maxWidth: 640, margin: '0 auto' }}>
            <h2 style={{ fontSize: 24, marginBottom: 24 }}>选择发票类型</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {INVOICE_TYPES.map((t) => (
                <button
                  key={t.key}
                  onClick={() => handleSelectType(t.key)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 20, padding: 24,
                    borderRadius: 12, background: '#112B36', border: '2px solid transparent',
                    color: '#fff', cursor: 'pointer', textAlign: 'left',
                    transition: 'transform 200ms ease, border-color 200ms ease',
                    minHeight: 72,
                  }}
                  onPointerDown={(e) => { e.currentTarget.style.transform = 'scale(0.97)'; }}
                  onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                  onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                >
                  <div style={{
                    width: 56, height: 56, borderRadius: 12, background: '#FF6B2C', color: '#fff',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 24, fontWeight: 'bold', flexShrink: 0,
                  }}>
                    {t.icon}
                  </div>
                  <div>
                    <div style={{ fontSize: 20, fontWeight: 'bold', marginBottom: 4 }}>{t.label}</div>
                    <div style={{ fontSize: 16, color: '#8899A6' }}>{t.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Step 2: 信息填写 */}
        {step === 'info' && (
          <div style={{ maxWidth: 640, margin: '0 auto' }}>
            <h2 style={{ fontSize: 24, marginBottom: 8 }}>填写发票信息</h2>
            <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 24 }}>
              发票类型: {typeInfo?.label}
            </div>

            {/* 基本信息 */}
            <FormField
              label="发票抬头" required
              value={form.title}
              onChange={(v) => updateField('title', v)}
              placeholder="请输入发票抬头（公司名称）"
              error={errors.title}
            />
            <FormField
              label="纳税人识别号" required
              value={form.taxNo}
              onChange={(v) => updateField('taxNo', v)}
              placeholder="15-20位字母数字"
              error={errors.taxNo}
            />

            {/* 专票额外字段 */}
            {form.type === 'special' && (
              <>
                <div style={{ fontSize: 18, fontWeight: 'bold', margin: '20px 0 12px', borderTop: '1px solid #333', paddingTop: 20 }}>
                  专票必填信息
                </div>
                <FormField
                  label="开户银行" required
                  value={form.bankName}
                  onChange={(v) => updateField('bankName', v)}
                  placeholder="请输入开户银行"
                  error={errors.bankName}
                />
                <FormField
                  label="银行账号" required
                  value={form.bankAccount}
                  onChange={(v) => updateField('bankAccount', v)}
                  placeholder="请输入银行账号"
                  error={errors.bankAccount}
                />
                <FormField
                  label="公司地址" required
                  value={form.companyAddress}
                  onChange={(v) => updateField('companyAddress', v)}
                  placeholder="请输入公司注册地址"
                  error={errors.companyAddress}
                />
                <FormField
                  label="公司电话" required
                  value={form.companyPhone}
                  onChange={(v) => updateField('companyPhone', v)}
                  placeholder="请输入公司电话"
                  error={errors.companyPhone}
                />
              </>
            )}

            {/* 电子票接收信息 */}
            {form.type === 'electronic' && (
              <>
                <div style={{ fontSize: 18, fontWeight: 'bold', margin: '20px 0 12px', borderTop: '1px solid #333', paddingTop: 20 }}>
                  接收方式（邮箱或手机至少填一个）
                </div>
                <FormField
                  label="接收邮箱"
                  value={form.receiverEmail}
                  onChange={(v) => updateField('receiverEmail', v)}
                  placeholder="example@company.com"
                  error={errors.receiverEmail}
                />
                <FormField
                  label="接收手机"
                  value={form.receiverPhone}
                  onChange={(v) => updateField('receiverPhone', v)}
                  placeholder="手机号"
                  error={errors.receiverPhone}
                />
              </>
            )}

            {/* 备注 */}
            <FormField
              label="备注"
              value={form.remark}
              onChange={(v) => updateField('remark', v)}
              placeholder="可选备注信息"
            />

            <div style={{ display: 'flex', gap: 12, marginTop: 24 }}>
              <button
                onClick={() => setStep('type')}
                style={{ flex: 1, padding: 16, background: '#333', border: 'none', borderRadius: 12, color: '#fff', fontSize: 18, cursor: 'pointer', minHeight: 56 }}
              >
                上一步
              </button>
              <button
                onClick={handleNext}
                style={{
                  flex: 2, padding: 16, background: '#FF6B2C', border: 'none', borderRadius: 12,
                  color: '#fff', fontSize: 18, fontWeight: 'bold', cursor: 'pointer', minHeight: 56,
                  transition: 'transform 200ms ease',
                }}
                onPointerDown={(e) => { e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                下一步
              </button>
            </div>
          </div>
        )}

        {/* Step 3: 确认 */}
        {step === 'confirm' && (
          <div style={{ maxWidth: 640, margin: '0 auto' }}>
            <h2 style={{ fontSize: 24, marginBottom: 24 }}>确认发票信息</h2>

            <div style={{ background: '#112B36', borderRadius: 12, padding: 20, marginBottom: 20 }}>
              <InfoRow label="发票类型" value={typeInfo?.label || '--'} />
              <InfoRow label="发票抬头" value={form.title} />
              <InfoRow label="税号" value={form.taxNo} />
              <InfoRow label="开票金额" value={fen2yuan(orderAmountFen)} highlight />
              {form.type === 'special' && (
                <>
                  <InfoRow label="开户银行" value={form.bankName} />
                  <InfoRow label="银行账号" value={form.bankAccount} />
                  <InfoRow label="公司地址" value={form.companyAddress} />
                  <InfoRow label="公司电话" value={form.companyPhone} />
                </>
              )}
              {form.type === 'electronic' && (
                <>
                  {form.receiverEmail && <InfoRow label="接收邮箱" value={form.receiverEmail} />}
                  {form.receiverPhone && <InfoRow label="接收手机" value={form.receiverPhone} />}
                </>
              )}
              {form.remark && <InfoRow label="备注" value={form.remark} />}
            </div>

            <div style={{ display: 'flex', gap: 12 }}>
              <button
                onClick={() => setStep('info')}
                style={{ flex: 1, padding: 16, background: '#333', border: 'none', borderRadius: 12, color: '#fff', fontSize: 18, cursor: 'pointer', minHeight: 56 }}
              >
                返回修改
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting}
                style={{
                  flex: 2, padding: 16, border: 'none', borderRadius: 12,
                  background: submitting ? '#444' : '#FF6B2C',
                  color: '#fff', fontSize: 20, fontWeight: 'bold',
                  cursor: submitting ? 'not-allowed' : 'pointer', minHeight: 56,
                  transition: 'transform 200ms ease',
                }}
                onPointerDown={(e) => { if (!submitting) e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                {submitting ? '提交中...' : '确认开票'}
              </button>
            </div>
          </div>
        )}

        {/* Step 4: 完成 */}
        {step === 'done' && (
          <div style={{ maxWidth: 480, margin: '0 auto', textAlign: 'center', paddingTop: 40 }}>
            <div style={{
              width: 80, height: 80, borderRadius: 40, background: '#0F6E56', color: '#fff',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 36, fontWeight: 'bold', margin: '0 auto 20px',
            }}>
              ✓
            </div>
            <h2 style={{ fontSize: 24, marginBottom: 8, color: '#0F6E56' }}>开票请求已提交</h2>
            <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 12 }}>
              {form.type === 'electronic'
                ? `电子发票将发送至 ${form.receiverEmail || form.receiverPhone}`
                : form.type === 'paper'
                  ? '纸质发票正在打印，请稍候...'
                  : '增值税专票将在 1-3 个工作日内寄出'
              }
            </div>
            <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 32 }}>
              发票金额: <span style={{ color: '#FF6B2C', fontWeight: 'bold' }}>{fen2yuan(orderAmountFen)}</span>
            </div>
            <button
              onClick={() => navigate(-1)}
              style={{
                padding: '16px 48px', background: '#FF6B2C', border: 'none', borderRadius: 12,
                color: '#fff', fontSize: 18, fontWeight: 'bold', cursor: 'pointer', minHeight: 56,
                transition: 'transform 200ms ease',
              }}
              onPointerDown={(e) => { e.currentTarget.style.transform = 'scale(0.97)'; }}
              onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
            >
              返回
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------- 子组件 ---------- */

function FormField(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  error?: string;
  required?: boolean;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ display: 'block', fontSize: 16, marginBottom: 6, fontWeight: 'bold', color: '#E0E0E0' }}>
        {props.label} {props.required && <span style={{ color: '#A32D2D' }}>*</span>}
      </label>
      <input
        type="text"
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        placeholder={props.placeholder}
        style={{
          width: '100%', padding: 14, fontSize: 18,
          border: props.error ? '2px solid #A32D2D' : '2px solid #333',
          borderRadius: 12, background: '#112228', color: '#fff',
          boxSizing: 'border-box', outline: 'none',
        }}
        onFocus={(e) => { if (!props.error) e.currentTarget.style.borderColor = '#FF6B2C'; }}
        onBlur={(e) => { if (!props.error) e.currentTarget.style.borderColor = '#333'; }}
      />
      {props.error && (
        <div style={{ color: '#A32D2D', fontSize: 16, marginTop: 4 }}>{props.error}</div>
      )}
    </div>
  );
}

function InfoRow(props: { label: string; value: string; highlight?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0', borderBottom: '1px solid #1A3A48', fontSize: 16 }}>
      <span style={{ color: '#8899A6' }}>{props.label}</span>
      <span style={{ fontWeight: props.highlight ? 'bold' : 'normal', color: props.highlight ? '#FF6B2C' : '#fff' }}>
        {props.value}
      </span>
    </div>
  );
}
