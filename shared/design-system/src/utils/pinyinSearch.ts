/**
 * 轻量拼音搜索 — 专为餐饮菜单优化
 * 支持全拼 / 首字母 / 混合匹配
 *
 * ~2KB gzipped. 覆盖餐饮常用汉字 400+，无需引入完整拼音库。
 */

// ---------------------------------------------------------------------------
// Compact pinyin map: "char:pinyin" pairs joined by ","
// Covers: 食材、烹饪方式、调味料、菜名常用字、餐饮运营用字
// ---------------------------------------------------------------------------
const PINYIN_DATA =
  '剁:duo,椒:jiao,鱼:yu,头:tou,虾:xia,蟹:xie,龙:long,凤:feng,鸡:ji,鸭:ya,' +
  '鹅:e,牛:niu,羊:yang,猪:zhu,肉:rou,排:pai,骨:gu,蹄:ti,肘:zhou,腩:nan,' +
  '肋:lei,腱:jian,腰:yao,肝:gan,肚:du,肠:chang,血:xue,蛋:dan,豆:dou,腐:fu,' +
  '皮:pi,笋:sun,菇:gu,菌:jun,藕:ou,瓜:gua,茄:qie,葱:cong,姜:jiang,蒜:suan,' +
  '韭:jiu,芹:qin,菜:cai,白:bai,青:qing,红:hong,黄:huang,绿:lv,紫:zi,黑:hei,' +
  '酱:jiang,醋:cu,盐:yan,糖:tang,油:you,酒:jiu,汤:tang,粥:zhou,饭:fan,面:mian,' +
  '粉:fen,米:mi,饼:bing,包:bao,饺:jiao,馄:hun,饨:tun,烧:shao,烤:kao,炒:chao,' +
  '炸:zha,煮:zhu,蒸:zheng,炖:dun,焖:men,煲:bao,卤:lu,拌:ban,腌:yan,熏:xun,' +
  '烩:hui,爆:bao,溜:liu,煎:jian,焗:ju,扒:ba,酿:niang,涮:shuan,火:huo,锅:guo,' +
  '铁:tie,板:ban,石:shi,砂:sha,小:xiao,大:da,老:lao,嫩:nen,鲜:xian,香:xiang,' +
  '辣:la,麻:ma,甜:tian,酸:suan,咸:xian,苦:ku,清:qing,浓:nong,干:gan,湿:shi,' +
  '凉:liang,热:re,冰:bing,温:wen,农:nong,家:jia,口:kou,味:wei,水:shui,活:huo,' +
  '海:hai,河:he,湖:hu,山:shan,林:lin,田:tian,园:yuan,特:te,招:zhao,牌:pai,' +
  '推:tui,荐:jian,新:xin,品:pin,经:jing,典:dian,传:chuan,统:tong,手:shou,' +
  '工:gong,秘:mi,制:zhi,自:zi,选:xuan,套:tao,餐:can,梅:mei,柠:ning,檬:meng,' +
  '橙:cheng,桔:ju,果:guo,汁:zhi,茶:cha,奶:nai,咖:ka,啡:fei,可:ke,乐:le,' +
  '雪:xue,碧:bi,啤:pi,精:jing,基:ji,围:wei,鲈:lu,鲤:li,鲫:ji,鳝:shan,' +
  '鳗:man,鲍:bao,参:shen,翅:chi,燕:yan,窝:wo,松:song,露:lu,笼:long,糕:gao,' +
  '点:dian,心:xin,拼:pin,盘:pan,碟:die,份:fen,位:wei,杯:bei,壶:hu,瓶:ping,' +
  '罐:guan,碗:wan,盅:zhong,金:jin,银:yin,玉:yu,翠:cui,珍:zhen,珠:zhu,宝:bao,' +
  '满:man,堂:tang,彩:cai,福:fu,禄:lu,寿:shou,喜:xi,和:he,顺:shun,丰:feng,' +
  '富:fu,贵:gui,吉:ji,祥:xiang,如:ru,意:yi,太:tai,平:ping,安:an,康:kang,' +
  '德:de,仁:ren,义:yi,礼:li,智:zhi,信:xin,忠:zhong,孝:xiao,美:mei,好:hao,' +
  '佳:jia,优:you,极:ji,至:zhi,上:shang,中:zhong,下:xia,东:dong,西:xi,南:nan,' +
  '北:bei,春:chun,夏:xia,秋:qiu,冬:dong,一:yi,二:er,三:san,四:si,五:wu,' +
  '六:liu,七:qi,八:ba,九:jiu,十:shi,百:bai,千:qian,万:wan,元:yuan,角:jiao,' +
  '号:hao,桌:zhuo,台:tai,厅:ting,房:fang,间:jian,层:ceng,楼:lou,阁:ge,轩:xuan,' +
  '居:ju,坊:fang,馆:guan,店:dian,铺:pu,庄:zhuang,苑:yuan,府:fu,斋:zhai,' +
  '坛:tan,缸:gang,区:qu,的:de,不:bu,了:le,在:zai,是:shi,有:you,个:ge,' +
  '这:zhe,那:na,也:ye,要:yao,我:wo,你:ni,他:ta,她:ta,们:men,什:shen,么:me,' +
  '吃:chi,喝:he,来:lai,去:qu,看:kan,做:zuo,想:xiang,给:gei,到:dao,说:shuo,' +
  '会:hui,能:neng,吗:ma,呢:ne,很:hen,都:dou,就:jiu,还:hai,与:yu,或:huo,' +
  '对:dui,把:ba,被:bei,让:rang,比:bi,最:zui,更:geng,非:fei,常:chang,已:yi,' +
  '正:zheng,请:qing,谢:xie,再:zai,多:duo,少:shao,打:da,开:kai,关:guan,' +
  '加:jia,减:jian,单:dan,双:shuang,全:quan,半:ban,两:liang,几:ji,些:xie,' +
  '每:mei,等:deng,块:kuai,条:tiao,只:zhi,张:zhang,片:pian,粒:li,根:gen,' +
  '支:zhi,串:chuan,道:dao,样:yang,种:zhong,类:lei,组:zu,合:he,配:pei,搭:da,' +
  '装:zhuang,取:qu,送:song,买:mai,卖:mai,付:fu,收:shou,退:tui,换:huan,' +
  '订:ding,约:yue,预:yu,定:ding,客:ke,人:ren,员:yuan,师:shi,傅:fu,长:zhang,' +
  '主:zhu,管:guan,理:li,营:ying,服:fu,务:wu,外:wai,堂:tang,食:shi,早:zao,' +
  '午:wu,晚:wan,宵:xiao,夜:ye,粤:yue,川:chuan,湘:xiang,鲁:lu,苏:su,浙:zhe,' +
  '闽:min,徽:hui,本:ben,帮:bang,京:jing,沪:hu,港:gang,澳:ao,日:ri,韩:han,' +
  '泰:tai,越:yue,印:yin,法:fa,式:shi,国:guo,地:di,方:fang,成:cheng,都:du,' +
  '重:chong,庆:qing,武:wu,汉:han,深:shen,圳:zhen,广:guang,州:zhou,杭:hang,' +
  '苏:su,宁:ning,波:bo,厦:xia,门:men,福:fu,建:jian,浙:zhe,江:jiang,湖:hu,' +
  '北:bei,南:nan,河:he,陕:shan,甘:gan,云:yun,贵:gui,藏:zang,蜀:shu,滇:dian,' +
  '螺:luo,蛳:si,丝:si,麻:ma,辣:la,酸:suan,汤:tang,粿:guo,粄:ban,糍:ci,' +
  '粑:ba,粽:zong,豆:dou,花:hua,腰:yao,筋:jin,蘑:mo,芽:ya,藻:zao,紫:zi,' +
  '菜:cai,萝:luo,卜:bo,番:fan,茄:qie,土:tu,马:ma,铃:ling,薯:shu,芋:yu,' +
  '莲:lian,荷:he,桂:gui,兰:lan,玫:mei,瑰:gui,竹:zhu,芝:zhi,麻:ma,花:hua,' +
  '椒:jiao,桂:gui,皮:pi,八:ba,角:jiao,丁:ding,香:xiang,草:cao,叶:ye,陈:chen,' +
  '年:nian,腊:la,肠:chang,培:pei,根:gen,芝:zhi,士:shi,吐:tu,司:si,披:pi,' +
  '萨:sa,沙:sha,拉:la,蛤:ge,蜊:li,鱿:you,墨:mo,章:zhang,带:dai,扇:shan,' +
  '贝:bei,蚝:hao,蛏:cheng,螃:pang,蟹:xie,生:sheng,蚝:hao,响:xiang,铃:ling,' +
  '鳕:xue,鲑:gui,鲷:diao,鲳:chang,鲶:nian,鲢:lian,鳊:bian,鲿:chang,鲥:shi,' +
  '秋:qiu,刀:dao,黄:huang,鱼:yu,带:dai,鱼:yu,石:shi,斑:ban,桂:gui,鱼:yu,' +
  '多:duo,宝:bao,比:bi,目:mu,罗:luo,非:fei,草:cao,鲤:li,鲫:ji,武:wu,昌:chang,' +
  '鳜:gui,鲟:xun,甲:jia,鱼:yu,娃:wa,牛:niu,蛙:wa,田:tian,鸡:ji,鸽:ge,' +
  '鹌:an,鹑:chun,兔:tu,鹿:lu,驴:lv,狗:gou,胡:hu,萝:luo,卜:bo,芦:lu,' +
  '荟:hui,百:bai,合:he,枸:gou,杞:qi,当:dang,归:gui,黄:huang,芪:qi,党:dang,' +
  '参:shen,枣:zao,桃:tao,核:he,仁:ren,杏:xing,栗:li,葡:pu,萄:tao,荔:li,' +
  '枝:zhi,芒:mang,椰:ye,榴:liu,莲:lian,子:zi,银:yin,耳:er,木:mu,冬:dong,' +
  '瓜:gua,苦:ku,丝:si,南:nan,豇:jiang,蕨:jue,菊:ju,薄:bo,荷:he,苋:xian,' +
  '蕹:weng,芫:yan,荽:sui,薄:bo,荷:he,紫:zi,苏:su,藿:huo,香:xiang,佛:fo,' +
  '跳:tiao,墙:qiang,佛:fo,手:shou,瓜:gua,观:guan,音:yin,素:su';

