/**
 * DishRecommendBanner — AI 个性化菜品推荐横幅
 *
 * 基于桌台人数与历史偏好，展示 AI 推荐菜品横向滚动列表。
 * Sprint 2：菜品智能体 + 客户大脑 POS 层
 */

interface RecommendDish {
  id: string;
  name: string;
  price: number;
  reason: string; // AI推荐理由，如「该桌历史常点」
  isMultiSpec?: boolean; // 是否多规格
}

interface DishRecommendBannerProps {
  tableNo?: string;
  pax?: number;
  dishes?: RecommendDish[];
  onAddDish?: (dishId: string) => void;
  onDismiss?: () => void;
}

const DEFAULT_DISHES: RecommendDish[] = [
  { id: 'd1', name: '蒜蓉蒸鲍鱼', price: 128, reason: '该桌常点蒜蓉系', isMultiSpec: true },
  { id: 'd2', name: '清蒸多宝鱼', price: 188, reason: '6人桌推荐',        isMultiSpec: false },
  { id: 'd3', name: '椒盐濑尿虾', price: 96,  reason: '替代皮皮虾',      isMultiSpec: false },
];

export default function DishRecommendBanner({
  tableNo,
  pax,
  dishes,
  onAddDish,
  onDismiss,
}: DishRecommendBannerProps) {
  const displayDishes = dishes ?? DEFAULT_DISHES;

  return (
    <div
      style={{
        background: 'rgba(109,62,168,.08)',
        border: '1px solid rgba(109,62,168,.2)',
        borderRadius: 10,
        padding: '10px 14px',
        marginBottom: 12,
      }}
    >
      {/* 顶部行 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          marginBottom: 10,
        }}
      >
        <span style={{ fontSize: 16 }}>🤖</span>
        <span style={{ fontSize: 14, fontWeight: 700, color: '#6D3EA8' }}>
          AI 个性化推荐
        </span>
        <span style={{ fontSize: 12, color: '#8A94A4', flex: 1 }}>
          基于该桌{pax ? `${pax}人 ` : ''}人数与历史偏好
          {tableNo ? `（${tableNo}桌）` : ''}
        </span>
        {onDismiss && (
          <button
            onClick={onDismiss}
            aria-label="关闭推荐"
            style={{
              minWidth: 32,
              minHeight: 32,
              background: 'transparent',
              border: 'none',
              color: '#8A94A4',
              fontSize: 18,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: 6,
              padding: 0,
            }}
          >
            ✕
          </button>
        )}
      </div>

      {/* 推荐菜品横向滚动列表 */}
      <div
        style={{
          display: 'flex',
          gap: 10,
          overflowX: 'auto',
          WebkitOverflowScrolling: 'touch',
          paddingBottom: 4,
        }}
      >
        {displayDishes.map((dish) => (
          <div
            key={dish.id}
            style={{
              flexShrink: 0,
              width: 120,
              background: '#fff',
              borderRadius: 8,
              padding: '10px 10px 8px',
              border: '1px solid rgba(109,62,168,.15)',
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
            }}
          >
            {/* 菜名 */}
            <div
              style={{
                fontSize: 14,
                fontWeight: 700,
                color: '#2C2C2A',
                lineHeight: 1.3,
                overflow: 'hidden',
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
              }}
            >
              {dish.name}
            </div>

            {/* 价格 */}
            <div style={{ fontSize: 14, fontWeight: 700, color: '#FF6B35' }}>
              ¥{dish.price}
            </div>

            {/* 推荐理由 tag */}
            <div
              style={{
                display: 'inline-block',
                fontSize: 10,
                padding: '2px 5px',
                borderRadius: 3,
                background: 'rgba(109,62,168,.12)',
                color: '#6D3EA8',
                fontWeight: 600,
                lineHeight: 1.4,
              }}
            >
              {dish.reason}
            </div>

            {/* + 加入按钮 */}
            <button
              onClick={() => onAddDish?.(dish.id)}
              style={{
                marginTop: 4,
                width: '100%',
                minHeight: 44,
                border: 'none',
                borderRadius: 6,
                background: '#FF6B35',
                color: '#fff',
                fontSize: 13,
                fontWeight: 700,
                cursor: 'pointer',
                fontFamily: 'inherit',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 2,
              }}
            >
              + 加入{dish.isMultiSpec ? '…' : ''}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
