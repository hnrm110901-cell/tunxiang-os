/**
 * ReviewIntelPage — 点评情报页
 * 路由: /hq/market-intel/review-intel
 * 选项卡：自家门店 / 竞对门店
 * 点评列表（评分/情感色块/主题标签/内容预览/平台来源）+ 主题词频柱状图 + 时间筛选
 */
import { useState } from 'react';

// ---- 颜色常量 ----
const BG_1 = '#1a2836';
const BG_2 = '#243442';
const BRAND = '#ff6b2c';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型定义 ----

type ReviewTab = 'own' | 'competitor';
type Platform = '大众点评' | '美团外卖' | '饿了么' | '抖音' | '小红书';
type SentimentType = 'positive' | 'neutral' | 'negative';
type TimeRange = '近7天' | '近30天' | '近90天';

interface Review {
  id: string;
  platform: Platform;
  rating: number;      // 1-5
  sentiment: SentimentType;
  themes: string[];
  content: string;
  date: string;
  storeName: string;
  likeCount: number;
}

interface ThemeFreq {
  keyword: string;
  positiveCount: number;
  negativeCount: number;
}

// ---- Mock 数据 ----

const MOCK_OWN_REVIEWS: Review[] = [
  { id: 'r01', platform: '大众点评', rating: 5, sentiment: 'positive', themes: ['口味好', '食材新鲜', '服务热情'], content: '辣椒炒肉真的超正宗！油不多，腊肉的咸香和辣椒的鲜辣完美融合，比家里做的还好吃。', date: '2026-03-30', storeName: '芙蓉路店', likeCount: 42 },
  { id: 'r02', platform: '美团外卖', rating: 4, sentiment: 'positive', themes: ['打包快', '分量足', '性价比高'], content: '外卖打包挺好的，菜量扎实，39.9一人食套餐非常划算，下班一个人吃刚好。', date: '2026-03-30', storeName: '五一广场店', likeCount: 28 },
  { id: 'r03', platform: '大众点评', rating: 3, sentiment: 'neutral', themes: ['等位时间', '口味偏淡'], content: '菜品整体不错，但等了40分钟才上菜，口味比上次淡了一些，不知道是不是换厨师了。', date: '2026-03-29', storeName: '梅溪湖店', likeCount: 15 },
  { id: 'r04', platform: '抖音', rating: 5, sentiment: 'positive', themes: ['环境好', '拍照好看', '菜品颜值'], content: '被朋友种草来的！环境超适合拍照，剁椒鱼头造型很好看，发了朋友圈收获好多点赞！', date: '2026-03-29', storeName: '万达广场店', likeCount: 156 },
  { id: 'r05', platform: '大众点评', rating: 2, sentiment: 'negative', themes: ['偏贵', '服务一般', '出餐慢'], content: '感觉比之前贵了，加上服务员态度不太好，等了快一个小时，体验很差。', date: '2026-03-28', storeName: '岳麓店', likeCount: 8 },
  { id: 'r06', platform: '小红书', rating: 5, sentiment: 'positive', themes: ['强烈推荐', '猪蹄好吃', '宵夜首选'], content: '强推！卤猪蹄Q弹入味，加班后来一份配米饭绝了。每次来都点这个，已经是老顾客了～', date: '2026-03-28', storeName: '芙蓉路店', likeCount: 89 },
  { id: 'r07', platform: '饿了么', rating: 4, sentiment: 'positive', themes: ['配送及时', '菜不凉', '会再点'], content: '配送速度很快，菜到手还是温热的，比很多外卖强多了。荷叶蒸肉很不错！', date: '2026-03-27', storeName: '星沙店', likeCount: 21 },
  { id: 'r08', platform: '大众点评', rating: 1, sentiment: 'negative', themes: ['卫生问题', '投诉'], content: '在菜里发现了异物，和店员反映态度很差，这种问题不能接受，不会再去了。', date: '2026-03-27', storeName: '开福寺店', likeCount: 3 },
  { id: 'r09', platform: '美团外卖', rating: 5, sentiment: 'positive', themes: ['辣度可调', '口味正宗', '推荐'], content: '特别喜欢这里可以选辣度！中辣刚好，不像有些湘菜店硬塞给你特辣。', date: '2026-03-26', storeName: '河西大学城店', likeCount: 34 },
  { id: 'r10', platform: '大众点评', rating: 4, sentiment: 'positive', themes: ['小孩喜欢', '家庭聚餐', '包间好'], content: '带孩子来吃，有儿童椅，服务员很有耐心。包间安静，适合家庭聚餐。', date: '2026-03-26', storeName: '梅溪湖店', likeCount: 47 },
  { id: 'r11', platform: '抖音', rating: 3, sentiment: 'neutral', themes: ['有点吵', '排队久'], content: '菜是好吃的，但节假日真的太吵了，排队等位45分钟，不知道下次还有没有耐心。', date: '2026-03-25', storeName: '五一广场店', likeCount: 12 },
  { id: 'r12', platform: '大众点评', rating: 5, sentiment: 'positive', themes: ['老顾客', '年年来', '回忆'], content: '吃了5年了，从没让我失望过。辣椒炒肉的味道始终如一，这才是真正的匠心。', date: '2026-03-25', storeName: '芙蓉路店', likeCount: 203 },
];