const PINYIN_MAP: Record<string, string> = {};

// Parse once on module load
PINYIN_DATA.split(',').forEach((entry) => {
  const idx = entry.indexOf(':');
  if (idx > 0) {
    const char = entry.slice(0, idx);
    const pinyin = entry.slice(idx + 1);
    // First occurrence wins (handles duplicate chars with different readings)
    if (!PINYIN_MAP[char]) {
      PINYIN_MAP[char] = pinyin;
    }
  }
});

/**
 * Get full pinyin for a Chinese string.
 * Non-Chinese characters pass through unchanged.
 */
export function getPinyin(text: string): string {
  return Array.from(text)
    .map((ch) => PINYIN_MAP[ch] || ch)
    .join('');
}

/**
 * Get pinyin initials for a Chinese string.
 * "剁椒鱼头" → "djyt"
 */
export function getInitials(text: string): string {
  return Array.from(text)
    .map((ch) => {
      const py = PINYIN_MAP[ch];
      return py ? py[0] : ch;
    })
    .join('');
}

/**
 * Check if a dish name matches a search keyword.
 *
 * Supports:
 *  - Chinese character match: "鱼头" matches "剁椒鱼头"
 *  - Full pinyin match: "duojiaoyutou" matches "剁椒鱼头"
 *  - Initials match: "djyt" matches "剁椒鱼头"
 *  - Mixed partial: "duo" matches "剁椒鱼头"
 */
export function matchesPinyin(dishName: string, keyword: string): boolean {
  if (!keyword) return true;
  const kw = keyword.toLowerCase().trim();
  if (!kw) return true;

  // Direct Chinese character match
  if (dishName.includes(kw)) return true;

  // Full pinyin match (continuous)
  const fullPinyin = getPinyin(dishName).toLowerCase();
  if (fullPinyin.includes(kw)) return true;

  // Initials match
  const initials = getInitials(dishName).toLowerCase();
  if (initials.includes(kw)) return true;

  return false;
}
