/**
 * city-picker/index.tsx — 城市选择（LBS降级）
 *
 * Features:
 *  - Search bar for city name (live filter)
 *  - Popular cities grid: 10 major cities
 *  - Province accordion: all provinces → cities list
 *  - On select: update location state → navigateBack
 */

import React, { useState, useMemo } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, Input, ScrollView } from '@tarojs/components'

// ─── Brand tokens ─────────────────────────────────────────────────────────────
const C = {
  primary: '#FF6B35',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgHover: '#1A2E38',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#fff',
} as const

// ─── Data ─────────────────────────────────────────────────────────────────────
const POPULAR_CITIES = [
  '北京', '上海', '广州', '深圳', '成都',
  '重庆', '武汉', '长沙', '杭州', '南京',
]

const PROVINCES: Array<{ name: string; cities: string[] }> = [
  {
    name: '北京市',
    cities: ['北京'],
  },
  {
    name: '上海市',
    cities: ['上海'],
  },
  {
    name: '天津市',
    cities: ['天津'],
  },
  {
    name: '重庆市',
    cities: ['重庆'],
  },
  {
    name: '广东省',
    cities: ['广州', '深圳', '东莞', '佛山', '珠海', '汕头', '中山', '江门', '湛江', '惠州', '茂名', '梅州', '肇庆', '韶关', '潮州', '揭阳', '清远', '云浮', '阳江', '河源', '汕尾', '潮南'],
  },
  {
    name: '四川省',
    cities: ['成都', '绵阳', '德阳', '宜宾', '南充', '达州', '遂宁', '乐山', '广安', '泸州', '攀枝花', '眉山', '资阳', '内江', '自贡'],
  },
  {
    name: '湖南省',
    cities: ['长沙', '株洲', '湘潭', '衡阳', '邵阳', '岳阳', '常德', '益阳', '郴州', '永州', '怀化', '娄底', '张家界', '湘西'],
  },
  {
    name: '湖北省',
    cities: ['武汉', '宜昌', '襄阳', '荆州', '十堰', '孝感', '黄石', '荆门', '咸宁', '黄冈', '恩施', '随州', '鄂州', '仙桃', '天门', '潜江'],
  },
  {
    name: '浙江省',
    cities: ['杭州', '宁波', '温州', '绍兴', '金华', '嘉兴', '台州', '湖州', '舟山', '衢州', '丽水'],
  },
  {
    name: '江苏省',
    cities: ['南京', '苏州', '无锡', '南通', '常州', '盐城', '扬州', '徐州', '连云港', '淮安', '泰州', '镇江', '宿迁'],
  },
  {
    name: '山东省',
    cities: ['济南', '青岛', '烟台', '潍坊', '临沂', '淄博', '威海', '济宁', '泰安', '菏泽', '日照', '东营', '滨州', '德州', '聊城', '莱芜'],
  },
  {
    name: '河南省',
    cities: ['郑州', '洛阳', '南阳', '许昌', '新乡', '安阳', '焦作', '开封', '平顶山', '驻马店', '周口', '商丘', '信阳', '漯河', '濮阳', '三门峡', '鹤壁', '济源'],
  },
  {
    name: '河北省',
    cities: ['石家庄', '唐山', '保定', '秦皇岛', '沧州', '邯郸', '邢台', '廊坊', '衡水', '张家口', '承德'],
  },
  {
    name: '陕西省',
    cities: ['西安', '咸阳', '宝鸡', '渭南', '榆林', '延安', '汉中', '铜川', '商洛', '安康'],
  },
  {
    name: '福建省',
    cities: ['福州', '厦门', '泉州', '漳州', '莆田', '三明', '南平', '宁德', '龙岩'],
  },
  {
    name: '安徽省',
    cities: ['合肥', '芜湖', '蚌埠', '阜阳', '安庆', '滁州', '马鞍山', '淮南', '淮北', '铜陵', '宣城', '宿州', '黄山', '亳州', '六安', '池州'],
  },
  {
    name: '江西省',
    cities: ['南昌', '赣州', '上饶', '吉安', '九江', '宜春', '抚州', '新余', '景德镇', '鹰潭', '萍乡'],
  },
  {
    name: '云南省',
    cities: ['昆明', '曲靖', '大理', '红河', '玉溪', '楚雄', '普洱', '保山', '文山', '德宏', '西双版纳', '昭通', '丽江', '临沧'],
  },
  {
    name: '贵州省',
    cities: ['贵阳', '遵义', '毕节', '黔东南', '黔南', '安顺', '铜仁', '六盘水', '黔西南'],
  },
  {
    name: '广西壮族自治区',
    cities: ['南宁', '柳州', '桂林', '梧州', '玉林', '贵港', '百色', '河池', '钦州', '北海', '来宾', '崇左', '防城港', '贺州'],
  },
  {
    name: '辽宁省',
    cities: ['沈阳', '大连', '鞍山', '抚顺', '锦州', '营口', '本溪', '丹东', '阜新', '朝阳', '铁岭', '盘锦', '葫芦岛', '辽阳'],
  },
  {
    name: '吉林省',
    cities: ['长春', '吉林', '四平', '通化', '白城', '延边', '辽源', '白山', '松原'],
  },
  {
    name: '黑龙江省',
    cities: ['哈尔滨', '齐齐哈尔', '大庆', '佳木斯', '牡丹江', '鸡西', '鹤岗', '双鸭山', '绥化', '伊春', '黑河', '七台河', '大兴安岭'],
  },
  {
    name: '山西省',
    cities: ['太原', '大同', '运城', '临汾', '长治', '晋城', '忻州', '晋中', '阳泉', '朔州', '吕梁'],
  },
  {
    name: '内蒙古自治区',
    cities: ['呼和浩特', '包头', '赤峰', '通辽', '鄂尔多斯', '呼伦贝尔', '巴彦淖尔', '乌兰察布', '锡林郭勒', '兴安盟', '阿拉善'],
  },
  {
    name: '新疆维吾尔自治区',
    cities: ['乌鲁木齐', '昌吉', '巴音郭楞', '伊犁', '喀什', '阿克苏', '和田', '哈密', '博尔塔拉', '克孜勒苏', '吐鲁番'],
  },
  {
    name: '甘肃省',
    cities: ['兰州', '天水', '庆阳', '定西', '张掖', '武威', '平凉', '白银', '酒泉', '陇南', '临夏', '甘南', '金昌', '嘉峪关'],
  },
  {
    name: '海南省',
    cities: ['海口', '三亚', '三沙', '儋州'],
  },
  {
    name: '西藏自治区',
    cities: ['拉萨', '日喀则', '昌都', '山南', '林芝', '那曲', '阿里'],
  },
  {
    name: '宁夏回族自治区',
    cities: ['银川', '吴忠', '固原', '中卫', '石嘴山'],
  },
  {
    name: '青海省',
    cities: ['西宁', '海东', '海南', '海北', '黄南', '果洛', '玉树', '海西'],
  },
]

