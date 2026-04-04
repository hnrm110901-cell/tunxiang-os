// 大厨详情 + 点菜页
// API: GET /api/v1/trade/chef-at-home/chefs/{chef_id}
//      GET /api/v1/trade/chef-at-home/menu?chef_id=
//      GET /api/v1/trade/chef-at-home/chefs/{chef_id}/reviews
var api = require('../../../utils/api.js');

// 降级Mock数据（4位大厨）
var MOCK_CHEFS = {
  'mock-chef-001': {
    id: 'mock-chef-001',
    name: '陈师傅',
    title: '粤菜行政总厨',
    slogan: '30年粤菜经验，细火慢炖，鲜味留住。曾任五星酒店行政总厨，擅长传统粤式烹饪与现代创意菜品结合，多次获得行业大赛金奖，致力于将酒楼品质带入千家万户。',
    avatar: '/assets/chef-default.png',
    rating: 4.9,
    approval_rate: 98,
    total_services: 312,
    years_experience: 30,
    cuisine_types: ['粤菜', '海鲜', '广式早茶'],
    specialties: ['清蒸石斑鱼', '白切鸡', '脆皮烧鹅', '虾饺皇'],
    base_fee_fen: 80000,
    min_spend_fen: 200000,
    max_guests: 30,
    service_area: '长沙市全区',
    service_radius_km: 15,
    honors: ['粤菜金牌厨师', '中国烹饪协会会员', '五星服务认证'],
    available_slots: ['上午 10:00-12:00', '下午 14:00-17:00', '晚上 17:00-21:00'],
    status: 'available',
    signature_dishes: [
      { id: 's001', name: '清蒸石斑鱼', image: '', price_fen: 38800 },
      { id: 's002', name: '白切鸡', image: '', price_fen: 15800 },
      { id: 's003', name: '脆皮烧鹅', image: '', price_fen: 22800 },
      { id: 's004', name: '虾饺皇', image: '', price_fen: 12800 },
    ],
  },
  'mock-chef-002': {
    id: 'mock-chef-002',
    name: '张大厨',
    title: '川菜技术总监',
    slogan: '麻辣鲜香，正宗川味，让你家宴也能有大酒楼的味道。18年川菜从业经验，师从川菜泰斗，精通正宗四川传统烹饪技法，尤其擅长水煮系列和传统红烧菜品。',
    avatar: '/assets/chef-default.png',
    rating: 4.8,
    approval_rate: 96,
    total_services: 248,
    years_experience: 18,
    cuisine_types: ['川菜', '家常菜'],
    specialties: ['水煮鱼', '夫妻肺片', '麻婆豆腐', '红烧肉'],
    base_fee_fen: 60000,
    min_spend_fen: 150000,
    max_guests: 25,
    service_area: '长沙市内（芙蓉/雨花/天心/岳麓）',
    service_radius_km: 10,
    honors: ['川菜烹饪大赛金奖', '国家高级厨师资格'],
    available_slots: ['下午 14:00-17:00', '晚上 17:00-21:00'],
    status: 'available',
    signature_dishes: [
      { id: 's101', name: '水煮鱼', image: '', price_fen: 18800 },
      { id: 's102', name: '夫妻肺片', image: '', price_fen: 8800 },
      { id: 's103', name: '麻婆豆腐', image: '', price_fen: 6800 },
    ],
  },
};