const MOCK_COMPETITOR_REVIEWS: Review[] = [
  { id: 'cr01', platform: '大众点评', rating: 5, sentiment: 'positive', themes: ['服务极好', '细节感动', '必去'], content: '海底捞的服务真的没话说，等位期间给了零食和美甲，孩子要生日歌他们马上就来，感动到哭。', date: '2026-03-30', storeName: '海底捞·芙蓉路店', likeCount: 512 },
  { id: 'cr02', platform: '美团外卖', rating: 4, sentiment: 'positive', themes: ['新品好吃', '酸汤鲜', '推荐'], content: '试了新出的酸汤肥牛，汤底超鲜，酸辣适中，下次要带朋友一起来。', date: '2026-03-29', storeName: '费大厨·万达店', likeCount: 234 },
  { id: 'cr03', platform: '大众点评', rating: 3, sentiment: 'neutral', themes: ['排队2小时', '翻台快', '感觉赶人'], content: '太二酸菜鱼排了2个小时，鱼的口感还不错，但服务员催得厉害，吃得不舒服。', date: '2026-03-28', storeName: '太二·梅溪湖店', likeCount: 67 },
  { id: 'cr04', platform: '大众点评', rating: 4, sentiment: 'positive', themes: ['装修有格调', '食材好', '西北味'], content: '西贝羊肉质量真的好，烤羊腿很嫩，就是价格有点高。环境不错适合商务请客。', date: '2026-03-27', storeName: '西贝·五一广场店', likeCount: 88 },
  { id: 'cr05', platform: '大众点评', rating: 2, sentiment: 'negative', themes: ['价格贵', '性价比低', '后悔'], content: '海底捞人均130，现在经济不好真的有点贵，同样的钱能在别的地方吃得更好。', date: '2026-03-26', storeName: '海底捞·梅溪湖店', likeCount: 43 },
  { id: 'cr06', platform: '抖音', rating: 5, sentiment: 'positive', themes: ['网红店', '拍照好', '等位值'], content: '费大厨网红爆款辣椒炒肉！肉嫩不柴，辣椒还带点生，火候刚好，难怪天天排队。', date: '2026-03-25', storeName: '费大厨·芙蓉路店', likeCount: 1024 },
];

const MOCK_OWN_THEMES: ThemeFreq[] = [
  { keyword: '口味正宗', positiveCount: 8420, negativeCount: 120 },
  { keyword: '食材新鲜', positiveCount: 7230, negativeCount: 95 },
  { keyword: '服务好', positiveCount: 6840, negativeCount: 680 },
  { keyword: '性价比高', positiveCount: 5920, negativeCount: 340 },
  { keyword: '分量足', positiveCount: 5120, negativeCount: 230 },
  { keyword: '辣度可选', positiveCount: 4360, negativeCount: 180 },
  { keyword: '环境好', positiveCount: 3890, negativeCount: 420 },
  { keyword: '推荐朋友', positiveCount: 3450, negativeCount: 40 },
  { keyword: '出餐速度', positiveCount: 2140, negativeCount: 3820 },
  { keyword: '等位时间', positiveCount: 890, negativeCount: 5640 },
];

