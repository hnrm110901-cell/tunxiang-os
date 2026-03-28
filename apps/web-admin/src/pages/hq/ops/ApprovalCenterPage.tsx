/**
 * 审批中心 — 待审批列表、审批详情、通过/驳回、审批历史
 * 调用 POST /api/v1/approvals/*
 */
import { useState } from 'react';

type ApprovalType = 'discount' | 'refund' | 'price_adjust' | 'exception';
type ApprovalStatus = 'pending' | 'approved' | 'rejected';

interface ApprovalItem {
  id: string;
  type: ApprovalType;
  store: string;
  title: string;
  amount: number;
  submitter: string;
  time: string;
  status: ApprovalStatus;
  detail: string;
}

const TYPE_LABELS: Record<ApprovalType, { label: string; color: string }> = {
  discount: { label: '折扣', color: '#FF6B2C' },
  refund: { label: '退款', color: '#ff4d4f' },
  price_adjust: { label: '调价', color: '#1890ff' },
  exception: { label: '异常', color: '#faad14' },
};

const STATUS_LABELS: Record<ApprovalStatus, { label: string; color: string }> = {
  pending: { label: '待审批', color: '#faad14' },
  approved: { label: '已通过', color: '#52c41a' },
  rejected: { label: '已驳回', color: '#ff4d4f' },
};

const MOCK_ITEMS: ApprovalItem[] = [
  { id: 'A001', type: 'discount', store: '芙蓉路店', title: '会员8折优惠', amount: -3200, submitter: '张店长', time: '14:32', status: 'pending', detail: '老客户王先生消费¥400，申请8折优惠。会员等级：金卡，历史消费38次。折后毛利率52.3%（高于底线45%）。' },
  { id: 'A002', type: 'refund', store: '岳麓店', title: '菜品退款申请', amount: -8800, submitter: '李经理', time: '13:15', status: 'pending', detail: '客户反馈水煮鱼口味偏咸，要求退菜。该桌消费¥320，退菜金额¥88。退菜原因已登记，后厨已知悉。' },
  { id: 'A003', type: 'price_adjust', store: '星沙店', title: '小龙虾定价调整', amount: 0, submitter: '王厨师长', time: '11:20', status: 'pending', detail: '近期小龙虾进价上涨18%，申请将售价从¥128调至¥148。调价后毛利率恢复至62%。' },
  { id: 'A004', type: 'exception', store: '河西店', title: '收银差异报告', amount: -1500, submitter: '刘收银', time: '22:30', status: 'pending', detail: '日结发现现金短款¥15。已核查当班流水，疑似找零错误。附现金清点表和监控截图。' },
  { id: 'A005', type: 'discount', store: '芙蓉路店', title: '团购核销', amount: -5600, submitter: '张店长', time: '昨日', status: 'approved', detail: '美团团购券核销，4人餐原价¥256，团购价¥200。' },
  { id: 'A006', type: 'refund', store: '开福店', title: '出餐超时退款', amount: -4500, submitter: '陈经理', time: '昨日', status: 'rejected', detail: '客户等待35分钟，超出承诺的25分钟。申请全额退款。驳回原因：超时未达标准，建议部分补偿。' },
];