// Mock用户评价
var MOCK_REVIEWS = [
  { id: 'r001', customer_name: '李*生', customer_avatar: '', rating: 5, content: '陈师傅手艺真的一绝！清蒸石斑鱼鲜嫩无比，全家都很满意。服务态度也非常好，提前到达就开始准备了。', images: [], created_at: '2026-03-28' },
  { id: 'r002', customer_name: '王*华', customer_avatar: '', rating: 5, content: '第二次预约了，朋友聚会，菜品比上次还丰盛，强烈推荐白切鸡！', images: [], created_at: '2026-03-22' },
  { id: 'r003', customer_name: '张*', customer_avatar: '', rating: 4, content: '整体很棒，烧鹅皮很脆。不过上菜速度可以再快一点，人多的时候后面几道菜等了一会儿。', images: [], created_at: '2026-03-15' },
  { id: 'r004', customer_name: '赵*敏', customer_avatar: '', rating: 5, content: '家宴首选！老人小孩都吃得很开心，师傅还根据我们的口味做了调整，非常贴心。', images: [], created_at: '2026-03-10' },
  { id: 'r005', customer_name: '刘*强', customer_avatar: '', rating: 5, content: '公司团建点的大厨到家，比去饭店方便多了，菜品质量很高，同事们都赞不绝口。', images: [], created_at: '2026-03-05' },
  { id: 'r006', customer_name: '孙*', customer_avatar: '', rating: 4, content: '味道很好，就是价格稍贵，但考虑到是上门服务，性价比还是不错的。', images: [], created_at: '2026-02-28' },
  { id: 'r007', customer_name: '周*琳', customer_avatar: '', rating: 5, content: '生日派对请的大厨，朋友们都很惊喜。虾饺做得跟茶楼一模一样！', images: [], created_at: '2026-02-20' },
  { id: 'r008', customer_name: '吴*', customer_avatar: '', rating: 5, content: '师傅人很好，还教了我们几道简单的粤菜做法，下次还找陈师傅。', images: [], created_at: '2026-02-15' },
  { id: 'r009', customer_name: '郑*飞', customer_avatar: '', rating: 4, content: '菜品不错，就是希望菜单选择能更多一些，比如增加几道甜品。', images: [], created_at: '2026-02-08' },
  { id: 'r010', customer_name: '陈*', customer_avatar: '', rating: 5, content: '过年家宴，全家二十多口人的年夜饭，师傅一个人全搞定了，太厉害了！', images: [], created_at: '2026-02-01' },
];

var MOCK_MENUS = {
  'mock-chef-001': [
    { id: 'd001', name: '清蒸石斑鱼', category_id: 'cat-seafood', category_name: '海鲜', price_fen: 38800, description: '新鲜活宰，清蒸保留原汁原味', image: '', tags: ['招牌', '低脂'] },
    { id: 'd002', name: '白切鸡（例）', category_id: 'cat-poultry', category_name: '禽类', price_fen: 15800, description: '走地鸡，皮脆肉嫩', image: '', tags: ['招牌'] },
    { id: 'd003', name: '脆皮烧鹅', category_id: 'cat-poultry', category_name: '禽类', price_fen: 22800, description: '炭烤脆皮，锁住肉汁', image: '', tags: [] },
    { id: 'd004', name: '清炒时蔬', category_id: 'cat-veg', category_name: '素菜', price_fen: 5800, description: '时令蔬菜，清爽可口', image: '', tags: ['素食'] },
    { id: 'd005', name: '蒜蓉粉丝蒸扇贝', category_id: 'cat-seafood', category_name: '海鲜', price_fen: 28800, description: '每只鲜贝饱满，蒜香四溢', image: '', tags: [] },
    { id: 'd006', name: '老火靓汤（例）', category_id: 'cat-soup', category_name: '汤品', price_fen: 12800, description: '食材按季节变换，慢火4小时', image: '', tags: ['热门'] },
  ],
  'mock-chef-002': [
    { id: 'd101', name: '水煮鱼', category_id: 'cat-fish', category_name: '鱼类', price_fen: 18800, description: '麻辣鲜香，鱼片嫩滑', image: '', tags: ['招牌', '辣'] },
    { id: 'd102', name: '夫妻肺片', category_id: 'cat-cold', category_name: '凉菜', price_fen: 8800, description: '精选牛肉牛杂，红油调味', image: '', tags: ['凉菜', '辣'] },
    { id: 'd103', name: '麻婆豆腐', category_id: 'cat-hot', category_name: '热菜', price_fen: 6800, description: '嫩豆腐配牛肉末，麻辣烫口', image: '', tags: ['辣', '家常'] },
    { id: 'd104', name: '红烧肉', category_id: 'cat-hot', category_name: '热菜', price_fen: 9800, description: '五花肉慢炖2小时，肥而不腻', image: '', tags: ['招牌'] },
  ],
};