const MOCK_COMP_THEMES: ThemeFreq[] = [
  { keyword: '服务体验', positiveCount: 18500, negativeCount: 420 },
  { keyword: '口味', positiveCount: 15200, negativeCount: 1840 },
  { keyword: '价格', positiveCount: 4320, negativeCount: 9870 },
  { keyword: '等位排队', positiveCount: 1230, negativeCount: 12400 },
  { keyword: '食材质量', positiveCount: 14800, negativeCount: 560 },
  { keyword: '环境氛围', positiveCount: 12400, negativeCount: 870 },
  { keyword: '新品创新', positiveCount: 8900, negativeCount: 340 },
  { keyword: '外卖体验', positiveCount: 6700, negativeCount: 2340 },
  { keyword: '性价比', positiveCount: 3400, negativeCount: 8900 },
  { keyword: '翻台催促', positiveCount: 280, negativeCount: 7800 },
];

// ---- 子组件 ----

const platformColors: Record<Platform, string> = {
  '大众点评': RED,
  '美团外卖': YELLOW,
  '饿了么': BLUE,
  '抖音': TEXT_1,
  '小红书': RED,
};

const sentimentConfig: Record<SentimentType, { color: string; label: string; bg: string }> = {
  positive: { color: GREEN, label: '好评', bg: GREEN + '22' },
  neutral: { color: YELLOW, label: '中性', bg: YELLOW + '22' },
  negative: { color: RED, label: '差评', bg: RED + '22' },
};

function StarRating({ rating }: { rating: number }) {
  return (
    <span style={{ fontSize: 13 }}>
      {[1, 2, 3, 4, 5].map(i => (
        <span key={i} style={{ color: i <= rating ? YELLOW : TEXT_4 }}>★</span>
      ))}
    </span>
  );
}

