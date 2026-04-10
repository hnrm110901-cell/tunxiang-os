/**
 * 协议单位选择器（结算时选择挂账单位）
 *
 * 场景：POS结算 → 选择"挂账" → 弹出此组件 → 选择单位 → 确认
 *
 * TXTouch风格：
 *  - 深色 header (#1E2A3A)
 *  - 所有可点击区域 ≥ 48px
 *  - 最小字体 16px
 *  - 无 Ant Design 依赖
 */
import { useEffect, useRef, useState } from 'react';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

export interface AgreementUnit {
  id: string;
  name: string;
  short_name?: string;
  contact_name?: string;
  contact_phone?: string;
  credit_limit_fen: number;
  credit_used_fen: number;
  available_credit_fen: number;
  balance_fen: number;
  status: 'active' | 'suspended' | 'closed';
}

interface AgreementUnitSelectorProps {
  storeId: string;
  orderAmountFen: number;       // 本次待挂账金额（分）
  tenantId: string;
  onSelect: (unit: AgreementUnit) => void;
  onCancel: () => void;
}

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

// ─── 子组件：单位卡片 ─────────────────────────────────────────────────────────

interface UnitCardProps {
  unit: AgreementUnit;
  selected: boolean;
  orderAmountFen: number;
  onPress: () => void;
}

function UnitCard({ unit, selected, orderAmountFen, onPress }: UnitCardProps) {
  const isOverLimit = orderAmountFen > unit.available_credit_fen;
  const usageRate = unit.credit_limit_fen > 0
    ? unit.credit_used_fen / unit.credit_limit_fen
    : 0;

  let creditColor = '#0F6E56';   // 充足 — 绿
  if (usageRate >= 0.9) creditColor = '#A32D2D';     // 危险 — 红
  else if (usageRate >= 0.7) creditColor = '#BA7517'; // 警告 — 黄

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onPress}
      onKeyDown={(e) => e.key === 'Enter' && onPress()}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        padding: '16px 20px',
        borderRadius: 12,
        background: selected ? '#FFF3ED' : '#FFFFFF',
        border: selected ? '2px solid #FF6B35' : '1px solid #E8E6E1',
        cursor: unit.status !== 'active' ? 'not-allowed' : 'pointer',
        opacity: unit.status !== 'active' ? 0.5 : 1,
        transition: 'border-color 150ms, background 150ms',
        WebkitTapHighlightColor: 'transparent',
        minHeight: 80,
      }}
    >
      {/* 单位名 + 状态 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 18, fontWeight: 600, color: '#2C2C2A' }}>
          {unit.name}
        </span>
        {unit.status === 'suspended' && (
          <span style={{
            fontSize: 12, background: '#A32D2D', color: '#fff',
            padding: '2px 8px', borderRadius: 4,
          }}>已暂停</span>
        )}
        {selected && (
          <span style={{
            fontSize: 14, color: '#FF6B35', fontWeight: 600,
          }}>已选 ✓</span>
        )}
      </div>

      {/* 联系人 */}
      {unit.contact_name && (
        <span style={{ fontSize: 14, color: '#5F5E5A' }}>
          联系人：{unit.contact_name}
          {unit.contact_phone ? `  ${unit.contact_phone}` : ''}
        </span>
      )}

      {/* 额度信息 */}
      <div style={{ display: 'flex', gap: 20, marginTop: 4 }}>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ fontSize: 12, color: '#B4B2A9' }}>可用授信</span>
          <span style={{ fontSize: 16, fontWeight: 600, color: creditColor }}>
            {fen2yuan(unit.available_credit_fen)}
          </span>
        </div>
        {unit.balance_fen !== 0 && (
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span style={{ fontSize: 12, color: '#B4B2A9' }}>账户余额</span>
            <span style={{
              fontSize: 16, fontWeight: 600,
              color: unit.balance_fen >= 0 ? '#0F6E56' : '#A32D2D',
            }}>
              {fen2yuan(unit.balance_fen)}
            </span>
          </div>
        )}
      </div>

      {/* 超限警告 */}
      {isOverLimit && (
        <div style={{
          background: '#FFF3F3',
          border: '1px solid #A32D2D',
          borderRadius: 8,
          padding: '8px 12px',
          fontSize: 14,
          color: '#A32D2D',
          marginTop: 4,
        }}>
          ⚠ 本次挂账 {fen2yuan(orderAmountFen)} 超出可用授信额度 {fen2yuan(unit.available_credit_fen)}
        </div>
      )}
    </div>
  );
}

