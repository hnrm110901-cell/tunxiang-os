/**
 * 门店选择页 — KDS 启动入口
 *
 * 演示客户：尝在一起（长沙湘菜连锁）
 * 三家门店大按钮选择，进入对应门店 KDS 看板
 *
 * URL 规则：
 *   选择门店后跳转 /board?store=wh&demo=true（演示模式）
 *   或 /board?store=wh（正式模式）
 */
import { useNavigate, useSearchParams } from 'react-router-dom';

const STORES = [
  {
    id: 'wh',
    name: '文化城店',
    subtitle: '长沙市芙蓉区文化城',
    color: '#FF6B35',
    icon: '🍜',
  },
  {
    id: 'lx',
    name: '浏小鲜',
    subtitle: '长沙市开福区浏阳河路',
    color: '#0F6E56',
    icon: '🦞',
  },
  {
    id: 'ya',
    name: '永安店',
    subtitle: '长沙市天心区永安路',
    color: '#185FA5',
    icon: '🥘',
  },
] as const;

export function StoreSelectPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const isDemo = searchParams.get('demo') === 'true';

  const handleSelect = (storeId: string) => {
    const params = new URLSearchParams({ store: storeId });
    if (isDemo) params.set('demo', 'true');
    navigate(`/board?${params.toString()}`);
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        background: '#0D1117',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
        padding: 32,
        gap: 48,
      }}
    >
      {/* 品牌标题 */}
      <div style={{ textAlign: 'center' }}>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 80,
            height: 80,
            borderRadius: 20,
            background: 'linear-gradient(135deg, #FF6B35, #FF8F5E)',
            fontSize: 32,
            fontWeight: 900,
            color: '#fff',
            marginBottom: 20,
            boxShadow: '0 8px 24px rgba(255,107,53,0.4)',
          }}
        >
          屯
        </div>
        <div style={{ fontSize: 32, fontWeight: 700, color: '#fff', letterSpacing: 2 }}>
          后厨出餐系统
        </div>
        <div style={{ fontSize: 18, color: 'rgba(255,255,255,0.45)', marginTop: 10 }}>
          尝在一起 · 请选择门店
        </div>
        {isDemo && (
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              marginTop: 14,
              padding: '6px 18px',
              borderRadius: 20,
              background: 'rgba(255,107,53,0.15)',
              border: '1px solid rgba(255,107,53,0.4)',
              color: '#FF6B35',
              fontSize: 16,
              fontWeight: 600,
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: '#FF6B35',
                display: 'inline-block',
                animation: 'pulse 1.5s infinite',
              }}
            />
            演示模式
          </div>
        )}
      </div>

      {/* 门店选择按钮 */}
      <div
        style={{
          display: 'flex',
          gap: 24,
          flexWrap: 'wrap',
          justifyContent: 'center',
          width: '100%',
          maxWidth: 960,
        }}
      >
        {STORES.map((store) => (
          <StoreButton
            key={store.id}
            store={store}
            onSelect={() => handleSelect(store.id)}
          />
        ))}
      </div>

      {/* 底部提示 */}
      <div style={{ fontSize: 16, color: 'rgba(255,255,255,0.25)', textAlign: 'center' }}>
        {isDemo ? '演示模式 · 自动生成真实订单数据' : '选择门店后进入实时出餐看板'}
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}

function StoreButton({
  store,
  onSelect,
}: {
  store: { id: string; name: string; subtitle: string; color: string; icon: string };
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      onPointerDown={(e) => {
        (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)';
      }}
      onPointerUp={(e) => {
        (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
      }}
      onPointerLeave={(e) => {
        (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
      }}
      style={{
        flex: '1 1 240px',
        minWidth: 240,
        maxWidth: 280,
        minHeight: 200,
        padding: '32px 24px',
        background: '#111827',
        border: `2px solid ${store.color}30`,
        borderRadius: 20,
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        transition: 'transform 200ms ease, box-shadow 200ms ease, border-color 200ms ease',
        boxShadow: `0 4px 24px ${store.color}15`,
      }}
      onMouseEnter={(e) => {
        const el = e.currentTarget as HTMLButtonElement;
        el.style.borderColor = store.color;
        el.style.boxShadow = `0 8px 32px ${store.color}40`;
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget as HTMLButtonElement;
        el.style.borderColor = `${store.color}30`;
        el.style.boxShadow = `0 4px 24px ${store.color}15`;
      }}
    >
      <span style={{ fontSize: 52 }}>{store.icon}</span>
      <div>
        <div
          style={{
            fontSize: 26,
            fontWeight: 700,
            color: '#fff',
            textAlign: 'center',
            marginBottom: 6,
          }}
        >
          {store.name}
        </div>
        <div
          style={{
            fontSize: 16,
            color: 'rgba(255,255,255,0.45)',
            textAlign: 'center',
          }}
        >
          {store.subtitle}
        </div>
      </div>
      <div
        style={{
          marginTop: 8,
          padding: '10px 28px',
          borderRadius: 12,
          background: store.color,
          color: '#fff',
          fontSize: 18,
          fontWeight: 600,
          minHeight: 48,
          display: 'flex',
          alignItems: 'center',
        }}
      >
        进入看板
      </div>
    </button>
  );
}