function ReviewCard({ review }: { review: Review }) {
  const s = sentimentConfig[review.sentiment];
  return (
    <div style={{
      background: BG_1, borderRadius: 8, padding: '14px 16px',
      border: `1px solid ${BG_2}`, marginBottom: 10,
      borderLeft: `3px solid ${s.color}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        {/* 评分 */}
        <StarRating rating={review.rating} />
        {/* 情感色块 */}
        <span style={{
          fontSize: 10, padding: '1px 7px', borderRadius: 10,
          background: s.bg, color: s.color, fontWeight: 700,
        }}>{s.label}</span>
        {/* 平台 */}
        <span style={{
          fontSize: 10, padding: '1px 7px', borderRadius: 4,
          color: platformColors[review.platform], fontWeight: 600,
        }}>{review.platform}</span>
        {/* 门店名 */}
        <span style={{ fontSize: 11, color: TEXT_3 }}>{review.storeName}</span>
        <span style={{ fontSize: 11, color: TEXT_4, marginLeft: 'auto' }}>{review.date}</span>
        <span style={{ fontSize: 11, color: TEXT_4 }}>👍 {review.likeCount}</span>
      </div>
      {/* 主题标签 */}
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
        {review.themes.map(theme => (
          <span key={theme} style={{
            fontSize: 11, padding: '2px 8px', borderRadius: 10,
            background: BG_2, color: TEXT_3,
          }}>{theme}</span>
        ))}
      </div>
      {/* 内容预览 */}
      <p style={{ margin: 0, fontSize: 13, color: TEXT_2, lineHeight: 1.7 }}>{review.content}</p>
    </div>
  );
}

function ThemeBarChart({ themes, title }: { themes: ThemeFreq[]; title: string }) {
  const maxVal = Math.max(...themes.map(t => t.positiveCount + t.negativeCount));

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 20px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>{title}</div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
        <span style={{ fontSize: 11, color: GREEN }}>■ 正面提及</span>
        <span style={{ fontSize: 11, color: RED }}>■ 负面提及</span>
      </div>
      {themes.map(theme => {
        const total = theme.positiveCount + theme.negativeCount;
        const posPct = (theme.positiveCount / maxVal) * 100;
        const negPct = (theme.negativeCount / maxVal) * 100;
        const posRatio = theme.positiveCount / total;

        return (
          <div key={theme.keyword} style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
              <span style={{ fontSize: 12, color: TEXT_2, minWidth: 70, flexShrink: 0 }}>{theme.keyword}</span>
              <div style={{ flex: 1, display: 'flex', gap: 2, height: 16, alignItems: 'center' }}>
                {/* 正面条 */}
                <div style={{
                  width: `${posPct}%`, height: '100%', borderRadius: '3px 0 0 3px',
                  background: GREEN + '88', maxWidth: '50%',
                  minWidth: posPct > 1 ? 2 : 0,
                }} />
                {/* 负面条 */}
                <div style={{
                  width: `${negPct}%`, height: '100%', borderRadius: '0 3px 3px 0',
                  background: RED + '88', maxWidth: '50%',
                  minWidth: negPct > 1 ? 2 : 0,
                }} />
              </div>
              <span style={{
                fontSize: 10, minWidth: 32, textAlign: 'right',
                color: posRatio >= 0.8 ? GREEN : posRatio >= 0.5 ? YELLOW : RED,
                fontWeight: 600,
              }}>
                {(posRatio * 100).toFixed(0)}%
              </span>
              <span style={{ fontSize: 10, color: TEXT_4, minWidth: 38, textAlign: 'right' }}>
                {(total / 1000).toFixed(1)}k
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ReviewStats({ reviews }: { reviews: Review[] }) {
  const total = reviews.length;
  const positiveCount = reviews.filter(r => r.sentiment === 'positive').length;
  const avgRating = total > 0 ? reviews.reduce((s, r) => s + r.rating, 0) / total : 0;
  const fiveStarPct = total > 0 ? reviews.filter(r => r.rating === 5).length / total * 100 : 0;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
      {[
        { label: '总评价数', value: total, color: TEXT_1 },
        { label: '平均评分', value: avgRating.toFixed(1) + ' ★', color: YELLOW },
        { label: '好评率', value: total > 0 ? `${((positiveCount / total) * 100).toFixed(0)}%` : '-', color: GREEN },
        { label: '5星占比', value: `${fiveStarPct.toFixed(0)}%`, color: BRAND },
      ].map(item => (
        <div key={item.label} style={{
          background: BG_1, borderRadius: 10, padding: '14px 18px',
          border: `1px solid ${BG_2}`,
        }}>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: item.color }}>{item.value}</div>
        </div>
      ))}
    </div>
  );
}

// ---- 主页面 ----

export function ReviewIntelPage() {
  const [activeTab, setActiveTab] = useState<ReviewTab>('own');
  const [timeRange, setTimeRange] = useState<TimeRange>('近30天');
  const [filterSentiment, setFilterSentiment] = useState<SentimentType | '全部'>('全部');
  const [filterPlatform, setFilterPlatform] = useState<Platform | '全部'>('全部');
  const [page, setPage] = useState(1);
  const pageSize = 10;

  const reviews = activeTab === 'own' ? MOCK_OWN_REVIEWS : MOCK_COMPETITOR_REVIEWS;
  const themes = activeTab === 'own' ? MOCK_OWN_THEMES : MOCK_COMP_THEMES;

  const filteredReviews = reviews
    .filter(r => filterSentiment === '全部' || r.sentiment === filterSentiment)
    .filter(r => filterPlatform === '全部' || r.platform === filterPlatform);

  const totalPages = Math.max(1, Math.ceil(filteredReviews.length / pageSize));
  const pagedReviews = filteredReviews.slice((page - 1) * pageSize, page * pageSize);

  const selectStyle: React.CSSProperties = {
    background: BG_2, border: `1px solid ${BG_2}`, borderRadius: 6,
    color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none', cursor: 'pointer',
  };

  const handleTabChange = (tab: ReviewTab) => {
    setActiveTab(tab);
    setPage(1);
  };

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>点评情报</h2>
      </div>

      {/* 主选项卡 */}
      <div style={{
        display: 'flex', gap: 4, marginBottom: 20,
        background: BG_1, borderRadius: 10, padding: 4,
        width: 'fit-content', border: `1px solid ${BG_2}`,
      }}>
        {([
          { key: 'own', label: '🏠 自家门店' },
          { key: 'competitor', label: '🎯 竞对门店' },
        ] as const).map(tab => (
          <button
            key={tab.key}
            onClick={() => handleTabChange(tab.key)}
            style={{
              padding: '8px 24px', borderRadius: 8, border: 'none', cursor: 'pointer',
              background: activeTab === tab.key ? BRAND : 'transparent',
              color: activeTab === tab.key ? '#fff' : TEXT_3,
              fontSize: 14, fontWeight: 700, transition: 'all .2s',
            }}
          >{tab.label}</button>
        ))}
      </div>

      {/* 统计卡片 */}
      <ReviewStats reviews={reviews} />

      {/* 主体：左侧筛选+列表，右侧词频图 */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        {/* 左侧：筛选 + 列表 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* 筛选栏 */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14,
            padding: '10px 14px', background: BG_1, borderRadius: 8, border: `1px solid ${BG_2}`,
            flexWrap: 'wrap',
          }}>
            <select value={timeRange} onChange={e => setTimeRange(e.target.value as TimeRange)} style={selectStyle}>
              <option>近7天</option>
              <option>近30天</option>
              <option>近90天</option>
            </select>
            <select
              value={filterSentiment}
              onChange={e => { setFilterSentiment(e.target.value as SentimentType | '全部'); setPage(1); }}
              style={selectStyle}
            >
              <option value="全部">全部情感</option>
              <option value="positive">好评</option>
              <option value="neutral">中性</option>
              <option value="negative">差评</option>
            </select>
            <select
              value={filterPlatform}
              onChange={e => { setFilterPlatform(e.target.value as Platform | '全部'); setPage(1); }}
              style={selectStyle}
            >
              <option value="全部">全部平台</option>
              <option>大众点评</option>
              <option>美团外卖</option>
              <option>饿了么</option>
              <option>抖音</option>
              <option>小红书</option>
            </select>
            <span style={{ fontSize: 12, color: TEXT_4, marginLeft: 'auto' }}>
              {filteredReviews.length} 条评价
            </span>
          </div>

          {/* 评价列表 */}
          {pagedReviews.length === 0 ? (
            <div style={{
              padding: '48px 0', textAlign: 'center', background: BG_1, borderRadius: 10,
              color: TEXT_4, fontSize: 14, border: `1px solid ${BG_2}`,
            }}>暂无评价数据</div>
          ) : (
            pagedReviews.map(r => <ReviewCard key={r.id} review={r} />)
          )}

          {/* 分页 */}
          {totalPages > 1 && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 12 }}>
              <button
                disabled={page === 1}
                onClick={() => setPage(p => p - 1)}
                style={{
                  padding: '6px 14px', borderRadius: 6, border: `1px solid ${BG_2}`,
                  background: BG_2, color: page === 1 ? TEXT_4 : TEXT_2,
                  fontSize: 12, cursor: page === 1 ? 'default' : 'pointer',
                }}
              >上一页</button>
              <span style={{ fontSize: 12, color: TEXT_3 }}>
                第 {page} / {totalPages} 页，共 {filteredReviews.length} 条
              </span>
              <button
                disabled={page === totalPages}
                onClick={() => setPage(p => p + 1)}
                style={{
                  padding: '6px 14px', borderRadius: 6, border: `1px solid ${BG_2}`,
                  background: BG_2, color: page === totalPages ? TEXT_4 : TEXT_2,
                  fontSize: 12, cursor: page === totalPages ? 'default' : 'pointer',
                }}
              >下一页</button>
            </div>
          )}
        </div>

        {/* 右侧：词频柱状图 */}
        <div style={{ width: 380, flexShrink: 0 }}>
          <ThemeBarChart
            themes={themes}
            title={activeTab === 'own' ? '自家门店主题词频' : '竞对门店主题词频'}
          />
        </div>
      </div>
    </div>
  );
}