// ─── 主组件 ───────────────────────────────────────────────────────────────────

export const AgreementUnitSelector: React.FC<AgreementUnitSelectorProps> = ({
  storeId: _storeId,
  orderAmountFen,
  tenantId,
  onSelect,
  onCancel,
}) => {
  const [units, setUnits] = useState<AgreementUnit[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState('');
  const [selectedUnit, setSelectedUnit] = useState<AgreementUnit | null>(null);
  const [confirming, setConfirming] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // 加载协议单位列表
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams({ status: 'active', size: '100' });
        if (keyword) params.set('keyword', keyword);
        const res = await fetch(
          `/api/v1/agreement-units?${params}`,
          { headers: { 'X-Tenant-ID': tenantId } },
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!cancelled) setUnits(json.data?.items ?? []);
      } catch {
        if (!cancelled) setUnits([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [keyword, tenantId]);

  const handleConfirm = () => {
    if (!selectedUnit) return;
    if (selectedUnit.status !== 'active') return;
    if (orderAmountFen > selectedUnit.available_credit_fen) {
      // 超限仍然允许（收银员确认后可以处理），只提示
    }
    setConfirming(false);
    onSelect(selectedUnit);
  };

  const isConfirmDisabled = !selectedUnit || selectedUnit.status !== 'active';

  // ─── 确认界面 ─────────────────────────────────────────────────────────────
  if (confirming && selectedUnit) {
    const isOverLimit = orderAmountFen > selectedUnit.available_credit_fen;
    return (
      <div style={overlayStyle}>
        <div style={sheetStyle}>
          {/* Header */}
          <div style={headerStyle}>
            <button
              onClick={() => setConfirming(false)}
              style={backBtnStyle}
            >
              ← 返回
            </button>
            <span style={{ fontSize: 18, fontWeight: 600, color: '#fff' }}>确认挂账</span>
            <div style={{ width: 72 }} />
          </div>

          {/* 确认内容 */}
          <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 20 }}>
            <div style={confirmRowStyle}>
              <span style={confirmLabelStyle}>挂账单位</span>
              <span style={confirmValueStyle}>{selectedUnit.name}</span>
            </div>
            <div style={confirmRowStyle}>
              <span style={confirmLabelStyle}>本次挂账金额</span>
              <span style={{ ...confirmValueStyle, fontSize: 24, color: '#FF6B35' }}>
                {fen2yuan(orderAmountFen)}
              </span>
            </div>
            <div style={confirmRowStyle}>
              <span style={confirmLabelStyle}>挂账后剩余可用额度</span>
              <span style={{
                ...confirmValueStyle,
                color: isOverLimit ? '#A32D2D' : '#0F6E56',
              }}>
                {fen2yuan(selectedUnit.available_credit_fen - orderAmountFen)}
              </span>
            </div>

            {isOverLimit && (
              <div style={{
                background: '#FFF3F3',
                border: '2px solid #A32D2D',
                borderRadius: 12,
                padding: 16,
                color: '#A32D2D',
                fontSize: 16,
                lineHeight: 1.6,
              }}>
                ⚠ 注意：本次挂账将超出授信额度 {fen2yuan(orderAmountFen - selectedUnit.available_credit_fen)}。
                请确认已取得授权后再继续。
              </div>
            )}
          </div>

          {/* 操作按钮 */}
          <div style={{ padding: '0 24px 32px', display: 'flex', gap: 16 }}>
            <button
              onClick={onCancel}
              style={{
                flex: 1,
                height: 56,
                borderRadius: 12,
                border: '1px solid #E8E6E1',
                background: '#F8F7F5',
                fontSize: 18,
                fontWeight: 600,
                color: '#5F5E5A',
                cursor: 'pointer',
              }}
            >
              取消结算
            </button>
            <button
              onClick={handleConfirm}
              style={{
                flex: 2,
                height: 56,
                borderRadius: 12,
                border: 'none',
                background: isOverLimit ? '#A32D2D' : '#FF6B35',
                fontSize: 18,
                fontWeight: 700,
                color: '#fff',
                cursor: 'pointer',
              }}
            >
              {isOverLimit ? '⚠ 超限确认挂账' : '确认挂账'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ─── 选择界面 ─────────────────────────────────────────────────────────────
  return (
    <div style={overlayStyle}>
      <div style={sheetStyle}>
        {/* Header */}
        <div style={headerStyle}>
          <button onClick={onCancel} style={backBtnStyle}>✕</button>
          <span style={{ fontSize: 18, fontWeight: 600, color: '#fff' }}>
            选择挂账单位
          </span>
          <div style={{ width: 72 }} />
        </div>

        {/* 本次金额提示 */}
        <div style={{
          background: '#FFF3ED',
          padding: '12px 20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottom: '1px solid #E8E6E1',
        }}>
          <span style={{ fontSize: 16, color: '#5F5E5A' }}>本次挂账金额</span>
          <span style={{ fontSize: 20, fontWeight: 700, color: '#FF6B35' }}>
            {fen2yuan(orderAmountFen)}
          </span>
        </div>

        {/* 搜索框 */}
        <div style={{ padding: '16px 20px 8px' }}>
          <input
            ref={searchRef}
            type="text"
            placeholder="搜索单位名称 / 联系人..."
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{
              width: '100%',
              height: 48,
              padding: '0 16px',
              fontSize: 16,
              border: '1px solid #E8E6E1',
              borderRadius: 12,
              background: '#F8F7F5',
              color: '#2C2C2A',
              outline: 'none',
              boxSizing: 'border-box',
            }}
          />
        </div>

        {/* 单位列表 */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch',
          padding: '8px 20px',
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
        }}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: 40, color: '#B4B2A9', fontSize: 16 }}>
              加载中...
            </div>
          ) : units.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 40, color: '#B4B2A9', fontSize: 16 }}>
              {keyword ? `未找到"${keyword}"相关单位` : '暂无协议单位'}
            </div>
          ) : (
            units.map((unit) => (
              <UnitCard
                key={unit.id}
                unit={unit}
                selected={selectedUnit?.id === unit.id}
                orderAmountFen={orderAmountFen}
                onPress={() => {
                  if (unit.status === 'active') setSelectedUnit(unit);
                }}
              />
            ))
          )}
        </div>

        {/* 底部确认 */}
        <div style={{ padding: '16px 20px 32px', borderTop: '1px solid #E8E6E1' }}>
          <button
            disabled={isConfirmDisabled}
            onClick={() => setConfirming(true)}
            style={{
              width: '100%',
              height: 72,
              borderRadius: 16,
              border: 'none',
              background: isConfirmDisabled ? '#E8E6E1' : '#FF6B35',
              color: isConfirmDisabled ? '#B4B2A9' : '#fff',
              fontSize: 20,
              fontWeight: 700,
              cursor: isConfirmDisabled ? 'not-allowed' : 'pointer',
              transition: 'background 150ms',
            }}
          >
            {selectedUnit ? `确认选择「${selectedUnit.name}」` : '请先选择协议单位'}
          </button>
        </div>
      </div>
    </div>
  );
};