// ─── Types ────────────────────────────────────────────────────────────────────
interface LocationState {
  city: string
  province: string
}

// ─── Main Component ───────────────────────────────────────────────────────────
export default function CityPickerPage() {
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedProvince, setExpandedProvince] = useState<string | null>(null)

  // Filtered results when searching
  const searchResults = useMemo(() => {
    const q = searchQuery.trim()
    if (!q) return []
    const lower = q.toLowerCase()
    const results: Array<{ city: string; province: string }> = []
    for (const p of PROVINCES) {
      for (const city of p.cities) {
        if (city.includes(q) || city.toLowerCase().includes(lower)) {
          results.push({ city, province: p.name })
        }
      }
    }
    return results
  }, [searchQuery])

  function handleSelect(city: string, province?: string) {
    // Persist selection
    const resolvedProvince =
      province ||
      PROVINCES.find((p) => p.cities.includes(city))?.name ||
      ''

    const loc: LocationState = { city, province: resolvedProvince }
    Taro.setStorageSync('tx_selected_city', loc)

    // Notify via event for useLocation store updates
    Taro.eventCenter.trigger('citySelected', loc)

    Taro.showToast({ title: `已切换到${city}`, icon: 'success', duration: 1200 })
    setTimeout(() => Taro.navigateBack(), 1200)
  }

  function toggleProvince(name: string) {
    setExpandedProvince((prev) => (prev === name ? null : name))
  }

  const isSearching = searchQuery.trim().length > 0

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep, display: 'flex', flexDirection: 'column' }}>
      {/* ── Search bar ── */}
      <View
        style={{
          padding: '24rpx 32rpx',
          paddingTop: 'calc(24rpx + env(safe-area-inset-top))',
          background: C.bgCard,
          borderBottom: `1rpx solid ${C.border}`,
        }}
      >
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            background: C.bgHover,
            border: `1rpx solid ${C.border}`,
            borderRadius: '48rpx',
            padding: '0 28rpx',
            height: '80rpx',
            gap: '16rpx',
          }}
        >
          <Text style={{ fontSize: '32rpx', color: C.text3 }}>🔍</Text>
          <Input
            value={searchQuery}
            placeholder="搜索城市名称"
            placeholderStyle={`color: ${C.text3}; font-size: 30rpx;`}
            style={{ flex: 1, fontSize: '30rpx', color: C.text1 }}
            onInput={(e) => setSearchQuery(e.detail.value)}
          />
          {searchQuery.length > 0 && (
            <View
              onClick={() => setSearchQuery('')}
              style={{
                width: '44rpx',
                height: '44rpx',
                borderRadius: '50%',
                background: C.text3,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
              }}
            >
              <Text style={{ fontSize: '24rpx', color: C.bgDeep, lineHeight: '44rpx', textAlign: 'center' }}>✕</Text>
            </View>
          )}
        </View>
      </View>

      {/* ── Content ── */}
      <ScrollView scrollY style={{ flex: 1 }}>
        <View style={{ padding: '32rpx 32rpx calc(60rpx + env(safe-area-inset-bottom))' }}>

          {/* ── Search results ── */}
          {isSearching && (
            <>
              {searchResults.length === 0 ? (
                <View style={{ textAlign: 'center', padding: '80rpx 0' }}>
                  <Text style={{ fontSize: '28rpx', color: C.text3 }}>未找到「{searchQuery}」相关城市</Text>
                </View>
              ) : (
                <View>
                  <Text
                    style={{
                      fontSize: '24rpx',
                      color: C.text3,
                      display: 'block',
                      marginBottom: '16rpx',
                    }}
                  >
                    搜索结果
                  </Text>
                  {searchResults.map(({ city, province }) => (
                    <View
                      key={`${province}-${city}`}
                      onClick={() => handleSelect(city, province)}
                      style={{
                        padding: '28rpx 32rpx',
                        background: C.bgCard,
                        borderRadius: '16rpx',
                        marginBottom: '12rpx',
                        display: 'flex',
                        flexDirection: 'row',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        border: `1rpx solid ${C.border}`,
                        cursor: 'pointer',
                      }}
                    >
                      <Text style={{ fontSize: '30rpx', color: C.text1 }}>{city}</Text>
                      <Text style={{ fontSize: '24rpx', color: C.text3 }}>{province}</Text>
                    </View>
                  ))}
                </View>
              )}
            </>
          )}

          {/* ── Normal state: popular + province list ── */}
          {!isSearching && (
            <>
              {/* Popular cities */}
              <View style={{ marginBottom: '48rpx' }}>
                <Text
                  style={{
                    fontSize: '24rpx',
                    color: C.text3,
                    display: 'block',
                    marginBottom: '20rpx',
                    letterSpacing: '2rpx',
                  }}
                >
                  热门城市
                </Text>
                <View
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(5, 1fr)',
                    gap: '16rpx',
                  }}
                >
                  {POPULAR_CITIES.map((city) => (
                    <View
                      key={city}
                      onClick={() => handleSelect(city)}
                      style={{
                        height: '80rpx',
                        background: C.bgCard,
                        border: `1rpx solid ${C.border}`,
                        borderRadius: '12rpx',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                      }}
                    >
                      <Text style={{ fontSize: '28rpx', color: C.text1 }}>{city}</Text>
                    </View>
                  ))}
                </View>
              </View>

              {/* Province accordion */}
              <Text
                style={{
                  fontSize: '24rpx',
                  color: C.text3,
                  display: 'block',
                  marginBottom: '16rpx',
                  letterSpacing: '2rpx',
                }}
              >
                按省份选择
              </Text>
              <View
                style={{
                  background: C.bgCard,
                  borderRadius: '20rpx',
                  border: `1rpx solid ${C.border}`,
                  overflow: 'hidden',
                }}
              >
                {PROVINCES.map((province, idx) => (
                  <View key={province.name}>
                    {/* Province header */}
                    <View
                      onClick={() => toggleProvince(province.name)}
                      style={{
                        display: 'flex',
                        flexDirection: 'row',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '32rpx 32rpx',
                        borderBottom:
                          expandedProvince !== province.name && idx < PROVINCES.length - 1
                            ? `1rpx solid ${C.border}`
                            : 'none',
                        cursor: 'pointer',
                      }}
                    >
                      <Text
                        style={{
                          fontSize: '30rpx',
                          color: expandedProvince === province.name ? C.primary : C.text1,
                          fontWeight: expandedProvince === province.name ? '600' : '400',
                        }}
                      >
                        {province.name}
                      </Text>
                      <View
                        style={{
                          display: 'flex',
                          flexDirection: 'row',
                          alignItems: 'center',
                          gap: '12rpx',
                        }}
                      >
                        <Text style={{ fontSize: '24rpx', color: C.text3 }}>
                          {province.cities.length}个城市
                        </Text>
                        <Text
                          style={{
                            fontSize: '28rpx',
                            color: C.text3,
                            transform: expandedProvince === province.name ? 'rotate(90deg)' : 'none',
                            transition: 'transform 0.2s',
                          }}
                        >
                          ›
                        </Text>
                      </View>
                    </View>

                    {/* Cities list */}
                    {expandedProvince === province.name && (
                      <View
                        style={{
                          background: C.bgDeep,
                          borderBottom: idx < PROVINCES.length - 1 ? `1rpx solid ${C.border}` : 'none',
                          padding: '20rpx 32rpx',
                          display: 'flex',
                          flexWrap: 'wrap',
                          gap: '16rpx',
                        }}
                      >
                        {province.cities.map((city) => (
                          <View
                            key={city}
                            onClick={() => handleSelect(city, province.name)}
                            style={{
                              padding: '14rpx 28rpx',
                              background: C.bgCard,
                              border: `1rpx solid ${C.border}`,
                              borderRadius: '40rpx',
                              cursor: 'pointer',
                            }}
                          >
                            <Text style={{ fontSize: '28rpx', color: C.text2 }}>{city}</Text>
                          </View>
                        ))}
                      </View>
                    )}
                  </View>
                ))}
              </View>
            </>
          )}
        </View>
      </ScrollView>
    </View>
  )
}