export function ApprovalCenterPage() {
  const [tab, setTab] = useState<'pending' | 'history'>('pending');
  const [typeFilter, setTypeFilter] = useState<ApprovalType | 'all'>('all');
  const [selectedId, setSelectedId] = useState<string | null>(MOCK_ITEMS[0]?.id || null);

  const filtered = MOCK_ITEMS.filter((item) => {
    if (tab === 'pending' && item.status !== 'pending') return false;
    if (tab === 'history' && item.status === 'pending') return false;
    if (typeFilter !== 'all' && item.type !== typeFilter) return false;
    return true;
  });

  const selected = MOCK_ITEMS.find((i) => i.id === selectedId);
  const pendingCount = MOCK_ITEMS.filter((i) => i.status === 'pending').length;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>
          审批中心
          {pendingCount > 0 && (
            <span style={{
              marginLeft: 8, padding: '2px 10px', borderRadius: 10, fontSize: 12,
              background: 'rgba(255,107,44,0.15)', color: '#FF6B2C', fontWeight: 600,
            }}>{pendingCount} 待审</span>
          )}
        </h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['pending', 'history'] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: tab === t ? '#FF6B2C' : '#1a2a33',
              color: tab === t ? '#fff' : '#999',
            }}>{t === 'pending' ? '待审批' : '审批历史'}</button>
          ))}
        </div>
      </div>

      {/* 类型筛选 */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
        <button onClick={() => setTypeFilter('all')} style={{
          padding: '3px 12px', borderRadius: 4, border: 'none', cursor: 'pointer', fontSize: 11,
          background: typeFilter === 'all' ? '#1a2a33' : 'transparent', color: typeFilter === 'all' ? '#fff' : '#666',
        }}>全部</button>
        {(Object.keys(TYPE_LABELS) as ApprovalType[]).map((t) => (
          <button key={t} onClick={() => setTypeFilter(t)} style={{
            padding: '3px 12px', borderRadius: 4, border: 'none', cursor: 'pointer', fontSize: 11,
            background: typeFilter === t ? `${TYPE_LABELS[t].color}20` : 'transparent',
            color: typeFilter === t ? TYPE_LABELS[t].color : '#666',
          }}>{TYPE_LABELS[t].label}</button>
        ))}
      </div>

      {/* 主体：左列表 + 右详情 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* 审批列表 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 16 }}>
          {filtered.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#666', padding: 40 }}>暂无审批记录</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {filtered.map((item) => (
                <div
                  key={item.id}
                  onClick={() => setSelectedId(item.id)}
                  style={{
                    padding: 14, borderRadius: 8, cursor: 'pointer',
                    background: selectedId === item.id ? 'rgba(255,107,44,0.08)' : '#0B1A20',
                    border: selectedId === item.id ? '1px solid #FF6B2C' : '1px solid #1a2a33',
                    transition: 'all .15s',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{
                        padding: '1px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600,
                        background: `${TYPE_LABELS[item.type].color}20`, color: TYPE_LABELS[item.type].color,
                      }}>{TYPE_LABELS[item.type].label}</span>
                      <span style={{ fontSize: 13, fontWeight: 600 }}>{item.title}</span>
                    </div>
                    <span style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 4,
                      background: `${STATUS_LABELS[item.status].color}20`,
                      color: STATUS_LABELS[item.status].color,
                    }}>{STATUS_LABELS[item.status].label}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#666' }}>
                    <span>{item.store} - {item.submitter}</span>
                    <span>{item.time}</span>
                  </div>
                  {item.amount !== 0 && (
                    <div style={{ fontSize: 12, color: item.amount < 0 ? '#ff4d4f' : '#52c41a', marginTop: 4 }}>
                      {item.amount < 0 ? '' : '+'}¥{Math.abs(item.amount / 100).toFixed(2)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 审批详情 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          {selected ? (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
                <div>
                  <span style={{
                    padding: '2px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                    background: `${TYPE_LABELS[selected.type].color}20`,
                    color: TYPE_LABELS[selected.type].color,
                  }}>{TYPE_LABELS[selected.type].label}</span>
                  <h3 style={{ margin: '8px 0 4px', fontSize: 18 }}>{selected.title}</h3>
                  <div style={{ fontSize: 12, color: '#999' }}>
                    {selected.store} | {selected.submitter} | {selected.time}
                  </div>
                </div>
                <span style={{
                  padding: '2px 10px', borderRadius: 4, fontSize: 12,
                  background: `${STATUS_LABELS[selected.status].color}20`,
                  color: STATUS_LABELS[selected.status].color, fontWeight: 600,
                }}>{STATUS_LABELS[selected.status].label}</span>
              </div>

              {selected.amount !== 0 && (
                <div style={{
                  padding: 14, borderRadius: 8, background: '#0B1A20', marginBottom: 16,
                  textAlign: 'center',
                }}>
                  <div style={{ fontSize: 11, color: '#999' }}>涉及金额</div>
                  <div style={{ fontSize: 24, fontWeight: 'bold', color: selected.amount < 0 ? '#ff4d4f' : '#52c41a' }}>
                    {selected.amount < 0 ? '-' : '+'}¥{Math.abs(selected.amount / 100).toFixed(2)}
                  </div>
                </div>
              )}

              <div style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 12, color: '#999', marginBottom: 6 }}>审批详情</div>
                <div style={{
                  padding: 14, borderRadius: 8, background: '#0B1A20',
                  fontSize: 13, color: '#ccc', lineHeight: 1.8,
                }}>
                  {selected.detail}
                </div>
              </div>

              {selected.status === 'pending' && (
                <div style={{ display: 'flex', gap: 12 }}>
                  <button style={{
                    flex: 1, padding: '10px 0', borderRadius: 8, border: 'none',
                    background: '#52c41a', color: '#fff', fontSize: 14, fontWeight: 600,
                    cursor: 'pointer',
                  }}>通过</button>
                  <button style={{
                    flex: 1, padding: '10px 0', borderRadius: 8, border: 'none',
                    background: '#ff4d4f', color: '#fff', fontSize: 14, fontWeight: 600,
                    cursor: 'pointer',
                  }}>驳回</button>
                </div>
              )}
            </>
          ) : (
            <div style={{ textAlign: 'center', color: '#666', padding: 60 }}>选择一条审批记录查看详情</div>
          )}
        </div>
      </div>
    </div>
  );
}
