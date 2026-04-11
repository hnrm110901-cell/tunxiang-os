/**
 * CustomerBrainPanel — 客户大脑面板
 *
 * 结账视图左侧展示会员画像、偏好、存酒及 AI 行动建议。
 * Sprint 2：菜品智能体 + 客户大脑 POS 层
 */
import { TXButton } from '@tx/touch';

interface CustomerProfile {
  memberId: string;
  name: string;
  level: '钻石' | '金' | '银' | '普通';
  totalSpend: number;  // 累计消费，分
  visitCount: number;
  lastVisitDays: number; // 距上次到店天数
  preferences: string[];  // 偏好标签，如 ['靠窗位', '少辣', '清蒸系']
  avoidances?: string[];  // 忌口
  wineStorage?: { name: string; remainMl: number } | null;
  aiActions: { label: string; type: 'primary' | 'default' | 'dashed' }[];
}

interface CustomerBrainPanelProps {
  profile?: CustomerProfile;
  totalAmount?: number; // 本次消费，分
}

const DEFAULT_PROFILE: CustomerProfile = {
  memberId: 'M-00412',
  name: '王总',
  level: '钻石',
  totalSpend: 4860000,
  visitCount: 12,
  lastVisitDays: 16,
  preferences: ['包间', '清蒸系', '国窖1573'],
  wineStorage: { name: '国窖1573', remainMl: 800 },
  aiActions: [
    { label: '推荐续存 · 享9折', type: 'primary' },
    { label: '📅 预约下次包间',   type: 'default' },
    { label: '📄 自动准备发票',   type: 'dashed' },
  ],
};

const LEVEL_BADGE_STYLE: Record<string, { background: string; color: string; border: string }> = {
  钻石: { background: 'rgba(255,215,0,.15)', color: '#B8860B', border: '1px solid rgba(255,215,0,.5)' },
  金:   { background: 'rgba(255,215,0,.12)', color: '#B8860B', border: '1px solid rgba(255,215,0,.4)' },
  银:   { background: 'rgba(168,168,168,.12)', color: '#808080', border: '1px solid rgba(168,168,168,.4)' },
  普通: { background: 'transparent', color: '#8A94A4', border: '1px solid rgba(138,148,164,.3)' },
};

export default function CustomerBrainPanel({
  profile,
  totalAmount: _totalAmount,
}: CustomerBrainPanelProps) {
  const data = profile ?? DEFAULT_PROFILE;

  if (!profile && !data) {
    return (
      <div
        style={{
          background: 'rgba(109,62,168,.05)',
          border: '1px solid rgba(109,62,168,.15)',
          borderRadius: 12,
          padding: 16,
          marginBottom: 16,
          fontSize: 14,
          color: '#8A94A4',
          textAlign: 'center',
        }}
      >
        未识别会员信息
      </div>
    );
  }

  const badgeStyle = LEVEL_BADGE_STYLE[data.level] ?? LEVEL_BADGE_STYLE['普通'];

  return (
    <div
      style={{
        background: 'rgba(109,62,168,.05)',
        border: '1px solid rgba(109,62,168,.15)',
        borderRadius: 12,
        padding: 16,
        marginBottom: 16,
      }}
    >
      {/* 头部：客户大脑 + 等级 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 10,
        }}
      >
        <span style={{ fontSize: 14, fontWeight: 700, color: '#6D3EA8' }}>
          👤 客户大脑
        </span>
        <span
          style={{
            fontSize: 12,
            fontWeight: 700,
            padding: '2px 8px',
            borderRadius: 4,
            ...badgeStyle,
          }}
        >
          {data.level}会员
        </span>
      </div>

      {/* 姓名 + 会员ID */}
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: '#2C2C2A' }}>
          {data.name}
        </div>
        <div style={{ fontSize: 12, color: '#8A94A4', marginTop: 2 }}>
          会员号 {data.memberId}
        </div>
      </div>

      {/* 数据行 */}
      <div style={{ fontSize: 12, color: '#5F5E5A', marginBottom: 10, display: 'flex', gap: 12 }}>
        <span>累计消费 ¥{Math.round(data.totalSpend / 100)}</span>
        <span>到店{data.visitCount}次 · 上次{data.lastVisitDays}天前</span>
      </div>

      {/* 偏好标签 */}
      {data.preferences.length > 0 && (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 6,
            marginBottom: 10,
          }}
        >
          {data.preferences.map((tag) => (
            <span
              key={tag}
              style={{
                fontSize: 12,
                padding: '3px 8px',
                borderRadius: 4,
                background: 'rgba(109,62,168,.1)',
                color: '#6D3EA8',
                fontWeight: 600,
              }}
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      {/* 忌口 */}
      {data.avoidances && data.avoidances.length > 0 && (
        <div
          style={{
            fontSize: 12,
            color: '#ef4444',
            fontWeight: 600,
            marginBottom: 10,
          }}
        >
          ⚠ 忌{data.avoidances.join('/')}
        </div>
      )}

      {/* 存酒 */}
      {data.wineStorage && (
        <div
          style={{
            fontSize: 12,
            color: '#BA7517',
            fontWeight: 600,
            marginBottom: 12,
          }}
        >
          🍷 {data.wineStorage.name} 余{data.wineStorage.remainMl}ml
        </div>
      )}

      {/* AI 行动建议按钮列表 */}
      {data.aiActions.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {data.aiActions.map((action, i) => (
            <Button
              key={i}
              type={action.type}
              style={{
                width: '100%',
                minHeight: 44,
                fontSize: 14,
                fontWeight: 600,
                textAlign: 'left',
              }}
            >
              {action.label}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