Page({
  data: {
    chefId: '',
    chef: null,
    loading: true,
    loadError: false,

    // 菜单
    menuCategories: [],      // [{id, name, count}]
    allDishes: [],           // 全部菜品
    filteredDishes: [],      // 当前分类菜品
    selectedCategory: '',
    loadingMenu: false,

    // 已选菜品 {dish_id: {id, name, price_fen, quantity}}
    selectedDishes: [],       // 展示用列表（从cartMap同步）
    totalDishCount: 0,
    totalDishPrice: 0,

    // 购物车展开状态
    cartExpanded: false,

    // 个人简介展开
    bioExpanded: false,

    // 代表作品
    signatureDishes: [],

    // 用户评价
    reviews: [],
    loadingReviews: false,
    reviewsTotal: 0,
  },

  // 内部购物车 Map（不存 data 避免 setData 性能问题）
  _cartMap: {},

  onLoad: function (options) {
    if (options.chef_id) {
      this.setData({ chefId: options.chef_id });
      this._loadChef(options.chef_id);
    }
    // 恢复已有选菜缓存（如果从预约表单返回）
    var savedCart = wx.getStorageSync('cah_cart_' + (options.chef_id || ''));
    if (savedCart) {
      try {
        this._cartMap = JSON.parse(savedCart);
        this._syncCart();
      } catch (e) { /* ignore */ }
    }
  },

  onShareAppMessage: function () {
    var chef = this.data.chef;
    return {
      title: chef ? (chef.name + ' · 大厨到家预约') : '大厨到家',
      path: '/pages/chef-at-home/chef-detail/chef-detail?chef_id=' + this.data.chefId,
    };
  },

  // ─── 加载大厨详情 ───

  reload: function () {
    this.setData({ loadError: false, loading: true });
    this._loadChef(this.data.chefId);
  },

  _loadChef: function (chefId) {
    var self = this;
    api.txRequest('/api/v1/trade/chef-at-home/chefs/' + encodeURIComponent(chefId))
      .then(function (data) {
        self.setData({
          chef: data,
          loading: false,
          signatureDishes: data.signature_dishes || [],
        });
        self._loadMenu(chefId);
        self._loadReviews(chefId);
      })
      .catch(function (err) {
        console.warn('[chef-detail] loadChef failed, using mock', err);
        var mockChef = MOCK_CHEFS[chefId] || MOCK_CHEFS['mock-chef-001'];
        self.setData({
          chef: mockChef,
          loading: false,
          signatureDishes: mockChef.signature_dishes || [],
        });
        self._loadMenu(chefId);
        self._loadReviews(chefId);
      });
  },

  // ─── 加载菜单 ───

  _loadMenu: function (chefId) {
    var self = this;
    self.setData({ loadingMenu: true });
    api.txRequest('/api/v1/trade/chef-at-home/menu?chef_id=' + encodeURIComponent(chefId))
      .then(function (data) {
        self._processMenu(data || []);
        self.setData({ loadingMenu: false });
      })
      .catch(function (err) {
        console.warn('[chef-detail] loadMenu failed, using mock', err);
        var mockDishes = MOCK_MENUS[chefId] || MOCK_MENUS['mock-chef-001'];
        self._processMenu(mockDishes);
        self.setData({ loadingMenu: false });
      });
  },

  _processMenu: function (dishes) {
    // 按 category_id 分组，生成分类Tab
    var catMap = {};
    var catOrder = [];
    dishes.forEach(function (dish) {
      var cid = dish.category_id || 'other';
      var cname = dish.category_name || '其他';
      if (!catMap[cid]) {
        catMap[cid] = { id: cid, name: cname, count: 0 };
        catOrder.push(cid);
      }
      catMap[cid].count += 1;
    });

    // 加一个"全部"分类在最前
    var categories = [{ id: 'all', name: '全部', count: dishes.length }];
    catOrder.forEach(function (cid) { categories.push(catMap[cid]); });

    var firstCat = categories[0] ? categories[0].id : 'all';
    this.setData({
      allDishes: dishes,
      menuCategories: categories,
      selectedCategory: firstCat,
    });
    this._filterDishes(firstCat);
  },

  // ─── 个人简介展开/收起 ───

  toggleBio: function () {
    this.setData({ bioExpanded: !this.data.bioExpanded });
  },

  // ─── 加载用户评价 ───

  _loadReviews: function (chefId) {
    var self = this;
    self.setData({ loadingReviews: true });
    api.txRequest('/api/v1/trade/chef-at-home/chefs/' + encodeURIComponent(chefId) + '/reviews?limit=10')
      .then(function (data) {
        var reviews = (data && data.items) ? data.items : (Array.isArray(data) ? data : []);
        self.setData({
          reviews: reviews,
          reviewsTotal: (data && data.total) || reviews.length,
          loadingReviews: false,
        });
      })
      .catch(function (err) {
        console.warn('[chef-detail] loadReviews failed, using mock', err);
        self.setData({
          reviews: MOCK_REVIEWS,
          reviewsTotal: MOCK_REVIEWS.length,
          loadingReviews: false,
        });
      });
  },

  // ─── 分类切换 ───

  selectCategory: function (e) {
    var id = e.currentTarget.dataset.id;
    this.setData({ selectedCategory: id });
    this._filterDishes(id);
  },

  _filterDishes: function (categoryId) {
    var all = this.data.allDishes;
    var result = categoryId === 'all'
      ? all
      : all.filter(function (d) { return d.category_id === categoryId; });
    this.setData({ filteredDishes: result });
  },

  // ─── 购物车操作 ───

  addDish: function (e) {
    var dish = e.currentTarget.dataset.dish;
    var id = dish.id;
    if (!this._cartMap[id]) {
      this._cartMap[id] = {
        id: dish.id,
        name: dish.name,
        price_fen: dish.price_fen,
        quantity: 0,
      };
    }
    this._cartMap[id].quantity += 1;
    this._syncCart();
    this._saveCartCache();
  },

  removeDish: function (e) {
    var id = e.currentTarget.dataset.id;
    if (!this._cartMap[id] || this._cartMap[id].quantity <= 0) return;
    this._cartMap[id].quantity -= 1;
    if (this._cartMap[id].quantity === 0) {
      delete this._cartMap[id];
    }
    this._syncCart();
    this._saveCartCache();
  },

  clearCart: function () {
    this._cartMap = {};
    this._syncCart();
    this._saveCartCache();
    this.setData({ cartExpanded: false });
  },

  _syncCart: function () {
    var map = this._cartMap;
    var list = [];
    var totalCount = 0;
    var totalPrice = 0;
    Object.keys(map).forEach(function (id) {
      var item = map[id];
      if (item.quantity > 0) {
        list.push(item);
        totalCount += item.quantity;
        totalPrice += item.price_fen * item.quantity;
      }
    });
    this.setData({
      selectedDishes: list,
      totalDishCount: totalCount,
      totalDishPrice: Math.round(totalPrice / 100),
    });
  },

  _saveCartCache: function () {
    try {
      wx.setStorageSync('cah_cart_' + this.data.chefId, JSON.stringify(this._cartMap));
    } catch (e) { /* ignore */ }
  },

  // 模板辅助：获取某菜品数量（WXML不支持直接访问对象key，用computed近似处理）
  // 实际通过 selectedDishes 列表渲染步进器数量
  _getDishQty: function (dishId) {
    return this._cartMap[dishId] ? this._cartMap[dishId].quantity : 0;
  },

  // ─── 购物车面板展开/收起 ───

  toggleCartPanel: function () {
    this.setData({ cartExpanded: !this.data.cartExpanded });
  },

  // ─── 跳转预约表单 ───

  goToBooking: function () {
    var chef = this.data.chef;
    if (!chef) return;

    // 将已选菜单写入草稿，供 chef-booking 读取
    var draft = wx.getStorageSync('chef_at_home_draft') || {};
    draft.chef_id = chef.id;
    draft.chef_name = chef.name;
    draft.chef_title = chef.title;
    draft.base_fee_fen = chef.base_fee_fen || 0;
    draft.dishes = this.data.selectedDishes;
    draft.dish_total_fen = this.data.selectedDishes.reduce(function (sum, d) {
      return sum + d.price_fen * d.quantity;
    }, 0);
    wx.setStorageSync('chef_at_home_draft', draft);

    wx.navigateTo({
      url: '/pages/chef-at-home/chef-booking/chef-booking?chef_id=' + encodeURIComponent(chef.id),
    });
  },
});
