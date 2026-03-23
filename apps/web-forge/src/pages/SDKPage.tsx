import React from 'react';

const BRAND = '#FF6B2C';

const sdks = [
  {
    lang: 'Python',
    icon: 'PY',
    color: '#3776AB',
    version: '1.2.0',
    install: 'pip install tunxiang-sdk',
    example: `from tunxiang import Client

client = Client(api_key="your-api-key")

# 获取菜品列表
dishes = client.menu.list_dishes(
    store_id="store-001",
    page=1,
    page_size=20
)

for dish in dishes.items:
    print(f"{dish.name} - {dish.price}元")`,
    features: ['类型提示完整', '异步支持 (asyncio)', '自动重试与限流', 'Pydantic 模型'],
  },
  {
    lang: 'Node.js',
    icon: 'JS',
    color: '#339933',
    version: '1.1.0',
    install: 'npm install @tunxiang/sdk',
    example: `import { TunxiangClient } from '@tunxiang/sdk';

const client = new TunxiangClient({
  apiKey: 'your-api-key'
});

// 创建订单
const order = await client.trade.createOrder({
  storeId: 'store-001',
  type: 'dine_in',
  items: [
    { dishId: 'dish-001', quantity: 2 },
    { dishId: 'dish-002', quantity: 1 }
  ]
});

console.log(\`订单号: \${order.id}\`);`,
    features: ['TypeScript 原生', 'ESM & CJS 双模式', 'Promise / Callback', 'Webhook 验签工具'],
  },
  {
    lang: 'Java',
    icon: 'JV',
    color: '#E76F00',
    version: '1.0.0',
    install: `<dependency>
  <groupId>com.tunxiang</groupId>
  <artifactId>tunxiang-sdk</artifactId>
  <version>1.0.0</version>
</dependency>`,
    example: `import com.tunxiang.TunxiangClient;
import com.tunxiang.model.Member;

TunxiangClient client = TunxiangClient.builder()
    .apiKey("your-api-key")
    .build();

// 查询会员
Member member = client.member()
    .getUser("user-001");

System.out.println("积分: " + member.getPoints());`,
    features: ['Java 11+', 'Spring Boot Starter', '连接池管理', 'SLF4J 日志集成'],
  },
];

export default function SDKPage() {
  return (
    <div style={{ maxWidth: 1000, margin: '0 auto', padding: '40px 24px 80px' }}>
      <h1 style={{ fontSize: 28, fontWeight: 700, color: '#111', marginBottom: 8 }}>SDK 下载</h1>
      <p style={{ fontSize: 15, color: '#6b7280', marginBottom: 40 }}>
        选择你熟悉的语言，几行代码即可接入屯象OS全部能力
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
        {sdks.map((sdk) => (
          <div
            key={sdk.lang}
            style={{
              background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12,
              overflow: 'hidden',
            }}
          >
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px', borderBottom: '1px solid #f3f4f6' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{
                  width: 40, height: 40, borderRadius: 10, background: sdk.color,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: '#fff', fontWeight: 800, fontSize: 14,
                }}>{sdk.icon}</div>
                <div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: '#111' }}>{sdk.lang}</div>
                  <div style={{ fontSize: 12, color: '#9ca3af' }}>v{sdk.version}</div>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                {sdk.features.map((f) => (
                  <span key={f} style={{
                    padding: '4px 10px', background: '#f3f4f6', borderRadius: 20,
                    fontSize: 12, color: '#4b5563',
                  }}>{f}</span>
                ))}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>
              {/* Install */}
              <div style={{ padding: 24, borderRight: '1px solid #f3f4f6' }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: '#9ca3af', marginBottom: 10, textTransform: 'uppercase' }}>安装</div>
                <div style={{ background: '#1e293b', borderRadius: 8, padding: '12px 16px' }}>
                  <pre style={{ color: '#e2e8f0', fontSize: 13, fontFamily: '"Fira Code", monospace', margin: 0, whiteSpace: 'pre-wrap' }}>
                    {sdk.install}
                  </pre>
                </div>
              </div>
              {/* Example */}
              <div style={{ padding: 24 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: '#9ca3af', marginBottom: 10, textTransform: 'uppercase' }}>示例代码</div>
                <div style={{ background: '#1e293b', borderRadius: 8, padding: '12px 16px', maxHeight: 220, overflowY: 'auto' }}>
                  <pre style={{ color: '#e2e8f0', fontSize: 12, fontFamily: '"Fira Code", monospace', margin: 0, lineHeight: 1.6 }}>
                    {sdk.example}
                  </pre>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