// ─── 样式常量 ─────────────────────────────────────────────────────────────────

const overlayStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  background: 'rgba(0,0,0,0.6)',
  display: 'flex',
  alignItems: 'flex-end',
  zIndex: 1000,
};

const sheetStyle: React.CSSProperties = {
  width: '100%',
  maxHeight: '85vh',
  borderRadius: '20px 20px 0 0',
  background: '#FFFFFF',
  display: 'flex',
  flexDirection: 'column',
  overflow: 'hidden',
  boxShadow: '0 -8px 24px rgba(0,0,0,0.12)',
};

const headerStyle: React.CSSProperties = {
  background: '#1E2A3A',
  padding: '16px 20px',
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  flexShrink: 0,
};

const backBtnStyle: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  color: '#fff',
  fontSize: 16,
  cursor: 'pointer',
  padding: '8px 12px',
  minWidth: 72,
  minHeight: 48,
  display: 'flex',
  alignItems: 'center',
};

const confirmRowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  padding: '12px 0',
  borderBottom: '1px solid #F0EDE6',
};

const confirmLabelStyle: React.CSSProperties = {
  fontSize: 16,
  color: '#5F5E5A',
};

const confirmValueStyle: React.CSSProperties = {
  fontSize: 18,
  fontWeight: 600,
  color: '#2C2C2A',
};
